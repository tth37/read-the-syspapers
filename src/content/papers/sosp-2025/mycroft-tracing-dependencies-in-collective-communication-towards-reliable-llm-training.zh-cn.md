---
title: "Mycroft: Tracing Dependencies in Collective Communication Towards Reliable LLM Training"
oneline: "Mycroft 在 NCCL 内记录 Coll-level 通信进度、抽样少量 rank，并重建依赖链，从而在秒级定位 LLM 训练中的 hang 和 fail-slow。"
authors:
  - "Yangtao Deng"
  - "Lei Zhang"
  - "Qinlong Wang"
  - "Xiaoyun Zhi"
  - "Xinlei Zhang"
  - "Zhuo Jiang"
  - "Haohan Xu"
  - "Lei Wang"
  - "Zuquan Song"
  - "Gaohong Liu"
  - "Yang Bai"
  - "Shuguang Wang"
  - "Wencong Xiao"
  - "Jianxi Ye"
  - "Minlan Yu"
  - "Hong Xu"
affiliations:
  - "The Chinese University of Hong Kong"
  - "ByteDance"
  - "ByteDance Seed"
  - "Harvard University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764848"
tags:
  - llm-training
  - observability
  - rdma
  - gpu
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mycroft 把 Coll-level tracing 加到 NCCL 里，让在线 LLM 训练不必等到 NCCL timeout 才开始排障。它抽样少量 rank，记录 flow-level 和 chunk-level 进度，再用依赖违例把 hang 或 fail-slow 缩到可疑的 rank、GPU、NIC 路径或通信 flow。

## 问题背景

混合并行 LLM 训练会把一条慢 collective 放大成整集群空转。gray failure 会让作业停住却没有明显日志，fail-slow 则让作业继续运行但吞吐明显下滑。由于 DP、PP 和 TP 组相互嵌套，最早出问题的 rank 很快就会被后续等待者淹没掉。

作者认为现有工具看错了层级。Op-level 工具只能看到 collective 晚了，看不到内部原因；Kernel-level tracing 很细，但代价高，而且仍然离通信语义太远；RDMA 计数器只能看网络，看不到发送端 GPU 是否就绪、接收端是否阻塞。于是运维常常只能等 NCCL timeout 后盲目重启。论文的观点是，真正缺失的是 collective library 内部的可观测性。

## 核心洞察

Mycroft 的关键想法是用 Coll-level tracing 记录“能暴露依赖违例的进度状态”，而不是追完整的 CUDA timeline。它在 flow level 上跟踪单条网络路径，在 chunk level 上记录 GPU 准备了多少数据、RDMA 发出了多少、又真正完成了多少。

这些计数器已经足以区分几类常见根因。`GPU_ready > RDMA_transmitted` 更像发送端 RDMA 落后；`RDMA_transmitted > RDMA_done` 更像网络或接收端阻塞；如果三个计数器同步推进，但某个 rank 总是更晚开始或结束，那更像 GPU 或主机侧计算拖慢了通信。再加上异常会在几百毫秒内沿依赖链扩散，常驻触发只看少量抽样 rank 就足够了。

## 设计

Mycroft 在 NCCL 2.21.5 的 proxy-thread critical path 上插桩。它新增不到十个 tracepoint，输出两类日志：每个 collective 完成时写 completion log；collective 执行期间每 100 ms 写一次 real-time state log。日志里除了操作元数据，还包括 `GPU_ready`、`RDMA_transmitted`、`RDMA_done`，以及 GPU、channel、QP 和通信组标识。每台主机把数据写入 512 MB shared-memory 环形缓冲区，再由只读 agent 通过 Kafka 异步上传到云端数据库。

在线管线分两段。触发器通常每个 DP group 抽一个 rank、总数不超过十个；如果样本不再完成 collective，或者吞吐减半、操作间隔翻倍，就触发异常。随后，根因分析只回捞最近一个短窗口，重建全局状态机，找出受影响的通信组，再检查哪个 rank 或 flow 进度最少、开始或结束最晚。Mycroft 还会结合 `py-spy` 和 PyTorch Flight Recorder，快速排除 dataloader 卡住、某个 rank 没发起 CollOp、或 process-group 死锁这类非 CCL 问题。

## 实验评估

论文同时给出了受控注入实验和生产部署评估。实验平台是四台机器上的 32 张 A100-80GB GPU，机器内用 NVLink 和 PCIe，机器间每台配四张 ConnectX-6 RNIC；工作负载是 Megatron-LM GPT，配置为 TP=8、PP=2、DP=2。作者注入了七类问题：NIC shutdown、NIC bandwidth limit、PCIe downgrading、GPU power limit、background GPU computation、background network traffic，以及 NCCL send proxy 延迟。Mycroft 成功定位了这七类异常。不同问题会留下不同依赖特征：比如 NIC shutdown 时异常 rank 最先停止产生日志；NIC 带宽受限时会出现 `GPU_ready > RDMA_transmitted`；background traffic 则表现为 `GPU_ready = RDMA_transmitted` 但 `RDMA_done` 落后。七类注入里，从异常开始到诊断完成都不超过 13 秒。

开销也比较低。Mycroft 在 NCCL tests 上的带宽几乎和 baseline 重合，而 NPKit 会把 bus bandwidth 压到约三分之一；在 Megatron 训练中，平均 iteration time 只从 1116 ms 增加到 1119 ms。日志量方面，Mycroft 每台机器每次迭代约 46.8 KB，而 Nsight 只开 CUDA tracing 也约 15 MB。生产环境里，Mycroft 在 2024 年 11 月和 12 月检测到 13,221 次中断，执行了 1,253 次根因分析，并在 705 个案例中定位到单个问题 flow；论文还报告 90% 的异常能在 15 秒内发现，所有根因分析都能在 1 分钟内完成。不过作者也明确说明，生产环境缺少完整标注，因此这些结果更像运维证据，而不是完整的精确率/召回率评测。

## 创新性与影响

相对于 GREYHOUND，Mycroft 分析的是 collective 内部的依赖传播，而不只是 collective 时间戳变慢。相对于 Evolution of Aegis，它把 RDMA 可见进度和 GPU 侧通信状态结合起来。相对于 Nsight 或 NPKit，它用更贴近通信语义的表示替代完整 kernel timeline。

因此，这篇论文的贡献不是新的 collective 算法，而是新的可观测性边界。Coll-level tracing 给大规模 GPU 集群运维提供了一个介于粗粒度日志和高成本细粒度 trace 之间的中间层。

## 局限性

Mycroft 只看到通信层。它不能直接表达合理的 compute-communication overlap、合法负载不均，或更深的应用语义，因此阈值只能是启发式的；论文里使用了“吞吐下降 50%”“某个 rank 晚 1 秒以上开始或结束”这类规则。

实现上，它目前也依赖 NCCL，而且很多时候只能把范围缩小到可疑 GPU 或 flow，而不能自己证明最终的硬件故障。论文中的案例在这一步之后仍需要 `py-spy`、Flight Recorder 或离线检查。后端还是集中式的，在 10,000 GPU 规模下每天约产生 3 TB trace 数据，继续放大规模可能需要去中心化。

## 相关工作

- _Dong et al. (NSDI '25)_ — Evolution of Aegis 主要用 RDMA 层和运行时信号诊断 AI 训练故障，而 Mycroft 进一步加入 collective library 内部状态来解释传播链。
- _Wu et al. (ATC '25)_ — GREYHOUND 主要从 collective 的时间行为识别 fail-slow，而 Mycroft 深入到 flow-level 和 chunk-level 依赖来做定位。
- _Deng et al. (NSDI '25)_ — Minder 用带外机器信号检测分布式训练中的故障节点，而 Mycroft 直接给通信路径做插桩。
- _Xiong et al. (ATC '24)_ — SuperBench 通过基准程序主动验证 GPU 节点，而 Mycroft 面向真实训练作业运行时出现的故障与慢化。

## 我的笔记

<!-- 留空；由人工补充 -->

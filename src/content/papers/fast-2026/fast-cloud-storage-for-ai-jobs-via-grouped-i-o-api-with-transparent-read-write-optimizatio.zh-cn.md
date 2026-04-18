---
title: "Fast Cloud Storage for AI Jobs via Grouped I/O API with Transparent Read/Write Optimizations"
oneline: "AITURBO 通过 grouped read/write API、主机 DRAM 暂存和 compute fabric 广播，让云存储透明地去重并重排 AI checkpoint 与 KVCache I/O。"
authors:
  - "Yingyi Hao"
  - "Ting Yao"
  - "Xingda Wei"
  - "Dingyan Zhang"
  - "Tianle Sun"
  - "Yiwen Zhang"
  - "Zhiyong Fu"
  - "Huatao Wu"
  - "Rong Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "Huawei Cloud"
conference: fast-2026
category: ai-era-storage
tags:
  - storage
  - disaggregation
  - datacenter
  - llm-training
  - llm-inference
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`AITURBO` 把 AI 存储流量看成一种 grouped collective I/O，而不是彼此独立的文件访问。它的 grouped API 让存储层能够识别重复 payload、把数据暂存到空闲主机 DRAM，并在 storage fabric 成为瓶颈时借助更快的 compute fabric 转发数据。对 checkpoint write，它比云厂商现有通用存储路径快 `3.9-58.8x`，在存在跨节点重复内容时又能比 `GEMINI` 最高快 `5.9x`；对 KVCache read，它相对 `Mooncake` 将平均 TTFT 降低了 `23%`。

## 问题背景

论文先给出一个非常现实的云侧观察：在华为云的一个本地数据中心里，AI 作业已经消耗了超过 `10%` 的云存储带宽。最占带宽的几类操作都是 bulk transfer，包括训练中的 checkpoint write、autoscaling 或恢复时的 checkpoint read，以及 LLM serving 里的 KVCache read。这些 I/O 的单次规模往往从几十 MB 到数百 GB，因此真正决定端到端时间的不是元数据，而是带宽。

但在现代云的 compute-storage disaggregated architecture 下，带宽恰恰最难便宜提升。计算节点访问存储节点依赖较慢的 storage fabric，而 XPU 之间却有更快的 compute fabric。直接购买更多后端存储带宽不仅昂贵，还无法绕过每个计算节点 storage NIC 所形成的前端上限；作者给出的例子是，将 provisioned bandwidth 从 `1.6 GB/s` 提高到 `80 GB/s`，单位 GB 成本会上涨 `16x`。应用层优化也不令人满意。`Megatron` 大约拿出四分之一代码处理 checkpoint I/O，但依旧没有对云存储拓扑的全局视角。

问题还在于存储层看不见 group 语义。分布式训练里所有 rank 会一起写 checkpoint shard；扩容出来的多个 inference job 会一起读取同一个模型；agentic serving 中多个请求又可能同时需要共享前缀对应的 KVCache block。若存储系统每次只看到一个 `getfile` 或 `putfile`，它就既看不到重复内容，也生成不了真正全局最优的传输计划。

## 核心洞察

这篇论文最重要的主张是：云存储应该暴露一个极简的 grouped-I/O 抽象，再由存储层统一完成那些今天由框架各自实现的优化。一旦应用告诉存储“哪些客户端正共同参与这次读写”，存储服务就能同时知道哪些 payload 重复、真正的瓶颈链路在哪里，以及什么时候应该用更快的 XPU-to-XPU fabric 替代重复的 storage transfer。

这里优化的目标不是孤立追求 storage throughput，而是降低 AI 作业在关键路径上感受到的 storage overhead。对 checkpoint write 来说，很多场景下数据只要进入复制过的 DRAM buffer，训练就可以先恢复，真正持久化稍后完成即可。对 grouped read 来说，从存储中取一份数据，再通过 compute fabric 广播给其他消费者，往往优于让每个 XPU 都独立打到存储。也就是说，`AITURBO` 把云存储变成了 AI 作业的 collective-I/O planner。

## 设计

`AITURBO` 在原有文件 API 上增加了 `group_getfile` 和 `group_putfile`。调用方式仍然是“读/写文件”，只是调用方还要说明参与本次操作的 group。对 grouped write，系统返回两个 future：一个表示数据已经进入 DRAM staging buffer，另一个表示数据已经被持久化到后端存储。这个拆分很适合周期性 checkpoint，因为很多时候“已经安全缓存在内存里”就足以让训练继续前进。

系统实现有三个关键部件：统一管理空闲 host DRAM 的 staging-buffer manager、负责 compute fabric 传输的 communicator，以及生成 read/write plan 的无状态 job controller。grouped write 分三步：识别重复 payload、把去重后的数据放入各节点 DRAM buffer、再从这些 buffer flush 回存储。去重基于 `BLAKE3` checksum，粒度从整文件到 `4 MB` chunk 都支持，而且计算足够快，论文给出的例子是 `1 GB` 文件在 `V100` 上只需 `7.8 ms`，而测试 CPU 上需要 `35.6 ms`。由于连续 checkpoint 的重复模式通常稳定，job controller 还会缓存 dedup metadata。

真正的核心是 planner。作者把 buffer placement 和 write-back 都建模成 bilinear programming，目标是最小化总完成时间，约束则包括源端带宽、目的端带宽、点对点链路带宽、复制数以及 DRAM 容量。求解时固定总时间变量 `t`，把问题化成线性可行性检查，再不断缩小搜索区间。对一个 `38B` 模型、`64` 个 XPU 的训练 trace，即使用单线程 Python solver，也能在 `4` 秒内得到计划。读路径则做相反方向的优化：只从存储中取每个重复 chunk 或文件的一份副本，再通过 compute fabric 沿 `BlitzScale` 式串行链路广播给其他消费者。系统还支持跨计算节点的 distributed caching、tensor-native file format，以及直接建立点对点 RDMA 连接以绕开 `NCCL` communicator 初始化开销。

## 实验评估

实验运行在两套最多 `64` 个 XPU 的集群上，分别包含 `Ascend 910B` 和 `NVIDIA A800`。每个计算节点有 8 个 XPU、`192` 个 CPU 核、`1.5 TB` 主机 DRAM，以及一个 `100 Gbps` storage NIC；作业最多可获得 `30 GB/s` 的后端存储带宽。这套环境与论文想论证的 disaggregated storage 瓶颈高度一致。

对 checkpoint write，作者评测了 `1.5B`、`13B` 和 `38B` 三种模型，并分别在启用和不启用 `ZeRO` 的情况下比较 `Megatron + SFST URBO`、`GEMINI` 与 `AITURBO`。`AITURBO` 相比 `Megatron + SFST URBO` 最高快 `58x`，而在存在跨节点重复内容时，相比 `GEMINI` 最高快 `5.9x`。消融实验也说明收益来源很清楚：仅 deduplication 一项，就能在有重复 checkpoint 内容的配置下再带来 `4.3-47.2%` 的收益；显式 write plan 又能额外降低最多 `76%` 的时间。

checkpoint read 更能体现 grouped read 的价值。对于 `Qwen 72B` 和 `QwQ 32B`，在还没有任何缓存副本之前，所有系统都同样受 storage bandwidth 限制：当 provisioned bandwidth 只有 `1 GB/s` 时，在 `8` 个 XPU 上读取 `135 GB` 的 `Qwen 72B` checkpoint 都需要 `173` 秒。但只要第一份 checkpoint 已经读入，`AITURBO` 就能沿 compute fabric 快速广播。论文给出的数字是：把缓存副本分发到 `64` 个 XPU 上部署 `Qwen 72B` 只需 `2.25` 秒，而调优后的 `ServerlessLLM` 仍需要 `1,384` 秒沿着较慢的存储路径逐步分发。

KVCache 实验规模更小，但故事一致。作者在 `8` 个 XPU 上用 `Qwen-14B` 回放 `Qwen-Bailian` trace，把 `Mooncake` 的 storage read path 替换成 `AITURBO`，平均 TTFT 降低了 `23%`。论文关于工程成本的说法也可信：在 `Megatron` 里接入 `AITURBO` 只额外需要 `286` 行代码，而原框架已有的应用层 I/O 优化总共是 `2,228` 行；group coordination overhead 在 `64` 个 XPU 上最高也只有 `45 ms`。

## 创新性与影响

相对于 _Wang et al. (SOSP '23)_，`AITURBO` 把 `GEMINI` 那种 in-memory checkpointing 的直觉下沉到存储层，并在其上增加透明去重与拓扑感知的 read/write planning。相对于 _Wan et al. (NSDI '25)_，它追求与 `ByteCheckpoint` 类似的 checkpoint I/O 优化目标，但把逻辑从每个训练框架里移出来，做成同样能服务推理读路径的存储 API。相对于 _Qin et al. (FAST '25)_ 和 _Zhang et al. (OSDI '25)_，它又把 KVCache 系统与 autoscaling broadcast 的一些思想抽象成更通用的 grouped-I/O substrate。

因此，这篇论文更像一种系统机制，而不只是某个框架的 tuned implementation。它给云厂商提供了一种不必出售更昂贵存储 tier、也能利用空闲 DRAM 与 compute fabric 带宽的方法；同时也让框架开发者只需要面对更小的集成面。论文已经在华为云生产训练任务中落地，这使得它的系统影响力主张更可信。

## 局限性

论文明确承认，`AITURBO` 主要服务于 bulk transfer。若工作负载以小粒度读写为主，那么整套设计假设的“瓶颈是带宽而非元数据或控制开销”就不成立，收益会很有限。它的优势还依赖于存在可利用的空闲 host DRAM 与未被完全打满的 compute fabric；若这两类资源已经很紧张，核心收益就会明显缩小。

grouped API 在语义上也不是零成本的。应用需要知道这次操作的参与 group，而论文承认这对动态推理比对固定训练更难；`Mooncake` 的实验因此没有完整使用 grouped API。隔离机制目前也只依赖现成硬件 QoS，而 buffered-write 模式在 `future_1` 完成前依旧存在持久性折中。这些工程选择很合理，但也限制了设计的普适性。

## 相关工作

- _Wang et al. (SOSP '23)_ — `GEMINI` 通过 in-memory checkpointing 做快速故障恢复，而 `AITURBO` 在此基础上进一步把透明去重和存储层 read/write planning 统一进 grouped I/O。
- _Wan et al. (NSDI '25)_ — `ByteCheckpoint` 同样优化 checkpoint 流量，但它需要框架级支持；`AITURBO` 则通过 grouped API 把优化边界下沉到存储服务。
- _Qin et al. (FAST '25)_ — `Mooncake` 是面向 LLM serving 的 KVCache-centric 架构，而 `AITURBO` 是更通用的云存储底座，同时加速 checkpoint read、checkpoint write 和 KVCache miss。
- _Zhang et al. (OSDI '25)_ — `BlitzScale` 展示了 host caching 加广播的快速大模型 autoscaling；`AITURBO` 复用类似直觉，但把它作为更一般 grouped-read planner 的一个阶段。

## 我的笔记

<!-- 留空；由人工补充 -->

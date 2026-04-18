---
title: "PhoenixOS: Concurrent OS-level GPU Checkpoint and Restore with Validated Speculation"
oneline: "PhoenixOS 从 GPU kernel 启动参数推测访问集合并在运行时校验，据此把并发 checkpoint/restore 做到 GPU 进程上，显著缩短停顿。"
authors:
  - "Xingda Wei"
  - "Zhuobin Huang"
  - "Tianle Sun"
  - "Yingyi Hao"
  - "Rong Chen"
  - "Mingcong Han"
  - "Jinyu Gu"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "National University of Singapore"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764813"
code_url: "https://github.com/SJTU-IPADS/PhoenixOS"
tags:
  - gpu
  - fault-tolerance
  - kernel
  - serverless
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PhoenixOS 把 GPU 进程的并发 OS 级 checkpoint/restore 做成了一个透明系统：它先从 kernel 启动参数推测哪些 GPU buffer 会被读写，再用轻量级二进制插桩去校验推测结果。拿到这层访问信息后，系统就能把 CPU 世界里的 copy-on-write、recopy 和 on-demand restore 协议搬到 GPU 上，从而显著减少故障恢复、迁移和 GPU serverless 冷启动中的停顿时间。

## 问题背景

OS 级 checkpoint/restore 的价值在于透明性。云平台可以迁移黑盒 GPU 作业、在故障后恢复进程，或者直接重启一个已经“预热”过的 GPU 服务，而不必要求 PyTorch、Megatron 或其他框架单独实现自己的恢复逻辑。问题在于，现有 GPU checkpoint 系统基本都是 stop-the-world：先停住 CPU 和 GPU，再把 CPU 状态与几十 GB 的 GPU buffer 拷走，恢复时还要重新创建 GPU context，整个过程应用都在等待。

这类停顿对推理和训练都很伤。论文给出的例子里，先前 OS 级 GPU C/R 恢复一个 Llama2-13B 推理进程需要 6.2 秒，远高于它的 time-to-first-token；而训练场景里，checkpoint 时间甚至可能占到一次 iteration 的 46-87%。传统 CPU 并发 C/R 技术也很难直接套到 GPU 上，因为 CPU 有页表 dirty bit、present bit 和 OS 介导的数据路径，GPU 却既不暴露廉价的脏数据跟踪机制，也没有天然的 copy-on-write 支持。若想让并发 checkpoint 正确，OS 必须知道并发执行期间到底读了哪些数据、写了哪些数据，否则运行中的 kernel 可能覆盖尚未 checkpoint 的内容，或在 restore 尚未完成时读到不一致的数据。

## 核心洞察

论文最关键的判断是：GPU 执行在指令层面对 OS 来说确实是黑盒，但在提交边界上并不是。GPU 工作是通过细粒度 API 调用提交的，而这些 API 的启动参数通常就编码了 kernel 将访问的 buffer。于是，系统不必依赖硬件 dirty bit，也不必对任意 CUDA 代码做完全静态分析，而是可以从 API 语义和参数类型出发，先推测每个 kernel 的读写集合。

当然，只有推测还不够，所以 PhoenixOS 又加入了运行时校验。对于 opaque kernel，它会生成一个带插桩的 twin kernel，在执行每条内存写入前检查目标地址是否落在推测到的 buffer 中，并把误判报告给系统。只要这个访问集合在绝大多数情况下是正确的，PhoenixOS 就能把经典 CPU 并发协议软件化移植到 GPU：用 soft copy-on-write 隔离写入、用 recopy 追平新鲜状态、用按需 restore 避免一开始就把所有 GPU 数据恢复完。这里真正的新意不是“先猜再验”，而是 buffer 级推测对现代 GPU 工作负载已经足够有用，因为今天的 AI 框架通常以 tensor 为单位分配 buffer，而 kernel 也经常按整个 buffer 读写。

## 设计

PhoenixOS 由三部分组成：面向用户的 checkpoint/restore/migrate 命令行工具、通过 `LD_PRELOAD` 插入 GPU 软件栈以拦截 GPU API 的 frontend library，以及同时管理 CPU 状态与 GPU 状态的 backend。CPU 侧状态交给 `CRIU`，GPU 侧则由 PhoenixOS 自己处理；checkpoint 既可以落到本地内存/存储，也可以通过 RDMA 传到远端机器。

在写集合跟踪上，PhoenixOS 把 GPU API 分成四类。内存拷贝 API、通信 kernel，以及像 cuBLAS 这类语义已知的库调用，都可以直接从规范推出写集合。最难的是通过 `cudaLaunchKernel` 提交的 opaque kernel。PhoenixOS 的做法是，把启动参数与进程已分配的 GPU buffer 逐一比对，并结合 kernel signature 过滤参数，只重点关注可变指针；对看不见定义的 struct 参数，则保守地把其中每个 8 字节块都当成潜在 buffer 指针。验证逻辑插在 PTX 层，一旦发现误判，就回退到安全路径。

并发 checkpoint 本身有两套协议。soft copy-on-write 会先做一次很短的 quiesce，停住 CPU 与 GPU，然后开始后台拷贝。如果后续某个 kernel 要写一个尚未 checkpoint 完的 buffer，PhoenixOS 就先把该 buffer 复制到备用 GPU 内存里，让 checkpoint 继续读取旧版本，而应用执行切换到新版本。若 GPU 空闲内存不足，系统可以短暂阻塞，或者退回经由主机内存完成复制。soft recopy 则走另一条路：并发拷贝过程中把那些“已经被拷过、后来又被写过”的 buffer 记成 dirty，等主拷贝结束后再次 quiesce，只重拷 dirty 集合，从而得到与最新时刻一致的 checkpoint。为了让 recopy 的 dirty 集更小，PhoenixOS 先拷 CPU 数据、再拷 GPU 数据，缩短 GPU 侧的脏窗口；同时把 checkpoint 传输切成 4 MB 小块，让应用自己的 DMA 传输可以抢占 checkpoint，避免共用 DMA engine 时应用被饿死。

restore 也复用了同一套思路，只是把不可变指针参数也纳入推测，以推断 kernel 会读取哪些 buffer。若执行即将触及一个尚未恢复完成的 buffer，kernel 会先等待 PhoenixOS 把该 buffer 按需拷回。除此之外，restore 的另一个大瓶颈是 GPU context 创建。论文显示，这部分开销和数据拷贝本身差不多重，因此 PhoenixOS 额外维护了一个 daemon 侧的 context pool，预先创建好 CUDA、cuBLAS 和 NCCL context，恢复时直接分配给目标进程，以绕过这道同步屏障。

## 实验评估

评测平台是 8 卡 NVIDIA A800 服务器，配双路 Xeon Gold 6348、1 TB DRAM、机内 NVLink 和机间 100 Gbps RDMA。工作负载以 AI 为主，覆盖 ResNet-152M、PPO-336M、Stable Diffusion 1B、Llama2-13B 和 Llama3.3-70B，并包含单卡和多卡场景。主要基线是作者在自己代码库里精调过的 Singularity；`cuda-checkpoint` 作为更慢的 stop-the-world 参考。

主结果基本支撑了论文的中心论点。在容错场景里，PhoenixOS 明显缩短了 checkpoint stall；对 Llama2-13B 训练来说，checkpoint 开销从 3.2 秒降到 185 ms，哪怕该作业有 72 GB 的 GPU 状态要处理。按论文设定的“每小时一次 GPU 故障”模型，PhoenixOS 可以把 checkpoint 频率提高到每小时 279 次，而 Singularity 的最优点只有 67 次，因此不同训练任务上的 wasted GPU time 总共可减少 22-86%。在 live migration 上，Llama2-13B 训练和 Llama3.3-70B 推理的 downtime 分别降到 3.3 秒和 3.7 秒，而 Singularity 分别是 10.2 秒和 12.35 秒。对 serverless 冷启动，论文给出 Llama2-13B 推理 622 ms 的端到端启动时间，平均而言比 `cuda-checkpoint` 快 24 倍、比 Singularity 快 16 倍。

更细的分析也比较关键。runtime validator 的开销只有 1-12%，而且在被评测的 AI 工作负载中，真正需要插桩验证的 kernel 只占一部分。作者还把方法扩展到 Rodinia、Parboil、vLLM、TVM、FlashInfer 做可行性研究：现代 AI 工作负载里没有遇到 speculation failure，只有 Rodinia 里一个老旧 kernel 失败，并带来了 20 个失败实例。这个结果说明该方法对今天的 ML 风格 GPU 软件很有说服力，但对历史遗留 CUDA 程序未必同样稳健。

## 创新性与影响

PhoenixOS 与以往 GPU checkpoint 工作的最大区别，在于它同时追求并发 checkpoint 和并发 restore，而且目标是生产级 GPU、无应用改写。相比 _GPU Snapshot_ 这类依赖硬件 dirty tracking 的工作，它把硬件假设换成了“软件推测 + 运行时校验”。相比只关注快速启动的 restore-only 系统，它又把更难做的 checkpoint 一侧也解决了。因此，它真正贡献的是一种新的系统机制：validated speculation 充当了 GPU 世界里缺失的可观测层，使 CPU 时代的经典 C/R 协议能重新在 GPU 上成立。

如果这类设计被采用，最直接的受益者会是管理 GPU 集群、训练作业和冷启动敏感推理服务的基础设施团队。更广义地说，这篇论文给出的启发是：当加速器没有暴露 OS 想要的硬件钩子时，API 语义加运行时校验有时足以恢复出“够用的结构”，从而重新启用那些本来只属于传统 OS 的技巧。

## 局限性

最主要的局限仍然是：正确性虽然最终由回退路径兜底，但快路径依赖于“推测大多数时候别出错”。PhoenixOS 会验证写集合，并在失败时安全回退；只是这个回退相当直接，checkpoint 失败就重做 stop-the-world，restore 失败就回滚后做 stop-the-world restore。这样当然保住了正确性，但也说明性能收益高度依赖工作负载的规律性。

另一个问题是 opaque kernel 的跟踪粒度只有 buffer 级。如果一个 kernel 只写大 buffer 的小区域，PhoenixOS 仍可能把整块 buffer 当成脏数据处理，从而增加 copy-on-write 或 recopy 的额外工作。论文强调 AI 框架通常按 tensor 细粒度分配 buffer，因此这个问题不算严重，但 Rodinia 的结果已经表明这个假设并不普适。最后，系统实现明显依赖 NVIDIA 软件栈，评测也几乎都集中在 AI 任务上；多进程全局 quiesce 仍需用户给 hint，而 context pool 方案在 restore 后会引入 IPC 开销，论文报告该模式下最高可达 9%。

## 相关工作

- _Lee et al. (ICS '19)_ — _GPU Snapshot_ 依赖硬件支持的 dirty tracking 与 checkpoint offloading；PhoenixOS 则在现有量产 GPU 上用软件推测和运行时校验实现并发 C/R。
- _Bai et al. (OSDI '20)_ — _PipeSwitch_ 关注深度学习任务切换时的流水化 context switching，而 PhoenixOS 提供的是对未修改 GPU 进程透明的 OS 级 checkpoint/restore。
- _Du et al. (ASPLOS '20)_ — _Catalyzer_ 通过 initialization-less booting 加速 CPU 侧 serverless 启动；PhoenixOS 则恢复完整 GPU 进程状态，并把 restore 与 GPU 执行重叠起来。
- _Yang et al. (SoCC '24)_ — _gCROP_ 主要关注按需和并行 GPU restore；PhoenixOS 则把 concurrent checkpoint 也一并支持，并且目标是在 NVIDIA GPU 上无需应用改写地工作。

## 我的笔记

<!-- empty; left for the human reader -->

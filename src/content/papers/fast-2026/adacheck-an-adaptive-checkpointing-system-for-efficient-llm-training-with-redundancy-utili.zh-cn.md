---
title: "AdaCheck: An Adaptive Checkpointing System for Efficient LLM Training with Redundancy Utilization"
oneline: "AdaCheck 建模跨并行策略与迭代的 tensor 级冗余，只保存不可省略的状态与梯度增量，把 LLM 训练中的逐步检查点做成可行方案。"
authors:
  - "Weijie Liu"
  - "Shengwei Li"
  - "Zhiquan Lai"
  - "Keshi Ge"
  - "Qiaoling Chen"
  - "Peng Sun"
  - "Dongsheng Li"
  - "Kai Lu"
affiliations:
  - "National Key Laboratory of Parallel and Distributed Computing, College of Computer Science and Technology, National University of Defense Technology"
  - "Nanyang Technological University"
  - "Shanghai AI Laboratory"
conference: fast-2026
category: ai-era-storage
code_url: "https://github.com/HPDL-Group/Merak"
tags:
  - llm-training
  - fault-tolerance
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

AdaCheck 不把 checkpoint 优化看成单纯的 I/O 流水线问题，而是先回答“哪些状态真的必须保存”。它先在离线阶段识别任意 LLM 并行计划下不可省略的参数与 optimizer 状态，再在在线阶段用 gradient delta 继续压缩 checkpoint。对 dense 与 sparse 模型，AdaCheck 将 checkpoint 大小降低 `6.00–896×`，实现逐 iteration checkpoint，而训练吞吐几乎没有额外开销。

## 问题背景

论文的出发点很直接：大规模 LLM 训练运行时间长、失败频繁，而 bulk-synchronous recovery 会浪费大量算力。作者引用了 `LLaMA 3.1` 在 `16K` GPU 上训练 `54` 天的例子，其中发生了 `419` 次失败，总计浪费大约 `2M` GPU 小时。Checkpoint 因此不是附属优化，而是训练效率的核心组成部分。

现有系统优化错了边界。像 `CheckFreq` 这样的异步系统会减少 I/O 停顿，但仍然假设至少要把一个完整模型副本写入 persistent storage。像 `GEMINI` 这样的 in-memory 方案会把 checkpoint 发到 remote CPU memory，却仍然默认每个 worker 的本地状态都值得保存。对同时结合 `DP`、`ZeRO`、model parallelism、expert parallelism，甚至 auto-parallelizer 生成的不规则并行计划的训练来说，这会带来大量不必要的 checkpoint 流量。

而且，简单的副本计数并不安全。恢复是在 worker 或 node 级别发生的，因此副本分布位置会影响可恢复性；参数与 optimizer states 也可能拥有不同的冗余模式。如果只凭“有没有副本”来删减 checkpoint，结果可能更小，却无法恢复训练。

## 核心洞察

AdaCheck 的核心判断是：checkpoint 必要性是 tensor 分布属性，而不是整个模型的整体属性。它定义了 `tensor redundancy`，显式记录某个 tensor 的副本位于哪些 worker、对应哪些 tensor 索引，并据此把状态分成 full redundancy、partial redundancy 和 no redundancy。因为抽象落在 tensor 粒度上，所以 dense transformer、sparse `MoE` 和 auto-generated parallelism 都能用同一套逻辑处理。

第二个洞察来自时间维度。对 mixed-precision 训练的相邻迭代来说，checkpoint 之间真正需要保存的变化，往往是半精度梯度，而不是整套 optimizer state。只要系统已经知道哪些状态必须保留，就可以在很多情况下用 gradient delta 替代完整状态保存，把跨迭代冗余也变成收益来源。

## 设计

AdaCheck 分为 offline 和 online 两部分。Offline 阶段先判断哪些状态必须进入 checkpoint：系统先区分 full、partial 和 no redundancy，再把参数与其对应 optimizer state 的冗余结果取交集，并保留更保守的结论。它还支持用户指定 failure-tolerance factor `k`：副本跨越超过 `k` 个节点的状态可视为足够冗余，副本数不超过 `k` 的状态则必须保存。

为了低成本得到这些信息，AdaCheck 在训练启动时运行 redundancy detector。每个 worker 先对本地 tensor 求哈希，再只在训练中原本就会同步副本的 communication groups 内做比较，并用 ring-style 算法让通信与比较并发进行。系统还会对两个迭代的比较结果取交集，以过滤 hash collision 和瞬时相等。论文报告说，这个 detector 在 `128` 个 worker 上可在 `3` 分钟内完成。

Online 阶段则利用跨迭代冗余。在 mixed-precision Adam 训练里，参数占 `2M`，optimizer states 占 `12M`，完整 checkpoint 合计 `14M`。AdaCheck 在只需保留 optimizer state 或同时保留参数与 optimizer state 时，改为保存关联梯度，分别把代价降到 `1/6` 和 `1/7`。这些缩减后的 checkpoint 会写入 remote CPU memory，并按 model parallel 结构分组，从而尽量与正常训练重叠。为了避免恢复时重放过长的梯度链，AdaCheck 还在远端维护一个修改过的 CPU optimizer，使备份状态随着梯度到达而同步更新；non-blocking full checkpoint 则继续充当灾难性故障下的兜底路径。

## 实验评估

实验使用了两个集群：`32` 张 `A800 80G` GPU、训练网络 `800 Gbps` 的 datacenter 集群，以及 `128` 张 `RTX 3090`、训练网络 `100 Gbps` 的 commodity 集群。模型覆盖 `LLaMA-7B`、`LLaMA-30B`、`DeepSeek-V2-Lite`、`GPT-1.4B`、`GPT-7B` 和 `GPT-MoE`，并测试 `ZeRO`、`MiCS`、`EP` 与 `nnScaler` 生成的 auto-generated parallel plans。这一覆盖面与论文“跨训练布局自适应”的主张是匹配的。

最核心的结果是 checkpoint 大小的下降。相对 `CheckFreq` 和 `GEMINI`，AdaCheck 将 checkpoint 大小压缩了 `6.00–896×`。Ablation 进一步说明来源：仅 offline redundancy elimination，相对 `GEMINI` 就能缩小 `1.30–240×`；再叠加 online incremental 方法，最佳情况下还能再缩小 `7.09×`。更重要的是，AdaCheck 做到了逐 iteration checkpoint，并把 checkpoint 频率相对 `CheckFreq` 提高 `36.2–111×`，相对 `GEMINI` 提高 `1.46–3.64×`。

这些收益确实转化成了更低的故障代价。对 sparse 模型，平均每次故障浪费时间相对 `CheckFreq` 降低 `12.1–88.93×`，相对 `GEMINI` 降低 `1.73–4.51×`。训练期开销几乎可以忽略，而在更高的模拟故障率下，端到端 effective throughput 相对 `GEMINI` 最高还能提升 `1.12×`。需要保留的一点是，`GEMINI` 因为闭源只能由作者自行复现。

## 创新性与影响

AdaCheck 与已有工作的主要区别，是它把两类过去常被分开讨论的冗余合并起来利用。相对 `CheckFreq`，它改变了“什么状态必须 checkpoint”的定义，而不只是优化数据何时落盘。相对 `GEMINI`，它不仅利用 remote memory，还加入了 replica-aware 的状态裁剪与跨迭代的 gradient checkpoint。因此，这篇工作更像一个新机制，而不是单纯的工程优化。

它对大规模 LLM 训练框架、容错训练系统以及 auto-parallelizing 系统都很有意义，因为 checkpoint 逻辑不再需要为每一种并行布局单独手写。作者把原型集成进 `Merak` 并开源，也说明这套设计面向的是可复用的训练基础设施。

## 局限性

AdaCheck 只在训练开始时识别 redundancy pattern，因此若 parallel plan 动态变化，detector 很可能需要重跑。它的快速恢复在 simultaneous failures 超过组大小 `k` 时也变成概率性的，所以系统仍然需要 full checkpoint 兜底。最后，实验最多覆盖 `128` 张 GPU，而论文的动机来自 `1K–16K` GPU 训练，并且一个关键基线 `GEMINI` 还是作者自行复现。

## 相关工作

- _Mohan et al. (FAST '21)_ — `CheckFreq` 通过将 checkpoint I/O 与训练重叠来降低停顿，但仍然假设至少要把一个完整模型写入 persistent storage。
- _Wang et al. (SOSP '23)_ — `GEMINI` 把 checkpoint 发到 remote CPU memory 并利用训练网络带宽；AdaCheck 则进一步删除冗余状态，并使用 gradient-based incremental checkpointing。
- _Gupta et al. (EuroSys '24)_ — Just-in-time checkpointing 在故障发生后才利用已有副本构造 checkpoint；AdaCheck 则会预先保存 no redundancy 状态，因此不局限于纯副本式恢复。
- _Jiang et al. (NSDI '25)_ — `ByteCheckpoint` 优化的是 foundation model 的 checkpoint 流水线，而 AdaCheck 关注的是跨并行策略与跨迭代地最小化 checkpoint 内容本身。

## 我的笔记

<!-- 留空；由人工补充 -->

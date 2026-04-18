---
title: "Optimizing RLHF Training for Large Language Models with Stage Fusion"
oneline: "RLHFuse 把 RLHF 拆成 sample 级与 micro-batch 级子任务，再融合 generation/inference 与 Actor/Critic training，把吞吐提升到最高 3.7x。"
authors:
  - "Yinmin Zhong"
  - "Zili Zhang"
  - "Bingyang Wu"
  - "Shengyu Liu"
  - "Yukun Chen"
  - "Changyi Wan"
  - "Hanpeng Hu"
  - "Lei Xia"
  - "Ranchen Ming"
  - "Yibo Zhu"
  - "Xin Jin"
affiliations:
  - "School of Computer Science, Peking University"
  - "StepFun"
conference: nsdi-2025
category: llm-and-ml-training-serving
code_url: "https://github.com/FlexFusion/FlexFusion"
tags:
  - llm-training
  - gpu
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

RLHFuse 认为，RLHF 的低效根源不是缺少并行策略，而是同步边界画得太粗。它把 generation 和 inference 拆成 sample 级子任务，把 Actor 和 Critic 的训练拆成 micro-batch 级子任务，再在这些子任务之间做 stage fusion，让长尾 generation 不再阻塞 inference，也让一个模型的 pipeline bubble 由另一个模型来填补。作者在 256 张 Hopper GPU 集群上给出的结果是：端到端 RLHF 吞吐最高提升 3.7x。

## 问题背景

这篇论文关注 RLHF 中基于 PPO 的那一段流程。一次迭代要先做 Actor generation，再做 Reference、Reward、Critic inference，最后做 Actor 和 Critic training。已有 RLHF 系统已经会在 task 级别优化这个流程，比如给不同任务选择不同的 3D 并行策略，或者减少 task switching 的开销。RLHFuse 的判断是，这些优化仍然太粗，因为真正的大量浪费发生在任务内部。

第一类浪费来自 generation 的数据偏斜。生成出的 response 长度呈长尾分布，所以在 decoding 后半段，往往只剩下极少数超长 sample 还在跑。此时 GPU 利用率会明显下降，因为 decoding 本身是 memory-bandwidth-bound，依赖较大的 batch 才能吃满硬件；但 inference 又必须等待最慢的 sample 完成后才能开始。论文展示，在真实 RLHF 训练中，这部分长尾 sample 可以占掉 generation 时间的一半以上，而且最大输出长度越大，这个问题越严重。

第二类浪费来自 training 阶段的 pipeline bubble。RLHF 需要同时训练 Actor 和 Critic 两个大模型，而大模型通常必须提高 pipeline parallelism。对常见的 1F1B schedule，bubble 比例是 `(N-1)/(N-1+M)`，其中 `N` 是 pipeline stage 数，`M` 是 micro-batch 数。可是在 RLHF 里，global batch 先被切成 mini-batch，再分给 data parallel 组，`M` 本来就受限，不能无限增大。于是当模型规模继续上涨、`N` 接近甚至逼近 `M` 时，大量 GPU 会空转。论文的核心判断是：RLHF 的多模型结构引入了 task 级优化无法消除的系统性浪费。

## 核心洞察

RLHFuse 的核心洞察是，RLHF 的真实依赖边界比它在工作流图上看起来更细。Generation 和 inference 的依赖本质上是 sample 级的，而不是整个 stage 级的。只要大多数 sample 已经生成完成，剩下的长尾 sample 就可以迁移到少数 generation instance 上继续跑，同时把释放出来的 GPU 立即转给 inference，而不会破坏同步语义。

Training 阶段也一样。Pipeline bubble 是某一个模型内部 micro-batch 调度形成的依赖，而 RLHF 在 training 阶段恰好有两个彼此独立的模型：Actor 和 Critic。只要把它们的 micro-batch 放到同一个调度视角里，一个模型原本的空档就可以被另一个模型的计算填上。因此，这篇论文最值得记住的不是一个新的 RL 算法，也不是更好的单任务并行策略，而是执行粒度的变化：把 RLHF 当成一个由许多可融合子任务组成的系统来优化。

## 设计

RLHFuse 仍然先做类似 ReaLHF 和 HybridFlow 的 per-task parallel strategy selection。给定模型、集群和工作负载，它先为每个任务选好合适的 DP、TP、PP 配置。真正的新贡献发生在这一步之后，也就是两种 fusion 机制。

对于 generation 加 inference，RLHFuse 会持续监控 generation instance，并在剩余 sample 数降到阈值 `Rt` 以下时触发迁移。系统只保留 `m` 个 generation instance 处理长尾部分。`m` 的选择同时满足两个约束：一是保留足够的总 batch 容量，不让 tail decoding 本身变慢；二是有足够显存容纳这些 sample 的 KV cache。为了减少迁移量，系统会保留当前剩余 workload 最多的那 `m` 个 instance。论文里的部署环境使用 RDMA 直接迁移未完成 sample 的 KV cache，因此目标实例收到状态后就能继续 decoding。与此同时，其他 generation instance 释放出来的 GPU 会被转给 Reference、Reward、Critic inference，于是 inference 可以和长尾 generation 重叠执行，而不是被它阻塞。论文也明确说明，inference 和 training 之间不能照搬这个方法，因为 PPO 训练需要从完整生成样本集合中随机抽取 mini-batch。

对于 training，RLHFuse 把 bidirectional pipeline 的思路推广到异构模型。Actor 和 Critic 可能大小不同、TP/PP 配置也不同，所以 Chimera 那种对称 schedule 不能直接套用。RLHFuse 先用 fusion factor `K1` 和 `K2` 把两边归一成兼容的 pipeline group，然后在所有 stage 和 micro-batch 上搜索一个合法的 fused schedule。这个 schedule 必须同时满足跨 stage 数据依赖、同一 stage 内的执行顺序、无死锁，以及 activation memory 上限。系统没有直接使用贪心规则，而是采用 simulated annealing：先从一个贪心得到的初始解出发，再通过交换同一 stage 中相邻子任务来生成邻居解，用带备忘录的依赖递推计算总时延，最后再做第二轮搜索，在不增加 latency 的前提下降低 peak activation memory。围绕这两个核心机制，RLHFuse 还补充了 generation engine、按序列长度平衡 DP mini-batch、减少 weight redistribution 开销，以及把冻结的 Reference/Reward 权重留在 CPU 内存等工程优化。

## 实验评估

评估部署在一个生产级 RLHF 集群上，共 32 个节点、256 张 Hopper GPU，节点内通过 NVLINK 互联，节点间网络为 8x200 Gbps 的 RoCEv2。工作负载使用 LLaMA 13B、33B、65B 模型和 HH-RLHF 数据集，global batch size 为 512，mini-batch size 为 64。论文测试了四组 Actor/Critic 规模组合，把最大生成长度从 512 调到 2048 token，并且用 warm-up 之后连续 20 次迭代的平均 sample throughput 作为端到端指标。

端到端结果显示，RLHFuse 的 sample throughput 相比 DeepSpeed-Chat 提升 2.5-3.7x，相比 ReaLHF 提升 1.4-2.4x，相比 RLHFuse-Base 提升 1.2-1.4x。这里的 RLHFuse-Base 保留了相同的底层工程优化，但去掉了 inter-stage fusion 和 intra-stage fusion，因此能够把性能收益更干净地归因到 stage fusion 本身。基线设置也不算刻意“放水”：论文明确写到 DeepSpeed-Chat 在这套测试环境里无法用原始 mini-batch size 跑通，所以作者把它的 mini-batch size 提高到 256，同时保持 global batch size 不变，并指出这实际上更有利于 DeepSpeed-Chat 的吞吐表现。

分解结果也解释了这些收益来自哪里。当 generation length 足够大时，inter-stage fusion 基本可以把大部分甚至全部 inference 隐藏在长尾 generation 之后，使 generation 加 inference 的总时间缩短 1.2-1.6x。Intra-stage fusion 则通过让两个模型互相填补 pipeline bubble，把 training 时间再缩短 1.2-1.3x。剩余开销，比如数据传输和权重重分布，在总迭代时间里不到 3%。

论文还单独验证了两个关键调参点。对 inter-stage fusion 来说，最佳迁移点大约是 batch 还剩 20% sample 时：更小会浪费可重叠空间，更大则会把 surviving generation instance 压得过载。对 intra-stage fusion 来说，simulated annealing 始终优于贪心算法，在除最后一个配置外的所有情况都达到论文定义的 lower bound，并且 activation memory 也接近串行 1F1B 的下界。最有说服力的例子是 65B Actor 配 33B Critic 时，生成出的 fused schedule 在该配置下几乎把较小模型的训练完全重叠掉了。

## 创新性与影响

相对 ReaLHF 和 HybridFlow，RLHFuse 的新意在于：它不是只优化每个任务各自的并行策略，也不是只优化 stage 切换本身，而是在这些策略已经选定之后，继续优化任务内部以及任务之间的执行方式。相对 Chimera，它解决的是更难的异构情况，即两个不同模型、不同并行布局之间的联合调度，而不是同一个模型的两个副本。因此，这篇论文对构建大规模 RLHF 集群的团队很有参考价值，尤其是那些必须处理长输出、又不得不使用较大 PP 度的场景。它贡献的是一种新的 RLHF 执行机制，而不是新的对齐目标。

## 局限性

RLHFuse 依赖 profiling 和工作负载可预测性。迁移阈值 `Rt` 来自对输出长度分布的离线模拟，随着训练过程中分布变化，还需要周期性重新调整。它的迁移机制之所以代价很低，也部分依赖作者集群里的高速 RDMA 网络；如果换成更慢的网络，传输 KV cache 的代价未必还能忽略不计。

它的 fused pipeline 形式也带有结构性假设。论文假定 tensor parallel 度是 2 的幂，并且一个模型的 PP 配置能够整除进归一化后的 fused-stage 布局。评估本身也主要集中在 throughput 上：论文论证了同步语义没有被破坏，但并没有单独测量收敛速度、最终对齐质量，或者 LLaMA 之外模型家族的表现。最后，论文明确公开的是 intra-stage fusion 组件，但没有说明完整 RLHFuse 系统的公开发布路径。

## 相关工作

- _Lei et al. (USENIX ATC '24)_ - PUZZLE 主要降低 RLHF 各任务切换时的上下文切换开销，而 RLHFuse 直接处理 generation 和 training 内部的低利用率问题。
- _Li and Hoefler (SC '21)_ - Chimera 用双向 pipeline 训练同一模型的复制体；RLHFuse 则把这个思路推广到并行策略不同的异构 Actor 和 Critic 模型。
- _Narayanan et al. (SOSP '19)_ - PipeDream 普及了 1F1B pipeline scheduling，而 RLHFuse 的出发点正是这种基线在大 PP 宽度下仍然留下大量 bubble。
- _Jiang et al. (NSDI '24)_ - MegaScale 讨论的是超大规模 LLM training 基础设施，而 RLHFuse 聚焦于 RLHF 特有的多模型 PPO 阶段。

## 我的笔记

<!-- empty; left for the human reader -->

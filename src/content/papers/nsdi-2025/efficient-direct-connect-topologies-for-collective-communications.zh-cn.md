---
title: "Efficient Direct-Connect Topologies for Collective Communications"
oneline: "联合合成受端口度约束的直连拓扑与 collective 调度，再按工作负载在低跳数延迟和负载均衡带宽之间选择 Pareto 最优方案。"
authors:
  - "Liangyu Zhao"
  - "Siddharth Pal"
  - "Tapan Chugh"
  - "Weiyang Wang"
  - "Jason Fantl"
  - "Prithwish Basu"
  - "Joud Khoury"
  - "Arvind Krishnamurthy"
affiliations:
  - "University of Washington"
  - "RTX BBN Technologies"
  - "MIT CSAIL"
conference: nsdi-2025
category: llm-and-ml-training-serving
tags:
  - networking
  - gpu
  - llm-training
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文认为，direct-connect fabric 不该只能在 ring 和 tree 之间二选一。它提出了一条完整的合成流水线: 从小规模最优图出发，通过图扩展构造更大的拓扑，用多项式时间的 Breadth-First-Broadcast (BFB) 算法生成可扩展的 collective 调度，再根据工作负载所处的延迟/带宽区间选择最合适的拓扑与调度组合。

## 问题背景

论文面向的是一种受端口度约束的直连集群: 例如由 optical circuit 或 patch panel 搭成的网络，每台主机只有少量固定端口。在这种环境里，现有 collective 方案都带着明显短板。Ring collective 在大消息下可以做到带宽最优，但跳数会随集群规模线性增长，因此小消息或延迟敏感的 collective 很吃亏。Double binary tree 把跳数降到对数级，却会造成链路负载不均并牺牲带宽效率。另一方面，recursive doubling、Bruck 这类为 switch network 设计的算法又默认网络在时间上提供高逻辑度连接，因此并不适合低度数的 direct-connect fabric。

真正棘手的是，拓扑和调度彼此耦合。低直径图有利于小规模 allreduce 和 all-to-all，却可能在大消息下压垮少数链路；负载均衡好的规则图则可能要付出过多 hops。此前工作大多只优化其中一侧。论文想回答的是: 能不能在真实规模上把 topology 和 schedule 一起合成出来？

## 核心洞察

这篇论文最重要的洞察是: 对 direct-connect 网络来说，并不存在一个通吃所有工作负载的“最佳拓扑”，真正存在的是“低跳数”和“负载均衡”之间的一条 Pareto frontier，而这条 frontier 可以通过结构化搜索高效探索出来。

作者用两步把这个搜索空间做小。第一步，从具有良好 schedule 的小规模 base graph 出发，通过图扩展保留关键性质: line-graph expansion 保持节点度不变并保留近似最优的 hop 性质，degree expansion 在增大度数时保留带宽最优，Cartesian product 则把简单图组合成更大的结构。第二步，在大规模对称图上不再做穷举式 schedule synthesis，而是把调度限制为沿 shortest path 进行 eager breadth-first broadcast，然后只求解连续型的负载均衡问题。这样，BFB 一方面保证所选拓扑上的最小 `TL`，另一方面仍能在 torus、circulant 等图族上恢复带宽最优的 schedule。

## 设计

论文把 collective 成本拆成两个部分: `TL` 表示总 hop latency，即通信步数乘以 `alpha`；`TB` 表示带宽运行时间，取决于每一步里最拥塞的链路。因此搜索目标不是单一标量最优，而是给定节点数 `N` 和度数 `d` 下的一组 Pareto-efficient topology/schedule 组合。

合成工具箱包含三种 expansion operator。Line-graph expansion 把 base graph 的每条边变成新图中的一个节点，因此一个 `N` 节点、度数为 `d` 的图会变成 `dN` 节点的更大图，但节点度不增加，而且原图里的最短路径可以映射到扩展图中。Degree expansion 复制多个副本并重新连边，使节点数和度数都按 `n` 倍扩张；由于不同副本的广播路径互不重叠，带宽最优 schedule 可以保留下来。Cartesian product 则按维度组合多个图，从而构造 Hamming graph、hypercube 和不等边 torus 等结构。

对于没有现成 schedule 的图，作者用 BFB 生成调度。在 allgather 中，每个节点按 breadth-first frontier 分层广播自己的 shard。对每个通信步、每个接收节点，BFB 解一个线性规划，决定每个 shard 的多少比例该从哪个前驱节点接收，使最忙 ingress 链路的负载最小。变量采用连续比例而不是离散 chunk 放置，因此算法保持多项式时间并可并行求解。其上层的 Topology Finder 则在 base graph 库和 expansion sequence 上做搜索，用闭式公式预测 `TL` 与 `TB`，剪掉被支配方案，并输出目标 `N`、`d` 的 Pareto frontier。最终结果会 lowering 到 GPU 上的 MSCCL 和 CPU 集群上的 oneCCL/libfabric。

## 实验评估

评估基本支持了论文的核心主张。作者在一个 12 节点 optical GPU testbed 上测试，机器配备 A100-PCIe GPU，并通过 4x25 Gbps 直连链路互联；对比基线是 ShiftedRing 和 double binary tree (DBT)，并对 baseline 参数做了公平调优。在 1 KB allreduce 下，论文选出的拓扑在 12 节点时比 ShiftedRing 快约 75%，比 DBT 快约 20%。在 1 MB 下，它仍比 ShiftedRing 快约 50%，比 DBT 快约 45%。到 1 GB 时，它和带宽最优的 ShiftedRing 基本打平，但仍比 DBT 快约 50%。

训练和大规模结果更能说明问题。在多个小模型的数据并行训练中，论文方案把总 allreduce 时间相对 ShiftedRing 和 DBT 分别降低了 30% 和 50%，最终仍带来 10% 和 25% 的 iteration time 改善；在 GPT-2 上，这两个提升分别是 7% 和 25%。解析模型显示，在接近 1000 节点时，最佳合成拓扑在 allreduce 上比 ShiftedRing 和 DBT 分别快 56 倍和 10 倍；在 all-to-all 上，generalized Kautz 距理论下界只差 5.2%，却分别比两条基线快 28 倍和 42 倍。对 MoE 训练的模拟中，256 节点、14.7B 参数模型里，ShiftedRing 的 all-to-all 时间是论文方案的 8 倍，iteration time 是 4 倍；到 1024 节点、1.6T 参数时，这两个差距扩大到 27 倍和 9 倍。BFB 本身也足够实用: 它能在大约一分钟内为 1024 节点 hypercube 和 2500 节点 torus 生成 schedule，而 SCCL 和 TACCL 会在远小得多的规模上超时或失败。

## 创新性与影响

这篇论文的创新点不在某一个具体图结构上，而在于整套 synthesis framework。相较于 _TopoOpt_ (NSDI '23)，它不是围绕 ring collective 调整网络排列，而是连 collective schedule 本身一起改掉。相较于 _SCCL_ 和 _TACCL_，它牺牲了“任意图上全局最优合成”的一般性，换来一个真正能扩展到大规模 direct-connect fabric 的搜索与生成流水线。对 optical ML cluster、TPU 式 torus 部署，以及任何端口度稀缺但 all-to-all 已成关键路径的 accelerator fabric 来说，这都是很有价值的设计模板。

## 局限性

论文并没有证明最终搜索得到的是全局最优拓扑。它搜索的是一组精选 base graph 及其 expansion rule，因此库之外完全可能还存在更好的图。BFB 也只是条件最优: 它之所以能做到多项式时间，是因为把 schedule 限制为 eager 的 shortest-path broadcast，而这可能排除掉某些不规则图上的更优方案。实验部分还默认“每个作业使用一个静态拓扑”，因为 patch panel 的重配置太慢；同时正文也主要假设 homogeneous 的 direct-connect fabric。

## 相关工作

- _Wang et al. (NSDI '23)_ - `TopoOpt` 为训练任务联合优化网络拓扑与并行策略，但 collective 仍然沿用 ring；这篇论文则同时改变拓扑和 collective schedule。
- _Cai et al. (PPoPP '21)_ - `SCCL` 在固定拓扑上合成最优 collective schedule，而这篇论文通过结构化 graph expansion 和 `BFB` 把 topology 加 schedule 的联合搜索扩展到更大规模。
- _Shah et al. (NSDI '23)_ - `TACCL` 用 communication sketch 加速固定拓扑上的调度合成；`BFB` 的一般性较弱，但它是多项式时间，并且能处理大得多的图。
- _Basu et al. (HPDC '24)_ - 作者此前关于 direct-connect topologies 的 all-to-all 工作优化的是互补 primitive，而这篇论文把 allreduce、reduce-scatter 和 allgather 也纳入同一个设计空间。

## 我的笔记

<!-- 留空；由人工补充 -->

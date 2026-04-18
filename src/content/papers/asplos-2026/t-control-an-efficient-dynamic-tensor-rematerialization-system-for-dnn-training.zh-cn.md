---
title: "T-Control: An Efficient Dynamic Tensor Rematerialization System for DNN Training"
oneline: "T-Control 在运行时保留 TDG 中最关键的张量并主动整理 GPU 内存，让动态重计算在更紧的显存预算下减少驱逐与递归重算。"
authors:
  - "Zehua Wang"
  - "Junmin Xiao"
  - "Xiaochuan Deng"
  - "Huibing Wang"
  - "Hui Ma"
  - "Mingyi Li"
  - "Yunfei Pang"
  - "Guangming Tan"
affiliations:
  - "Institute of Computing Technology, Chinese Academy of Sciences, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790230"
tags:
  - ml-systems
  - memory
  - gpu
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

T-Control 的核心判断是，动态 tensor rematerialization 之所以常常不如静态方法，不只是因为在线决策本身有开销，更因为它在碎片化内存上做了局部驱逐。它用 TDG 中基于 shortest computation path 的中心性来保护真正关键的张量，再配合主动迁移和分段式内存管理减少碎片，因此把动态方法重新拉回到能和静态方法竞争的区间。

## 问题背景

论文讨论的是显存预算紧张时的训练问题。常见做法是 activation rematerialization，也就是在前向阶段释放一部分中间张量，在反向阶段需要时再重算。静态方法能提前看到完整计算图，因此可以全局规划重算与保留策略；但它们对输入相关的动态执行并不友好，因为图结构一变就得重新规划。动态方法天然更适合 AlphaFold、MoE 这类执行路径随输入变化的模型，可现实表现却往往更差。

作者把原因拆成两类。第一，已有动态系统如 DTR、DTE 多半依据张量大小、staleness、局部重算代价等局部属性做驱逐判断，却没有显式利用张量之间的依赖拓扑。这会把位于许多后续计算必经路径上的 hub tensor 驱逐掉，导致反向阶段出现大量 rematerialization 和很深的递归重算。第二，内存碎片会把问题进一步放大。动态重算下的分配模式本来就不规则，碎片一多，明明总空闲显存还够，却拿不到连续空间，只能继续驱逐和重算，形成恶性循环。论文的动机实验正是用 rematerialization 次数、递归深度和碎片率把这个问题量化出来。

## 核心洞察

这篇论文最值得记住的一点是：动态重计算要想追上静态方法，关键不是再找一个更聪明的单点 eviction heuristic，而是把“保留哪些张量”和“如何组织显存”一起做。运行时已经能看到被逐步 traced 出来的 tensor dependency graph，也能知道当前显存到底剩多少，因此系统完全可以同时利用图拓扑和实时内存状态做联合决策。

作者选择的图信号是 shortest-computation-path betweenness centrality。直观上，一个张量如果落在大量最短计算路径上，它就像连接多层或跨层依赖的桥；驱逐它带来的损失，通常远大于驱逐一个孤立但大小相近的 activation。只要优先保留这些 TDG 中的关键桥点，深层递归重算就会显著减少。与此同时，如果 allocator 主动把活跃张量压缩到高占用 segment，把稀疏 segment 腾出来做后续大块分配，就能减少“因为碎片而被迫驱逐”的情况。论文的真正贡献，在于说明这两个机制叠加后会相互增强，而不是各自独立改善一点点。

## 设计

T-Control 以对 PyTorch 的轻量修改实现，包含四个部件：OP Executor、Tensor Manager、TDG Manager 和 Memory Manager。它以单个算子为粒度拦截训练流程：先接管输入张量和输出分配，再执行算子、更新 TDG，最后决定哪些张量需要锁定保留、哪些可以驱逐。若当前内存逼近预算，就会进入额外的 eviction workflow，在继续执行前先让 Tensor Manager 释放空间。

保留算法围绕一个增量构建的 TDG 展开。作者观察到训练图天然具有层级结构，所以把它拆成按层增长的子图序列，以及位于更高层的 skip-connection 边。张量重要性不是按 hop 数定义，而是按 shortest computation path 的 betweenness centrality 定义，因此路径长度反映的是真实重算代价。每当新的一层子图加入，T-Control 不会从头重算所有中心性，而是按四个增量项更新：新子图内部路径的贡献、跨旧子图路径的贡献、流入新子图的贡献，以及从新子图流出的贡献。更新完分数后，系统按分数排序并把 top `K%` 的顶点放进 reservation set，其中 `K` 会随着 residual memory 增大而增大。也就是说，空闲显存越多，系统就越愿意多保留一些图结构上关键的张量。

内存管理是另一半关键。T-Control 把 PyTorch allocator 改造成按大小分桶的 segment-centered 结构，并遵循三条规则。第一条是 occupancy-guided best-fit allocation：若多个空闲块都能满足请求，就优先选位于高占用 segment 中的那个，把活跃张量尽量压紧。第二条是 occupancy-guided tensor migration：若分配失败的原因只是拿不到足够大的连续空间，就先把低占用 segment 里的张量迁到别处，腾出完整 segment。第三条是 cost-aware tensor eviction：当驱逐不可避免时，选择那个“腾出连续空间所需总代价最低”的 segment，代价综合考虑张量重算成本、大小和 staleness。作者把这看作一种比 virtual memory stitching 更轻量的替代方案。

## 实验评估

实验覆盖面相当广。分布式训练部分运行在最多 64 个节点上，每个节点有 4 张 A100-40GB；动态方法对比则在单机 8 张 A100-80GB 上完成。模型既包括 GPT、Llama 这类静态 Transformer，也包括 ResNet、ViT 这样的视觉模型，以及 AlphaFold、LSTM、GPT-MoE、BERT4GCN 等动态模型。这样的组合对一篇显存管理论文来说是比较扎实的，因为它不只是盯着单一 Transformer 工作负载。

和不使用重计算或使用静态重计算的系统相比，T-Control 给出的主结果很强。在分布式训练里，它相对 DeepSpeed ZeRO、Zero Bubble、Megatron-LM 和 AdaPipe，在 GPT 模型上达到 `1.05x-1.58x` 的吞吐提升，在 Llama 2 上达到 `1.10x-1.22x`。作者的解释是，重计算让每张卡能容纳更多工作，从而降低 TP 或 PP、提升 DP，最终减少跨 GPU 通信。更重要的是，在 GPT 3-121B 的 128 GPU 训练和 Llama 3-405B 的 256 GPU 训练里，其他非重计算基线全部 OOM，只有 T-Control 能跑起来。

和动态方法相比，论文也给出了比较完整的因果证据。在 8 张 A100 上跨静态与动态模型统计时，T-Control 相比 DTR、DTE、GMLake+DTR 的几何平均加速分别为 `1.17x`、`1.25x`、`1.47x`。当 memory budget 更紧时，它对 DTR 的优势扩大到 `1.04x-1.74x`，对 DTE 扩大到 `1.09x-1.91x`。更关键的是机制层面的数据：它最多减少 `92%` 的驱逐事件、`71%` 的 rematerialization 事件，把单次 TR 的最大递归深度压到 `126`，相对 DTR 低 `21x`；在分布式训练里，碎片率始终低于 `6%`。同时系统开销始终低于总执行时间的 `5%`，因此“增加控制逻辑但整体更快”这个结论是成立的。

## 创新性与影响

相对已有动态重计算工作，T-Control 的新意不只是“更好的启发式”。它把决策核心从局部张量代价改成了图拓扑上的关键性，并且把 rematerialization 调度与 allocator 设计绑在一起，明确把碎片问题纳入主设计空间。相对静态系统，它想证明的是：动态方法并不必然慢很多，只要同时利用 traced TDG 和实时显存状态，就能拿回相当一部分原本只属于静态方法的性能优势。

这使它对训练系统研究者、GPU 内存管理研究者以及大模型训练框架工程团队都有参考价值。更广义地说，这篇论文把动态重计算重新定义成一个“图控制加内存控制”的联合问题，而不是单纯的在线驱逐策略问题。

## 局限性

论文的说服力主要来自吞吐和显存利用，但边界也很清楚。中心性更新算法依赖 TDG 的层状规律，因此面对更不规则的执行图时能否保持同样效果，还没有被充分证明。保留阈值 `K%` 虽然会随 residual memory 自适应变化，但其中的系数仍是经验选取，说明策略层面仍有调参成分。内存迁移虽然比 VMS 便宜，但本质上依然是数据移动；如果换到不同互连或更大张量上，收益与代价的平衡可能会变化。

实验方面，主文仍以每迭代吞吐为中心，而不是完整训练到收敛的 wall-clock time，虽然附录给出了与 Megatron-LM 接近的 loss 曲线。另一个限制是，动态模型评测集中在单机 8 卡，而大规模分布式结果主要来自 GPT 和 Llama 这类静态 Transformer。因此，这篇论文最稳妥的结论不是“它解决了所有训练内存问题”，而是“它显著改善了动态重计算原本很差的运行区间”。

## 相关工作

- _Jain et al. (MLSys '20)_ - Checkmate 通过离线全局优化求解 rematerialization 计划，而 T-Control 选择牺牲这类离线最优性来换取运行时自适应和对动态模型的支持。
- _Hu et al. (ICS '22)_ - MegTaiChi 的 DTE 已经把碎片意识引入动态驱逐，但它仍主要依赖局部启发式，而不是显式保留 TDG 中的关键 hub tensor。
- _Guo et al. (ASPLOS '24)_ - GMLake 用 virtual memory stitching 降低碎片，T-Control 则试图用更低开销的迁移和 segment-aware placement 获得类似收益。
- _Sun et al. (ASPLOS '24)_ - AdaPipe 是面向 Transformer 的强静态规划器，而 T-Control 希望在不假设固定预规划 schedule 的前提下逼近这类效率。

## 我的笔记

<!-- 留空；由人工补充 -->

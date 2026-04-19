---
title: "Bingo: Radix-based Bias Factorization for Random Walk on Dynamic Graphs"
oneline: "Bingo 把边权按 radix bit 分组，再用两级采样和按组更新，把动态图上的偏置随机游走做成 O(1) 采样。"
authors:
  - "Pinhuan Wang"
  - "Chengying Huan"
  - "Zhibin Wang"
  - "Chen Tian"
  - "Yuede Ji"
  - "Hang Liu"
affiliations:
  - "Rutgers, The State University of New Jersey, Piscataway, NJ, USA"
  - "State Key Laboratory for Novel Software Technology, Nanjing University, Nanjing, China"
  - "The University of Texas at Arlington, Arlington, Texas, USA"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717456"
tags:
  - graph-processing
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Bingo 是一个面向动态图的 GPU random-walk engine。它不再为每个顶点维护整块的偏置采样表，而是把边权拆成按位 radix group，再用两级采样恢复原始概率分布。这样一来，采样仍是 O(1)，插入和删除只需改动对应的少数几个 group。

## 问题背景

这篇论文盯住的是一个很现实的空白：random walk 已经是 graph learning、推荐、PPR 和相似度计算里的基础操作，但真实世界里的图不会静止不动。边会不断插入、删除、改权重。现有 random-walk 系统大多把重点放在静态图上，而动态图系统又通常服务于通用图分析，而不是反复执行偏置采样。

难点在于，传统采样方法在动态图里各有致命缺口。Alias table 的采样时间很好看，是 O(1)，但只要某个顶点的一条边变了，就可能要按顶点度数 O(d) 重建整张表。Rejection sampling 的更新很轻，却可能因为 bias 分布太歪而让采样代价飙升。ITS 更新更方便，可每次采样仍要 O(log d)，碰到高阶顶点很多的图时，这个成本并不小。作者因此提出两个目标同时成立：既要能接住低延迟 streaming update，也要能吃下高吞吐 batched update，而且不能把偏置采样的速度一起牺牲掉。

## 核心洞察

Bingo 最关键的判断是：一个顶点的偏置邻居集合，不该继续被看成一张整体采样表，而应该按二进制位拆开。只要把每条边的 bias 分解成若干个 `2^k`，那么同一个 bit 位置上的元素就天然组成一个无偏组，因为它们在该组里贡献的子权重完全一样。

这个表示一变，采样和更新的代价结构也跟着变了。采样不再直接从原始邻居里选，而是先按各个 radix group 的总权重选组，再在组内做均匀采样。更新也不再跟整个邻居表长度绑定，而只和该边 bias 中非零 bit 的个数有关。论文还证明了，把一个邻居在所有 group 中被选中的概率加起来，恰好就是原始定义里的转移概率，所以 Bingo 只是重写了数据结构，并没有改写 random walk 的语义。

## 设计

对每个顶点，Bingo 会先把每个整数 bias `w_i` 分解成若干个 `2^k` 项，再按 bit 位置把这些子权重重新组织起来。于是每个顶点的采样空间被拆成两层。第一层是 inter-group sampling：记录每个 group 的总 bias，用 alias table 在 O(1) 时间里挑出一个 group。第二层是 intra-group sampling：在刚选中的 group 里直接均匀采样，因为同组内每个元素贡献的 radix 值相同，所以不需要再维护更复杂的偏置结构。

streaming update 也沿着同一套结构走。插入相对简单：把新边的 bias 分解后追加进对应的 group，再重建很小的 inter-group alias table。删除更麻烦，所以 Bingo 在 group 里存的不是 neighbor ID，而是 neighbor index；同时再配一个 inverted index，记录每个 neighbor index 当前落在各个 group 的什么位置。这样删除时就能 O(1) 找到目标元素，把它和组尾交换，再维持紧凑布局，保证组内均匀采样仍然成立。

如果照这个朴素设计硬做，内存会很高，所以论文加了 adaptive group representation。Dense group 完全不维护组内列表和反向索引，改成在原始 neighbor list 上做 rejection sampling。One-element group 因为只有一个元素，也无需额外索引。Sparse group 则只保留高 bias 边组成的缩小版 neighbor list，把 inverted index 做小。只有剩下的 regular group 才保留完整结构。对 floating-point bias，Bingo 先乘一个经验选出来的 `lambda`，把整数部分继续做 radix 分解，小数部分单独放进一个 group，用 ITS 或 rejection sampling 处理。

batched update 则体现了它的 GPU 系统设计。CPU 先把同一顶点的更新请求整理到一起，再交给 GPU 分阶段做 insert、delete 和 rebuild。里面最重要的技巧是两阶段 parallel delete-and-swap：先把尾部元素暂存起来，提前删掉其中那些本身也要被删的项，再只用确定不会被删除的尾元素去填补前面的空洞。这样既保住了紧凑布局，又把删除过程真正并行化了。

## 实验评估

实验基本支撑住了论文的中心论点。Bingo 大约用 2,000 行 CUDA/C++ 实现，平台是带 4 张 A100-80GB 的服务器，工作负载覆盖 biased DeepWalk、node2vec 和 PPR，数据集从 Amazon 一直到 Twitter，更新模式同时包含 insertion、deletion 和 mixed 三种情况。

最重要的结果是，Bingo 在文中报告的工作负载上始终快过三个对照系统：相对 KnightKing 快 24.46x 到 112.28x，相对 gSampler 快 8.74x 到 25.66x，相对 FlowWalker 快 182.78x 到 271.11x。更新吞吐方面，streaming update 大约能到 0.2 million updates/s，batched update 最高到 226 million updates/s。与此同时，adaptive group representation 又把 Bingo 自己相对朴素实现的内存占用压低了 14.6x 到 22.2x，并且在 Twitter 数据集上化解了 OOM。

这些数字和机制本身是对得上的。Deletion 比 insertion 更快，因为释放出来的内存可以离线处理；batched update 比 streaming update 快三个数量级左右，是因为一整批请求只需要重建一次 inter-group 状态。floating-point bias 的额外成本也不高，平均只比整数 bias 多 1.02x 时间和 1.08x 内存。不过有个需要读者自己记住的前提：gSampler 和 FlowWalker 本身并不是按 Bingo 这种动态更新模型设计的，所以论文里的对比包含了作者为它们加上的 rebuild 或 reload 开销。

## 创新性与影响

Bingo 的新意不在 random walk 目标函数，而在动态图上的偏置采样底座。它把原来那个按顶点度数重建的大问题，拆成只改少数 radix group 的小问题，再通过 GPU 友好的表示和 batched update 把这个想法落到系统里。

这件事对两类人都有价值。对 graph systems 研究者来说，Bingo 给出了一条不同于 alias table 和 rejection sampling 老套路的路径。对维护持续变化图数据的实际系统来说，它说明在线结构更新并不一定意味着要回退到慢采样，或者频繁整表重建。

## 局限性

内存仍然是 Bingo 最大的代价。即便用了 group adaptation，论文里还是能看到一些场景下 Bingo 的内存高于更简单的 baseline，尤其是在高 bias 顶点较多、regular group 更多的图上。作者提出可以调整 dense 和 sparse 的阈值，或者改用更大的 radix base，但这更像调参和工程补救，还不是一个很干净的答案。

floating-point bias 的支持也偏工程化。它依赖经验选定的 `lambda`，还要额外维护一个小数组成的 decimal group，并在其中切到 ITS 或 rejection sampling。论文证明这条路径在实验里够便宜，但它显然没有整数 bias 那么整齐。

最后，评测里的 update stream 是从静态图拆分生成的合成负载，而两类主要 baseline 也需要通过每轮更新后重建结构来适配比较。这并不否定 Bingo 的价值，但意味着论文中的端到端收益，既来自更好的采样表示，也来自对手本来就不是为这个动态问题而设计。

## 相关工作

- _Yang et al. (SOSP '19)_ - `KnightKing` 擅长静态图上的 random walk，并处理运行时变化的 bias；Bingo 则直接处理图结构本身的增删改。
- _Pandey et al. (SC '20)_ - `C-SAW` 把 GPU 上的图采样做得很快，但默认采样空间是静态的；Bingo 关注的是这些采样结构如何随着更新持续维护。
- _Huan et al. (EuroSys '23)_ - `TEA` 处理的是 temporal graph random walk，而 Bingo 要解决的是邻接关系会在线变化的动态图。
- _Papadias et al. (VLDB '22)_ - `Wharf` 重点是更新已经算出来的 random-walk 结果；Bingo 维护的是之后每一次 walk 都要用到的 biased-sampling substrate。

## 我的笔记

<!-- 留空；由人工补充 -->

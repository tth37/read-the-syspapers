---
title: "Groot: Graph-Centric Row Reordering with Tree for Sparse Matrix Multiplications on Tensor Cores"
oneline: "Groot 把重排行的问题改写成最小化行差异：先用 Hamming distance 建 kNN graph，再走 MST，让 Tensor Core sparse kernels 压成更少 tiles。"
authors:
  - "YuAng Chen"
  - "Jiadong Xie"
  - "Siyi Teng"
  - "Wenqi Zeng"
  - "Jeffrey Xu Yu"
affiliations:
  - "The Chinese University of Hong Kong"
  - "Hong Kong University of Science and Technology"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717460"
code_url: "https://github.com/yuang-chen/Groot-EuroSys25"
tags:
  - graph-processing
  - gpu
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Groot 是一个面向静态稀疏矩阵的 row reordering 预处理器，核心目标不是把相似行塞进同一个 cluster，而是让相邻行差得更少，好让 TC-GNN 那类 graph condensing 在 Tensor Cores 上生成更少的非空 tile。它用 Hamming distance 找近邻、在近邻图上抽取 MST，再用 preorder traversal 得到最终顺序。论文报告的平均加速是 TC-SpMM 1.80x、TC-SDDMM 2.02x。

## 问题背景

图稀疏矩阵的不规则性，正好卡住了 Tensor Cores 的效率上限。非零元分布散、每行长度差异大，SpMM 和 SDDMM 很容易出现 coalescing 差和负载不均。TC-GNN 的 graph condensing 能缓解这一点：先按 row windows 切矩阵，再删掉窗口内空列，把剩余列压成更适合 MMA 的 dense tile。

问题是，condensing 的收益高度依赖窗口里装了哪些行。已有 GPU reordering 方法大多沿用 Jaccard similarity 加 LSH clustering，但 Groot 认为这从目标函数开始就偏了。condensing 真正在乎的是一个 window 里保留多少不同的非零列，而不是某一行和 cluster center 有多像。再加上 cluster 大小常常和 row window 对不上、LSH 在高维下又慢又不准，局部聚类很容易和真正的 Tensor Core 目标脱节。

## 核心洞察

这篇论文最重要的判断是：对 Tensor Core sparse kernels 来说，应该最小化 row difference，而不是最大化 row similarity。只要相邻两行在列位置上的分歧更少，后续切成窗口时，就更可能留下更少的有效列，形成更密的 tile。

因此 Groot 直接把度量从 Jaccard similarity 换成二值行向量上的 Hamming distance，再把原本依赖固定 window 的目标放宽成一个顺序优化问题：重新排列所有行，让相邻两行的 Hamming distance 总和最小。这个版本仍然是 NP-hard，但已经很像 open-loop TSP，可以用图近似算法处理，而且不会绑死某个特定 MMA shape。

## 设计

Groot 分三步做事。第一步，把 CSR 每一行表示成按列号排序的非零索引列表，用类似 merge 两个有序数组的方式计算 sparse Hamming distance。然后利用 `kGraph` 和这个距离构建 kNN graph，而不是显式构造全体行之间的完整距离图，这样能保留最重要的局部邻接关系，同时避开 `O(n^2)` 的代价。

第二步，在 kNN graph 上用 Kruskal 抽取 MST；第三步，对 MST 或 forest 做 preorder traversal，把访问顺序当作新的 row order。MST 保留低代价的行间连接，preorder 则给了它一个 TSP 风格的近似解释。整套复杂度从原始的阶乘级搜索降到 `O(n^1.14 + nk log nk)`，而且重排结果不依赖固定 window 大小，因此可以跨不同 MMA shape 复用。

## 实验评估

实验平台是双路 AMD EPYC 7443 服务器加一张 NVIDIA L40 40 GB。重排过程在 CPU 上完成，下游 kernel 在 GPU 上执行。比较对象包括开源 LSH reordering 和 TCA，工作负载覆盖 17 个图数据集，使用 TC-GNN 的 TC-SpMM、TC-SDDMM，以及 cuSPARSE 的 CUDA-core baseline。

主结论基本站得住。Tensor Cores 上，Groot 对 SpMM 的平均加速是 1.80x，而 LSH 与 TCA 分别只有 1.20x 和 1.11x；对 SDDMM，Groot 是 2.02x，LSH 和 TCA 则是 1.08x 与 0.98x。代表性结果包括 `artist` 上 TC-SpMM 的 2.64x、`products` 的 3.28x、`reddit` 的 2.74x，以及 `reddit` 上 TC-SDDMM 的 3.99x。机制层面也对得上：Groot 在 `amazon0505`、`products`、`reddit` 上分别把非空 tile 数压低 37%、69%、58%，而 ablation 里的 unordered、kNN-only、MST-only 版本只达到完整 Groot 的 56%、73%、77%。

收益并不普适。`Yeast` 和 `YeastH` 几乎没改善，`proteins` 上 LSH 还略胜一筹。预处理开销是一次性的 CPU 成本，范围是 0.27 s 到 82 s，明显低于 LSH 的 1.5 s 到 1.7 hr，以及 TCA 的最高超过 15 hr。端到端上，GCN 得到 1.22x、AGNN 得到 1.38x，OPT-30B 的一个稀疏 MLP 权重矩阵在 sparsity 超过 50% 后也开始受益。

## 创新性与影响

Groot 的新意不在于再造一个 sparse kernel，而在于把 Tensor Core 前面的 preprocessing 问题重新表述了一遍。它用 Hamming-distance graph construction 加 tree-based global ordering，替代了 Jaccard/LSH row clustering，这对依赖 graph condensing 的 Tensor Core sparse kernels 更贴题。只要稀疏模式足够静态，能摊薄一次性重排成本，这个思路就可能影响图计算、GNN 训练与推理，以及剪枝模型 serving。

## 局限性

这套方法默认稀疏模式是静态且非结构化的。动态图或动态矩阵会反复支付重排成本，NVIDIA 2:4 这类结构化 sparsity 也会被 row reordering 破坏。更广义的系统证据也比 kernel 结果窄一些：GNN 的整体加速更小，因为 dense layers 仍占不少时间；LLM 实验只用了一个 `28672 x 7168` 的 OPT-30B 权重矩阵，而不是完整 serving stack。CUDA-core 部分还有一个文本不一致的问题：平均 CU-SDDMM 加速一处写成 1.11x，后面又写成 1.32x。

## 相关工作

- _Wang et al. (USENIX ATC '23)_ - TC-GNN 提出了把图稀疏矩阵压成适合 Tensor Cores 的 graph condensing；Groot 则是放在它前面的 reordering layer，用更好的行顺序进一步减少 tile 数。
- _Fan et al. (ASPLOS '24)_ - DTC-SpMM 也讨论 Tensor Core sparse MM 的重排问题，但 Groot 的观点是 Jaccard 风格目标和 condensing 并不一致，因此改用 Hamming-distance ordering。
- _Jiang et al. (PPoPP '20)_ - 这类更早的 GPU sparse-MM 预处理方法使用 Jaccard similarity 和 LSH 做分组；Groot 则改成 graph-based ANN 加 MST 导出的全局顺序。
- _Wei et al. (SIGMOD '16)_ - GOrder 把 graph ordering 当作 NP-hard 的 locality 优化问题来处理；Groot 延续了这种全局排序思路，但服务的目标变成 Tensor Core tile formation，而不是单纯的 cache locality。

## 我的笔记

<!-- 留空；由人工补充 -->

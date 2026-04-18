---
title: "Slaws: Spatial Locality Analysis and Workload Orchestration for Sparse Matrix Multiplication"
oneline: "Slaws 用在线稀疏模式分析重排块并融合行，再用近似 top-K 的 Shuffle-Compare 均衡乘法器负载，加速 SpMSpM。"
authors:
  - "Guoyu Li"
  - "Zheng Guan"
  - "Beichen Zhang"
  - "Jun Yu"
  - "Kun Wang"
affiliations:
  - "State Key Laboratory of Integrated Chips and Systems, College of Integrated Circuits and Micro-Nano Electronics, Fudan University, Shanghai, China"
  - "State Key Laboratory of Integrated Chips and Systems, School of Microelectronics, Fudan University, Shanghai, China"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790222"
tags:
  - hardware
  - caching
  - graph-processing
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Slaws 是一个面向 `SpMSpM` 的稀疏矩阵加速器，它把两个操作数分开处理：对左矩阵在线分析稀疏模式，挖出局部与远距离复用；对右矩阵则重新组织工作流，避免乘法器因为行长不均而空转。靠着 Pass-Aware 和 Shuffle-Compare 两个机制，最终的 `Slaws-POS` 平均比 Feasta 快 `1.46x`、比 Spada 快 `1.43x`，相对 RTX 5080 GPU 也有 `1.55x` 的提升。

## 问题背景

这篇论文抓住的是 `SpMSpM` 在硬件上最难处理的两种不规则性。理论上，稀疏矩阵乘法通过跳过零元素来省存储、省计算；但一旦左右操作数都变成稀疏矩阵，访存与调度会同时变得很乱。若稀疏矩阵位于左侧，硬件要根据 `A` 的非零列去索引 `B` 的行，此时能否复用 `B`，取决于 `A` 的多行是否真的共享列位置，而不只是行长相近。若稀疏矩阵位于右侧，不同行长度差异又会带来负载失衡：短行对应的乘法器先做完后空等，合并单元还要为了保持有序输出而等待长行。

已有工作往往只解决其中一部分。Spada 用行长作为重叠关系的代理指标，但 Slaws 指出，行长相同并不意味着非零分布相似。Feasta 和 Trapezoid 虽然支持多种数据流，但其并行度选择基本在编译前就定死，无法根据当前矩阵区域的稀疏结构动态调整。软件预处理确实可以做更激进的重排，但论文认为它的代价常常远高于一次 kernel 执行本身。于是问题就变成：能不能在硬件里用很低成本做在线结构分析，一边为左操作数找复用机会，一边为右操作数做负载均衡，而不引入一个昂贵的精确调度器？

## 核心洞察

论文最重要的洞察是，`SpMSpM` 的两个难点需要依靠两类不同的结构信息来解决。对左乘数来说，关键不是行长，而是多行之间是否在局部共享列位置，以及相距很远的块是否具有相似的稀疏签名。只要硬件能以较低开销采样并比较这些模式，就能判断什么时候应该把多行合起来执行，利用 `Outer-Product` 风格的输入复用；什么时候应该保持 `Gustavson` 风格的逐行处理。

对右乘数来说，关键观察是 `CSR` 行本身已经按列索引升序排列。Slaws 利用这个顺序，把多行元素按对角线方式送入比较器树，在不实现精确 top-`K` 硬件的前提下，近似地产生每周期最小的若干个输出。论文真正想说明的是：在线得到“足够好”的结构信息就已经足够了。一套机制通过改善复用降低访存流量，另一套机制通过抑制短行和归并依赖带来的空转来提高利用率。

## 设计

Slaws 建立在一个可重构稀疏加速器之上，基础架构可以在乘法器组内使用 Gustavson 数据流，在组间使用 `Outer-Product` 数据流；新的贡献则围绕这套骨架展开。

Pass-Aware 由三个阶段组成。第一步是 `Structure-Profiling`：它从 `A` 中采样一批行，把非零位置转成位图，压缩掉所有行都为零的位置，再对压缩后的位图做交集统计，得到一张记录行间重叠程度的 score table。第二步是 `Block-Reordering`：系统按照缓存容量把 `A` 切成多个块，从每个块采样若干行，估计块与块之间的相似度，再用贪心算法构造执行顺序，让相似块尽量相邻执行。这样做是为了抓住普通逐行执行无法保留的全局复用，因为缓存往往装不下相距很远但结构相似的区域。第三步是 `Pass-Generation`：它在一个块内部观察连续的若干行，判断是否应把这些行融合成一个 pass。其准则是比较两种收益与代价：共享 `B` 行带来的输入复用收益，以及同时保留更多部分和所带来的输出存储开销。一个 pass 内采用 `OutP`，不同 pass 之间则退回 `Gus`。

针对右矩阵的机制是 `Shuffle-Compare`。它不再把“一行对应一个乘法器”当成固定绑定关系，而是把多行中已排序的元素按对角线模式送入比较器树。一个小型调度器记录哪些位置已被消费，把剩余元素前移，再把新的尾部元素补进来，同时保持每一行内部的顺序不变。这个过程不能保证每周期都算出精确的 top-`K`，但足以近似得到最小的一批元素，从而持续向后端 merger 供给工作。最后由 `Task Allocator` 把这些机制串起来：它会根据当前 pass 的宽度选取最近的 2 的幂作为重构因子，并据此切分行和任务。

## 实验评估

实验方法由两部分组成：一是 `C++` 周期级精确模拟器，用来比较不同加速器；二是把新增控制逻辑综合到 `TSMC 28nm`、`1 GHz` 条件下，估算面积与功耗。工作负载来自 `SuiteSparse`：方阵做自乘，非方阵与其转置相乘；另外还补充了随机右矩阵和 `SpMM` 实验。主要对比对象包括 Spada、Feasta、只保留 Gustavson 数据流的 Feasta 变体，以及运行 `cusparseSpGEMM_compute()` 的 `Nvidia RTX 5080`。

在主 `SpMSpM` 负载上，`Slaws-POS` 平均比 Feasta 快 `1.46x`，比 Spada 快 `1.43x`，比 Gustavson-only 的 Feasta 变体快 `1.51x`。这些提升并不是均匀发生的。像 `cari`、`msc10848` 这类结构较规则的矩阵中，Spada 仍然有竞争力，因为行长与真实模式相似性相关性较强；而在 `email-Enron`、`dbir2`、`ca-CondMat` 这类更不规则的矩阵上，Slaws 的优势更明显，因为它不会被单纯的行长误导，而且 Shuffle-Compare 还能减少乘法器等待和 merger 背压。对一些存在远距离相似块的矩阵，块重排几乎把 `B` 矩阵流量减半。

我认为论文最扎实的部分是开销分析。`Block-Reordering` 的时间开销低于 kernel 执行时间的 `2%`，采样新增的 `A` 流量平均只占原始 `A` 流量的约 `5%`。这正是它拿来反驳 Gamma 与 Bootes 这类软件重排方法的依据：论文报告它们的预处理时间分别是一轮 kernel 的 `6178x` 与 `4872x`，而性能收益却远没有到这个量级。这个对比让“低精度在线近似比高精度离线重排更实用”的主张变得可信。论文还报告，当右矩阵改成随机矩阵时，Slaws-POS 相对 Feasta 仍有 `1.45x` 提升；在 `SpMM` 中也有 `1.30x` 提升，主要来自 Pass-Aware 降低访存流量。即使面对带宽高出 `7.5x` 的 RTX 5080，Slaws 平均仍快 `1.55x`，只是像 `cari` 这类更稠密、更偏计算受限的矩阵上优势会缩小。

## 创新性与影响

相较于 _Li et al. (ASPLOS '23)_，Slaws 的新意在于拒绝把行长当成稀疏结构的充分摘要。相较于 _Zhong et al. (ASPLOS '24)_，它把固定编译期并行度推进成了运行时结构分析与 pass 形成。相较于 _Zhang et al. (ASPLOS '21)_ 和 _Yadav and Asgari (MICRO '25)_，它追求的不是更强的离线重排最优性，而是一个开销足够低、可以按 kernel 使用的硬件方法。

因此，这篇论文对做稀疏线性代数、图计算内核和其他不规则访存加速器的人都值得看。它提出的并不只是一个新数据流，而是一个更强的主张：如果希望稀疏加速器同时拥有通用性与低流量，在线结构分析本身就应该成为硬件的一部分。

## 局限性

第一类局限来自模型本身。论文在估计输出复用时，假设矩阵 `B` 近似为随机稀疏矩阵，这让硬件分析变得可实现，但并不保证适用于所有真实工作负载。块重排和行融合也都是贪心近似，因此即使开销很低，Slaws 仍可能错过全局最优的执行顺序。

第二类局限来自评估范围。大部分加速器比较建立在模拟器之上，而不是真实流片系统；GPU 对比也只覆盖了一种软件路径和一代设备。对于结构较规则或较稠密、缓存抖动与负载失衡不那么严重的矩阵，收益会明显变窄。最后，Shuffle-Compare 本身是有意做成近似机制的；论文也承认，在某些极端失衡的矩阵上，精确 top-`K` 仍会再快一些，这意味着 Slaws 为了节省硬件成本，确实放弃了部分上限性能。

## 相关工作

- _Li et al. (ASPLOS '23)_ — Spada 通过行长窗口来切换数据流，而 Slaws 认为直接分析重叠关系才是更可靠的稀疏模式信号。
- _Muñoz Martínez et al. (ASPLOS '23)_ — Flexagon 提供了多数据流硬件骨架，但 Slaws 在其之上进一步加入了在线结构分析与负载均衡。
- _Zhang et al. (ASPLOS '21)_ — Gamma 在软件侧通过行重排优化 Gustavson 风格乘法，而 Slaws 追求的是可按单次 kernel 使用的低开销硬件辅助重排。
- _Zhong et al. (ASPLOS '24)_ — Feasta 提供了灵活的稀疏张量加速器，但其并行度是预先设定的；Slaws 则根据采样到的稀疏模式在运行时决定 pass 和复用机会。

## 我的笔记

<!-- empty; left for the human reader -->

---
title: "Quake: Adaptive Indexing for Vector Search"
oneline: "Quake 用代价模型持续分裂或合并热分区，再用几何化 recall 估计按查询提前停止扫描，从而在动态向量检索中同时守住低延迟和目标召回。"
authors:
  - "Jason Mohoney"
  - "Devesh Sarda"
  - "Mengze Tang"
  - "Shihabur Rahman Chowdhury"
  - "Anil Pacaci"
  - "Ihab F. Ilyas"
  - "Theodoros Rekatsinas"
  - "Shivaram Venkataraman"
affiliations:
  - "University of Wisconsin-Madison"
  - "Apple"
  - "University of Waterloo"
conference: osdi-2025
code_url: "https://github.com/marius-team/quake"
tags:
  - databases
  - ml-systems
  - memory
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Quake 是一个面向动态工作负载的 partitioned ANN index。它一边用延迟代价模型持续重塑分区结构，一边用几何化的 recall estimator 按查询决定该扫多少分区，还把扫描过程做成 NUMA-aware 的并行执行，因此在数据和访问热点不断变化时，仍能把 partitioned index 的更新优势和较低查询延迟同时保住。

## 问题背景

这篇论文切中的，是向量数据库里一个很现实的结构性矛盾。HNSW、DiskANN、SVS 这类 graph index 在静态检索上通常很强，但插入和删除代价高，因为图结构维护本身就是随机访问密集型操作。Faiss-IVF、ScaNN 这类 partitioned index 更容易更新，写入路径也更顺，但它们在动态和偏斜工作负载下会迅速老化。一旦某些区域变热、或者新向量不断涌入少数区域，分区会失衡，查询需要扫描更多数据，延迟随之上升。

作者强调，这不是实验室里人造出来的边角问题。他们构造的 Wikipedia 工作负载包含 103 个月的页面增长和 page-view 变化，既有明显的 read skew，也有 write skew。现有维护方法，比如把大分区切开、或者周期性重聚类，并不能真正解决问题，因为 query-time 参数通常还是静态的。分区结构一变，原先手工调好的 `nprobe` 就不再合适：不调高就掉 recall，调得保守又会把延迟重新拉高。于是，真正的问题不是单独“怎么维护索引”，也不是单独“怎么做 early termination”，而是如何在数据和访问模式持续变化时，仍然以固定 recall target 保持低延迟。

## 核心洞察

Quake 的核心判断是：partitioned index 在动态场景下要想继续有竞争力，必须同时自适应两件事，分区布局和每个查询的扫描预算。前者不该只看分区大小，而应看某个分区到底给整体查询延迟贡献了多少成本；后者不该由一个全局固定的 `nprobe` 决定，而应由当前索引几何形状和查询过程中间 top-k 结果共同决定。

这个组合很关键，因为它保留了 partitioned index 最有价值的结构优势，也就是更新便宜、扫描顺序化，同时正面处理了它在 drift 场景下的两个主要失效模式：热点大分区，以及过时的 `nprobe`。论文的第三个观察则是，partitioned index 相对 graph index 剩下的搜索差距，很大一部分其实是 memory-bandwidth 问题。一旦查询被表达为“扫哪些分区”，NUMA-aware 的数据放置和调度就能把更多代价转化为本地内存带宽，而不是跨节点访存。

## 设计

Quake 是一个 multi-level 的 partitioned index。最底层把真实向量划成若干互不重叠的分区，每个分区有一个 centroid；上层再对这些 centroid 递归分区，因此查询可以自顶向下逐层缩小范围，而不必每次都与全部底层 centroid 比较。插入会沿层级找到最近的叶子分区并追加进去；删除则通过一个映射定位向量所在分区，再立即做 compaction。

第一项核心机制是自适应维护。对每个分区 `(l, j)`，Quake 维护它的大小和一个滑动窗口内的访问频率，并用 `A_l,j * lambda(s_l,j)` 估计该分区给查询延迟带来的成本，其中 `lambda` 是离线 profile 出来的扫描延迟函数。全局代价就是所有层、所有分区成本之和。围绕这个模型，Quake 可以 split 热或过大的分区，merge 冷而小的分区，在顶层 centroid 太多时 add level，太稀疏时 remove level。真正有系统味道的地方在于它的决策流程：estimate、verify、再 commit 或 reject。某个 split 或 merge 先按轻量近似去打分，实际执行后再测量真实生成的分区大小，并重新计算代价变化；如果实际收益不再成立，就回滚。这一步是论文很重要的安全阀，因为许多维护动作在“平均意义上”看似有利，实际却可能产生一个很大的孩子分区和一个很小的孩子分区，反而让延迟上升。split 之后，Quake 还会对附近分区做局部 k-means refinement，以减少 overlap。

第二项核心机制是 Adaptive Partition Scanning，也就是 APS。对一个查询，Quake 先挑出一个初始比例的候选分区，先扫描最近的那个分区，得到当前 top-k 半径，再估计其余候选分区包含真实近邻的概率。这个概率来自一个几何近似：把查询邻域视为一个 hypersphere，再估计这个球体有多少体积落在每个分区内。之后 APS 按概率从高到低继续扫描，直到累计 recall 估计跨过目标值。为了让这件事可用，Quake 预计算了昂贵的 beta-function 数值，并且只有在当前第 `k` 个近邻距离缩小到足够明显时，才重算一次概率。在 multi-level 配置里，上层统一用 99% recall target 搜索，以避免误差逐层放大。

第三项机制是 NUMA-aware 查询执行。Quake 把分区分散到不同 NUMA node，上绑定 partition affinity 到固定 worker core，以便利用局部性和 cache reuse；worker 只在同一 NUMA node 内做 work stealing。主线程周期性合并各 NUMA node 的局部 top-k 结果，再调用 APS 判断是否已经达到目标 recall；如果达到了，就直接终止剩余分区扫描。这样一来，early termination 不再只是一个单线程技巧，而是和带宽利用绑定在一起的并行执行策略。

## 实验评估

实现约 7,500 行 C++，并提供 Python API。实验设计也比较扎实，确实在测论文声称要解决的问题，而不是一个容易取胜的玩具场景：包括从页面增长与 page views 构造的 Wikipedia-12M，包含插入和删除的 OpenImages-13M，MSTuring 的静态与动态工作负载，以及 SIFT 微基准；大规模实验跑在一台四路 Xeon 服务器上，用来验证 NUMA 效果。

最强的结果出现在动态工作负载上。在 Wikipedia-12M 上，Quake-MT 的搜索总时间是 `1.53` 小时，而 DiskANN 是 `12.11` 小时，Faiss-IVF 则高达 `165.8` 小时；论文把这一类结果概括为，相对 HNSW、DiskANN、SVS，Quake 在动态负载上的搜索延迟低 `1.5x-13x`，更新延迟低 `18x-126x`。在 OpenImages-13M 上，Quake-MT 的搜索时间是 `0.03` 小时，而 DiskANN 是 `0.22` 小时；图索引在 delete consolidation 上付出的代价尤其明显。APS 本身也达到了作者宣称的目标：在 SIFT1M 上，它与 oracle 的 `nprobe` 选择器相比，只多出 `17%-29%` 的延迟，但完全不需要 offline tuning；把调参成本算进去后，Auncel、LAET 和 SPANN 都不如它。NUMA 部分也不是装饰：在 MSTuring100M 上，论文报告相对单线程大约 `20x` 的查询延迟下降，相对非 NUMA-aware 并行版本也有约 `4x` 的下降，扫描吞吐最高接近 `200 GB/s`。

实验还有一个优点是对自己不利的场景也讲清楚了。在静态只读的 MSTuring10M 上，SVS 仍然更快，搜索时间 `0.33` 小时，而 Quake-MT 是 `0.63` 小时。也就是说，这篇论文更准确的结论不是“partitioned index 普遍比 graph index 好”，而是“在动态和偏斜足够强时，partitioned index 可以通过自适应维护与查询控制重新变得有竞争力”。

## 创新性与影响

相对于 _Xu et al. (SOSP '23)_ 的 SPFresh/LIRE，Quake 不再依赖纯 size-threshold 的维护规则，而是把访问频率和扫描代价纳入统一 cost model，并在真正提交动作前做一次验证。相对于 _Li et al. (SIGMOD '20)_ 的 LAET 和 _Zhang et al. (NSDI '23)_ 的 Auncel，Quake 不需要为每个数据集或 recall target 做训练与校准，而且在索引结构本身持续变化时依然成立。相对于 _Guo et al. (ICML '20)_ 的 ScaNN，它把动态维护和 query adaptivity 当成一等设计目标，而不是默认索引结构基本静态。

它的影响也很直接。推荐系统、语义检索和 RAG 背后的向量数据库，往往既想要 partitioned index 的低更新成本，又想逼近 graph index 的查询时延。Quake 没有提出一种全新的 ANN 基元，但它给出了一个很可信的系统设计点：partitioned index 只要把维护、scan budget 和 NUMA 执行一起做成自适应，就能在真实线上更常见的动态场景里站住脚。

## 局限性

Quake 并不是 graph index 的通用替代品。论文自己的结果已经说明，在静态、只读、查询为主的场景里，强实现的 graph index 仍然可能更快。Quake 的优势明确绑定在动态与偏斜负载上。

此外，系统仍有几个重要参数需要人为设定。APS 的初始候选比例 `f_M` 对性能影响最大，split/merge 阈值 `tau` 决定索引演化得有多激进。作者认为默认值在他们测试的负载上已经足够稳定，但这毕竟还是参数，不是完全自调的控制律。最后，当前实现把 search、update 和 maintenance 串行执行；论文明确把 copy-on-write 并发、filtered search、distributed placement、compression-aware cost model 等都留作未来工作，而没有在本文中验证。

## 相关工作

- _Xu et al. (SOSP '23)_ — SPFresh 针对流式向量检索做增量 split 和 delete，而 Quake 进一步用 cost model 选择维护动作，并加入自适应的 query-time recall 控制。
- _Li et al. (SIGMOD '20)_ — LAET 通过学习模型预测每个查询何时停止扫描；Quake 则使用解析式 recall estimator，避免离线训练。
- _Zhang et al. (NSDI '23)_ — Auncel 同样利用几何信息估计 recall，但 Quake 把 recall estimation 和索引维护联动起来，并指出 Auncel 的校准在变化中的索引上过于保守。
- _Guo et al. (ICML '20)_ — ScaNN 是非常强的 partitioned baseline，主要优化静态近似检索；Quake 关注的是在 insert、delete 和 skew 持续存在时怎样维持这类索引的性能。

## 我的笔记

<!-- 留空；由人工补充 -->

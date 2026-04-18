---
title: "Achieving Low-Latency Graph-Based Vector Search via Aligning Best-First Search Algorithm with SSD"
oneline: "PipeANN 打破 best-first search 严格按步执行的 compute/I/O 次序，把 SSD 读取流水化，并用两阶段动态 pipeline 把吞吐损失压回去。"
authors:
  - "Hao Guo"
  - "Youyou Lu"
affiliations:
  - "Tsinghua University"
conference: osdi-2025
tags:
  - ml-systems
  - storage
  - databases
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

PipeANN 是一个把 graph ANNS 放到 SSD 上仍尽量维持低延迟的系统，它不再把 best-first search 当成“读一批、等完、展开、再读下一批”的刚性循环。它的核心算法 PipeSearch 会在更早一批读取尚未完全展开时，就从当前 candidate pool 中继续异步发起新的 SSD 读取；随后 PipeANN 再用两阶段动态 pipeline 和更保守的 refill 策略，把大部分延迟收益保住，同时避免吞吐完全崩掉。

## 问题背景

Graph-based ANNS 在全索引驻留内存时可以在高精度下提供很低的查询延迟，但同样的行为放到 SSD 上就不成立了。论文先给出一个直接的经验事实：在 SIFT 数据集上，DiskANN 在 0.9 recall 下的延迟是内存版 Vamana 的 4.18 倍，在 0.99 recall 下也仍有 3.14 倍差距。这个差距并不是学术上的小瑕疵，因为作者关心的正是十亿级向量检索场景，例如推荐系统和 RAG；这些场景往往只有大约 10 ms 的延迟预算，而省下来的每一点时间都可以换成更高的 recall。

论文的判断是，问题不只是“SSD 比 DRAM 慢”。真正的瓶颈来自 SSD 特性与 graph index 所采用的 best-first traversal 之间的不匹配。Best-first search 的执行方式是：从当前 top-W 的未展开候选里挑一批，读出来，等整批返回，展开它们的邻居，再决定下一批。对 SSD 而言，这个节奏会同时浪费两类机会。第一，跨搜索步的 compute 和 I/O 被串行化了，尽管 SSD 读取已经长到足以成为主导开销；在 greedy search 中，I/O 延迟是 compute 的 7.43 倍，即便 W = 8，compute 也仍有 I/O 时间的 45.6%。第二，每一步都要同步等待整批 I/O 的尾部完成，因此 SSD 的并行能力没有真正吃满；测得的 pipeline utilization 在 W = 8 时只有 76%，在 W = 32 时更只有 58%。

## 核心洞察

论文最重要的命题是：best-first 的顺序有助于减少无效读取，但它并不是 graph search 收敛所必需的。图索引里的同一个向量通常有多条可达路径，因为每个节点可能有多个 in-edge；因此，best-first search 只是近似出一条较短搜索路径的办法，并不像 B+-tree 那样代表唯一正确的遍历序。

这个观察揭示了作者所说的 pseudo-dependency。系统要决定下一次 I/O，其实只需要内存里的 candidate pool，也就是一组向量 ID 与近似距离；它并不必须等待当前所有 I/O 全部结束，也不必等之前读到的每个向量都完成 neighbor exploration。只要打破这层伪依赖，系统就可以把 compute 和 I/O 重叠起来，同时让 SSD 上保持更多 in-flight requests。第二个关键观察是，speculative I/O 的浪费在整个搜索过程中并不均匀：早期的“approach phase”最糟，因为搜索还在快速接近目标；后期的“converge phase”则会好很多，因为 candidate pool 里已经积累了更多真实 top-k 邻居。这就为动态调整 pipeline width 提供了依据。

## 设计

PipeSearch 保留了熟悉的 candidate pool `P`、explored set `E` 和类似 beam width 的 pipeline width `W`，但改写了执行调度。只要 I/O 队列没满，它就为 `P` 中当前最近、但还没读取过的向量发起一次读取。与此同时，它独立地处理已经读回但尚未展开的向量集合 `U`：选择其中最近的向量，展开其邻居，用内存中的 PQ distance 把邻居插入 `P`，再把 `P` 修剪回长度 `L`，最后轮询 I/O completion。换句话说，算法不再受“搜索步边界”约束，磁盘读取与邻居展开是机会主义地并行推进的。

PipeANN 则把这个基础低延迟算法补成一个吞吐更高的完整系统。它在磁盘上按 adjacency-list record 存储图，在内存中保存 PQ-compressed vectors 以便快速给邻居打分，并额外维护一个小型、采样得到的 in-memory graph index 来选择 entry points。整个搜索被分成两个阶段。Approach phase 中，PipeANN 先用内存索引把起点推进到更接近 query 的位置，并把 PipeSearch 的固定 pipeline width 设成 4，因为这时 speculative 读取最容易浪费。进入 converge phase 后，系统开始估计“已经有效召回了多少好候选”，并在完成的读取仍大概率返回 candidate pool 中保留下来的向量时扩大 pipeline；默认动态策略是在该比例超过 0.9 时把 `W` 增加 1。

另一个关键优化是：当多个读取几乎同时完成时，PipeANN 不会立刻把队列重新塞满。若直接暴力 refill，就会产生大量“已经读回但还未展开”的向量，使后续 I/O 决策缺失太多邻居信息。PipeANN 改成了交替策略：发起一个新读请求，展开一个向量，更新候选，再重新决策。这样可以把每次 I/O 决策所缺失的信息量限制在一个较低范围内。实现上，系统使用带 SQ polling 的 `io_uring`，把第一次 SSD miss 与每查询一次的 PQ table 初始化重叠起来，并用 non-temporal AVX-512 load 避免初始化过程污染 cache。

## 实验评估

实验规模足以支撑论文关于“低延迟”的主论点。在 100M 级数据集上，PipeANN 在 0.9 recall10@10 下的平均延迟分别只有 DiskANN 的 39.1% 和 Starling 的 48.5%，而且在高 recall 区间还比 SPANN 低 70.6%。这些数字并不是靠弱基线拿到的：作者让 PipeANN、DiskANN 和 Starling 共用同一批 graph indexes，统一把 DiskANN 和 Starling 换成 `io_uring`，并分别为每个基线选择最优 latency 配置。

吞吐结果则更有层次，这反而提高了论文的可信度。在 100M 数据集、0.9 recall 条件下，PipeANN 的吞吐最高，平均比其余 on-disk 系统高 1.35 倍，因为这时磁盘带宽还没被打满，而 pipelining 缩短了关键路径。但在 0.99 recall 时，Starling 的吞吐可能反超 PipeANN，因为 Starling 通过 record reordering 降低了每次搜索所需的平均 I/O，而 PipeANN 仍然要为 speculative reads 付费。论文并没有把自己的延迟优化包装成对所有设计点都绝对占优的方案。

十亿级结果是全文最重要的 headline numbers。对 SIFT1B 和 SPACEV1B，PipeANN 在 0.9 recall 下分别达到 0.719 ms 和 0.578 ms 延迟；其中在 SIFT 上，PipeANN 的延迟只有 DiskANN 的 35.0%，吞吐则高 1.71 倍。与内存版 Vamana 相比，PipeANN 仍然更慢，但在高 recall 时差距已经缩小到可接受范围：0.9 recall 下，SIFT 上慢 2.02 倍，DEEP 上只慢 1.14 倍。Ablation 也与设计叙事一致：单独使用 PipeSearch 会大幅降低延迟但损失吞吐；逐个 refill 的算法优化能把吞吐拉回来；dynamic pipeline 主要在高 recall 下更有效，因为那时 converge phase 持续得更久。

## 创新性与影响

相对于 _Subramanya et al. (NeurIPS '19)_，PipeANN 仍然属于 DiskANN 那一类 graph index 体系，但它改变的是搜索调度本身，而不是单纯把 batch 放宽。相对于 _Wang et al. (SIGMOD '24)_，它的主要手段不是通过布局重排减少 I/O 次数，而是通过把不可避免的 I/O 与 compute 重叠来降低延迟，这与 Starling 的方法基本正交。相对于 _Chen et al. (NeurIPS '21)_，它试图在不放弃 graph search 细粒度剪枝能力和高 recall 吞吐优势的前提下，逼近 cluster-based index 的低延迟特性。

这篇论文最可能影响的是那些既需要高 recall、又无法承受全内存索引成本的 vector-search 基础设施。它并没有发明一种新的 index structure，而是提出了一种与 SSD 特性对齐的 graph traversal 调度方式。这个贡献是实质性的，因为它把系统瓶颈从“如何造更好的图”重新表述成“不要再按 DRAM 时代的顺序执行图搜索算法”。

## 局限性

这套方法的主要局限也写在方法本身里：speculative reads 终究仍是 speculative。PipeANN 能减少 I/O 浪费，但不能把它消灭，所以在低 recall 时，它可能输给理想化的 greedy best-first 实现；在很高 recall 时，它也可能在吞吐上输给采用 record reordering 的 Starling。论文还明确展示了低 recall 是 PipeANN 最不像内存系统的时候：在 SIFT100M 的 0.8 recall 上，它比 Vamana 慢 3.38 倍，因为这时搜索大部分时间都落在 approach phase，放宽 pipeline 还帮不上太多忙。

它还有部署边界。对十亿级数据集，PipeANN 仍需要不到 40 GB 的 DRAM，主要用来存 PQ-compressed vectors 和采样得到的 in-memory graph。实验环境是单机、单块 NVMe SSD、只读索引，因此它并没有回答更新代价、多 SSD 条带化，或在线服务与后台维护混跑时的行为。论文声称相同思路也可迁移到 RDMA 或 CXL 支撑的 remote memory，但这一点目前仍停留在推理层面，而不是实现结果。

## 相关工作

- _Subramanya et al. (NeurIPS '19)_ — DiskANN 奠定了 SSD-resident graph ANNS 的标准设计与 best-first beam search，而 PipeANN 保留图模型但去掉了严格的逐步 compute/I/O 次序。
- _Wang et al. (SIGMOD '24)_ — Starling 通过 record reordering 和更好的 entry-point selection 来降低搜索成本；PipeANN 则通过异步流水线和动态调度来压低延迟。
- _Chen et al. (NeurIPS '21)_ — SPANN 采用 cluster-based 的磁盘布局，使关键路径上只剩一次并行磁盘读取，用更粗粒度但更 I/O 友好的搜索换取低延迟。
- _Zhang et al. (OSDI '23)_ — VBASE 在带标签的向量检索里观察到两阶段、relaxed monotonicity 的现象；PipeANN 借用了类似的两阶段视角，来决定何时可以安全地放大 speculative pipeline。

## 我的笔记

<!-- 留空；由人工补充 -->

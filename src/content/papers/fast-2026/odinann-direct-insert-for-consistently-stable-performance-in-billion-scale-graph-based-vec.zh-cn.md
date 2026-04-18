---
title: "OdinANN: Direct Insert for Consistently Stable Performance in Billion-Scale Graph-Based Vector Search"
oneline: "OdinANN 用直接插入替代批量 merge，并用无 GC 的页内更新合并与近似并发控制，把十亿级磁盘图向量检索的更新扰动摊平。"
authors:
  - "Hao Guo"
  - "Youyou Lu"
affiliations:
  - "Tsinghua University"
conference: fast-2026
category: indexes-and-data-placement
tags:
  - storage
  - databases
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

OdinANN 的核心观点是，磁盘上的 graph ANN index 不应该再把插入先缓存在内存里，等攒够一批后再 merge 到磁盘。它把每个新向量直接插入 on-disk graph，再用无 GC 的 out-of-place 更新和近似并发控制把这件事做得足够便宜。结果是，在持续更新下，它仍能保持 graph navigation 的精度优势，同时让搜索延迟稳定得多。

## 问题背景

十亿级 ANN 服务越来越常见于持续变化的数据集：电商商品库会更新，web search 的 embedding 会不断重算，RAG 语料也会持续注入新向量。已有的 on-disk graph index 通常采用 buffered insert：把新向量先放进内存索引，查询时同时搜索内存和磁盘索引，等缓冲区达到阈值后，再把这些向量批量 merge 进磁盘图。论文指出，这种做法虽然降低了单次更新的写入压力，却同时引入了三个新的系统问题。

第一，merge 会直接干扰前台搜索。merge 期间，系统必须再次遍历磁盘图，为缓冲中的向量寻找邻居，这会和用户查询争抢 SSD 带宽；在 SIFT100M 上，中位搜索延迟在 merge 阶段平均升高到 `1.54x`。第二，buffered insert 很吃内存，因为系统不仅要保留 in-memory index，还要缓存 merge 所需的磁盘更新；论文给出的例子是，把 `3%` 的向量 merge 进十亿级索引需要 `125 GB` 内存。第三，批处理的收益并没有想象中高。merge 最贵的步骤仍然是“为每个新向量单独查找邻居”，这一步几乎无法高效 batch 化，所以吞吐即使在很大的 batch 下也大致卡在 `3000 QPS`。

看起来直接插入是自然替代方案，因为它把更新代价摊平了，也避免了庞大的内存层。但朴素的 direct insert 实现根本不可用。每次插入不仅要写入新向量自身的 record，还要改动几十到上百个邻居 record，形成大量分散的随机 SSD 写。更糟的是，插入本身要先搜索图来找邻居，如果使用传统加锁方式，频繁访问的 near-root 节点会成为严重的串行化热点。于是，论文真正回答的问题不是“graph ANN 能否在线更新”，而是“能否把 direct insert 做到足够稳定，让前台搜索不再随着更新周期剧烈抖动”。

## 核心洞察

这篇论文最值得记住的命题是：只要系统不再把“操作级别的精确隔离”当成不可放松的前提，direct insert 就能变得可行。OdinANN 抓住了 on-disk graph ANN index 的两个结构性事实。第一个是物理层面的：record 是 fixed-size 的，因此更新后的 record 可以搬到同页的空槽里，让一次 page write 吸收多个逻辑 record update，而不需要 log-structured layout 那样的垃圾回收。第二个是语义层面的：ANN search 和 neighbor selection 本来就是 approximate 的，因此 insert 和 search 并不需要整个图的全局一致快照，只需要每个 record 自身是一致的、候选邻居集合是“足够合理”的近似快照。

这一定义方式很关键，因为它重写了问题边界。buffered insert 试图通过 batching 去隐藏更新成本；OdinANN 则是先降低每次插入的固有代价，再放松并发控制，让剩余代价不会长期阻塞其他请求。它并不承诺事务式的精确图维护，而是主张：ANN 本来就接受的近似预算，可以被有意识地花在系统目标上，用来换取更少的写入和更短的 critical section。

## 设计

OdinANN 延续了常见的 on-disk graph layout：每个 fixed-size record 保存一个向量和最多 `R` 个出邻居 ID，DRAM 中保存 PQ-compressed vectors 以支持导航。它的第一个核心机制是 GC-free update combining。系统在磁盘上做 space overprovision，让每个 page 留出若干 free record slots。插入时，OdinANN 不在原地修改新向量及其邻居的 record，而是把新版本写到这些空槽中，尽量把多次更新收敛到同一个 page，然后更新内存中的 ID-to-location table，并立刻把旧槽位回收。因为 record 大小固定，旧位置不是需要专门 compact 的垃圾，而只是可复用的空洞。其分配策略会优先使用空页，其次使用插入搜索路径上已经被读入缓存的 partial-empty pages，最后才新分配页面。论文分析表明，在默认“页内大约半满”的设置下，这种设计大致带来 `2x` 的空间消耗和 `2x` 的写放大，但避免了 log-structured 方案频繁 GC 的副作用。

第二个核心机制是 approximate concurrency control。搜索线程只在读取某个 record 的 ID-to-location 映射时持有 per-record lock，这保证了单个 record 的一致快照，但不保证整个 graph 的一致快照。插入线程先搜索得到候选邻居，接受这只是一个 approximate snapshot；随后再锁住相关 record 和 page，重新加载邻居 record 防止 update loss，并发布新 record。于是，一个 search 允许在遍历早期看不到某个刚插入的 record，却在后续步骤里又能看到它。论文认为，这种行为是可以接受的，因为 approximate graph navigation 本来就不依赖 serializable execution。

为了继续缩短 critical path，OdinANN 还做了两个优化。第一，它使用 write-back page cache 和后台 I/O 线程，让大多数 reload 直接来自 cache，record update 也先写回 cache，再异步落盘，而不是在锁内同步完成。第二，它把 DiskANN 中 `O(R^2)` 的 pruning 改成 delta pruning：先只检查“新插入邻居”和现有邻居之间的关系，只有必要时才退回完整 pruning，因此大多数情况下插入端 pruning 的复杂度更接近 `O(R)`。删除路径则采取另一套策略：OdinANN 只在内存里缓冲 deleted IDs，用 dynamic candidate pool 保证删除节点仍可辅助导航、但不会污染返回结果，再周期性执行 lightweight 的 two-pass merge 来重写边。这一点很说明问题：论文并不是说所有更新都该 direct，而是说 insert 才是最不适合 buffering 的那一类更新。

## 实验评估

实验和论文声称的目标场景是对齐的。作者在一台配有 `2 x 28-core` Xeon、`512 GB` RAM 和 `3.84 TB` SSD 的服务器上，对比 OdinANN、DiskANN 和 SPFresh，数据集包括 SIFT100M、DEEP100M 和 SIFT1B。最关键的结果是“更新期稳定性”。在 SIFT100M 上，OdinANN 的中位搜索延迟波动只有 `1.07x`，而 DiskANN 是 `2.44x`；它的平均 P50 延迟比 DiskANN 低 `13.3%`。尾延迟收益更明显：平均 P90 和 P99 分别低 `34.6%` 和 `19.5%`。相对 SPFresh，OdinANN 的平均 P50/P90/P99 又分别低 `51.7%`、`36.5%` 和 `28.4%`，同时还保持了更高的精度。

吞吐和内存结果也支持同一个结论。在 SIFT100M 上，OdinANN 的搜索吞吐是 DiskANN 的 `1.15x`、SPFresh 的 `1.99x`；峰值内存则只有 DiskANN 的 `29.3%`，因为它不再需要巨大的 merge 内存态。到十亿级数据集时，系统可以同时达到大约 `5000 QPS` 的搜索吞吐和 `1100 QPS` 的插入吞吐，同时把中位搜索延迟稳定在约 `3 ms`；即便 DiskANN 把 merge 阈值降到 `3%`，其内存占用仍然超过 `200 GB`。论文的 breakdown analysis 也很有价值，因为它把几个机制的贡献拆开了：异步 I/O 主要降低延迟，页内 out-of-place update 带来最大的吞吐提升，delta pruning 则把优化后的 direct insert 进一步推到约 `2000 QPS`、`11.1 ms` 中位插入延迟。

论文也没有回避代价。由于更新路径被放松，OdinANN 的索引质量略有下降：在 DEEP100M 的大规模更新后，为了达到和 DiskANN 相同的 recall，它大约需要多读 `4.5%` 的磁盘页。这当然是真实代价，但相比它换来的稳定性和内存优势，这个代价是可接受的，因此实验整体上较有说服力。

## 创新性与影响

相对于 _Subramanya et al. (NeurIPS '19)_，OdinANN 的新意不在新的 graph search algorithm，而在 on-disk graph index 的 update path。相对于 _Xu et al. (SOSP '23)_，它说明 graph-based index 可以在保持搜索质量优势的同时，避免 cluster-based 可更新系统中常见的 buffered-merge 抖动。相对于 _Wang et al. (SIGMOD '24)_ 这类主要面向静态磁盘图搜索的工作，OdinANN 把关注点放在更难的 online-update 场景。

因此，这篇论文对 vector database、embedding retrieval infrastructure、以及需要持续刷新向量语料的系统构建者都很重要。我预计它未来被引用时，更多是因为它传达了一个系统层面的判断：approximate search structure 并不需要在所有地方都维持 database-grade isolation，只要设计得当，把这部分“精确性余量”花在写入合并和并发控制上，就能在十亿级规模下换来稳定性能。这更像是一种新的更新机制，而不是新的 ANN 目标函数或纯测量研究。

## 局限性

OdinANN 为稳定性付出的代价并不小。最明显的是存储放大：默认配置大约使用 `2x` 的磁盘空间。作者用 SSD 和 DRAM 的价格对比来为它辩护，但在真实部署中，这依然是需要认真核算的容量成本。其次，放松并发控制确实会让 graph quality 略有下降；论文用“达到同样 recall 需要更多页读取”来间接测量这一点，而在比 SIFT、DEEP 更对抗性的插入序列下，这个代价可能更明显。

删除路径也没有插入路径那么漂亮。delete 仍然是 buffered 的，不是 direct 的，而且 merge 时为了满足内存预算，系统可能只加载每个 deleted node 的部分邻居，这意味着最终精度和内存占用之间还要继续权衡。更广义地说，论文的实验集中在单机、单 SSD 场景上，这正是它的目标包络，但也意味着多设备、更强 I/O 干扰、或者更严格持久性要求下的表现，仍然留待后续工作回答。

## 相关工作

- _Subramanya et al. (NeurIPS '19)_ — DiskANN 奠定了 on-disk graph ANN 的基本形态，而 OdinANN 继承这一搜索骨架后，重点解决的是在线更新稳定性而不是静态索引构建。
- _Chen et al. (NeurIPS '21)_ — SPANN 代表了十亿级 ANN 的 cluster-based 路线，而 OdinANN 论证了 graph-based index 也可以在不放弃细粒度搜索行为的前提下支持更新。
- _Xu et al. (SOSP '23)_ — SPFresh 在 SPANN 上增加了 in-place update；OdinANN 则处理 graph index 中更难的邻居维护问题，并在延迟和精度上取得更强结果。
- _Wang et al. (SIGMOD '24)_ — Starling 优化的是 disk-resident graph index 的 I/O 效率，而 OdinANN 基本是正交的，因为它关注的是“索引持续在线更新时，如何维持稳定表现”。

## 我的笔记

<!-- empty; left for the human reader -->

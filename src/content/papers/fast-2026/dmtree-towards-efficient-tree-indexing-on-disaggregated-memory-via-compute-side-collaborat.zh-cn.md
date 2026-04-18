---
title: "DMTree: Towards Efficient Tree Indexing on Disaggregated Memory via Compute-side Collaborative Design"
oneline: "DMTree 把 fingerprint lookup 和 leaf locking 从 memory server 挪到 compute peer，使 disaggregated-memory tree index 能同时兼顾 RDMA bandwidth 与 IOPS。"
authors:
  - "Guoli Wei"
  - "Yongkun Li"
  - "Haoze Song"
  - "Tao Li"
  - "Lulu Yao"
  - "Yinlong Xu"
  - "Heming Cui"
affiliations:
  - "University of Science and Technology of China"
  - "The University of Hong Kong"
  - "Anhui Provincial Key Laboratory of High Performance Computing, USTC"
conference: fast-2026
category: indexes-and-data-placement
code_url: "https://github.com/muouim/DMTree"
tags:
  - disaggregation
  - memory
  - rdma
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

DMTree 是一个面向 disaggregated memory 的 tree index。它把 leaf data 继续放在 memory server 上，但把细粒度的 metadata 路径挪到了 compute server：fingerprint table 和 leaf lock 都由 compute peers 协同存放与访问，因此 memory server 主要承担真正需要远程内存的数据读写。作者在 `100 Gbps` RDMA 集群上报告，DMTree 相比已有 DM range index 最高可获得 `5.7x` 吞吐提升，而且 point operations 和 scans 都保持较强表现。

## 问题背景

论文关注的是 disaggregated memory 的一个核心矛盾。compute server 拥有大量 CPU core，却只有有限内存；memory server 拥有大容量内存，却只有很弱的 CPU。one-sided RDMA 让这种架构很有吸引力，但也让 index 设计同时暴露在两种不同瓶颈下：memory side 的 RDMA bandwidth 和 RDMA IOPS。

现有方案各自只解决了一半问题。Sherman、ROLEX 这类 B+-tree 或 learned index 把一个范围内的 key-value entries 连续放在 leaf 里，扫描时很自然，但读取或更新单个 entry 时往往要把整个 leaf 拉回来，于是产生 read amplification，带宽很快被耗尽。SMART 这类 ART 方案则反过来，它能精确定位单个 entry，point lookup 不再有明显 read amplification，但 scans 和 inserts 需要许多小粒度 RDMA，请求数暴涨，IOPS 反而成为瓶颈。CHIME 和 FP-B+-tree 这类混合方案虽然把连续 leaf 和精准 in-leaf locating 结合起来了，但仍然要把 fingerprint table 访问和 leaf-node locking 发到 memory server，于是最容易放大的并不是数据本体，而是 control path 上那部分“小而频繁”的 metadata 操作。

论文的判断是，这首先是 metadata 放置错误，而不只是数据结构本身不够巧妙。memory server 本来就是多个 compute server 请求的汇聚点，所以它最先拥塞；而 compute servers 之间的 RDMA 资源却常常闲着。真正高性能的 DM index 应该把高 IOPS 的 control path 从 memory server 挪走，同时保留 tree 对 range operations 友好的连续布局。

## 核心洞察

这篇论文最重要的命题是：在 DM index 里，不同类型的工作应当按资源属性拆开。大块的 key-value storage 当然应该留在 memory server，因为真正的大对象就在那里；但 precise locating metadata 和 lock state 都很小、访问很频繁、又特别吃 IOPS，更适合放在 compute side，并由多个 compute servers 协同共享。

这样一来，设计空间就变了。DMTree 不再被迫在“连续 leaf 但浪费带宽”和“精确 leaf 但浪费 IOPS”之间二选一。它保留连续 leaf 来服务 scans，同时把让 point operations 变贵的 metadata 访问从 memory server 卸掉。这个思路成立的原因有两个：一是 fingerprint table 足够小，适合在 compute nodes 上复制和同步；二是用 optimistic 的 version checking 去修复暂时不一致，比每次更新都做严格同步一致性更划算。

## 设计

DMTree 整体上沿用了 FP-B+-tree 的骨架。internal nodes 指向下层节点；leaf nodes 连续存放一段 key-value entries，同时维护一个 fingerprint table，用来在不整页读取 leaf 的前提下定位某个 entry。每个 leaf 还保存 `Kmin`、`Kmax`、右兄弟指针、version，以及用于正确性的 CRC 或 lock 字段。

第一部分是 compute-side 的双层缓存。每个 compute server 维持一个 private internal-tree cache，但只缓存最底层 internal nodes；更高层在本地重建，以降低一致性管理复杂度。更关键的是 fingerprint table 不再像普通远程 metadata 一样从 memory server 读取。每个 leaf 的 fingerprint table 在某个 compute server 上有一个 primary copy，也可以被其他 compute servers 缓存。于是，某个 server 要执行 search 或 write 时，会先借助本地 internal cache 找到目标 leaf，再去 peer compute server 读取 fingerprint table，而不是去 memory server 读。论文用 fingerprint-table offset 上的 consistent hashing 决定 primary owner，这也顺带提供了节点变化时的负载分摊能力。

第二部分是一致性验证。由于 collaborative fingerprints 在缓存中是异步更新的，过期的 fingerprint 可能把请求导向错误 entry，也可能漏掉新插入的 entry。DMTree 的处理方式是 optimistic repair：如果 cached fingerprint 表明某个 key 应该存在，但随后读回的 key-value entry 对不上；或者 fingerprint 里查不到，但 key 仍可能存在，那么系统就去负责该 fingerprint table 的 compute peer 读取 primary copy，并刷新本地缓存。为了保证 private internal cache 与远端 leaf 结构一致，DMTree 在 internal entries、leaf nodes 和 fingerprint tables 中都放置 version ID。只要 leaf 发生 split、merge 或 key range 变化，version 就会递增；一旦版本不匹配，就说明本地 cached internal entry 过期，需要丢弃并重新远程遍历。CRC checks 则用来发现读写竞争。

第三部分是 collaborative locking。以往 DM index 的并发控制主要优化冲突锁，但论文指出，即便没有冲突，普通 lock 和 unlock 也会消耗大量 memory-side IOPS。DMTree 因此把 leaf-node lock field 和 primary fingerprint table 一起放在 compute servers 上。writer 通过对 compute peer 执行 `RDMA_CAS` 来加锁，随后在 memory server 上更新真正的 leaf entry，再执行解锁。对 insert 来说，DMTree 把解锁嵌入 fingerprint-table 的写回中，因此一次 `RDMA_WRITE` 就能同时提交更新后的 fingerprint metadata 并释放锁。在数据路径上，DMTree 还利用 fingerprint table 在 scan 时过滤空槽位，避免把未写入的 entries 一并读回来；同时，它会把同一 compute server 上的并发请求做 batching，但又设置批大小上限，避免 tail latency 被过大队列拖垮。

## 实验评估

实验设置和论文主张是匹配的。作者使用 `6` 台 compute servers 加 `1` 台 memory server；每台机器都有两颗 40-core Xeon Gold、`128 GB` DRAM 和 `100 Gbps` ConnectX-6 RNIC；memory server 只分到一个 CPU core，以贴近 DM 场景下“内存强、算力弱”的假设。实验预加载十亿个 32-byte key-value entries，每组跑一亿次操作，并与 Sherman、dLSM、ROLEX、SMART、CHIME 对比。

核心结果是，DMTree 同时逼近了 point path 和 range path 的理想权衡。在 search-only microbenchmark 中，它接近“每次 lookup 只需要一次远程读取”的目标，相比 Sherman 和 ROLEX 提升 `4.5-5.2x`，主要原因是避免了 leaf 级 read amplification。对于 inserts，它比 SMART 和 CHIME 快 `2.3-3.5x`，比 dLSM 最多快 `5.7x`，因为 fingerprint access 与 locking 不再堆到 memory server 上。对于 scans，它相对 SMART 提升 `3.2x`，原因是范围内 entries 仍连续存放；相对 Sherman 和 CHIME 也还有 `1.1-1.3x` 的优势，因为它能跳过 leaf 中的空 entries。在 YCSB workload 下，这个模式仍然成立：DMTree 在 search/write-intensive workload 上比 Sherman 和 ROLEX 快 `3.8-9.7x`，相对 dLSM 提升 `1.4-8.6x`，在 scan-heavy 的 workload E 上则比 SMART 快 `3.2x`。

overhead 分析也比较可信。fingerprint traversal 只占 search latency 的约 `5%`，而 fingerprint traversal 加 synchronization 一共占 write latency 的 `19.4%`。在每台 compute server 上，DMTree 默认需要 `5.4 GB` 内存，其中 `2.3 GB` 给 internal-tree cache，`3.1 GB` 给 collaborative fingerprint storage。这个开销高于 Sherman 和 CHIME，但远低于 SMART 的 `22.5 GB`。memory side 的额外 metadata 开销也不算大：对十亿个 32-byte entries，DMTree 总共用 `60.1 GB`，Sherman 是 `54.2 GB`。更有说服力的一点是，当 compute-side cache 从 `20 GB` 降到 `2.5 GB` 时，SMART 的 search throughput 最多下降 `72%`，而 DMTree 基本保持稳定，这说明它对现实内存预算的脆弱性更低。

## 创新性与影响

相对于 Sherman 和 ROLEX，DMTree 的创新不是更好的 private cache，也不是更准的 leaf prediction，而是直接改变了 metadata path 的放置位置。相对于 SMART，它有意识地保留连续 leaf 与较粗的存储粒度，但把这一路线通常会引入的 control-path IOPS 爆炸拆掉了。相对于 CHIME 和 FP-B+-tree，它进一步把 fingerprint tables 和 locks 从 memory-side remote metadata 变成了 compute-side shared objects。

因此，这篇论文更像一篇真正提出新机制的系统论文，而不是单纯的工程打磨。它给出的可迁移经验是：在 RDMA-based disaggregated memory 中，那些体积小、访问热、协调频繁的 metadata，不应该跟 bulk data 一样放在 memory server 上，而应该放到 peer fabric 上。对构建 key-value store、ordered index，甚至事务型 DM 数据结构的人来说，这都是一个可以复用的设计结论。

## 局限性

这套设计依赖一种比较具体的瓶颈画像：memory server 是最先达到 IOPS 或 bandwidth 饱和的一侧，而 compute-to-compute RDMA 仍有明显富余。如果实际部署的资源平衡不同，或者未来互连显著降低了 memory-side metadata access 的代价，它的收益可能会缩小。论文确实讨论了 CXL 兼容性，但那部分更多是推演，还没有实验验证。

此外，DMTree 也用更复杂的 control path 换来了性能。它同时维护 private internal cache、协同放置的 fingerprint tables、基于 version 的失效机制、optimistic repair、CRC checks，以及分布式 lock placement，正确性表面并不小。论文虽然概述了 fingerprint table 的 failure detection、primary re-election 和重建思路，但并没有直接评测故障恢复成本或故障场景。最后，整套评测仍然是 index-centric 的，并固定在单个 memory server 与以 32-byte entries 为主的设置上；这很适合隔离机制本身，但在完整应用栈或更异构的 memory-server 配置下，收益能保留多少，论文没有完全回答。

## 相关工作

- _Wang et al. (SIGMOD '22)_ — Sherman 用 private internal-node cache 优化了 DM 上的 B+-tree，但仍然要为 leaf-level read amplification 付出带宽代价，而 DMTree 用 compute-side fingerprints 避开了这一点。
- _Li et al. (FAST '23)_ — ROLEX 用 learned model 降低了 traversal cost，但 point access 仍会因为远程读取预测 span 而浪费带宽。
- _Luo et al. (OSDI '23)_ — SMART 的 ART 布局在 point lookup 上消除了 read amplification；DMTree 则选择保留连续 leaf，避免 scans 和 inserts 被拆成大量小 RDMA 请求。
- _Luo et al. (SOSP '24)_ — CHIME 已经把 tree layout 和 in-leaf precise locating 结合起来，而 DMTree 更进一步，把 fingerprint access 与 leaf locking 一起从 memory server 挪到了 compute peers。

## 我的笔记

<!-- 留空；由人工补充 -->

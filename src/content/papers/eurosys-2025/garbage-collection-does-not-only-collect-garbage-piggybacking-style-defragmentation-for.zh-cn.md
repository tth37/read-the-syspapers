---
title: "Garbage Collection Does Not Only Collect Garbage: Piggybacking-Style Defragmentation for Deduplicated Backup Storage"
oneline: "GCCDF把按 chunk ownership 重排数据这件事嵌进 mark-sweep GC，只在本来就要搬的 valid chunk 上改布局，从而同时保住 dedup ratio 和 restore locality。"
authors:
  - "Dingbang Liu"
  - "Xiangyu Zou"
  - "Tao Lu"
  - "Philip Shilane"
  - "Wen Xia"
  - "Wenxuan Huang"
  - "Yanqi Pan"
  - "Hao Huang"
affiliations:
  - "Harbin Institute of Technology, Shenzhen, China"
  - "DapuStor, Shenzhen, China"
  - "Dell Technologies, Boston, USA"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717493"
code_url: "https://github.com/Borelset/GCCDF"
tags:
  - storage
  - filesystems
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

GCCDF抓住的不是一个新的 restore heuristic，而是一个更省账的切入点：deduplicated backup storage 里的 mark-sweep GC 本来就要把 partially invalid container 里的 valid chunk 拷出来，于是 defragmentation 最贵的那一步其实已经在做。它把 chunk 按 ownership，也就是哪些 backup 会引用它，重新分组，再在 GC 的 sweep 路径里顺手重排写回。结果是在四组数据集上既保住了与 naive dedup 相同的 dedup ratio，又把 restore throughput 提高了 2.1x-3.1x，同时还常常让后续 GC 更省写。

## 问题背景

去重备份系统靠 chunk sharing 把容量压下去，但 restore locality 也被一起打散了。一个原本按逻辑顺序排列的 backup image，在 dedup 之后变成一串跨越很多 container 的 recipe；恢复时为了取回这些 chunk，系统不得不读进许多只命中一小部分有用数据的 container，于是产生明显的 read amplification。论文给出的结论很直接：deduplication-specific fragmentation 最坏能让 restore speed 掉到原来的五分之一左右。

已有办法基本都卡在同一个三难选择里。rewriting 路线通过保留部分 duplicate chunk 来换 restore locality，问题是这等于主动把 dedup 节省下来的空间再花回去。论文里的代表性 rewriting 方法在不同数据集上会损失 11%-56% 的 dedup ratio。另一条路是 reordering：保持 dedup ratio 不变，额外做一次大规模迁移，把 chunk 重新写成更适合恢复的布局。但这类方法常常要搬动 50%-80% 的数据集，而且默认 backup 之间存在强烈的时间连续性，最好还来自同一个 source。到了 MIX 这种多源混合工作负载上，代表方法 MFDedup 基本退化成接近 non-dedup 的行为。真正棘手的地方不只是碎片化，而是要在不丢 dedup ratio、不再额外付出一次大搬迁、也不依赖单一来源假设的前提下解决碎片化。

## 核心洞察

这篇论文最值得记住的命题是：deduplicated backup storage 里的 defragmentation 根本不应该被视作另一项单独维护任务。只要系统采用 immutable container，旧 backup 被删除后就会留下 invalid chunk，而 mark-sweep GC 为了回收这些空间，本来就要在 sweep 阶段把仍然有效的 chunk 复制到新 container 里。GCCDF做的事情，就是把 layout repair 塞进这条既有的数据搬移路径里，让 defragmentation 搭 GC 的便车。

可光把两条流程合并还不够，因为 chunk 同时被多个 backup 共享时，帮一个 backup 聚合数据，往往会把另一个 backup 再次打散。GCCDF 给出的抽象是 chunk ownership，也就是引用该 chunk 的 backup 集合。如果一个 container 里的 chunk 拥有相同 ownership，那么恢复任意一个 backup 时，要么整批都需要，要么整批都不需要。这样一来，布局问题就不再是单个 backup 的顺序问题，而变成了跨所有 backup 的兼容性问题。当 ownership cluster 和固定 4 MB container 边界对不齐时，GCCDF再去混合 ownership 最相近的 cluster；若相似度打平，则优先让末尾共享后缀更长的 cluster 相邻，以便把 locality 更偏向最近的 backup。

## 设计

GCCDF 被插在 mark-sweep GC 的 mark 和 sweep 之间。mark 阶段照常生成 valid chunk table，同时还能顺手产出 RRT，记录哪些 GC-involved container 会被哪些 backup recipe 引用。之后 GCCDF 依次运行三个模块。

Preprocessor 先把这轮 GC 会处理的 container 划成 segment，默认每个 segment 是 100 个 container。这样做不是为了好看，而是因为 reordering 自己也会遇到 scattered read；如果一次把所有待迁移 chunk 全部读进内存，缓存成本会过高。对每个 segment，Preprocessor 根据 valid chunk table 只把 valid chunk 读入 GC cache，再收集这个 segment 里涉及到的那部分 backup 引用信息。

Analyzer 负责 locality-promoting chunk clustering，也就是判断每个 chunk 的 ownership，并把 ownership 相同的 chunk 放进同一类。论文没有用最直接的暴力办法去扫描每条 recipe，而是先为 involved backups 建 Bloom filter，再用一棵 binary tree 逐轮划分 chunk：某个 backup 会引用的 chunk 走右子树，不会引用的走左子树。所有相关 backup 检查完后，每个 leaf node 就对应一个 ownership cluster。这里有两个实现上的关键点。其一，检查 backup 的顺序是从新到旧倒着做，这样相邻 leaf node 会天然更照顾最近 backup 的局部性。其二，Analyzer 会拒绝继续切分太小的 leaf，避免 cluster 本身被切得过碎，反而制造更多布局噪声。

Planner 再把这些 ownership cluster 变成实际的迁移顺序。论文在概念上提出的是 container-adaptable packing：每次都把 ownership 最相似的下一个 cluster 接到后面；如果多个候选的相似度相同，就选 ownership 列表末尾共享后缀更长的那个，因为最新 backup 通常更碎，而且还会经历更多轮 backup turnover，优化收益持续时间更长。实现上，Planner 直接利用 Analyzer 产出的 leaf list，从左到右遍历就能近似得到这种顺序。最后，sweep 阶段按这个次序从 GC cache 中取出 valid chunk，装入新的 container，于是 GC 和 defragmentation 在同一次搬迁里一起完成。

## 实验评估

实验平台是一台 Intel Xeon Platinum 8468V 服务器，128 GB 内存，两个 Intel S4610 SSD 组成 RAID-0 作为 backup storage，另有一块 Intel P4610 SSD 存原始数据。chunking 使用 FastCDC，配置是 1 KB 最小、4 KB 平均、32 KB 最大，container 大小 4 MB。评测覆盖四组数据：WIKI 1.2 TB、CODE 394 GB、MIX 809 GB、SYN 1.1 TB。系统总是保留最近 100 个 backup，每轮以论文设定的策略删除最旧的 20 个，再运行 GC，最后恢复剩余 backup。

最核心的结果是：和 naive dedup 相比，GCCDF 在 WIKI、CODE、MIX、SYN 上分别把 restore throughput 提升了 2.7x、3.1x、2.1x、2.3x，同时 dedup ratio 完全不变。若按摘要中更贴近实务的对比口径去看，GCCDF 相比 SMR 能带来 2.1x 的 restore speedup，而且不会像 SMR 那样付出最高 34.5% 的 dedup ratio 损失。对 MFDedup，论文则报告 GCCDF 在典型场景下能拿到 6.45x 更高的 dedup ratio，因为后者在多源 workload 上几乎放弃了有效的 chunk sharing。

论文也给出了更直接的碎片化证据。GCCDF 的平均 read amplification 分别只有 WIKI 1.3x、CODE 2.2x、MIX 1.4x、SYN 3.6x；对应地，SMR 分别是 5.9x、4.3x、3.4x、8.2x。GC 开销部分同样有说服力：在初始几轮之后，GCCDF 会明显减少 involved、reclaimed 和 produced container 的数量，论文甚至指出 produced container 大约只有其他方法的三分之一。虽然 GCCDF 额外多了一个 Analyze stage，但这部分时间占 GC 总时长很小，而 sweep-read 与 sweep-write 的下降通常足以把这点额外计算抵掉。灵敏度实验也支撑了设计本身：segment 太小会损害 defragmentation 效果，而把 ownership-aware packing 换成 random packing，则平均会把 read amplification 再抬高约 20%。

整体来看，这组实验是支持中心论点的。baseline 选得合理，既有 rewriting，也有 prior reordering；数据集既包含同源版本，也包含多源混合场景；而且不仅测了 restore speed，也测了 GC 的 I/O 和时间成本。需要留一层保留意见的是，MFDedup 的假设本来就和多源 workload 不够匹配，所以 GCCDF 最有力的比较对象，其实是 rewriting 方法加常规 GC，而不是某个已经被证明足够通用的 prior reordering 系统。

## 创新性与影响

GCCDF 的创新点不只是又设计了一套 dedup layout heuristic。它真正重新定义的是成本该在哪条路径里支付。论文先看穿了 GC 和 defragmentation 在 deduplicated backup storage 里都要为 valid chunk migration 买单，然后把这两项工作折叠成同一条 maintenance path。再往上，它把 chunk ownership 提炼成兼容多 backup locality 的核心抽象，并进一步解决了 ownership cluster 与 fixed-size container 对不齐的问题。

这会对 deduplicated backup appliance、immutable-container storage，以及更广义的 GC-heavy storage system 都有参考价值。以后别人完全可能换掉 ownership 推断方式、binary tree 实现，甚至 packing heuristic，但这篇论文已经把讨论重心改掉了：restore locality 不一定要靠事后的独立重写过程来修，而可以在 GC 的 sweep 路径中一并修好。从贡献类型上看，我会把它归为一个建立在清晰系统重构视角上的新机制。

## 局限性

GCCDF 只能处理这轮 GC 本来就会触碰到的数据。如果某些 live data 很碎，但所在 container 还没有进入 GS list，它就没法立即重排，只能等后续 backup turnover 让这些 container 变成 GC 候选。论文认为 backup system 的 GC 足够频繁，所以这件事问题不大，但 defragmentation 的推进速度终究被 retention churn 绑定住了。

segment 也是一个不能忽略的现实约束。segment 小，内存占用好控，可论文自己的实验已经表明它会错过很多本可跨 container 聚合的 chunk，导致 read amplification 变高；segment 大，则会推高 GC cache 大小和 ownership analysis 的复杂度。再往外看，评测主要集中在一套 SSD 原型和四组数据集上。论文没有量化 GCCDF 与前台 backup ingestion 并发时的干扰，也没有系统展示不同 container size、不同介质组合或不同 retention policy 下，收益是否仍然保持同样形态。

## 相关工作

- _Lillibridge et al. (FAST '13)_ - Capping 这类 rewriting 通过保留部分 duplicate chunk 来换 restore locality，而 GCCDF 不牺牲 dedup ratio，只在 GC 已经要迁移 valid chunk 时顺带修布局。
- _Douglis et al. (FAST '17)_ - 这篇工作梳理了 deduplicated storage 中 physical GC 的流程与成本；GCCDF 则直接把这条 sweep-time migration 路径扩展成 defragmentation 的落点。
- _Zou et al. (FAST '21)_ - MFDedup 需要一条独立的 chunk migration 路径，并且依赖连续版本间的局部性假设；GCCDF 用 ownership clustering 取代这种假设，因此在 mixed-source workload 上更稳。
- _Zou et al. (USENIX ATC '22)_ - 这项 fine-grained deduplication framework 面向高性能、高去重率的 backup storage 总体设计，而 GCCDF 更聚焦于 dedup 完成之后的 restore locality 与 GC-time layout repair。

## 我的笔记

<!-- 留空；由人工补充 -->

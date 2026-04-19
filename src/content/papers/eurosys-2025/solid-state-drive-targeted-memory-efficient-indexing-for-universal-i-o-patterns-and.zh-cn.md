---
title: "Solid State Drive Targeted Memory-Efficient Indexing for Universal I/O Patterns and Fragmentation Degrees"
oneline: "AppL 把任意 SSD 写入重排成按 LBA 排序的 append-only run，再分层混用 FP 和 PLR，把 L2P 索引稳定压到 6∼8 bits/entry，不怕低局部性和碎片化。"
authors:
  - "Junsu Im"
  - "Jeonggyun Kim"
  - "Seonggyun Oh"
  - "Jinhyung Koo"
  - "Juhyung Park"
  - "Hoon Sung Chwa"
  - "Sam H. Noh"
  - "Sungjin Lee"
affiliations:
  - "POSTECH"
  - "DGIST"
  - "Virginia Tech"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717478"
code_url: "https://github.com/dgist-datalab/AppL/"
tags:
  - storage
  - databases
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

AppL 想解决的不是某一种好看的 workload，而是 SSD 在最坏输入下也得把 L2P 索引做小。它先用 `LSM-tree` 把任意写入整理成按 LBA 排序、按物理扇区连续追加的 run，再在高层用 `FP`、低层用 `PLR` 做近似索引，因此即便 I/O 很随机、介质已经碎片化，索引仍能维持在大约 `6∼8` bits per entry。作者的原型结果表明，这样的设计能同时把读延迟和吞吐量拉到 DFTL、SFTL、LeaFTL 之上。

## 问题背景

论文要解决的是一个很硬的扩容瓶颈：完整 L2P table 大约需要 SSD 容量的 `0.1%`，所以 `16 TB` SSD 就要 `16 GB` DRAM。DFTL、SFTL、LeaFTL 都在想办法缩这部分内存，但它们分别依赖时间局部性、空间局部性或 `<LBA, PSA>` 的规律性。现实 workload 往往把这些前提一起打碎：hash-based cache system 会把请求打散，允许 in-place update 的 database 会破坏物理连续性，设备老化又会进一步放大 fragmentation。论文的动机实验里，当 DRAM 只有 OFTL 的 `20%` 时，SFTL 和 LeaFTL 在 fragmented Varmail 与 CacheLib 上的 entry size 会涨到 `24.9∼62.7` bits，读延迟变成 OFTL 的 `1.3∼6.9x`。真正缺的是一种在坏 locality 和碎片化下也不塌缩的索引。

## 核心洞察

AppL 的核心判断是，先把映射变规整，再谈近似压缩。它把写入先送进 `LSM-tree`，把原本任意顺序的更新重排成按 LBA 排序、按物理扇区连续追加的 run。这样一来，近似索引面对的就不再是碎片化后的原始映射，而是已经被正则化的 run。高层 run 小、规律性弱，用 `FP`；低层 run 大、排列密，用 `PLR`。这就是 AppL 和 LeaFTL 的根本差别。

## 设计

AppL 的写入先经过 memtable，再 flush 到 `L0`，之后通过 compaction 下推成有序 run。run 的 metadata area 里保留精确 `<x_i, y_i>`，但 DRAM 里只放轻量索引。最关键的是 `shortcut table`，它直接把 LBA 映射到拥有该块的 run，避免普通 `LSM-tree` 那种逐层探测。论文给出的 `16 TB` 平衡配置树高为 `3`：`L0` 用 `RB-tree`，高层用 `FP`，最低层用 `PLR`。

`FP` 的压缩来自一个 SSD 特有性质：run 内物理扇区连续，所以 PSA 不必显式存储，只要存 group 的首个精确 LBA 和后续条目的 fingerprint 即可。对 `E_appx = 0.1`，论文推导出 `7-bit` fingerprint、`28` 个条目的 group，平均 `7.89` bits per entry，而 naive FP 要 `40.3`。`PLR` 则利用 `16 KB` NAND page 对 `4 KB` host block 的覆盖关系，把 `δ` 从 `0.55` 放宽到 `2.2`，使每条线段平均覆盖 `25.76` 个 entry；再用量化和 delta-encoding，把单条线段描述压到 `47.4` bits，而常规 `PLR` 需要 `192`。为了控制写放大，AppL 固定树高并调节 `L0` 与 size factor，最终选择 `T = 14`、`|L0| = 84.7 GB`，峰值内存约为 OFTL 的 `29.1%`，`WAF` 约 `3.0∼3.5`。

## 实验评估

作者不是只做模拟，而是在 FPGA-based SSD prototype 上实现了 AppL，并和 OFTL、DFTL、SFTL、LeaFTL 在相同条件下比较。除 OFTL 外，其余方案都只给 `51.2 MB` DRAM，也就是完整页映射的 `20%`，外加同样的 `4 MB` write buffer，所以比较是公平的。

核心结果是，AppL 在真实 workload 上没有像基线那样因为输入变坏而丢掉压缩率。无论是 Filebench、TPC-C、Redis 上的 YCSB，还是 CacheLib，AppL 的 average entry size 都维持在 `5.82∼6.3` bits，因此整个近似索引只要 `46.6∼50.4 MB` DRAM 就能基本常驻。对应地，它相对 DFTL、SFTL、LeaFTL 的平均读延迟分别缩短 `72.4%`、`62.7%`、`33.6%`，吞吐分别提升 `48.5%`、`28.4%`、`83.4%`。在 RR/RW 微基准下，AppL 依旧能把平均延迟压低 `33∼44%`、把吞吐拉高 `10∼79%`，因为它的 entry size 还能维持在约 `9.3` bits，而 SFTL 和 LeaFTL 已经涨到 `32` 和 `62.7` bits。

不过评估也把代价说清楚了。只要 DRAM 小到连 `shortcut table` 都放不下，性能就会明显掉下来；而到了更快的 SSD 上，后台排序会吃掉 `28.4%∼51.7%` 的 compaction 时间，作者在 GEN4 SSD 加 `1.2 GHz` CPU 的实验里就看到 AppL 在 random write 上会输给 DFTL 和 SFTL。也就是说，这篇论文很有力地证明了它不怕坏 locality，但控制器算力仍是下一步瓶颈。

## 创新性与影响

AppL 的创新不在单个组件，而在把 `LSM-tree` 正则化、`shortcut table`、隐式 PSA 的 `FP`、以及 page-aware `PLR` 放宽误差拼成一个适合 FTL 的整体。它给 SSD 控制器设计和 learned-index 工作都提了一个很实用的提醒：如果输入本身太乱，先改写入路径，往往比继续堆更复杂的模型更有效。

## 局限性

AppL 的鲁棒性是用后台工作换来的。即便平衡点已经把 `WAF` 压到 `3.0∼3.5`，更新重、利用率高的场景仍会频繁触发 compaction 和 last-level GC。它也明显依赖控制器资源：`shortcut table` 自身就要 OFTL 内存的 `15.6%`，而 SSD 一旦变快，sorting 和 index building 就会成为瓶颈。作者给出的方向是并行排序或硬件加速，但这部分还没有真正解决。

## 相关工作

- _Jiang et al. (MSST '11)_ - SFTL 依赖 translation chunk 内的空间局部性来压缩映射，而 AppL 的目标正是局部性被碎片化和随机写打散之后仍能保持小索引。
- _Zhou et al. (EuroSys '15)_ - TPFTL 继续沿着 page-mapping 结构内部做压缩，AppL 则把重点前移到写入路径，用 `LSM-tree` 主动制造可近似的有序 run。
- _Sun et al. (ASPLOS '23)_ - LeaFTL 把 `PLR` 直接用于 flash translation；AppL 保留近似索引思路，但先通过 `LSM-tree` 放大规律性，因此对 fragmentation 更不敏感。
- _Dayan et al. (SIGMOD '17)_ - Monkey 研究的是 `LSM-tree` 元数据与层级的内存分配，AppL 则把类似的层级调参思想搬到 SSD L2P 索引里，用 `shortcut table` 和受控树高换取低 `RAF` 与可接受的 `WAF`。

## 我的笔记

<!-- 留空；由人工补充 -->

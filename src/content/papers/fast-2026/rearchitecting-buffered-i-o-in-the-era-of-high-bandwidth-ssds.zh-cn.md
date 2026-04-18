---
title: "Rearchitecting Buffered I/O in the Era of High-Bandwidth SSDs"
oneline: "WSBuffer 用 scrap buffer 加对齐直写 SSD 重做 buffered I/O 写路径，既避免 partial write 的先读后写，又让 page cache 主要服务读路径。"
authors:
  - "Yekang Zhan"
  - "Tianze Wang"
  - "Zheng Peng"
  - "Haichuan Hu"
  - "Jiahao Wu"
  - "Xiangrui Yang"
  - "Qiang Cao"
  - "Hong Jiang"
  - "Jie Yao"
affiliations:
  - "Huazhong University of Science and Technology"
  - "University of Texas at Arlington"
conference: fast-2026
category: flash-and-emerging-devices
tags:
  - storage
  - filesystems
  - kernel
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`WSBuffer` 保留了 buffered I/O 的接口，但不再让每一次写入都先经过 page cache。它把小写、非对齐写和 partial-page 写先放进新的 `scrap buffer`，把大块且对齐的部分直接写到 SSD，再在后台机会式地把 scrap-pages 补全并刷回。论文在 8 块 PCIe 4.0 SSD 上报告，相比 Linux 文件系统和 `ScaleCache`，它最高带来 `3.91x` 吞吐提升和 `82.80x` 写延迟下降。

## 问题背景

论文的出发点是：在现代 SSD 阵列上，buffered I/O 已经不再天然是最快的默认路径。虽然 DRAM 带宽仍高于 SSD，但 direct I/O 在大写入上已经能明显超过 buffered I/O，因为真正拖后腿的不是介质，而是 page cache 自己的管理开销，包括 page 分配、XArray 查找与更新、脏页状态维护，以及 LRU 管理。作者展示了一个很直接的现象：在 8 块 PCIe 4.0 SSD 组成的 RAID0 上，direct I/O 可以逼近约 `55 GB/s` 的阵列带宽，而 buffered I/O 明显跟不上。

第二个问题是内存压力。高强度写入时，page cache 既要吸收前台写入，又要足够快地把脏页刷出并回收空间；但这些路径上的 page-state 更新和树结构修改会竞争不可扩展的锁，导致可用内存一降，吞吐就明显下滑。第三个问题是 partial-page 写入。只要一个 partial write 在 page cache 中未命中，传统 buffered I/O 就必须先把旧页从 SSD 读上来，再做修改，因此 partial-page write 的延迟会比对应的 full-page write 高出 `1.51x-84.37x`。

现有工作大致分成两类：一类继续优化 page cache，例如 `ScaleCache`；另一类则改用 direct I/O 或 hybrid I/O。论文认为，前一类仍把完整缓冲放在写关键路径上，后一类则牺牲了 buffered I/O 的透明语义与免对齐编程体验。

## 核心洞察

这篇论文最重要的判断是：buffered I/O 真正需要缓冲的，只是 SSD 不擅长处理的那部分写入，而不是每一个字节。只要把小块、非对齐和 partial-page 片段留在内存里，把大块且对齐的部分直接送到 SSD，就能在不把 direct I/O 约束暴露给应用的前提下利用 SSD 带宽。

要做到这一点，关键不变量是把“脏写数据”和“干净读缓存”彻底分开。在 `WSBuffer` 里，最新但尚未落盘的片段只存在于 scrap-pages 中；已经提交的大块对齐数据在 SSD 上；传统 page cache 页面始终保持 clean，只负责读缓存。只要 page cache 不再承担写缓冲，partial write 的先读后写代价和大量写侧元数据竞争就都能被显著缓解。

## 设计

`WSBuffer` 引入了由 `scrap-pages` 组成的 `scrap buffer`。默认情况下，一个 scrap-page 由 `128 B` 的 header 和 `256 KB` 的 data zone 组成。header 记录有效字节数、segment 数量、目标 SSD、页面状态，以及最多 `15` 个 segment 描述符，因此多个小写入或地址重叠写入可以直接在同一个 scrap-page 内合并，而不需要先从 SSD 把旧数据读回来。为了减少碎片与复制开销，系统一次分配 `32` 个 scrap-pages，并把 headers 与 data zones 分开存放。

写路径使用一个 `1 MB` 阈值。小于该阈值的写入全部进入 scrap buffer。更大的写入会被拆成两端不完整的 partial-scrap-page 部分，以及中间按 `256 KB` 对齐的主体部分。两端进入 scrap-pages，中间部分直接写 SSD。这个对齐粒度不是随便选的：它既保证文件在 SSD 上以大块连续布局存放，避免后续碎片化，也让后续对完整 scrap-page 的刷回更自然。如果 direct SSD write 覆盖了 scrap-pages 或只读 memory-pages 中已有的数据，对应的旧缓存会在后台被回收。

读路径则先查 scrap buffer，再对剩余部分走普通 page-cache 读路径。这样一来，数据一致性反而比直觉上简单：scrap-pages 永远保存最新的脏数据，page cache 页面永远是 clean 的，SSD 保存的是已经提交的数据。

后台处理由两阶段的 `OTflush` 完成。Stage 1 负责异步从 SSD 读取缺失字节，把因为 partial write 而产生的未填满 scrap-page 补全，因此先读后写的代价被移出了前台关键路径。Stage 2 再把完整 scrap-pages 刷回 SSD。两个阶段都带有 SSD 负载感知：每块 SSD 维护一个在途字节计数 `Bcount`，`OTflush` 优先给不忙的设备派活，默认把 `4 MB` 作为忙碌阈值。为了降低锁竞争，只读 memory-pages 继续使用普通 `XArray`，而 scrap-pages 进入 `SXArray`；后者把删除后的树清理延后处理，并用 per-scrap-page lock 管理状态变化，而不是反复去争用全局锁。

## 实验评估

作者在 Linux `6.8` 的 `XFS` 上实现了约 `4500` 行代码的原型，实验平台是两颗 Xeon Gold `6348`、`256 GB` DRAM，以及 8 块 Samsung `990 PRO` SSD 组成的 RAID0。微基准非常直接地支撑了论文主张。对 full-page write，`WSBuffer` 将延迟降低了 `1.03x-3.29x`。对最关键的 partial-page write，它把延迟提升到基线的 `1.70x-82.80x`。即使和带 read-modify-write 的 direct I/O 实现、以及 `AutoIO` 风格的 hybrid policy 相比，它仍然快 `1.59x-231.28x`，因为它避免了在关键路径上同步修复 partial write。

更大的 benchmark 也比较有说服力。在充足内存下，`WSBuffer` 在 Filebench `Fileserver` 上相对基线提升 `1.23x-2.51x`，在 `Varmail` 上提升 `1.06x-2.84x`；在偏读的 `Webproxy` 上，它仍优于大多数基线，但在关闭 flushing 的情况下会略输给 `XFS`，论文将其归因于额外的 scrap-buffer 查找路径。到了受限内存并打开 flushing 的场景，优势扩大到 `Fileserver` 上的 `1.23x-4.48x` 和 `Webproxy` 上的 `1.07x-4.37x`，说明减少写侧缓冲确实释放了更多内存给读缓存。

真实应用结果延续了这一模式：`YCSB+LevelDB` 提升 `1.32x-2.02x`，`GridGraph` 的 PageRank 提升 `1.09x-4.37x`，`Nek5000` 提升 `1.74x-3.09x`。CPU 利用率下降 `3.2%-28.4%`；在图计算与 `Nek5000` 中，前台写数据真正停留在内存里的比例只有 `0.34%-1.67%`。整体看，评测覆盖了小写、大写、混合负载、内存受限场景以及真实应用，对论文的核心架构主张支撑较强。

## 创新性与影响

相对于 _Pham et al. (EuroSys '24)_ 的 `ScaleCache` 和 _Li and Zhang (USENIX ATC '24)_ 的 `StreamCache`，`WSBuffer` 不是再做一轮 page-cache 并发优化。它真正新的地方在于改了 buffered I/O 的架构边界：page cache 不再承担通用写缓冲，而重新主要服务读路径。

相对于 _Qian et al. (FAST '24)_ 的 `AutoIO` 和 _Zhan et al. (FAST '25)_ 的 `OrchFS`，这套设计仍保留 buffered I/O 的编程模型，把 direct SSD access 藏在内核内部，而不是把对齐约束或额外 API 暴露给应用。因此，这篇论文对内核文件系统开发者和希望让 POSIX buffered I/O 在高速 SSD 阵列时代继续可用的存储研究者都很有参考价值。

## 局限性

这篇论文最强的证据仍来自单机、本地 SSD、写密集场景，以及一个基于 `XFS` 的原型。论文虽然宣称设计可以移植到其他文件系统，但并没有真正实现这些移植；同时，若干关键参数都是基于实验平台经验选出来的，包括 `1 MB` 的请求阈值、`256 KB` 的 scrap-page 大小，以及 `4 MB` 的 SSD 忙碌阈值。

评测本身也有一些范围与公平性上的保留。`ScaleCache` 使用的是 Linux `5.4`，而 `XFS` 与 `WSBuffer` 基线运行在 Linux `6.8`；`AutoIO` 的比较对象也只是对其原则的用户态实现，而不是原始的 Lustre 系统。再者，在内存充足且读占主导时，优化充分的传统 `XFS` 仍可能更占优；至于 durability 与 crash consistency，论文大多把它们交给底层文件系统负责，而没有对 `WSBuffer` 自身的恢复边角情况做很深入的分析。

## 相关工作

- _Pham et al. (EuroSys '24)_ — `ScaleCache` 通过并行化 page-cache 索引和刷脏来提速，而 `WSBuffer` 直接减少了需要 page-cache 缓冲的数据量。
- _Li and Zhang (USENIX ATC '24)_ — `StreamCache` 关注 fast storage 上的文件扫描缓存，而 `WSBuffer` 聚焦于写密集 buffered I/O 与 partial-write 修复。
- _Qian et al. (FAST '24)_ — `AutoIO` 在运行时混合 buffered I/O 与 direct I/O，`WSBuffer` 则保留 buffered I/O 语义，并把这种拆分内化到内核里。
- _Zhan et al. (FAST '25)_ — `OrchFS` 借助 NVM 与 direct I/O 主动利用 SSD 带宽，而 `WSBuffer` 保留主流 buffered I/O，只重做其写路径。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "Unleashing Zoned UFS: Cross-Layer Optimizations for Next-Generation Mobile Storage"
oneline: "ZUFS 通过设备侧槽式缓冲、跨层严格写序和主动式 F2FS 垃圾回收，把 zoned UFS 从规范能力变成可在旗舰手机上落地的移动存储栈。"
authors:
  - "Jungae Kim"
  - "Jaegeuk Kim"
  - "Kyu-Jin Cho"
  - "Sungjin Park"
  - "Jinwoo Kim"
  - "Jieun Kim"
  - "Iksung Oh"
  - "Chul Lee"
  - "Bart Van Assche"
  - "Daeho Jeong"
  - "Konstantin Vyshetsky"
  - "Jin-Soo Kim"
affiliations:
  - "SK hynix Inc."
  - "Google"
  - "Seoul National University"
conference: fast-2026
category: flash-and-emerging-devices
tags:
  - storage
  - filesystems
  - kernel
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文把 `ZUFS` 从一套 JEDEC 接口真正做成了可量产的手机存储栈：设备控制器、Linux I/O 路径、`F2FS` 与 Android 集成被一起重做，而不是只在设备侧加一个 zone 模式。部署在商用 `Pixel 10 Pro` 上后，系统能在碎片化条件下保持稳定随机读，在老化场景中把写吞吐提升到传统 `UFS` 的 `2x` 以上，并把 `Genshin Impact` 的校验加加载时间从 `35` 秒降到 `30` 秒。

## 问题背景

传统 `UFS` 依赖页级 `L2P` 映射，但手机控制器只有很小的 SRAM。随着容量增长，映射工作集装不下，随机读就会不断触发 map-cache miss。论文还证明，碎片化不是实验室里的边角问题：作者从 `10,000` 台已出货手机收集统计数据，发现约 `30%` 的设备碎片化水平超过 `0.7`，而且低利用率下也存在严重碎片化的样本。

`ZUFS` 看起来像自然答案，因为它把页级映射改成 zone 级映射，并要求顺序写入。但论文指出，手机上不能只“打开 zone 功能”就指望它工作。系统既要支持至少六个并发 open zones，又要在激进的 UFS 省电机制下维持严格写序，还要处理 `F2FS` 在超大 section 上的垃圾回收成本。三者任何一个没有处理好，zoned storage 都会分别卡在 SRAM 浪费、正确性破坏或 GC 失控上。

## 核心洞察

论文最关键的判断是：移动端 zoned storage 是否成立，取决于 zone 抽象能否成为跨层不变量，而不是控制器内部的一个局部优化。更小的映射表当然重要，但真正的收益只有在三个条件同时满足时才会出现：控制器能把稀缺 SRAM 在多个 open zones 之间动态共享，内核与驱动绝不重排 zoned writes，文件系统也会在大 zone GC 变成前台阻塞前主动回收空间。

因此作者没有把复杂性大规模搬到主机侧，而是保留设备内 `FTL`，再重写围绕它的契约。相较 `ZMS` 这类主机参与很重的方案，这篇论文的路线是尽量保持主机接口标准化，把新增机制压缩到控制器和上游存储栈中。

## 设计

设备由多颗 TLC NAND die 组成，每个 zone 横跨多个 dies 与 planes，大小为 `1,056 MB`，页大小为 `16 KB`。`ZUFS` 不再维护页级映射，而是用一个 `8` 字节的 zone 映射项记录起始物理地址和有效长度。论文给出的量级很有说服力：`1 TB` 设备只需要大约 `8 KB` 的完整 `ZMT`，而传统页级映射接近 `1 GB`，因此 zone 映射可以常驻 SRAM。

为了解决多 open zones 的写缓冲问题，控制器实现了 `ZABM`，核心是 `Scatter-Gather Buffer Manager (SGBM)`。`SGBM` 把预留 SRAM 切成 `4 KB` 槽位，为每个 open zone 维护一个 slot table；当数据够写一个 die 时就按 `192 KB` 刷下去，凑满 superpage 时则按 `768 KB` 并行刷新。这样系统就能给每个 zone 提供“逻辑上的独立写缓冲”，却不需要真的为每个 zone 固定保留 `7 x 768 KB` 的物理 SRAM，而且热点 zone 还能动态借到更多槽位。

第二部分是正确性。作者把 UFS 驱动里“时钟门控时先 requeue、稍后再发”的行为改成同步 ungating，确保请求按文件系统发出的顺序进入设备。与此同时，他们还修掉了 Linux block layer 里三个会破坏写序的角落：`mq-deadline` 中可能失效的 `next_rq` 指针、绕开排序路径的 `FUA` 写，以及会把 zoned writes 重排的 I/O priority 逻辑。最后，作者为 `F2FS` 加入面向 zoned device 的主动式后台 GC 参数，如 `gc_no_zoned_gc_percent`、`gc_boost_zoned_gc_percent` 与 `reserved_segments`，把回收策略分成 `No-GC`、`Normal-GC`、`Boosted-GC` 三个阶段。

## 实验评估

评测平台是 `Google Pixel 10 Pro`，配备 `12 GB` LPDDR5X、`512 GB` `ZUFS`，运行 Android `16` 和 Linux `6.6`。在干净设备上，`CUFS` 与 `ZUFS` 的顺序/随机读写吞吐基本相当，这一点其实很重要，因为它说明 zoned 设计不是靠牺牲新盘带宽换取后续优势。

优势在更大范围或更老化的场景下出现。对 `4 GB` 到 `256 GB` 的大范围随机读，`CUFS` 会随着访问范围扩大而退化，`ZUFS` 则保持稳定，因为它的 zone 映射表完整驻留在 SRAM 中。请求尺寸小于 `128 KB` 时差距最大，此时 `CUFS` 的主要成本已经变成 map-cache miss。写缓冲实验也说明了设备侧细粒度刷新为何关键：当 chunk size 为 `192 KB` 时，`ZUFS` 的写吞吐比模拟 `ZMS` 风格的 `768 KB` chunk 高 `26%`，原因是它能更早释放槽位，并把主机写入和 NAND 编程更好地流水化。

在合成碎片化老化测试中，`CUFS` 大约在第 `90` 次迭代附近崩塌：写吞吐降到约 `100 MB/s`，读吞吐下降约 `35%`。`ZUFS` 虽然也会在后台 GC 提速时出现低谷，但写吞吐始终高于 `200 MB/s`，读吞吐也保持稳定，因为回收主要在后台完成，并且遇到用户读会立即暂停。应用级结果把这些机制转成了用户可感知差异：在老化设备上，`Genshin Impact` 的校验加加载时间从 `CUFS` 的 `35` 秒降到 `ZUFS` 的 `30` 秒；相册滚动测试中，jank rate 从 `0.60%` 降到 `0.26%`，每个文件的碎片数减少 `20x`，`p99` 帧时间也从 `16 ms` 降到 `11 ms`。

## 创新性与影响

相较 _Hwang et al. (USENIX ATC '24)_，这篇论文不依赖主机侧 `IOTailor` 或设备几何参数感知，而是努力让 zoned `UFS` 在现有 Android 与 Linux 抽象下可落地。相较 _Bjørling et al. (USENIX ATC '21)_ 以及后续 `ZNS` 论文，它进一步说明，移动端真正困难的不只是 zone 语义本身，而是在 UFS 级别的 SRAM、功耗与系统集成约束下把它做对。

这篇论文的影响力还来自它的落地强度。作者明确表示这些特性已经进入 `2025` 年发布的 `Google Pixel 10 Pro` 系列，并将其描述为旗舰智能手机中首次商用部署 zoned storage。它因此既是一篇系统设计论文，也是一份难得的产业部署报告。

## 局限性

论文最强的结果主要出现在碎片化或老化状态下；在干净设备上，`ZUFS` 多数时候只是追平而不是明显超过 `CUFS`。这并不削弱结论，但意味着它的价值主张更偏向长期稳定性，而不是新机阶段的跑分领先。

评测范围也仍有边界。实验主要围绕一款商用手机平台和一种 zone 几何展开；论文展示了吞吐、jank 和碎片化上的收益，但没有给出更系统的能耗或长期耐久性评估。另一方面，这一方案要求固件、驱动、文件系统和 Android 框架协同改动，因此部署成本显著高于替换单个设备组件。

## 相关工作

- _Hwang et al. (USENIX ATC '24)_ - `ZMS` 同样面向移动端 zoned flash，但依赖 `IOTailor` 和主机可见的设备策略；这篇论文则把缓冲管理留在设备内，并严格遵循 JEDEC `ZUFS` 语义。
- _Yan et al. (CCGrid '24)_ - 将 zoned namespace 集成进 `UFS` 时采用主机侧 `FTL`，而这篇论文坚持把映射与空间管理保留在设备控制器中。
- _Bjørling et al. (USENIX ATC '21)_ - `ZNS` 论证了服务器 SSD 中避免 block-interface tax 的价值，这篇论文则把同一核心思想落到移动 `UFS` 预算和 Android 栈中。
- _Han et al. (OSDI '21)_ - `ZNS+` 通过设备内 zone compaction 缓解文件系统 GC，而这篇论文则围绕固定的大 `ZUFS` zones 重新设计 `F2FS` 后台 GC。

## 我的笔记

<!-- 留空；由人工补充 -->

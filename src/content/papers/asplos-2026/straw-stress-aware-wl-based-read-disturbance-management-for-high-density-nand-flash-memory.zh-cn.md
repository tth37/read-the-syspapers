---
title: "STRAW: Stress-Aware WL-Based Read Disturbance Management for High-Density NAND Flash Memory"
oneline: "STRAW 按 wordline 跟踪读扰动压力，并按有效性调节 pass-through voltage，让 SSD 只回收真正危险的数据而不是整块搬迁。"
authors:
  - "Myoungjun Chun"
  - "Jaeyong Lee"
  - "Inhyuk Choi"
  - "Jisung Park"
  - "Myungsuk Kim"
  - "Jihong Kim"
affiliations:
  - "Soongsil University, Seoul, Republic of Korea"
  - "Seoul National University, Seoul, Republic of Korea"
  - "POSTECH, Pohang, Republic of Korea"
  - "Kyungpook National University, Daegu, Republic of Korea"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790228"
tags:
  - storage
  - hardware
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

STRAW 认为，现代 SSD 的 read reclaim 既太粗，也来得太晚。它不再等整个 block 跨过一个极度保守的阈值后再整块迁移，而是按 wordline 跟踪读扰动风险，只回收真正接近失效的 wordline。与此同时，它还会在每次读时按 wordline 的有效性调节 `Vpass`，主动减少未来扰动，因此能同时降低 reclaim 流量和读尾延迟。

## 问题背景

论文要解决的是一个随着 NAND 密度上升而不断恶化的可靠性与性能矛盾。现代 3D NAND 每个 block 里存的数据更多，阈值电压窗口又更窄，因此一次读操作会扰动更多邻近数据，而且同样的扰动更容易更早变成不可纠正错误。作者先用真实 SSD 说明这已经不是“小维护开销”问题：一块 176-layer QLC SSD 在只有 `30 TB` 主机读流量后，就会产生 `8.7 TB` 的内部写入；若持续读流量只有 `50 MB/s`，按照 `200 TBW` 估算，`144` 天就可能耗尽寿命预算。

现有 SSD 之所以表现糟糕，根源在于标准 read reclaim (`RR`) 是 block 粒度、而且是反应式的。控制器只给每个 block 维护一个读计数器，设置统一的 `RC_MAX`，一旦超过阈值，就把整个 block 的所有有效页全部复制出去。这个策略只有在 `RC_MAX` 按最坏访问模式来设置时才是安全的。问题在于，在高密度 3D NAND 里，“最坏情况”和“平均情况”之间差距极大，因为读扰动在不同 wordline 上高度不对称：目标 wordline 的相邻 wordline 受到的压力远大于非相邻 wordline，而不同 wordline 自身的容忍度也差别很大。论文给出的例子很直观：同一个 TLC block，若持续读取某个最弱 wordline 的邻页，只能承受 `54,560` 次读；若 block 内页面被均匀顺序读取，则可承受 `518,420` 次。只要采用 block 级阈值，就必须为前者买单，于是在后者这种更常见的场景里不断触发大量过早 reclaim。

反应式 reclaim 又进一步放大了问题。因为 SSD 只有在扰动错误已经明显累积后才行动，所以每次 reclaim 都要复制大量其实还安全的有效数据。随着密度继续上升，即便策略本身完全正确，这个搬运成本也会越来越高。论文对五类 flash 芯片的对比也说明了趋势：在最坏模式下，3D QLC 的可容忍读次数比 2D MLC 低 `88.2%`，比 2D TLC 低 `79%`。也就是说，未来 SSD 不能只是把 block-level RR 调得更精细一些，而是需要换一个控制粒度。

## 核心洞察

论文的核心主张是：读扰动应该以 wordline 为单位来管理，而不是以 block 为单位；并且控制器可以足够准确地估计每条 wordline 的风险，从而安全地这样做。STRAW 的模型把一次读操作视为向其他 wordline 增加一定数量的“有效读次数”，但这个增量取决于它们与目标 wordline 是否相邻，以及该 wordline 自身有多脆弱。只要控制器能跟踪这些有效读次数，就可以只回收那些真正“压力过大”的 wordline，而把 block 里其余数据留在原地。

第二个洞察是，`Vpass` 不只是读扰动的来源，也是一个可编程控制旋钮。降低有效非目标 wordline 的 `Vpass` 能显著减少每次读带来的扰动，但如果直接这么做，会提高目标页的 bit error rate。STRAW 的器件表征给出了一条可行路径：如果先把无效 wordline 的 `Vpass` 提高，目标页的错误数反而会下降，于是系统就得到了一部分额外的错误裕量，可以拿来安全地下调有效 wordline 的 `Vpass`。这样就能在不触发 ECC 爆炸或额外 read-retry 的前提下，主动减少后续读扰动。

## 设计

STRAW 由两个紧密集成的机制组成，并落在 `StrawFTL` 中实现。`WR2` 负责 reclaim 策略，`SR2` 负责每次读时的扰动抑制。

`WR2` 依赖离线表征得到的两个参数：`ERC_MAX`，表示一条 wordline 可容忍的最大有效读次数；`alpha`，表示“读取相邻 wordline”相对于“读取非相邻 wordline”带来的压力倍数。为了让模型可落地，论文没有对每条 wordline 单独建模，而是把 block 内 wordline 按可靠性分成 Best、Good、Bad、Worst 四组。控制器维护按 block 和近似按 wordline 的计数器，然后把某条 wordline 的累计有效读估计为：相邻读次数乘以 `alpha`，再加上非相邻读次数的单位权重。如果某条有效 wordline 已经超过 `ERC_MAX`，或者在下一个检查周期前会超过，`WR2` 就只复制这条 wordline 上的有效页，block 其余部分继续留在原地。

这样的设计立刻带来元数据开销问题：按 wordline 计数远比每个 block 一个计数器贵得多。论文的做法是用 Space-Saving 流算法实现 `REC`，也就是 Resource-Efficient Counter。它只给每个 block 保留有限数量的热点 wordline 计数器，而且保证不会低估真实读数；如果出错，也只会偏保守，提前 reclaim，而不会冒数据损坏风险。论文默认配置是在一个 `704`-wordline block 上使用 `32` 项 `REC`，这样能大幅压缩元数据，同时保留大部分收益。

`SR2` 则负责主动降压扰动。每次读之前，`StrawFTL` 会根据 block 的 P/E cycle、两个相邻 wordline 的有效性，以及非相邻无效 wordline 的占比，查询一个 `Vpass` 表来选择安全的最小电压模式。无效 wordline 使用高于默认值 `10%` 的 `Vpass`，而有效的非相邻 wordline 在安全时可以采用更低的 `Vpass`。随后，控制器还会用 `beta` 加权的方式更新 reclaim 计数器，使得“在更低 `Vpass` 下完成的读”在未来累计的扰动压力更小。整体上，这套机制依赖离线 profiling、少量额外固件表项、近似计数器，以及通过 `SET FEATURES` 之类现有接口为每条 wordline 设定 `Vpass` 模式的能力。

## 实验评估

论文的评估由两部分组成：器件级表征和系统级 SSD 仿真。器件侧，作者表征了 `160` 颗 3D TLC 芯片、`3,686,400` 条 wordline，并据此提取出 STRAW 使用的 `ERC_MAX`、`alpha` 和 `beta` 参数。这组数据直接支撑了两个机制：平均来看，读取相邻 wordline 带来的扰动大约是非相邻读取的 `8.4x`；把 `Vpass` 下调 `5%` 时，`ERC_MAX` 最多可提升 `59.1%`。

系统侧，作者在扩展后的 `NVMeVirt` 上运行了七个工作负载，覆盖 FIO、YCSB、Filebench、Lumos 和 Llama。与使用保守 block-level RR 的 baseline SSD 相比，完整 STRAW 在 `0K`、`1K`、`2K` P/E cycle 下，平均把 RR 诱发的 page copy 数量分别降低了 `90.0%`、`92.2%` 和 `93.6%`。尾延迟的变化与此高度一致：在相同三组条件下，`99.9th` 百分位读延迟平均下降了 `65.2%`、`71.1%` 和 `75.6%`。这正是论文最应该赢的指标，因为系统里拉长长尾的主要机制就是 reclaim 搬运流量。

其余实验主要用来回应潜在疑问。把 STRAW 和已有的热点页重分布方案 Cocktail 组合后，在读占比很高的工作负载上，相比 STRAW 单独使用，还能进一步把 page copy 数量最多再降 `31%`，说明这套机制更像是底层粒度升级，而不是只能替换所有既有优化。对于混合读写负载，尽管 wordline 级 reclaim 理论上可能增加垃圾回收触发次数，但总 block erase 次数仍平均下降 `53.6%`。`SR2` 的代价也很小：在测得的最坏情况下，更高预充电只会把总读延迟提高最多 `1.2%`。就论文目标场景而言，我认为这组实验是有说服力的，前提是目标 TLC SSD 控制器确实具备所需的电压模式和 profiling 流程。

## 创新性与影响

和 Cocktail 这类 RR 优化相比，STRAW 的新意不在于 reclaim 之后怎样更聪明地重新分布热点页，而在于它首先拒绝继续把整个 block 当作读扰动管理的最小单位。和更早面向 2D NAND 的 `Vpass` 缩放工作相比，它的关键新贡献则是说明：在更脆弱的高密度 3D NAND 里，仍然可以借助无效 wordline 提供的错误裕量，把电压缩放安全地用起来。

因此，这篇论文对 SSD 控制器研究者和高密度 flash 存储系统工程师都很重要。它是一篇机制设计论文，但落地路径相当清楚：付出有限的控制器状态和少量芯片控制逻辑改动，就能同时换回更好的寿命和更低的尾延迟。

## 局限性

STRAW 依赖大量离线表征，并且表项要按 P/E cycle 和 wordline 质量分桶，因此跨 flash 世代迁移并不是零成本。它的实现也默认 commodity 芯片已经暴露、或至少可以暴露足够细粒度的 per-wordline `Vpass` 控制能力。作者认为这在工业上是可行的，但当前原型仍然是“基于仿真器评估的设计”，而不是已经量产的 SSD。

此外，计数器设计本身存在精度与开销权衡。近似 `REC` 计数器不会少算，这保证了安全性，但在缺乏稳定热点的工作负载里可能因为高估而提前 reclaim。最后，论文最细致的器件表征仍然集中在一代 3D TLC 芯片上；虽然总体动机讨论了 QLC 与未来更高密度器件，但最强的结论仍然是关于趋势和机制，而不是说同一套参数可以不加修改地复用于所有 flash。

## 相关工作

- _Cai et al. (DSN '15)_ — 这项工作刻画了 MLC NAND 中的 read disturb 与 `Vpass` 缓解方法，而 STRAW 把电压缩放思路迁移到现代 3D NAND，并把它和 SSD 级 reclaim 控制绑在一起。
- _Hong et al. (FAST '22)_ — GuardedErase 利用 weak-wordline 差异来优化 SSD 的 erase 管理，STRAW 则利用 per-wordline 差异来控制 read-disturbance reclaim。
- _Park et al. (ASPLOS '21)_ — 这篇 read-retry 优化论文从另一个来源降低现代 SSD 读延迟；STRAW 与其互补，因为它针对的是 reclaim 引起的尾延迟和扰动累积。
- _Chun et al. (HPCA '24)_ — RiF 主要加速 NAND 芯片内部的 read-retry，而 STRAW 则降低读扰动把 SSD 推入高代价 retry 与 reclaim 区间的频率。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "Arm Weak Memory Consistency on Apple Silicon: What Is It Good For?"
oneline: "论文利用 Apple silicon 可切换的 TSO 模式直接比较 Arm 与 TSO，发现大多数性能差距很小，而明显慢下来的案例多半是实现瑕疵，不是 TSO 本身的代价。"
authors:
  - "Yossi Khayet"
  - "Adam Morrison"
affiliations:
  - "Tel Aviv University, Tel Aviv, Israel"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790129"
tags:
  - hardware
  - formal-methods
  - verification
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文抓住了 Apple silicon 一个罕见特性：同一颗商用 CPU 可以在运行时切到 `TSO` 模式，因此作者能在同一套硬件上直接比较 Arm 弱内存模型和 `x86-TSO`。结论很明确：在 Apple M 系列上，`TSO` 通常只比 Arm 慢 `3%` 左右，明显的慢速案例大多来自 Apple 当前 `TSO` 实现的 artifact，而不是 `TSO` 排序约束本身。

## 问题背景

论文的出发点不是“TSO 能不能更快”，而是弱内存模型值不值得整个软件栈为它付出复杂度成本。Arm 这类弱模型允许比 `TSO` 更多的乱序可见行为，因此并发程序、编译器映射和 verification / model checking 工具都更难推理。作者把这称为持续存在的“复杂度税”：Linux 内核持续积累显式 memory-ordering 代码，系统软件里确实出现过 Arm 风格重排导致的 bug，而弱内存也让模型检查必须面对更多可能执行。

如果这种复杂性换来的是不可替代的性能，软件社区也许只能接受。但此前支持“优化过的 `TSO` 未必明显更慢”的证据，几乎都来自 simulator 或 FPGA prototype；与此同时，M1 上已有工作又报告过更明显的 `TSO` slowdown。于是论文要回答的就是：在一颗能同时运行 Arm 模式和 `TSO` 模式的商用 CPU 上，观测到的差距究竟是 `TSO` 天生的代价，还是某个具体实现的副作用？

## 核心洞察

论文最重要的命题是：只要处理器在“不让程序观察到 `TSO` 违规”的前提下尽量保留 Arm 模式下的乱序优化，`TSO` 就未必会比 Arm 明显更慢。换句话说，真正该比较的不是“非常保守的 `TSO`”和 Arm，而是“内部仍然激进优化、只在可能暴露违规时才 squash 的 `TSO`”和 Arm。

Apple 提供的运行时 `TSO` bit 让这个命题第一次能在同一套商用硅片上直接检验。作者也因此把 slowdown 分成两类：如果差距来自过于保守的 squash 逻辑、特殊 load/store 路径，或者某些指令在 `TSO` 下的实现瑕疵，那它反映的是 Apple 当前 `TSO` mode，而不是 `TSO` 这个内存模型本身。

## 设计

这是一篇 measurement-and-explanation paper，不是新机制论文。第一部分是有针对性的 microbenchmark，用来反向推断 Apple 在 `TSO` 模式下到底保留了多少 Arm 弱内存优化。对 load-load reordering，作者构造了只有在乱序真正变成可观察行为时才该受罚的访存模式，结果发现 Apple silicon 在 `TSO` 模式下仍会投机地乱序执行 load，并且只在 `L1` invalidation 暗示可能出现可见违规时才 squash。对 store-store 行为，M4 P core 的结果又显示，`TSO` 模式仍能让命中 `L1` 的 store 有效地绕过更老的 cache-missing store，这说明 Apple 的 `TSO` 并没有把弱内存硬件优化全部关掉。

第二部分是应用级评估。作者在 M1 和 M4 上测试了 49 个 workload，来源覆盖 SPEC CPU 2017、PARSEC、SPLASH-2x 和 OpenBenchmarking，并比较单核和多核执行。实验方法也很扎实：控制 P core / E core 放置，按需要使用 macOS、原生 Linux 或 Linux VM，随机化 benchmark 执行顺序，并重复运行直到 `95%` 置信区间收敛到 median 的 `1%` 以内。

## 实验评估

最核心的实验结论是：`TSO` 与 Arm 的距离远比很多人想象的小。在 M4 P core 上，如果先排除七个作者随后会分析的重度 outlier，`TSO` 相对 Arm 的每应用平均 slowdown 的 harmonic mean 只有 `1.9%`，而且大多数应用都在 `3%` 以内。即便把 outlier 也算进去，整体 harmonic-mean slowdown 也只有大约 `4.2%`。

论文最有说服力的地方在于，它没有把 outlier 直接解释成“TSO 本来就慢”，而是继续追根因。四个 SPEC outlier，`bwaves`、`cactuBSSN`、`wrf` 和 `roms`，根因都是有效 memory-level parallelism 被吃掉了：`TSO` 模式下的 load-squash 机制会对映射到相同 `L1` set 的 benign self-conflict 反应过度，随机化 intra-page allocation offset 后，冲突和 slowdown 都基本消失。`fluidanimate -O0` 的慢来自 partial store-to-load forwarding 被疑似串行化；把代码改成数据宽度匹配的访问后，问题消失。M1 P core 上的 `ffmpeg_x264` 则暴露了另一种 artifact：大于 `16 B` 的 NEON load 在 `TSO` 模式下会异常缓慢，而这个问题在 M4 上已经不存在。真正更像“缺失优化导致慢”的案例只有 M4 E core 上的 `lbm`，因为那里的 `TSO` 实现没有 P core 那种 store-store 优化。

这些结果很好地支撑了论文主张，因为许多最大 slowdown 甚至出现在单核执行里，而单核执行根本不可能出现跨核可观察的 `TSO` 违规。这几乎直接说明，主导这些差距的并不是“更强排序约束必然更贵”。

## 创新性与影响

相对于 _Guiady et al. (ISCA '99)_ 以及后续 optimized-TSO 设计，这篇论文的新意不在于再给出一个 simulator 论证，而是在商用 Apple silicon 上直接做 Arm 与 `TSO` 的一一对照。相对于 _Wrenger et al. (JSA '24)_ 和 _Beck et al. (ASPLOS '23)_ 这类只报告 M1 `TSO` slowdown 的工作，它最大的推进是因果解释：不是把 slowdown 当成自明事实，而是把主要 outlier 追到具体的微架构 artifact。

这让论文同时影响两个方向。对硬件架构研究者来说，它说明弱内存 ISA 复杂度未必能在激进 OoO 商用核心上换来足够大的性能回报。对 PL 和 verification 研究者来说，它则提供了现实依据，支持“弱硬件模型给软件带来的复杂度，可能比默认想象的更不值”这一判断。

## 局限性

论文非常清楚自己的边界。首先，它只衡量运行时间，不衡量能耗或能效，因此没有回答 `TSO` 在 perf-per-watt 上是否也同样接近 Arm。其次，它研究的是 Apple 的单 die M-series 处理器，而不是多 die 设计、简单顺序核或其他厂商的 Arm 微架构，所以结论最强的适用范围仍然是高性能 Apple silicon。

此外，“`TSO` 可以这么快”并不等于“所有 `TSO` 实现都会这么快”。应用套件虽然很广，但仍可能漏掉那些更依赖 barrier、atomic、coherence 或能耗特性的真实工作负载。

## 相关工作

- _Guiady et al. (ISCA '99)_ — 用 simulation 论证强一致性配合激进硬件也能接近弱模型性能，而这篇论文把类似命题搬到了真实 Apple 商用 CPU 上检验。
- _Ros et al. (ISCA '17)_ — 提出适用于 TSO 的 non-speculative load-load reordering；Apple 的结果从实证角度支持了“强模型也能保留大量弱模型优化”的思路。
- _Wrenger et al. (JSA '24)_ — 报告了 M1 在 SPEC FP 上的 `TSO` slowdown，而本文扩大了 workload 范围，并把主要 outlier 追溯到具体实现 artifact。
- _Beck et al. (ASPLOS '23)_ — 观察到 M1 `TSO` 模式下 Geekbench 分数明显下降；本文则强调，不做 root-cause analysis 就不能把这种差距直接归咎于 `TSO` 本身。

## 我的笔记

<!-- 留空；由人工补充 -->

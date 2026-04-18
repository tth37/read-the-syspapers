---
title: "Characterizing and Emulating FDP SSDs with WARP"
oneline: "WARP 证明 FDP 只有在 RUH 分类真正贴合数据寿命时才接近 1.0 WAF，并把真实 SSD 隐藏的隔离、OP 与 GC 策略变成可解释、可优化的仿真器旋钮。"
authors:
  - "Inho Song"
  - "Shoaib Asif Qazi"
  - "Javier Gonzalez"
  - "Matias Bjørling"
  - "Sam H. Noh"
  - "Huaicheng Li"
affiliations:
  - "Virginia Tech"
  - "Samsung Electronics"
  - "Western Digital"
conference: fast-2026
category: flash-and-emerging-devices
code_url: "https://github.com/MoatLab/FEMU"
tags:
  - storage
  - hardware
  - observability
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文说明，`FDP` 既不是 SSD 写放大问题的万能解药，也不是噱头：只有当 `RUH` 分类真正贴合数据寿命时，它才会逼近 `1.0` WAF；一旦分类失配或控制器内部重新引入干扰，效果就会迅速退化。`WARP` 的价值在于，它把商用 FDP SSD 隐藏起来的控制器决策显式化，让研究者既能复现实机趋势，也能系统探索更好的策略。

## 问题背景

云存储系统关心写放大（`WAF`），因为它直接影响 SSD 寿命、设备更换成本，以及大规模闪存部署的可持续性。`FDP` 的初衷正是降低 WAF：主机把写请求打上 reclaim unit handle（`RUH`）标签，让寿命相近的数据尽量被放到一起回收。与 `OpenChannel` 或 `ZNS` 不同，FDP 保留了传统 block interface，不要求应用做大规模改造，因此从部署角度看非常有吸引力。

问题在于，FDP 只是提示接口，不是强保证。真正的垃圾回收仍然发生在厂商固件内部，而这些内部策略对主机完全不可见。两块都宣称支持 `NVMe FDP` 的 SSD，可能因为 reclaim-unit 大小、over-provisioning（`OP`）比例、lazy GC 阈值，甚至 `II` / `PI` 隔离语义不同，而在同一 workload 上得到完全不同的 WAF。主机看不到 GC copy 是否保留原始 RUH，也看不到某个 RUH 的失效流量是否会抬高其他 RUH 的放大开销。

因此，真正的问题不是“FDP 有没有用”，而是“它在什么条件下有用、在什么条件下失效，以及背后是哪类隐藏的控制器设计在决定结果”。这个问题不仅关系到固件研究，也关系到 `CacheLib`、`F2FS` 以及未来任何想利用 FDP 的上层系统。如果没有一个透明模型，社区就只能得到针对单一设备、单一 workload 的经验性结论。

## 核心洞察

论文最重要的命题是：FDP 的收益来自两层分类是否对齐。第一层是主机把数据寿命映射到 `RUH` 的分类；第二层是设备内部如何管理空闲空间与垃圾回收的隐藏策略。只有这两层对齐时，FDP 才可能接近 `1.0` WAF。只要主机把冷热数据混进同一个 RUH，或者设备在回收时重新制造跨 RUH 干扰，FDP 就会逐步退化成普通 SSD 行为。

这也是为什么 `WARP` 与实机测量同样重要。`WARP` 把原本不可见的控制器自由度显式化：`II` 与 `PI` 的隔离语义、reclaim-unit 大小、`OP` 比例、victim selection、lazy GC 阈值，以及 block remapping。只有这些旋钮可见以后，论文才能解释那些商用硬件上只能“看到结果、看不到原因”的现象。换句话说，FDP 更像是一份 best-effort 契约，而不是一个打开就会稳定生效的 host API 开关。

## 设计

`WARP` 基于 `FEMU` 扩展而来，能够解析 NVMe 请求中的 FDP 标签，并把写入映射到 reclaim unit（`RU`）和 reclaim unit handle（`RUH`）。在放置语义上，它同时实现了标准中的两种模式。`II` 会把主机写入放进目标 RUH，但把 GC copy 重定向到一个共享的 GC-RUH；这种做法容易嫁接到传统 FTL 上，但长期隔离性较弱。`PI` 则要求 GC copy 继续留在原 RUH 中，隔离更强，但代价是每个 RUH 都需要自己的 slack space，因此更容易碎片化。

垃圾回收被拆成两个决策。第一步是选哪个 RUH 回收，可以用 greedy 或 pressure-based 之类的策略。第二步是在该 RUH 内选哪个 victim RU，可以使用简单 greedy，也可以使用基于 utilization 与 age 的 cost-benefit。`WARP` 还实现了 lazy GC、前后台 GC 阈值分离，以及对完全有效块的 block remapping，从而把 FDP GC 从“固件黑盒行为”变成可控的研究表面。

另一半设计价值来自可观测性。`WARP` 记录 device-level 的 host bytes、media bytes 与整体 WAF，也记录 RUH-level 的 host bytes、GC-copy bytes、allocation、eviction、remap 等计数，并提供 per-GC-event 级别的结构化日志，标出 victim RUH、destination RUH、copied pages 与耗时。论文借此揭示了两个关键病灶。`Noisy RUH` 指一个 RUH 中的 invalidation 会间接提升其他 RUH 的 GC 压力；`Save Sequential` 指一个本来应当天然友好的大规模顺序流，仍可能因为 slack 不足和 GC 策略而被过早回收，反而成为主要的 WAF 来源。与此同时，RU 大小、`OP` 比例与 RUH 数量也都被做成运行时参数，而不再是厂商写死的几何常量。

## 实验评估

实机刻画首先说明，FDP 的收益是有条件的。在单流 `128 KB` 随机写下，两块商用盘的稳定 WAF 明显不同：`SSDA` 大约停在 `2.0`，`SSDB` 则接近 `3.5`。在三流 workload 中，如果 RUH 分类准确而且访问偏斜足够强，FDP 可以维持接近理想值；但一旦变成 `80/20` 重写或 uniform-random invalidation，收益就会快速塌缩。论文的第一个结论是：主机分类准确是必要条件，但绝不是充分条件。

`CacheLib` 给出了最有说服力的端到端证据。在 `kvcache` 上，`BigHash` 与 `BlockCache` 的写入行为天然不同，FDP 实际上消除了“更高 hit ratio 往往意味着更高 WAF”的老问题。在 `40%` SOC 时，WAF 从 `1.85` 降到 `1.27`，而 hit ratio 仍保持在大约 `82%`。在多租户实验中，noisy neighbors 会把非 FDP 情况从 `1.28` 推到接近 `3.0`，而 FDP 把最坏情况控制在约 `2.6`。相对地，`cdn` 与 `twitter` trace 本来就接近 `1.0` WAF，开启 FDP 也没有带来回退。`F2FS` 则是一个反例：eBPF tracing 显示大约 `99%` 的用户写入都带着同一种泛化 hint，结果几乎所有数据都被送进同一个 RUH，设备表现自然退化为 `NoFDP`。

`WARP` 随后复现了这些趋势，并进一步给出机制解释。经过标定后，它在随机写场景中覆盖了与商用盘相同的 `2.0-3.5` WAF 区间；在 `CacheLib` 的 `40%` SOC 场景中，也能复现同方向改善（`2.00 -> 1.37`）。更重要的是，per-RUH 日志解释了某些 workload 为什么失败：一个很小的 invalidation 流可能让其他 RUH 变得更贵，而一个容量占主导的顺序流也可能反而成为放大的主要来源。`II` 与 `PI` 的比较尤其有价值。以 `256 MB` RU 为例，在 `3%` `OP` 时，`II` 的 WAF 是 `2.92`，而 `PI` 反而更差，为 `3.80`；当 `OP` 增加到 `10%` 时，`PI` 才优于 `II`，分别是 `1.181` 对 `1.338`。最后，`WARP` 还能指导优化：给 `CacheLib` 中 noisy 的 small-object handle 分配更小的 RU，可把 WAF 再从 `1.37` 降到 `1.16`。

## 创新性与影响

相较于 _Allison et al. (EuroSys '25)_ 这类展示单一应用栈如何从 FDP 受益的工作，这篇论文问的是更基础的问题：为什么同一个 FDP 接口会在不同设备和 workload 上表现差异巨大。相较于 _Bjørling et al. (FAST '17)_ 与 _Bjørling et al. (ATC '21)_，它突出了 FDP 的“中间地带”属性：比 `OpenChannel` 和 `ZNS` 更容易部署，但也因此更黑盒、更难推理。相较于 _Li et al. (FAST '18)_，它把 `FEMU` 从通用 SSD 仿真器推进成了一个带显式隔离语义与 RUH 级遥测能力的 FDP 研究平台。

这让论文对三类读者都有实际价值。做固件的人得到一个透明的 controller-policy playground；做系统的人得到证据，知道真正重要的不只是 NVMe 接口，还包括 RUH 分类质量与 workload 组成；做应用和文件系统的人则得到一个提醒：上层如果只会把绝大多数写入压成一个类别，那么“支持 FDP”本身并不会带来收益。

## 局限性

这篇论文最强的部分是 WAF，而不是全方位性能建模。它确实给出了 `WARP` 的延迟标定结果，但评估重点还是写放大，不是把商用控制器的每个微观细节都按时钟级重建。作为第一篇平台型论文，这个范围是合理的，但也意味着 `WARP` 更擅长解释趋势，而不是逐项复刻所有硬件内部机制。

跨设备研究也比已有工作更宽，但仍然有限。论文只分析了两块商用 FDP SSD，而且明确说明 `SSDB` 在高写压测试后失效，因此该设备的结果是不完整的。软件生态方面，`F2FS` 也说明了现实限制：接口存在不代表收益自动出现，如果 tagging 过于粗糙，设备就没有发挥空间。

## 相关工作

- _Allison et al. (EuroSys '25)_ - 将 `FDP` 集成进 `CacheLib` 并展示缓存层收益，而 `WARP` 进一步解释这些收益背后的设备策略差异。
- _Bjørling et al. (FAST '17)_ - `LightNVM` 把放置与垃圾回收控制交给主机，而 `FDP` 仍把 GC 留在设备内部，只暴露提示接口。
- _Bjørling et al. (ATC '21)_ - `ZNS` 同样试图降低写放大，但它依赖主机显式遵守顺序写约束，FDP 则避免了这种侵入式要求。
- _Li et al. (FAST '18)_ - `FEMU` 是 `WARP` 的底座，但它本身并不建模 `RUH` 隔离语义，也没有 FDP 所需的 per-RUH telemetry。

## 我的笔记

<!-- 留空；由人工补充 -->

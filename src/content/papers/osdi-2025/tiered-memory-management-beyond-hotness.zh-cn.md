---
title: "Tiered Memory Management Beyond Hotness"
oneline: "AOL 用 latency 与 MLP 估计真实性能影响，再据此做对象放置和页迁移节流，而不是只看 hotness。"
authors:
  - "Jinshu Liu"
  - "Hamid Hadian"
  - "Hanchen Xu"
  - "Huaicheng Li"
affiliations:
  - "Virginia Tech"
conference: osdi-2025
code_url: "https://github.com/MoatLab/SoarAlto"
tags:
  - memory
  - disaggregation
  - kernel
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文认为，tiered memory 不该围绕 hotness 优化，而该围绕真实的“暴露延迟代价”优化。作者提出的 amortized offcore latency（AOL）把 memory latency 与 memory-level parallelism（MLP）结合起来，再据此设计 Soar 和 Alto：前者做离线对象放置，后者做在线页迁移节流。

## 问题背景

现有 tiered-memory 系统大多默认一个前提：越热的页越重要，应该优先留在 DRAM。这个前提实现简单，却忽略了现代 out-of-order CPU 会重叠许多 miss。一个高频访问页如果位于高 MLP 的顺序流中，可能几乎不暴露 stall；反而一个访问次数较少、但位于串行 pointer-chasing 路径上的页，才真正决定运行时间。

作者用一个 microbenchmark 把这个问题说得很清楚：一个线程执行 sequential read，另一个执行 pointer chasing。顺序区域平均热度高出 13.6x，但若按 hotness 把这些“热页”留在 DRAM、把 pointer-chasing 页放到 slow tier，性能只剩全 DRAM 配置的 52.4%。反过来放置，反而快 34%。这说明现有 tiering 系统会犯两层错误：先放错数据，再为修正误判支付大量迁移开销。

## 核心洞察

论文的核心命题是，tiering 应该优化“暴露出来的 stall 成本”，而不是访问次数。一次 slow-tier 访问只有在其 latency 真正暴露给 CPU 时才会伤害性能；如果多个 miss 可以重叠，单次访问的代价就会被摊薄。AOL 试图捕捉的正是这个量：用 memory latency、MLP 和 LLC stall pressure 近似 slow-tier 访问对运行时间的真实贡献。

有了这个指标，两个策略就顺理成章。其一，把累计 AOL 贡献最高的对象一开始就放进 fast tier，尽量避免后续 migration。其二，如果当前阶段 AOL 很低，就说明 slow-tier latency 大多已被掩蔽，此时继续 promotion 热页通常不值得。AOL 因而同时回答了“什么该放进 DRAM”和“什么时候迁移值得做”。

## 设计

技术核心首先是一个 AOL-based slowdown predictor。论文先证明，slow tier 带来的 slowdown 与新增 LLC stall cycle 高度相关；然后再用 MLP 修正高 MLP workload 中的过估计。系统只用四个 PMU counter 就能估计 latency、MLP 与基础预测量，再乘上按硬件离线标定的修正因子 `K = f(AOL)`。在 56 个 workload 上，这个模型把预测与真实 slowdown 的 Pearson 相关系数从 0.869 提升到 0.951。

Soar 把这个信号用于离线对象排序。它通过 `LD_PRELOAD` 截获 `malloc`/`free` 与 `mmap`/`munmap`，按 call chain 对分配分组；再用 PEBS 采样 LLC miss，并记录 AOL 驱动的性能事件。系统把对象生命周期、采样地址和区间级性能估计拼接起来，得到每个对象的 AOL 加权分数，再按对象大小归一化形成 unit score。部署时，`libnuma` 将高分对象直接放入 fast tier，把其余对象留在 slow tier。

Alto 处理在线场景，但不重新发明 page tracker，而是包裹在 TPP、NBT、Nomad、Colloid 等现有系统外层。每个采样周期，Alto 读取 PMU counter、计算 AOL，并与低阈值和高阈值比较。AOL 低时说明 promotion 大多不值，系统就节流甚至关闭 promotion；AOL 高时沿用 baseline policy；中间区间则只放行一部分候选页。整个实现只改了大约 30 行 Linux migration path。

## 实验评估

实验使用两套平台：一套是 CloudLab 上模拟 2.1x fast/slow latency gap 的 Skylake NUMA 服务器，另一套是配备真实 ASIC-based CXL expander、latency gap 为 2.4x 的 Sapphire Rapids 服务器。工作负载覆盖图计算、ML、缓存和 HPC。

Soar 最有说服力的结论是：性能感知的首次放置常常优于所有反应式 baseline。在 `bc-urand` 上，即便 90% 内存位于 slow tier，Soar 的 slowdown 仍低于 20%，而 NUMA 平台上的 Nomad 会到 217%。在真实 CXL 上，Soar 最差为 42%，相比之下 Nomad 达到 588%，Colloid 达到 92%。在更广泛的 workload 集合、50% slow-tier ratio 下，Soar 的 slowdown 为 4%-18%，而 NBT 最高 68%，Nomad 123%，TPP 甚至 1246%。

Alto 的价值主要体现在少做无效工作。它最多把 page promotion 次数减少 127.4x，并将其转化成对 baseline 的性能收益：相对 TPP 提升 2%-471%，相对 NBT 提升 1%-23%，相对 Colloid 提升 0%-18%，对 Nomad 也大多有正收益，而少数回退被限制在约 2%-3%。论文也承认，在强 bandwidth contention 下，queueing delay 会抬高 AOL，默认阈值会变得不再合适，需要上调后才能恢复收益。

## 创新性与影响

相较于 _Al Maruf et al. (ASPLOS '23)_、_Xiang et al. (OSDI '24)_ 和 _Vuppalapati and Agarwal (SOSP '24)_，这篇论文的主要新意不是换一个更好的 hot-page detector，而是换一个不同的控制信号：以暴露延迟代价取代访问频率，并把同一信号同时用于离线 placement 和在线 migration control。

它更大的影响是观念上的。论文为 CXL 时代的 tiering 给出了一个简洁而可操作的指标，把 PMU 可观测行为与真实性能收益连接起来，也说明了 "hotter means more important" 不是可靠的默认抽象。

## 局限性

Soar 需要一次“全部位于 fast tier”的 profile run，因此更适合分配点稳定、行为可重复的应用。它还以对象为粒度做排序，而不是对象内部的更细粒度区域，所以混合了关键页和非关键页的大对象仍可能被放置得不够理想。

Alto 的轻量化来自于它不直接估计 per-page 性能影响，而只是调节现有系统迁移自己挑出来的候选页。它的 AOL 阈值也依赖硬件，并且在重 bandwidth contention 下会变得不稳定。自动阈值调优和更细粒度的在线策略都被留给了未来工作。

## 相关工作

- _Dulloor et al. (EuroSys '16)_ — X-Mem 依赖更粗粒度的 region classification，而不是像 AOL 这样显式建模 MLP 的性能指标。
- _Al Maruf et al. (ASPLOS '23)_ — TPP 是典型的 hotness-driven CXL tiering 系统，而 Alto 正是针对这类激进 promotion 策略提出的调节层。
- _Xiang et al. (OSDI '24)_ — Nomad 通过 non-exclusive migration 降低阻塞，而本文认为很多迁移本身就不该发生。
- _Vuppalapati and Agarwal (SOSP '24)_ — Colloid 重点处理 bandwidth saturation 下的 latency 平衡，而 Soar/Alto 更关注暴露出来的 latency 成本。

## 我的笔记

<!-- 留空；由人工补充 -->

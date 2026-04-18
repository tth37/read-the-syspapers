---
title: "CounterPoint: Using Hardware Event Counters to Refute and Refine Microarchitectural Assumptions"
oneline: "CounterPoint 用带噪声的硬件事件计数器检验专家写下的微架构模型，并借由违约约束反推出隐藏的硬件行为。"
authors:
  - "Nick Lindsay"
  - "Caroline Trippel"
  - "Anurag Khandelwal"
  - "Abhishek Bhattacharjee"
affiliations:
  - "Yale University, New Haven, Connecticut, USA"
  - "Stanford University, Stanford, California, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790145"
tags:
  - hardware
  - memory
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CounterPoint 用来检验“专家脑中的微架构故事”是否真能和硬件事件计数器数据对上。它把假设写成 `muDD`，自动导出隐含约束，再与带 multiplexing 噪声的统计置信区域做比较。以 Intel Haswell 的 MMU 为例，这个过程推断出了若干可能被文档遗漏的行为，包括由 load-store queue 触发的 TLB prefetch、被合并的 page-table walk、可中止的 page walk，以及根级 MMU cache 的迹象。

## 问题背景

现代 CPU 暴露了很多 hardware event counters，但“直接看计数器就能看懂硬件”在实践里并不成立。计数器语义往往不够清楚，硬件实现又是黑盒，而且一次只能精确测少量计数器，更多计数器只能靠 multiplexing 轮流采样。于是研究者面对异常读数时，常常只能靠经验判断到底是模型错了，还是噪声太大。

作者指出，这个问题在 virtual memory 硬件上尤其尖锐。连“PDE cache miss 不应超过 page walk”这样看似朴素的 Haswell 假设，都会在真实数据中被打破。随着计数器数量增加，隐含约束会快速膨胀，而每条约束又同时依赖 page size、cache hit、walk completion、abort 等多个条件。难点不只是收集 counters，而是系统性地检验整套微架构叙事是否与噪声观测相容。

## 核心洞察

最重要的洞察是：专家不该手写计数器约束，而应该先把自己相信的硬件行为写成执行路径图，再让系统自动推出约束。CounterPoint 提出的 `mu-path Decision Diagram`，即 `muDD`，就是为此服务的。每条路径对应一种可能的微架构执行路径，并带有一个 counter signature，记录它会增加哪些计数器。只要存在某个非负组合能拼出观测值，模型就是 feasible 的；如果不存在，就说明隐藏假设有问题。统计上的另一半也很关键：CounterPoint 不是给每个计数器单独套误差条，而是利用计数器相关性构造多维置信区域，从而避免真实违约被 multiplexing 噪声掩盖。

## 设计

CounterPoint 的流程分三步。第一步，专家用一个很小的 DSL 描述动作、计数器递增点和决策分支，系统把它编译成 `muDD`。随后它枚举所有 `mu-path` 的 counter signature，并据此定义 `model cone`，也就是所有可能由这些路径以非负流量组合出来的计数器向量集合。

第二步，CounterPoint 把像 `perf` 这样采样得到的时间序列转成 `counter confidence regions`。它显式估计协方差矩阵，构造 99% 置信椭球，再把椭球近似成沿主成分方向对齐的包围盒，这样就仍然可以用线性规划做可行性测试。论文也强调，这只是为了 tractability 的近似，不是精确编码。

第三步是 guided model exploration。若置信区域与 model cone 相交，观测就与模型相容；若不相交，CounterPoint 就导出被违反的 half-space 约束，让专家继续增删候选硬件特性。论文把这一过程拆成 discovery phase 和 elimination phase。实现上，CounterPoint 是一个大约 3K 行的 Python 库，使用了 Pandas、pulp 和可复现的 Docker 环境。

## 实验评估

评估以 Intel Haswell MMU 为核心案例，关注 native execution 下 data-side 的地址翻译行为。工作负载覆盖 GAPBS、SPEC2006、PARSEC、YCSB，以及线性和随机访问 microbenchmark；内存 footprint 从 250 MB 到 600 GB；页大小覆盖 4 KB、2 MB 和 1 GB。整体上，作者收集了大约 2000 万条计数器样本。

第一组结果先证明了相关性建模确实有价值。对几十个代表性的 `muDD` 来说，利用计数器相关性的置信区域，比假设计数器独立的做法多检测出超过 24% 的 model-constraint violation；对某些模型，增益甚至超过 75%。论文还报告，数据集中有超过 25% 的计数器对 Pearson 相关系数高于 0.9。作者的初始 Haswell 模型包含 31 个约束，其中 8 个被真实数据打破，之后才开始迭代精炼。

这些违约进一步暴露了具体硬件行为。CounterPoint 推断 Haswell 里存在一个由 load-store queue 驱动的 TLB prefetcher，其触发条件与顺序访问跨页边界有关；对递增地址，触发点出现在 cache line 51 和 52 之后；对递减地址，则是 8 和 7。论文还指出，这类 prefetch 会真正借助 page walker 向 pipeline 注入额外 load，而不是直接绕过它。除此之外，精炼后的模型还显示：针对同一虚拟页的 page-table walk 可以被 merge，在某些 workload 上几乎把独立 walk 数量减半；当模型不包含 walk bypassing 时，1 GB 页的观测与 root-level MMU cache 相容；而 aborted walk 甚至可能在发出任何 memory access 之前就发生。框架本身的运行成本也不算高：在 24-core Xeon E5-2680 v3 上，完整计数器集合下判断一条观测是否 feasible 大约需要 200 ms，评估一个模型平均需要 213 秒，显式推导约束则约为 0.8 到 10 秒。

## 创新性与影响

和以往那些“用 counters 逆向某一个具体硬件细节”的工作相比，CounterPoint 的创新更偏方法论。它给了研究者一条可复用的闭环：先写结构化模型，再自动导出所有隐含约束，用统计几何方法让带噪声的测量变得可比较，最后让违约约束驱动下一轮假设修正。和 BayesPerf、CounterMiner 这类专注 multiplexing 噪声处理的工作相比，它的贡献也不是单纯“降噪更好”，而是把降噪直接服务于微架构模型的一致性检验。因此，这篇论文最可能影响的是构建 simulator、分析模型、或研究不透明 CPU 行为的研究者。

## 局限性

作者对 Haswell 结论的表述很克制。论文明确承认，若要把这些发现提升为最终事实，仍然需要 proprietary RTL，因此这些结果更准确的理解方式是“与数据高度一致的解释”，而不是对实现细节的形式化证明。评估范围也集中在单一 CPU 家族、data-side 地址翻译和 native execution；multiple cores、multiple sockets、hyperthreading、kernel-level activity 以及 accelerator 都被留给了未来工作。

方法本身也有边界。CounterPoint 依赖专家提供足够丰富的 workload 与特性空间；如果 workload 从未触发某个角落行为，框架就不可能把它发现出来。整个搜索流程仍然是 expert guided，而不是全自动搜索；同时，置信区域最终采用的是椭球外包盒近似，计算上更方便，但理论上比更精确的公式更松。

## 相关工作

- _Lindsay and Bhattacharjee (IISWC '24)_ - 用 hardware counters 研究地址翻译的伸缩行为；CounterPoint 则把这类计数器解释流程提升成可复用的模型检验框架。
- _Banerjee et al. (ASPLOS '21)_ - BayesPerf 从统计角度降低 PMU 测量误差；CounterPoint 也利用计数器结构信息，但目标是为微架构模型构造 feasibility region。
- _Zhao et al. (USENIX Security '22)_ - Binoculars 用 counters 分析 page walker contention；CounterPoint 关注的是更一般的问题，即哪些隐藏的 MMU 特性能让观测数据变得可行。
- _Hsiao et al. (MICRO '24)_ - RTL2MuPATH 从 RTL 合成微架构路径；CounterPoint 则从专家手写的 `muDD` 出发，再去和真实硬件测量做一致性检验。

## 我的笔记

<!-- 留空；由人工补充 -->

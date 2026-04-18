---
title: "Tintin: A Unified Hardware Performance Profiling Infrastructure to Uncover and Manage Uncertainty"
oneline: "Tintin 把 HPC multiplexing 误差显式建模为运行时 uncertainty，并用一等 profiling context 同时改进事件调度与归因。"
authors:
  - "Ao Li"
  - "Marion Sudvarg"
  - "Zihan Li"
  - "Sanjoy Baruah"
  - "Chris Gill"
  - "Ning Zhang"
affiliations:
  - "Washington University in St. Louis"
conference: osdi-2025
code_url: "https://github.com/WUSTL-CSPL/tintin-kernel"
project_url: "https://github.com/WUSTL-CSPL/tintin-user"
tags:
  - observability
  - kernel
  - hardware
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Tintin 是一个面向 Linux 内核的 hardware performance counter profiling 基础设施，试图同时解决两个老问题：事件数多于可用计数器时的 multiplexing 误差，以及现有工具只能按 task 或 core 归因所带来的错配。它的关键做法是在线估计 measurement uncertainty，按 uncertainty 最小化来调度事件，并把任意 profiling scope 抽象成一等对象 Event Profiling Context（ePX）。

## 问题背景

论文首先指出一个基础失配。现代 CPU 往往支持几十到上千种可观测事件，但每个 core 真正可编程的 HPC 通常只有 2 到 6 个，Linux 还常常默认占掉其中一个。与此同时，真实系统又需要同时观察很多事件；无论是 Intel Top-Down 这类派生指标，还是 Pond 的延迟敏感性模型，背后都可能依赖十几个到几十个原始事件。Linux `perf_event` 的常见做法是 round-robin multiplexing，然后对没有被持续监控的时间段做插值。作者用 SPEC 里的 workload 说明，只要请求事件数超过可用计数器，报出的计数就会明显不稳定。

第二个问题是 attribution。HPC 本质上只是 per-core 的硬件计数器，真正决定“这次测到的事件该算到谁头上”的是操作系统。现有基础设施通常只能把事件绑定到 task 或 core 上，这对代码区域级 profiling 太粗，对重叠 scope 也太死板。例如一个系统可能同时想观察“这个 VM”“这个 function”“这个 core”，但 `perf_event` 会分别管理这些请求。结果是两类错误同时出现：无关执行被算进目标 scope，而重叠 scope 又会互相争抢稀缺计数器，导致后来的请求饥饿。论文用 DMon 做例子说明，按整个程序聚合的统计会把真正 backend-bound 的循环淹没掉。

## 核心洞察

Tintin 的第一个核心命题是，multiplexing 误差并不是用户态只能被动接受的黑盒噪声。插值之所以会错，是因为事件到达率在“没被测到”的那段时间里发生了变化；因此内核可以根据已观测到的方差，在线估计某个事件当前计数的 expected error，并把它作为 uncertainty 与 count 一起返回。一旦 uncertainty 成为显式量，事件调度就不再只是固定的 round robin，而变成了一个可以优化的问题。

第二个洞察更偏系统抽象：profiling scope 本身应该被提升为独立的一等内核对象。如果把代码片段、线程、进程、VM 以及它们的组合都翻译成统一抽象，内核就可以在正确边界放置 measurement calipers，协同管理重叠 scope，并在需要时把同一条底层硬件读数同时归到多个活跃 scope 上。作者把这个对象命名为 Event Profiling Context，也就是 ePX。

## 设计

Tintin 由三个模块组成。`Tintin-Monitor` 负责读计数器、对 multiplexed 计数做 trapezoid-area interpolation，并把“事件在未被监控期间的 expected count error”建模为方差的平方根。由于内核里不可能每次都回看全历史，它采用了加权版 Welford 增量更新算法来维护方差。实现上，Monitor 由 `hrtimer` 驱动，复用了 `perf_event` 现有的 PMU 读写接口，并通过定点数运算避免在内核里引入浮点开销。

`Tintin-Scheduler` 则把 measurement 问题转成加权 elastic scheduling。每个事件都被赋予一个 utilization，表示它占用某个硬件计数器的时间份额；调度器的目标是在计数器数量受限的前提下，最小化加权平方归一化误差总和。论文把这个问题映射到 real-time elastic scheduling，然后通过构造一个虚拟资源把多计数器情况串接起来，再把结果展开成各个 counter 上重复的 hyperperiod schedule。它还支持 event group、一个更简单的 `Uncertainty-First` 备选策略，以及最小 scheduling quantum，以避免切得过碎导致估计不稳定和中断过多。

`Tintin-Manager` 负责 attribution。它引入的一等对象 ePX 会把一个 profiling scope 及其事件集合打包管理。ePX 可以表示 thread、process、core、VM、function，也可以是几个 scope 的用户自定义组合。对于执行实例级 scope，Tintin 监听 CPU scheduling 事件；对于代码区域级 scope，它在入口和出口插入 syscall，使计数只在目标代码段内部开启。当多个 ePX 重叠时，Tintin 会把它们的事件集合并后统一调度，但仍然为每个 ePX 单独维护 count 与 uncertainty，并在一次硬件读数发生时把结果归给所有活跃且请求了该事件的 ePX。暴露给用户的 API 基本兼容 `perf_event`，只是额外增加了 context 创建、关联、设权重和读取 uncertainty 的能力。

## 实验评估

实验总体上支持论文的主张：uncertainty-aware scheduling 与更精细的 scope 控制，确实能显著提升在线 profiling 的可用性。对 SPEC CPU 2017 与 PARSEC，Linux `perf_event` 相对 pinned-counter ground truth 的平均计数误差是 9.01%，CounterMiner 清洗后也有 8.80%；Tintin 的 elastic scheduling 把平均误差降到 2.91%，而较简单的 `Uncertainty-First` 只能做到 6.51%。运行时开销仍然较低，Tintin 平均 overhead 为 2.4%，`perf_event` 为 1.9%，而 CPU 版 BayesPerf 的开销最高可到 31.3%，几乎不适合作为通用内核机制。

几个 case study 进一步说明问题不只是“数得更准”，而是“能不能把数算到正确对象上”。在 Pond 的 resource orchestration 模拟里，使用 Tintin 为 VM 线程建立 scope 后，100 次实验中有 95 次预测分数优于 Intel EMON 的 core-scope 基线，平均提升 0.51。相对 round robin，再启用 elastic scheduling 平均还能再提高 0.15；把 uncertainty 一并喂给模型后，平均又增加了超过 0.02。在存在重叠 scope 冲突时，workload 的计数误差只从 3.11% 小幅升到 3.56%，Pond 模型分数也仅下降 0.01。

对 DMon，`perf_event` 在 10 次运行里有 9 次没能找出真正 backend-bound 的代码区域，而 Tintin 借助 loop-level ePX 能稳定定位问题，目标函数的 backend 时间始终高于 91.1%。在 Diamorphine rootkit 检测实验里，AUC 从 `perf_event` 的 0.57 提升到 Tintin 的 0.66，加入 uncertainty 后进一步到 0.70。作为基础设施论文，这些证据已经相当有说服力，但也要承认，大部分应用验证仍是重现实验或单工作负载演示，还不是长期生产部署结果。

## 创新性与影响

相对于 _Banerjee et al. (ASPLOS '21)_，Tintin 并不依赖 Bayesian 推断和事件之间的代数关系去补未观测事件，而是把 uncertainty 当作内核可以廉价在线估计的通用量。相对于 _Lv et al. (MICRO '18)_，它明确面向在线控制回路，而不是多次运行后的离线清洗流程。相对于 _Khan et al. (OSDI '21)_，它贡献的是一个通用 scope primitive，让 DMon 这类工具可以建立在更可靠的归因基础上，而不是再做一个专用 profiler。把这三点放在一起看，这篇论文更像是在补系统基础设施，而不是提出一个新的 profiling 小技巧。

它最可能影响的是那些把 HPC 放进控制回路的系统，例如性能诊断、资源编排和异常检测。论文真正改写的不是某个具体应用，而是我们看待 HPC profiling 的方式：不再默认“计数器能给多少算多少”，而是把 measurement confidence 和 profiling scope 一并提升为系统级接口。

## 局限性

Tintin 并没有把 HPC 数据变成 ground truth。它的 uncertainty 模型本质上仍然是把方差当作插值误差代理，这个近似合理，但终究是间接估计。论文也明确承认，许多误差来源仍不在它的处理范围内，包括 polling 与 sampling 的固有取舍、skid effect、架构级 counter corruption，以及其他 PMU 微架构怪癖。也就是说，Tintin 修复的是一大类关键误差，但不是 PMU 正确性的总解决方案。

它还有部署边界。代码区域级 profiling 目前依赖源码级或编译器插桩，binary-only 支持被留到未来工作。对于“某些事件只能放到特定 counter 上”的 PMU，当前支持也有限。扩展性方面，几百个事件仍可接受，但当事件类型达到 1024 时，内核里的排序过程会让机器失去响应。最后，实验主要基于关闭 Hyper-Threading 的 Intel Skylake，跨架构适用性更多是通过复用 `perf_event` 接口来论证，而不是被直接实测覆盖。

## 相关工作

- _Banerjee et al. (ASPLOS '21)_ — BayesPerf 也想降低在线 multiplexing 误差，但它依赖事件关系和较重的推断流程；Tintin 用更通用的 variance-based uncertainty 模型加内核调度器来完成。
- _Lv et al. (MICRO '18)_ — CounterMiner 通过多次运行后挖掘和清洗 trace 来改善测量，而 Tintin 是给一次在线运行中的控制系统用的。
- _Khan et al. (OSDI '21)_ — DMon 说明了精确归因对 locality bug 诊断有多重要；Tintin 提供的 ePX 正是让这种归因真正可靠的底层机制。
- _Demme et al. (ISCA '13)_ — 早期恶意软件检测工作把 HPC 特征喂给分类器，Tintin 改进的是这些特征的质量与置信度，而不是重新设计检测模型。

## 我的笔记

<!-- 留空；由人工补充 -->

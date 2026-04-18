---
title: "Chips Need DIP: Time-Proportional Per-Instruction Cycle Stacks at Dispatch"
oneline: "DIP 直接对 dispatch slot 采样并做时间成比例归因，生成能暴露流水线入口瓶颈的 dispatch cycle stacks，而不是只看 commit 侧热点。"
authors:
  - "Silvio Campelo de Santana"
  - "Joseph Rogers"
  - "Lieven Eeckhout"
  - "Magnus Jahre"
affiliations:
  - "Norwegian University of Science and Technology, Trondheim, Norway"
  - "Ghent University, Ghent, Belgium"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790139"
tags:
  - hardware
  - observability
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文认为，指令级性能分析如果只看 commit 阶段，就只能看见指令如何从乱序窗口中“出去”，却看不见它们为何进不来。作者提出的 DIP 直接对 dispatch slot 采样，并把每个采样周期里的 slot 归因给当时真正暴露 dispatch latency 的 uop，于是得到时间成比例的 `PICS_D`。在 SPEC CPU2017 上，它把平均 profile error 从传统 dispatch tagging 的 `26.9%` 降到 `5.2%`，并帮助作者为 `fotonik3d` 找到一个 `8.5%` 的优化。

## 问题背景

论文的出发点并不抽象。即便加速器越来越强，CPU 单线程性能仍然关键，因为不能被加速器吃掉的那部分代码会在 Amdahl's Law 下变得更显眼。开发者因此需要指令级的性能剖析工具，既告诉他们哪些静态指令最热，也解释这些指令为什么热。现有工作里，像 TEA 这样的工具已经能在 commit 端给出准确的 per-instruction cycle stacks，也就是文中的 `PICS_C`。

但只看 commit 只会看到乱序窗口的 egress。若性能问题来自长延迟 load 堵住 ROB，这种视角很好用；可一旦问题来自 ingress，也就是 uop 进不了窗口，commit 侧就很容易把真正的责任方藏起来。分支误预测、前端供给中断、序列化指令、以及各种后端资源满导致的 dispatch stall，都可能让某条静态指令承担大量 dispatch latency，而 `PICS_C` 却只在别的代码位置上看到“结果”。

现有的 dispatch-tagging 方案，比如 AMD IBS、Arm SPE 和 IBM RIS，也补不上这个缺口。它们在 dispatch 时给单个 uop 打标签，之后再把经历过的事件取回来。问题在于，这种策略对 dispatch 来说并不是时间成比例的：一个采样周期里可能有多个 dispatch slot 同时在暴露延迟，而 misspeculated uop 上的样本又常常会被直接丢掉。于是它会产生系统性偏差，尤其容易低估控制流和 misspeculation 的影响。论文真正要补的是这个空白：既然优化需要同时看 `PICS_D` 和 `PICS_C`，那 dispatch 端也必须有一个时间成比例、而不是仅仅“在 dispatch 触发”的 profiler。

## 核心洞察

论文最核心的洞察是，dispatch latency 也可以像 execution time 一样做时间成比例归因，只是归因对象不该是“一个被打标签的 uop”，而应该是采样周期里每一个 dispatch slot。换句话说，采样发生时，profiling 硬件要判断每个 slot 当下究竟在暴露谁的 dispatch latency，然后把这一份时间记到那个 uop 对应的静态指令上。

之所以能这样做，是因为每个 dispatch slot 其实只会落在四种基本状态之一：`Base` 表示正确路径上不可避免的正常 dispatch；`Stall` 表示正确路径上的 uop 因后端资源不足而无法进入窗口；`Front-End` 表示 slot 为空，但原因是前端没有把 uop 送过来；`Misspeculation` 则表示 slot 被错误路径上的工作占用，或者 flush 之后的 refill 仍在为那次 misspeculation 付账。只要把 slot 先分进这四类，再记录导致它落入该类的具体原因，dispatch profiling 就既能做到时间成比例，也能解释入口带宽为什么损失。这其实就是论文最重要的概念推进：dispatch profiling 应该像 commit 侧的 cycle stacks 一样，解释 ingress，而不是只记录“某条被采样指令看到过什么事件”。

## 设计

论文先为 BOOM 核心定义了一份 `PICS_D` golden reference。它逐周期、逐 slot 地给所有 dispatch slot 做精确归因，包括“前几个 slot 成功 dispatch、后几个 slot 因资源满而 stall”的部分周期情况。这个参考实现显然无法直接落地到真实硬件里，但它给出了清晰的目标：DIP 要近似的不是某种经验规则，而是严格的时间成比例 dispatch 归因策略。

DIP 本身被设计成 PMU 里的一个轻量机制。它的核心数据结构是 Dispatch Information Table (`DIT`)，每个 dispatch slot 对应一项，记录 slot 的状态、导致该状态的 cause、被跟踪 uop 的 ROB index，以及静态指令地址。除此之外，还有一个 Last Misspeculation Record，用来记住最近一次 flush 是哪条指令触发的，这样当采样落在 refill 阶段时，空 slot 也仍然可以正确归因到那条分支、异常指令或序列化指令，而不是错误地算到 refill 后第一条正确路径指令头上。

有了这些状态，DIP 就能把 golden reference 的归因规则压缩进采样版实现里。若 slot 属于 `Stall`，时间就记到最老的那个尚未 dispatch 的 uop 上，并标记成 ROB 满、issue buffer 满、load/store queue 满、rename stall 或 serialization 等原因。若 slot 为空但属于 `Front-End`，它就归因给下一条将要 dispatch 的 uop，同时记录是 I-cache miss、I-TLB miss 还是一般性的 front-end bubble。若 slot 落在错误路径或 flush 后 refill 期间，则全部归因给引发 misspeculation 的那条指令。因为整个机制是按 slot 记账，而不是按单个 tagged uop 记账，所以它能自然处理 dispatch parallelism，这正是传统 dispatch tagging 做不到的地方。

硬件代价也被控制得很低。对文中的 4-wide BOOM 来说，作者报告额外存储不到 `49 bytes`，面积开销 `0.065 mm^2`，在 `4 kHz` 采样频率下运行时开销约 `1.08%`。样本数据通过只读 CSR 暴露给软件，再由离线工具生成可视化的 `PICS_D`。

## 实验评估

实验平台是 FireSim 上的 4-wide BOOM，工作负载是 22 个 SPEC CPU2017 benchmark，每个 benchmark 跑前 `150` billion cycles。作者比较了三种方案：传统 dispatch tagging (`DT`)、补上 misspeculation 归因的增强版 (`DT-M`)，以及 DIP，并用相对于 golden-reference `PICS_D` 的 profile error 衡量准确性。

结果非常扎实。DIP 的平均 profile error 只有 `5.2%`，而 `DT` 是 `26.9%`，`DT-M` 也还有 `16.8%`；即便最差的 `gcc`，DIP 也只是 `20.9%`，远低于 `DT` 的 `55.1%`。更重要的是定性结果。对 `gcc` 和 `deepsjeng` 来说，DIP 找出来的 hottest instructions 以及各类原因分解，和 golden reference 几乎一致；`DT` 会直接漏掉控制流主导的热点，`DT-M` 虽然补回了部分 misspeculation，但仍会把 flush 之后 refill 阶段的时间算错。采样频率实验也很合理：`4 kHz` 基本就是甜点区，再往上只会慢慢减少随机误差，而开销近似线性增加。

论文对“为什么必须同时看 `PICS_D` 和 `PICS_C`”的论证也很有说服力。作者把 DIP 的 `PICS_D` 和 TEA 的 `PICS_C` 配对分析后发现，`22` 个 SPEC benchmark 里有 `18` 个同时存在 ingress 和 egress 问题。也就是说，需要两种视角并不是特殊情况，而是常态。`fotonik3d` 的 case study 尤其能说明问题：`PICS_D` 揪出了一条 load 指令，它之所以在 dispatch 端极热，是因为 branch target 附近一个本可避免的 spill/reload 序列不断触发 memory ordering exception；而 `PICS_C` 主要看到的却是另一个代码区域里会 miss LLC 的浮点 load。作者改写了那段代码后，最严重的 ingress 问题被移除，整体性能提升 `8.5%`。这正是论文想证明的点：只看 commit 端，很容易错过真正可优化的地方。

## 创新性与影响

和 _Dean et al. (MICRO '97)_ 以及后来的商用 dispatch-tagging 设施相比，这篇论文的关键创新不在于“在 dispatch 采样”，而在于把 dispatch profiling 变成时间成比例的归因机制，因此结果可以被认真拿来做指令级分析。和 _Gottschall et al. (MICRO '21)_ 以及 _Gottschall et al. (ISCA '23)_ 相比，它则是把同样的哲学从 commit 侧扩展到 dispatch 侧，形成 ingress/egress 的成对视角。

因此，这篇论文对微架构 profiling 工具研究者和做极致 CPU 调优的工程师都很有价值。它贡献的不只是一个新 PMU 机制，也是一种更清楚的分析框架：commit 解释 egress，dispatch 解释 ingress，两者缺一不可。

## 局限性

DIP 的实现和验证都建立在 FireSim 里的 BOOM 核心之上，而不是商用硅片，所以具体的 cause 分类、状态细节和存储成本都带有架构特定性。论文虽然论证了它可以扩展到更宽的核、uop fusion、instruction replay 等情形，但这些更多还是工程上的可扩展性分析，而不是已经展示出来的产品级落地。

此外，DIP 也不是对 `PICS_C` 的替代。它负责揭示 ingress 问题，但论文自己已经说明，egress 问题依然需要 commit 侧 profiling。最后，DIP 终究是采样式 profiler，对冷指令和长尾分布的收敛仍然较慢；`gcc` 的结果就表明，即便没有系统性偏差，当热点分散在成千上万条静态指令上时，随机误差仍然不可忽视。

## 相关工作

- _Dean et al. (MICRO '97)_ - ProfileMe 提供了乱序处理器上的指令级 profiling 硬件支持，而 DIP 进一步专注于 dispatch latency 的时间成比例归因。
- _Gottschall et al. (MICRO '21)_ - TIP 在 commit 端实现了时间成比例的 instruction profiling，而 DIP 把这一原则推广到了 dispatch 端。
- _Gottschall et al. (ISCA '23)_ - TEA 提供准确的 `PICS_C`，而这篇论文论证 TEA 的 commit 视角必须和 `PICS_D` 配合，才能同时看见 ingress 与 egress。
- _Eyerman et al. (ISPASS '18)_ - Multi-Stage CPI Stacks 在应用层面区分不同流水级的代价，而 DIP 把入口瓶颈进一步定位到具体静态指令上。

## 我的笔记

<!-- 留空；由人工补充 -->

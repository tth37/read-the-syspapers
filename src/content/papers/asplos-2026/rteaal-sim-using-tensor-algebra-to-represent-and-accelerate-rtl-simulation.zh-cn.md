---
title: "RTeAAL Sim: Using Tensor Algebra to Represent and Accelerate RTL Simulation"
oneline: "RTeAAL Sim 把 full-cycle RTL simulation 重写成稀疏张量内核，用张量格式压缩与循环展开取代巨大的生成式二进制。"
authors:
  - "Yan Zhu"
  - "Boru Chen"
  - "Christopher W. Fletcher"
  - "Nandeeka Nayak"
affiliations:
  - "University of California, Berkeley, Berkeley, CA, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790214"
code_url: "https://github.com/TAC-UCB/RTeAAL-Sim"
tags:
  - hardware
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

RTeAAL Sim 的主张是：full-cycle RTL simulation 不该继续被编码成巨大的 straight-line C++，而应该被表达成一个稀疏张量代数内核。论文把电路数据流图编码成张量，再对张量格式和循环结构做优化，结果是在显著降低编译开销的同时，把仿真性能做到与 Verilator 同一量级。

## 问题背景

这篇论文瞄准的是一个很顽固的瓶颈：CPU 上的 RTL simulation 仍然是日常设计迭代的主力工具，但随着设计规模增长，它越来越难扩展。像 Verilator 这样的现代模拟器，会先把 RTL 降成数据流图，再生成接近 straight-line 的 C++ 交给 `clang` 做激进优化。这样确实容易跑得快，但也把模拟器性能和代码体积牢牢绑在一起。

这个绑定同时伤害编译和执行。设计越大，编译时间与峰值内存越高；运行时又会变成典型的 frontend-bound 程序，instruction cache 压力大，取指停顿多。ESSENT 通过更激进的展开缓解了一部分 frontend 问题，但论文表明这只是把分支开销换成更糟糕的编译成本。真正的问题因此变成：能不能用一种更紧凑、循环化的表示，让 RTL simulation 不再依赖把整个电路硬编码进 instruction stream？

## 核心洞察

论文的核心判断是：同步 RTL simulation 可以被表达成稀疏张量代数，而且不会丢掉真实电路所需的语义。只要把 next-state 数据流图编码成张量，一次 simulation cycle 就能表示成 extended Einsum 的级联。这个转换最重要的效果，是把模拟器动态行为和二进制体积解耦：电路主要留在数据中，而真正执行的是一个较小、较稳定的 kernel。

第二层洞察是，张量代数已经有一整套成熟的优化语言。RTeAAL Sim 借助 TeAAL 的 separation of concerns，把问题拆成 cascade、mapping、format 和 binding。于是，稀疏格式设计、rank swizzle、loop unrolling 这些原本属于 tensor compiler 的手段，就能被当成 RTL simulation 的一等优化来使用。

## 设计

表示方法从单层数据流图的三个张量开始：`LI` 保存输入值，`OIM` 记录哪些输入喂给哪些操作，`LO` 保存输出。为了从单个操作扩展到任意同步电路，`OIM` 继续引入层号 `I`、输出编号 `S`、操作类型 `N`、操作数顺序 `O` 和操作数来源 `R` 等 rank，于是一次 cycle 就能表示成若干 extended Einsum 的级联。

这些结构使它能覆盖非交换操作与 select 操作。可归约操作通过按 `N` 分派的自定义 reduce operator 处理；一元操作放到 map 阶段；mux 这类 select 操作则在 populate 阶段看完整个 operand fiber 再决定输出。为了支持任意图，编译器先做 levelization，再插入 identity operations 把跨层依赖变成逐层传递；随后又通过让源坐标和目标坐标对齐，把大量 identity copy 的成本消掉。

真正体现系统味道的，是对 `OIM` 的优化。它的密度只有 `10^-7` 到 `10^-9`，所以非常适合压缩：稠密 rank 保持 uncompressed，稀疏 rank 使用 compressed format，而可以由结构推断的 payload array 被直接删除。之后编译器继续探索从 rolled 到 unrolled 的一系列 kernel，并通过交换 `S` 与 `N` 的顺序，把同类操作聚在一起做部分展开，从而避免重新退化成巨大的 straight-line binary。整个 proof-of-concept flow 以 FIRRTL 为输入，做 operator fusion、copy propagation 等图优化，输出 JSON 形式的张量元数据和可参数化的 C++ kernel。

## 实验评估

作者在 Intel、AMD 和 AWS Graviton 平台上测试了 RocketChip、BOOM、Gemmini 和 SHA3，并把七种 RTeAAL Sim kernel 与 Verilator、ESSENT 做对比。最关键的编译结果出现在 1 到 24 核 RocketChip 上：部分展开的 `PSU` kernel 在整个范围内都只需要 `4.26` 秒编译时间和约 `0.203 GB` 峰值内存；Verilator 则从 `92` 秒涨到 `724` 秒，ESSENT 从 `121` 秒涨到 `13,700` 秒。这个结果很直接地说明，只要把设计主要留在数据中，编译成本就能几乎与设计规模脱钩。

运行时则不是单方向胜利。完全展开的 kernel 虽然减少了 dynamic instructions，但二进制膨胀后会越来越 frontend-bound。在 Xeon 上，最优点是中间状态的 `PSU`，既保留了大部分指令数下降收益，又没有把 instruction cache 压垮。随着 RocketChip 从 1 核扩展到 24 核，`PSU` 仍接近线性扩展，而 fully inlined 的 `TI` 因为 fetch stall 越来越重，从 4 核开始就被反超。

与现有模拟器相比，这个 prototype 基本落在论文宣称的位置上。用 `clang -O3` 时，ESSENT 在大规模 Xeon RocketChip 上仍是最快，但代价是夸张的编译成本；RTeAAL Sim 则整体上与 Verilator 竞争，并在较大、cache 更紧张的设计上经常更快。最能支撑中心论点的是 8-core SmallBOOM 的 LLC 限制实验：当 Xeon 的 LLC 从 `10.5 MB` 缩到 `3.5 MB` 时，RTeAAL Sim `PSU` 相对 Verilator 的加速比从 `1.32x` 升到 `1.55x`，而 ESSENT 明显退化。不过边界也很清楚：对较小的 SHA3 设计，Verilator 仍然更强，所以这套方法最适合的还是那些真正受 cache 与 frontend 限制的 RTL simulation 场景。

## 创新性与影响

相对于 _Beamer and Donofrio (DAC '20)_，RTeAAL Sim 的新意不在于新的代码生成小技巧，而是在表示层面换道：保持 kernel 紧凑，把电路结构搬进稀疏张量数据中。相对于 _Wang and Beamer (ASPLOS '23)_ 与 _Wang et al. (ASPLOS '24)_ 这类仍在传统 RTL simulation 流程内优化划分和复用的工作，这篇论文提出了一个更通用的 substrate，前述技巧都可以在其上被重新表述。相对于 _Nayak et al. (MICRO '23)_，它则展示了 TeAAL 风格抽象在一个看上去并不像 tensor workload 的领域里也能成立。

因此，这篇论文同时会吸引 RTL simulator 设计者和 sparse tensor compiler / accelerator 研究者。前者会把它看成一种新的编译时间与运行时间权衡点，后者则会把它视作一个新的潜在负载族。

## 局限性

论文明确承认这只是一个 proof-of-concept，而不是工业级 simulator 的直接替代品。它聚焦于 CPU 上的 full-cycle simulation，核心表述默认单时钟域，也只实现了文中讨论的一部分优化空间。multi-clock 支持、event-driven 技术、GPU 映射和 accelerator co-design 基本都还是未来工作。

性能上的边界也很清楚。这个 prototype 对 Verilator 已经有竞争力，但并不能稳定压过 ESSENT；对 SHA3 这种较小设计，它甚至会输给传统 straight-line 方案。与此同时，最佳 kernel 会随机器和设计规模变化，这意味着若想真正落地，后续大概需要 autotuning 或 cost model。形式化层面上，`O` rank 的遍历顺序约束也还缺少更完整的理论处理。

## 相关工作

- _Beamer and Donofrio (DAC '20)_ — ESSENT 通过激进 straight-line code 降低分支与 frontend 浪费，而 RTeAAL Sim 选择保留 rolled kernel，并把电路结构放进稀疏张量数据。
- _Wang and Beamer (ASPLOS '23)_ — RepCut 通过 replication-aided partitioning 加速并行 RTL simulation；RTeAAL Sim 则把这类方法视作可以叠加在张量 substrate 之上的 mapping 或 cascade 优化。
- _Wang et al. (ASPLOS '24)_ — Dedup 利用重复电路结构优化传统仿真流程，而 RTeAAL Sim 认为这类复用也可以在 tensor-level representation 中被更系统地表达。
- _Nayak et al. (MICRO '23)_ — TeAAL 提供了 separation-of-concerns 框架，而 RTeAAL Sim 正是借助这个框架来组织 format、mapping 与 binding 层面的仿真优化。

## 我的笔记

<!-- 留空；由人工补充 -->

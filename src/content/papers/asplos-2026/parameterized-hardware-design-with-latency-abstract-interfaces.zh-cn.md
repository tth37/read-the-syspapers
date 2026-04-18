---
title: "Parameterized Hardware Design with Latency-Abstract Interfaces"
oneline: "论文提出 latency-abstract interface 与 Lilac，让生成式硬件把时序作为编译期参数向上传递，从而保留 LS 效率并去掉 LI 握手开销。"
authors:
  - "Rachit Nigam"
  - "Ethan Gabizon"
  - "Edmund Lam"
  - "Carolyn Zech"
  - "Jonathan Balkind"
  - "Adrian Sampson"
affiliations:
  - "MIT CSAIL, Cambridge, USA"
  - "Cornell University, Ithaca, USA"
  - "UC Santa Barbara, Santa Barbara, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790199"
tags:
  - hardware
  - pl-systems
  - verification
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文指出，很多生成式硬件模块只是“写代码时不知道具体延迟、生成后延迟就固定”，却仍被工程师包进 latency-insensitive 接口里，白白付出握手开销。作者提出 latency-abstract interface 与 Lilac：把时序作为编译期 output parameter 暴露出来，并用类型系统证明任意参数化实例都不会出现结构性 hazard。

## 问题背景

论文把两个常被混为一谈的场景拆开了。若模块时延真的依赖运行时输入，例如 memory hierarchy 或 variable-latency divider，就必须使用 latency-insensitive (LI) 接口，用 ready/valid 一类同步信号来协商时序。但很多 generator 产出的模块其实仍是 latency-sensitive (LS) pipeline：FloPoCo、Vivado IP generator、加速器 DSL 会根据 bitwidth、目标频率、微架构选项改变 latency 和 initiation interval，可一旦 generator 跑完，这些值就固定了。

问题在于现有 HDL 很难把这种“编译后确定”的时序变化传回父模块。于是设计者不是手工维护脆弱的 pipeline balancing 逻辑，就是干脆给模块套一层 LI wrapper。后者虽然省心，却会引入纯粹的协调成本。论文里的 FloPoCo FPU 例子显示，LI 版本为了对齐 adder 和 multiplier，要额外加入 ready/valid 逻辑、控制 FSM 和 FIFO；综合后，相比 LS 实现，LI 多用 29-31% 的 LUT、3-4 倍寄存器，并让最高频率下降 21-25%。

## 核心洞察

作者的核心洞察是：大量 generator 模块处在 LS 与 LI 之间的中间地带。它们的 timing 在写父模块时还是抽象的，但到 elaboration 完成后已经完全具体。因此，正确抽象不是把未知拖到运行时靠握手解决，而是把 timing 在设计期保留为符号量，等 generator 跑完后再编译成高效的 LS 电路。这正是 latency-abstract (LA) interface 的含义。

关键机制是 output parameter。传统 HDL 参数只会自顶向下流动，但真正知道 latency 的其实是 child generator。Lilac 允许子模块把 `#L`、`#II` 之类的时序信息向上传回父模块，后者再据此安排调度、插入 delay，并推导自己的接口时序。这样验证的对象就不是某一个固定实例，而是一整族参数化设计。

## 设计

Lilac 在 Filament 风格的 timeline types 上加入了 parameterization 与 output parameter。以生成的 adder 为例，接口除了常规输入参数 `#W` 外，还导出 output parameter `#L` 表示 latency。父模块不能预先假定 `#L` 的具体值，只能按接口约束来使用它。论文中的 FPU 例子里，直接在同一时刻读取 adder 和 multiplier 输出的设计会被 Lilac 拒绝，因为两路结果不一定同拍有效。修正后的实现读取 `Add::#L` 与 `Mul::#L`，计算最大值，再用参数化 `Shift` 去平衡两条 datapath 和 opcode 路径。

为了让这种写法真正可用，Lilac 还提供了 bundles、compile-time loop 与参数计算。bundle 可以表达“第 `i` 个值在 `G+i` 时刻有效”，非常适合 shift register 这类结构。类型系统随后用 SMT 检查三件事：只在值有效时读取、同一周期不出现多重驱动、对子模块的再次调用满足 initiation interval。output parameter 会被编码成关于输入参数的 uninterpreted function，求解器通过寻找反例来证明不存在 latency safety 和 resource safety 违规。

类型检查通过后，编译器采用自底向上的 elaboration：在输入参数具体化后运行 generator、回收 output parameter 绑定、展开 compile-time 循环和条件，并最终 lowering 到 Filament 与 Verilog。这个顺序很关键，因为父模块经常依赖 child generator 结束后才知道的 latency。

## 实验评估

评估主要回答两个问题：Lilac 能否覆盖真实 generator 的接口形态，以及 LA interface 是否真的去掉了有意义的 LI 开销。先看编译器。Figure 8 显示，类型检查是主要成本，但规模仍然很小：从 480 行的三段 RISC 到 1346 行的 BLAS kernels，类型检查时间在 160-1295 ms 之间，大多数设计不到 1 秒。作者还展示了 Lilac 已经覆盖的接口特征，包括输入参数决定时延、output parameter 决定时延、参数相关的 initiation interval，以及多周期输入保持时间。

第一个硬件 case study 是 FloPoCo FPU。论文比较同一组 adder/multiplier 的 LS 集成与 LI 集成：当 `(A, M) = (1, 1)` 时，LI 使用 614 LUT 和 824 个寄存器，LS 只需 441 LUT 和 205 个寄存器，频率从 163.0 MHz 降到 134.5 MHz；当 `(A, M) = (4, 2)` 时，LI 为 662 LUT、1426 个寄存器，LS 为 459 LUT、482 个寄存器，频率从 280.8 MHz 降到 224.4 MHz。这里几乎把“握手式模块化有多贵”单独量了出来。

第二个 case study 是用 Aetherling 生成卷积模块实现的 Gaussian Blur Pyramid。LI baseline 围绕相同生成模块写了 ready/valid 状态机；Lilac 版本则用 LA interface、serializer 和参数化 pipeline balancing。跨 5 个设计点平均来看，LI 多消耗 26.2% 的 LUT、33.0% 的寄存器，并带来 6.8% 更差的频率。随着 Aetherling 暴露更多并行度，Lilac 所需的 serializer 逻辑下降，而 LI 的 FSM 握手成本基本保持常数。这支持作者的中心论点：LA 特别适合构建更大的 LS“岛”，LI 只保留在真正动态时序的边界上。

## 创新性与影响

相对 _Nigam et al. (PLDI '23)_，Lilac 的新意不只是延续 timeline types，而是把“时序受参数影响”正式纳入语言机制，并允许这些时序信息从 child generator 回流到 parent。相对 Bluespec 这类传统参数化 HDL，它强调的不是一般意义上的 compile-time arithmetic，而是参数与 temporal behavior 的关系能够被组合式地描述和验证。相对 FloPoCo、Aetherling 这类 generator，它补上的不是生成算法，而是一个严肃的集成层，让设计者不必一碰到时序变化就退回到 LI wrapper。

这篇论文最可能影响 safe HDL、hardware generators 与 accelerator integration 这些方向。它的更大价值在于指出：很多 ready/valid-heavy 设计未必是硬件本质需求，而可能是现有抽象能力不足的结果。

## 局限性

作者并没有声称 LA interface 能替代 LI interface。若模块 timing 真的是运行时输入相关，例如 memory hierarchy 或 variable-latency divider，那仍然必须使用 LI 同步。Lilac 解决的只是“设计时抽象、编译后具体”的那类时序不确定性。

即便在这个范围内，方法也有边界。SMT 推理对更复杂的等式有时仍需要用户手动提供 `assume`；elaborator 也要求实例化图里有足够具体的部分来打破循环。评估则主要围绕 FPGA generator 与结构开销，没有覆盖用户生产力或 ASIC flow。与此同时，Gaussian Blur Pyramid 也说明 LA 并非“零控制开销”：它仍可能需要 serializer 或 balancing 逻辑，收益来自去掉不必要的运行时握手，而不是让控制逻辑完全消失。

## 相关工作

- _Nigam et al. (PLDI '23)_ — Filament 为固定延迟设计提供了 timeline types，而 Lilac 把这个基础扩展到参数化时序和 generator 产出的 output latency。
- _Yu et al. (arXiv '25)_ — Anvil 把 timing-safe HDL 推向动态、事件参数化的 timing contract；Lilac 则聚焦于设计时抽象、elaboration 后具体的时序。
- _De Dinechin and Pasca (IEEE Design & Test '11)_ — FloPoCo 代表了 Lilac 旨在高效接入而非替代的 generator 生态。

## 我的笔记

<!-- 留空；由人工补充 -->

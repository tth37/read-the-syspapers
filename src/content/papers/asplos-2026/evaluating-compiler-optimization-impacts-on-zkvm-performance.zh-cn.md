---
title: "Evaluating Compiler Optimization Impacts on zkVM Performance"
oneline: "系统测量 64 个 LLVM pass 在 RISC-V zkVM 上的作用，指出动态指令数与分页才是关键成本，并证明少量 zkVM 感知改动就能超过原生 -O3。"
authors:
  - "Thomas Gassmann"
  - "Stefanos Chaliasos"
  - "Thodoris Sotiropoulos"
  - "Zhendong Su"
affiliations:
  - "ETH Zürich, Zürich, Switzerland"
  - "Centre for Blockchain Technologies, University College London, London, United Kingdom"
  - "zkSecurity, New York, United States"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790159"
tags:
  - compilers
  - pl-systems
  - security
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文不是在提出新的 zkVM，而是在回答一个更基础、也更容易被忽略的问题：把 LLVM 直接搬到 zkVM 上到底会发生什么。作者系统测量了 64 个 LLVM pass、标准 `-O` 等级和 autotuning 组合在两个生产级 RISC-V zkVM 上的效果，结论是：标准优化确实有用，但真正支配性能的是证明语义下的动态指令数与分页开销，而不是 CPU 上熟悉的缓存、分支预测和指令级并行。

## 问题背景

zkVM 的吸引力在于它把零知识证明包装成普通编译流水线的后端。开发者可以继续写 Rust 或 C，把程序编译成 RISC-V，再由 zkVM 执行并产生日志与证明。这种抽象显著降低了上手门槛，但也把传统编译器的默认假设一并带了进来。LLVM 的很多优化是围绕 cache locality、branch prediction、out-of-order execution 和 instruction-level parallelism 设计的，可 zkVM 在证明执行时并不具备这些硬件特性。

这件事之所以重要，是因为 zkVM 的核心瓶颈就是性能。论文反复强调，zkVM 执行和 proving 比原生执行慢几个数量级，所以哪怕只有几个百分点的改进，也可能换来数秒甚至数分钟的节省。如果编译器还在为不存在的微架构收益做决策，就会把本可节约的证明成本白白浪费掉。因此，真正的问题不是“LLVM 有没有帮助”，而是“哪些传统优化还能成立，哪些优化在 zkVM 上已经变成反效果”。

## 核心洞察

论文最重要的洞察是：对 zkVM 而言，最能解释性能变化的不是静态代码形态，而是运行时到底执行了多少条指令，以及为了重放这些指令产生了多少 paging 开销。作者用动态指令数和 paging cycles 去重新理解 pass 的效果后，很多现象立刻变得清楚。凡是能稳定减少动态指令数的 pass，通常会带来执行和 proving 的双重收益；凡是引入额外地址计算、栈 spill、load/store 或 page-in/page-out 的 pass，就算在 CPU 上常见地“优化了程序”，在 zkVM 上也可能明显变慢。

这也解释了为什么标准 `-O3` 依然能获得超过 40% 的提升，却仍然明显弱于 x86 上的收益。LLVM 并不是完全不适合 zkVM，而是它的 cost model 用错了目标。只要把已有 pass 的启发式从“追逐 CPU 微架构收益”改成“减少证明相关成本”，现有工具链就已经能走得更远，而不必从头发明一套全新的编译器。

## 设计

这篇论文本质上是一项系统化测量研究。作者选择了两个最成熟、也最常见的 RISC-V zkVM：RISC Zero 和 SP1。基准程序一共 58 个，来源覆盖 PolyBench、NPB、SPEC CPU 2017，以及多套面向 zkVM 的加密工作负载，另外还加入了 `sha256`、`regex-match`、`loop-sum` 这类专门用于放大循环、内存和数学模式的小程序。整体上，他们比较了 71 种优化配置：一个无优化基线、六个标准优化等级，以及 64 个单独开启的 LLVM pass。为了让“单 pass 效果”更干净，作者还把 Rust MIR 优化关掉。

评估指标有三类：cycle count、zkVM execution time 和 proving time。为了对照传统机器，他们还在 x86 上跑同一套优化配置，并测量原生执行时间。对于 pass 组合空间，作者使用 OpenTuner 做 genetic autotuning，把 cycle count 当作代理目标，因为它比反复测执行时间和 proving 时间便宜得多，而且与最终性能高度相关。

真正让这篇论文从“跑了很多 benchmark”变成“能指导后续优化”的，是后半部分的成本分析。作者进一步观察动态指令数和 paging cycles，并围绕几个典型 pass 做 case study，最后提炼出四条原则：会制造分页压力的变换要谨慎；inline 只有在真正减少动态工作量且不触发栈 spill 时才值得做；loop unrolling 只有在总执行指令数下降时才有意义；branch elimination 不能照搬 CPU 直觉，因为 zkVM 没有分支预测惩罚，反而会为额外算术和双路径证明买单。基于这些原则，作者还做了一个很轻量的 LLVM 原型修改：加入 zkVM-aware 的 RISC-V cost model，调高 inline 阈值，修改 `simplifycfg` 的默认启发式，并关闭若干依赖传统 CPU 特性的 pass。

## 实验评估

单个 pass 的结果里，最关键的一组对照是 `inline` 和 `licm`。`inline` 是整体上最有利的 pass，在两个 zkVM 上都把 proving time 平均降低了 `22.4%`，cycle count 下降约 `30%`。相反，`licm` 是最有害的 pass：它让 RISC Zero 的执行时间增加 `11.8%`、SP1 增加 `7.1%`，让 proving time 分别恶化 `13.5%` 和 `8.4%`。论文给出的解释很有说服力：LLVM 在 `LCSSA` 形式下做 loop 相关变换时，可能引入额外的 `getelementptr`、load/store 和 spill，结果动态指令数与 paging 开销一起上涨。

如果把粒度放到标准优化等级，结论会更正面一些。除了 `-O0` 之外，默认 `-O` 等级相对基线都能稳定提升性能，其中 `-O3` 最好：RISC Zero 的执行时间平均提升 `60.5%`，SP1 提升 `47.3%`；proving time 分别提升 `55.5%` 与 `51.1%`。这说明“直接用成熟编译器”已经是值得的默认选项。但论文同时指出，这些提升相比 x86 仍然偏小，说明 LLVM 的许多决策并没有真正命中 zkVM 的成本瓶颈。

autotuning 进一步证明，`-O3` 还远远不是终点。只跑 160 轮 OpenTuner，RISC Zero 就有 18 个程序、SP1 有 20 个程序能超过 `-O3`。在 NPB 套件上，延长搜索后，执行时间和 proving time 的平均改进大约还能做到 `17%-19%`；其中 `npb-sp` 在两个 zkVM 上都超过 `2x`。即便是用了 precompile 的 crypto workload，也仍然能看到超过 `10%` 的改进。更值得注意的是，autotuning 还意外触发了一个 SP1 的严重安全漏洞：某些 pass 序列会让程序在中途静默退出，但系统仍然产出一个能通过验证的 proof。

作者最后做的 LLVM 原型修改虽然很小，却很能说明问题。不到 100 行代码，就让修改后的 `-O3` 在 RISC Zero 上的 39/58 个 benchmark 中超过原版 `-O3`，平均执行时间再提升 `4.6%`；在 SP1 上则有 19/58 个 benchmark 超过原版，平均提升 `1%`。最好的一例是 `fibonacci`，RISC Zero 上可快到 `45%`。从论证链条上看，这组结果很扎实：相关性分析、case study 和原型实现都指向同一个事实，即动态指令数是最主要的解释变量，而 paging 是最重要的第二因素。

## 创新性与影响

这篇论文的创新不在于重新设计 proof system，也不在于提出一台全新的 zkVM，而在于把注意力放到一个此前几乎没人系统回答过的层次：既然生产级 zkVM 正在沿用 LLVM，那 LLVM 的每一个经典优化在“可证明执行”这个语境里到底还成不成立。这个切口比“新架构”“新协议”更朴素，但对实际部署非常重要，因为它直接决定了现有 zkVM 生态能否继续吃到成熟编译器基础设施的红利。

它的影响面也因此相当广。对 zkVM 厂商来说，论文给出了一张非常具体的改进清单，说明哪些 pass 值得保留、重写或降权。对写 proving-heavy 应用的工程师来说，它证明了 autotuning 不是学术玩具，而是现实可用的性能旋钮。对编译器和系统研究者来说，这篇论文则提供了后续方向：更好的 zkVM-specific backend、profile-guided optimization，以及面向 proof cost 的 superoptimization。

## 局限性

论文只研究了两个基于 RISC-V 的 zkVM，并且传统架构对照只做到 x86。这足以说明“CPU 启发式和 zkVM 成本模型并不一致”，但还不足以外推到所有 zkVM，尤其是像 Cairo 这样自带专用 ISA 和工具链的系统。作者考察的 64 个 pass 大多也是在“单独启用”的条件下测量，这种方法有利于隔离因果，但无法覆盖完整的 phase-ordering 组合空间。

实验本身也有现实限制。部分 benchmark 缩小了输入规模，否则 proving 成本过高；SP1 的 proving time 噪声更大，因为它依赖通过 RPC 访问的闭源 prover；而“动态指令数 + paging”的成本模型虽然已经解释了大部分性能变化，却还没把 proof sharding、precompile 使用方式等 zkVM 特有因素完整纳入。最后，作者给出的 LLVM 修改刻意保持轻量，因此更像“概念验证”和“修正方向”，而不是已经打磨完成的生产级 backend。

## 相关工作

- _Ben-Sasson et al. (USENIX Security '14)_ — 这类工作奠定了“为 von Neumann 机器执行生成 succinct proof”的基础，而本文研究的是在这一抽象已经可用之后，主流编译器该如何适配 zkVM。
- _Ansel et al. (PACT '14)_ — OpenTuner 提供了本文使用的 autotuning 框架，但本文的新意在于把它带到 zkVM 编译优化空间里，并证明它能直接降低 proving 成本。
- _Ernstberger et al. (SCN '24)_ — zk-Bench 关注的是 ZK DSL 与 proving 系统的比较评测，而本文把问题收缩到两个生产级 zkVM 内部，专门分析编译器 pass 对执行与 proving 的影响。

## 我的笔记

<!-- empty; left for the human reader -->

---
title: "Arancini: A Hybrid Binary Translator for Weak Memory Model Architectures"
oneline: "Arancini 用统一 IR、经证明的内存映射和混合静态/动态翻译，让 x86-64 二进制能在 Arm 与 RISC-V 弱内存主机上正确运行。"
authors:
  - "Sebastian Reimers"
  - "Dennis Sprokholt"
  - "Martin Fink"
  - "Theofilos Augoustis"
  - "Simon Kammermeier"
  - "Rodrigo C. O. Rocha"
  - "Tom Spink"
  - "Redha Gouicem"
  - "Soham Chakraborty"
  - "Pramod Bhatotia"
affiliations:
  - "TU Munich, Munich, Germany"
  - "Huawei Research, Edinburgh, UK"
  - "University of St Andrews, St Andrews, UK"
  - "RWTH Aachen University, Aachen, Germany"
  - "TU Delft, Delft, Netherlands"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790127"
tags:
  - compilers
  - verification
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Arancini 是一个面向 Arm 和 RISC-V 的 x86-64 混合二进制翻译器：静态路径和动态路径先汇合到同一个 IR，再通过机助证明的内存模型映射，把 x86 的顺序约束正确带到更弱的主机架构上。它的结果不只是比纯静态翻译器覆盖更多程序，而是在接近 DBT 覆盖面的同时，相比基于 QEMU 的 Risotto 最高可快 `5x`。更重要的是，论文把这种正确性声明推进到了 Arm 上的 mixed-size access。

## 问题背景

论文从二进制翻译领域里一个典型的两难出发。静态二进制翻译器可以提前做 LLVM 风格的跨函数优化，也不用完整模拟 guest CPU 状态，因此通常更快；但它在原理上并不完备，因为二进制反汇编一般不可判定，控制流结构和跳转目标在编译后已经丢失，间接跳转、jump table 和函数指针都会让 lifting 失败。动态二进制翻译器则更接近完备，因为它只翻译真正执行到的代码片段，但要承担运行时编译成本，而且只能优化局部代码，所以常常比 native 慢 `5-10x`。

跨 ISA 并发让问题更难。Arancini 从 x86-64 翻到 Armv8 和 RISC-V，而前者内存模型更强、后两者更弱。如果翻译器忽略这种 mismatch，就可能在 host 上放出 guest 架构本来不允许的执行。论文拿 QEMU 作为明确反例：先前工作已经证明它会错误处理并发程序，所以只能禁用相关并发执行。mixed-size access 又增加了一层复杂性，因为看似自然的变换，例如把宽访问拆成几个窄访问，也可能改变程序允许的结果。真正的问题因此是：怎样在保住弱内存正确性的前提下，获得接近 DBT 的覆盖面，同时尽量拿回静态翻译的性能。

## 核心洞察

论文最值得记住的命题是：混合翻译要想既实用又正确，静态翻译和动态翻译必须共享同一个低层语义核心。Arancini 的回答是 ArancinIR。它足够低层，贴近机器执行，便于动态路径快速 lower；同时又保留了足够多的结构，让静态路径还能做有效优化。一旦两条路径都经过同一个 IR，系统就只需要维护一套内存语义，而不是为 LLVM 路径和 JIT 路径分别写两套容易漂移的正确性故事。

但这只有在 IR 自己的内存操作定义足够精确时才成立。于是作者给 ArancinIR 定义了一个独立的公理化内存模型 AIMM，再证明从 x86-64 到 AIMM、以及从 AIMM 到 Armv8 和 RISC-V 的映射。这样，翻译器插入的 fence 和 atomic 形式就不是经验主义调参，而是由证明支撑的必要约束。关键变化在于：正确性被前推到了翻译基底本身。只要这一点站住，hybrid binary format 和运行时查表机制就能在不重新引入语义裂缝的前提下，把静态阶段漏掉的代码动态补回来。

## 设计

ArancinIR 的核心结构是 packet 和 chunk。packet 表示单条 guest 指令对应的 DAG，chunk 则是 packet 的线性序列，在静态路径里可以代表整个函数，在动态路径里则代表一个 basic block。packet 内部又分为两类节点：value node 负责计算中间值，action node 负责提交寄存器或内存写入等可观察状态变化。这个划分既保留了 guest 状态必须一致的边界，也给 dead-flag elimination 之类的局部优化留下空间。

证明部分和 IR 结构同样关键。AIMM 定义了 load、store、RMW 以及一组 fence，再通过全局顺序公理把局部顺序与跨线程通信关系组合起来。在此基础上，论文给出从 x86 memory primitive 到 AIMM、再从 AIMM 到 Arm 与 RISC-V 的 verified mapping，并声称这些映射是 minimal 的。一个很重要的负结果是：把大访问拆成小访问并不正确，因为它会制造出源程序原本不允许的 mixed-size outcome。这解释了为什么 Arancini 不能随意 lower 宽访问，也解释了它在 Arm mixed-size access 上的结果为什么有分量。

系统层则把这些语义保证接到真正的混合翻译器上。静态路径先从 ELF 里发现 symbol，把可达代码 lift 到 ArancinIR，再提升到 LLVM IR，运行 LLVM `O2` 和 fence-merging pass，最终生成一个 hybrid ELF，其中同时保存 host 代码、原始 guest 代码和 guest 地址到 host 函数的映射元数据。运行时库负责初始化 guest stack 与 thread-local state，拦截 `clone` 这类系统调用，并在控制流跳到尚无静态翻译的 guest PC 时触发按需动态翻译。动态路径复用同一个 frontend 和 IR，但一次只 lower 一个 basic block，通过轻量 backend 放进 code cache，再通过 block chaining 降低后续查找开销。

## 实验评估

实验使用 Phoenix 多线程基准的 `pthread` 与 map-reduce 两个版本。x86-64 guest 程序由 Clang 18 和 musl 构建，再分别翻译到 ThunderX2-99xx Arm 主机与 SOPHON SG2042 RISC-V 主机。完备性结果很直接：Arancini 成功翻译了全部七个 benchmark 的两个版本；相比之下，Lasagne 无法处理所有 map-reduce benchmark，也会在若干 `pthread` 场景下因为静态 lifting 无法解析动态控制流而失败。这说明 hybrid 设计带来的不是摆设式 fallback，而是真正接近 DBT 的覆盖能力。

性能方面，论文给出的结论是“有意义地优于纯动态方案”，而不是“逼近 native”。相对 native，Arancini 的几何平均 slowdown 在 Arm 上是 `8.01x`，在 RISC-V 上是 `4.52x`；如果链接到 native library，则分别改善到 `6.01x` 和 `3.81x`。这些数字本身仍然不低，但更 relevant 的对照是其他翻译器：Arancini 通常与 Risotto 持平或更快，论文概括为相对基于 QEMU 的动态翻译最高可快 `5x`。性能剖析也支持论文的叙事。动态阶段唯一地址的最高占比只有 `2.1%`，perf 采样显示大多数时间都耗在静态翻译代码里，运行时主要是在补全控制流，而不是大规模临场 JIT。Arm 上的线程扩展曲线也与 native 接近，说明为保证正确性而插入的 fence 没有明显压垮可扩展性。

正确性评估上，论文首先依赖证明，其次用实验做支撑。作者翻译了 Linux kernel 和 libvsync 风格的多种锁实现，报告相对 native 的 slowdown 介于 `3.11x` 到 `3.56x` 之间，并特别指出带有 mixed-size access 的 `lockref` 在 Arm 路径上也受到其 proof-guided mapping 的覆盖。这不是对所有软件的穷尽验证，但和论文真正主张的形式化结论是对得上的。

## 创新性与影响

和 _Rocha et al. (PLDI '22)_ 相比，Arancini 的推进不在于把静态翻译单独做得更强，而在于把静态与动态翻译真正结合起来，同时保住经证明的 strong-on-weak 映射故事。和 _Gouicem et al. (ASPLOS '23)_ 相比，它用 hybrid 架构换取了“绝大多数周期花在 AOT 代码里”的执行形态，并把证明链扩展到 RISC-V 以及 Arm 上的 mixed-size access。和很多主要围绕工程性能调优的 hybrid 系统相比，它最有辨识度的地方在于把 IR、runtime format 和 proof obligation 当成一个联合设计对象。

这会同时影响 binary translation 实践者和 verification 研究者。前者得到了一条逃离“静态不完备、动态太慢”二选一困境的具体路线，而且不是靠模糊处理内存正确性来换性能；后者则看到了一个少见的例子：机助证明不是玩具编译器的附属品，而是真正约束了系统实现的主干。论文最耐久的贡献，就是把“混合翻译需要共享语义基底”这件事讲清楚了。

## 局限性

实现还没有完全兑现它在架构层面描绘出的完备性前景。论文明确说，Arancini 目前并没有实现 Risotto 和 QEMU 的全部特性，因此“像任意 DBT 一样完备”更多是设计方向，而不是已经完成的工程状态。系统在工程上也有现实限制：当前只支持链接到 musl 的二进制，还没有实现 C++ `new`/`delete` 所需的 relocation 处理；自修改代码也仍然是一个棘手的 runtime invalidation 问题。

内存模型结果本身也有边界。mixed-size correctness 的证明只覆盖 x86 到 Arm 的路径，RISC-V 侧因为所采用的形式模型本身不包含 mixed-size access，所以论文没有给出同等级别的保证。non-temporal access 不在讨论范围内。Advanced Vector Extensions 也尚未支持，因为直接把 512-bit 访问拆开翻译会落入已经证明不正确的 access splitting 问题。最后，实验工作负载仍然比较窄，Phoenix 虽然合适，但终究只是少量 C 程序，因此它更强地证明了机制成立，而不是广泛部署已经成熟。

## 相关工作

- _Rocha et al. (PLDI '22)_ — Lasagne 证明了 proof-guided 的静态 strong-on-weak 翻译可以成立，而 Arancini 在此基础上增加了动态补译路径以及 hybrid binary/runtime 设计，用来覆盖 Lasagne 无法 lift 的代码。
- _Gouicem et al. (ASPLOS '23)_ — Risotto 提供了纯 DBT 版本的完备性故事；Arancini 保留其对 strong-on-weak 正确性的关注，但把大部分工作量重新压回静态翻译，以换取更低开销。
- _Deshpande et al. (EuroSys '24)_ — Polynima 也是 hybrid 路线，但重点是面向多线程二进制补丁的实用重编译，而不是在弱内存模型下做 proof-guided 的跨 ISA 翻译。
- _Gao et al. (USENIX ATC '24)_ — CrossMapping 同样研究 cross-ISA translation 中的内存一致性保持，而 Arancini 把这一点嵌入进一个带有 mechanized mapping 和 runtime integration 的完整 hybrid translator。

## 我的笔记

<!-- empty; left for the human reader -->

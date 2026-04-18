---
title: "Optimizer-Friendly Instrumentation for Event Quantification with PRUE Algorithm"
oneline: "Zircon 用局部 delta-counter 加上优化后的 PRUE 重写，在保持精确事件计数的同时，把 instrumentation 变成更容易被编译器优化的代码。"
authors:
  - "Hao Ling"
  - "Yiyuan Guo"
  - "Charles Zhang"
affiliations:
  - "The Hong Kong University of Science and Technology, Hong Kong, China"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790196"
code_url: "https://github.com/zirconinstrumentation/ZirconInstrumentation"
tags:
  - compilers
  - fuzzing
  - observability
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Zircon 的核心主张是：精确事件计数不该继续被实现成“每次事件发生就立刻去加全局计数器”。它先把计数写进函数内的局部 delta-counter，让编译器能像处理普通局部变量那样分析和化简；等主优化流程结束后，再用 PRUE 把延后的全局更新移动、拆分或删除。这样既保留了精确计数，又把循环、分支和标量表达式重新暴露给 LLVM 现有优化器，因此在 SanCov、Nisse 等基线之上拿到了明显更低的开销。

## 问题背景

这篇论文关注的是精确事件量化：比如 coverage counting、函数调用计数、内存操作计数等。很多下游系统都依赖这类数据，包括调试、PGO、运行时调优和 fuzzing。问题并不在“要不要计数”，而在“怎么计数”。为了让外部工具可见，传统方案通常在事件点直接更新全局计数器；但这一步会引入副作用、制造 may-alias 关系，并在函数之间形成隐式数据依赖。结果就是，原本能做循环化简、指令重排、值域推断和 LICM 的优化器都不得不更保守。

看起来有两条常见路线，但两条都不理想。早期插桩保留了较完整的高级结构，可惜副作用太早进入 IR，导致优化失败；论文引用的前人工作和自己的实验都显示，early instrumentation 会显著拖慢程序，最坏可达到晚期插桩的数倍。晚期插桩则避开了“污染优化器”的问题，但这时程序已经被 lowering、拆分甚至重写过，插桩质量反而下降。像 Nisse 这样的方案依赖循环结构与 SESE 区域，而这些信息在 `-O2`/`-O3` 之后往往已经被 loop fission 等变换破坏。

局部计数器似乎是自然的修复手段，因为编译器更擅长优化局部变量，而不是全局内存。但局部值对函数外部不可见，所以最终还是得在某些位置把局部计数同步回全局计数器。如果同步得太早，原来的 barrier 又回来了；如果统一拖到函数退出点，又会让很多执行路径白白执行 `counter += 0`，并且拉长局部值的 live range。真正困难的地方不是“要不要用局部变量”，而是“优化之后到底该把哪些精确更新 materialize 到哪里”。

## 核心洞察

论文最重要的洞察是把“精确计数”拆成两个优化需求不同的阶段。函数内部只记录事件带来的局部增量，也就是 delta-counter；这些值的作用域和生命周期对编译器完全透明，因此 loop optimizer、SCEV、induction-variable simplification 乃至 vectorization 都更容易接管。等主优化结束后，再把这些局部增量变成外部可见的全局更新。这样一来，很多原本必须逐次执行的计数，最后会自然收敛成“循环 trip count”“分支选择出来的常量”甚至“向量归约后的标量”。

PRUE，也就是 Partially Redundant Update Elimination，把“延后更新放哪儿”这个问题改写成一个稀疏 SSA 重写问题，而不是在优化前凭 CFG 猜位置。它从一个晚期的 `inc(v)` 更新出发，沿着 SSA 的 def-use 关系向后分析，只保留那些可能携带非零值的路径；只会产生零值的路径则被剪掉。于是 Zircon 同时解决了两件事：一方面避免了优化前的全局副作用，另一方面又避免了“全部拖到最后”带来的部分冗余更新。

## 设计

Zircon 分成两个阶段。第一阶段发生在常规优化管线之前：系统为每个函数注入局部 delta-counter。实现上，它先用 LLVM `alloca` 分配可变局部变量，之后再交给 `Mem2Reg` 提升成 SSA 值和 phi 节点。为了尽可能不挡住优化器，Zircon 先把全局更新统一放到函数的单一出口上，让每个 delta-counter 拥有尽可能长的生命周期；等优化器把局部算术、循环结构和控制流都整理完，再在第二阶段收缩这些生命周期。为了让值流分析保持简单，Zircon 还采用 single-assignment policy：一个 delta-counter 只会在一个 basic block 中被递增；如果同一事件会在多个块中出现，就拆成多个专用 counter。

第二阶段是在 LLVM 优化管线末端运行的 PRUE。它维护一个工作队列，队列元素是“在 basic block `u` 里执行 `inc(v)`”这样的任务。每个 transformer 的目标都是把更新尽量往函数入口方向推，或者把更新拆开，让携带零值的路径显式暴露出来。`eliminate` 最简单，遇到 `inc(0)` 就直接删掉。`relocate` 把更新提升到同一循环结构中的最高安全 dominator，以缩短 live range。`split` 面对 phi 值时，会沿着每条 incoming edge 把更新拆成多个副本，必要时还会新建 edge block，以保证这些副本彼此不可达，不会重复计数。

循环是最难的部分，因为把更新往循环内部移动，很容易让一次应该做的更新被多次执行。为此，PRUE 设计了两个 loop-aware transformer。`offload` 处理的是“外层延后更新其实只依赖某个内层循环里的活跃加法”这一类情况：它把来自循环外部的 phi 输入重写成零，然后在循环的专用退出点上新建更新。`unpack` 是保底机制，当所有嵌套循环里都还残留 partial redundancy 时，它会拆开加法表达式，把那个不属于局部闭包的操作数单独变成新的更新任务。论文的正确性论证围绕两个不变量展开：原始更新里所有会产生非零贡献的值，必须被恰好一个派生子任务捕获；而同一个原始更新拆出来的子任务必须彼此不可达。由于每一次变换都会把任务进一步推向函数入口，算法最终一定终止。

## 实验评估

评估覆盖了三个层面：LLVM 17 上 `-O3` 的 SPEC CPU 2017，借助 CFGGrind 的 Jotai 指令计数实验，以及 AFL++ 配合 Magma 的下游 fuzzing 实验。整体上，基线设置是比较公平的：SanCov 既作为基线，也作为共享运行时；Nisse 因为公开原型无法处理多文件软件，所以作者基于同一运行时重写了一版；另一个 EarlyQ 基线则近似 Odin 风格的 early quantification。

主结果不是只靠个别工作负载撑起来的。Zircon 在 SPEC 上的运行时开销范围是 `0.2%-44%`，几何平均 `19%`；SanCov 是 `16%-263%`、均值 `51%`，Nisse 是 `9%-246%`、均值 `40%`，EarlyQ 是 `10%-484%`、均值 `105%`，PGOInstrumentation 是 `3%-131%`、均值 `46%`。最显眼的单点案例是 `nab`：Zircon 大约比 SanCov 和 Nisse 快 `2.5x`，因为它让循环优化器恢复出了标量化后的计数，而不是保留逐次迭代的全局加法。论文也没有回避边界情况：如果某些程序里优化器可利用的信息本来就很少，那么依靠 MST pruning 直接减少计数器数量的 Nisse 或 EarlyQ 仍然可能更快。

PRUE 本身也不是可有可无的锦上添花。没有 PRUE 时，延后更新会带来平均 `8.45%` 的冗余更新比例，并让 Zircon 再慢 `1.15x-7.53x`；启用 PRUE 后，这个比例降到 `0.68%`，意味着超过 `90%` 的冗余更新被消掉。Jotai 上用 CFGGrind 统计得到的指令增长比也支持这一点：Zircon 平均只有 `1.13x`，低于 SanCov 的 `1.17x`、Nisse 的 `1.19x`、PGOInstrumentation 的 `1.21x` 和 EarlyQ 的 `1.33x`。编译统计从另一个角度说明了同一件事：和晚期插桩相比，Zircon 让 reassociation 大约提升 `10x`、instruction simplification 提升 `7x`、induction-variable replacement 提升 `6x`、LICM 风格的 sinking 提升 `3x`。而它的编译时额外开销只比 SanCov 高约 `12.4%`，明显低于 Nisse 相对 SanCov 的 `54.9%`。在下游 AFL++/Magma 实验里，Zircon 在固定预算内比 SanCov 多找到 `17.5%` 的 bug、比 Nisse 多找到 `20%`，同时把 RMST 分别降低了 `13.43%` 和 `10.70%`。

## 创新性与影响

和 _Frenot and Pereira (CC '24)_ 相比，Zircon 的新意不在于再设计一种 MST 上的计数恢复方法，而在于先把精确计数写成优化器友好的形式，让编译器直接把大量计数简化掉。和 _Wang et al. (PLDI '22)_ 相比，它并不靠按需移除 instrumentation 来换性能，而是在全程保留精确信息的前提下降低开销。和 _Wang et al. (USENIX ATC '21)_ 相比，它关注的不是 counter 地址或索引的机器级简化，而是 exact counting 真正昂贵的那部分，也就是 value update。

因此，这篇论文对编译器工程师、sanitizer / profiler 作者，以及 fuzzing 系统设计者都很有参考价值。它更大的意义在于换了一个问题表述：instrumentation overhead 往往不只是“额外执行了多少条指令”，而是“你写出来的 instrumentation 到底是否 compatible with optimizers”。Zircon 给出的答案是一个新的机制，也是一种新的思路。

## 局限性

论文对局限性写得比较坦诚。首先，Zircon 是 compiler IR 层面的方案，因此二进制插桩若想受益，必须先把 binary lift 回 IR。其次，它要求事件标识符在一次函数调用内部保持稳定；对很多 context-insensitive 或 calling-context-sensitive 方案来说这不是问题，但若标识符在函数内部高度动态变化，就比较难处理。再者，Zircon 依赖 dominance / post-dominance 这样的控制流结构，不规则控制流，比如非局部异常跳转，会削弱它的基本假设。

从部署视角看，还有两点现实限制。其一，原型和实验主要围绕 exact edge counting 展开，并借用了 SanCov 的运行时支持层，因此论文并没有完全证明 Zircon 在更异质的 instrumentation scheme 或不同 runtime 设计下也一定保持同样收益。其二，为了保持 general-purpose，Zircon 默认不启用 MST-style pruning；这让它在优化器收益主导时更强，但在“直接减少计数器数量”更重要的工作负载上，可能会输给更专门化的方案。

## 相关工作

- _Frenot and Pereira (CC '24)_ — Nisse 通过 affine variable 与 MST 结构降低 exact profiling 的代价，而 Zircon 则重写 exact update 本身，让优化器直接把计数化简掉。
- _Wang et al. (PLDI '22)_ — Odin 依赖按需 instrumentation 与重编译来降低 fuzzing 开销；Zircon 则面向始终开启的精确事件量化，不丢失运行时信息。
- _Wang et al. (USENIX ATC '21)_ — RIFF 通过硬编码 counter 地址缩小 coverage-guided fuzzing 的指令足迹，这属于 counter index 优化；Zircon 关注的是与之正交的 counter value update。
- _Ball and Larus (MICRO '96)_ — 经典 path profiling 主要优化动态路径索引，而 Zircon 处理的是编译器优化之后 exact counter-value update 这一不同瓶颈。

## 我的笔记

<!-- empty; left for the human reader -->

---
title: "QTurbo: A Robust and Efficient Compiler for Analog Quantum Simulation"
oneline: "把模拟量子模拟编译拆成全局线性求解、局部混合求解、演化时间收紧和残差修正，在更短脉冲下更快、更稳地生成控制序列。"
authors:
  - "Junyu Zhou"
  - "Yuhao Liu"
  - "Shize Che"
  - "Anupam Mitra"
  - "Efekan Kökcü"
  - "Ermal Rrapaj"
  - "Costin Iancu"
  - "Gushu Li"
affiliations:
  - "University of Pennsylvania, Philadelphia, PA, USA"
  - "Lawrence Berkeley National Laboratory, Berkeley, CA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762227"
code_url: "https://github.com/JunyuZhou2002/QTurbo.git"
tags:
  - compilers
  - hardware
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

QTurbo 的核心观点是，模拟量子模拟编译之所以显得很难，很大程度上是因为现有工具把所有事情都塞进一个巨大的混合方程组里一次性求解。它先把反复出现的系数提升为 synthesized variables，先解一个全局线性系统，再只对真实控制量所在的小型局部混合子系统求解。随后，QTurbo 再根据硬件幅度上限选出最短可行的演化时间，并用残差修正把精度拉回来。结果是在模拟后端和 QuEra Aquila 真机上，QTurbo 都比 SimuQ 更快地产生更短、误差更低的脉冲序列。

## 问题背景

模拟量子模拟的吸引力在于，它不必像数字量子模拟那样先把物理系统离散成海量量子门，而是直接利用硬件原生 Hamiltonian 去逼近目标系统的演化。但软件栈还很早期。论文把 SimuQ 视为当前唯一公开可用的同类编译器，并将其作为主要基线。SimuQ 的基本方法是：把目标 Hamiltonian 映射到模拟器控制指令时，一次性构造一个覆盖演化时间、脉冲幅度、相位、原子位置以及若干开关型变量的大型混合方程组。

这种表达能力很强，但搜索空间的形状非常糟糕。求解器必须同时处理连续变量和离散变量之间的耦合关系，随着系统规模增长，编译时间会迅速恶化。论文用 Ising cycle 的实验展示了近似指数式的增长趋势。更麻烦的是，即使 SimuQ 找到了一个可行解，它也往往没有把机器上的实际演化时间压到最短，因此生成的脉冲序列可能比必要长度长得多。对模拟量子硬件来说，这会同时带来两类问题：一是更长的脉冲更容易受退相干和噪声影响，二是求解过程本身不稳定，某些情况下基线甚至会直接失败、给不出解。于是，真正的问题不只是“能不能正确编译”，而是“能不能稳定、快速地编译，并把脉冲长度压进硬件相干时间预算里”。

## 核心洞察

QTurbo 最重要的洞察是，表面上那个“一整个巨大的混合方程组”其实并不是结构上真正扁平的。许多方程会反复使用相同的物理量，比如 Rydberg 相互作用系数，或者“幅度乘以演化时间”这样的组合项。只要把这些重复表达式提出来，定义成 synthesized intermediate variables，那么全局匹配问题就会先退化成一个针对目标 Hamiltonian 系数的线性系统。真正困难的部分不再是一个统一的巨型非线性求解，而是若干个规模很小的局部混合子系统，用来恢复每个 synthesized coefficient 背后的真实控制变量。

第二个洞察是，硬件约束不必只是“求解时顺带检查”的麻烦事，而可以直接变成优化原则。像 detuning、Rabi amplitude 这类 runtime-dynamic control 都有明确的最大合法幅度，因此每个局部子系统都隐含了一个“该指令在极限幅度下最短能跑多久”的下界。所有这些下界里最慢的那个指令，就是全局机器演化时间的瓶颈。把这个时间固定后，再去解 runtime-fixed variables，并让更灵活的 dynamic controls 吸收残余误差，就能把分解、定时和精度控制串成一条统一流水线，而不是三段互不相干的启发式步骤。

## 设计

QTurbo 的设计可以看成四个衔接紧密的阶段。第一步是构造全局线性系统。以 Rydberg 后端为例，编译器把 `C6 / 4|xi - xj|^6`、`Delta_i / 2 * T_sim`、`Omega_i / 2 * cos(phi_i) * T_sim` 之类的重复表达式替换为 synthesized variables `alpha`。之后，编译器只需要写出一个线性系统，要求这些 synthesized coefficients 在乘上目标演化时间后与目标 Hamiltonian 的系数一致。这样做的效果是：在真正进入非线性求解之前，就已经把大部分组合爆炸削掉了。

第二步是恢复剩余依赖关系。QTurbo 把 synthesized variables 和真实 amplitude variables 之间的依赖建成一个图，再对这个图求 connected components。每个连通分量都对应一个局部 mixed equation system。共享相互作用项的原子位置变量会落在同一个子系统里；每个 detuning 或 Rabi drive 也可能形成自己的子系统。相比 SimuQ 的“一锅端”求解，这种做法把高维耦合限制在真实存在依赖的地方，因此局部系统更小、更容易解。

第三步是演化时间优化。论文把变量分成两类：一类是 runtime-dynamic variables，也就是执行过程中可以调整的控制量；另一类是 runtime-fixed variables，例如原子位置。对每个带有 time-critical dynamic variable 的局部子系统，QTurbo 都会问一个具体问题：如果这个变量跑到硬件允许的最大幅度，为了满足 synthesized coefficient，最短合法的 `T_sim` 是多少？编译器对每条相关指令都算出这样一个最小时间，然后取其中最大的那个作为全局机器演化时间。这样做的意义是让真正的瓶颈指令被“打满”，同时保证其他指令依旧可行。如果后续 fixed-variable 求解仍然违反约束，QTurbo 就逐步增大时间直到满足限制。对 time-dependent Hamiltonian，论文则采用 piecewise-constant 离散化，再按时间段重复这个过程。

第四步是精度修正。论文先给出一个 `L1` 误差上界，说明总编译误差可以分解成全局线性系统误差与各局部 mixed system 误差之和，再乘上线性系统矩阵范数。基于这个分析，QTurbo 在第一轮求解完成后，利用 residual equation 去微调那些属于 runtime-dynamic controls 的 synthesized variables。因为这些动态控制量比固定变量更灵活，它们就可以在不重新打开整个大非线性问题的前提下，补偿前面各阶段累积下来的近似误差。

## 实验评估

论文的实验同时覆盖模拟后端和真实硬件。在模拟后端上，作者评测了 Rydberg 与 Heisenberg 两类 analog instruction set，基准系统规模从 `3` 到 `93` 个 qubit，涵盖 Ising chain、Ising cycle、Kitaev、Ising cycle+、Heisenberg chain、MIS chain 和 PXP。基线始终是 SimuQ，指标则包括 compilation time、machine execution time，以及编译后 Hamiltonian 与目标 Hamiltonian 在系数空间上的 relative error。

对 Rydberg 后端，QTurbo 报告平均 `350x` 的编译加速、`54%` 的执行时间缩短，以及 `45%` 的编译误差下降；单独看 refinement，本身又能比不做 refinement 再降 `66%` 误差。对 Heisenberg 后端，平均编译加速提升到 `800x`，执行时间缩短 `48%`，并且在评测样例上把编译误差降到零。论文中的 mapping case study 直接复用了 SimuQ 的映射策略，但仍然得到 `61x` 的编译加速，这点很重要，因为它说明主要收益确实来自求解过程的分解，而不是靠更聪明的 placement“偷分”。对于 time-dependent 的 MIS chain，论文先把时间轴切成四段，再分别编译，最终报告 `1300x` 的编译加速、`64%` 的执行时间缩短和 `77%` 的误差下降。

最有说服力的还是 Aquila 真机实验。对一个 `12` 原子的 Ising cycle，QTurbo 能把 `1.0 us` 的目标演化压缩成 `0.25 us` 的机器脉冲，而 SimuQ 需要 `1.2 us`；对一个 `6` 原子的 PXP 模型，QTurbo 把 `20 us` 的目标演化压到 `0.4 us`，而 SimuQ 需要 `3.4 us`。这些更短的脉冲最终体现为更低的测量误差：论文报告两项 Ising 可观测量的平均误差分别下降 `59%` 和 `80%`，两项 PXP 可观测量的平均误差分别下降 `31%` 和 `36%`。这组结果很好地支撑了论文的主张。不过边界也很清楚：真机实验规模不大，而且论文的主要 relative-error 指标本身并不直接建模退相干，因此必须依赖这些硬件结果来证明“更短脉冲更抗噪”这件事。

## 创新性与影响

和 _Peng et al. (POPL '24)_ 相比，QTurbo 保留了“把任意 analog Hamiltonian 编译到真实控制脉冲”的目标，但彻底改变了计算结构：一个全局 mixed solve 被拆成线性阶段、局部 mixed 阶段、显式的时间优化和后续 refinement。和 Pulser 这类 pulse-programming framework，或者 OpenQASM 3 这种更通用的控制语言相比，QTurbo 的新意不是暴露更多底层接口，而是从 Hamiltonian 规格自动求出满足硬件约束的优质控制序列。

因此，这篇论文最重要的意义在于，它把 analog quantum simulation 往“真正可编译的目标”推进了一步，而不再只是依赖大量手工数值调参。它首先是一篇编译器论文，但它的影响会直接落在硬件噪声预算、脉冲长度和模拟设备可用性上。如果未来 Rydberg、trapped-ion 或 superconducting 的模拟量子平台继续扩大，这种基于分解的编译器架构很可能会成为后续工作的参照点。

## 局限性

QTurbo 并没有解决整个 analog-programming 栈。它的主要收益建立在一个前提上：后端需要提供清晰的 instruction abstraction，并且存在幅度上限明确的 time-critical variables。映射问题也基本不在本文主贡献内，论文里的 mapping case study 只是直接复用了基线的放置策略。time-dependent Hamiltonian 的处理同样依赖 piecewise-constant 近似，这在实践里很常见，但也意味着误差有一部分在真正编译之前就已经被引入。

实验方面，最强的证据来自 neutral-atom Rydberg 系统，而真实硬件多样性仍然有限。Heisenberg 的结果主要停留在模拟层面，没有在云端真实设备上复现；Aquila 真机部分也只有两个较小案例。论文的主精度指标比较的是 Hamiltonian 系数差异，而不是带完整噪声模型的最终 many-body state fidelity。这些都不削弱论文的价值，但它更适合被理解为“一个很强的 analog simulation compiler architecture”，而不是已经把 mapping、calibration 和 hardware-aware verification 全部做完的完整解决方案。

## 相关工作

- _Peng et al. (POPL '24)_ — SimuQ 同样试图把任意 Hamiltonian 编译成 analog control，但它直接求解一个全局混合方程组，而 QTurbo 把求解过程拆成线性阶段与局部阶段。
- _Silvério et al. (Quantum '22)_ — Pulser 提供 neutral-atom pulse design 的可编程接口，而 QTurbo 的重点是从 Hamiltonian 描述自动综合控制序列。
- _Cross et al. (TQC '22)_ — OpenQASM 3 扩展了 pulse-level programmability，但并不会直接优化 analog Hamiltonian compilation 或演化时间。
- _Li et al. (ASPLOS '22)_ — Paulihedral 优化的是离散化之后的 digital Hamiltonian-simulation kernel，而 QTurbo 保持在 analog 域内，直接利用原生相互作用。

## 我的笔记

<!-- 留空；由人工补充 -->

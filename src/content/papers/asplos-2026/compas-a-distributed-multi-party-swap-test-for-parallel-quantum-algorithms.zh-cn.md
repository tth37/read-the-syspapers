---
title: "COMPAS: A Distributed Multi-Party SWAP Test for Parallel Quantum Algorithms"
oneline: "COMPAS 用 Bell pair 传送把 multi-party SWAP test 分布到线形互连 QPU 上，在保持常数深度的同时，把朴素方案的二次纠缠开销降到 O(nk)。"
authors:
  - "Brayden Goldstein-Gelb"
  - "Kun Liu"
  - "John M. Martyn"
  - "Hengyun (Harry) Zhou"
  - "Yongshan Ding"
  - "Yuan Liu"
affiliations:
  - "Brown University, Providence, Rhode Island, USA"
  - "Yale University, New Haven, Connecticut, USA"
  - "Pacific Northwest National Lab, Richland, Washington, USA"
  - "Harvard University, Cambridge, Massachusetts, USA"
  - "QuEra Computing Inc., Boston, Massachusetts, USA"
  - "North Carolina State University, Raleigh, North Carolina, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790143"
code_url: "https://github.com/kunliu7/Distributed-Q-Algo"
tags:
  - hardware
  - compilers
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

COMPAS 把原本适用于单体量子机的 constant-depth multi-party SWAP test，改造成可在模块化量子计算机上执行的分布式原语。它让每个输入态留在本地 QPU，用 Bell-pair-assisted teleoperation 实现共享 GHZ 控制态和远程 `CSWAP`，再用 Fanout 并行化共享控制的 Toffoli。这样既保住了常数深度，也把朴素分布式方案里的 Bell pair 开销降成 `O(n k)`。

## 问题背景

这篇论文首先面对的是硬件扩展瓶颈，而不是某个孤立算法的优化问题。实际有用的量子计算很可能会超出单芯片在 qubit 数量、布线密度和控制复杂度上的能力，因此未来系统大概率要由多个 QPU 互连组成。但在分布式量子计算里，跨节点操作必须依赖 Bell pair、state teleportation 和 remote gate；每一次非本地交互都会直接消耗纠缠资源，并增加噪声暴露。

作者把目标锁定在 multi-party SWAP test，因为它是 Rényi entropy estimation、entanglement spectroscopy、virtual cooling / distillation 和 parallel quantum signal processing 的共同子程序。难点在于，现有最好的单机实现并不能直接平移到模块化硬件上。朴素分布式方案会把输入态切片，再把相同位置的 qubit 汇聚到同一台 QPU 上局部运行 SWAP test；在 line topology 上，这种最坏情况每个 QPU 都要消耗 `O(n^2)` 个 Bell pair，而且若计算继续执行，还得把 qubit 再传回原位。论文真正要回答的，就是能否把这个 primitive 分布出去，同时保住常数深度、控制 GHZ 宽度，并把纠缠开销压到近期开销模型还能接受的范围内。

## 核心洞察

论文最核心的洞察是，multi-party SWAP test 的内部结构比一般量子电路规整得多，因此它可以被分布化，而不必付出常见的深度惩罚。该测试依赖的 cyclic-shift operator 可以按 `1, k, 2, k-1, ...` 这样的交错布局执行，在这种布局下，每个状态最多只与两个邻居交互。于是系统就能让每个状态驻留在一台 QPU 上，状态制备完全本地化，而把跨节点通信限制在 SWAP-test 阶段。

在此基础上，COMPAS 把方案拆成三个模块：用 teleported CNOT 在多台 QPU 上准备 GHZ 控制态；用 `telegate` 或 `teledata` 实现相邻状态之间的远程 `CSWAP`；再用 Fanout 把每轮测试里共享同一控制位的 `n` 个 Toffoli 从串行改成 `O(1)` 深度并行执行。三者结合起来，才让分布式实现既能保留原始算法的 constant-depth 特性，又把 Bell pair 消耗压到 `O(n k)`。

## 设计

整个架构使用 `k` 台按线形互连的 QPU。第 `i` 台 QPU 存放一个 `n`-qubit 状态 `rho_i`，部分 QPU 还额外持有 GHZ 控制位。这个布局的意义在于，把昂贵的远程交互缩到最小：`rho_i` 的制备始终本地完成，只有分布式 multi-party SWAP test 才需要通信。GHZ preparation 阶段把 Quek et al. 的 constant-depth GHZ 构造改写到分布式环境里，用 telegated CNOT 替换跨 QPU 的 CNOT，于是得到一个分布在 `ceil(k/2)` 个节点上的 GHZ 状态；随后 controlled cyclic shift 由两轮相邻 `CSWAP` 完成。

这里论文给出两种 `CSWAP` 实现。`Telegate` 把远程 `CSWAP` 分解成 teleported CNOT 和 teleported Toffoli；`teledata` 则先把 Bob 的 `rho_j` 传到 Alice 的 ancilla，本地做完整 `CSWAP`，再把 qubit 传回去。共享控制的 Toffoli 会被重写成 Fanout 形式，因此深度仍是常数，并且 ancilla 可以跨步骤重用。逐 QPU 的资源表也很明确：`telegate` 需要 `n` 个 ancilla、`2 + 6n` 个 Bell pair、总深度 `99`；`teledata` 需要 `2n` 个 ancilla、`2 + 4n` 个 Bell pair、总深度 `91`。论文最终推荐 `teledata`，因为把 Bell pair distillation 算进去后，它的总内存成本更低。

## 实验评估

这不是一篇做出真实硬件原型的论文，评估主体是资源分析加电路级仿真。作者首先比较 `telegate`、`teledata` 和朴素分布式基线的 ancilla 数、Bell pair 数和 circuit depth。仅这一部分就足以支撑论文主张：COMPAS 用不大的常数项深度代价，换来了更健康的纠缠资源缩放规律，而在把 Bell pair 看成昂贵资源时，`teledata` 明显优于 `telegate`。对 Fanout，Stim 仿真显示最常见的是共享控制 qubit 上的 `Z` error；对 `CSWAP`，Qiskit 仿真显示 `teledata` 与 `telegate` 很接近，但前者平均仍高出约 `0.84%` 的 fidelity。

这些部件模型随后被组合成单次 multi-party SWAP test 的整体下界 `(1 - p_GHZ(ceil(k/2))) (1 - p_CSWAP(n))^(k-1)`。我认为最重要的结果是 network-level bound。论文假设本地门完美，只把 Bell pair 分发过程建模成 depolarizing channel，于是得到 `F_tot >= (1 - 43p/4)^(O(nk))`，进一步推出若想把总误差压在 `epsilon` 以内，就必须满足 `k <= O(epsilon / (n p))`。作者再把这个式子和最近的 entanglement distillation 结果联系起来：若每台 QPU 有 `n = 100` 个 qubit，并采用文中引用的 LP code，把逻辑 Bell pair infidelity 压到约 `10^-6` 以下，那么在仅考虑 Bell pair 噪声时，系统最多能扩展到 `k = 5` 台 QPU，之后总误差就会超过 `epsilon = 10^-3`。

## 创新性与影响

和 _Quek et al. (Quantum '24)_ 相比，COMPAS 并没有提出新的 trace-estimation 目标，而是把 constant-depth multi-party SWAP test 真正移植到 distributed QPU 上，并补齐了 multi-qubit 状态下维持常数深度所需的编译与资源分析。和 _Ferrari et al. (IEEE TQE '21)_ 这类通用 distributed quantum compiler 工作相比，它的范围更窄，但也正因为只盯住一个 primitive，才能给出精确的 Bell pair、ancilla 和噪声公式。和 _Huggins et al. (PRX '21)_、_Martyn et al. (Quantum '25)_ 这类应用论文相比，COMPAS 更像是 virtual distillation 和 parallel QSP 背后的底层基础设施，而不是新的应用算法。

## 局限性

论文最强的证据仍然是资源估算，而不是真实硬件上的端到端演示。`Teledata` 与 `telegate` 的优劣比较依赖于 Bell pair distillation 比例的假设，而整体可扩展性又高度依赖网络误码率。尤其是 `k <= O(epsilon / (n p))` 这个约束，意味着当状态更宽或链路更噪时，系统会更难扩展。

它的作用域也很明确。COMPAS 针对的是 multi-party SWAP test 及其直接衍生应用，而不是任意 distributed quantum circuit。架构分析假设了 line topology，并抽象掉了完整的 fault-tolerant 开销、异构链路以及 Bell pair generation 节点部署等现实因素。

## 相关工作

- _Quek et al. (Quantum '24)_ — 给出了 constant-depth 单机场景构造，而 COMPAS 把它移植到 distributed QPU。
- _Ferrari et al. (IEEE TQE '21)_ — 研究一般性的 distributed quantum compiler，而 COMPAS 围绕单个 primitive 给出精确资源核算。
- _Huggins et al. (PRX '21)_ — 用 multi-party SWAP test 做 virtual distillation；COMPAS 扩展的是该子程序的硬件适用范围。
- _Martyn et al. (Quantum '25)_ — 给出一类应用动机，而 COMPAS 提供其所需的分布式 trace-estimation 底座。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "Architecting Scalable Trapped Ion Quantum Computers using Surface Codes"
oneline: "用拓扑感知的 QCCD 编译与误差模型证明：面向 surface code 的 trapped-ion 机器应优先选择双离子 trap 与 grid 互连，而布线仍是功耗与速度的权衡。"
authors:
  - "Scott Jones"
  - "Prakash Murali"
affiliations:
  - "Department of Computer Science and Technology, University of Cambridge, Cambridge, United Kingdom"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3779212.3790128"
tags:
  - quantum
  - hardware
  - compilers
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文问的不是“QCCD 能不能扩展”，而是“真正跑 surface-code 容错时，QCCD trapped-ion 机器到底该长什么样”。作者给出的答案出人意料地激进：trap 要尽量小，最好是容量为 `2` 的 trap；互连用能保留二维局部性的 grid；还要配一个足够懂 surface code 结构的编译器，才能把这些设计点公平地比较出来。论文同时指出，当前看起来更省功耗的布线方法虽然缓解了控制电子学压力，却可能把逻辑时钟拖慢到难以接受。

## 问题背景

论文的出发点是一个很硬的规模鸿沟。今天的 trapped-ion 系统还停留在不到 `60` 个 physical qubit 的量级，而真正有实用价值的 fault-tolerant quantum computing 需要大约 `100-1000` 个 algorithmic qubit，并把逻辑错误率压到 `10^-9` 左右。要跨过这道坎，就必须做 quantum error correction。作者选择研究 surface code，因为它的二维局部结构与模块化 trapped-ion 架构比很多其他编码更契合。目标硬件则是 QCCD：把离子分散在许多小 trap 中，再通过 transport segment 和 junction 在 trap 之间搬运离子，使需要的双比特操作能在同一个 trap 内完成。

真正缺失的不是 QCCD 这个概念，而是“为了逻辑 qubit，QCCD 应该选哪个设计点”的工程答案。trap capacity、trap 之间的通信拓扑、以及 electrode 到 DAC 的布线方式会相互牵制。大 trap 可以减少通信，但会串行化更多门操作，甚至拉低 fidelity；小 trap 能释放更多并行性，但通信次数最多；更丰富的互连似乎更强，但如果 workload 本身就极度局部，这种额外灵活性也许根本用不上。此前的编译器和体系结构研究大多盯着 NISQ 电路、手工 mapping 或少数固定硬件参数，因此不足以回答“怎样的 trapped-ion 机器最适合跑 surface code”这个问题。

## 核心洞察

这篇论文最重要的结论是：对 surface-code 工作负载来说，“先尽量减少通信”是一个会把人带偏的优化目标。由于 parity-check 电路本身非常规则、通信也高度局部，真正决定系统质量的是能否保住并行性，同时只为那些结构上必需的相互作用付出搬运成本。只要编译器同时理解 code 的拓扑和设备的拓扑，一个表面上“通信最多”的 capacity-2 设计，反而会成为整体最优点。

这个结论之所以站得住，不是因为作者只比了 swap 数或 crossing 数，而是把 compilation、noise 和 hardware cost 放进了同一个闭环里。他们会完整编译 syndrome-extraction round，用符合 trapped-ion 物理特性的噪声模型去模拟 logical error，还会根据 electrode 数量和布线方式去估算控制链路带宽与功耗。于是 capacity-2 的优势不只体现在 cycle time 上，也体现在 logical error 上，甚至在考虑“为了达到同样目标逻辑错误率到底需要多大 code distance”之后，连硬件效率都更好。

## 设计

整套工具流先把 surface-code parity-check 电路翻译成原生 QCCD 指令，包括单比特旋转、Mølmer-Sørenson 双比特门、测量、复位，以及 split、merge、shuttling、junction crossing 等显式 movement primitive。随后编译器分两步把逻辑 qubit 映射到物理离子。第一步是把 surface-code 交互图切成大小约为 `capacity - 1` 的平衡 cluster，并且故意给每个 trap 留出一个空位，方便通信时让外来离子临时进入。由于 surface code 的图结构本身接近规则网格，作者没有把它当成一般 NP-hard mapping 问题硬求，而是利用这种规则性做自顶向下的 partition。第二步再把这些 cluster 按几何位置匹配到具体 trap 上，尽量让代码中相邻的区域在硬件上也仍然相邻。

路由部分也不是抽象成交换边就结束，而是直接面对 QCCD 约束：trap 有容量上限，segment 和 junction 在同一时刻只能容纳一个离子，ancilla 必须被送到能与目标 data qubit 同 trap 的位置。编译器把设备状态建成有向图，为 ancilla 的移动分批分配最短路径；在一个 pass 中，凡是容量被占满的组件都会暂时从图里移除，随后再把已经变得可执行的 movement 和 gate 发射出去。最后用 list scheduling 根据 primitive latency 和依赖关系排时间，并按加权 critical path 优先调度 ready 操作。

作者还给这条编译链接上了物理模型。运行时间由 primitive 的持续时间决定；logical error 则通过 Stim 做 noisy simulation，其中包括 idle 与 movement 期间的 dephasing、单/双比特门的 depolarizing error、reset 与 measurement error，以及离子加热对后续 gate fidelity 的影响。另一套 resource model 则根据 trap 数、junction 数和 electrode 数量，推导 controller-to-QPU 的数据率与功耗，从而可以把标准直接布线和 WISE 式复用控制放到同一个量纲里比较。

## 实验评估

实验覆盖了 `2` 到 `20` 的 rotated surface code distance、`2` 到 `30` 的 trap capacity、三种通信拓扑、两种布线方式，以及 `1x` 到 `10x` 的物理门质量改进情景。在真正做 design-space exploration 之前，作者先验证编译器本身是否靠谱。对手工优化的小规模样例，编译结果的 elapsed time 平均只比理论最优差 `1.09x`，routing operation 数则在 `1.04x` 之内。和已有 trapped-ion 编译器相比，新编译器把 movement time 平均降低了 `3.85x`，movement operation 平均减少了 `1.91x`。这一步很关键，因为如果 compilation 本身就很差，后面所有体系结构结论都会失真。

最核心的结果来自 trap-capacity sweep。容量为 `2` 的 trap 给出了最低的 QEC round time，而且与更大 trap 不同，它的 cycle time 随着 code distance 增长几乎保持常数。根本原因在于：更大 trap 虽然减少了部分跨 trap 通信，却永远弥补不了并行性损失。一旦太多 qubit 被塞进同一个 trap，门操作就会被更多地串行化。logical error 的结果更强。论文报告说，在考察的 `1x`、`5x`、`10x` gate-improvement 情景下，capacity-2 设计相对更大 capacity 通常能低出一到两个数量级的逻辑错误率。在 `10x` gate improvement 下，作者预计 distance `13` 的 capacity-2 设计就能达到目标的 `10^-9` 逻辑错误率。

通信拓扑的结论也很干脆。线性拓扑因为 routing congestion 非常差；例如论文报告在 `d=5, capacity=2` 时，linear 设计完成一次 logical identity 需要超过约 `275 ms`，大约是 grid 或 all-to-all switch 的 `12x`。相比之下，grid 和 switch 在 elapsed time 与 logical error 上几乎没有显著差别。这意味着 surface code 本身的局部性已经足够强，较简单的 grid 拓扑基本吃到了 all-to-all switch 的大部分收益。

最后，布线实验揭示了第二个系统瓶颈。对标准直接布线方案来说，即便在最优设计点，要把单个 logical qubit 压到 `10^-9`，依然需要大约 `1.3 Tbit/s` 的控制带宽和约 `780 W` 的功耗，这显然无法线性扩展。WISE 可以把数据率和功耗降低两个数量级以上，但由于它限制了可同时发生的 movement primitive 类型，在接近 `10^-9` 的工作点上，逻辑时钟可能会慢到标准方案的 `25x`。这很好地支撑了论文的整体论点：trapped-ion 的可扩展性不是单纯的 qubit-count 问题，而是一个控制电子学、编译、拓扑和误差共同决定的 cross-layer architecture 问题。

## 创新性与影响

相较于 _Murali et al. (arXiv '20)_，这篇论文把 workload 和结论都改写了：前者面向 NISQ 应用时偏好 `15-25` 离子的 trap，而本文针对 surface-code logical qubit 得出的却是“trap 越小越好，最好就是 2”。相较于 _Malinowski et al. (PRX Quantum '23)_，本文并没有提出新的 wiring mechanism，而是把 WISE 放进完整的 logical-qubit 评估中，量化出节能收益会在什么位置转化成 runtime 代价。相较于 _Leblond et al. (SC-W '23)_，它也不是针对单一标准架构的固定 resource estimator，而是一个由编译器支撑的体系结构设计空间探索框架。

因此，这篇论文最可能影响的是 trapped-ion 硬件路线图和 quantum hardware-software co-design 社群。它最有价值的地方不是某一个孤立的 routing 技巧，而是系统性纠正了社区对“可扩展 trapped-ion 设计”应当追求什么的直觉。

## 局限性

论文有意把问题收窄到“单个 logical qubit 持续执行 surface-code parity check”，因此它并没有直接评估如何把许多 QCCD 模块联网，也没有真正模拟多个 logical qubit 之间的大规模协同调度。作者认为若采用 lattice surgery，很多结构性结论仍会保留，但这更像一种合理外推，而不是文中实证过的结果。另一个局限是，论文中的可行性拐点明显依赖 `5x` 和 `10x` gate improvement 这样的未来假设，因此“要做到 `10^-9` 究竟需要多大 code distance”仍然会随硬件路线图而变化。

还有一些体系结构假设未来可能改变结论。分析默认 trap 内没有真正实用的并行双比特门，这也是 capacity-2 如此占优的重要原因之一。如果未来设备能把 trap 内并行 entangling gate 做得既快又稳，trap-capacity tradeoff 可能会重排。类似地，WISE 的分析建立在 cooling 支持和特定全局重配置方式之上；如果后续出现新的控制架构，在功耗与逻辑时钟之间也许能找到更好的折中点。

## 相关工作

- _Murali et al. (arXiv '20)_ — 研究的是面向 NISQ 工作负载的 QCCD 设计选择，而本文把目标换成 surface-code logical qubit，并得出了相反的 trap-capacity 建议。
- _Malinowski et al. (PRX Quantum '23)_ — 提出了 WISE 这类可扩展 trapped-ion 布线架构，而本文进一步量化了它在 surface-code QEC 上的逻辑时钟代价。
- _Leblond et al. (SC-W '23)_ — TISCC 面向固定 trapped-ion 设计编译 surface-code 工作负载，本文则把显式 primitive routing 和更大的 architecture space 一起纳入分析。
- _Wu et al. (ISCA '22)_ — 探索 surface-code 结构在 superconducting 设备上的实现，而本文把 trapped-ion 的 transport、topology 和 control wiring 作为一等约束来研究。

## 我的笔记

<!-- empty; left for the human reader -->

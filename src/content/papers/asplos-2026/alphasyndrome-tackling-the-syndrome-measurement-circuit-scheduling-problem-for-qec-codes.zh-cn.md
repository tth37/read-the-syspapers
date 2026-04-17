---
title: "AlphaSyndrome: Tackling the Syndrome Measurement Circuit Scheduling Problem for QEC Codes"
oneline: "AlphaSyndrome 用 MCTS 和带 decoder 的噪声仿真联合搜索 syndrome-measurement 顺序，把 hook error 推向远离逻辑算子且更易被纠正的模式。"
authors:
  - "Yuhao Liu"
  - "Shuohao Ping"
  - "Junyu Zhou"
  - "Ethan Decker"
  - "Justin Kalloor"
  - "Mathias Weiden"
  - "Kean Chen"
  - "Yunong Shi"
  - "Ali Javadi-Abhari"
  - "Costin Iancu"
  - "Gushu Li"
affiliations:
  - "University of Pennsylvania, Philadelphia, United States"
  - "University of California, Berkeley, Berkeley, United States"
  - "Amazon Quantum Technologies, Pasadena, United States"
  - "IBM Research, Yorktown Heights, United States"
  - "Lawrence Berkeley National Laboratory, Berkeley, United States"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790123"
code_url: "https://github.com/acasta-yhliu/asyndrome.git"
project_url: "https://doi.org/10.5281/zenodo.18291927"
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

AlphaSyndrome 把 QEC 的 syndrome-measurement scheduling 视为合法 Pauli check 顺序上的搜索问题，而不是单纯的最小深度优化。它用带噪声仿真并把目标 decoder 放进评估环路，对完整 schedule 直接打分，并在 `32` 个 code/decoder 组合上报告了平均 `80.6%` 的 logical error rate 降低。

## 问题背景

这篇论文抓住了 stabilizer-based QEC 中一个很关键、但过去常被弱化处理的问题：syndrome measurement 的调度空间极大。因为大多数 stabilizer 彼此可交换，而单个 stabilizer 内部的大多数 Pauli check 也可交换，所以在理想无噪声情况下，许多执行顺序看起来等价。但一旦考虑真实硬件噪声，这些顺序就不再等价。ancilla 上的错误会通过后续双比特门传播成 hook error，把一个局部故障扩散成多个 data-qubit 错误；因此，哪个 check 先做、哪个后做，会直接决定哪些 data qubit 更脆弱，以及最终的 logical error rate。

问题在于，常见调度策略都太粗糙。最简单的是按索引顺序执行。更“系统化”的做法是求最低深度，因为这样可以减少 idle 和退相干。对于 rotated surface code，Google 还有很好的 zig-zag 手工 schedule，但它依赖这类 code 的几何结构，很难直接推广。论文强调，更深层的问题是：一个“好”的 schedule 不只取决于 code，也取决于 decoder 和噪声模型。

## 核心洞察

AlphaSyndrome 的核心洞察是，一个好的 syndrome-measurement schedule 必须同时优化两件事。第一，传播后的错误模式应尽量远离 logical operator 的支撑集。第二，这些错误模式要尽量落在所选 decoder 的“可纠正区域”内。论文用 rotated surface code 上顺时针与逆时针的测量顺序做了直观说明：两者都合法，但一个会让传播错误更接近 logical `Z`，另一个则更接近 logical `X`，因而对应的逻辑错误偏置完全不同。

真正重要的是，作者并没有试图为所有 code 写出一条封闭形式的解析规则。一般 QECC 里等价的 logical operator 数量可能是指数级的，而现实中的 decoder 本身就是针对 NP-hard 问题的启发式近似。因此，论文转向对完整 schedule 做仿真评估，让 decoder 与噪声模型直接成为综合目标的一部分。

## 设计

AlphaSyndrome 把一次 syndrome-measurement round 表示成多个 tick，每个 Pauli check 都是一个 `(data, ancilla, sigma)` 三元组，并被分配到某个 tick。位于同一 tick 的 check 不能共享 data qubit 或 ancilla qubit。为了满足反对易约束，系统先把 stabilizer 划分成若干 partition，再对每个 partition 分别运行 MCTS，最后把局部 schedule 串接成完整电路。

MCTS 的状态是“部分完成的 schedule”。一次 move 是选择一个尚未调度的 Pauli check，并把它放到与已有条目不冲突的最早 tick 上；同时通过复用上一步最优 child 的子树来减少重复搜索。对于完整 schedule，AlphaSyndrome 会构造 `stim` 采样电路，执行带噪声的 syndrome-measurement round，调用指定 decoder 做理想纠错，再检查 logical observable 是否翻转。评分函数取整体逻辑错误率的倒数 `1 / (1 - (1 - pX)(1 - pZ))`，因此优化目标直接就是 logical reliability。

## 实验评估

实验覆盖 rotated surface code、color code、hyperbolic surface/color code、defect surface code 和 bivariate bicycle code，并配合 `MWPM`、`BP-OSD` 与 hypergraph union-find decoder 使用。相较最低深度 schedule，AlphaSyndrome 在 `32` 个 code/decoder 实例上的整体 logical error rate 平均降低 `80.6%`，最高降低 `96.2%`。它通常会得到更深的 syndrome-measurement 电路，但作者认为这是值得的交换。

从系统层面看，更低的逻辑错误率意味着系统在达到同等可靠性时可以使用更小的 code distance，因此反而降低 space-time volume。Table 3 在若干代表性 code family 上报告了 `18.4%-89.0%` 的 space-time-volume 降低。对手工 schedule 的比较也很有说服力：在 rotated surface code 上，AlphaSyndrome 能匹配 Google 的 zig-zag schedule；在 `[[72, 12, 6]]` 的 bivariate bicycle code 上，它相对 IBM 的 schedule 在 `BP-OSD` 下把整体 logical error 再降 `44%`，在 union-find 下也有 `10%` 改进。cross-decoder 实验同样很关键：`BP-OSD` 编出来的 schedule 在 `BP-OSD` 下平均优于 union-find 版本 `25.4%`，反向比较则由 union-find 平均领先 `34.3%`。论文还展示了在物理错误率降到 `10^-5` 时仍能持续优于最低深度 baseline。

## 创新性与影响

和最低深度调度工作相比，AlphaSyndrome 最大的新意是把优化目标从 circuit depth 改成了 logical reliability。和 Google、IBM 的手工 schedule 相比，它的价值在于通用性：不依赖某一个 code family 的几何结构，而是给出一套可迁移到多类 QECC 的自动综合流程。和 QECC-Synth 这类 layout synthesis 工作相比，它处理的是执行栈中更靠内的一层问题：code 本身不变，但 syndrome extraction 内部的执行顺序被重新优化。

## 局限性

这套方法代价不低，而且带有很强的专用化。论文在大内存多路服务器上运行 `4000-8000` 次每步 MCTS 迭代，并行调用 `stim` 做 rollout，因此它并不是一个轻量级在线调度器。输出 schedule 明确针对特定 decoder 与特定噪声模型优化，而 cross-decoder 结果也说明这种专用化不会自动迁移。AlphaSyndrome 也不联合优化 layout、routing、decoder 设计或多轮自适应控制，space-time-volume 的分析则依赖 IBM Brisbane 的时延模型而不是真机测量。

## 相关工作

- _Acharya et al. (Nature '25)_ — Google 在 rotated surface code 上的手工 schedule 是 AlphaSyndrome 需要追平的经典参考点，而论文展示了自动搜索也能达到这一水平。
- _Bravyi et al. (Nature '24)_ — IBM 的 bivariate bicycle 工作给出了另一类手工 schedule 目标，AlphaSyndrome 在论文比较中进一步超过了它。
- _Li et al. (ASPLOS '25)_ — QECC-Synth 关注的是稀疏硬件上的 QEC layout synthesis，而 AlphaSyndrome 固定 layout、优化 syndrome extraction 的内部顺序。
- _Gehér et al. (PRX Quantum '24)_ — Tangling schedules 研究了测量顺序与连通性需求的关系，而 AlphaSyndrome 直接针对带 decoder 的逻辑错误率来搜索完整 schedule。

## 我的笔记

<!-- 留空；由人工补充 -->

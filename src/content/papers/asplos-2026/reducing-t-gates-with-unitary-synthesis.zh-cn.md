---
title: "Reducing T Gates with Unitary Synthesis"
oneline: "trasyn 直接综合 `U3` 而不是先拆成三个 `Rz`，让 fault-tolerant 编译用更少的 T 门得到同等或更高保真。"
authors:
  - "Tianyi Hao"
  - "Amanda Xu"
  - "Swamit Tannu"
affiliations:
  - "University of Wisconsin-Madison, Madison, WI, USA"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3779212.3790210"
code_url: "https://github.com/haoty/trasyn"
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

这篇论文指出，现有 fault-tolerant 编译器之所以要付出过高的 `T` 门成本，很大一部分原因是把任意单量子比特操作都绕路拆成三次独立的 `Rz` 综合。`trasyn` 用张量网络引导的搜索直接综合 `U3` unitary，去掉这条绕路后，不仅 `T` count 和 Clifford 开销下降，在把 logical error 也算进去时，整条电路的最终 fidelity 往往还会更高。

## 问题背景

论文关注的是 fault-tolerant quantum computing 里一个非常硬的成本来源。在 QEC 保护下，`T` 门远比 Clifford 门昂贵，因为每个 logical `T` 都要依赖 magic-state distillation；论文把这类开销描述为相对物理门大约高两个数量级。很多有用算法又离不开任意角度的单量子比特旋转，于是编译器必须把这些旋转近似到纠错码允许的受限门集上。结果就是，`T` count 几乎直接决定了运行时间与硬件资源需求。

今天主流流程优化的是 `Rz`，而不是一般单量子比特 unitary。像 `gridsynth` 这样的数论方法，可以在给定误差阈值下为单个 `Rz` 找到最优或近最优的分解，所以实际 FT 工具链通常先把电路表示成 Clifford+`Rz` 的中间表示，再分别综合每个旋转。论文批评的是，这样做虽然算法上方便，却在结构上很浪费：一个一般的 `U3(theta, phi, lambda)` 往往要被改写成三个 `Rz` 加中间的 `H` 门，因此编译器实际上为原本一个 unitary 支付了三次 `T` 门开销。如果总误差预算固定，那三次子综合还常常要各自用更紧的误差阈值，进一步把 `T` count 推高。

那为什么不直接综合 `U3` 呢？因为 arbitrary-unitary synthesis 比 `Rz` synthesis 难得多。`Rz` 之所以适合数论技巧，是因为它有对角结构；一般 unitary 没有这个便利。已有替代方法要么靠穷举，`T` 预算稍大就完全不再可扩展；要么靠启发式搜索，而论文认为它在 early fault tolerance 关心的误差区间里既不够快，也不够稳定。所以真正的问题不是“能不能再省几个门”，而是“能不能把直接 arbitrary-unitary synthesis 做到足够实用，让 FT 编译器敢于改用更好的中间表示”。

## 核心洞察

论文最核心的观点是：只要不把候选门序列当成一张平铺开的搜索表，而是把它编码成张量网络，直接 `U3` 综合就会变得可做。`trasyn` 先离线预计算许多精确的短 Clifford+`T` 序列，把这些序列对应的矩阵堆成 tensor，再把多个 tensor 连成一个 matrix product state，用紧凑表示去隐式覆盖指数级多的长序列。把目标 unitary 接到这个结构上之后，系统就能在不逐个枚举候选序列的情况下，同时评估它们与目标之间基于 trace 的接近程度。

这件事之所以重要，有两个层面的原因。第一，它把综合问题从 brute-force 搜索改成了“按质量引导的采样”。论文把 trace 值解释成概率分布，于是高质量候选会被更频繁地采到，而不是和差解一视同仁。第二，它让编译器终于可以原生工作在 `U3` 上，这会反过来改变上游 IR 选择：相邻的旋转门，或者被可交换结构隔开的旋转门，都可以先合并成一个更丰富的单量子比特 unitary，再去做一次综合，而不是过早冻结成多个独立 `Rz` 子问题。六个月后最该记住的命题是：让 arbitrary-unitary synthesis 具备可扩展性之后，收益不只来自“综合器更强”，更来自“整个编译流程终于能选对 IR”。

## 设计

`trasyn` 可以理解成一个离线准备阶段加三个在线阶段。第 0 步是一次性的预计算：在固定 `T` budget 内，枚举所有唯一的单量子比特矩阵，并为每个矩阵保存最短的门序列表示，忽略 global phase 的差异。论文报告的唯一矩阵数是 `24 * (3 * 2^#T - 2)`，与已有理论计数在忽略 phase 变体后吻合。这个表构建起来很贵，但它的代价是“每个门集一次”，不是“每次编译一次”。

在线的第 1 步是从这些预计算 tensor 构造一个 MPS。每个 tensor 都代表一批精确的短序列，并带有受限的 `T` count。通过沿着矩阵维度把多个 tensor 串起来，`trasyn` 可以组合出更长的候选序列，而不用显式列出所有矩阵乘积。目标 unitary 被接到链的两端，随后通过一串 contraction 和 SVD，把网络变换到 canonical form，并隐式完成对每个候选 `V` 的 `Tr(U†V)` 计算。最终得到的 MPS，本质上就是一张被压缩过的“候选解质量表”。

第 2 步是在这张表上做采样。设计借用了 MPS sampling 的经典做法，把 trace 质量解释成关于 tensor 索引的联合分布。因为 canonical form 让条件概率变成局部可算，编译器就能一次决定一个 tensor 选哪段序列，投影之后继续向后采样。这里最关键的不变量是：每个采样到的索引都对应一个真实存在的预计算子序列，因此采样过程从头到尾都不会离开可行的 Clifford+`T` 搜索空间。论文还让一次遍历中取出很多样本，所以这套方法能在 GPU 上相当快地扫过很大的空间。

第 3 步是后处理。虽然每个被存进表里的短序列在本地看来已经是最优的，但多个短序列拼接之后，边界处仍可能形成一个“整体更短”的等价子序列。`trasyn` 会扫描采样出来的整条门序列，再利用预计算阶段保存的等价关系把这些局部次优片段替换掉。最外层再套一个逐步增加 tensor 数量或 `T` budget 的循环，就可以分别求解“给定 `T` budget 时误差最小”或“满足目标误差时 `T` 最小”这两类问题。

## 实验评估

论文既评估综合器本身，也评估它对应用级编译结果的影响。单量子比特综合实验里，作者从 Haar measure 均匀采样了 1000 个随机 unitary，给 `trasyn`、`gridsynth` 和 `Synthetiq` 每个目标各 10 分钟时间。在误差阈值 `0.001` 下，`trasyn` 相对“三次 `Rz` + gridsynth”流程取得了 `3.74x` 的几何平均 `T` count 降低，以及 `5.73x` 的 Clifford count 降低。散点图还显示出一个更本质的现象：在大致相同 `T` count 下，`trasyn` 常常能把 synthesis error 再降两个数量级；而在误差接近时，它通常少用大约 13 个 `T` 门。和 `Synthetiq` 相比，关键优势则是规模与稳定性：在阈值 `0.01` 时，`Synthetiq` 有 931 个实例超时；到 `0.001` 时则 1000 个实例全部超时，而 `trasyn` 对大多数实例仍能在几秒内完成。

真正让这篇论文不只是一个 synthesis microbenchmark 的，是电路级实验。作者在 187 个电路上测试了由 `trasyn` 支撑的 `U3` 工作流，数据集覆盖 FT 算法、quantum chemistry 与 material simulation、Hamiltonian benchmark，以及 QAOA。总体上，`T` count 平均降低 `1.39x`，最高达到 `3.5x`，同时 `T` depth 和非 Pauli Clifford count 也一起下降。收益最大的，是本来就包含多种旋转、能被合并成更丰富单量子比特 unitary 的电路；如果电路几乎只有 `Rz`，提升就会小得多。论文还和 `BQSKit + gridsynth` 做了比较，结论是通用数值 resynthesis 不会自动恢复 fault-tolerant 场景下真正需要的低-`T` 分解，反而常常让旋转数增加。

我认为最有意思的实验结果，是它对 fidelity tradeoff 的讨论。作者给综合后电路加入 logical error 模型，发现对 early FTQC 来说，“把 synthesis error 一路压到极低”并不是正确目标，因为更低的逼近误差通常意味着更多 `T` 门，从而暴露在更多 logical fault 下。实验显示最优 synthesis threshold 大致随 logical error rate 的平方根变化，而当 logical error rate 处于 `10^-6` 到 `10^-7` 之间时，`0.001` 左右已经足够。按这个 operating point 计算，`trasyn` 可以把总体 circuit infidelity 最多再改善 `4x`。这很有力地支撑了论文主张：降低 `T` count 不只是编译层面的漂亮数字，它可能正是 qubit-starved early FT 系统的最佳端到端工作点。

## 创新性与影响

相对于 _Ross and Selinger (QIC '16)_，这篇论文的创新点不是再把 `Rz` 的数论分解磨得更锋利，而是直接换掉问题形式，让编译器一次综合整个单量子比特 unitary。相对于 _Paradis et al. (PACMPL OOPSLA '24)_，它的贡献也不是一般意义上的启发式电路搜索，而是在单量子比特 FT 场景中给出一个明显更稳定的 tensor-guided 方法。相对于围绕 `gridsynth` 建起来、却看不见 `U3` 结构的主流 FT 工作流，论文更大的影响在于体系结构层面：一旦 direct arbitrary-unitary synthesis 变得可行，编译器就能保留更多 merge 机会，而不是过早把一个 unitary 炸成三个旋转。

因此，这篇论文最可能影响的是 fault-tolerant compiler 设计者，以及研究 early fault tolerance 的 hardware-software co-design 社群。它并没有提出新的纠错码，也没有提出新的 magic-state factory；它做的是指出 synthesis 这一层本身一直在浪费资源，而修正这一层之后，电路成本和最佳 fidelity operating point 都会跟着改变。

## 局限性

作者明确说明，`trasyn` 不是像 `gridsynth` 那样的解析式算法，因此它并不能在任意需要时持续往更小的逼近误差推进。它真正舒服的工作区间，是 early FTQC 关心的误差范围；论文也明确把 `0.001` 描述成在 `A100` 上的舒适区，而不是普适上限。这个方法还依赖很重的一次性预计算：枚举到 15 个 `T` 门的唯一矩阵，论文说在 `A100` 上就花了好几天。对固定门集来说这可以接受，但它仍然是实实在在的系统成本。

另外，方法范围目前仍局限于单量子比特综合。论文虽然提到把 `CNOT` 并入门集原则上可以推广到多量子比特 unitary，但正文评估并没有真正做到这一步。logical-error 分析也主要基于简化的 depolarizing model 和模拟，而不是完整、架构特定的 FT software stack。最后，应用级收益有一部分依赖于上游 transpilation 和 commutation pass 能把电路整理成更适合 `U3` 的形态；如果 frontend 不够强，最终能拿到的好处也会被削弱。

## 相关工作

- _Ross and Selinger (QIC '16)_ — `gridsynth` 为 `Rz` 提供了最优的 ancilla-free Clifford+`T` 综合，而本文最关键的论点正是：如果每个 `U3` 都被迫走三次这样的 `Rz` 综合，FT 工作流就会付出不必要的高代价。
- _Paradis et al. (PACMPL OOPSLA '24)_ — `Synthetiq` 同样尝试一般 unitary synthesis，但本文实验表明它的 simulated-annealing 搜索在这里目标的误差区间里不够稳定、也不够可扩展。
- _Amy et al. (TCAD '13)_ — meet-in-the-middle exact synthesis 同样搜索离散 FT 电路，但它面向的是很小规模的精确综合；`trasyn` 则用放弃精确最优性的方式换取更高 `T` budget 下的可扩展近似综合。

## 我的笔记

<!-- 留空；由人工补充 -->

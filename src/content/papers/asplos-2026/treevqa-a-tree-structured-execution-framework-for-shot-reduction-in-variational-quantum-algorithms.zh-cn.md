---
title: "TreeVQA: A Tree-Structured Execution Framework for Shot Reduction in Variational Quantum Algorithms"
oneline: "TreeVQA 先让相似 VQA 任务共享 mixed Hamiltonian 联合优化，再在轨迹分化时分裂，从而把量子 shot 数平均降到原来的 1/25.9。"
authors:
  - "Yuewen Hou"
  - "Dhanvi Bharadwaj"
  - "Gokul Subramanian Ravi"
affiliations:
  - "Computer Science and Engineering, University of Michigan, Ann Arbor, MI, USA"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3779212.3790239"
tags:
  - quantum
  - hardware
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

TreeVQA 把一个 VQA 应用看成“一组相关 Hamiltonian 的联合执行问题”，而不是很多彼此独立的小任务。它先用 mixed Hamiltonian 让相似任务共享同一段优化轨迹，只在轨迹开始分化时才拆开，最后再为每个任务挑出最优叶子状态。论文在 chemistry、physics 和 QAOA 基准上报告平均 `25.9x` 的 shot 缩减，并且在最大规模或最高精度的设置里超过 `100x`。

## 问题背景

这篇论文抓住的是 VQA 在系统层面最致命的成本来源。单个 VQA 任务本来就很贵：每次优化要做很多 iteration，每次 evaluation 又要对 Hamiltonian 的很多 Pauli term 做采样，而且为了把期望值估准，还要重复大量 shots。真正的应用通常还不是一个任务。化学里要扫很多相近的分子构型来画 potential energy surface；凝聚态物理要扫模型参数；QAOA 里的规划问题也会在不同边权场景下反复求解。

已有工作大多只优化“单任务内部”的成本。更好的 initialization 可以减少 iteration，measurement grouping 一类方法可以减少一次 Hamiltonian evaluation 里的采样开销，error mitigation 则用更多 shots 换更高精度。但这些方法没有处理更高层的冗余：同一个应用里的相邻任务往往对应非常相似的 Hamiltonian，其 ground state 和优化轨迹也常常接近。若每个任务都从头独立跑一遍 VQA，最应该共享的那段工作就被重复执行了很多次。

## 核心洞察

论文的核心判断是：许多 VQA 任务其实可以共享一大段优化前缀，因为相似的 Hamiltonian 往往对应相似的 ground state，也因此对应相似的有用 variational parameter。作者用 adiabatic continuity 来支撑这个观点：如果 Hamiltonian 的变化是平滑的，而且能隙没有闭合，那么 ground-state wavefunction 也会平滑变化。

TreeVQA 把这个物理直觉变成了一条执行规则：只要一组任务的损失趋势还保持一致，就让它们一起优化；一旦共享轨迹开始拖累某些成员，再把它们拆开。它没有直接比较量子态，而是把各个 Hamiltonian pad 到统一的 Pauli-term basis 上，用系数向量的 `L1` 距离度量差异，再通过 RBF kernel 得到 similarity matrix。论文的意思是，这个代理指标足以近似反映 ground-state 接近程度和 gradient direction 的一致性。

## 设计

TreeVQA 的运行结构由一个全局 controller 和若干 VQA cluster 组成。每个 cluster 持有一组 Hamiltonian，以及一个共享的 parameterized quantum state。它先把簇内所有 Hamiltonian pad 到统一 Pauli 集合，再取平均形成 mixed Hamiltonian。优化 mixed objective，本质上就是让一次量子执行同时为多个相近任务服务。

系统从“每个唯一初始态对应一个 cluster”开始运行，并在 cluster 内对 mixed Hamiltonian 执行常规 VQA 优化。论文重点实现的是 SPSA，但后面也展示了 COBYLA，作者的论点是 TreeVQA 只依赖 loss evaluation，因此并不绑定某个特定 optimizer。经过 warmup 之后，每个 cluster 都会维护一个 sliding window，同时跟踪 mixed loss 的 slope，以及 cluster 内每个单独 Hamiltonian loss 的 slope。如果 mixed optimization 停滞，或者某个成员的 slope 变成正值，就触发 split。

触发分裂后，TreeVQA 会在 similarity matrix 上做 spectral clustering，把当前 cluster 切成两个子 cluster。两个子簇都会继承父簇参数，所以这是 warm start，而不是从头再来。递归下去就得到论文里的树结构：根部共享最多，叶子越来越专门化。等总 shot budget 用完之后，系统再做 post-processing，把每个原始 Hamiltonian 放到所有最终叶子状态上做 classical recombination，选出能量最低的结果。对 QAOA，作者沿用同一套树式框架，只是把 ansatz 换成 multi-angle QAOA。

## 实验评估

论文的实验覆盖面足够大，基本能检验它真正主张的东西，而不只是挑一个 chemistry case 做展示。作者评估了多个分子 VQE 基准（`H2`、`LiH`、`BeH2`、`HF`、`C2H2`）、两个自旋模型（XXZ 和 transverse Ising），以及来自 IEEE 14-bus system 的 QAOA MaxCut 工作负载。baseline 是把每个任务独立执行的传统 VQA，并且和 TreeVQA 使用相同的 per-term shot 分配规则。

最核心的结果是在固定 fidelity 下显著省 shot。论文给出的总平均收益是 `25.9x`。一个很直观的例子是 `HF`：独立 VQE 要大约 `1.5e11` shots 才能把所有任务推到约 `98%` fidelity，而 TreeVQA 只用约 `4e9` shots 就达到同一水平，对应 `34.7x` 缩减。文中还报告了 `LiH` 的 `38.0x`、`BeH2` 的 `30.0x`、以及 transverse-field model 的 `43.3x`。收益较弱的案例也很说明边界：`H2` 的 UCCSD 只拿到 `5.0x`，因为问题太小；XXZ 只有 `4.1x`，因为它的优化地形更难，迫使 TreeVQA 更早分裂。

更有说服力的是，收益会在论文预期最有利的场景里继续放大。随着 task precision 提高，shot savings 会从粗粒度时的约 `5-10x` 增长到 `80-100x`，最细精度的外推结果甚至超过 `250x`。摘要还明确说，在大规模问题上收益可超过 `100x`。对 QAOA，任务之间越相似，TreeVQA 的好处越明显：图实例高度相似时 shot savings 超过 `20x`，即便边权方差增大，收益也仍然高于 `10x`。带噪声的 `LiH` 仿真里，不同 backend 仍然有 `12.0x-24.8x` 的缩减。综合来看，这组实验比较扎实地支撑了论文的主张。

## 创新性与影响

和 _Cervera-Lierta et al. (PRX Quantum '21)_ 的 Meta-VQE 相比，TreeVQA 的新意更偏系统架构，而不是重新发明一个参数化 ansatz。它保留普通 VQA 的基本形式，把创新点放在在线 clustering、动态 branching 和最终 post-processing 上，而不是把 Hamiltonian 参数直接编码进一个专门电路族。和 _Gokhale et al. (IEEE TQE '20)_ 这类 measurement reduction 工作相比，TreeVQA 是正交的：前者减少一次 Hamiltonian evaluation 的成本，后者减少很多 Hamiltonian 之间被重复执行的优化工作。和 CAFQA 这类 classical warm-start 方法相比，TreeVQA 也是可叠加的，而不是替代关系。

因此，这篇论文最可能影响的是关心 execution framework 的 quantum systems 研究者，而不只是做 ansatz 设计的人。只要未来有价值的 NISQ 或 early fault-tolerant 工作负载仍然主要以“相近参数扫描的一族任务”出现，那么这种 application-level 的共享执行层就很可能变成软件栈里的标准组成部分。

## 局限性

TreeVQA 的前提是应用里确实存在足够相似的任务。如果 Hamiltonian 很快分化，或者接近 quantum phase transition 这类会让优化地形突变的区域，树就会提前分裂，收益自然下降；论文里 XXZ 的结果本身就说明了这个边界。

方法学上也有几处限制。大部分证据来自 simulation，而不是 live hardware。大规模实验依赖 PauliPropagation，而且有些情况下 baseline 在给定预算内追不上 TreeVQA，因此未来真实硬件上的精确收益未必和论文里完全一致。warmup、slope window、split threshold 等超参数确实会影响结果，论文虽然分析了它们，但还没有把 controller 做成完全自动化。最后，QAOA 实验选择的是同构图上只变化边权的实例，这比任意组合优化工作负载更窄。

## 相关工作

- _Cervera-Lierta et al. (PRX Quantum '21)_ - Meta-VQE 同样面向一族 Hamiltonian，但它依赖把家族参数编码进专门 ansatz，而 TreeVQA 选择在线分裂执行轨迹。
- _Grimsley et al. (Nature Communications '19)_ - ADAPT-VQE 关注的是单个问题实例的电路与测量成本，而 TreeVQA 关注许多相关实例之间的重复优化。
- _Gokhale et al. (IEEE TQE '20)_ - measurement grouping 降低的是单次 VQE evaluation 的代价，TreeVQA 则通过跨任务共享优化来省 shot，两者是正交关系。
- _Bhattacharyya and Ravi (ICRC '23)_ - classical initialization 改善单个 Hamiltonian 的起点，而 TreeVQA 可以建立在这类 warm start 之上继续减少后续量子执行。

## 我的笔记

<!-- 留空；由人工补充 -->

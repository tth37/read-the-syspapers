---
title: "QOS: Quantum Operating System"
oneline: "QOS 用统一的 Qernel 抽象把误差缓解、保真度估计、兼容性感知多程序执行与调度串成量子云操作系统，在小幅牺牲 fidelity 的前提下降低排队并提高利用率。"
authors:
  - "Emmanouil Giortamis"
  - "Francisco Romão"
  - "Nathaniel Tornow"
  - "Pramod Bhatotia"
affiliations:
  - "Technical University of Munich"
conference: osdi-2025
code_url: "https://github.com/TUM-DSE/QOS"
tags:
  - quantum
  - scheduling
  - hardware
  - datacenter
category: quantum-computing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

QOS 把量子电路提升成共享的 `Qernel` 抽象，再围绕这个对象统一做误差缓解、保真度估计、兼容性感知的多程序执行，以及排队感知调度。作者在 IBM QPU 上表明，这种做法能用很小的 fidelity 代价，换来明显更低的等待时间和更高的资源效率。

## 问题背景

当前的云量子计算并不是“把作业扔给任意一台加速器”就结束了。QPU 规模小、噪声大，而且跨机器、跨 calibration cycle 都高度异构。于是量子云管理天然面临经典 CPU/GPU 调度里没有的矛盾：更大的电路和更高的占用率通常意味着更低的 fidelity，而把所有作业都送到 fidelity 最好的 QPU 又会制造严重的队列热点。今天的云接口里，这些取舍仍常常需要人工完成。

已有工作通常只修补其中一个局部，例如 circuit cutting、qubit freezing、简单的 multi-programming，或者启发式 scheduling。论文认为这是一种错误分解。缓解阶段改变了电路形态，就会改变哪些 QPU 可用、哪些作业能安全共置，进而改变排队与利用率。没有一个跨层系统，操作者只能在 fidelity、利用率和等待时间之间用彼此脱节的启发式做取舍。

## 核心洞察

论文的核心主张是，正确的管理对象不是原始量子电路，而是一个更丰富的执行对象。QOS 把它称为 `Qernel`：其中既保存 qubit 数量、depth、gate mix、SupermarQ 特征等静态属性，也保存 fidelity 估计、调度状态、后处理结果等动态状态。只要各层都围绕同一个对象读写，面向 fidelity 的策略和面向利用率的策略就能真正组合起来。

这个命题成立，是因为所有关键取舍都依赖同一组事实：电路结构、硬件校准数据和当前队列状态。如果缓解阶段缩小了电路宽度或消除了高噪声交互，那么可选 QPU 与共置安全性都会变化；如果估计器判断某台略差的机器也“足够好”，调度器就能大幅削减排队。QOS 因而把量子云管理重写成一个关于电路、校准数据和队列状态的联合优化问题。

## 设计

QOS 对上提供 `run`、`results`、`backends` 等硬件无关 API，但真正的设计重点在 API 之下。系统先把用户电路转成 Qernel，再交给四个核心组件。误差缓解器首先分析 hotspot qubit，并在预算约束下按顺序组合技术：先做 qubit freezing，再做 circuit cutting，最后在仍然装不进目标 QPU 时使用 qubit reuse。执行结束后，配套的 post-processor 再把碎片化结果重建成最终输出。

估计器负责在不真正执行电路的前提下预测 fidelity，它通过目标 QPU 的 transpilation 与校准数据给出每个 Qernel 的分数。随后，多程序执行器利用 effective utilization、compatibility score 和一到两个 qubit 的 buffer zone 判断是否值得共置；若映射重叠，则重新 transpile 并重新估计。最后，调度器根据 Qernel 最长 gate path 估计运行时间，并用公式策略或 NSGA-II 在 fidelity、waiting time 和 utilization 之间做显式权衡。

## 实验评估

实验使用真实 IBM Falcon r5.11 设备，主要是 27-qubit 的 Kolkata，累计超过 7000 次真实量子运行和 70000 个 benchmark 实例，覆盖 9 类 benchmark。动机实验已经说明为什么需要这样的系统：电路从 4 qubit 增长到 24 qubit 时，fidelity 平均下降 98.9%；同型号 QPU 间最多相差 38%；相同规模 QPU 的队列长度最多可相差 57 倍。

单层结果里最强的是误差缓解器。相对于 Qiskit、CutQC 和 FrozenQubits，QOS 在 12-qubit 电路上分别带来 2.6 倍、1.6 倍和 1.11 倍的 fidelity 提升；在 24-qubit 电路上分别达到 456.5 倍、7.6 倍和 1.67 倍。代价也真实存在：12 qubit 时经典和量子开销分别是 16.6 倍和 31.3 倍，24 qubit 时降为 2.5 倍和 12 倍。更高层结果也基本支持论文主张：估计器通常优于“总是上 Auckland”的朴素选择；在相同利用率目标下，多程序执行器可带来 1.15 倍到 9.6 倍的 fidelity 提升，而相对单独运行的平均 fidelity 损失约为 9.6%；调度器在 `c = 0.7` 时可把 waiting time 压低约 5 倍，而 fidelity 只下降约 2%，且各 QPU 负载差异控制在 15.2% 以内。评估的主要弱点在于调度层缺少可忠实复现的外部基线，因此这部分更像策略权衡展示，而不是严格的一对一比较。

## 创新性与影响

相对于 _Ayanzadeh et al. (ASPLOS '23)_ 和 _Tang et al. (ASPLOS '21)_，QOS 不是又一个孤立的缓解技巧，而是把 qubit freezing、circuit cutting 和 qubit reuse 放进统一运行时抽象。相对于 _Das et al. (MICRO '19)_，它补上了 compatibility-aware co-location、buffer zone 和 effective utilization；相对于 _Ravi et al. (QCE '21)_，它让调度成为一个已经能看到缓解结果和 fidelity 预测的软件栈层。这个架构教训对未来的量子云运行时，乃至 fault-tolerant 资源管理，都很可能有持续影响。

## 局限性

这篇论文的证据仍然受限于今天的硬件和评估方式。多数实验集中在 IBM Falcon 级别的 27-qubit 系统上，因此跨云厂商、跨架构的可移植性更多是被论证，而不是被直接展示。误差缓解在小电路上可能代价过高，若干阈值和权重也是手工调参得到，调度实验仍是基于 trace 而非在线部署。论文还主张这些思想未来可延伸到 fault-tolerant quantum computing，但本文并未真正展示那个阶段的系统行为。

## 相关工作

- _Ayanzadeh et al. (ASPLOS '23)_ - FrozenQubits 通过冻结 hotspot node 提升 QAOA fidelity，而 QOS 把 qubit freezing 作为更大预算式缓解流水线中的一个阶段。
- _Tang et al. (ASPLOS '21)_ - CutQC 用 circuit cutting 在小硬件上执行更大的量子电路，而 QOS 把 cutting 作为操作系统栈中的一个可组合机制。
- _Das et al. (MICRO '19)_ - A Case for Multi-Programming Quantum Computers 研究量子作业共置，而 QOS 增加了 compatibility scoring、buffer zone 和 effective utilization。
- _Ravi et al. (QCE '21)_ - Adaptive Job and Resource Management for the Growing Quantum Cloud 聚焦量子作业调度，而 QOS 把调度与误差缓解和 fidelity 估计整合在同一系统中。

## 我的笔记

<!-- 留空；由人工补充 -->

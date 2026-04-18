---
title: "Reconfigurable Quantum Instruction Set Computers for High Performance Attainable on Hardware"
oneline: "ReQISC 通过把时间最优的 SU(4) 门控、编译优化与路由联动起来，让连续量子 ISA 真正变成可落地的硬件接口。"
authors:
  - "Zhaohui Yang"
  - "Dawei Ding"
  - "Qi Ye"
  - "Cupjin Huang"
  - "Jianxin Chen"
  - "Yuan Xie"
affiliations:
  - "The Hong Kong University of Science and Technology, Hong Kong"
  - "Fudan University, Shanghai Institute for Mathematics and Interdisciplinary Sciences, Shanghai, China"
  - "Tsinghua University, Beijing, China"
  - "DAMO Academy, Alibaba Group, Bellevue, WA, USA"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3779212.3790208"
project_url: "https://zenodo.org/records/18163249"
tags:
  - quantum
  - hardware
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

ReQISC 的核心论点是：量子硬件不该继续被 CNOT 这一种两比特指令绑死，但更丰富的 ISA 只有在控制、校准、编译和路由一起重做时才真的有价值。它的做法是把完整的 `SU(4)` 作为 ISA，在任意两比特耦合哈密顿量下以理论最优时间实现任意两比特门，再用专门的编译与映射流程把这种表达能力兑现成整程序级别的缩减。

## 问题背景

这篇论文抓住的是量子系统里一个很典型的错位。硬件平台越来越常暴露出比 CNOT/CZ 更丰富的原生两比特相互作用，已有工作也表明，更强的基门通常能降低程序综合时所需的纠缠门数量。但这些理论收益很少能直接落到真实系统里。原因并不神秘：每多一种原生两比特门，校准负担就更重；连续门族的控制方式往往复杂而且依赖特定硬件；主流编译器则仍把这些更丰富的 ISA 当作局部小技巧，而不是整条软件栈的中心抽象。

所以真正的瓶颈是跨层的。更强的 ISA 只有在三个条件同时成立时才有意义。第一，硬件必须能用短而高保真的脉冲，直接实现任意或接近任意的两比特门，而不是退回到冗长拼接。第二，校准成本必须可控，否则 ISA 再漂亮也只是论文里的概念。第三，编译器必须能在真实程序上把这些表达能力变成更少的两比特门、更浅的深度、更低的路由开销和更短的运行时间，而不是只在单个 gate synthesis 例子上好看。论文的判断是，过去工作通常只解决了其中一两层，因此 CNOT 风格的编译流程仍然占主导。

## 核心洞察

作者最重要的洞察是：完整 `SU(4)` 空间之所以能变得“实用”，不是因为我们突然多了很多酷炫门型，而是因为它可以被当成一种可重构机器接口。任意两比特酉变换在忽略局部单比特旋转后，都能化约为 Weyl chamber 里的一个点。ReQISC 就把这个几何表示变成编译器与微架构之间的共同契约：编译器输出规范化的 `SU(4)` 指令，控制层则负责把硬件驱动到对应的 Weyl 坐标，并保证时间最优。

这个抽象之所以站得住，是因为论文同时补上了两个最容易把它拖垮的现实问题。第一是硬件普适性。ReQISC 的门控方案不局限于纯 `XY` 耦合，而是能处理任意规范化的两比特耦合哈密顿量。第二是 near-identity 门的控制奇异性。某些非常靠近恒等门的 `SU(4)` 指令若直接按最优时间执行，会要求近乎无界的脉冲幅值。ReQISC 不去硬扛，而是在编译期把它们镜像到 SWAP 角附近，再把由此带来的 qubit 重映射交给编译器处理。这样既避开了物理上不可接受的控制点，也尽量不增加额外两比特门数。

## 设计

ReQISC 可以分成两层来看。第一层是微架构，本质上是一套面向任意两比特指令的脉冲生成与控制逻辑。给定目标酉变换和设备的耦合哈密顿量后，系统先通过 KAK 分解提取 Weyl 坐标，再在三种执行子模式中选一种：no-detuning (`ND`)、equal-amplitude-plus (`EA+`) 或 equal-amplitude-minus (`EA-`)。每种模式最终都只需求解一小组控制参数，包括局部驱动幅度、共享 detuning 和门时长。论文最关键的系统结论是，这套逻辑既统一又时间最优：不管底层是 `XY`、`XX` 还是更一般的耦合，都可以用同一套解码流程命中理论下界。

第二层是编译器，这也是 ReQISC 不只是“更好的脉冲控制”而是真正系统工作的原因。对于由 `CX`/`CCX`/`MCX` 一类结构化片段构成的量子程序，ReQISC 先做 program-aware 的模板综合，把细化后的三比特 IR 重写为预先综合好的 `SU(4)` 模板。随后它执行 hardware-agnostic 的 hierarchical synthesis：把电路切成 `SU(4)` 块，对紧凑的三比特区域按条件做近似综合，并用一个基于 approximate commutation 的 DAG compacting pass 创造更好的局部优化机会。最后，在拓扑受限设备上它用 mirroring-SABRE 做映射，这是 SABRE 的一个变体，会优先选择那些能被邻近 `SU(4)` 门“吸收”的 SWAP。

校准也被明确纳入设计，而不是事后补丁。ReQISC 提供 "Eff" 和 "Full" 两种编译模式：前者跳过最激进的局部综合，以保持极低的不同 `SU(4)` 门型数量；后者则接受更高的校准负担，换取更多门数下降。对于 variational 程序，作者也没有回避问题，而是明确建议退回到固定两比特门族加参数化单比特门的实现路径，避免每次运行都重新校准任意 `SU(4)` 指令。

## 实验评估

微架构层面的结果很扎实，而且很好解释。在 `XY` 耦合下，ReQISC 综合 Haar-random `SU(4)` 的平均脉冲时长只有 `1.341 g^-1`，而传统基于 CNOT 的实现需要 `6.664 g^-1`，也就是 `4.97x` 的缩短。这个优势在 `XX` 耦合和随机耦合下也依然存在，所以论文“适用于任意耦合”的说法不是只在一个偏爱的哈密顿量上成立。

编译层面，作者在 `17` 个类别、`132` 个基准上对比了 Qiskit、TKet、BQSKit 以及若干 SU(4) 增强变体。ReQISC-Full 平均把两比特门数降了 `51.89%`，两比特深度降了 `57.5%`，脉冲时长降了 `71.0%`；ReQISC-Eff 也还能带来 `68.03%` 的平均时长缩减。这些数字明显大于各类基线，说明优势不只是“SU(4) 比 CNOT 强”，而是编译器的专门优化真的在起作用。消融实验也支持这一点：去掉 DAG compacting 会显著变差，而 BQSKit-SU(4) 虽然能降一些门数，却会引入失控的不同门型数量，使校准几乎不可收拾。

硬件约束下的结果同样有说服力。加入路由后，ReQISC 在 1D chain 和 2D grid 上的几何平均开销分别是 `1.36x` 和 `1.09x`，而 CNOT 风格编译对应的是 `2.45x` 和 `1.79x`。在十二个基准上的 noisy simulation 中，ReQISC 不只是更快，也更准：在逻辑层面平均有 `2.36x` 的误差下降和 `3.06x` 的加速；映射到受限拓扑后，误差下降大约扩大到 `3.18x-3.34x`，速度提升扩大到 `4.30x-4.55x`。校准权衡看起来也不是空话：ReQISC-Eff 的不同 `SU(4)` 门型数低于 `10`，ReQISC-Full 低于 `200`，而且超过四分之三的 Full 编译程序最终仍少于 `20` 种不同两比特门。

## 创新性与影响

和 _Chen et al. (ASPLOS '24)_ 相比，ReQISC 的前进一步不只是“又一种连续门族”，而是把原本偏 `XY` 的门控思路推广到任意耦合哈密顿量，并围绕它补上整套编译与路由流程。和 _Huang et al. (PRL '23)_ 相比，后者强调“更好的两比特基门确实重要”，而 ReQISC 则把这个想法推到极致，直接把完整 `SU(4)` 暴露为机器接口。和 `Qiskit`、`TKet`、`BQSKit` 这类主流流程相比，这篇论文最重要的贡献是架构性的：它把 ISA 设计、脉冲控制、编译优化和拓扑映射当成一个共同设计的问题。

因此，这篇论文最可能影响的是量子硬件软件协同设计，而不只是量子编译器子领域。如果未来硬件平台真的能以足够低的成本校准连续门族，ReQISC 提供的是一条从物理控制一直通到程序优化的完整蓝图。

## 局限性

最大的局限在于，大部分证据仍来自模拟与模型，而不是一套在真实量子芯片上端到端部署的系统。论文引用了先前实验来说明类似门型可以被高保真实现，它自己的控制方案在解析上也很扎实，但 ReQISC 本身并没有以完整生产栈的形式在真实硬件上跑出这些结果。因此，校准成本和并行串扰到底能否像论文设想得那样可控，目前更像是很强的可行性论证，而不是已经尘埃落定的工程事实。

它也有明显的工作负载边界。program-aware synthesis 特别适合由 `CX`/`CCX`/`MCX` 这类结构化片段构成的程序；对于 variational 程序，作者自己也承认必须走更保守的实现路径，避免连续 `SU(4)` 的重复校准。ReQISC-Full 还会主动拿更多校准复杂度去换更低门数；即便实验里不同门型数量还算温和，一些实验室也可能仍然更偏好更保守的 Eff 配置。更广义地说，保真度实验采用的是随时长线性缩放的 depolarizing 模型，所以它证明的是“更短的门在标准噪声抽象下更有利”，而不是穷尽了所有平台相关误差机制。

## 相关工作

- _Chen et al. (ASPLOS '24)_ — AshN 证明了在 `XY` 耦合下，精简连续 ISA 可以做到时间最优；ReQISC 把控制方案推广到任意耦合，并补齐端到端编译与路由。
- _Huang et al. (PRL '23)_ — Quantum Instruction Set Design for Performance 说明更好的原生两比特门会改变综合成本，而 ReQISC 直接把这种思路扩展成完整的 `SU(4)` 机器接口。
- _Lin et al. (MICRO '22)_ — 这类工作是在既有原生门集合上做硬件感知的 basis 选择，而 ReQISC 试图把原生接口本身重塑为任意 `SU(4)` 可实现。
- _McKinney et al. (HPCA '24)_ — MIRAGE 用 mirror gate 改善固定替代门集下的分解和路由；ReQISC 里的 mirroring 则服务于另一件事，即规避 near-identity `SU(4)` 门的控制奇异性。

## 我的笔记

<!-- empty; left for the human reader -->

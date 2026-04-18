---
title: "PrioriFI: More Informed Fault Injection for Edge Neural Networks"
oneline: "PrioriFI 先用 Hessian 建立位级先验，再用注入过程中的实时反馈重排后续翻转顺序，更快找出边缘 NN 中最脆弱的参数位。"
authors:
  - "Olivia Weng"
  - "Andres Meza"
  - "Nhan Tran"
  - "Ryan Kastner"
affiliations:
  - "University of California San Diego, La Jolla, CA, USA"
  - "Fermi National Accelerator Laboratory, Batavia, IL, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790204"
code_url: "https://github.com/KastnerRG/priorifi"
tags:
  - hardware
  - ml-systems
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PrioriFI 是一个面向量化边缘神经网络的 fault-injection 调度器。它先用 Hessian 建立排序先验，再根据已经观察到的任务损伤动态重排后续 bit flip。这样能比 BinFI、StatFI 和纯 Hessian 排名更早找出高敏感度的 weight / bias bits。

## 问题背景

论文面向的是那类“错误代价非常真实”的边缘部署。作者的核心例子是 HL-LHC 上的 `ECON-T` ASIC：每个神经网络必须在 `25 ns` 内完成推理，面积预算约 `4 mm^2`，还要承受论文所说比太空高 `1000x` 以上的辐射环境。在这种系统里，设计者不能把所有参数位都同样加固，必须先知道哪些位真的危险。

穷举式 single-bit fault injection 虽然准确，但太贵了。即使是小型 fixed-point 模型，也有成千上万到几十万候选 bits，而每次注入后都要重新跑很多验证样本。此前的加速方法大多依赖 bit-level monotonicity，即“高位至少不比低位更安全”。PrioriFI 的反驳是，这只是倾向，不是规律。论文在九个模型上统计到 `15%` 的参数内单调性违例和 `80%` 的跨参数违例。只要这种例外足够多，基于单调性的搜索就会把注入预算花错地方。

## 核心洞察

论文最重要的判断是：bit 敏感度应该在线更新，而不是一次性静态排完。Hessian 适合做初始先验，因为它能反映参数的重要性；但 campaign 真正开始后，更有价值的是已经观测到的 `ΔC`。PrioriFI 因此持续观察最近哪一类 significance level 更容易造成任务损伤，并把后续注入转向那里。

这对 inter-parameter exceptions 尤其重要。假如最近若干个 `MSB-1` 的伤害已经超过下一个还没测的 `MSB`，PrioriFI 会立刻改道，而不是继续盲信单调性。它不是去证明顺序，而是在顺序出错时快速纠偏。

## 设计

PrioriFI 使用标准的 single-bit-flip 模型，目标是 weights 和 biases。它的任务级敏感度指标是 `ΔC = max(C_faulty - C_faultless, 0)`：分类任务里，`C` 是 misprediction 数量；`ECON-T` 里，`C` 是用 Earth Mover's Distance 表示的重构损失。

算法分两步。先用 Hessian 排参数，再按 significance 拆成多条列表：所有 `MSB` 一条，所有 `MSB-1` 一条，一直到 `LSB`，每条列表内部仍按 Hessian 排序。接着，先从每条列表头部各翻一个 bit，拿到初始 `ΔC`。之后进入 priority-guided phase：对每条列表计算最近 `k` 次 `ΔC` 的中位数，哪条列表的近期中位数最高，就从那条列表继续翻下一个 Hessian 排名最高的 bit。

这个设计保留了 Hessian 初始化的好处，同时把真实注入中暴露出来的非单调行为吸收到后续决策里。它也避免了 BinFI 那种“根据已翻 bit 去推断未翻 bits 状态”的风险，因此不会累积 false positives 或 false negatives。PrioriFI 本质上不是新的保护机制，而是给更大的 power-performance-area-reliability 权衡提供更可信的敏感度画像。

## 实验评估

作者评估了九个 fixed-point edge models：`HGCal` 上的三种 `ECON-T` 自编码器、三种 `SmartPixel` 分类器和三种 `CIFAR-10` 模型，规模从 `825` bits 到 `944,208` bits，量化位宽覆盖 `3` 到 `8` bits。关键在于，每个模型都先跑了一遍穷举 single-bit FI，得到真正的 Oracle 排名，因此论文可以严格比较各种加速方法离理想顺序还有多远。

PrioriFI 在九个模型中的七个上是最好的近似排名。它相对 Oracle 的归一化 AUC 在所有模型上都达到 `0.93` 以上，并且在最不单调的 `SmartPixel` 模型上优势最明显：`SmartPixel-L` 上是 `0.97` 对 `0.87`，`SmartPixel-M` 上是 `0.94` 对 `0.88`。而在更接近单调的 `CIFAR-10` 模型上，提升较小，这和论文的 monoscore 分析是一致的。

时间结果也很实在。PrioriFI 在 `SmartPixel-M` 上达到总累计敏感度 `50%` 的速度，比 Hessian 快 `43%`；在 `CIFAR-10-M` 上仍快 `14%`，节省 `1 hour 37 minutes`。初始化成本对大多数模型都不到完整 campaign 的 `1%`。另外，PrioriFI 因为显式翻转 bits，所以没有 false positives 或 false negatives；相对地，论文报告 `StatFI` 在 `ECON-T-M` 上有 `31.3%` 的 false negatives，在 `CIFAR-10-M` 上达到 `66.5%`。如果排序结果会被拿去指导硬件保护，这种漏报会非常危险。

## 创新性与影响

和 _Chen et al. (SC '19)_ 相比，PrioriFI 的关键新意是放弃把单调性当成硬规则。和 _Ruospo et al. (DATE '23)_ 相比，它说明了为什么 magnitude-based sampling 在量化 edge model 上并不是可靠 proxy。和 Hessian-guided 方法相比，它真正新增的是会随着证据持续重排的自适应闭环。

这让它同时对 dependable ML 研究者和 edge hardware 设计者有价值，尤其适合那些需要决定 parity、`TMR` 或 selective protection 到底值不值得花面积的人。它的贡献是把可靠性刻画变成可行动的设计输入。

## 局限性

论文也很清楚，PrioriFI 仍然是一种 FI campaign，而不是闭式捷径。它缩短的是“先找到关键 bits”的时间，但完整 campaign 依然昂贵，Oracle 也只适合离线分析。它的故障模型也比较窄，只覆盖 weight / bias 上的 single-bit flip，没有研究 multi-bit corruption、activation faults 或更广义的硬件失效。

另外，它的收益强烈依赖模型本身有多不单调。`CIFAR-10` 模型更接近单调，因此 PrioriFI 相对 Hessian 的提升有限。作者也明确承认，当前的 `medianLastK` 仍然达不到 Oracle，后面还有优化在线排序启发式的空间。

## 相关工作

- _Chen et al. (SC '19)_ — BinFI 在单调性假设下用二分搜索加速 FI，而 PrioriFI 选择显式翻转 bits，并在假设失效时动态纠偏。
- _Ruospo et al. (DATE '23)_ — StatFI 根据预期的 magnitude swing 做统计采样；PrioriFI 则直接测量任务级损伤，并说明为什么幅值变化对量化 edge NN 并不可靠。
- _Schmedding et al. (ISSRE '24)_ — Aspis 用 gradient / Taylor 一类轻量 proxy 来指导保护，而 PrioriFI 仍然停留在真正的 FI 范式中，输出的是 bit-level 的真实排序。
- _Reagen et al. (DAC '18)_ — Ares 是更通用的 DNN resilience framework，而 PrioriFI 专注于小型 fixed-point edge models 上如何高优先级地安排 FI。

## 我的笔记

<!-- 留空；由人工补充 -->

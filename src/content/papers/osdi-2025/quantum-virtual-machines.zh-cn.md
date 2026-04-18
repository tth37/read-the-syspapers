---
title: "Quantum Virtual Machines"
oneline: "HyperQ 把量子硬件抽象成架构相关的 qVM，并在空间与时间上做装箱调度，让云端量子机能并发执行多个彼此隔离的程序。"
authors:
  - "Runzhou Tao"
  - "Hongzheng Zhu"
  - "Jason Nieh"
  - "Jianan Yao"
  - "Ronghui Gu"
affiliations:
  - "University of Maryland, College Park"
  - "Columbia University"
  - "University of Toronto"
conference: osdi-2025
code_url: "https://github.com/1640675651/HyperQ"
tags:
  - quantum
  - virtualization
  - scheduling
category: quantum-computing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

HyperQ 把量子处理器拆成一组 quantum virtual machines（qVM），其拓扑直接对应底层芯片里重复出现的物理区域。量子程序先各自针对 qVM 独立编译，随后 HyperQ 再通过空间和时间复用把多个 qVM 打包进一个复合电路中执行。在 IBM 的 127-qubit Eagle 硬件上，这种做法显著提升了吞吐、利用率和用户看到的延迟，同时保持了结果保真度，某些情况下甚至还能更好。

## 问题背景

今天的量子云服务基本把整台机器当成最小调度单位。用户提交一个电路，这个电路就独占整台量子机直到结束，然后下一个作业才能运行。问题在于，大多数 NISQ 工作负载实际上只使用全部 qubit 里的很小一部分，却仍然阻塞所有其他租户。论文认为，这种低利用率在量子云里尤其严重，因为公开可用的机器数量很少、需求很高，用户往往要等上几天才能拿到结果。

表面上的补救办法是让多个电路同时跑，但这并不容易。已有量子 multiprogramming 工作大多依赖自定义编译器，在编译期直接把多个电路融合起来，因此系统必须事先知道到底哪些程序会一起执行。这破坏了独立编译，也难以扩展，而且还放弃了 Qiskit 这类标准编译栈里已经很成熟的优化。另一方面，现有量子硬件没有 QRAM，也就没有经典系统那种可抢占的保存/恢复上下文能力。HyperQ 因而必须在不引入新编译栈、也不假设硬件支持量子上下文切换的前提下完成复用。

## 核心洞察

论文最关键的判断是，量子虚拟化应该围绕真实芯片已经暴露出的重复物理结构来定义。以 IBM Eagle 为例，它由重复出现的 7-qubit I 形区域构成。如果 HyperQ 把一个 qVM 定义成这样一个区域，或者定义成若干区域按固定矩形方式组合起来的形状，那么一个面向 qVM 编译好的电路，之后就可以通过简单的 qubit 重标号被迁移到真实芯片上任意匹配的位置，而不需要重新编译。

这种物理拆分还天然提供了可操作的隔离边界。只要保证不同 qVM 的 qubit 之间不存在直接连接，HyperQ 就能降低并发执行程序之间的 crosstalk。这样得到的虚拟化抽象，已经足够接近经典系统里对效率、资源控制和等价性的要求：编译后的指令仍然直接在硬件上执行，HyperQ 保留对放置和资源的控制，而用户则继续用现有框架写普通量子程序即可。

## 设计

HyperQ 把每个 qVM 暴露成一个 virtual backend，接口形式和真实量子后端一样，都包含 coupling map 和 gate set。对 IBM 硬件而言，基本 qVM 是一个 7-qubit 的 I 形区域，正好与较小的 Falcon 机器拓扑一致。HyperQ 还定义了 scaled qVM，即把多个基本区域按 m x n 方式拼起来并加上连接 qubit；对于特别小的程序，还支持 fractional qVM。编译阶段里，HyperQ 先检查程序需要多少 qubit，选择能容纳它的最小 qVM 形状，再让 Qiskit 面向这个 virtual backend 做编译。这样一来，程序仍然享受标准的 routing 和 gate decomposition，而不是被迫使用专门为 multiprogramming 设计的编译器。

调度被拆成空间调度和时间调度两步。空间调度器是一个按 FIFO 顺序运行的贪心装箱器：它按到达顺序扫描作业，把每个作业放到当前最靠左上、且兼容的空闲区域中。它还有一个 noise-aware 变体，会利用硬件每天更新的校准数据给基本区域打分，尽量避开最差的区域，并把更能容忍噪声的作业放到低质量区域。时间调度器则进一步填补不同电路长度造成的空隙。它根据关键路径上的 gate delay，再加上 mid-circuit measurement 和 reset 的代价来估算执行时间，然后把后续 qVM 追加到那些不会超过当前最长区域时长的区域尾部。

批次选好之后，HyperQ 会把它聚合成一个可直接执行的复合电路。它先把每个 virtual qubit 翻译成被分配到的 physical qubit，再把 qVM 中无方向的边调整成目标区域实际需要的有方向 gate 方向；如果某个区域在时间上被复用，还会插入 reset 和 barrier。所有子电路随后被串接成一个大电路，并作为普通作业提交给云服务。执行结束后，HyperQ 再按事先维护的 classical bit 映射，把结果拆回每个 qVM。对于那些中途 measurement 或 reset 太多的异常电路，HyperQ 会把它们单独拿出来，避免它们扰动同批其他程序。

## 实验评估

实现基于 IBM Quantum Platform 和 Qiskit，实验跑在公开可用的 IBM Brisbane，也就是一台 127-qubit Eagle 机器上。工作负载来自 QASMBench：`small-only` 基准共 145 个作业，`small&med` 共 196 个作业。每个作业默认执行 4000 shots。论文比较了四种配置：原始的 IBM Quantum、只做空间调度的 HyperQ、做空间加时间调度的 HyperQ，以及带 noise-aware 放置的 HyperQ。

最核心的性能结论是，复用并不是纸面概念，而是在真实机器上有量级收益。对于 all-at-once 到达模型，带空间加时间调度的 HyperQ 在 `small-only` 上把吞吐提升了 9.7x，在 `small&med` 上提升了 4.9x；利用率则分别提升 11x 和 5.8x。换成 Poisson 到达模型后，提升会小一些，但吞吐和利用率仍有大约 3.2x 到 3.6x 的改善。用户可感知的延迟下降更加明显。在论文采用的“初始队列为空、忽略其他用户作业”的模型下，Poisson 到达时平均延迟在 `small-only` 上下降了 43x，在 `small&med` 上下降了 26x，因为当前云服务里的主要等待成本本质上就是前面那些整机独占作业排队清空的时间。

保真度同样是实验重点。论文在 small benchmark 上使用和理想模拟器之间的 L1 distance 来衡量结果质量。只做空间调度时，HyperQ 的平均保真度几乎与 IBM Quantum 完全一致；在 Poisson 到达下，noise-aware 模式还能把平均 L1 从 0.55 改善到 0.50，其中数值越低越好。时间复用的平均噪声会更高一些，因为当下的 mid-circuit measurement 和 reset 仍然比较昂贵，但即便如此，其平均值仍明显低于论文给出的 L1 = 1 这一“至少超过一半正确”的粗阈值。论文还专门做了一个 crosstalk 实验：两个程序若放在直接相邻的 qubit 上，并发执行的正确率会从 85% 掉到 81%；中间隔开一个未使用 qubit 后，成功率又回到 85%，与单独运行一致。

## 创新性与影响

相对于 _Das et al. (MICRO '19)_ 和 _Liu and Dou (HPCA '21)_ 这类先前工作，HyperQ 改变的是抽象边界。那些系统主要把 multiprogramming 看成编译期的电路合成或映射问题；HyperQ 则引入了架构相关的 qVM 抽象，保留独立编译，并把组合推迟到运行时调度中完成。这是一种系统层的新机制，而不是仅仅更好的 mapper。

它的潜在影响首先会落在量子云 runtime 设计上。只要公开量子服务仍然需要把稀缺且带噪的设备暴露给大量用户，那么调度、隔离和弹性 right-sizing 就会和编译质量一样关键。HyperQ 证明，即便在今天硬件能力受限的前提下，也已经可以用类似 VM 的软件层，把量子云从“单用户批处理队列”往“可复用的多租户服务”方向推进。

## 局限性

HyperQ 依赖硬件具有较强的结构规律性。它构建 qVM 的方法假设机器可以被分解成重复区域，并且这些区域之间的连接方式足够规则；这对论文评估的超导设备成立，但对未来所有量子架构未必都成立。论文在时间调度上也假设电路结构是静态的，可以据此预估执行时长；若后续硬件支持更丰富的动态电路和控制流，这种估计可能会变得不准确。

此外，它也有现实代价。由于当前机器没有 QRAM，HyperQ 无法像经典虚拟机那样抢占并恢复任意量子态，只能在执行前把完整电路组合好再一次性提交。时间调度依赖 mid-circuit measurement 和 reset，而实验已经显示这些操作目前仍会引入可见噪声。最后，利用率还受 external fragmentation 限制：在 Eagle 上，即使 9 个基本 qVM 区域全部占满，HyperQ 的隔离布局最多也只能使用 127 个 qubit 中的 85 个。实验范围同样有限，主要集中在 IBM Brisbane 和 QASMBench 风格工作负载上，跨硬件家族的证据仍然不足。

## 相关工作

- _Das et al. (MICRO '19)_ - 该工作提出了量子计算机上的编译期 multiprogramming，而 HyperQ 保持独立编译，并通过 qVM 运行时调度来组合作业。
- _Liu and Dou (HPCA '21)_ - QuCloud 主要关注云环境下多程序执行时的 qubit mapping，而 HyperQ 进一步提供了完整的虚拟化接口、时间复用和结果拆分机制。
- _Niu and Todri-Sanial (DATE '22)_ - 这项工作讨论了并行电路执行在 NISQ 系统中的价值，而 HyperQ 则把这一想法落成了与现有云服务兼容的运行时系统。
- _Murali et al. (ASPLOS '20)_ - 该工作用 noise-adaptive mapping 为单个电路挑选更好的 qubit；HyperQ 则把类似思路扩展到区域级放置，用于多个并发 qVM。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "SEVI: Silent Data Corruption of Vector Instructions in Hyper-Scale Datacenters"
oneline: "SEVI 在超大规模数据中心上实测向量指令 SDC，并把 matmul 改造成带 ABFT 校验的在线探针，以约 1.35% 开销检测多数故障机器。"
authors:
  - "Yixuan Mei"
  - "Shreya Varshini"
  - "Harish Dixit"
  - "Sriram Sankar"
  - "K. V. Rashmi"
affiliations:
  - "Carnegie Mellon University, Pittsburgh, PA, USA"
  - "Meta Platforms Inc., Menlo Park, CA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790217"
code_url: "https://github.com/Thesys-lab/SEVI-ASPLOS26"
tags:
  - hardware
  - datacenter
  - observability
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

SEVI 在一个足够大的生产 CPU 机群上系统性研究了向量指令中的 silent data corruption，因此原本“极罕见”的故障终于能被当成可测量现象来分析，而不只是零散事故。论文最重要的结论有两个：第一，FMA 指令几乎主导了观测到的向量 SDC；第二，把一个便宜的 ABFT 校验嵌入 matrix multiplication 后，可以在 `1024 x 1024` 矩阵上仅增加约 `1.35%` 开销，就检测到大多数故障机器。

## 问题背景

这篇论文针对的是超大规模基础设施里一个很难处理的可靠性漏洞。SDC 最麻烦的地方不在于它会让程序崩溃，而在于它不会崩溃：硬件直接产出错误结果，软件继续往下运行，错误值再一路传播到上层状态。在单机视角里，这种事情频率低得像噪声；但在数据中心规模下，累计故障率已经足够影响生产。此前的研究要么是个案分析，要么是更宽泛的 fleet 统计，要么依赖模拟器中的 fault injection，因此我们仍然缺少一个关键答案：究竟哪些向量指令最危险，这些错误具体以什么模式出现，以及如何在不付出巨大纯测试开销的前提下持续检测它们。

作者把焦点放在向量指令上是有充分理由的。论文指出，向量指令约占 AI 工作负载计算指令的 `80%`，也占多类超大规模服务中约 `50%` 的执行驻留时间。也就是说，真正的问题不是“CPU 是否会发生 SDC”，而是“哪些向量操作是机群里的主要风险来源，它们的故障形态是什么，以及我们能否把一个常见生产算子变成廉价的在线探针”。如果答案仍然只是依靠长时间、专门化、脱离业务的 fleet tests，那么得到覆盖率的代价就是持续的纯额外成本。

## 核心洞察

论文的核心判断是，向量指令 SDC 在真实机群中既足够集中，又足够有结构，因此可以针对性检测，而不必做一个对所有故障一视同仁的通用方案。作者的数据表明，大多数观测到的 SDC 都来自 FMA 指令；大多数错误局限在单个物理核心上，甚至通常只影响一个 vector lane；很多 matrix multiplication 里的应用级错误，又和 FMA 级别的错误高度一致。这意味着，只要选对一个广泛使用且高度依赖向量运算的 kernel，它就可以代表性地覆盖掉问题中的大头。

第二个洞察是，这个探针不需要完整复制原始工作负载。Matrix multiplication 自带一个很强的代数不变量：输出矩阵所有元素之和，等于矩阵 `A` 的行校验向量与矩阵 `B` 的列校验向量的点积。计算这些 checksum 的成本远小于重算整个乘法，但一旦发生 SDC，错误同时把两边都扰动成同一个错误值的概率又很低。于是，论文把 ABFT 从传统 HPC 的容错技巧，转成了一个可以在生产数据中心持续运行的 fleet canary 机制。

## 设计

SEVI 的研究方法分成两个阶段。第一阶段，Meta 的基础设施在整个生产 fleet 里持续筛选“SDC Suspects”。它一方面在维护窗口做 out-of-production 测试，另一方面把轻量 in-production 测试与正常业务共置运行；测试来源既包括厂商套件，也包括十六类生产工作负载中的代码片段。被怀疑有问题的机器不会立刻下线，而是先被虚拟打标，方便后续做长时间保留测试；与此同时，这些机器仍继续承载和其他生产机器相同的软件栈与工作负载。

第二阶段，作者对所有 suspect 机器做深度测试。指令级套件包含 `246` 个 AVX2、FMA3、BMI1 和 BMI2 测试用例，每个用例只隔离一条指令，并在每个逻辑核心上运行 `1` 百万轮，再完整重复两次，最后再做一轮所有 lane 输入一致的测试。全部加起来超过 `78` 万亿轮、`140` 亿 CPU 秒。应用级测试则用 NumPy matmul，覆盖有界与无界浮点输入以及不同矩阵维度上界，再增加 `430` 亿轮和 `25` 亿 CPU 秒。这样的设计既保留了 fleet 规模，又把单机驻留时间拉长到足以暴露低于 `10^-5` 的稀有故障。

检测机制建立在同样的 matmul 事实上。对 `A x B`，SEVI 先计算 `A` 的行 checksum、`B` 的列 checksum，再把两者点积与输出矩阵元素总和比较。论文建议对大矩阵做 tile 级校验，以免单个错误元素在全局和中被过度稀释。评估阶段为了拿到 ground truth，作者用 scalar 重算做验证；但真正可部署的路径是轻量 checksum，而不是完整复制。

## 实验评估

指令级结果是这篇论文最扎实的部分。SEVI 一共观测到 `28` million 次 SDC incident，归并成 `400` 个 SDC case，对应约 `0.072‱` 的 fleet-level vector-SDC machine rate。`246` 个指令测试里，只有 `75` 个真正发现过 SDC，而且这些 case 只分布在 arithmetic、FMA、gather 与 permute 四类指令中。FMA 占绝对主导：它贡献了超过 `75%` 的 SDC case 和超过 `92%` 的 incident。论文还给出了很有价值的形态细节：内存访问类 SDC 大约 `76%` 是读到了错误 offset，`24%` 是读到损坏数据；全部向量 SDC incident 中有 `98.5%` 只影响单个 lane。这些结果不是花边观察，而是后面 canary 设计成立的经验基础。

应用级分析把这个故事往真实 workload 推进了一步。作者在 matmul 中观测到 `292K` 次 incident，分布于 `12` 台机器上的 `24` 个 SDC case，约对应 `0.048‱` 的 fleet-level 机器率。其中 `10` 个 case 出现在同时也有 FMA SDC 的核心上，而且 matmul SDC 频率与 FMA SDC 频率的 Pearson 相关系数达到 `0.979`，非常有力地支持了“应用级错误主要由 FMA 故障驱动”这一判断。错误严重程度也并不温和：多数错误输出的相对误差低于 `1`，但仍有明显长尾可以高到 `10240`，因为 exponent bits 也会翻转，这直接推翻了“浮点 SDC 大多只碰 mantissa 低位，所以影响有限”的乐观假设。

ABFT 的结果则说明这件事不只是测量，更有部署价值。对无界浮点输入、最大维度 `10` 的矩阵，方法能检测到 matmul 研究里发现的全部故障核心。最大维度升到 `25` 时覆盖率仍有 `94%`，到 `100` 时还有 `88%`；若输入有界，则能检测 `23` 台故障机器中的 `21` 台，并在被捕获机器上覆盖约 `99%` 的 incident。超过 `80%` 的核心能在 `21` 秒内看到第一次 ABFT 告警。开销也足够低：小矩阵约 `11%`，而在 `1024 x 1024` 时降到 `1.35%`，远低于复制执行的 baseline。整体来看，这些证据足以支持论文的中心论点，不过前提也很明确：它最擅长的仍是那些与作者优化目标相近的 matmul 类工作负载。

## 创新性与影响

相对于 _Wang et al. (SOSP '23)_，SEVI 的范围更窄，但深度更高。它不再问“大规模 CPU 群体中的一般性 SDC 是什么样”，而是直指向量指令，并把故障粒度细化到可观察的指令类型、位模式和 lane 局部性。相对于 _Chatzopoulos et al. (HPCA '25)_，它的贡献不是微架构建模，而是更大规模的生产证据，并且证明一些关于浮点 SDC 的既有直觉并不完整。相对于 _Karystinos et al. (ISCA '24)_，论文最重要的一步是把专用测试和 in-application detector 结合起来，让检测能够在有用工作发生时顺带完成，而不是完全依赖独立测试时段。

这使它同时对基础设施团队和架构研究者都有价值。对工程实践者来说，论文给出的是一条可落地路径：利用生产 workload 当 canary，更快找出坏核心，并且只禁用或下线问题核心，而不是整颗处理器。对研究者来说，它提供了一个罕见的 field dataset，展示真实 SDC 行为会被指令类别、位宽、温度和 lane 空间局部性强烈塑形。因此，这篇论文既是测量研究，也是系统设计论文，而不是简单把两者拼在一起。

## 局限性

论文对自己的边界说得比较清楚。整个 fleet 研究是从已经被标记为 suspect 的机器出发，因此那些在第一阶段就漏掉的超低频故障，仍然可能看不见。作者认为这不会改变定性结论，但这也意味着测量结果始终受制于前置检测流水线，而不是来自完全随机的 fleet 抽样。同样，指令级测试只覆盖了 x86 数据中心 CPU 上的 AVX2、FMA3、BMI1 和 BMI2；它并不试图外推到其他 ISA 或加速器。

缓解方案的覆盖面也比标题略窄。ABFT 机制目前只在 matmul 上实现，论文虽然建议部署到 math library 层，使所有使用 matrix multiplication 的应用自动获得检测能力，但并没有报告生产应用中的端到端上线结果。随着矩阵变大，若不做 tiling，checksum 的相对误差会被稀释，检测能力也会下降，所以“低开销”部分依赖于合适的粒度选择。最后，论文无法真正给出电路级根因，因为底层硬件设计是专有的、CPU 架构信息也被匿名化。它提供的是很强的运维证据和可信的硬件假设，而不是最终定案的电路诊断。

## 相关工作

- _Wang et al. (SOSP '23)_ — 研究大规模生产 CPU 群体中的 silent data corruption，而 SEVI 进一步聚焦向量指令，并把这些故障和具体检测机制连接起来。
- _Hochschild et al. (HotOS '21)_ — 说明生产 fleet 中确实存在“静默出错”的核心；SEVI 则进一步回答哪些向量指令会错、这些错误局部到什么程度。
- _Karystinos et al. (ISCA '24)_ — Harpocrates 通过 hardware-in-the-loop 方式生成 CPU 故障测试，而 SEVI 把长时间 fleet 测量和 in-application ABFT canary 结合起来。
- _Chatzopoulos et al. (HPCA '25)_ — Veritas 从微架构角度建模 SDC 可能来源，SEVI 则用真实 hyperscale 机器验证并补充了这幅图景。

## 我的笔记

<!-- 留空；由人工补充 -->

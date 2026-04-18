---
title: "SEVI: Silent Data Corruption of Vector Instructions in Hyper-Scale Datacenters"
oneline: "SEVI 在 hyperscale 数据中心上实测向量指令 SDC，并把 matmul 改造成带 ABFT 校验的在线探针，以约 1.35% 开销检测多数故障机器。"
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
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

SEVI 在 hyperscale 生产机群上实测向量指令里的 silent data corruption，并把 matrix multiplication 改造成一个低开销在线探针。论文表明，FMA 指令主导了观测到的故障，而基于 ABFT 的 checksum 能以 `88%-100%` 的机器覆盖率检测这些故障，`1024 x 1024` 矩阵上的开销约为 `1.35%`。

## 问题背景

这篇论文关心的是 hyperscale 基础设施里一个很难定位的可靠性漏洞。SDC 的麻烦不在于程序会崩，而在于程序不会崩：硬件直接返回错误值，软件继续执行，错误一路传到上层状态。在单机上，这类事件像噪声一样稀少；但在数据中心规模下，累计故障率已经有运维意义。此前工作给出了案例分析、fleet 级统计和模拟器里的 fault injection，但还缺少一个系统答案：究竟哪些向量指令会在生产里出错，这些错误长什么样，以及能否不靠大量纯测试时间来持续发现它们。

向量指令之所以值得单独研究，是因为它们既重要又脆弱。论文指出，向量指令约占 AI 工作负载计算指令的 `80%`，也占多类 hyperscale 服务约 `50%` 的执行驻留时间。于是问题不再只是“CPU 会不会 SDC”，而是“哪些向量操作是主要风险源，它们有没有稳定结构，以及能否把常见生产 kernel 变成廉价探针”，从而避免只靠长时间专用测试来买覆盖率。

## 核心洞察

论文的核心判断是，向量指令 SDC 在真实机群里足够集中，因此值得做定向检测。SEVI 的数据表明，绝大多数故障来自 FMA 指令，故障通常局限在单个物理核心，而 `98.5%` 的 incident 只影响一个 vector lane。与此同时，matrix multiplication 里的应用级错误又和 FMA 级别故障高度相关，因此它很适合作为把“底层指令故障”映射到“真实工作负载检测”的桥梁。

第二个洞察是，这个探针不需要完整复制原工作负载。对 `A x B` 来说，输出矩阵元素总和应当等于 `A` 的行 checksum 向量与 `B` 的列 checksum 向量的点积。这个不变量比重算整个 matmul 便宜得多，而 SDC 同时把两边扰动成同一个错误 checksum 的概率又很低。论文因此把 ABFT 从传统 HPC 容错技巧改造成生产 fleet canary。

## 设计

SEVI 的方法分成两个阶段。第一阶段，Meta 的基础设施通过维护窗口里的 out-of-production tests 和与正常业务共置的轻量 in-production tests，在整个平台里筛选 “SDC Suspects”。这些机器被虚拟打标后仍继续承载正常工作负载，因此后续测试仍然贴近真实生产环境。论文覆盖的是一个拥有数百万台服务器、七代近期 CPU 架构、十六类工作负载的 fleet，最终在多年运行中找到了 `2,500+` 台 suspect 机器。

第二阶段，作者对所有 suspect 机器做长时间深测。指令级套件包含 `246` 个 AVX2、FMA3、BMI1 和 BMI2 测试，每个测试只隔离一条指令，并在每个逻辑核心上运行 `1` 百万轮，完整重复两次，再加一轮所有 lane 输入一致的测试。总量超过 `78` 万亿轮和 `140` 亿 CPU 秒。应用级套件则使用 NumPy matmul，在有界和无界浮点输入、三种矩阵维度上界下运行，共增加 `430` 亿轮和 `25` 亿 CPU 秒。

缓解机制建立在 matmul 的 checksum 不变量上。对 `A x B`，SEVI 计算 `A` 的行 checksum、`B` 的列 checksum，再把两者点积与输出矩阵元素和比较。论文建议对大矩阵做 tile 级校验，以免单个错误元素在全局求和里被稀释。评估时用 scalar 重算作为 ground truth，但真正可部署的是轻量 checksum 路径，而不是完整复制执行。

## 实验评估

这篇论文最强的部分是它真的把“罕见故障”测成了统计量。指令级实验里，SEVI 一共观测到 `28` million 次 incident，归并成 `400` 个 SDC case，对应约 `0.072‱` 的 fleet-level vector-SDC machine rate。`246` 个测试里只有 `75` 个真正发现过 SDC，而且全部集中在 arithmetic、FMA、gather 和 permute 四类指令中。FMA 占绝对主导：贡献了超过 `75%` 的 case 和超过 `92%` 的 incident。故障形态也很有结构：内存访问类 SDC 约 `76%` 是错误 offset 读取，`24%` 是读取数据被破坏；向量 SDC 通常只落在单个物理核心、单个 lane 上。

应用级结果把这个故事和真实 workload 接了起来。作者在 matmul 中观测到 `292K` 次 incident，分布在 `12` 台机器上的 `24` 个 SDC case，约对应 `0.048‱` 的 fleet-level 机器率。其中 `10` 个 case 出现在同时也有 FMA SDC 的核心上，而且 matmul SDC 频率与 FMA SDC 频率的 Pearson 相关系数达到 `0.979`，很有力地说明应用级故障主要由 FMA 驱动。错误幅度也不总是轻微的：虽然多数错误输出相对误差低于 `1`，但长尾可以达到 `10240`，因为 exponent bits 也会翻转。

ABFT 结果说明这不只是测量，更是一个可部署检测器。对无界浮点输入、最大维度 `10` 的矩阵，它能检测出 matmul 研究里发现的全部故障核心；最大维度为 `25` 时覆盖率仍有 `94%`，到 `100` 时还有 `88%`。对有界输入，方法能检测 `23` 台故障机器中的 `21` 台，并在被捕获机器上覆盖约 `99%` 的 incident。超过 `80%` 的核心能在 `21` 秒内看到第一次告警。开销方面，小矩阵约 `11%`，维度 `100` 时约 `3%`，到 `1024 x 1024` 时降到 `1.35%`，明显低于复制执行。

## 创新性与影响

相对于 _Wang et al. (SOSP '23)_，SEVI 的范围更窄，但也更深：它不再研究一般性的 processor SDC，而是聚焦向量指令，并把故障细化到指令类别、位模式、核心局部性和 lane 局部性。相对于 _Chatzopoulos et al. (HPCA '25)_，它贡献的不是微架构建模，而是更大规模的生产证据。相对于 _Karystinos et al. (ISCA '24)_，它最重要的系统贡献是把专用测试和 in-application detector 结合起来，让检测发生在有用工作期间。

因此，这篇论文同时服务两类读者。对基础设施团队，它给出了一条现实路线：让常见 workload 充当 canary，更快定位坏核心，并选择性禁用它们。对体系结构研究者，它给出一个少见的 field dataset，展示真实 SDC 会被指令类别、位宽、温度和 lane 局部性强烈塑形。

## 局限性

论文对边界说得比较清楚。整个 fleet 研究是从 suspect 机器出发的，因此那些在第一阶段就漏掉的超低频故障，仍可能不可见。作者认为这不会改变定性结论，但它毕竟不是对整个 fleet 的随机抽样。类似地，指令级测试只覆盖了匿名化 x86 数据中心 CPU 上的 AVX2、FMA3、BMI1 和 BMI2，不能直接外推到其他 ISA 或加速器。

缓解方案的覆盖面也比标题略窄。ABFT 机制目前只在 matmul 上实现，论文建议把它部署到 math library 层，但没有报告生产应用中的端到端 rollout。随着矩阵变大，如果不做 tiling，checksum 的相对误差会被稀释，检测能力随之下降。最后，由于底层硬件设计是专有的，论文只能给出强有力的运维证据和可信假设，而不是电路级定论。

## 相关工作

- _Wang et al. (SOSP '23)_ — 研究大规模生产 CPU 群体中的 silent data corruption，而 SEVI 进一步聚焦向量指令，并把这些故障和具体检测器连接起来。
- _Hochschild et al. (HotOS '21)_ — 说明生产 fleet 中确实存在静默出错的核心；SEVI 则进一步回答哪些向量指令会错、这些错误局部到什么程度。
- _Karystinos et al. (ISCA '24)_ — Harpocrates 通过 hardware-in-the-loop 方式生成 CPU 故障测试，而 SEVI 把长时间 fleet 测量和 in-application ABFT canary 结合起来。
- _Chatzopoulos et al. (HPCA '25)_ — Veritas 从微架构角度建模 SDC 可能来源，SEVI 则用真实 hyperscale 机器验证并补充这幅图景。

## 我的笔记

<!-- 留空；由人工补充 -->

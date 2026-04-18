---
title: "SEVI: Silent Data Corruption of Vector Instructions in Hyper-Scale Datacenters"
oneline: "SEVI 在 hyperscale 机群上实测向量指令 SDC，并把 ABFT 校验嵌入 matmul，以最高 1.35% 开销检测 88%-100% 的故障机器。"
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
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790217"
code_url: "https://github.com/Thesys-lab/SEVI-ASPLOS26"
tags:
  - hardware
  - datacenter
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

SEVI 不是只靠 fault injection 来研究 silent data corruption，而是在 hyperscale 生产机器上直接测量向量指令 SDC。论文表明，绝大多数观测到的故障来自 FMA 指令，故障通常局限在单个物理核心、甚至单个 vector lane，而嵌入 matmul 的 ABFT 校验能以 `88%-100%` 的机器覆盖率发现这些故障，在大矩阵上最低只带来 `1.35%` 开销。

## 问题背景

这篇论文关心的是 hyperscale 基础设施里一种最难防的可靠性故障。SDC 的麻烦不在于程序崩溃，而在于程序不崩溃：硬件返回错误值，软件照常往前跑，错误一路被上层系统消费。在单机尺度上，这类事件可能低到像噪声；但在数据中心尺度上，Google、Meta、Alibaba 的既有事故已经说明，累计故障率足以影响生产可靠性。

论文真正要补上的，是三个更可操作的答案：哪些向量指令主导风险，这些故障是否有稳定结构，以及运维系统能否不花大量纯测试开销也持续发现最重要的 SDC。向量指令之所以值得单独研究，是因为它们既关键又脆弱：论文指出，它们约占 AI 工作负载计算指令的 `80%`，也占多类 hyperscale 服务约 `50%` 的执行驻留时间，而先前工作已经暗示它们特别容易发生 SDC。

## 核心洞察

论文最重要的判断是，向量指令 SDC 不是一团无结构的“可靠性噪声”，而是集中到足以被刻画、再被利用的程度。SEVI 的测量显示，FMA 指令贡献了压倒多数的 incident，故障通常只停留在单个物理核心上，而 `98.5%` 的 incident 甚至只影响一个 vector lane。既然问题高度集中，检测系统就不必先覆盖所有 CPU 故障模式，才能获得有意义的收益。

把测量结果转化成缓解机制的桥梁是 matmul。它既是数据中心里的常见基础操作，又高度依赖 FMA，因此很适合充当 canary。更关键的是，这个 canary 不需要完整复制原工作负载：对 `A x B`，输出矩阵元素和必须等于 `A` 的行 checksum 向量与 `B` 的列 checksum 向量的点积。这个不变量比重算整个 matmul 便宜得多，同时两边恰好被 SDC 扰动成同一个错误结果的概率也很低。

## 设计

SEVI 分成两个阶段。第一阶段是 fleet 级 suspect 筛选。Meta 的基础设施既在维护窗口里运行 out-of-production tests，也把轻量 in-production tests 与真实业务共置运行；测试内容同时包含 vendor suite 和来自十六类工作负载的代码片段。出现异常的机器会被虚拟打上 `SDC Suspects` 标记，但仍继续承载生产流量。多年运行下来，这个流程从拥有数百万台服务器、七代近期 CPU 架构的 fleet 中识别出了 `2,500+` 台 suspect 机器。

第二阶段是对所有 suspect 做长时间刻画。指令级套件包含 `246` 个 AVX2、FMA3、BMI1 和 BMI2 测试，每个测试只隔离一条指令；每个逻辑核心都运行 `1` 百万轮，再把整套实验完整重复两次，最后加一轮所有 lane 输入一致的测试。总规模超过 `78` 万亿轮和 `140` 亿 CPU 秒。应用级套件则用 NumPy matmul，在有界和无界浮点输入、三种矩阵维度上界下运行，再增加 `430` 亿轮和 `25` 亿 CPU 秒。

缓解机制是嵌入 matmul 的 in-application ABFT。对 `A x B`，SEVI 先计算 `A` 的行 checksum 向量和 `B` 的列 checksum 向量，再把二者点积与输出矩阵元素和比较。这个额外开销只是 `O(mn + np)`，而原始 matmul 是 `O(mnp)`。评估时作者用 scalar 重算作为 ground truth；真正可部署的路径则是 checksum 检测本身。对于更大的矩阵，论文建议使用 tile 大小小于 `100` 的分块校验。

## 实验评估

这篇论文最有说服力的部分，是它真的把“极罕见故障”测成了可讨论的统计量。指令级实验里，SEVI 观测到 `28` million 次 incident，归并成 `400` 个 SDC case，对应约 `0.072‱` 的 fleet-level vector-SDC machine rate。`246` 个测试里只有 `75` 个真正发现过 SDC，而且它们全部集中在 arithmetic、FMA、gather 和 permute 四类指令里。FMA 占绝对主导：贡献了超过 `75%` 的 case 和超过 `92%` 的 incident。故障形态也很有结构：内存访问类 SDC 约 `76%` 是错误 offset 读取，`24%` 是读取数据被破坏；每台受影响机器上，SDC 都只出现在一个物理核心，而 `98.5%` 的 incident 只影响一个 vector lane。

应用级结果把这套故事和真实 workload 接了起来。作者在 matmul 中观测到 `292K` 次 incident，分布在 `12` 台机器上的 `24` 个 SDC case，约对应 `0.048‱` 的 fleet-level 机器率。其中 `10` 个 case 出现在同时也有 FMA SDC 的核心上，而且 matmul SDC 频率与 FMA SDC 频率的 Pearson 相关系数达到 `0.979`。`75%` 的 matmul SDC case 会在 `8` 秒内出现第一次失败；虽然 `75%` 的错误结果相对误差低于 `1`，但长尾可以达到 `10240`，这与 exponent bits 被翻转相吻合。

ABFT 结果说明这篇论文不只是测量研究，也给出了一个可部署的检测器。对无界浮点输入、最大维度 `10` 的矩阵，它能检测出 matmul 研究里发现的全部 `24` 个故障核心；最大维度为 `25` 时覆盖率仍有 `94%`，到 `100` 时还有 `88%`。对有界输入，方法能检测 `23` 台故障机器中的 `21` 台，并在被捕获机器上覆盖约 `99%` 的 incident。超过 `80%` 的核心能在 `21` 秒内看到第一次告警。开销方面，维度 `10` 和 `25` 时都是 `11%`，维度 `100` 时约 `3%`，到 `1024 x 1024` 时降到 `1.35%`，远低于复制执行。整体看，这组实验对论文主张的支撑是扎实的，只是没有补上 math-library 级检测器在真实生产业务中的完整 rollout。

## 创新性与影响

相对于 _Wang et al. (SOSP '23)_，SEVI 的范围更窄，但也更深：它不再研究一般性的 processor SDC，而是聚焦向量指令，并把故障细化到指令类别、位模式、核心局部性和 lane 局部性。相对于 _Chatzopoulos et al. (HPCA '25)_，它的贡献不是更好的微架构模型，而是更大规模的生产证据。相对于 _Karystinos et al. (ISCA '24)_，它最重要的系统贡献是把专用测试和 in-application detector 结合起来，让检测发生在有用工作期间。

因此，这篇论文同时服务两类读者。对基础设施团队，它给出了一条现实路线：让常见的 math-library 调用充当 canary，更快定位坏核心。对体系结构和可靠性研究者，它给出一个少见的 field dataset，展示真实 SDC 会被指令类别、位宽、温度和 lane 局部性强烈塑形。

## 局限性

论文对边界说得比较清楚。整个 fleet 研究是从 suspect 机器出发的，因此那些在第一阶段就漏掉的超低频故障，仍可能不可见。作者认为这不会改变定性结论，但它毕竟不是对整个 fleet 的无偏随机抽样。类似地，指令级测试只覆盖了匿名化 x86 数据中心 CPU 上的 AVX2、FMA3、BMI1 和 BMI2，不能直接外推到其他 ISA 或加速器。

缓解方案的覆盖面也比标题略窄。ABFT 机制目前只在 matmul 上实现，论文建议把它部署到 math library 层，但没有报告生产应用中的端到端 rollout。随着矩阵变大，如果不做 tiling，checksum 的相对误差会被稀释，检测能力会下降；而底层硬件又是专有设计，因此论文无法给出电路级定论。

## 相关工作

- _Wang et al. (SOSP '23)_ — 研究大规模生产 CPU 群体中的 silent data corruption，而 SEVI 进一步聚焦向量指令，并把这些故障和具体检测器连接起来。
- _Hochschild et al. (HotOS '21)_ — 说明生产 fleet 中确实存在静默出错的核心；SEVI 则进一步回答哪些向量指令会错、这些错误局部到什么程度。
- _Karystinos et al. (ISCA '24)_ — Harpocrates 通过 hardware-in-the-loop 方式生成 CPU 故障测试，而 SEVI 把长时间 fleet 测量和 in-application ABFT canary 结合起来。
- _Chatzopoulos et al. (HPCA '25)_ — Veritas 从微架构角度建模 SDC 可能来源，SEVI 则用真实 hyperscale 机器验证并补充这幅图景。

## 我的笔记

<!-- 留空；由人工补充 -->

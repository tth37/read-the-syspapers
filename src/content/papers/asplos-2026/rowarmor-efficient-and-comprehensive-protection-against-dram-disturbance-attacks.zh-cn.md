---
title: "RowArmor: Efficient and Comprehensive Protection Against DRAM Disturbance Errors"
oneline: "用八位组级扰动约束、反应式 ECC 校正、地址混淆与按风险触发的 scrubbing，一起防住 DRAM 扰动导致的数据破坏和 DoS。"
authors:
  - "Minbok Wi"
  - "Yoonyul Yoo"
  - "Yoojin Kim"
  - "Jaeho Shin"
  - "Jumin Kim"
  - "Yesin Ryu"
  - "Saeid Gorgin"
  - "Jung Ho Ahn"
  - "Jungrae Kim"
affiliations:
  - "Seoul National University, Seoul, Republic of Korea"
  - "Samsung Electronics, Suwon, Republic of Korea"
  - "Sungkyunkwan University, Suwon, Republic of Korea"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790213"
tags:
  - memory
  - security
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

RowArmor 的核心主张是，DRAM 扰动防护不该继续执着于“提前拦下每一次可疑激活”，而应该把错误塑形成 ECC 擅长处理的形状，再在真正出错时做反应式恢复。它先把单个 aggressor 的影响约束到 octet 级别，再用能纠正最多 8 个重叠 octet 错误的 ECC、控制器侧地址混淆，以及只在积累风险升高时才触发的 scrubbing 组合起来。最终，它同时压低数据破坏和拒绝服务风险，而性能开销最高只有 `0.7%`。

## 问题背景

这篇论文针对的是一个越来越糟糕的现实：DRAM 的 disturbance threshold 持续下降，但防御方法仍主要依赖“数激活次数，然后提前 refresh 或 backoff”。传统思路的问题不只是在成本高，而是在工艺继续缩小时越来越不对题。

第一，预防式机制必须按最脆弱单元来定阈值。可真实 DRAM 的脆弱性受工艺差异、环境、老化、存储值、row open time 等因素影响非常大，于是系统为了少数最坏行去保护所有行，难免会产生大量并不必要的 refresh、swap 或 throttle。第二，新攻击已经不再只由 activation count 决定。RowPress 说明“把一行保持打开更久”也能显著放大扰动，因此只盯计数器的方案和底层物理现象越来越脱节。第三，预防动作本身还会变成 DoS 攻击面。论文引用前人结果指出，PRAC 类 backoff 在理论最坏情况下会吃掉高达 `94%` 的内存带宽，攻击者即使没能制造静默数据损坏，也可能把保护机制本身变成系统瓶颈。

“那就交给 ECC”也不够。现代服务器 DRAM 已经为 On-Die ECC 和 rank-level ECC 付出了很高的冗余，但这些 ECC 主要是为随机位错和整颗芯片故障设计的，并不擅长处理会跨多个 chip、甚至跨整个 data transfer block 的扰动模式。一旦超出可纠范围，系统常常只能把它当成 DUE 处理，进一步触发重启、回滚、摘机或服务中断。所以论文要解决的不是单纯“减少 bit flip”，而是“在不再引入额外可利用瓶颈的前提下，同时防住数据破坏和可用性崩溃”。

## 核心洞察

论文最值得记住的命题是：如果硬件能先把 disturbance error 重新排布成 ECC 天然擅长纠正的形状，那么反应式防护就会比持续预防更划算。RowArmor 的第一步因此不是追踪每个 aggressor，而是改变 DRAM 内部映射，让单个 aggressor 在一次访问里最多只污染一个 8-bit octet；接着再用更强的符号级 ECC 去恢复这些 octet 错误。

但这还不足以应对 many-aggressor 攻击，所以作者再叠加了两个判断。其一，只要控制器把 physical address 到 DRAM row 的映射随机化，攻击者就很难把很多 aggressor 精准对齐到同一个 victim 地址上。其二，只要系统在观察到“中等程度的可纠错重叠”时就启动 scrubbing，就能在不做持续全盘巡检的情况下阻断错误继续积累到不可恢复。换句话说，RowArmor 认为更好的平衡点是“先约束错误形状，再增强纠错能力，再用概率方式打散对齐”，而不是继续堆更悲观的计数和刷新。

## 设计

RowArmor 由四个关键动作组成：confine、correct、obfuscate 和 scrub。

confine 对应 octet scrambling。论文在 DRAM 内部引入两层改动：DQ Address Scrambling 让不同 DQ 和不同 chip 使用不同的 row-address 映射；Sub-WordLine Permutation 再把同一个 DQ 上的两个 octet 分散到不同的本地字线布局。两者叠加后，单个 aggressor 的扰动不会再表现成一个“大块多位错误”，而会被拆散成分布在多个地址上的 octet 级错误。这样，一次访问里最多只会看到来自两个相邻 victim row 的两个受损 octet。

correct 对应 Octuple-Octet Correcting (OOC) ECC。论文把一个传输块重组为 `64` 个 data symbol 和 `16` 个 parity symbol，每个 symbol 都是一个 8-bit octet，并用 Reed-Solomon 码实现每次访问最多纠正 8 个 octet 错误。和传统 chipkill 式 ECC 相比，这不是简单“更强一些”，而是明确围绕 multi-aggressor overlap 设计的纠错能力。由于强纠错也会提高随机错误被误纠正的风险，RowArmor 还加入 correction validation：当观察到不太像随机故障的错误图样时，系统会通过 mode-register read 读取 OD-ECC counter，再重读同一行的其他列；若计数器继续增长，说明更像 disturbance propagation，就接受这次强纠错；若计数器不变，则拒绝该纠正并上报 DUE，以避免 miscorrection。

obfuscate 对应控制器侧的 Row Address Obfuscation。系统为每个 bank 配置 key，用 Feistel 结构对 row address 做一一映射的置换，让软件可见的 physical page 不再暴露哪些 DRAM row 真正相邻。论文给出的分析结果是：如果一个 bank 有 `128K` 行，那么在这种随机化下，9-aggressor 攻击制造 9 个重叠错误的概率只有 `4 x 10^-27`。

scrub 解决的是“错误会不会慢慢堆起来”这个问题。OOC 在读出时能纠正，但不会自动把所有地方都写回干净数据，因此那些暂时没被访问到的行仍可能继续积累错误。RowArmor 的 guardband scrubbing 就把“观测到的可纠错数”当成风险信号。论文举的例子是，当一次访问中需要纠正 3 个或更多 octet 时，就主动对整个 bank 做 read-correct-write scrubbing，趁还没越过 8 个可纠错上限前把隐藏的积累清掉。若 scrubbing 仍反复触发，系统还可以继续升级为 throttle 可疑线程，或者轮换 bank key。

## 实验评估

论文从安全性、性能、可靠性和硬件开销四个维度评估 RowArmor，并和 PARA、SRS、Cube、RAMPART、Graphene、ABACuS、PRAC 等方案比较。安全评估覆盖 `0.01%` 到 `10%` 的 BER，并把 aggressor 数量一直扫到 `256`。在 `0.01%` BER 下，RowArmor 的 targeted attack 成功概率已经极低；即便放到 `256` 个 aggressor，仍只有 `3 x 10^-57`。DoS 方面，在 `16` 个 aggressor 时成功概率只有 `1 x 10^-43`，到 `256` 个 aggressor 也只是 `9 x 10^-32`。低 BER 时，主要是 octet confinement 加 OOC ECC 已经足够强；高 BER 时，guardband scrubbing 的价值反而更明显，因为攻击会更早暴露出可观测的纠错事件。

性能评估使用 McSimA+ 和 SPEC CPU2017 traces，在 `16` 核 DDR5-6400 系统上做实验。最关键的结论是 RowArmor 的开销几乎不随阈值恶化而增长：即使在最吃内存的 `Mix-High` 工作负载上，平均 slowdown 也只有约 `0.7%`，而且在假设 `NRH` 从 `2048` 一路降到 `128` 时，这个开销基本保持不变。相比之下，预防式方案会随着阈值下降而付出越来越多 refresh、swap、stall 或 counter 更新成本。

我觉得这篇论文的评估说服力比较强，因为作者没有只报攻击概率和吞吐，还额外检查了可靠性与面积。OOC 在 Monte Carlo 实验里能纠正最多三个彼此独立的 1-bit 错误，论文还通过数学分析估算其 silent-data-corruption 概率约为 `5 x 10^-19`。控制器侧 RAO 逻辑面积大约 `1,460 um^2`，DRAM 侧 scrambling 逻辑也非常小，作者估计其面积不到所引用 DRAM die 面积的 `0.005%`。综合起来看，论文确实证明了它不是靠“隐藏的硬件税”换安全，而是真正把安全性和性能边界往前推了一步。

## 创新性与影响

和 _Kim et al. (MICRO '23)_ 相比，RowArmor 的创新点不只是把随机化和 ECC 再拼一次，而是把故障粒度从 chip 级处理改成 octet 级约束，再据此重新设计 ECC。和 _Woo et al. (MEMSYS '23)_ 相比，它也不只是单纯隐藏地址关系，而是把地址混淆、强纠错和受控清理组合起来。和 PRAC 或 MOAT 这类预防式工作相比，它最大的贡献是把 DRAM disturbance 防护重新表述成“反应式纠错问题”，而不是“持续计数问题”。

因此，这篇论文会同时吸引 DRAM 架构师、服务器内存系统设计者，以及关注硬件可用性安全的系统研究者。它既提出了一个新机制，也给出了一个很强的观点转移：未来 threshold 更低的 DRAM，也许更适合通过“把错误变得可纠正”来防御，而不是继续努力保证每次危险激活都能被提前观察到。

## 局限性

RowArmor 依然是一个硬件侵入性不低的方案。它需要控制器侧地址混淆、DRAM 内部地址 scrambling、更大的 ECC 组织、OD-ECC counter 可见性，以及系统软件配合 scrubbing。尤其是 key rotation 路径并不便宜，论文明确提到操作系统可能需要暂停某个 bank 的访问，并在新旧映射之间迁移数据。

此外，论文的大部分安全证据来自分析和模拟，而不是量产硬件上的端到端验证。它的攻击概率建立在若干前提上，例如攻击者拿不到 secret key、无法直接探测 DRAM 信号，以及背景访问足以帮助系统在出现 UE 之前观察到中等规模重叠错误。这些假设并不离谱，但也意味着最稳妥的结论是“在论文建模的扰动过程中，该机制很稳健”，而不是“现成商品硬件已经完整验证了这套实现”。

## 相关工作

- _Kim et al. (MICRO '23)_ — Cube 也把 ECC 和地址随机化结合起来，但它对大规模重叠错误的处理能力更有限；RowArmor 明确支持最多 8 个 octet overlap，并用 scrubbing 阻止继续积累。
- _Woo et al. (MEMSYS '23)_ — RAMPART 依赖控制器侧混淆和 ECC 修复，而 RowArmor 进一步把故障塑形工作推进到 DRAM 内部，让 ECC 面对的是 octet 级受限错误而不是 chip 级破坏。
- _Kim et al. (ISCA '14)_ — PARA 是经典的低成本预防式基线，通过概率 victim refresh 来压制 RowHammer；RowArmor 的对照点则是完全避免这种可被攻击者触发的预防刷新。
- _Qureshi and Qazi (ASPLOS '25)_ — MOAT 继续在 DRAM 内优化 PRAC 风格的计数与刷新，而 RowArmor 认为即便这些计数机制被优化，仍然难以摆脱额外开销和 DoS 压力。

## 我的笔记

<!-- 留空；由人工补充 -->

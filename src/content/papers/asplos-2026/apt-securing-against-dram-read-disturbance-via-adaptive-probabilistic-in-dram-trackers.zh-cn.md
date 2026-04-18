---
title: "APT: Securing Against DRAM Read Disturbance via Adaptive Probabilistic In-DRAM Trackers"
oneline: "APT 用按激活次数自适应的 reservoir sampling 和分段式受害行刷新，在不依赖可被攻击者触发的 RFM 的前提下同时防御 RowHammer 与 RowPress。"
authors:
  - "Runjin Wu"
  - "Meng Zhang"
  - "You Zhou"
  - "Changsheng Xie"
  - "Fei Wu"
affiliations:
  - "School of Computer Science and Technology, Huazhong University of Science and Technology, Wuhan, China"
  - "Wuhan National Laboratory for Optoelectronics, Huazhong University of Science and Technology, Wuhan, China"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790126"
tags:
  - memory
  - security
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

APT 是一种低成本的 in-DRAM RowHammer/RowPress 防御方案，它把固定概率的行采样改成按真实激活次数自适应变化的 reservoir sampling。论文的第二个关键招式是 Step Mitigation：按物理上观测到的距离衰减形状来分配受害行刷新概率，因此可以在普通 `REF` 的空闲时间里塞下最多三次安全 mitigation，并在需要时再和固定频率的 `TB-RFM` 组合。最终，纯 `REF` 方案可保护到 `TRH = 694`，若配合 `TB-RFM0.5`，则能把可容忍阈值进一步降到 `228`，平均 slowdown 只有 `1.6%`。

## 问题背景

这篇论文针对的是一个越来越尖锐的矛盾：DRAM 的 read disturbance 在变严重，但透明式防御的资源预算并没有跟着增加。传统 `RowHammer` 通过频繁激活相邻 aggressor row 诱发 bit flip，而 `RowPress` 进一步表明，只要把一行长时间保持打开，也能显著降低触发错误所需的激活次数。随着工艺缩放，这类攻击越来越现实，但 DRAM 芯片内部可用于防御的空间仍然极小，每个 bank 只有很少的存储位来记录可疑行，也只有主要借自 refresh 的有限时间来刷新受害行。

现有低成本方案里，概率式 tracker 看起来最有吸引力，因为它们避免了 per-row counter 的巨大代价。但论文指出，这类设计恰恰会在攻击者最喜欢的模式下露出破绽。若系统在一个固定激活窗口里随机抽一个 slot，那么当窗口内真实激活次数偏少时，就可能一个 aggressor 都没采到。论文把这称为 row-sampling miss。这个缺陷之所以严重，是因为 `RowPress` 以及混合 `RowPress/RowHammer` 攻击会主动减少“可见”的激活次数，却仍旧制造足够的电荷损失，于是固定 `1/WA` 采样就可能让攻击行完全逃过 mitigation。

最直接的补救办法是依赖 DDR5 的 `RFM` 增加 mitigation 机会，但这又引出了第二个问题。`RFM` 会让 bank 停顿一段可观察的时间，而近期工作已经证明，这些时延尖峰可以被做成 side channel 或 covert channel。于是，这篇论文真正要解决的并不只是“怎样便宜地采样 aggressor row”，而是一个更严格的问题：怎样设计一种透明的 in-DRAM 防御，使其既能适应动态激活模式、避免可被攻击者触发的时序泄漏，又能在不付出巨大 SRAM 和性能代价的前提下向更低的 `TRH` 扩展。

## 核心洞察

论文最核心的命题是：只要把采样概率绑定到“已经看到的真实激活数”，而不是预先固定好的窗口大小，概率式追踪就会稳健得多。APT 因此借用了 reservoir sampling：在一个 `tREFI` 窗口内，第一个激活必然被选中，第 `i` 个激活则以 `1/i` 的概率被选中。由于被选中的行后续还会以对应的 reservoir-sampling 保留概率留到窗口结束，所以每次激活最终获得的 mitigation 概率都是相同的 `1/N`，其中 `N` 是这个窗口里的真实激活数。这样一来，固定窗口方案里的 row-sampling miss 就被消掉了。

第二个洞察是，受害行刷新概率也应该贴着真实物理现象走，而不是沿用一个通用的指数衰减规则。作者引用近期表征工作指出，电荷损失随着 aggressor-victim 距离增加，更像是“分段下降”而不是平滑指数下降。于是 Step Mitigation 直接按这种形状来采样刷新距离。这样做的好处有两个：第一，它仍然能抵御 transitive attack；第二，它每次 mitigation 只需要两次 victim refresh，因此足够省时，能够把多次 mitigation 塞进普通 `tRFC` 的空闲部分。

## 设计

APT 的基础形态是单条目的 in-DRAM tracker。在每个 `tREFI` 内，一个 activation counter 为每次激活分配序号 `i`。第一次激活会直接写入 mitigation-address register；之后的激活则通过“随机数与 modulo-`i` 条件比较”的方式实现近似 `1/i` 的 reservoir sampling。论文在这里并没有回避硬件细节：它不用真正的除法，而是用 staged subtractor，在特定阈值才提升操作数宽度，从而把采样逻辑的延迟隐藏在 `tRC` 内。到了下一个 `REF`，若寄存器里有有效 aggressor 地址，就对其邻近受害行执行 mitigation。

这些 victim refresh 不是简单的“刷新最近邻”而已。Step Mitigation 把 aggressor-victim 距离分成几个 step，并给每个 step 分配递减但经过仔细校准的概率。论文默认 blast radius 为 4，此时距离 `1` 的最近邻总刷新概率是 `31/32`，距离 `2` 是 `1/64`，距离 `3` 和 `4` 各是 `1/128`。这个设计的重点不是公式漂亮，而是既要贴近真实 disturbance 分布，又要把一次 mitigation 控制在两次 victim refresh 之内。正因为如此，普通 `REF` 才还能容纳多次 mitigation。

在此基础上，论文又给出两个扩展方向。`APT-3` 用三个单条目 sampler 轮转工作，使一次 `REF` 能排空三个被采到的 aggressor。`APT-P` 则把这个思路扩展到 15 个条目，用来在 refresh postponement 存在时依旧保持自适应。最后，如果部署环境必须支持更低的阈值，作者就再叠加 `Timing-Based RFM`：它按固定时间间隔发出，而不是由攻击者通过激活计数触发，从而避免可观测的时序泄漏。

## 实验评估

论文把安全阈值分析和 gem5 上的性能实验放在一起看。性能评估使用 `32GB DDR5` 系统，运行 `SPEC2017` rate 和 mixed workloads。对性能最重要的结论是：只靠 `REF` 的方案几乎是“白送”的。`APT-P` 的 slowdown 为零，`APT-3+TB-RFM1` 也几乎没有性能损失，因为在良性工作负载下，很少真的需要利用 postponed refresh。即便使用更激进的固定频率支持，代价也不大：`APT-2+TB-RFM0.5` 平均 slowdown 为 `0.7%`，`APT-3+TB-RFM0.5` 为 `1.6%`；能耗分别只比 baseline 高出 `2.8%` 到 `5.5%`。

安全阈值方面，论文给出的几组核心数字也很清晰。不使用 `TB-RFM` 时，`APT-3` 可保护到 `TRH = 694`；加上 `TB-RFM1` 后可降到 `490`；`APT-2+TB-RFM0.5` 可降到 `349`；`APT-3+TB-RFM0.5` 则可进一步降到 `228`。论文还和两类重要基线做了直接比较。相对于 `MINT + ImPress`，APT 不需要把长时间 row-open 额外折算成大量 mitigation 工作，因此在低阈值下避免了大幅 slowdown；例如 `TRH = 256` 时，`ImPress-N` 和 `ImPress-P` 大约分别带来 `28%` 与 `12.7%` 的 slowdown，而 APT 只有 `1.6%`。相对于安全的 `TPRAC`，APT 的优势更明显：在 `TRH = 256` 时，`TPRAC` slowdown 为 `11%`，APT 仍然只有 `1.6%`，约为前者的 `0.15x`。

我认为这组实验对论文的核心系统主张支撑得相当充分：作者确实展示了“自适应采样 + 分段式 victim refresh”能把透明式防御拉到一个比现有方案好得多的安全/开销平衡点。不过也要看到，安全性证据很大一部分来自解析模型，而不是在真实芯片上做完整攻击验证。因此，最稳妥的解读应当是：在论文给定的模型下，这个设计既有明确的理论依据，也保持了很低的开销。

## 创新性与影响

相对于 _Qureshi et al. (MICRO '24)_ 的 `MINT`，APT 的创新点在于消除 fixed-window 采样带来的 row-sampling miss，而不是只把 tracker 做得更小。相对于 _Jaleel et al. (ISCA '24)_ 的 `PrIDE`，APT 在动态激活模式下更自适应，同时把 victim-refresh 策略明确地绑定到距离相关的 charge-loss 形状上。相对于 _Woo et al. (ISCA '25)_ 的 `TPRAC`，APT 则提出：想要安全地支持低阈值，并不一定非要走 per-row activation counting 那条高成本路线。

因此，这篇论文对 DRAM 架构研究者和硬件安全研究者都很重要。它不只是又做了一个 RowHammer tracker，而是在尝试定义一种更实际的未来设计点：当 commodity DRAM 的阈值继续下降时，工业界是否还能用透明、低面积、低性能损失的方式把系统保住。

## 局限性

APT 终究还是一个硬件提案，“低开销”背后有不少前提。它需要 `TRNG`、新的 in-DRAM 采样逻辑，以及厂商对具体器件 charge-loss profile 的了解，才能把 Step Mitigation 的概率设定好。它最强的低阈值结果还依赖控制器端配合 `TB-RFM`，而且固定频率越高，性能和能耗开销就会稳定上升。

另外，论文的安全分析明显偏模型驱动。作者把任何连续 `TRH` 次未被 mitigation 的激活都视为失败，并采用每 bank `10K` 年的目标 `MTTF`，这当然合理，但仍然是一套设计假设。某些威胁也明确不在范围内，例如 `ColumnDisturb`；作者也承认，若未来阈值进一步降低，可能还需要更大的 mitigation budget。所以，APT 最适合作为 DDR5 类近未来系统中的透明保护机制来看，而不是把它理解成对所有 memory disturbance 现象的一次性终局答案。

## 相关工作

- _Qureshi et al. (MICRO '24)_ — `MINT` 用单项的极简 in-DRAM tracker 做概率式防护，而 APT 改用按真实激活数自适应的 reservoir sampling 来消除 row-sampling miss。
- _Jaleel et al. (ISCA '24)_ — `PrIDE` 同样面向低成本且安全的 in-DRAM tracking，但 APT 更强调动态激活模式下的自适应性，以及如何把更多安全的 victim refresh 塞进普通 `REF` 的空闲时间。
- _Saxena et al. (MICRO '24)_ — `ImPress` 的思路是把 `RowPress` 折算成等价激活，再交给既有防御处理；APT 则试图把 `RowPress` 直接吸收到 tracker 与 mitigation 设计里，并把运行时成本压得更低。
- _Woo et al. (ISCA '25)_ — `TPRAC` 用 `TB-RFM` 保护 `PRAC`-based mitigation，而 APT 主张使用概率式 in-DRAM 方案来换取明显更低的性能和存储开销。

## 我的笔记

<!-- 留空；由人工补充 -->

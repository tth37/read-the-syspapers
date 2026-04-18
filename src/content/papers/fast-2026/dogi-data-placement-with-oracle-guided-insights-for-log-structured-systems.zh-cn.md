---
title: "DOGI: Data Placement with Oracle-Guided Insights for Log-Structured Systems"
oneline: "DOGI 用 oracle 指导的 hot/frozen 过滤、轻量级 ML 和自适应分组来放置日志结构数据，在最佳基线之上再把平均 WAF 降低 15.5%。"
authors:
  - "Jeeyun Kim"
  - "Seonggyun Oh"
  - "Jungwoo Kim"
  - "Jisung Park"
  - "Jaeho Kim"
  - "Sungjin Lee"
  - "Sam H. Noh"
affiliations:
  - "POSTECH"
  - "DGIST"
  - "Gyeongsang National University"
  - "Virginia Tech"
conference: fast-2026
category: indexes-and-data-placement
code_url: "https://github.com/dgist-datalab/DOGI"
tags:
  - storage
  - hardware
  - databases
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`DOGI` 的出发点很克制：它不是先堆一个更复杂的在线策略，而是先构造 `NoDaP` 这个近似最优的 oracle 基线，定量找出现有日志结构放置方案到底把效率丢在了哪里。随后，DOGI 把这些 oracle 洞察落成一个可部署设计：最热块先用便宜规则分离，剩余写入再交给轻量级 MLP，GC 复制出来的块则用历史预测日志来重定位，并且按预测精度动态调整分组粒度。论文报告称，相比最佳基线，它平均把 `WAF` 再降 `15.5%`，并把原型写吞吐提升 `9.2%`。

## 问题背景

日志结构系统之所以被广泛采用，是因为它能把大量随机小更新转换成顺序追加写；无论是 SSD firmware、LSM 风格的 KV store，还是分布式文件系统，这一点都很有吸引力。但真正吞掉收益的是垃圾回收。数据更新后，旧块会失效；一旦空闲段不足，系统就必须挑选 victim segment，把其中仍然有效的块搬走，再回收整段。所有这些额外写入都会体现在写放大因子 `WAF` 上，直接伤害吞吐、介质寿命，有时也会拖累延迟。

理想解法并不神秘。如果系统知道每个块未来何时失效，并且拥有几乎无限的预留空间，那么它就可以把寿命接近的块放进同一批 segment，只回收已经“死透”的段，把 `WAF` 压到接近 `1.0`。可现实系统两者都没有：未来失效时间不可见，over-provisioning 有上限，而且放置决策必须在线完成。

已有工作试图逼近这个理想。SepBIT 和 MiDAS 依赖 latest invalidation time、age 之类的廉价启发式；PHFTL 和 ML-DT 引入更重的 ML 模型；MiDAS 还会调整 group 数量。论文的核心批评是，这些方案大多只优化一个旋钮：要么改善 user-written block 的预测，要么调 group 规模，要么沿用很粗糙的 GC block relocation 策略。于是，SOTA 与现实容量约束下“本可达到”的最优 WAF 之间仍有明显差距，而且过去缺少一种办法把这部分差距拆解清楚。

## 核心洞察

这篇论文最值得记住的一句话不是“要用更准的预测器”，而是“应该把预测预算留给真正困难的部分，并让分组粒度去适配你手上预测器的真实能力”。通过 `NoDaP` 的 oracle 分析，作者得到三个结论。第一，最热的块其实很容易靠简单规则识别出来，没必要把昂贵 ML 浪费在这里。第二，GC-written block 并不都是“冷数据”，它们的剩余寿命分布很散，单靠 age 重定位会系统性放错地方。第三，group 越细不一定越好；当预测误差上升后，更多 group 只会把误分类代价放大，反而推高 WAF。

因此，合理设计应该是混合式的：最容易分辨的极端情况先用廉价规则隔离，模糊的中间区域再交给轻量 ML，而 group 数量则依据观测到的预测精度动态决定，而不是事先写死。这里 `NoDaP` 的价值很大，因为它把“现有方法可能还差很多”这种模糊直觉，变成了一个清晰的设计参照物。

## 设计

`NoDaP` 是全文的离线参照系。它假设自己知道块未来的准确失效时间，通过穷举搜索得到一组接近最优的 block invalidation range (`BIR`) 和 group 大小，并用更接近最优的 victim 选择策略，给出现实容量限制下可达到的低 WAF。DOGI 的问题则是：这些 oracle 行为里，哪些可以在线近似？

在线系统的布局由一个 hot group `Ghot`、一个 frozen group `Gfrzn` 和 `N` 个中间 group 组成。面对 user-written block，`Hot Filter` 先检查块的 latest invalidation time，把最热的数据直接放进 `Ghot`。它的阈值不是静态的：DOGI 会按时间窗口观察最近 WAF 的变化，如果扩大或缩小 `BIR_Ghot` 的上界能让 WAF 下降，就继续沿那个方向调。只有非 hot 块才会进入 `ML-Alloc`。这里作者没有继续采用又深又慢的序列模型，而是选了一个很轻的 MLP：只用六个特征，把块分到十个寿命类别里，并用 `128` 块 batch inference 加上 double buffering 把预测成本藏到写路径之外；模型每 `26M` 个 user-written blocks 在线重训一次。

第二个关键部件是自适应 group configuration。DOGI 一开始保留十个中间类别，但不会机械地维持十个 group。它维护一个预测日志 `PLog`，其中记录采样块的 `<predicted category, actual invalidation time>`。随后，一个 Markov-chain 模型会利用这些真实误分类数据，估算不同 group 合并方案下的预期 `WAF`；由于相邻 group 的合并方式一共只有 `512` 种，DOGI 可以暴力搜索出最低 WAF 的配置，再据此推导新 group 的 `BIR`。

GC-written block 的处理则是第三个亮点。`Frozen Filter` 借助每块一个 update flag，加上周期性清零的 clock 机制，把几乎不再被更新的数据识别出来，直接送去 `Gfrzn`。其余 GC-written block 进入 `ML-Reloc`。这里 DOGI 不再用粗糙的 age，而是重用 `PLog`：对每个类别，估计它在 GC 时刻的平均“剩余失效时间”，再把块重定位到 `BIR` 覆盖该剩余时间的 group 中。如果块被重定位后依然存活到下次 GC，系统再退回保守的 age-based “下移一组”策略。Victim 选择也延续 `NoDaP` 的思路：优先回收较热 group 中已过期的 segment，实在没有，再去最冷端找 live block 最少的段。

## 实验评估

实验分成 trace-driven simulator 和真实原型两部分。原型运行在 Western Digital `ZN540` `2 TB` ZNS SSD 上，通过 `ZenFS` 构建日志结构环境。默认配置是 `128 GiB` 逻辑容量、`256 MiB` segment、`4 KiB` block 和 `10%` over-provisioning。工作负载包括 `FIO`、运行在 MySQL 上的 `YCSB-A` 与 `YCSB-F`、`Varmail`，以及 Alibaba 云块存储 traces 和 Exchange traces。对比对象是 `SepBIT`、`MiDAS`、`PHFTL`、`ML-DT`，外加 oracle 风格的 `NoDaP`。

最核心的结果是：DOGI 相比所有基线平均把 `WAF` 降低 `25.1%`，相比最佳基线 `MiDAS` 也还能再降 `15.5%`。在 `FIO` 和 `YCSB` 这类偏斜、相对稳定的工作负载上，效果更明显，因为 DOGI 可以安全地维持更多中间 group，user-written block 的预测准确率也能达到 `78-84%`。在 `Varmail`、Alibaba、Exchange 这类更动态的负载上，模型准确率下降，但 DOGI 会通过减少 group 数量来降低误分类代价；如果精度跌破阈值，它还会暂时关闭 ML，回退到更简单的基线式策略，而不是坚持使用一个错误的模型。

组件拆分实验基本支撑了论文的机制解释。对于 user-written block，DOGI 的混合策略在准确率上优于只看 latest invalidation time，也优于 ML-DT 那种更重的纯 ML 方案，同时推理成本低得多。对于 GC-written block，`PLog` 驱动的 relocation 在除 Exchange 之外的所有工作负载上都比 age-based relocation 更准，并平均把这部分策略带来的 `WAF` 再降 `8.1%`。关于 group configuration 的实验尤其有说服力：不同工作负载对应的最优 group 数量并不一样，而当预测器被迫区分过多类别时，WAF 会非常快地恶化。

原型结果说明这些收益不是模拟器幻象。DOGI 的写吞吐分别比 `ML-DT`、`PHFTL`、`SepBIT`、`MiDAS` 高 `19.4x`、`1.19x`、`1.17x` 和 `1.09x`，平均推理延迟只有 `0.39 us`。它的 read latency 与 MiDAS 接近，甚至略低，说明计算开销大多被隐藏住了。真正的保留意见在于：论文最强的证据仍然集中在写密集场景和 WAF，本身也承认相对 `NoDaP` 还有一段不小的距离。

## 创新性与影响

相对 `MiDAS`，DOGI 的新意不只是“也会调 group 数量”，而是把 group 配置与实测预测误差紧耦合起来，并把同样的精细化思想扩展到了 GC-written block relocation。相对 `PHFTL` 和 `ML-DT`，论文提出的反驳更有价值：问题不在于 ML 还不够重，而在于应该先用便宜规则剥离简单样本，再让轻量模型处理真正模糊的部分。更深一层的贡献则是方法论上的，`NoDaP` 给社区提供了一个可操作的上界基线，让研究者能把 WAF 的损失拆成 user placement、GC relocation 和 grouping 三部分来分析。

因此，这篇论文很可能会被 SSD firmware、LSM 存储引擎、ZNS/日志结构系统的设计者引用。它既提出了新机制，也重新定义了“oracle-guided storage design”在工程上应该如何落地。

## 局限性

DOGI 并不是放之四海而皆准。面对高度动态的 traces，它的预测精度会明显下滑，而 fallback 机制本身就说明现有 ML 模型还不足以在所有负载下长期无人值守。内存开销在论文规模下不算夸张，`128 GiB` 设备需要 `68 MiB`，但它会随着容量线性增长；作者估算到 `64 TiB` 时会达到 `34 GiB`。

实验也留下了一些边界问题。工作负载集合对于写密集场景已经很广，但依旧主要服务于 WAF 论点，而不是混合生产业务中更强的读敏感性或延迟敏感性。整个设计依赖在线重训、per-block metadata 和多个耦合控制机制，所以“可部署”不等于“免费部署”。最后，由于 DOGI 与 `NoDaP` 之间仍存在明显差距，这篇论文更像是向最优解推进了一大步，而不是彻底终结了这个问题。

## 相关工作

- _Oh et al. (FAST '24)_ — `MiDAS` 会自适应调整 group 数量和大小，但 user-written block 仍主要依赖 latest invalidation time，GC-written block 仍依赖 age；DOGI 则用 oracle 指导的混合预测与 relocation 取代这些近似。
- _Wang et al. (FAST '22)_ — `SepBIT` 按推断的 invalidation time 分离数据，但它级联式的 GC groups 无法表达 GC-written block 寿命分布的宽广多样性，而这正是 DOGI 重点暴露并利用的地方。
- _Chakraborttii and Litz (SYSTOR '21)_ — `ML-DT` 用更重的 TCN 来预测 user write 的 death time；DOGI 的论点则是先过滤掉容易判别的样本，可以让更轻的模型同时获得更好的速度与精度。
- _Sun et al. (DAC '23)_ — `PHFTL` 把 GRU 引入到 user-written block prediction，但 GC relocation 和 group configuration 仍更接近传统启发式，没有像 DOGI 那样形成跨三条路径的一体化设计。

## 我的笔记

<!-- empty; left for the human reader -->

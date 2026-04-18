---
title: "Preventing Network Bottlenecks: Accelerating Datacenter Services with Hotspot-Aware Placement for Compute and Storage"
oneline: "论文把持久 ToR 热点视为放置问题：让 Borg 避开高利用率机架、让 Colossus 偏向高上联容量机架，从而把热点 ToR 降低 90%，并把存储网络 p95 延迟降到原来的一半以下。"
authors:
  - "Hamid Hajabdolali Bazzaz"
  - "Yingjie Bi"
  - "Weiwu Pang"
  - "Minlan Yu"
  - "Ramesh Govindan"
  - "Neal Cardwell"
  - "Nandita Dukkipati"
  - "Meng-Jung Tsai"
  - "Chris DeForeest"
  - "Yuxue Jin"
  - "Charlie Carver"
  - "Jan Kopański"
  - "Liqun Cheng"
  - "Amin Vahdat"
affiliations:
  - "Google"
  - "Harvard University"
  - "University of Southern California"
  - "Columbia University"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - networking
  - datacenter
  - storage
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文认为，持续存在的数据中心热点很多时候不是传输层问题，而是放置问题。Google 在生产系统里加入了两条轻量级启发式：让 Borg 在任务放置和迁移时偏向更“冷”的 ToR，让 Colossus 在放置数据块时偏向“上联带宽相对存储容量更充足”的机架。结果是热点计算 ToR 数量下降 90%，存储和查询的尾延迟也显著下降。

## 问题背景

Google 的 Clos 网络里，真正麻烦的热点主要出现在 ToR 到 aggregation block 的上联。论文基于全网一个月的遥测发现，这一层链路成为热点的概率约是 host-to-ToR 链路的 10 倍、DCNI 链路的 2 倍。约三分之一持续不到 1 小时，接近 40% 持续 1 到 12 小时，约 13% 会持续 1 天到 2 周。Mixed rack 和 Disk rack 合计占了约 90% 的热点，因此存储相关服务承受了大部分影响。

根因是“结构性失衡”叠加“网络盲的放置策略”。ToR 本来就是按 oversubscription 规划的，而计算节点升级、更密或更快的磁盘、临时上联缩减，都会改变机架级带宽供需。Borg 和 Colossus 又长期按照“网络通常不是瓶颈”的假设做任务与数据放置，于是很容易把大量网络密集型 worker 或过多存储容量堆到同一台 ToR 后面。拥塞控制、负载均衡和 traffic engineering 能更好地利用既有路径，但无法凭空补上缺失的 ToR 上联带宽。

## 核心洞察

论文最值得记住的命题是：持久 ToR 热点应通过改变工作和数据落点来解决，而不只是继续优化网络内部控制。它背后的经验事实是一个明显的阈值效应：不少应用在 ToR 利用率接近 75% 前仍可接受，但一旦越过该门槛，尾延迟就会明显恶化。既然全网平均 ToR 利用率依然偏低，那么只要以 best-effort 方式偏向更冷、供需更平衡的机架，就能去掉很大一部分热点，而不必把网络彻底做成被严格预留和统一管理的一级资源。系统不需要全局最优联合调度，只需要足够的网络感知来避免显然错误的机架级放置。

## 设计

设计分成两部分。第一部分是 Borg 里的 ToR-utilization-aware task placement and migration，也就是 UTP。Borg 本来就会在随机抽样的一组候选机器上，根据多个目标做打分。UTP 保留了这一结构，只是改写了一个优先级较低的负载均衡目标：如果某台机器所在 ToR 更冷，那么它会得更高分。这个分数结合了瞬时 ToR 利用率和任务的峰值带宽需求估计。当 ToR 超过 75% 利用率时，Borg 会优先迁移带宽占用高、但对延迟更宽容的任务，并且只在 availability budget 允许时才迁移。目标不是求解全局网络优化，而是以最小扰动压住热点。

第二部分是 Colossus 里的 ToR-capacity-aware chunk placement，也就是 CCP。它按“已配置 ToR 上联能力”相对“已安装存储容量”的关系，把机架分成 High-Uplink、Medium-Uplink、Low-Uplink 三类，然后在新 chunk 放置时优先选 High-Uplink 机架。论文刻意保持 CCP 的简单性；除这种优先级顺序之外，没有进一步说明更细的打分规则。

## 实验评估

证据来自交换机遥测、一天的 Dapper HDD trace、七个 QuerySys benchmark、pilot cluster，以及后续的全网 rollout。在 QuerySys 中，最网络密集的 shuffle flush 的 1.5x Load-tolerance 只有 70%；materialize 是 75%；aggregation 是 85%；更轻的查询在 90% 到 95%。论文还用 compute ratio 解释了差异来源：计算占比越高，查询越不容易被网络热点放大。

Colossus 的读写行为更明显。对 HDD read 而言，75% 热点门槛处网络延迟膨胀 4x，但总读延迟只膨胀约 1.5x，因为磁盘时间仍占主导；其 2x Load-tolerance 高达 95%。HDD write 则脆弱得多，因为 write-back caching 让网络占比更高，因此 2x Load-tolerance 只有 50%，Hotspot-inflation 约为 4x。论文还表明，最高 ToR 利用率对应的存储请求几乎都落在 Low-Uplink 机架上，这直接支撑了 CCP。

部署结果是最核心的部分。UTP 全网 rollout 后把热点计算 ToR 数量减少了 90%。在一个 pilot cluster 中，它将 p98 出向 ToR 利用率降低 18.5%，且作者没有观察到 Borg 其他关键目标回归；若移除 proactive placement，迁移次数几乎翻倍，网络密集型任务落到热点 ToR 的概率约高 7 倍。QuerySys 的 p95 延迟最高改善 13%。在一个 15 天 CCP pilot 中，Colossus 的 p95 网络延迟下降 50% 到 80%，总 HDD 读延迟下降 30% 到 60%。这些证据对 Google 场景很有说服力，但主要仍是上线前后对比，而非与更强网络感知调度器的受控对照。

## 创新性与影响

这篇论文最重要的价值，是把“持久机架热点应靠移动工作和数据来缓解”做成了可落地的生产方案。它不是在发明新协议，而是在说明：对大型数据中心运维者来说，只要给成熟调度器和存储系统注入足够的网络感知，就能获得很大收益。

## 局限性

这套方法明确只是 best-effort，并不保证 SLO；论文也只覆盖传统 compute/storage 集群和持续性的 ToR 热点，不涉及 ML cluster 或秒级突发拥塞。评估大量依赖 Google 的生产遥测和 pilot，工程说服力很强，但外部很难复现。论文没有和把网络作为完整一级资源建模的调度器做正面对比，CCP 的细节也只给到高层，因此它证明的是“轻量启发式有效”，而不是“已经接近最优”。另外，5 分钟热点窗口和 30 秒利用率归因也让更短时的拥塞基本不在研究范围内。

## 相关工作

- _Chen et al. (NSDI '22)_ - NetHint 把网络结构和瓶颈暴露给租户应用自行适配，而这篇论文把热点处理留在云提供方内部，通过调度器和存储系统本身来完成。
- _Rajasekaran et al. (NSDI '24)_ - CASSINI 为 ML 作业做网络感知调度，而这篇论文把相似的经验推广到传统 compute/storage 服务，并重点处理持久性的 ToR 失衡。
- _Jalaparti et al. (SIGCOMM '15)_ - Corral 一类工作会显式为数据并行作业规划带宽，而这篇论文强调的是可以嫁接到现有生产调度器上的、best-effort 的简单启发式。

## 我的笔记

<!-- 留空；由人工补充 -->

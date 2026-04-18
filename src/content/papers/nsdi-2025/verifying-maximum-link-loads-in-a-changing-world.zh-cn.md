---
title: "Verifying maximum link loads in a changing world"
oneline: "Velo 把 route changes 抽象成 egress 选择，再用流量聚类压缩目的前缀空间，从而在 failures 与 BGP 变更下验证每条链路的最坏负载。"
authors:
  - "Tibor Schneider"
  - "Stefano Vissicchio"
  - "Laurent Vanbever"
affiliations:
  - "ETH Zürich"
  - "University College London"
conference: nsdi-2025
category: network-verification-and-synthesis
code_url: "https://github.com/nsg-ethz/velo"
tags:
  - networking
  - verification
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Velo 是论文所称第一个能够在同时考虑内部 failures 与外部 BGP route changes 时，计算网络中每条链路最坏负载的系统。它的核心做法是把庞大的 route-advertisement 空间收缩为 egress-router 选择，再证明在 strictly isotone 的内部路由下，只看每个目的前缀的 single-egress 状态就足以覆盖每条链路的最坏情况，最后再用带误差界的流量聚类压缩 traffic matrix。对大型 ISP 风格拓扑，原型在论文关注的实用区间内能在几分钟到几小时内完成计算，而且近似误差始终低于 1%。

## 问题背景

运营者之所以关心 worst-case link load，是因为真正把常规路由波动变成丢包、时延膨胀和紧急 traffic engineering 的，往往不是平均负载而是峰值负载。只测量当前网络并不够，因为链路会失效，BGP 路由会出现、撤回和变化，而少量目的前缀在边界路由器上的 egress 改变，就可能把大量流量重新压到完全不同的内部路径上。论文的动机图表明，在一个真实 ISP 网络中，如果在一跳和两跳链路失效之外再允许 route changes，核心链路承受的额外负载大致会翻倍。

现有工具在这里有两种失配。大多数 network verification 系统验证的是 reachability、loop 或 control-plane correctness 之类的功能性质，而不是性能性质。少数研究负载的系统通常又假设外部路由固定，这在受控 datacenter 里还能接受，但对 Internet-facing 的 ISP 就不够了。一旦允许 route changes，搜索空间立刻失控：每个 destination 都可能新增、丢失或修改路由；route attributes 的取值域非常大，甚至无界；而 failures 又把不同 destinations 耦合起来，因为一次失效会同时改变许多转发路径。按目的前缀逐个验证的方法因此不再可行。

## 核心洞察

Velo 的第一层洞察是：为了分析 worst-case load，它不需要显式建模完整的 BGP advertisements。真正决定内部转发和链路负载的，是某个 destination 可以经由哪些 border routers 出网。很多具体的 BGP routes 虽然属性不同，但只要它们诱导出相同的 egress 选择，链路负载就是一样的。这个 router-based abstraction 已经把巨大的符号状态空间压缩成了有限的 egress 组合空间。

更关键的洞察来自内部路由结构。对于 shortest-path 一类 strictly isotone 的 intra-domain routing，给定某条链路和某个 destination，该链路的最坏负载会出现在整个网络都等价于只使用一个 egress router 转发该 destination 的时候。这样，原本需要枚举 egress 子集的指数级搜索，就被压缩成对 border routers 的线性扫描。如果网络中配置了 MPLS traffic-engineering tunnels 之类的 exception paths，这个定理不再原封不动成立，但论文证明只需在“一个普通 egress”之外，再枚举这些 exception paths 终止的 egresses 即可。随后，论文再配上 traffic-matrix approximation：把那些在各 ingress routers 上呈现相似流量分布的 destinations 聚到一起，并用 clustering error 来界定 worst-case load 的近似误差。

## 设计

Velo 的输入包括 router configurations、当前 BGP routes、按 ingress router 与 destination prefix 索引的 traffic matrix、运营者对 route changes 的约束，以及需要考察的 failure scenarios。之所以采用“按 destination”而不是“按 ingress/egress 对”来表达流量，是因为 BGP 变化本身就是 destination-specific 的。运营者还可以额外指定允许发生变化的 egress 数量上限、声明某些 destinations 是稳定的，或限制某些 prefixes 只能从哪些 border routers 学到路由。

对固定拓扑和单个 destination，Velo 搜索的是 egress 选择，而不是原始的 BGP attributes。对于 strictly isotone routing，它以每个 border router 为根构造 forwarding DAG，把该 destination 的流量沿 DAG 按拓扑序向前推进，并记录每条链路可能承受的最大贡献。对所有 destinations 重复这件事，就能以多项式时间得到每条链路的 worst-case load，而不必枚举指数级的 route combinations。如果网络里存在 exception paths，Velo 只把搜索扩展到包含这些路径终止 egress 的小型组合上，以此在保持正确性的同时避免状态爆炸。

系统还处理了两个现实问题。第一，如果运营者只关心最多 `k` 个 route changes，Velo 就为每条链路维护一个大小为 `k` 的堆，记录那些让该链路负载增幅最大的 destinations。第二，真实路由表往往有近百万个 destinations，直接逐个分析仍然太慢，所以 Velo 会先压缩 traffic matrix。它只把满足两类条件的 destinations 聚在一起：当前使用相同的 egress 集合，并且在任何允许的 egress 选择下都具有相同的 forwarding behavior。然后系统在这些 destination 的 ingress 分布上运行一种经过归一化、按流量加权的 k-means 变体。得到的近似矩阵不仅更小，而且伴随一个明确保证：clustering error `ε` 上界 worst-case link load 的近似误差 `δ`。对于额外流量不确定性，运营者可以给出一个总预算 `y`；Velo 先在名义 traffic matrix 上求最坏负载，再把每条链路至多增加 `y`，论文认为在常见场景下这是精确的。

## 实验评估

原型大约有 7,000 行 Rust 代码，评估覆盖了 Topology Zoo 中最大的 75 个网络，规模从 80 条链路到 1,790 条链路不等，同时使用了真实流量矩阵和合成流量矩阵。对论文宣称要解决的问题区间，扩展性结果是扎实的。在最多两条链路同时失效、30 个 border routers、300 个 traffic clusters 的设置下，Velo 在最大的 1,790-link 拓扑上分析单链路失效约需 1 分钟，分析双链路失效约需 3 小时；其余所有拓扑在最多两条失效时都能在 2 分钟内完成。论文还指出，当网络变大后，真正主导总时间的是分析阶段而不是聚类阶段。

精度结果同样有说服力。对来自 Swiss research network 的四个真实 traffic matrices，理论误差界约为 3.5% 到 5.6%，而实际 approximation error 只有约 0.4% 到 0.7%。在按 gravity model 合成、并被刻意做得更难压缩的流量矩阵上，近似误差仍然保持在 1% 以下。论文还把自己的聚类方案与一个只保留最大流量 destinations 的 heavy-hitter 基线做了比较：为了得到同等级别的保证，Velo 的方法通常只需要对方 1/5 到 1/50 的有效 destination 数量。

与 QARC 的比较也很关键，因为 QARC 是最接近的 link-load verification 系统。在不允许 route changes、因而两者可直接比较的设置下，Velo 在最多两条 simultaneous failures 时快出好几个数量级；即便把失败数增加到三条或四条，它仍然快 10 倍到 100 倍。论文认为，根本原因在于 Velo 把问题化简成重复的图计算，而不是去求解 ILP。最后的 ISP case study 也说明了系统价值：Velo 发现一个 126-router ISP 只需 4 次 egress changes 就会有两条链路超载，随后又指出增加若干 MPLS paths 可以把鲁棒性提升到承受 16 次变化，并帮助评估“新增一条 IXP 链路”是否优于单纯升级带宽。

## 创新性与影响

这篇论文的创新点不只是又做了一个 link-load checker。Velo 的真正贡献，是提出了一个让 worst-case performance verification 变得可计算的抽象边界：把 route changes 提升到 egress-router level 去思考，再用一个定理把最坏情况搜索压缩到很小的状态集合。traffic clustering 的定理同样重要，因为它把“只能看少量重要 prefixes”的工程妥协，推进成了“可以覆盖完整 routing table 且有显式误差保证”的系统能力。

因此，这项工作不只适合离线 what-if analysis。运营者可以在部署前验证配置，在日常调参时寻找更稳健的 BGP 偏好和内部路径，在做 peering 或容量升级决策时评估风险，也可以把它作为快速 traffic-engineering 反应的触发器。我预计后续关于 performance-aware control-plane verification 的工作，会主要引用这篇论文的抽象思路：分析 egress choices 与可量化的 traffic uncertainty，而不是试图直接穷举原始 BGP message space。

## 局限性

Velo 最强的定理依赖 strictly isotone 的 intra-domain routing。论文确实把算法扩展到了 exception paths，但前提依然是这些 exception 足够显式、足够少，以至于它们终止的 egresses 可以被枚举。若网络里存在更复杂的策略交互，或者存在大量人工设计的工程路径，这套效率结论就可能被削弱。

系统模型本身也排除了若干真实世界复杂性。它假设路由器最终都能学到自己偏好的 routes，不存在 iBGP visibility problems，并要求 destinations 彼此独立，因此不涵盖 route aggregation 或 conditional advertisements 之类把不同前缀绑在一起的特性。Velo 计算链路负载时只是简单地累加经过该链路的流量，并不模拟真正发生拥塞后下游负载如何因丢包而下降。额外流量模型是保守的，某些链路会被高估，而“新出现的更细粒度子前缀”这种目的集合本身变化的系统性探索，也被留作未来工作。

## 相关工作

- _Subramanian et al. (PLDI '20)_ - `QARC` 在 failures 下验证 link-load violations，但假设外部 routes 固定；`Velo` 则把 route changes 也纳入模型，并直接计算所有链路的 worst-case loads。
- _Li et al. (NSDI '24)_ - `Jingubang` 面向生产规模网络推理 traffic-load properties，但主要针对给定场景；`Velo` 关注的是 failures 与有界 route changes 上的穷举式 worst-case analysis。
- _Li et al. (SIGCOMM '24)_ - `YU` 把 traffic-load verification 推广到任意 `k` failures，但仍停留在 fixed-route 世界，而 `Velo` 的核心论点正是 Internet-connected 网络不能忽略 route changes。
- _Steffen et al. (SIGCOMM '20)_ - `NetDice` 可以表达概率化的 link-load properties，但 `Velo` 论文认为它无法扩展到 worst-case load verification 所需的大量 ingress-destination pairs。

## 我的笔记

<!-- 留空；由人工补充 -->

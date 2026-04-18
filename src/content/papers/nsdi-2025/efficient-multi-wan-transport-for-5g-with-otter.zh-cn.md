---
title: "Efficient Multi-WAN Transport for 5G with OTTER"
oneline: "OTTER 为每条 5G 流同时选择 compute destination 和 multi-WAN overlay path，在改进吞吐/RTT/jitter/loss 的同时，比贪心路由多承载 26%-45% 的需求。"
authors:
  - "Mary Hogan"
  - "Gerry Wan"
  - "Yiming Qiu"
  - "Sharad Agarwal"
  - "Ryan Beckett"
  - "Rachee Singh"
  - "Paramvir Bahl"
affiliations:
  - "Oberlin College"
  - "Google"
  - "University of Michigan"
  - "Microsoft"
  - "Cornell University"
conference: nsdi-2025
project_url: "https://otter-5gwan.github.io/"
tags:
  - networking
  - datacenter
  - virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

OTTER 的核心观点是: 当 5G network functions 和应用被迁到云里后，端到端性能不再只是 routing 问题。它把 compute destination 和跨 operator WAN 与 cloud WAN 的 overlay path 一起选，用 demand function 同时表达 throughput、RTT、jitter、loss 和 compute capacity 需求。在覆盖美国大陆的 Azure+GCP 部署上，OTTER 能持续找到比默认路径更好的性能折中，而它的周期性优化器比贪心放置多分配 26%-45% 的字节量。

## 问题背景

论文的出发点是 5G 架构本身发生了变化。越来越多的无线网络功能被拆成软件 NF，最敏感的部分留在 operator edge，其他部分，例如 5G core 中的一些组件和云上的交互式应用，则部署在 cloud edge 或 cloud datacenter。这样一来，一条用户流量从接入侧到被服务的 NF 或应用，往往要跨越 operator WAN 和 cloud WAN 两张广域网。

现有机制把这件事拆成互相独立的子问题，而这正是失败的来源。像 5G NRF 这样的 compute selector 可以根据服务器可用性挑 destination，却不看抵达该 destination 的网络路径。单个 WAN 内部的 traffic engineering 可以在本域里优化路由，但它既看不到跨两个管理域的端到端路径，也不知道换一个 destination 可能整体更优。论文里的玩具例子说明了这种失配: 两个 WAN 分别选择各自局部最优的路径段后，拼起来的端到端路径反而差于另一条谁都不会单独选中的全局路径。

问题之所以严重，是因为 5G 流量的异质性远超传统 WAN TE 的抽象能力。有的流追求 throughput，有的对 jitter 极其敏感，有的要求很低 RTT，还有的主要关心 loss。同时，edge 站点 compute 很紧，而 cloud DC 虽然远，却有更充足的资源。周期性的 TE 重算和少数几个粗粒度 priority class 在这里都太钝了，因为 5G 的 per-flow 需求是按需到达的，而且“正确”的选择同时取决于 endpoint 放在哪里以及去往那个 endpoint 的路径是什么。

## 核心洞察

论文最重要的判断是: cloudified 5G 本质上形成了一个 joint placement-and-routing problem，应该直接联立求解，而不是继续把 compute selection 和每个 WAN 内部的 routing 分开近似处理。只要 serving 的 NF 或应用能够在 operator edge、cloud edge、cloud DC 之间移动，path 与 destination 就是无法分离的两个控制变量。

OTTER 让这个问题变得可解的方法，是用 demand function 来表示服务目标。系统不再把流量粗暴塞进固定 priority class，而是把候选路径上每个 metric 的取值映射成一个 `(0, 1]` 范围内的 tolerance coefficient。这样，同一个优化目标就能比较 RTT、jitter、loss、throughput 偏好完全不同的流，而不必假装所有服务需求都能被压缩成同一种“高优先级”。论文更大的主张是: 只靠 overlay 层可见的测量数据和 operator 与 cloud 已经对齐的商业激励，就足以解决这个问题，不需要私有 underlay 数据、BGP 改造，或跨提供商的协商协议。

## 设计

OTTER 由两个主要部分组成: Controller 和 Orchestrator。Controller 通过 "Quality on Demand" 风格的 API 接收 per-flow QoS 请求，请求中包含 flow 标识以及目标服务画像。随后它求解论文所说的 multi-WAN flow placement problem: 为一个流同时选择 destination site 和一条或多条 overlay path，以满足它的网络与 compute 需求。

优化模型是整篇论文的技术核心。每条候选路径都带有实测的 throughput、RTT、jitter、loss，以及它经过的 link 集合。每个流则有 source、可选 destination 集、请求带宽、各 metric 的 demand function，以及 CPU、memory、storage 的资源向量。线性规划使用两个决策变量: 一个是分配到 flow-path 对上的带宽，另一个是给该流在某个 destination 上预留的资源量。目标函数最大化“已分配流量”与“tolerance coefficient 之和”的乘积，并再按请求带宽归一化，避免大流天然主导结果。约束则分别限制请求带宽、每条链路容量、destination 资源上限，以及某个 destination 上分到的 compute 与该 destination 上承载的流量份额一致。

由于 5G 请求是按需到达的，论文没有指望 LP 单独承担全部在线决策。OTTER 先用一个 greedy heuristic 立即安置新到达的流，再在后台周期性运行完整优化器。对 RTT 和 jitter 敏感的流，系统还可以选择 path pinning 或 destination pinning，以避免频繁迁移带来的 disruption 和 packet reordering。这是一个很重要的工程折中: 系统接受短时间内的次优解，以换取足够快的反应速度。

Orchestrator 负责把这些控制决策真正实现为跨 GCP 与 Azure 的 overlay。它使用 private subnet、VPN gateway、VPC/VNet peering、多个区域的 VNet，以及 user-defined route 来转发流量，而不要求用户自己部署 BGP speaker 或 packet forwarder。Measurement Coordinator 持续用 iPerf3 测 throughput、用 sockperf 测 RTT/jitter，把滑动窗口的中位数写入 Cosmos DB，再反馈给优化器。原型刻意建立在云原生基础设施之上，而不是依赖专有网络设备; 论文真正的贡献是如何从云平台已经暴露的 primitive 中合成 multi-WAN path 和 endpoint placement。

## 实验评估

实验分成两部分。第一部分是 Orchestrator 的真实部署评估: 系统跨美国大陆的 Azure 与 GCP 区域部署，在 64 个 source-destination VM 对之间评估 512 条候选路径，并在 24 小时内重复测量约 20 轮。相对于普通云路由选择的默认路径，OTTER 的 throughput 平均提升 13%，最佳情况提升 136%，跨云峰值吞吐超过 20 Gbps。对 latency-sensitive 流量，它把 RTT 平均降低 15%，最好可减少 42 ms。jitter 平均下降 45%，平均 loss 从 0.06% 降到 0.001% 以下。最有价值的定性结论是，不同 overlay path 分别擅长不同 metric，因此 OTTER 真正在利用 path diversity，而不是简单地找到一条对所有指标都完胜的“万能路径”。

第二部分是 Controller 的规模化评估: 使用前述真实部署测得的路径分布，再叠加合成的 5G 流到达过程和参考 3GPP 的应用画像。这里的重点是分配器质量。带周期性重优化的方案，加上 path pinning 或 destination pinning 后，比纯贪心方案多分配 26%-45% 的字节量，而且离“无限快优化器”版本只差约 10%。在 40K flows/s 的到达率下，带 pinning 的方法能让大约 47% 的流获得完美 RTT 满足度，而贪心方案只有 41%，同时显著减少被送到几乎无用 RTT 路径上的流。论文还证明，忽略 destination resource constraint 是严重错误: 一旦把 oversubscribed edge site 的实际可服务能力算进去，有效分配字节量会下降 23%-50%。

整体上，这组实验基本支撑了论文的中心论点，但需要区分两类证据。路径编排收益来自真实 multi-cloud 部署，因此很有说服力地证明了 overlay 能找到更好的端到端选择。Controller 的收益虽然建立在真实测量到的路径分布之上，但流量画像和资源容量仍是合成的，所以它更有力地验证了优化模型本身，而不是直接证明它在真实运营商网络上的生产表现。

## 创新性与影响

OTTER 所处的位置很特别。和 `Skyplane` 这样的系统相比，它不是为对象存储之间的 bulk transfer 在 cost 与 throughput 之间做静态折中。和 `SWAN`、`OneWAN` 这类单 WAN TE 系统相比，它也不只是把流量重新分配到单个管理域中的少数几个服务等级。再和 `Nexit`、`Wiser` 这类跨域协调工作相比，它不依赖竞争 ISP 之间的显式协商，也不要求交换私有拓扑信息。

因此，这篇论文的创新既是 mechanism，也是 framing。机制上，它把 endpoint placement、multi-metric path selection 和 endpoint resource constraint 合并到一个 LP 支撑的 Controller 里，并给出可部署的 overlay 实现。概念上，它强调 5G 云化改变了控制问题本身: 当流量和 NF 横跨 operator WAN 与 cloud WAN 时，服务质量必须通过联合编排两者来获得。这使它对未来的 cloud-hosted mobile core、edge-cloud placement，以及跨管理域的 service-aware transport 都有参考价值。

## 局限性

OTTER 只能优化 overlay 层已经暴露出来的路径和云原语。论文明确把隐藏 underlay path、WAN monetary cost，以及跨多个 hyperscaler 的部署留到未来工作中。如果某个 WAN 内部其实还存在更多 path diversity，但没有通过 overlay 暴露出来，OTTER 就无法利用。

此外，原型与目标部署之间仍有现实差距。路径编排实验把 GCP 当作 operator WAN 的替代，而不是真实 carrier backbone; Controller 的研究也依赖合成到达流量和抽样资源容量。最后，周期性重优化意味着在 LP 求解期间，新流仍要先走 greedy placement; path pinning 虽然减少了对 RTT/jitter 敏感流的扰动，但也会阻止部分本来有利的重新分配。因此，这篇论文证明的是一个可信的机制，而不是对所有 5G 流量管理问题都已给出完整运营答案。

## 相关工作

- _Jain et al. (NSDI '23)_ - `Skyplane` 同样使用 cloud overlay，但它面向的是 bulk inter-cloud transfer 中 cost/throughput 的静态折中，而 `OTTER` 处理的是带有 RTT、jitter、loss 和 compute constraint 的实时 5G 流。
- _Hong et al. (SIGCOMM '13)_ - `SWAN` 代表的是周期性、单 WAN、粗粒度优先级的 TE，而 `OTTER` 做的是跨两个 WAN 的 per-flow 放置，并显式建模 destination resource capacity。
- _Mahajan et al. (NSDI '05)_ - `Nexit` 通过协商来协调相邻 ISP，而 `OTTER` 利用 operator 与 cloud 已经对齐的激励，避免协议改动和私有数据交换。
- _Birge-Lee et al. (HotNets '22)_ - `Tango` 通过暴露更多路径来提升 edge-to-edge path choice，而 `OTTER` 还会进一步配置云资源，并决定哪个 compute destination 来服务该流。

## 我的笔记

<!-- empty; left for the human reader -->

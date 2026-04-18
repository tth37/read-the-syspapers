---
title: "Learnings from Deploying Network QoS Alignment to Application Priorities for Storage Services"
oneline: "Aequitas 按 RPC 优先级把存储流量映射到 DSCP/WFQ 队列，并在生产环境证明：修正 QoS 错配后，即使部分流量被降级，尾时延也可能整体下降。"
authors:
  - "Matthew Buckley"
  - "Parsa Pazhooheshy"
  - "Z. Morley Mao"
  - "Nandita Dukkipati"
  - "Hamid Hajabdolali Bazzaz"
  - "Priyaranjan Jha"
  - "Yingjie Bi"
  - "Steve Middlekauff"
  - "Yashar Ganjali"
affiliations:
  - "Google LLC."
  - "University of Toronto"
conference: nsdi-2025
tags:
  - networking
  - datacenter
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Aequitas 在 RPC 粒度上为存储流量分配网络 QoS，而不是继续相信用户手工选择的 QoS。论文的核心结论是：生产环境里的优先级反转主要来自全局队列错配；只要把 RPC 优先级重新对齐到健康的 QoS 配比上，即使一部分流量被降级，也可能让整体尾时延更低。

## 问题背景

论文讨论的是应用层优先级与交换机实际执行的 DSCP/WFQ 调度之间的脱节。在 Google 存储系统里，不同 RPC 的时延需求差别很大：Performance-Critical（PC）RPC 面向交互式、尾时延敏感场景，Non-Critical（NC）RPC 更像吞吐导向的存储操作，Best-Effort（BE）RPC 则是后台工作。但在实际生产环境中，用户往往在看到 SLO 违约后就申请更高 QoS，久而久之形成前作所说的 race-to-the-top：越来越多流量挤向高优先级队列，结果是高权重队列反而可能比低权重队列更拥塞，出现 priority inversion。

论文进一步指出，按应用或作业整体设置 QoS 太粗糙。虽然大多数作业只使用一种优先级，但真正占据大部分字节量的是那批同时含有两种甚至三种优先级 RPC 的大型作业。同一个作业内部既有必须压尾时延的 RPC，也有可以忍受更高网络时延的 RPC。如果整个作业继承同一个 QoS，网络就失去了它最需要的区分信息。

此外，这个问题不能只停留在“理论上应该怎么映射”。系统必须跨多个存储层工作，要区分 intra-cluster 流量与受不同带宽策略约束的 WAN 流量，还不能为了做 QoS 决策引入新的 CPU、内存或端到端开销。更现实的约束是部署：如果高优先级流量出现回退，或者用户看不懂为什么自己的流量被降级，那么 Aequitas 就不可能成为默认策略。

## 核心洞察

论文最重要的判断是：对存储 RPC 来说，正确的网络调度单位是 priority，而不是 size；同时，决定时延的并不是“这个队列名义上更高”，而是“这个队列在当前全局流量分布下是否健康”。Aequitas 因此不去预测流大小，也不引入新的传输协议，而是把来自应用的元数据映射为 BE、NC、PC 三类优先级，再一一映射到 `QoSl`、`QoSm`、`QoSh`。

真正非直觉的地方在于论文对 QoS 的解释。对两个 WFQ 队列来说，如果高权重队列相对其权重已经过载，那么把一小部分流量移到低权重队列，反而可能提升该客户端的服务率。这就是论文解释“降级为什么有时会更快”的方式：不能只问“这个队列级别是不是更低”，而要问“在当前 fleetwide mix 下，哪个队列更空、更健康”。Aequitas 的任务不是机械地把关键流量都抬高，而是恢复一个不会产生优先级反转的全局配比。

## 设计

Aequitas 的设计非常保守。它不要求新交换机原语，也不要求主机运行全新的拥塞控制，而是直接复用已有的 DSCP 标记和交换机上的 weighted fair queuing。每个存储系统向 Aequitas 提供 RPC 的元数据特征，Aequitas 把这些特征映射到三种应用优先级，再由网络按照静态的 priority-to-QoS 映射执行调度。

具体实现按存储层拆分。对于 lower-level（LL）存储，Aequitas 放在服务端，因为 LL 层对用户大多不可见，而且服务端部署一旦落地，打到该服务器的所有流量都会一起切换，更容易快速收敛。其过程是：RPC 的前几个包仍沿用原始 QoS，等请求到达 LL 服务器后，由服务器端 Aequitas 为该 RPC 选定新 QoS，之后双向后续报文都使用更新后的类别。对于 upper-level（UL）系统，例如面向 Spanner 或 Bigtable 的路径，Aequitas 放在客户端，这样用户在发包前就能直接看到 RPC 将使用的 QoS，更容易将性能变化与自己的 SLO 联系起来。

论文还把 rollout machinery 当成系统设计的一部分。由于某个客户端的性能不仅取决于它自己的 QoS 分布，还取决于同队列里所有其他流量，简单的“启用前/启用后”对比并不可靠。团队因此加入了随机采样能力，让只有一部分 RPC 服从 Aequitas；同时优先选择由单一大客户主导的 cluster，便于在 cluster 级别观察影响。分析侧则把 Dapper 的 per-RPC tracing 与 Monarch 的高层指标结合起来：前者提供 RPC priority、requested QoS、Aequitas chosen QoS 与 RNL 分解，后者用来核对更长时间尺度上的尾部行为。

## 实验评估

这篇论文的证据几乎完全来自生产环境，而不是独立测试床。作者在高负载 cluster 上进行 50% 左右的随机采样，把 obey Aequitas policy 的 aligned 流量和同一客户端、同一 cluster 中的 misaligned 流量直接对比。

第一组结果说明，size 不是合适的抽象。Figure 6 显示，无论小 RPC 还是大 RPC，都会分布在三个优先级中，因此单靠流大小无法告诉网络谁更重要。把 RNL 视为总 RPC latency 的一部分来比较后可以看到，PC RPC 从高权重 QoS 中获益最大，而 BE 流量对网络优先级最不敏感。

对一个占据 cluster 超过一半流量的 Spanner 大客户，哪怕只让 50% 流量对齐，收益也极不对称：BE 和 NC 的 RNL 仅有轻微上升，但 PC 的尾时延显著下降。论文明确给出，PC 流量 maximum p99 RNL 的下降幅度，超过 NC 流量 maximum p99 RNL 上升幅度的 150 倍。总 RPC latency 也表现出同样趋势，这说明这些错配的 PC RPC 的确被网络瓶颈卡住，而不是其他组件主导。

论文最有代表性的案例，是那个原本几乎所有流量都放在 `QoSm` 上的客户端。在 `QoSh:QoSm:QoSl = 8:4:1` 的权重下，该 cluster 的 `QoSm:QoSl` 实际流量比达到 `10.69:1`，远高于健康阈值 `4:1`。Aequitas 把一部分 BE 流量从 `QoSm` 降到 `QoSl`，结果降级反而更快：aligned BE 流量的平均 p99 RNL 更低，最坏 p99 RNL 还下降了 `18.51` 个标准化单位。更重要的是，等该客户端完全 rollout 后，原本已经“对齐”的 NC 流量 RNL 仍继续下降了 `31.04%`，说明更好的 QoS 对齐不是简单地把伤害转嫁给别人，而是可以通过减少队列争用让所有优先级一起受益。

更大范围的结果也支持这一点。对一个 planet-scale UL 系统，Aequitas 加上原有对齐后，使大约 `72%` 的 RPC 实现对齐，覆盖约 `84%` 的 response bytes 和 `78%` 的 request bytes。对一个大型 query service，rollout 后几乎所有 cell 的错配都被消除；其 maximum p99 RNL 对 NC 流量改善 `68.91%`，对 PC 流量改善 `36.45%`，方差也显著下降。附录 D 又把结论扩展到 SSD LL 存储：部署前大约 `30%` 的 LL-bound SSD RPC 处于错配状态，部署后约为 `0%`；其中一个受影响最重的用户，PC RPC 平均 latency 改善 `6.4%`、p99 改善 `11.2%`，fleetwide 的 PC latency 也分别改善 `1.8%` 和 `4.8%`。

## 创新性与影响

这篇论文首先是一篇 deployment / operational systems 论文，而不是新的传输协议论文。它的贡献在于证明：只靠现有 DSCP/WFQ 基础设施，也能把应用优先级稳定地传达到网络层；真正困难的地方不是发明一个更聪明的调度器，而是维持健康的全局队列配比，并向用户证明“被降级不一定更慢”。

相对 _Zhang et al. (SIGCOMM '22)_ 的原始 Aequitas 论文，这篇工作更像是从“机制设计”走向“默认策略落地”的第二阶段：为什么必须做到 RPC 粒度、为什么 LL 与 UL 要放在不同位置执行、为什么 rollout 只能渐进，以及真实 cluster 中会出现哪些反直觉现象。相对基于 size 的数据中心调度工作，本文则明确论证了在存储 RPC 上，priority 比 size 更稳健，因为大小和时延重要性并不一致。真正会引用这篇论文的人，大概率是需要在大规模存储网络里操作已有 QoS 队列的工程团队，因为它给的是一套可部署的经验法则，而不是只在理想模型中成立的最优策略。

## 局限性

Aequitas 的适用范围是刻意收窄的。论文只覆盖 intra-cluster 存储流量，明确把 WAN 留给未来工作，因为跨 cluster 的网络时延往往主导总 RPC latency，而且 Google 还有 BwE 这样的带宽管理器在 WAN 上按优先级分配预算。策略空间也被限制为三种优先级和静态映射。这让部署简单了很多，但也意味着系统依赖存储服务提供高质量元数据，并且假设底层交换机已经支持 differentiated service。

评估也带有明显的生产环境妥协。论文没有真正的 A/B 实验，只能依赖随机采样、主导用户 cluster 和标准化指标，而不是公开绝对时延数字。这种方法对生产系统来说是现实的，但因果结论自然不如受控实验那样干净。论文同样承认仍有例外：部分客户端还保留定制 QoS 策略，LL 存储上的错配也只能做到“接近零”，因为仍可能有短暂流量绕过 Aequitas 框架。

## 相关工作

- _Zhang et al. (SIGCOMM '22)_ — 原始 Aequitas 论文给出了机制与早期 rollout 证据；本文则补上大规模部署、执行位置选择和生产异常现象的经验总结。
- _Seemakhupt et al. (SOSP '23)_ — 该文从云规模视角刻画 RPC latency 组成；本文利用同样的观察，即部分 RPC 的网络时延会主导总时延，因此值得在 RPC 粒度上做 QoS 对齐。
- _Zhu et al. (SoCC '14)_ — PriorityMeister 面向共享网络存储的尾时延 QoS，而本文把三类 priority 方案标准化到多个 Google 存储服务，并依赖现有交换机 QoS 机制落地。
- _Montazeri et al. (SIGCOMM '18)_ — Homa 通过新的传输层协议利用优先级降低时延；Aequitas 则不改传输协议，而是通过已部署的 DSCP/WFQ 做增量部署。

## 我的笔记

<!-- 留空；由人工补充 -->

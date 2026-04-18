---
title: "Söze: One Network Telemetry Is All You Need for Per-flow Weighted Bandwidth Allocation at Scale"
oneline: "Söze 把单个 per-packet max queueing-delay 信号变成去中心化控制回路，在数据中心网络里实现 per-flow weighted max-min 带宽分配。"
authors:
  - "Weitao Wang"
  - "T. S. Eugene Ng"
affiliations:
  - "Rice University"
conference: osdi-2025
tags:
  - networking
  - datacenter
  - observability
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Söze 只用一个 in-band telemetry 信号，也就是一条流路径上的最大 queueing delay，来完成 weighted sharing 所需的协调。发送端把自己的 rate-per-weight 映射到目标时延，再根据观测到的 `maxQD` 做乘法更新，直到两者一致。这样，系统就在不知道 topology、routing 或竞争流信息的前提下，实现 per-flow weighted max-min allocation。

## 问题背景

论文针对的是数据中心网络里的一个明确缺口。很多应用并不满足于“按当前流量公平分带宽”：critical path 流需要更早完成，coflow straggler 需要追平，单个作业也可能想在自己内部重新分配带宽，同时不改变它与其他作业之间的总体占比。现有传输协议如 DCTCP、Swift、HPCC 更多是在既定竞争格局下追求公平或低延迟，而不是精确执行应用指定的权重。

直观解法都不理想。交换机侧 WFQ 需要 per-flow queue、有限的硬件权重粒度，以及沿路径控制；这对 commodity switch 和大规模并发流都不友好。集中式 allocator 虽然可以计算理想速率，但必须先收集 topology、routing 和 flow metadata，再在每次流到达、结束或改权重后重新求解并下发。真正难的是，多跳网络里的 bottleneck hop 事先并不知道，系统却必须在那里快速实现正确的 weighted share。

## 核心洞察

Söze 的核心洞察是：来自 bottleneck 的一个 telemetry 值就够了。在一条饱和链路上，weighted fairness 可以拆成两个条件：链路被充分利用，以及所有 bottlenecked flows 的 `r / w` 相等。Queueing delay 的导数天然反映前者，因为它对应到达速率与链路带宽之差；Söze 再用一个单调函数 `T(r / w)` 把后者也编码进 queueing delay 的绝对值里。于是，发送端只要比较“当前 `r / w` 应该对应的目标时延”和“实际看到的时延”，就知道自己该加速还是减速。

这个想法能推广到 arbitrary network，是因为在 weighted max-min fair 状态下，一条流只会在自己的 bottleneck hop 上拥有最大的 rate-per-weight，而不会在其他已饱和 hop 上也这样。因此，对这条流真正重要的反馈会表现为路径上的最大相关 queueing delay。只要沿途携带 `maxQD`，发送端就能获得正确反馈，而不需要知道瓶颈具体在哪。

## 设计

Söze 的数据面设计非常小。每个数据包带一个 2 字节字段，用来记录路径上见过的最大 queueing delay。数据包经过每个交换机 egress 时，交换机会把本地 queueing signal 和包头里的值做比较，保留更大的那个；接收端再把 `maxQD` 回写到 ACK。这样，发送端就持续收到整条路径的单一反馈信号，而交换机不需要维护 per-flow state、知道 topology，或主动计算 fair share。

控制算法全部在发送端。应用通过 socket 或 RPC API 给流设置权重，发送端根据当前 `r / w` 用参数 `p`、`k`、`alpha`、`beta` 计算目标时延 `T(r / w)`，再结合观测到的 `maxQD` 和反函数 `T^-1` 得到乘法更新比率。若观测到的时延高于目标，就说明这条流相对自己的权重发得过快，需要退让；反之则继续增速。论文证明，只要乘法增益 `m` 位于 0 到 2 之间，并让目标时延函数维持一个非零稳态队列，系统就会收敛到正确的 weighted allocation。

这套反馈回路既能放进 kernel TCP module，也能放进 rate-based 的 eRPC pacing。论文真正强调的是，把 weighted allocation 和 congestion control 视为同一个 transport control law，而不是在现有 CC 上再套一层独立控制平面。

## 实验评估

实现很轻量：Tofino 上的 queueing-delay telemetry 只用了 9 行代码；Linux congestion-control module 增加了 241 行；eRPC 集成增加了 1,972 行。实验覆盖 25 Gbps 的 eRPC testbed，以及拥有 1,024 台服务器的 fat-tree NS-3 模拟器。

第一类结果说明 Söze 本身就是一个可用的 transport control。step-in/step-out 实验里，它比 Timely 更快收敛、链路利用率更高；在模拟器中，相比 HPCC，它给出的速率分配更稳定、更接近目标。放到 RPC workload 中，Söze 也能降低 FCT slowdown，尤其对短流更明显。

对论文主张本身，microbenchmark 更关键。Söze 能在某条流权重提升、bottleneck hop 随之变化时，依然跟踪到正确的 weighted max-min allocation，而且通常在大约 10 个 RTT 内收敛。它在粒度上也优于把权重近似成整数个连接，或依赖少量物理 WRR 队列的替代方案。应用案例则说明这个 primitive 的价值：它能缩短 critical path、缓解 coflow straggler、支持 altruistic sharing，并把 TPC-H 作业完成时间降到基线的平均 0.79x、最佳 0.59x。

需要保留的意见是，不少“应用策略”仍然是作者手工构造的示例，而不是生产环境中的实际 controller。实验很好地证明了 Söze 的控制回路足够 agile、足够精确，但并不是和真实的云端 centralized weighted allocator 做正面对比。

## 创新性与影响

相对 _Nagaraj et al. (SIGCOMM '16)_ 这类依赖交换机侧 WFQ 的工作，Söze 把权重执行从交换机里拿到了主机侧控制回路。相对 _Jose et al. (HotNets '15)_ 这种让交换机主动计算 fair share 的方案，Söze 让交换机只负责写 telemetry，计算几乎全在 end host。相对 _Vamanan et al. (SIGCOMM '12)_ 或 _Crowcroft and Oechslin (CCR '98)_ 这类 host-side heuristic，Söze 追求的是明确的 weighted max-min equilibrium，而不是简单地让某些流更激进。

这篇论文最有价值的地方，是把 INT 从 observability feature 重新定义成 distributed control substrate。如果这个 framing 成立，那么利用 commodity switch 已有的 telemetry 能力，就足以在不引入重型控制器的前提下实现灵活的 weighted sharing。

## 局限性

Söze 仍然依赖一些明确前提：交换机要支持 queueing telemetry 和包头修改，接收端要把信号带回 ACK，主机网络栈也要允许应用设置权重。和在交换机里实现 WFQ 相比，这当然轻得多，但并不是零成本部署。

论文也把权重 policy 基本留在系统外。它解决的是“给定权重后如何实现”，而不是“多租户环境里该如何分配、限制、审计这些权重”。讨论部分给出的 logging 和 monitor 只是思路，还不是被评估过的系统部分。

最后，最强证据来自 testbed 和 simulation，场景也集中在 fat-tree 与 incast。理论上它适用于 arbitrary networks，但论文没有展示真实生产部署，也没有系统评估更复杂 routing churn 或异构 RTT。并且，queueing delay 作为反馈信号本身就意味着系统会刻意维持一个非零队列。

## 相关工作

- _Nagaraj et al. (SIGCOMM '16)_ — NumFabric 通过交换机侧 WFQ 权重来实现数据中心带宽目标，而 Söze 把权重执行转移到主机侧控制回路里。
- _Jose et al. (HotNets '15)_ — PERC 要求交换机主动计算并通告 fair share；Söze 只要求交换机写入 telemetry，计算工作全部留在 end host。
- _Vamanan et al. (SIGCOMM '12)_ — D2TCP 根据 deadline 调整 TCP 的激进程度，但并不追求跨任意瓶颈的精确 weighted max-min allocation。
- _Crowcroft and Oechslin (CCR '98)_ — MulTCP 让一条流“表现得像多条 TCP”，而 Söze 则直接构造了一个平衡点对应 weighted fairness 的控制律。

## 我的笔记

<!-- 留空；由人工补充 -->

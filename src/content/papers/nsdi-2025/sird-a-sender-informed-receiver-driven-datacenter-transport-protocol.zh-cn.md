---
title: "SIRD: A Sender-Informed, Receiver-Driven Datacenter Transport Protocol"
oneline: "SIRD 让接收端继续精确调度独占下行链路，同时用发送端与 ECN 反馈收紧共享链路上的 credit 分配，在高利用率下把队列压得更小。"
authors:
  - "Konstantinos Prasopoulos"
  - "Ryan Kosta"
  - "Edouard Bugnion"
  - "Marios Kogias"
affiliations:
  - "EPFL"
  - "UCSD"
  - "Imperial College London"
conference: nsdi-2025
code_url: "https://github.com/epfl-dcsl/SIRD-Caladan-Impl"
tags:
  - networking
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SIRD 的核心主张是：接收端驱动协议不该把所有瓶颈都当成同一种对象。接收端应主动调度自己独占的下行链路，而发送端上行和网络核心这类共享链路则应通过反馈回路来控制。这样一来，SIRD 能在保持 100 Gbps 级别高利用率的同时，把接收端驱动协议常见的过量 overcommitment 和网络排队显著压低。

## 问题背景

论文首先抓住一个越来越现实的矛盾：数据中心链路速率持续上升，但交换机按单位双向带宽计算的 SRAM buffer 却在下降。拥塞控制协议可依赖的缓冲空间更少了，可应用仍然要求高吞吐和低延迟并存。DCTCP、Swift 这类发送端驱动协议通常要等拥塞已经发生后再收缩窗口或速率，反应天然要多花几个 RTT，也不容易表达面向 message 的调度策略。接收端驱动协议在接收端下行链路上很有优势，因为该链路只由一个接收者控制，credit 可以把到达速率卡得很准。

但并不是所有瓶颈都属于单一接收者。发送端上行链路和网络核心链路都要被多个接收者共享。若多个接收者独立地向同一个 sender 发 credit，这个 sender 就会堆积起自己暂时用不掉的 credit；若多个接收者同时穿过同一个 core bottleneck 拉数据，它们各自的调度也会在核心处互相冲突。现有接收端驱动方案各有代价：Homa 通过下行链路 overcommitment 和网络优先级来换取高利用率，dcPIM 在大消息发送前加入 matching 轮次，ExpressPass 则把复杂性推到交换机配置和路径对称性上。SIRD 试图同时保住接收端驱动在 incast 下的优势，并避免高排队、额外握手和重型交换机依赖。

## 核心洞察

这篇论文最值得记住的判断是：应按链路所有权来决定控制方式。只有单一所有者的链路才适合做前摄式调度，而被多个接收者共享的链路更适合变成反馈控制对象。在 SIRD 中，receiver 仍然决定下一份 credit 发给哪个 sender，但它的决定不再是盲目的，而是结合了这个 sender 目前是否拥塞、对应网络路径是否已经被 ECN 标记的实时信息。

这使得 overcommitment 从“统计上押注总会有人能及时回包”变成了“根据信号精确投放 credit”。接收端不再给每个活跃 sender 都预留一份可能足以填满下行链路的 credit，而是为每个 sender 维护一个会随拥塞反馈收缩的 bucket。结果是，credit 会流向那些此刻真的能立刻消费它的 sender，而不是被拥塞 sender 白白囤积。论文要证明的正是：只要把共享链路的拥塞信息回送给 receiver，接收端驱动协议就不必靠大排队来换高利用率。

## 设计

SIRD 是一个构建在 UDP/IP 之上的 RPC-oriented 传输协议，并假设网络开启了 ECN。它定义了两类主要报文。`DATA` 承载 message 数据，可以是 scheduled 也可以是 unscheduled。`CREDIT` 由 receiver 发给 sender，用来授权后续 scheduled DATA 的发送。超过 `UnschT` 阈值的消息不会直接发数据，而是先发一个零长度 `DATA` 报文请求 credit；更小的消息则可以直接先发 `min(BDP, msg_size)` 的 unscheduled 前缀，这样就不会因为等一次 credit 而白白多花一个 RTT。

credit 管理分成两层。每个 receiver 有一个全局 bucket `B`，限制整个接收端已经发出但还没收回的数据授权总量；同时每个 sender 还有一个独立 bucket，限制该 sender 最多能占用多少 credit。全局 bucket 控制的是下行链路 overcommitment 的总量，而 per-sender bucket 则承载了 SIRD 的 sender-informed 设计：它的大小取决于两个独立反馈回路中的较小者，一个反映 sender 是否拥塞，一个反映网络核心路径是否拥塞。

发送端侧的信号是 `sird.csn` bit。只要某个 sender 从所有 receiver 收到的累计 credit 超过 `SThr`，它就在返回的数据包里把这个 bit 置上，告诉各个 receiver：“你们给我的 credit 已经多于我此刻能消费的速率。”网络侧的信号则是普通 ECN 标记。每个 receiver 同时运行两个 AIMD 控制器，一个读 `sird.csn`，一个读 ECN，然后取二者中更保守的结果来决定这个 sender 的 credit bucket。论文的稳态分析进一步说明，在公平共享前提下，只要 `B >= BDP + SThr`，哪怕存在很多个拥塞 sender，receiver 也仍可保住满下行带宽。作者在默认设置中使用 `B = 1.5 x BDP`、`SThr = 0.5 x BDP`。

还有两个设计点同样关键。第一，receiver 会以略低于 line rate 的速度 pace credit，从而把 scheduled 流量形成的下行排队进一步压低到 `B - BDP` 上界之下。第二，调度策略完全留在端系统：receiver 可以按 round-robin 或近似 SRPT 发 credit，sender 也需要在多个 receiver 之间做选择。正因为 SIRD 的目标是让网络内部始终接近空队列，它不需要依赖交换机 fabric 来执行复杂优先级；若硬件有两个优先级队列，SIRD 可以利用它们进一步优化尾延迟，但这不是正确性前提。

## 实验评估

实现层面的结果本身就很有分量。作者在 Caladan 上用约 4300 行代码实现了 SIRD，在配备 100 Gbps ConnectX-6 DX NIC 的 CloudLab 机器上，空载 RTT 约为 18 us，并能维持 100 Gbps 级别的运行。六发送端 incast 实验显示，即便接收端下行链路被打满，8 字节请求的延迟也只比空载多几个微秒；论文同时给出对照，内核态 TCP Cubic 在同类实验里的中位数延迟超过 1 ms。对 500 KB 请求，receiver 端 SRPT 策略在保持约 96 Gbps 吞吐的同时，把延迟压到接近空载水平，说明软件实现下的 credit pacing 和 message-aware scheduling 都是可行的。

sender-informed 机制也被单独验证。论文设计了一个 outcast 场景：一个 sender 以满速向三个 receiver 发送 10 MB 消息，三个 receiver 分时加入。若关闭 sender 反馈，随着新 receiver 加入，sender 侧囤积的 credit 会持续上升，因为每个 receiver 都会独立给它约一个 BDP 的 credit。启用 `SThr = 0.5 x BDP` 后，各 receiver 会收敛到一个新平衡点，使 sender 手里的 credit 大致围绕阈值波动，多余的 credit 留在 receiver 处，因而能被重新分配给其他未拥塞 sender。

更全面的对比来自 ns-2 仿真。作者在 144 主机 leaf-spine 拓扑上，对 balanced、core bottleneck 和 incast 三种配置、三类平均消息大小分别为 3 KB、125 KB、2.5 MB 的工作负载进行比较，基线包括 DCTCP、Swift、Homa、ExpressPass 和 dcPIM。论文的结论是，只有 SIRD 能同时靠近利用率、排队和 slowdown 的 Pareto 前沿。代表性数字包括：相对 Homa，峰值排队降低 12 倍而利用率与延迟仍具有竞争力；相对 dcPIM，goodput 高 9%，峰值排队低 43%，slowdown 低 46%；相对 ExpressPass，slowdown 低 10 倍、goodput 高 26%。即使在全网高压下，SIRD 在 receiver bottleneck 场景下的 ToR 排队也最多 0.8 MB，在 core bottleneck 场景下最多 2.3 MB，作者将其对应到 3.13 MB/Tbps 交换机 buffer 预算的 8% 与 23%。这些结果相当支持论文的核心论点，不过大规模仿真使用了无限 buffer、且除 ExpressPass 的 credit drop 外不考虑丢包，因此更接近“协议设计空间研究”而不是对现实硬件部署的直接预测。

## 创新性与影响

相对 _Montazeri et al. (SIGCOMM '18)_ 的 Homa，SIRD 仍然坚持 receiver-driven 思路，但把 Homa 的 controlled overcommitment 改造成 sender-informed overcommitment，使高利用率不再依赖先制造大规模入站压力、再借助交换机优先级绕过去。相对 _Cai et al. (SIGCOMM '22)_ 的 dcPIM，SIRD 去掉了大消息发送前的半同步 matching 过程，让消息可以立刻开始传输，再靠在线反馈去调节共享链路。相对 _Cho et al. (SIGCOMM '17)_ 的 ExpressPass，SIRD 把共享链路管理留在端到端闭环里，而不是交给逐跳交换机逻辑。

因此，SIRD 的价值不只是“又一个 transport protocol”。它给接收端驱动设计在新一代交换机约束下提供了一条更一般的设计法则：独占链路由 owner 直接调度，共享链路则显式转化为反馈通道。如果运营者想要接近 Homa 的低延迟，但又不愿接受较高 buffer 占用和交换机优先级依赖，那么 SIRD 提供了一个很有说服力的中间路线。

## 局限性

SIRD 依赖若干明确的部署前提。消息长度必须事先已知，或者上层能把流切成 message 粒度；网络必须正确配置 ECN；同时协议还默认可以通过随机 UDP source port 获得足够细粒度的负载均衡。这些假设对某些 RPC 数据中心成立，但并非任何现有以太网应用都能直接套用。

它为了稳定性和可部署性也牺牲了一些最优性。与 Homa 相比，SIRD 只能近似 SRPT，因为每个 sender uplink 的一部分带宽仍需在多个 receiver 之间公平共享，而且 sender 一旦拥塞，per-sender bucket 会按较公平的方式一起收缩。论文报告，在 balanced 配置下，SIRD 针对中等大小 group-C 消息的 99th slowdown 在 50% 与 70% 负载时分别比 Homa 高 1.85 倍和 2.68 倍。实现层面上，作者也明确避免把 `SThr` 设得过低，因为软件中批量到达的 credit 可能触发伪拥塞标记。

评估本身也有边界。大规模仿真采用无限交换机 buffer 来避免不同 ASIC 组织方式带来的方法学噪声，因此并未直接测出真实浅 buffer 硬件下的丢包行为。Homa 模拟器也没有实现它的 incast optimization，而论文自己也承认某些基线在双向 RPC 工作负载下会表现不同。这些问题并不会推翻 SIRD 的设计结论，但说明实验更适合回答“这个机制方向对不对”，而不是“上线后一定能按这些数字复现”。

## 相关工作

- _Montazeri et al. (SIGCOMM '18)_ - Homa 是最接近的 receiver-driven 基线，用 controlled overcommitment 和网络优先级来近似 SRPT；SIRD 则保留接收端调度，同时明显降低为保持 work-conserving 而付出的排队代价。
- _Cai et al. (SIGCOMM '22)_ - dcPIM 用显式 sender-receiver matching 轮次来协调共享 sender uplink，而 SIRD 用持续反馈和 per-sender credit cap 取代发送前配对。
- _Cho et al. (SIGCOMM '17)_ - ExpressPass 依赖交换机逐跳节流 credit 来管理拥塞；SIRD 接受少量额外排队，以换取无需特殊交换机配置和路径对称性的端到端设计。
- _Gao et al. (CoNEXT '15)_ - pHost 早早暴露了 receiver-driven transport 中的 unresponsive sender 问题；SIRD 把它进一步系统化为显式 sender congestion notification 加 AIMD 式重新分配。

## 我的笔记

<!-- 留空；由人工补充 -->

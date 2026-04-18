---
title: "MTP: Transport for In-Network Computing"
oneline: "MTP 把 transport 提升到 message 与 pathlet 粒度，让 in-network offload 即使会修改、拦截、重排或长时间延迟消息，也不再破坏可靠性与拥塞控制。"
authors:
  - "Tao Ji"
  - "Rohan Vardekar"
  - "Balajee Vamanan"
  - "Brent E. Stephens"
  - "Aditya Akella"
affiliations:
  - "UT Austin"
  - "University of Illinois Chicago"
  - "Google and University of Utah"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - networking
  - smartnic
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`MTP` 是第一篇真正按 in-network computing 需求来设计的 transport。它把 message 与 pathlet 变成 transport 直接理解的一等对象，因此即使 offload 会修改、拦截、重排或长时间延迟流量，协议仍能保持可靠传输与有效拥塞控制。

## 问题背景

论文关注的是部署在 switch 或 SmartNIC 上的 on-path L7 offload，例如 cache、load balancer、transaction accelerator 与 in-network aggregator。它们会直接改写消息内容与长度，直接吞掉某些消息，不同副本之间把消息重排，或者因为处理与排队导致长而不可预测的延迟。这些都不是偶发异常，而正是 INC 想做的事。

这正好击中了现有 transport 的假设。TCP 变种和 RDMA 依赖连续的 byte 或 packet sequence space，所以一旦 offload 改变消息长度或直接拦截消息，ACK 就无法再与原始发送内容一一对应，严重重排也会被误判为丢包。`Homa` 虽然是 message-oriented，但它的重传恢复仍要求接收端指出缺失的 byte range；如果消息在网络里被改写，这个范围就不再能映射回原消息。更麻烦的是拥塞控制也会失真，因为延迟现在既可能来自 fabric，也可能来自一个慢 offload，而 switch 与 SmartNIC 往往没有空间承载完整 transport stack、大缓冲与复杂 per-flow state。论文要解决的不是某个特定 offload 的兼容性，而是为 INC 提供一个通用 transport 契约。

## 核心洞察

最关键的洞察是：既然 offload 处理的是 message，transport 也应该直接以 message 为基本单位。只要协议显式编号并追踪消息，mutation、intercept 和 reordering 就不再是需要绕开的“异常路径”，而是 message descriptor 上的标准操作。

第二个洞察是把每个 offload 实例，或者一组 fate-sharing 的副本，抽象成 `pathlet`。`Pathlet` 可以显式告诉发送端：消息是否已经完整进入自己、是否已经离开自己、自己当前有多拥塞。这样发送端就第一次能区分“消息被 offload 暂时扣住了”和“消息大概率在网络里丢了”，而传统 transport 无法做出这个区分。

## 设计

`MTP` 是面向连接的，并假设网络能提供 pathlet discovery，以及沿选定 pathlet chain 转发的 source routing。发送端提交 message descriptor 后，协议为其分配 message number，选择 pathlet，再把 payload 切成多个 segment。每个 packet 都携带 message number、segment number、总 message length 和 virtual channel 标识。接收端被刻意设计成“被动”：它只记录哪些 segment 到达，等整条消息齐全后才发送 end-to-end ACK，因此消息重排不会触发 gap processing。`Mutation` 合法，因为 pathlet 可以改变消息长度与 segment 数；`intercept` 也合法，因为 pathlet 可以直接替接收端生成 end-to-end ACK。

可靠性由发送端主导。它不再要求接收端指出缺失 byte range，而是在超时后重传整条消息。`Pathlet` 再补上两个关键信号：完整缓存消息后发送 `PRX` ACK，处理完成并继续发出后发送 `PTX` ACK。于是发送端能在端点之间使用较短的 fabric RTO，而在消息停留于 offload 内部时使用更宽松的 pathlet RTO。为了在严重重排下仍维持 exactly-once，同时避免无界 reorder window，`MTP` 使用固定数量的 virtual channels：每个 inflight message 占一个 channel，接收端只记住该 channel 最近完成的 message number。

拥塞控制也围绕 pathlet 展开。每个 pathlet 把 queue occupancy 映射成 8-bit feedback，发送端为每个 pathlet 运行一个受 `Swift` 启发的控制器，并额外维护链路拥塞状态；如果某个实例持续过热，proactive pathlet switching 会把后续消息切到同类型其他实例。整个设计刻意不要求 offload 自己维护 transport sequence space；它们只要吐出 ACK 与 congestion feedback 即可。

## 实验评估

评估结合了 DPDK prototype、NetCache、受控 middlebox 实验和 ns-3。在 25 Gbps 的 NetCache 场景中，`MTP` client 能维持系统峰值吞吐的 95% 以上，而 UDP 加 timeout-retry 在 offered load 到 80% 时就开始掉队；论文把这个端到端结果概括为 `MTP` 吞吐提升超过 15%。面对重尾 offload delay 加 1% fabric drop，`PRX` 与 `PTX` ACK 为 `MTP` 提供了 `400-1050 us` 的安全 fabric-RTO 区间，协议在这段范围内仍能保持 90% 以上 goodput 且没有 false positive；单一 end-to-end RTO 做不到。对 pathlet congestion，早期多比特 feedback 能稳定收敛到公平份额，而 ECN 风格反馈不能；再配合 proactive pathlet switching，系统可达到两条非对称 pathlet 平均总吞吐的约 98%，而 ECMP 只有约 90%。代价并非为零，但还算可控：4 KB 消息加两条 pathlet 的最坏配置下，ACK 流量占链路带宽 6%，发送端 MTP 栈在 RX 路径上约消耗两颗 CPU core 中 55% 的周期，但仍能跑满 25 Gbps。在 ns-3 的 packet spraying 场景里，`MTP` 相比 TCP 将 tail completion time 降低约 65%，并基本消除了 TCP 因把重排误判为丢包而出现的 10% 到 15% 重传。

## 创新性与影响

这篇论文的新意，不在于做出一个更激进的 TCP、RDMA 或 `Homa` 变体，而在于给 INC 定义了一套 transport contract：message-oriented reliability、pathlet-oriented congestion control，以及一个低状态的 offload interface。它既对 transport 研究者有价值，也对 cache、aggregator 和 SmartNIC/switch offload 的实现者有价值，因为后者终于有机会摆脱各自为政的 workaround。

## 局限性

`MTP` 依赖明确的 message boundary、service/pathlet discovery 与 source routing。它主要面向 full-buffering pathlet；原生 streaming 以及 branching 或 multicast pathlet 都被留到了未来。安全性也没有真正解决，因为 INC 与端到端加密 transport 存在直接冲突。ACK 开销会随 message rate 和 pathlet 数量增长，而评估也仍是 prototype 加 simulation，不是跨多类硬件的生产级部署。附录还提示，当 mutation 让消息大小变化超过约 20% 时，公平性会开始退化，因此基于 DCTCP 演化出的控制器还不是最终答案。

## 相关工作

- _Montazeri et al. (SIGCOMM '18)_ - `Homa` 同样是 message-oriented transport，但它的丢包恢复默认消息内容不会在网络里被改写；`MTP` 从一开始就是为 message mutation 设计的。
- _Sapio et al. (NSDI '21)_ - `SwitchML` 证明了 in-network aggregation 的价值，而 `MTP` 试图提供这类 offload 目前尚缺失的通用 transport substrate。
- _Liu et al. (ASPLOS '23)_ - `NetReduce` 在消息长度不变时实现了透明 aggregation，`MTP` 则把 size-changing mutation、intercept 和 reordering 都纳入 transport 语义本身。
- _Qureshi et al. (SIGCOMM '22)_ - `PLB` 通过切换网络路径绕开拥塞热点；`MTP` 将这一思路迁移到拥塞的 offload instance 上，形成 proactive pathlet switching。

## 我的笔记

<!-- 留空；由人工补充 -->

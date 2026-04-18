---
title: "Picsou: Enabling Replicated State Machines to Communicate Efficiently"
oneline: "Picsou 用类似 TCP 的跨集群广播协议，让两个独立 RSM 在常态下每条消息只跨集群发送一次，并在 crash 或 Byzantine fault 下精确重传。"
authors:
  - "Reginald Frank"
  - "Micah Murray"
  - "Chawinphat Tankuranand"
  - "Junseo Yoo"
  - "Ethan Xu"
  - "Natacha Crooks"
  - "Suyash Gupta"
  - "Manos Kapritsos"
affiliations:
  - "University of California, Berkeley"
  - "University of Oregon"
  - "University of Michigan"
conference: osdi-2025
code_url: "https://github.com/gupta-suyash/BFT-RSM"
tags:
  - consensus
  - fault-tolerance
  - networking
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Picsou 定义了 Cross-Cluster Consistent Broadcast (C3B)，把“一个 replicated state machine 把已提交消息交给另一个”变成有形式化语义的原语。它借鉴 TCP 的 QUACKs，让常态路径里每条消息通常只跨集群发送一次、元数据保持常数级，而在 crash 或 Byzantine fault 下只做有依据的定点重传。

## 问题背景

现实系统里，RSM 与 RSM 之间的通信非常常见：Etcd 异地灾备要跨机房镜像更新，彼此独立的组织要在主权边界下对共享状态做 reconciliation，区块链之间则希望实现 interoperability。现有办法都不理想。Kafka 会在两边之外再插入第三个 replicated service；all-to-all broadcast 在 WAN 上会把流量成本放大；各种 ad hoc bridge 往往又缺乏精确定义的保证。作者因此提出，跨 RSM 通信需要同时满足四点：语义清晰、对 crash 和 Byzantine fault 都鲁棒、常态开销低、并且能连接 Raft、PBFT、PoS BFT 等异构协议。

## 核心洞察

C3B 故意把保证收窄到一个更容易高效实现的层次：如果发送方 RSM `Rs` transmit 了消息 `m`，那么接收方 RSM `Rr` 最终只需要保证“至少一个正确副本收到 `m`”。更强的性质，比如让所有接收副本都看到消息、或者把消息纳入接收侧自己的顺序，都可以由接收 RSM 内部再做 broadcast 或 consensus。正因为只要求证明“某个正确节点已经拿到”，Picsou 才能复用 TCP 式思路：累计确认表示“到 `k` 为止的消息都已经安全存在于某处”，而对同一个 `k` 的重复确认则说明 `k+1` 很可能丢了。论文真正有价值的地方，是把这个思路扩展到 many-to-many、并且允许节点 crash 或撒谎的环境里。

## 设计

Picsou 传输的基本单位是一个已提交请求 `m`，外加发送侧日志序号 `k`、跨 RSM 流序号 `k'`，以及发送方已经 commit 该请求的证明。发送侧按 `k' mod ns` 把消息划分给不同 replica，因此常态下每条消息只由一个 sender 负责。与此同时，每个 sender 会轮换 receiver；这样即使某个对端有故障，正确节点也不会永远卡在同一对 sender-receiver pairing 上，系统最终会把每个 receiver 的状态扩散到全体发送方。

receiver 拿到合法消息后，并不会重新跑一次 consensus。它只验证证明，然后在本地 RSM 内做 broadcast。为了让发送侧知道哪些消息已经稳妥落地，每个 receiver 维护自己看到的最高连续前缀，并发回 `ACK(p)`。当发送侧观察到来自 `ur + 1` 个不同 receiver 的累计确认时，消息就被 QUACKed；这说明至少有一个正确 receiver 已经看到了它。因为确认通常会 piggyback 在反向流量上，所以在 failure-free 路径里，Picsou 每条消息只额外带两个计数器级别的元数据。

真正复杂的是故障处理。对 `k` 的 duplicate QUACK 意味着有正确 receiver 还缺少 `k+1`，于是发送侧无需额外协调就能判断消息被丢弃或延迟。为了防止 Byzantine node 伪造抱怨、诱导系统无意义重传，duplicate-ack 证据必须来自 `rr + 1` 个一致的 receiver，而不是单个副本。确认丢失之后，所有 sender replica 都能本地计算新的重传者 `(original_sender + resend_count) mod ns`，因此每一轮依然只有一个节点负责重发。

论文还补了两个很关键的细节。第一，如果攻击者选择性丢弃多个消息，单纯依赖 cumulative ACK 只会暴露“最早的洞”，恢复会被串行化。为此 Picsou 增加了有界的 `phi`-list，汇报当前前缀之后一小段窗口里的投递状态，从而允许并行恢复多个缺失消息。第二，直接在 QUACK 后做垃圾回收并不安全：某条消息可能因为“一个正确 receiver 加上若干后来消失的 faulty receiver”形成了 QUACK，之后却反而卡住后续进度。Picsou 因此在发现这种不一致时 piggyback 自己见过的最高 QUACK 序号，让接收侧先推进前缀或向其他副本取回缺失消息，再让发送侧彻底遗忘。

面对 PoS RSM，平均轮转也不再合理，因为物理节点承担的 stake 可能极不均匀。Picsou 用 weighted QUACK 和 Dynamic Sharewise Scheduler 替代简单 round-robin；后者借助 Hamilton apportionment，按 stake 比例分配 sender/receiver 机会，同时尽量保留并行性。到了故障恢复阶段，它又把两边总 stake 按 least common multiple 缩放，避免因为两个系统使用了不同量级的绝对 stake，重传逻辑就被迫膨胀。

## 实验评估

实现约 4,500 行 C++20。先看不受 consensus 限制的 File RSM 微基准：在 4 节点集群上，Picsou 相对 all-to-all broadcast 提升 2.5x 到 3.2x；在 19 节点集群上提升扩大到 6.6x 到 12.1x；论文 headline 结果则是相对既有方案最高 24x。跨区域实验也很能说明问题：在 US-West 到 Hong Kong、消息大小 1 MB 的设置下，Picsou 比 ATA 在 4 副本时快 12x，在 19 副本时快 44x，因为它把流量分散到多条 WAN 路径，而不是塞给单 leader 或泛洪给所有人。

故障实验也基本支撑了作者的核心主张。每个 RSM crash 33% 副本时，吞吐下降 22.8% 到 30.5%，这和损失约三分之一“有用链路”是匹配的；即便如此，Picsou 仍然比 ATA、OTU、leader-to-leader 快 2x 到 8.9x。对 Byzantine selective drops，较大的 `phi`-list 能明显缩短恢复时间；而错误 ACK 的杀伤力反而比 crash 小得多，因为系统本来就要求匹配的 quorum 证据才能判定送达。

应用实验是这篇论文最有说服力的部分。在 Etcd disaster recovery 里，Picsou 让 5 个 sender 并行跨区域发送，于是总可用 WAN 带宽达到 250 MB/s，最终把 Raft 的磁盘 goodput 顶到约 70 MB/s；论文把这一点以及数据 reconciliation workload 总结为大约 2x 优于 Kafka。在 Algorand 和 PBFT-based ResilientDB 之间做 blockchain bridge 时，Picsou 带来的吞吐损失始终低于 15%，这说明它更像一个 transport layer，而不是又叠了一层新的 consensus engine。

## 创新性与影响

相对于 Kafka，Picsou 去掉了“为了让两个已有 RSM 交换状态，还得再引入第三个 replicated log”这一结构性负担。相对于 all-to-all broadcast，它把跨集群通信从二次方级流量压回到线性常态路径，再辅以精确恢复。相对于 OTU 这类 leader-centric 方案，它避免把单个 sender 或 receiver 固化成长期瓶颈。

更重要的是它的 framing。论文主张，inter-RSM communication 本身就该有独立原语 C3B，而不该只是 consensus 的尾巴或某个桥接应用里的特例。对任何需要在自治、异构、跨区域 RSM 之间高吞吐交换状态的系统，这个抽象都很有参考价值。

## 局限性

C3B 的保证是刻意收窄的：它只保证至少一个正确 receiver 收到消息，不保证两个 RSM 之间自动形成总序，也不保证原子化的跨集群事务。应用若需要更强语义，仍然要自己补。Picsou 还假设 reconfiguration 不频繁、成员信息已知，并且接收侧能够验证发送侧确实 commit 了对应消息。

它的性能优势也更适合长时间流式传输，以及存在双向流量或廉价 no-op ACK 的场景。随着网络规模增加，延迟仍会增长；而在 weighted 设计里，如果过多 stake 聚集到单个物理节点，该节点最终也会成为瓶颈。最后，论文没有试图解决 invalid traffic 带来的 volumetric DDoS，这一点作者明确视为超出范围。

## 相关工作

- _Aksoy and Kapritsos (SOSP '19)_ - Aegean 研究的是 replicated service 向后端服务发起嵌套请求；Picsou 关注的是更直接的 RSM-to-RSM 消息传输原语。
- _Balakrishnan et al. (OSDI '20)_ - Delos 用 virtual consensus 和 shared log 作为公共底座；Picsou 则研究两个已经复制好的系统如何在不插入第三个 replicated service 的情况下交换状态。
- _Suri-Payer et al. (SOSP '21)_ - Basil 处理的是 sharded BFT transaction，通常要付出比 Picsou 的窄 C3B 原语更重的 cross-shard coordination 成本。
- _Gilad et al. (SOSP '17)_ - Algorand 是促使 Picsou 设计 weighted QUACK 和 stake-aware scheduler 的代表性 PoS BFT 系统，但它解决的是 RSM 内部 consensus，而不是 RSM 之间的传输。

## 我的笔记

<!-- 留空；由人工补充 -->

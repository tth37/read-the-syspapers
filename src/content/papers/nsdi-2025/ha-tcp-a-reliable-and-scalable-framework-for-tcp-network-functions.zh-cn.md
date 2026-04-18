---
title: "HA/TCP: A Reliable and Scalable Framework for TCP Network Functions"
oneline: "HA/TCP 用 replicated sockets 和栈内流量复制，让 endpointing TCP network function 在迁移或故障切换时保持连接不断。"
authors:
  - "Haoyu Gu"
  - "Ali José Mashtizadeh"
  - "Bernard Wong"
affiliations:
  - "University of Waterloo"
conference: nsdi-2025
code_url: "https://github.com/rcslab/hatcp/"
tags:
  - networking
  - fault-tolerance
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HA/TCP 把 active replication 做进 TCP stack，并把结果封装成 replicated sockets，让 endpointing 的 layer-7 network function 在 failover 或 migration 时不必重置已有连接。它最关键的工程招式是：每个 packet 先复制给 replica，再让 replica 立即确认收到，primary 只有在此之后才继续本地 TCP 处理；这样既维持了两端 TCP state 的一致性，也仍能支撑 100 Gbps 级别的吞吐。

## 问题背景

以往的 NF 高可用工作大多针对 layer-2/3 function，默认每条 flow 的 state 很小、更新也不频繁。这个前提对 SOCKS proxy、TCP splicer、WAN accelerator 这类 endpointing 的 layer-7 NF 不成立。它们会终止 TCP，维护完整的 transport control block，把 payload 缓存在 socket queue 里，还常常会改写或重封装流量。一旦这类 NF 挂掉，就没有 fail-to-wire 这种退路：直接旁路它，后端可能根本看不懂流量，远端主机只会看到连接断开。

只复制 application state 也不够。TCP acknowledgment 只能说明对端 TCP stack 已经接收了字节，不能说明 NF application 已经完成消费、改写或转发。如果 primary 过早 ACK，随后又崩溃，sender 可能永远不会重传那些 replica 还没真正处理的数据。可如果等应用处理完再发 ACK，又会抬高 RTT、扰乱 congestion control，并直接伤害吞吐。因此，这篇论文要解决的是：如何在不要求客户端改协议、也不把每个 packet 变成远程 state 访问的前提下，为 endpointing TCP NF 提供无缝 failover。

## 核心洞察

论文的核心判断是，复制边界应该放在 transport stack 内部，而不是外部 state store，也不是把整个应用做成 full record/replay。只要 primary 和 replica 以相同顺序看到同一批 packet，以及同一组带有非确定性的 TCP-visible state transition，那么 NF 对外部世界暴露出来的大部分行为就会变成可重现的。

HA/TCP 把这个思路包装成 replicated socket abstraction。primary 等待的只是 replica 的“已收到”快速确认，而不是 replica 完成 TCP processing 或 application execution。replica 可以在本地落后一点，并用队列把这种落后吸收掉，只要最终保持对外可见输出的确定性即可。这样，系统真正需要同步的就缩小成流量本身和少量控制变量，代价远低于逐包复制任意 application state。

## 设计

HA/TCP 基于 FreeBSD 13.1/F-Stack TCP stack 实现。primary 收到一个 packet 后，会在 checksum validation 和 TCP control block lookup 之后将其拦截。HA/TCP 先把原始 mbuf 放进队列，再复制该 packet，加上一个很小的 HA/TCP header，其中包含 packet size、congestion-window 更新等控制信息，然后通过专用 replication channel 发给 replica。只有等 replica 确认收到之后，primary 才把本地排队的原始 packet 放回正常 TCP 处理路径。

replication channel 故意选在 IP 层，而不是 TCP 或 UDP。作者认为，这样可以绕开额外的 control block lookup、锁竞争和 congestion control，也避免他们早期设计中出现的 TCP-over-TCP meltdown。由于 LRO 会把流量合并成接近 64 KiB 的大包，HA/TCP 又把 shallow copy 和 IP fragmentation 合并起来：它既能保留本地对原始 packet chain 的引用，又能在 replica 链路上发出 9 KB 的分片，而不需要反复 deep copy。为了避免高吞吐下的 IP reassembly collision，每条 replicated TCP connection 还会附带唯一的 32-bit ID 和 timestamp option。至于复制链路上的丢包，HA/TCP 不在通道里做复杂修复；如果 primary 收不到 replica 的确认，就不向客户端发送 TCP acknowledgment，转而依赖客户端重传。

replica 在 NIC thread 上立即确认每个复制过来的 packet，然后先把它排队，等本地 TCP state 已经准备好接收时再交给 TCP stack。这个队列用来吸收 primary 和 replica 的性能偏差，也让 HA/TCP 能保持 SACK state、PAWS 所需的 timestamp 单调性，以及按序交付条件。HA/TCP 还会复制 listening socket 和三次握手过程：primary 转发 SYN、自己的 initial sequence number，以及 timestamp offset；之后再复制最终 ACK 和初始 congestion-window 信息。围绕 transport path，HA/TCP 使用 CARP 做 leader election 和 failover，并增加了一个基于 distributed LACP 的 IP Clustering 机制，让多个节点共享同一个 IP/MAC，以实现 connection-level load balancing。

## 实验评估

实验运行在 dual-socket Xeon Gold 6342 服务器和 dual-ported 100 Gbps ConnectX-6 NIC 上，客户端一侧使用 1500-byte MTU，replication link 使用 9000-byte MTU。第一个核心结果是，HA/TCP 仍然可以用 4 条连接打满 100 Gbps 链路。它的 IP Clustering 设计在扩展到 6 个节点时也几乎保持线性扩展，总吞吐只比理想值低 2%。

migration 是最醒目的系统结果。HA/TCP 完成一次 migration 总共需要 38 us，其中 22 us 是网络通信延迟，16 us 是本地处理时间。论文报告说，这比 Prism 快 2.4x，比 Capybara 快 1.7x。对 failover 来说，真正的 transport switchover 在检测完成后只需要 13 us，不过用户可见中断主要还是由 CARP 设定的 300 ms 检测窗口主导。

steady-state overhead 不算大，但并不对称。在 iPerf3 中，receive-bound 吞吐下降 3.4%，因为 primary 的 input path 必须先等 replica 确认收到，才能继续 TCP processing；transmit-bound 吞吐只下降 0.3%，因为这时 primary 主要是在跟踪 outgoing acknowledgment。一个带 100 kQPS 背景负载的 latency benchmark 显示，复制平均只多出 11 us 延迟。论文还估计，在 100 Gbps 下 steady state 的复制额外内存峰值约为 875 KiB，本质上就是 replication link 的 bandwidth-delay product。

应用级 case study 比 microbenchmark 更有说服力。WAN accelerator 基本没有可测的吞吐损失，并且在检测到故障后的 132 us 内完成所有连接切换。SOCKS proxy 的吞吐下降 2%，primary 的 CPU 使用增加 29%，但它的 failover 在检测后仍要 84 ms，因为 replica 可能落后大约 44 个排队请求。分布式 load balancer 则把 64 条连接中的 32 条迁移到第二台服务器，使总吞吐从 90.6 Gbps 提升到 181.2 Gbps。这些结果总体支持了论文的中心论点：持续复制 TCP-visible state 是可行的。不过证据范围仍局限在低丢包 LAN、单 replica，以及单一 software stack/NIC family 上。

## 创新性与影响

相较于既有 NF 可靠性工作，HA/TCP 改变了“该复制什么”这个基本单位。它不再把 layer-7 NF 看成“application state 加一个通用 failover 机制”，而是把 transport path 本身视为必须保持确定性的对象。由此得到的是一个可复用的 replicated-socket API，而不是只服务某一种 proxy 的一次性 migration 机制。

这对仍在软件里终止 TCP 的 virtual appliance、proxy 和 service-function-chain 开发者很有价值。论文留下来的重要启发既是一个具体机制，也是一条系统设计经验：对于 endpointing NF，最不容易丢失语义的位置，就是在本地 TCP processing 把失败变成“发送端不可见”之前先完成复制。

## 局限性

HA/TCP 在绝对资源成本上并不便宜。它要求修改 FreeBSD/F-Stack，最好还有一条专用 replication link，并且默认 primary 和 replica 之间的丢包足够少，以至于依赖客户端重传来修补空洞不会造成明显伤害。这些假设在工程上并非不合理，但也意味着它不算一个可以无痛落地的 drop-in 方案。

它的 failover 延迟也分成内部与外部两个部分。内部 switchover 一旦开始就很快；但在实际部署里，CARP 的检测时间往往才是主导项，而 replica 队列积压还会进一步拉长恢复时间，SOCKS 实验就清楚地展示了这一点。当前原型也还没有把 IP Clustering 与 replication 真正整合起来，因此完整的“可弹性扩展且高可用”的故事还需要更多 orchestration。最后，实验始终停留在单一低时延环境里，没有测试 replica 链路在更高丢包率或更远距离下会表现得多稳健。

## 相关工作

- _Woo et al. (NSDI '18)_ - `S6` 通过远程或合并后的 state 来弹性扩展 layer-2/3 network function，而 `HA/TCP` 需要为 endpointing 的 layer-7 NF 保住完整 TCP state 和 in-flight payload。
- _Sherry et al. (SIGCOMM '15)_ - `FTMB` 依赖 rollback-recovery 和 replay 来恢复 middlebox，`HA/TCP` 则在 transport stack 内持续同步 replica，以实现更快的透明接管。
- _Hayakawa et al. (NSDI '21)_ - `Prism` 用 proxy-specific 机制迁移连接，而 `HA/TCP` 把 migration 与 failover 做成一个可复用的 replicated-socket substrate，并报告了更低的迁移时延。
- _Choi et al. (APSys '23)_ - `Capybara` 借助 library OS 和 custom stack 做到了很快的 live TCP migration，而 `HA/TCP` 面向的是 FreeBSD/F-Stack 这类 production-style NF，并额外提供 steady-state replication 来支持 failover，而不仅仅是 migration。

## 我的笔记

<!-- 留空；由人工补充 -->

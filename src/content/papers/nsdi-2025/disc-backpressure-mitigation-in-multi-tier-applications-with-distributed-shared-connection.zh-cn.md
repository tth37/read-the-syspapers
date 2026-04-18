---
title: "DISC: Backpressure Mitigation in Multi-tier Applications with Distributed Shared Connection"
oneline: "DISC 将响应 metadata 与最终 payload 分离，并让 backend datapath 在 client 原始 TCP/TLS 连接上直接发送 payload 字节，绕过 relay tiers。"
authors:
  - "Brice Ekane"
  - "Djob Mvondo"
  - "Renaud Lachaize"
  - "Yérom-David Bromberg"
  - "Alain Tchana"
  - "Daniel Hagimont"
affiliations:
  - "Univ. Rennes, Inria, CNRS, IRISA, France"
  - "Univ. Grenoble Alpes, CNRS, Inria, Grenoble INP, LIG, 38000 Grenoble, France"
  - "IRIT, Université de Toulouse, CNRS, Toulouse INP, UT3 Toulouse, France"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - datacenter
  - networking
  - kernel
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

DISC 解决的是 multi-tier 应用里典型的 backpressure：真正生成数据的是 backend，但大 payload 却要被 frontend 和中间 tiers 一层层搬回去。它把响应拆成 metadata 和 payload 两部分，让 metadata 继续沿应用链路回传，同时让 backend 侧 datapath 在 client 原始 TCP/TLS 连接上直接发送 payload，因此 relay tiers 不再为无意义的字节转发付出主要成本。

## 问题背景

论文研究的是数据中心软件里最常见的一种调用结构：client 请求先进入 front end，再经过一个或多个中间服务，最后到达真正持有数据的 backend。很多场景下，backend 返回的内容已经是“最终数据”，例如图片、邮件正文或数据库对象；但这些字节仍然必须逐跳回流，通过所有前面的 tiers。于是 frontend 和 intermediate services 即使并不修改 payload，也要为接收和重发这些字节消耗 CPU。论文把这种性能耦合称为 backpressure，它会让前面的 tiers 跟着 backend 的负载一起被拖高，甚至比 backend 更早饱和。

作者先用 3-tier NGINX 链路、SpecWeb 和 SpecMail 证明这个现象确实存在。随着 payload 变大，FE 和 IS 的 CPU 增长明显快于 BE，这说明系统的瓶颈被错误地推到了只负责转发的 tiers。已有 shortcut 方案大多基于 connection handoff，但它们通常只针对 2-tier 的 load balancer/backend 结构，要求前后两端使用相同的应用协议与 API，并且会把中间 tier 完整绕开。真实 multi-tier 应用往往做不到这一点，因为前面 tiers 仍可能需要看到 response header 或 footer，而且一条链路中经常混用 HTTP、IMAP、SOAP、gRPC 和数据库协议。

## 核心洞察

DISC 的核心判断是：系统并不需要把整条连接“迁移”给 backend，真正需要的是把一条响应流的发送权分布出去。只要把响应拆成 metadata 和 payload，两者就不必走同一条回程路径。metadata 继续沿原来的 backward path 逐层返回，保持应用语义；大 payload 则绕过那些只负责 relay 的 tiers。

这就形成了 distributed shared connection。frontend 可以把某一段 payload 字节的发送权临时委托给 backend datapath，等 payload 发完后再收回控制权，用来发送 footer 或下一条 response。正因为它不是完整 handoff，而是共享同一逻辑连接上的发送职责，所以 DISC 同时保住了中间 tiers 对响应元数据的可见性，以及异构协议链路的兼容性。

## 设计

DISC 在 TCP 之上增加一个 DISC-PROT header，并在各 tier 安装局部 hook。请求头里会记录 tier 位置以及哪些 tiers 同意被 bypass；响应头里会记录这次 payload 是否 bypass、payload 大小、缓存该 payload 的标识符，以及托管 backend datapath 的地址。这样一来，shortcut 不只适用于单个 FE-BE 对，而是可以发生在任意深度的子链路上。

实现上有四个关键部件。`feHook`、`isHook`、`beHook` 负责应用层改造。`kHook` 作为内核侧 hook，配合 BPF 状态维护连接信息并重写 sequence/acknowledgment numbers。backend 上的 `DP` 负责缓存 payload，并在之后代表 frontend 直接发 raw packets。`ackSender` 则把 frontend 主机收到的 ACK/SACK 信息转发给 backend datapath。在一次 shortcut 中，backend 只把 DISC 和应用层 headers 沿原链路回传，把真正的 payload 存到 `DP` 并标记为 bypass；frontend 收到 header-only response 后，把该 payload 对应的 sequence range 记入共享内核状态，再远程调用 `DP`，要求它在原始 client 连接上发送这些字节。

真正困难的是：在完全不改 Linux TCP 栈的前提下，维持正确的 TCP 语义。DISC 为此维护一个跨 FE 和 BE 发送行为的全局 sequence-number 视图。`DP` 被调用时会拿到当前全局 sequence state，并在该范围内发出 payload；之后 FE 再发包时，`kHook` 会把这些包的 sequence number 翻译成 client 眼中连续一致的字节流。反过来，client 发回的 ACK、SACK 和 duplicate ACK 也会先被 FE 拦截：如果确认的是 FE 自己发出的字节，就翻译回 FE 本地编号；如果确认的是 bypassed payload，就转给 `DP`，让它推进发送窗口或重传。论文明确强调，这套做法与 keep-alive、piggybacking、pipelining 以及 TCP congestion control 兼容。

TLS 也沿用了同样的委托思路。DISC 在 FE 上序列化 `wolfSSL` session，把它导入 `DP`，让 backend 在同一 TLS session 里加密 bypassed payload；发送完成后，再把 session 归还给 FE。client 完全无需修改，但代价是 bypass 期间 TLS 开销会从 FE 转移到 BE。

## 实验评估

评估基于 CloudLab，既有可控的 NGINX microbenchmark，也有 SpecWeb、SpecMail、Train Ticket 和 Social Media。microbenchmark 主要改变链路深度和 16 KB 到 64 KB 的 payload 大小，正好对应论文要解决的问题：大 final payload 被不做内容修改的 tiers 反复 relay。

CPU 结果最能说明问题。在 4-tier 的 `FE-IS1-IS2-BE` 链路、64 KB payload 场景下，DISC 分别把 FE、`IS1`、`IS2` 的 CPU 压低 63.4%、64.3% 和 60.4%，同时把 BE CPU 提高 98.8%。这仍然是净收益，因为累计 CPU 从 vanilla 的 246% 降到 145%，而单跳 DSR 只能降到 208%。SpecWeb 和 SpecMail 也呈现同样趋势，累计 CPU 分别下降 41.5% 和 36.5%。

DISC 还改变了系统的扩展拐点。在 `FE-BE` microbenchmark 中，32 KB payload、每个 tier 两个核时，vanilla 大约在 18 Kreq/s 开始明显掉队，而 DISC 在相同资源下可以跑到 26 Kreq/s，也就是 45% 提升；再扩到四核后，DISC 大约在 30 Kreq/s 触到网卡上限。没有 intermediate tier 时，平均 latency 与 vanilla 基本相同，这符合论文的主张，因为 DISC 去掉的是 relay 成本，不是网络往返。随着链路变深，tail latency 的收益迅速放大：有两个 intermediates 时，99.99 分位从 4.803 s 降到 2.959 s；有十个 intermediates 时，论文报告从 8 s 降到 1.4 s，也就是 5.71 倍改善。Train Ticket 也显示这种机制对微服务有效，平均延迟从 3.57 s 降到 0.928 s，吞吐从 635.8 提高到 889.2 req/s。

总体上，这些结果支持论文的中心论点：DISC 不是凭空减少工作量，而是把工作转移到真正应该承担它的 tier，并避免 FE 与 IS 被无意义的 payload forwarding 拖成瓶颈。

## 创新性与影响

DISC 与经典 connection migration 的区别，在于它共享发送职责，而不是转移整条连接的所有权。这正是它能让 header/footer 继续沿应用链路回传、同时让 payload 走更短回程路径的关键。相比 `Prism` 和 `CRAB`，DISC 不再局限于单一的 load-balancer/backend shortcut；相比 `QDSR` 这类基于 QUIC 的 direct server return 设计，它保持 client 无感，并能适配 service chain 内部的异构协议。

因此，这篇论文的贡献不只是一个实现技巧，而是一整套机制：协议头、TCP/TLS 协调方法，以及把 partial response-path bypass 集成进现有 datacenter 应用的方式。最直接的潜在采用者会是 cloud provider 或托管式 multi-tier 平台的运营者。

## 局限性

部署成本仍然不低。所有参与 shortcut 的服务器都必须部署 DISC，而且既需要应用层 hooks，也需要内核侧 packet interception。论文也明确指出，DISC 依赖 IP spoofing，因此它更适合 cloud provider 或受控基础设施，而不适合普通 IaaS tenant。

它的收益还明显依赖工作负载。DISC 最适合 backend 返回大块 final data、而前面 tiers 只是 relay 的场景。如果 intermediate 真的要改写 body，或者 payload 很小，那么 bypass 空间会很快缩小。Train Ticket 就说明了这一点：gateway 仍然昂贵，因为它的主要成本来自 traffic shaping，而不是 payload forwarding。

最后，DISC 把 backend datapath 变成了更强也更复杂的组件。`DP` 需要缓存 payload、处理基于 ACK 的重传，并在 bypass 期间承担 TLS 工作。评估表明这种集中通常是值得的，但容量规划也因此更偏向 backend 一侧。

## 相关工作

- _Hayakawa et al. (NSDI '21)_ - `Prism` 主要解决 proxy 与 backend 之间的 relay 开销，而 DISC 支持任意深度链路，并且只绕过 payload 字节而不是整条 response path。
- _Kogias et al. (SoCC '20)_ - `CRAB` 可以绕过 load balancer，但本质上仍是 2-tier shortcut；DISC 则把发送权分布到多级 intermediary hops 与混合协议链路上。
- _Snoeren et al. (USITS '01)_ - Fine-grained failover 依赖 connection migration，而 DISC 刻意避免完整迁移，转而共享同一逻辑连接上的发送职责。
- _Wei et al. (USENIX ATC '24)_ - `QDSR` 将 direct server return 用于基于 QUIC 的负载均衡，而 DISC 保持 client 不变，并面向异构 multi-tier service chain。

## 我的笔记

<!-- 留空；由人工补充 -->

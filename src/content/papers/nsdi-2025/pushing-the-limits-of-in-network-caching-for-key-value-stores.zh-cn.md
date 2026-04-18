---
title: "Pushing the Limits of In-Network Caching for Key-Value Stores"
oneline: "OrbitCache 不再把热点键值对塞进 switch 表项，而是让它们以循环数据包形式驻留在数据面，从而支持可变长度 item 并缓解热点负载。"
authors:
  - "Gyuyeong Kim"
affiliations:
  - "Sungshin Women’s University"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
tags:
  - caching
  - smartnic
  - networking
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`OrbitCache` 用一种不同于传统 switch cache 的方式实现 in-network caching：它不把热点项存在 switch SRAM 里，而是让完整的键值回复包在数据面里持续循环。这样一来，系统不再受以往 16 字节 key、128 字节 value 上限的约束，并且在高度偏斜的负载下，相比无缓存基线可获得最高 `3.59x` 的吞吐提升。

## 问题背景

论文关注的是一个很具体但很关键的矛盾：programmable switch cache 在概念上很诱人，但真实 key-value workload 的尺寸分布与 switch ASIC 的表项约束并不匹配。`NetCache`、`DistCache`、`FarReach` 这一路工作已经证明，把热点项放进 switch 可以比增设一层 server cache 更便宜、更快地平衡读热点。然而它们都受制于同一类硬件限制：match key 宽度有限、每个 stage 可访问字节数很小、能拿来做缓存的 match-action stage 数也有限。结果就是，这类方案基本只能处理约 16 字节 key 和 128 字节 value。

这对真实生产负载并不够。论文引用 Twitter 与 Facebook 的测量结果指出，很多 key 往往有几十字节，而大量 value 虽然仍能装进一个 MTU 级别的数据包，却已经超过旧式 in-switch cache 的格式上限。以 Twitter 的 54 个工作负载为例，其中 42 个负载里，现有方案连一个 item 都缓存不了，因为 key 或 value 至少有一项超出硬件限制。也就是说，旧方案失败的对象不是超大对象，而是那些对服务器而言仍然很小、但对 switch table 来说已经过大的普通对象。

最直接的补救办法同样行不通。一个自然想法是把 request 多次 recirculate，让它反复访问 switch memory 中被分片保存的 value。但 programmable switch 每条 pipeline 只有一个内部 recirculation port；如果每个 request 都需要循环多次，这个端口会立刻变成瓶颈。论文真正要回答的问题是：怎样利用 switch 的超高 packet-processing 吞吐，却又不把数据本身硬塞进它狭小的随机访问存储里。

## 核心洞察

这篇论文最核心的洞察是，不要再把“缓存”理解成“存在 switch table 里的数据”。`OrbitCache` 改为把每个热点项表示成一个持续在 switch 数据面中循环的 reply packet。请求不再从 SRAM 中“读出” value，而只是把一小段 metadata 写进一个按 key 划分的 request table，其中包括 client IP、端口和序列号。随后，循环中的 cache packet 会主动检查有没有人在等待自己的 key；如果有，switch 就 clone 这个包，把一份发给 client，把另一份继续送回 recirculation path。

这个视角转换一次性解决了两个问题。首先，完整 key 和完整 value 都在 packet payload 里，所以只要 item 能装进单个数据包，就不再受 switch table 宽度限制。其次，因为返回给 client 的 reply 里包含完整 key，switch 就可以只用固定长度的 key hash 做 cache lookup，而把极少发生的 hash collision 交给 client 端解决：client 比较“我请求的 key”和“reply 带回来的 key”，若不一致再发一个 correction request 去 server 取正确值。论文真正强调的是，只有少量、固定数量的 cache packet 在 switch 里循环时，recirculation 才是便宜的；如果让每个 request 都循环，硬件优势就会立刻消失。

## 设计

`OrbitCache` 的 switch 数据面由五个核心部件组成。Lookup table 用 128-bit key hash 找到 cache index。State table 标记每个缓存项当前是 valid 还是 invalid，以避免写入进行中时读到旧值。Request table 为每个已缓存 key 维护一个逻辑上的 circular queue，用多组寄存器数组和指针寄存器保存待服务请求。Key counters 记录每个缓存键的热度，以及全局 cache hit 和 overflow 情况，供控制面做更新决策。最后，cloning module 借助 switch 的 packet replication engine，把一个 cache packet 同时送往 client 和 recirculation port。

读路径是刻意设计成不对称的。若 cache miss，请求直接发往 storage server。若命中且该项当前有效，switch 就把请求的 metadata 插入这个 key 对应的逻辑队列，并直接丢弃原请求包。之后，当相应的 cache packet 从 recirculation port 再次经过数据面时，它会去 request table 查询是否有等待者；若找到，switch 就把 header 改写成该 client 的地址信息，clone 这个包，把原包转发给 client，删除已经消费的请求记录，并让 clone 继续回到 recirculation path 服务后续请求。

写路径使用基于 invalidation 的 coherence 协议。对一个已缓存 key 的写请求会先把该项状态设为 invalid，然后无条件发往 storage server。Server 在 write reply 中附带新 value，于是 switch 一边重新把该项标记为 valid，一边通过 clone 这份 reply 生成新的 cache packet。缓存更新则由控制面负责：server 周期性上报“未缓存但变热”的 key，switch 周期性上报“已缓存 key 的热度”，controller 再据此驱逐一个旧条目、安装新的 lookup-table 映射，并从对应 server 拉取最新 value。

这套设计里有两个特别重要的取舍。第一，request table 按 key 隔离请求，因此某个热点 key 的突发流量不会破坏其他 key 的排队状态。第二，`OrbitCache` 有意把 cache 做得很小。论文依赖 small-cache effect：只缓存少量最热 item 就足以平衡偏斜负载，而过多循环的 cache packet 只会在 recirculation path 上制造额外排队延迟。

## 实验评估

原型基于 Intel Tofino 1，用 `P4_16` 实现，配合 100 GbE NIC 的服务器集群完成实验。大多数实验模拟一个包含 32 个 storage server 的 rack，数据集大小为 1000 万个键值对，默认 key 长度为 16 字节，value 采用双峰分布：`82%` 为 64 字节，`18%` 为 1024 字节。主要对比对象是 `NoCache` 和 `NetCache`，并在部分实验中与 `Pegasus`、`FarReach` 对照。

最重要的结果来自热点读负载。在 Zipf-0.99 的 key 访问分布下，`OrbitCache` 的吞吐达到 `NoCache` 的 `3.59x`、`NetCache` 的 `1.95x`，同时服务器之间的负载分布明显更均衡。随着 storage server 数量从 4 增加到 64，`OrbitCache` 的总吞吐几乎线性增长，而基线方案因为平衡效率不足，扩展性显著更差。面对来自 Twitter 的生产工作负载，`OrbitCache` 也始终是三者中最快的，因为很多真正的热点项根本超出了 `NetCache` 能表示的尺寸。

代价也被论文量化了。由于请求需要等待某个循环中的 cache packet 读到自己，`OrbitCache` 的延迟大约比 `NetCache` 高 `1 us`；但即便在接近饱和时，switch 侧 tail latency 仍维持在几十微秒量级，而 server 侧 tail 已经明显恶化。论文还说明 cache 规模并不是越大越好：总吞吐在约 `128` 个缓存条目时就基本饱和，而当缓存条目增加到 `256` 后，overflow request 会快速上升，因为过多 cache packet 会在 recirculation path 上彼此排队。随着写比例提高，`OrbitCache` 的收益会下降，并在 100% 写入时逐渐逼近 `NoCache`；与 `FarReach` 相比，它在写比例低于约 `25%` 时更强，但写入更多后会被采用 write-back caching 的 `FarReach` 反超。尽管如此，系统的鲁棒性仍然不错：它能处理接近 MTU 大小的 value，能在几秒内适应热点集合变化，也能在多种生产 workload 混合条件下持续维持较好的负载均衡。

## 创新性与影响

这篇论文的创新点主要体现在体系结构层面，而不是某个局部算法优化。此前的 switch cache 一直在问：怎样把更多字节塞进 switch memory。`OrbitCache` 问的是：能否尽量不把数据放进 switch memory，而是把 recirculation 和 packet cloning 本身当成缓存载体。这个转向很重要，因为它把 in-network caching 的适用范围从“玩具级小对象”推进到了真实读密集型 key-value store 中常见的单包对象。

它的潜在影响也因此比较明确。对做 switch-based storage acceleration 的研究者而言，这篇论文证明，ASIC 上那些常被当作附属功能的硬件机制，其实可以支撑一种完全不同的 cache architecture。对更广义的 in-network system 设计来说，它也传达了一个有价值的经验：有时最合适的抽象不是“再多一个表项”，而是“一个会不断回到数据面的包”。

## 局限性

`OrbitCache` 用更强的 item 尺寸支持换来了更小的 cache capacity。因为请求必须等待循环中的 cache packet 为自己服务，所以一旦缓存条目过多，recirculation path 上的排队会迅速变差，并让 overflow request 回退到 server。实验表明，一个有效的工作区间大致在 `32-128` 个缓存条目之间；这对论文里的偏斜负载已经足够，但与传统 server-side cache 相比仍然非常小。

这套设计在写密集和快速变化的工作负载下也更脆弱。它采用 write-through invalidation，因此写入挂起期间，缓存读的优势会暂时消失；当写比例升高后，`FarReach` 会因为 write-back 设计而占优。Hash collision 也不是在 switch 内完全解决，而是交给 client 做 correction，这一做法虽然简单优雅，但在极少数碰撞路径或条目替换与旧请求并存的角落场景下会带来一次额外 RTT。最后，论文主要实现并评估的是单包 item 的方案，而且部署上还受制于 pipeline 放置约束，因为不同 pipeline 之间不能共享这些 metadata；多包 item 与多 pipeline 的支持更多停留在扩展讨论里，而不是核心实现结果。

## 相关工作

- _Li et al. (NSDI '16)_ - `SwitchKV` 只把 switch 用作 lookup 加速，缓存值本身仍放在服务器侧；`OrbitCache` 则让 value 自己留在 packet-resident 的 switch 路径中。
- _Jin et al. (SOSP '17)_ - `NetCache` 把极小的热点项直接存入 switch memory，而 `OrbitCache` 放弃了这种 memory-centric 设计，从而支持更大的单包对象。
- _Li et al. (OSDI '20)_ - `Pegasus` 通过在服务器之间选择性复制热点项来应对 skew；`OrbitCache` 则直接把热点读吸收到 switch 中，因此不再同样受 server 吞吐上限约束。
- _Sheng et al. (ATC '23)_ - `FarReach` 在 `NetCache` 路线上加入 write-back caching，但仍继承了固定 item 尺寸的基本假设，而这正是 `OrbitCache` 试图突破的地方。

## 我的笔记

<!-- 留空；由人工补充 -->

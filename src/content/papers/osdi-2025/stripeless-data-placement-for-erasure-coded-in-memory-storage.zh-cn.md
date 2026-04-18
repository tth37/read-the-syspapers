---
title: "Stripeless Data Placement for Erasure-Coded In-Memory Storage"
oneline: "Nos 用 SBIBD 约束 backup 选择、在后台将副本 XOR 成 parity，去掉 stripes 带来的放置与协调开销，同时保留 in-memory KV store 的多故障恢复能力。"
authors:
  - "Jian Gao"
  - "Jiwu Shu"
  - "Bin Yan"
  - "Yuhao Zhang"
  - "Keji Huang"
affiliations:
  - "Tsinghua University"
  - "Huawei Technologies Co., Ltd"
conference: osdi-2025
code_url: "https://github.com/IcicleF/Nos"
tags:
  - storage
  - fault-tolerance
  - rdma
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Nos 的核心判断是：in-memory KV store 要想承受多节点故障，并不一定非要依赖 stripe。它用一个基于 SBIBD 的 affinity matrix 约束 primary 可以把对象复制到哪些 backup，再让 backup 在后台把缓冲的副本 XOR 成 parity。建立在其上的 Nostor 因而同时避开了 stripe 分配、MDS 查询和对象切分的开销，并在实验中取得了比 stripe-based baseline 更高的吞吐，以及比 full replication 更低的内存占用。

## 问题背景

论文面向的是建立在 RDMA 网络上的分布式 in-memory storage system。这类系统服务的是热数据、细粒度对象和低延迟访问，因此 DRAM 的成本高到让 replication 显得浪费，但访问路径又快到足以让传统 erasure coding 里那些“看起来只是管理细节”的额外工作真正变成瓶颈。作者认为，问题根源就在 stripe。

如果采用 intra-object stripe，每个对象都会被切成 `k` 个 chunk 分散到多个节点上，于是一次读写哪怕只涉及一个很小的 value，也必须扇出到多个节点。对于大量小对象为主的 KV workload，这个 fanout 成本非常刺眼。如果采用 inter-object stripe，对象本身可以保持完整，但系统就必须决定“这个对象属于哪条 stripe”。静态策略会因为 stripe 半空、慢节点或负载变化而浪费内存并损害性能；动态策略则往往需要在关键路径上引入 metadata service 或 proxy，增加一个网络往返、制造集中瓶颈，甚至带来单点故障。对一个高性能 RDMA 内存系统来说，这两条路都不理想。论文要解决的问题，就是在保留 erasure coding 存储效率的同时，去掉 stripe 构造、stripe 查找和对象切分的成本。

## 核心洞察

这篇论文最值得记住的一句话是：多故障可恢复性本质上是 placement invariant，而不是 stripe invariant。传统 stripe 真正提供的，不是某种不可替代的组织形式，而是一种保证“故障后仍有足够编码关系可解”的结构。Nos 试图把这种保证转移到 placement 本身上。

作者采用 `(v, k, 1)` symmetric balanced incomplete block design（SBIBD）来构造 primary-to-backup affinity matrix，其中 `v = k^2 - k + 1`。把这个矩阵解释成“某个 primary 允许把对象复制到哪些 backup”之后，每个 primary 恰好有 `k` 个可选 backup，而任意两个 primary 最多只会共享一个共同 backup。这个重叠上界就是 Nos 的关键不变量：当一个对象被复制到 `(p + 1)` 个 backup，且每个 backup 都把来自其 `k` 个 source primary 的一个对象 XOR 成 parity 时，即使发生最多 `p` 个节点故障，也不会把目标对象的所有幸存 parity 全部纠缠到不可恢复的程度。最坏情况下，只需要额外先恢复一个别的丢失对象，再用它恢复目标对象。

## 设计

Nos 由 `(k, p)` 参数化，并要求 `k > p`。每个对象有一份 primary 副本，再有 `(p + 1)` 份 backup 副本，这些 backup 必须从该 primary 在 SBIBD 中对应的 `k` 个合法目标里选出。各个 backup 之间不需要协调去拼出 stripe。相反，每个 backup 只需从自己的 `k` 个 source primary 接收副本，按 source 暂存，然后在后台取每个 source 的一个副本做 XOR，生成一个 parity。由于 primary 上保留的是原始对象，Nos 属于 systematic code。

Nostor 把这套编码方案落成了一个分布式 in-memory KV store。它先把 key hash 到某个 subcluster，再映射到该 subcluster 内的 primary server。前台 RDMA RPC 线程负责处理客户端 GET/PUT，后台线程负责把复制来的 delta 消化成 parity。PUT 采用 versioning：primary 先把新版本挂到 version queue，分配 sequence number，计算相对旧版本的 delta，把 delta 复制到 `(p + 1)` 个 backup，待复制完成后再推进 committed sequence number，使这次写入同时变成可见且 fault-tolerant。GET 则只需读取 primary 上已提交的队首版本。

真正让 Nostor 避开 stripe 管理开销的，是它的后台编码流水线。若后台线程能从每个 replication-source queue 中各取到一个新对象，它就生成一个包含 `k` 个 encodee 的 full parity；若某些队列暂时没有新对象，它会在 10 微秒后超时，先生成 partial parity，再通过按 source 维护的 parity queue 逐步把它补满。更新通过把新 delta XOR 进已有 parity 来完成；删除则可能把 full parity 再次变回 partial parity。发生故障时，Nostor 先让失效 primary 的所有幸存 replication target 对齐到一致的已提交状态，然后再提供 degraded read：查询所有幸存 backup，挑选“还依赖最少失败对象”的 parity，必要时递归恢复一次。节点修复则并行地重建丢失的 primary 数据和 parity。

## 实验评估

实验在 16 台 CloudLab 节点上进行，使用 100 Gb RDMA NIC，并将 Nostor 与 Cocytus、PQ、Split 以及纯 replication 对比。这个设置正好打在论文关心的区间：小 value、高请求率、以内存访问为主，因此任何额外 fanout 或 placement coordination 都会被放大出来。

microbenchmark 很直接地验证了论文的中心论点。对 100%-GET 且 value 很小的场景，Nostor 在 `(k, p) = (4, 2)` 下达到 Split 吞吐的 `3.92x`，在 `(6, 2)` 下达到 `6.06x`，几乎正比于它避免的 I/O fanout。对 PUT，它在 64 B value 时已接近 replication，并且明显优于 Cocytus 和 PQ，因为它不需要同步地为 stripe 做空间分配。论文还实现了一个把 MDS 插入 I/O critical path 的 dummy baseline，结果 GET 吞吐比 Nostor 低 `89.2%`，PUT 吞吐低 `72.4%`，这非常有力地说明：对这种 fast path，集中式 placement lookup 基本不可接受。

端到端结果也足够强。对真实的 Twemcache trace，Nostor 相比其他 erasure-coded baseline 带来了 `1.61x` 到 `2.60x` 的吞吐提升，同时保持相近或更低的 median latency。与 replication 相比，它的内存占用低 `18.7%` 到 `57.4%`，节点修复速度比 Split 快 `16.4%`。主要代价出现在 degraded read：在 `(4, 2)` 和 `(6, 2)` 下，Nostor 的 degraded-read latency 平均比 Split 高 `16.5%`；在 `(6, 3)` 的最坏递归恢复场景里，它比 Cocytus 高 `35.0%`、比 Split 高 `62.4%`。这与设计目标是一致的：它优先优化 common-case 的 steady-state read/write，而不是最坏情况下的降级访问。

## 创新性与影响

相对于 _Chen et al. (FAST '16)_，Nos 不是在想办法让“stripe-based 的 in-memory erasure coding”变得稍微没那么难受，而是直接把 stripe 从 placement abstraction 里拿掉。相对于 _Cheng et al. (SC '21)_，它也不是在 stripe 框架内做 parity logging 或写路径修补，而是换了一个关于“parity 应该如何形成”的答案。论文真正的新意，是把 combinatorial design 里的 SBIBD 引入系统放置问题，并据此给出一个既可证明、又足够容易实现的 stripeless recovery invariant。

因此，这篇工作会同时吸引两类读者。对做 RDMA in-memory store、remote memory 或容错 KV 服务的人来说，它给出了介于 replication 和传统 erasure coding 之间的一条新路线。对做 coding-for-systems 的研究者来说，它展示了一个很好的例子：现代系统里的性能瓶颈未必出在编码代数本身，也可能出在 placement structure。

## 局限性

Nos 用结构简单换来了约束刚性。因为它依赖 `(v, k, 1)` SBIBD，所以集群规模必须满足 `v = k^2 - k + 1`，而且每个节点只会与 `Theta(sqrt(v))` 个 peer 交换编码相关数据，而不是像 Reed-Solomon 那样几乎可以自由选择放置位置。这使得在同一集群里混用多个 `k` 值，或者按照任意拓扑灵活调整策略，都更困难。

这个设计还会额外消耗网络带宽。每次写入相对传统 erasure coding 要多发送一份 replica；当 direct recovery 不成立时，degraded recovery 最多还可能读取 `O(kp)` 个对象，只不过从摊还角度看，每个对象的平均恢复成本仍不超过 `k`。论文也明确承认，它的收益主要针对 fast in-memory system；若底层是 slow storage，优势会被介质延迟淹没。wide-stripe、超大 `k` 的场景也不适合，因为所需 failure domain 数量会二次增长。最后，Nostor 在故障期间不支持 degraded write，而实验中每台物理机运行两个逻辑 server，所以 failure-domain 的真实性弱于真正部署环境。

## 相关工作

- _Chen et al. (FAST '16)_ - Cocytus 也把 erasure coding 用到 in-memory KV store 上，但它仍然要把对象分配进 stripes；Nos 去掉了 stripe allocation 及其连带的 placement 瓶颈。
- _Rashmi et al. (OSDI '16)_ - EC-Cache 通过 intra-object chunking 和 online erasure coding 做低延迟 cluster caching；Nos 则保持对象完整，避免 split-object 设计的 `k` 路访问 fanout。
- _Cheng et al. (SC '21)_ - LogECMem 在 stripe-based in-memory KV store 上加入 parity logging 来优化写路径，而 Nos 直接放弃了 stripe 这一组织抽象。
- _Lee et al. (FAST '22)_ - Hydra 关注 far-memory 模型下的 resilient remote memory，而 Nostor 提供的是一个支持 committed PUT 语义、面向多客户端的分布式 KV store，以及 stripeless inter-object coding。

## 我的笔记

<!-- 留空；由人工补充 -->

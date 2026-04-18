---
title: "Rearchitecting the Thread Model of In-Memory Key-Value Stores with μTPS"
oneline: "μTPS 把 KVS 请求处理拆成 cache-resident 与 memory-resident 两层，并在线调节 cores、LLC ways 与 hot set，以超过 RTC 设计。"
authors:
  - "Youmin Chen"
  - "Jiwu Shu"
  - "Yanyan Shen"
  - "Linpeng Huang"
  - "Hong Mei"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Tsinghua University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764794"
tags:
  - databases
  - scheduling
  - caching
category: storage-and-databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`μTPS` 的核心主张是：现代 in-memory KVS 不该再把一次请求从 NIC 轮询到索引查找再到返回响应，全部塞进一个 run-to-completion worker。它把系统拆成处理 NIC、响应和 hot keys 的 cache-resident 层，以及处理完整索引和冷数据访问的 memory-resident 层，再在线调节 cores、LLC ways 和 hot-set 大小。论文在两个实现上报告了相对接近的 RTC 基线 `1.03-5.46x` 吞吐提升，同时延迟基本维持在相近水平。

## 问题背景

这篇论文瞄准的是一个很容易被低估的拐点：当 RDMA NIC 已经能把请求率推到每秒 `10M` 以上时，一次 cache miss 不再只是小噪声，而可能直接吞掉一次 KV 操作里相当可观的一段预算。作者指出，现代 KV 操作常常只有几百纳秒，而一次 LLC miss 就可能带来 `50-150 ns` 的代价。在这种速度下，当前最常见的 non-preemptive KVS 架构，也就是 thread-per-queue 加 run-to-completion，开始暴露结构性问题。

原因在于，一个 worker 被迫顺序执行一串内存行为完全不同的子任务：先轮询网络缓冲区、解析请求、遍历索引、读写 value、最后准备并发送响应。其中轮询网络缓冲区其实很适合待在 cache 里，因为 DDIO/DCA 会把 NIC 数据直接放进 LLC；但索引遍历和冷 value 访问则天然是 pointer chasing 和大范围内存访问。把它们捆在同一个热循环里，结果就是 cache thrashing。与此同时，真实生产负载往往是 skewed 的，热点 key 会让更新路径出现冲突。share-nothing 可以减少锁，却容易负载失衡；share-everything 负载更均衡，却会付出同步开销。很多已有工作优化了 cache allocation 或索引结构，但并没有动到“线程模型本身是否合理”这个前提。

## 核心洞察

论文最重要的洞察是：在超高速 KVS 里，stage 的划分应该首先服从 cache residency 与 contention behavior，而不是服从传统的软件模块边界。网络轮询、请求解析、响应处理，以及最热的一小部分 key，可以被组织成基本停留在 LLC 里的 cache-resident 工作；完整索引遍历、冷数据访问、冲突频繁的更新，则应该被视为 memory-resident 工作，用 batching、prefetch 和受控的线程数量来处理。

这件事之所以有效，不只是因为“分层”本身，而是因为 `μTPS` 把 TPS 重新收缩成只有两层，而不是回到传统那种多 stage、多 queue、多 thread pool 的复杂设计。这样做把跨层通信频率压到了足够低，同时仍然把最容易互相污染 cache、或者因为锁竞争而相互阻塞的部分隔离开。分离之后，系统就能分别给两层分配 cores 和 LLC ways，让 hot keys 尽量常驻 cache，并在 skewed 负载下主动收缩真正会冲突的更新线程数，而不拖住整个请求流水线。

## 设计

`μTPS` 的主体是两个层次：cache-resident (`CR`) layer 和 memory-resident (`MR`) layer。`CR` 层负责轮询网络、解析请求、发送响应，并直接处理 hot items；`MR` 层持有完整索引和全部数据项，处理来自 `CR` 的 miss。于是每个请求只有两条路径：命中 hot set 时在 `CR` 层本地完成；未命中时通过 `CR-MR` queue 转发到 `MR`，处理完成后再通过响应缓冲区回到客户端。

RPC 路径的设计重点是“可重配置”。作者没有给每个 worker 单独配一个接收队列，而是在服务端使用一个共享 receive queue。客户端并发把请求追加到同一个 receive buffer，`CR` worker 根据槽位编号满足 `m mod n = i` 的规则轮询并解析属于自己的请求，其中 `n` 是当前 `CR` worker 数量。这样做一方面显著降低了接收缓冲区的内存占用，另一方面在调整线程数时只需要改服务端的全局状态，而不需要与所有客户端同步新映射。配合 RDMA SRQ、MP-RQ 和每线程的小响应缓冲区，系统获得了可重配但仍然足够轻量的 RPC 路径。

`CR` 层里的 cache 也不是传统 LRU，而是一个可伸缩的 hot set。后台线程周期性采样最近访问，用 count-min sketch 加 min-heap 找出热点 key，再通过 epoch-based 方式原子切换到新的 hot set。若底层是 tree index，热点索引会被整理成 sorted array 以减少指针和空间开销；若底层是 hash index，则直接复用主索引结构。`CR` worker 以一个很小的 FSM 运行：请求命中热层时直接完成；未命中时推入 `CR-MR` queue，然后立刻继续非阻塞轮询，而不是等待下层处理结束。

`MR` 层的工作重点是隐藏内存访问延迟。它把一批请求从 `CR-MR` queue 弹出后，用 C++20 stackless coroutines 把 put/get 的索引遍历改写成可切换的协程，在每次指针解引用前插入 prefetch，再在多个协程之间切换，从而把 pointer-chasing 的等待时间摊在整个 batch 上。真正的数据复制也不经过层间队列，而是由 `MR` 直接在网络缓冲区和 KV 存储之间搬运。并发控制方面，系统继续采用 share-everything：索引复用 thread-safe 的 `MassTree` 或 `libcuckoo`，value 上则嵌入 version 与 lock bits，使读可以 lock-free，而较大的写通过 CAS 加锁完成。

层间通信由专门的 `CR-MR` queue 承担。它为每一对 `CR`/`MR` 线程准备独立的 lock-free ring buffer，形成 all-to-all 映射，每个 slot 还能容纳多个请求批量传输。单条请求只占 `16` 字节，包含压缩后的 key、请求类型、大小和网络 buffer 指针；完成信息不再额外回传，而是 piggyback 在 tail pointer 推进上。最上层的 auto-tuner 则负责在线重分配 `CR`/`MR` 线程、调整 hot-set 大小，并通过 `PQOS` 分配 LLC ways。它对 thread allocation 和 cache-way split 做分层搜索，在近似凸的空间里用 trisecting，加上对 cache size 的线性探测；论文给出的完整重配置时间大约是 `0.9 s`，期间请求处理不会暂停。

## 实验评估

作者实现了两个版本：基于 `libcuckoo` 的 `μTPS-H` 和基于 `MassTree` 的 `μTPS-T`。实验平台是在单个 NUMA node 上使用 `28` 个核、`200 Gbps` RDMA，以及一个预装 `10M` 键值项的数据库。主要对比对象是 `BaseKV`，它保留了相同的 batching、prefetch 和 RPC 优化，但线程架构仍是 run-to-completion；另外还有 `eRPC-KV` 以及 `RaceHash`、`Sherman` 这类 passive RDMA KVS。

最强的结果出现在论文最期待的区域，也就是 read-heavy、skewed、tree index 的场景。使用 tree index 时，`μTPS` 在 `YCSB-B` 和 `YCSB-C` 上平均达到 `BaseKV` 的 `1.30x` 和 `1.29x` 吞吐。论文还先用理想化实验说明“拆层本身”就有价值：去掉层间通信的 NP-TPS 原型，相对 NP-TPQ 提供了 `1.22-1.54x` 的吞吐增益；仅把最热的 `0.1‰` key 定向给专门线程处理，也能让 `MassTree` lookup 吞吐提升约 `1.08x`。

在 scan-heavy 和真实负载上，收益仍然成立。`μTPS-T` 在 `YCSB-E` 上比 `BaseKV` 快 `33.1%`，在 scan-only 负载上快 `25.1%`。在 ETC 负载里，它相对 `BaseKV` 在 `10%`、`50%`、`90%` get ratio 下分别高 `29.1%`、`13.0%`、`26.6%`，相对 `eRPC-KV` 的优势更大。三条 Twitter trace 也给出一致图景：对 `BaseKV` 的提升分别是 `44.5%`、`39.8%` 和几乎持平的 `0.1%`。最后这一点很重要，它说明 `μTPS` 在 uniform、write-dominant 的负载里不会崩，但如果工作负载本身几乎没有可利用的 hot/cold 分离，优势也会明显变小。

论文对不占优的情况也交代得比较清楚。uniform、write-heavy、特别是小 item 的场景里，`μTPS` 的收益很有限，`eRPC-KV` 有时还会略好，因为 share-nothing 避免了锁，而 `eRPC` 的 RPC 路径又比论文里的单 receive queue 更成熟。延迟方面，`μTPS` 没有承诺绝对更低，而是承诺“接近”：多一次 inter-core hop 大约增加 `100 ns`，文中报告的 median 和 P99 latency 大多与 `BaseKV` 相近，只在部分 hash-index 情况下中位数略高。ablation 也基本支撑了设计逻辑：batching 让 `μTPS-T` 和 `μTPS-H` 的吞吐分别提升 `51.6%` 和 `93.7%`；面对 value size 从 `512B` 变到 `8B` 的动态负载变化时，auto-tuner 大约在 `0.9 s` 内完成重配置，最终把吞吐再拉高约 `20%`。

## 创新性与影响

相对 `MICA`、`FaRM` 这些经典高性能 RDMA KVS，`μTPS` 的创新点并不是再做一个“更快的 run-to-completion KVS”。它真正的新意是重新定义 non-preemptive KVS 里的 stage：不再按软件模块划分，而按 cache residency 与 contention behavior 划分。`Reconfigurable RPC`、hot-set cache、协程化 batched indexing、紧凑的 `CR-MR` queue，以及 auto-tuner，都是围绕这个主命题展开的。

这让论文的价值不只是一组工程优化，而是一次对默认设计范式的反驳。它说明当 NIC 和内存足够快时，thread model 本身就会成为吞吐与延迟的主导因素，而不是一个可以默认沿用的背景条件。对正在设计 CPU 参与式 in-memory store 的工程团队，以及研究高速网络下软件结构的系统研究者来说，这种 framing 很可能比某个单独技巧更有长期影响。

## 局限性

这篇论文并没有证明 `μTPS` 在所有场景下都占优。它自己的结果已经说明，收益最明显的是 tree index、skewed 访问，以及 read-heavy 或 mixed workload；在 uniform 的小 item 写负载下，优势会明显缩小，甚至会被 `eRPC-KV` 反超。也就是说，`μTPS` 需要工作负载里确实存在足够强的 hot/cold 结构或者冲突结构，拆层才有明显价值。

RPC 路径本身也还不是终点。作者明确承认 `Reconfigurable RPC` 在部分场景下不如 `eRPC`，并提到如果把 `μTPS` 与 `eRPC` 结合，性能可能进一步提升，但论文并没有实现这个组合。auto-tuner 也是经验搜索而不是解析模型：它要在 threads、hot-set 大小和 LLC ways 的空间里试探，虽然 `0.9 s` 对作者设想的工作负载变化频率是可接受的，但如果流量剧烈波动，这个收敛过程就未必那么从容。

最后，评估范围比题目给人的感觉更窄一些。大多数实验都在单个 NUMA node、`28` 个核上完成，因此论文并没有深入回答跨 socket 的行为会怎样。整个设计也默认系统愿意让 CPU 参与关键路径，并依赖 thread-safe index 与显式并发控制，所以它并不面向那些把 server CPU 大量移出数据路径的 passive one-sided RDMA KVS。

## 相关工作

- _Lim et al. (NSDI '14)_ - `MICA` 代表了高性能 run-to-completion KV serving 的经典路线；`μTPS` 保留 non-preemptive polling，但认为把所有子阶段折叠进一个 worker loop 会浪费 cache locality。
- _Dragojević et al. (NSDI '14)_ - `FaRM` 同样依赖 pinned threads 与快速 RDMA 请求处理，而 `μTPS` 针对的是这种单体 worker 在 cache thrashing 和 contention 上暴露出的代价。
- _Roghanchi et al. (SOSP '17)_ - `ffwd` 证明 delegation 风格的 inter-core communication 其实可以非常便宜；`μTPS` 把这种思路用于 multi-producer、multi-consumer 的 KVS 流水线。
- _Pismenny et al. (OSDI '23)_ - `ShRing` 通过 shared receive rings 优化包接收，`μTPS` 则把 shared receive queue 用在可重配置 RPC 路径中，并服务于更大的 hot/cold stage split。

## 我的笔记

<!-- 留空；由人工补充 -->

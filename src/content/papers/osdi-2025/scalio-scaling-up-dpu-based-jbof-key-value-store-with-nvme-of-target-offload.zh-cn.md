---
title: "Scalio: Scaling up DPU-based JBOF Key-value Store with NVMe-oF Target Offload"
oneline: "Scalio 把 JBOF 读路径下沉到 NVMe-oF target offload，用 RDMA 可见的 inline cache 吸收热读，并以批量刷盘让单个 DPU 在 4 块以上 SSD 上继续扩展。"
authors:
  - "Xun Sun"
  - "Mingxing Zhang"
  - "Yingdi Shan"
  - "Kang Chen"
  - "Jinlei Jiang"
  - "Yongwei Wu"
affiliations:
  - "Tsinghua University"
  - "Quan Cheng Laboratory"
conference: osdi-2025
code_url: "https://github.com/madsys-dev/scalio-osdi25-ae"
tags:
  - storage
  - smartnic
  - disaggregation
  - caching
  - rdma
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Scalio 的核心判断是，高密度 DPU-based JBOF key-value store 的瓶颈不在 SSD 介质，也不在网络 IOPS，而在 DPU CPU。它把读路径迁移到 one-sided RDMA 与 NVMe-oF target offload，把热数据放进一个 RDMA 可直接访问的紧凑 DRAM cache，再把 DPU CPU 主要留给批量写入和一致性管理。论文的关键结果是：这套组合在保持 linearizability 的同时，让单个 DPU 能跨过现有 JBOF KV 系统在 4 块 SSD 左右就出现的扩展瓶颈。

## 问题背景

论文从一个硬件与软件不匹配的问题出发。今天的 JBOF 厂商已经开始提供每个 DPU 挂 26 块甚至 36 块 SSD 的高密度设备，因此从“每瓦吞吐”角度看，多个 SSD 共享同一个控制平面本应越来越划算。但现有软件栈并没有把这种密度兑现成吞吐。以 LEED 为例，作者复现实验后发现，系统在大约 4 块 SSD 时吞吐就不再提升，因为 DPU 需要把太多核心花在 SSD I/O 和元数据处理上。在他们的测量中，处理 SSD I/O 的 CPU 使用率此时达到 400%，而网络 I/O 利用率却仍不到 ConnectX-6 理论峰值的 1%。

这个瓶颈在论文关注的小 key-value workload 上尤其明显。社交、推荐、云服务等场景中的大量请求都是细粒度、低延迟的 point operation；单次 SSD 访问已经足够轻，以至于真正稀缺的资源变成了 DPU 上那几颗弱核。最直接的想法似乎是“把 CPU 绕开”，但这还不够。一旦 client 可以直接从 SSD 读数据、并通过 RDMA 修改位于 DPU DRAM 中的 cache/index 元数据，系统就不能再依赖 CPU 内部那套天然的 cache coherence。真正的问题因此分成两部分：如何尽量把 I/O 工作移出 DPU CPU，以及在 client 自主并发访问 DRAM 和 SSD 的情况下，如何定义一个仍然满足 linearizability 的 cache/update protocol。

## 核心洞察

Scalio 的核心主张是：在 DPU-based JBOF 中，HCA 和网络路径应该成为读请求的 fast path，而 DPU CPU 只负责那些确实需要集中协调的工作。NVMe-oF target offload 已经允许 server 侧 HCA 直接把远程 NVMe 请求翻译成面向 SSD 的 peer-to-peer 命令，不再经过 DPU 核心；论文真正的创新点在于围绕这个硬件能力重新设计 KV store，而不是继续围绕 CPU 发起的 SSD I/O 来构建整个系统。

这件事之所以成立，是因为 Scalio 同时引入了一个极小、但对 client 可见的 DRAM 结构。热数据直接内联在 hash block 中，因此 cache hit 只需一次 RDMA read。cache miss 也尽量不经过 DPU CPU：client 先锁住一个 victim slot，从同一块元数据里拿到 SSD offset，再发起 NVMe-oF target-offloaded read，把数据回填到 cache 中。写入没有被完全做成 one-sided，但论文证明，借助 ring-buffered batching 与 group commit，写放大和 CPU 压力都可以显著摊薄。剩下的正确性问题，则通过两个显式状态位 `occupied` 与 `complete` 来解决，让 client 能区分空槽、填充中、有效槽和已失效槽，而不再假设 DRAM 与 SSD 会自动保持一致。

## 设计

Scalio 把数据路径拆成一个以读为主的 offloaded fast path，以及一个仍需 DPU CPU 参与、但按批处理的写路径。内存结构是一个支持 RDMA 直接访问的 hash table，block 在 DRAM 中连续布局。每个 slot 内联保存 key 和 value，同时额外维护 `occupied`、`complete` 和 `last_ts`。论文的 sensitivity analysis 指出，block 大小做到 1 KB 仍不会打满网络带宽；这足以在单个 block 内放下最多 10 个约 100 字节的 key-value pair。每个 block 还带一个 `next_offset`，指向 SSD 上对应的 hash index 区域，因此 miss 后可以直接跳到 flash 侧元数据。

读路径几乎完全是 one-sided。client 先 RDMA-read 整个 hash block；若命中一个有效 slot，就立刻返回。若未命中，则按 client 维护的 LRU 时间戳挑选 victim，用 RDMA CAS 修改 `complete` 来加锁，再做一次 double-read，确认没有其他 client 把同一个 key 填进别的 slot。确认无冲突后，client 通过 NVMe-oF target offload 直接从 SSD 读取数据，再用 RDMA write 把结果写回 slot。这个设计把原本空闲的网络/HCA 能力转化成了存储吞吐：论文测得，target offload 的读 IOPS 与标准 NVMe-oF 基本相当，但 target 侧 CPU 占用从 562% 降到了 0。

写路径则刻意采用不同策略。client 把更新内容和自己的 client ID 追加到 DRAM 中的 ring buffer；DPU CPU 轮询这个缓冲区，把多条更新聚合后批量刷入 SSD，再更新内存中的 `next_offset`，最后通知 client 去失效旧的 cache 副本。这里 batching 的价值很直接：LEED 的每次更新需要两次 SSD 写，而 Scalio 在实验中把这个数字降到了大约一次。为了保证一致性，Scalio 把 slot 状态形式化成四类：可复用空槽、填充中槽、有效完整槽，以及“填充过程中已被失效”的槽。读者在遇到进行中状态时会重试，写者通过清除 `occupied` 完成失效；如果 client 崩溃，还可以通过可选 lease 回收被遗弃的填充过程。论文随后为 cache hit、cache miss 和 write 分别定义 linearization point，并证明每次读都会返回最近一次先行写入的值。

## 实验评估

实验平台由一个 storage node 和五个通过 RDMA 连接的 client node 组成；存储侧配有 7 块 Samsung 970 PRO SSD 和一张 ConnectX-6 HCA。为了模拟 commodity DPU JBOF，作者把服务器限制为 8 个 Xeon 核和 8 GB 内存。工作负载使用 YCSB A、B、C、D、F，在 2000 万条 key-value 上运行，key 最长 16 字节、value 最长 64 字节。对比基线是 LEED，以及把 Ditto 作为远程内存缓存接到 LEED 上的 LEED+Ditto。

最重要的扩展性结论很清楚：当 SSD 数从 1 增加到 7 时，LEED 和 LEED+Ditto 在 server 侧碰到 CPU 墙后都会趋于饱和，而 Scalio 还能继续扩展。论文报告，相比 LEED+Ditto，Scalio 吞吐提升 1.8x-3.3x；相比 LEED，提升 2.5x-17x。对读密集的 B、C、D，增益最高约 3x；对写密集的 A、F，最高约 2x。分解实验也很有信息量：仅仅 offloaded read 就带来 1.5x-3.2x 提升；inline cache 在 YCSB B、C、D 中分别吸收了 72.2%、85.2%、62.6% 的操作，对应 3.6x、6.7x、2.7x 提升；batched write 最高再增加 1.96x，因为它把每次更新的 SSD 写次数从 2 次降到大约 1 次。

实验也清楚展示了代价。关闭 batched write 时，Scalio 相比 LEED+Ditto 同时具备更高吞吐和更低延迟，平均延迟下降 20%-30%。打开 batching 之后，系统吞吐进一步上升，但写延迟也会因为 linearization point 绑定到 SSD 落盘和 cache invalidation 而增加。论文用 YCSB A 举例：Scalio 获得 2.1x 更高吞吐，同时平均延迟增加到 614 us，为基线的 1.97x。整体来看，实验最有力地证明了“CPU offload 才是真正瓶颈”的论点；相对薄弱之处在于部署真实性，作者使用的是受限 Xeon 模拟的 DPU 环境，而且实验最多只做到 7 块 SSD，而不是动机中提到的 26-36 块高密度 JBOF。

## 创新性与影响

相对于 _Guo et al. (SIGCOMM '23)_，Scalio 的区别不只是“把 JBOF 上的 SSD-backed KV layout 做得更好”，而是重新定义了哪个硬件部件位于 critical path。LEED 仍然把 SSD 操作压在 DPU CPU 上，而 Scalio 把读 I/O 改由 NVMe-oF target offload 执行，并把 DRAM 元数据当作远程 RDMA 对象来访问。相对于 _Shen et al. (SOSP '23)_，它的贡献也不只是“再加一层 cache”：Ditto 是弹性的 disaggregated DRAM cache，而 Scalio 则把 cache 与 SSD offset、失效协议和 linearizability 证明放进同一个整体设计里。

这篇论文最可能影响的是做 SmartNIC/DPU storage server、storage disaggregation 和小对象 KV serving 的系统研究者或工程团队。它提供的主要不是新的 workload study，而是一套新的机制组合：target-offloaded SSD read、inline 的 RDMA-visible cache、buffered writeback，以及显式的 cache-consistency 状态机。论文因此提出了一个很有价值的工程判断：target offload 不应只被视作 NVMe 传输层的小优化，而应被视作 storage system 设计中的一等原语。

## 局限性

Scalio 明显是为小型 point operation 调优的。实验里的 key 最长 16 字节、value 最长 64 字节，而且由于系统并不面向 range query，YCSB E 被直接省略。论文没有展示 inline block 设计在大 value、多记录事务，或者局部性不足以支撑高 cache hit ratio 的 workload 下会如何表现。

这个系统也没有真正消灭 DPU CPU 的控制面角色，只是把它压缩到了较小范围。写路径仍然要经过 server 侧 batching、通知和失效，因此设计用一部分写延迟换取了吞吐。对故障的处理也并不完整。Scalio 增加了一个可选 lease 来回收被遗弃的填充过程，但 server failure 主要还是交给 RAID 或 dual-DPU 这类外部冗余机制，而不是在核心协议内部处理。最后，实验只在“8 核、8 GB、最多 7 块 SSD”的模拟 DPU 环境上完成，因此论文关于超高密度 JBOF 的最强论断仍然带有外推成分，而不是完整的端到端展示。

## 相关工作

- _Guo et al. (SIGCOMM '23)_ - LEED 面向相同的 SmartNIC JBOF 场景，但它的 DPU CPU 仍需执行 SSD I/O，这正是 Scalio 试图消除的扩展瓶颈。
- _Shen et al. (SOSP '23)_ - Ditto 是 disaggregated DRAM caching system；Scalio 借鉴了“client 可见远程 cache 状态”的思路，但把它和 SSD-backed offset、可线性化的失效协议结合在一起。
- _Sun et al. (CLUSTER '22)_ - SKV 把分布式 KV store 的部分工作卸载到 SmartNIC，而 Scalio 聚焦 JBOF server，并把直连 SSD 的读取进一步推进到 NVMe-oF target offload。
- _Zhang et al. (FAST '22)_ - FORD 依赖 one-sided RDMA atomic 来支撑 disaggregated persistent memory 上的事务；Scalio 则用更轻量的 RDMA 协议维护 SSD-backed KV store 中的 cache/index。

## 我的笔记

<!-- 留空；由人工补充 -->

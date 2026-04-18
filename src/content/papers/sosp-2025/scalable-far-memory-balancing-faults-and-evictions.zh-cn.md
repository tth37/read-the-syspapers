---
title: "Scalable Far Memory: Balancing Faults and Evictions"
oneline: "Mage 通过把驱逐彻底移出 fault 临界路径、跨批次流水化执行并分片分页元数据，让多核 far memory 在高并发下仍能持续扩容。"
authors:
  - "Yueyang Pan"
  - "Yash Lala"
  - "Musa Unal"
  - "Yujie Ren"
  - "Seung-seob Lee"
  - "Abhishek Bhattacharjee"
  - "Anurag Khandelwal"
  - "Sanidhya Kashyap"
affiliations:
  - "EPFL"
  - "Yale University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764842"
tags:
  - memory
  - disaggregation
  - rdma
  - datacenter
category: memory-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Mage 认为 page-based far memory 在高核数下失效，不是因为 paging 天生太慢，而是因为 fault 与 eviction 耦合得太紧。它把 eviction 移出应用路径，用跨批次流水线隐藏 TLB flush 与 RDMA 等待时间，再用分片元数据替代全局共享结构，从而恢复多核可扩展性。

## 问题背景

page-based far memory 的价值在于，它保留了应用兼容性；但最需要它的工作负载，已经是多核分析任务和在线服务。Hermit、DiLOS 这类已有系统确实让单次 page 操作更便宜了，但在线程数升高后，它们会在远端内存或 RDMA 真正成为瓶颈之前先崩掉。以 48 线程的 GapBS 为例，只 offload 10% 内存时，DiLOS 吞吐已经下降 50%，Hermit 下降 75%，远差于只计算 RDMA 延迟的理想基线。作者把差距归结为三个热点：跨核 TLB shootdown、全局 LRU 一类高争用页面记账结构，以及在高压下出现长尾延迟的本地和远端页面分配器。

## 核心洞察

论文最重要的观点是：fault-in 和 eviction 必须被当成两条不同的 pipeline 来优化。fault-in 位于应用的延迟敏感路径上，只该负责拿空闲页、拉回远端数据、做最少的 bookkeeping；eviction 则是后台吞吐任务，应该独自承担昂贵的协调动作。一旦 fault 线程自己去做 eviction，TLB flush、受害页选择和分配器争用都会进入临界路径，随后形成恶性循环：fault 越多，eviction 越慢；eviction 越慢，fault 代价越高。Mage 的做法因此很明确：禁止 synchronous eviction，只保留少量专用 evictor 线程。

## 设计

Mage 有三个设计原则。第一，always-asynchronous decoupling：系统给 eviction 分配固定后台线程和专用 CPU，faulting 线程完全不参与 eviction。作者发现四个 evictor 线程就足以持续补充 free pages，同时不会制造过多 IPI 争用。

第二，cross-batch pipelined execution：Mage 把不同 batch 的阶段交叠起来执行。每个 evictor 都维护一个等待 shootdown 完成的 TLB staging buffer，以及一个等待远端写回 ACK 的 RDMA staging buffer。当一个 batch 在等 TLB ACK 或 RDMA ACK 时，线程可以去准备或回收其他 batch，用网络等待时间覆盖协调开销。

第三，prioritizing scalability via coordination avoidance：Mage 明确接受“少一点全局最优，换更多并行度”。它用 partitioned LRU 替代单个全局 LRU，让 evictor round-robin 扫描不同分片；新页面按 CPU 哈希打散到各分片。free-page 缓存也被分片化，MageLib 进一步用三级分配器降低争用。远端分配则直接把本地偏移映射到远端偏移，不再维护 swap-entry 分配器。论文把这些思想同时实现为 Linux 4.15 上的 MageLnx 和 OSv 上的 MageLib，说明贡献不是某个特定内核技巧。

## 实验评估

实验覆盖了随机访问分析任务、可预取顺序扫描、工作集相位切换、Memcached 和多组微基准，运行平台是 200 Gbps RDMA 测试床。最关键的吞吐结果来自 48 线程 GapBS：在 10% far memory 下，MageLib 和 MageLnx 的吞吐只下降 15% 和 19%，而 DiLOS 和 Hermit 分别下降 51% 和 74%。在 XSBench 上，Mage 大约能在 20% 吞吐损失下承受 20% offload，比基线系统多出 3.6-3.8 倍的可 offload 内存。

微基准解释了原因。MageLib 在顺序读测试中达到 181 Gbps，约为 192 Gbps RDMA 上限的 94%，分别是 DiLOS 和 Hermit 的 3.1 倍、7.1 倍；p99 fault latency 也从基线的 82 us 和 255 us 降到 MageLib 的 12 us、MageLnx 的 31 us。对 Memcached，在 p99 200 us 的 SLO 下，MageLib 比 DiLOS 多 offload 21% 内存、比 Hermit 多 36%。这些结果与论文主张基本一致，不过比较并非完全对称，因为 Hermit 跑在 bare metal，而 MageLib 和 MageLnx 跑在 VM 中。

## 创新性与影响

相对 Hermit 和 DiLOS，Mage 的新意不在于换了新的 far-memory backend，也不在于更激进的 prefetch，而在于重新分解了 paging 系统。论文认为，只有把 eviction 变成拥有专用资源和低争用元数据的后台吞吐 pipeline，透明 far memory 才能真正扩展到多核。这把 page-based far memory 的关注点，从“让单次 page fault 更便宜”转成了“把协调代价移出 fault 路径”。

它的影响也不限于 RDMA。作者明确认为，同样的 OS 级思想可以迁移到 SSD-backed swap 和 zswap 这类快速后端。

## 局限性

Mage 的收益来自额外资源投入，也来自对策略精度的让步。系统默认需要专用 eviction 核，而 partitioned LRU 与简化远端分配也确实没有全局最优策略那么精确。

实验还揭示了现实限制。MageLib 和 MageLnx 在 100% local memory 下都慢于 Hermit，原因包括虚拟化开销以及 OSv 用户态库成熟度不足。MageLnx 还受到 Linux 网络栈干扰，并且没有实现 MageLib 展示的 prefetch 支持。更根本地说，Mage 仍然是 page-granularity 的系统，所以它只是让 paging 更可扩展，并没有消除 paging 的 I/O amplification 和 locality 依赖。

## 相关工作

- _Qiao et al. (NSDI '23)_ — Hermit 同样追求 Linux 上的透明 remote memory，但它的 feedback-directed asynchrony 仍会退化到 synchronous eviction，因此在线程数升高后明显失速。
- _Yoon et al. (EuroSys '23)_ — DiLOS 通过专用 LibOS 去掉了大量 Linux 分页开销，而 Mage 的结论是：仅靠特化还不够，还必须把 eviction 做成可扩展的后台流水线，并重写高争用元数据。
- _Ruan et al. (OSDI '20)_ — AIFM 通过 application-integrated far memory 避开 page fault，本质上要求应用改写；Mage 则坚持对未修改应用透明，只改造 paging 子系统本身。
- _Weiner et al. (ASPLOS '22)_ — TMO 证明了 page-based memory offloading 可以在 hyperscaler 规模部署，Mage 进一步追问的是：多核条件下，OS 内部的 fault/eviction 路径怎样设计才能把这些远端容量真正用起来。

## 我的笔记

<!-- empty; left for the human reader -->

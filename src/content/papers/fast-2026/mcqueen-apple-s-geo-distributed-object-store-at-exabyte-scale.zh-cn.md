---
title: "McQueen: Apple’s Geo-Distributed Object Store at Exabyte Scale"
oneline: "McQueen 把 Apple 的对象存储从双区域全副本演进到五区域 XOR 分段，在 exabyte 规模上把复制因子从 2.40 降到 1.50。"
authors:
  - "Benjamin Baron"
  - "Aline Bousquet"
  - "Eric Metens"
  - "Swapnil Pimpale"
  - "Nick Puz"
  - "Marc de Saint Sauveur"
  - "Varsha Muzumdar"
  - "Vinay Ari"
affiliations:
  - "Apple"
conference: fast-2026
category: cloud-and-distributed-storage
tags:
  - storage
  - fault-tolerance
  - datacenter
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

McQueen 是 Apple 的生产级 geo-distributed object store，承载数个 exabytes 数据并处理每天数十亿次请求。论文的主线，是把 McQueen 1.0 的“站内 LRC + 跨区域全副本”演进到 McQueen 2.0 的“五区域 `4+1` XOR 分段”，从而把整体复制因子从 `2.40` 降到 `1.50`，代价是完整对象 GET 更慢。

## 问题背景

Apple 想要一个统一对象存储，同时承接 iCloud 数据、媒体文件、Maps 资源和内部数据集。这些 workload 从很小的 metadata 对象到数 GB 视频分片都有，同时混合了用户面延迟需求和长期耐久性要求。

McQueen 1.0 已经具备很强的可用性：两个 active-active 区域、站内 erasure coding、degraded read，以及异步跨 stamp 复制。但十多年后，三个问题变成瓶颈：`(20, 2, 2)` LRC 加远端整对象副本把复制因子推到 `2.40`；固定容量的 store 迫使大客户维护多个 endpoint；而 Cassandra metadata 层也让统一多区域部署难以平滑扩展。

## 核心洞察

论文最核心的判断是：本地故障和区域故障不该用同一种冗余方式。站内继续使用 LRC，因为局部硬件故障需要高效修复；跨区域则不再镜像整个对象，而是把对象切成四个 data segments 加一个 XOR parity segment。任意四段都能恢复第五段，在明显降低冗余的同时保住区域级耐久性。

这也改变了系统抽象。metadata 记录的是各个 segment 的位置，而不是另一份完整对象的位置；于是系统就能暴露统一 endpoint，把 rebalancing 和扩容留在控制面处理。

## 设计

McQueen 1.0 的结构是一个 store 由两个不同区域的 stamp 组成。每个 stamp 都包含 load balancer、无状态 request handler、coordinator、metadata 和连接 JBOD 的 storage hosts。对象写入大 containers，新数据先进入五副本 container cluster；cluster 写满后再 sealing 成 LRC 编码布局，先是 `(12, 2, 2)`，后来是 `(20, 2, 2)`。coordinator 负责放置、compaction 和 repair。读路径则按“本地数据 -> 站内 LRC 重建 -> 对端 stamp”逐级回退。

McQueen 2.0 保留 stamp 抽象，但把 deployment 扩展到五个区域。PUT handler 把对象或 multipart part 切成四个 data segments 加一个 XOR parity segment，分别写到五个区域，只要四段成功就返回；缺失段之后由异步流程补齐。GET 直接读取需要的数据段，或者用 parity 重建一个缺失段；range GET 则尽量只抓所需字节。

最大的控制面变化是 ClassVI：一个基于 RocksDB、用 Raft 提供行级强一致性的 geo-distributed metadata store。handler 会把本地 inconsistent read 与后续 consistent validation 结合起来做预取。McQueen 2.0 还加入统一 DNS endpoint、基于容量的 stamp weights、按文件搬运 sealed containers 的 rebalancer，以及 geo-routing 和 inter-stamp 绕过 load balancer。

## 实验评估

这部分评估是生产回顾而不是实验室基准：作者统计了全量主机上一个月的线上流量，因此结果反映真实 workload，但不是完全受控的 1.0 对 2.0 对比。主要结论是，McQueen 2.0 没有明显伤害写路径。GET 的 TTFB 只略差于 1.0；完整对象 GET 平均大约多出 `50 ms`，因为部分 segment 需要跨区域获取。PUT 延迟则基本接近，因为两个系统都直接写 replicated containers，而 2.0 还能并行发起 segment writes。

耐久性结果更关键。在 McQueen 1.0 中，跨 stamp 复制发生在写完成之后，`90%` 的对象会在 `10 s` 内完成复制。到了 McQueen 2.0，`99.99%` 的 PUT 会在同步路径上把五个 segments 全部写好，因此只有 `0.01%` 的对象需要异步 repair。跨区域 reconstruction 在 p90 只增加约 `0.3 ms` 计算开销，真正更贵的是 failover 时的网络距离。站内 degraded read 在 p90 大约多出 `2 ms` 重建成本，在 p50 前大约多出 `30 ms` 延迟。论文还报告，迁移前优化把 server-side latency 最多压低 `60%`，而 load-balancer bypass 把 p50 请求延迟降低 `22%`。因此，这篇论文证明的不是“2.0 更快”，而是“2.0 更适合长期扩展”。

## 创新性与影响

McQueen 的价值不在于发明了新的编码或对象 API，而在于把“按故障域拆分冗余、围绕 segments 重构 metadata 与 placement、在不停机前提下迁移 live exabyte store”连成了一套生产经验。相对于 _Muralidhar et al. (OSDI '14)_ 和 _Pan et al. (FAST '21)_，它更像是一份 geo-distributed exabyte storage 的运维总结；相对于 _Noghabi et al. (SIGMOD '16)_，它更强调强一致的 geo-distributed metadata。

## 局限性

它的局限就是这套取舍的直接结果。McQueen 2.0 能承受一个区域失效，但不能承受两个区域同时失效；若两个及以上区域不可用，依赖缺失 segment 的请求就会失败。完整对象 GET 也天然比 1.0 慢，因为地理距离进入了关键路径。再者，1.0 与 2.0 的对比带有明显的生产观察性质。最后，Table 3 的耐久性分析依赖独立失效和指数修复时间等常见假设，更适合做设计空间判断。

## 相关工作

- _Muralidhar et al. (OSDI '14)_ — f4 也使用区域级 XOR 编码，但 McQueen 把这类思路放到了更广泛的 Apple 多租户对象存储上。
- _Noghabi et al. (SIGMOD '16)_ — Ambry 是 geo-distributed immutable object storage；McQueen 则支持 active-active 写入和强一致 metadata。
- _Pan et al. (FAST '21)_ — Tectonic 面向相近规模，而 McQueen 更强调多区域冗余和用户面可用性。

## 我的笔记

<!-- 留空；由人工补充 -->

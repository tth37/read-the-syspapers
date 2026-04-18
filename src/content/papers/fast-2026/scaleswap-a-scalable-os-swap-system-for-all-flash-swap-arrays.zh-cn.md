---
title: "ScaleSwap: A Scalable OS Swap System for All-Flash Swap Arrays"
oneline: "把 Linux swap 改成按核独占的 swap 文件、元数据委托和按核 LRU，让全闪存 swap 阵列的性能随 SSD 数量和核心数一起扩展。"
authors:
  - "Taehwan Ahn"
  - "Chanhyeong Yu"
  - "Sangjin Lee"
  - "Yongseok Son"
affiliations:
  - "Systems and Storage Laboratory, Chung-Ang University"
conference: fast-2026
category: flash-and-emerging-devices
code_url: "https://github.com/syslab-CAU/ScaleSwap"
tags:
  - memory
  - kernel
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ScaleSwap 重写了 Linux swap 在 many-core 服务器上的并发模型，目标是让 all-flash swap array 的带宽真正用起来。它不再让所有核心竞争同一组 swap 元数据、swap 空间和 LRU，而是把这些资源尽量按核私有化，只有在页面必须跨核访问时才委托元数据操作。论文在一台 `128` 核、`8` 块 NVMe SSD 的机器上显示，ScaleSwap 相比 Linux swap 最高获得 `3.41x` 吞吐提升和 `11.5x` 平均延迟下降。

## 问题背景

把 swap 条带化到多块 SSD 上，并不能自动得到可扩展的 swap。现代图处理、数据分析、虚拟化和容器工作负载经常需要远超 DRAM 的内存容量，而 SSD 的价格和容量已经让它成为现实中的最后一级内存。但 Linux swap 仍然采用 all-to-all 模型：任何核心都可能访问任何 swap space；一旦 direct reclaim 触发，多条应用线程会并行回收页面，却同时去争用共享的 per-node LRU 和共享的 swap metadata。

论文用数据说明了这个矛盾。原始设备上的混合随机读写吞吐，会随着 SSD 数量从 `1` 增加到 `2`、`4`、`8` 时，从 `3.4` 提升到 `5.8`、`9.4`、`11.2 GB/s`。Linux swap 却几乎始终停在约 `4 GB/s`。当核心数升到 `64` 和 `128` 时，Linux swap 的吞吐甚至比原始设备低 `1.5x` 和 `2.6x`。所以真正的问题不是闪存不够快，而是 swap 子系统的中心化数据结构把 many-core 并发串行化了。

## 核心洞察

这篇论文最核心的判断是：swap 要想扩展，关键不是继续给 Linux 多挂几块 SSD，而是把大多数 swap 操作变成 one-core-to-one-resource。只要分配页面、淘汰页面、再次 fault 该页面的那个核心，通常都能只访问自己的 swap metadata、swap cache、swap file 和 LRU list，那么两类主要锁竞争就会一起下降。

跨核情况当然仍然存在，例如本地 swap file 已满、页面被共享，或者进程迁移导致页面落在别的核心的 swap space 中。ScaleSwap 的做法是只把元数据访问委托给资源拥有者核心，而真正的页面 I/O 仍由请求方线程直接完成。这样既保留了一致性，又避免把每次 swap in/out 都变成一次跨核临界区。

## 设计

ScaleSwap 的第一部分是 core-centric resource management。每个核心都有自己的 swap metadata、swap cache、swap slot、swap file，以及共享的 per-core LRU list。为了突破 Linux 仅支持 `23` 个 swap space 的限制，论文把 swap entry 的 type 字段从 `5` 位扩到 `8` 位，同时把 offset 从 `50` 位降到 `47` 位。这样一来，可用 swap file 数量提升到 `247` 个，但每个 swap file 仍可表示最多 `128 TB` 空间。于是，核心在需要补充 swap entry 时，可以直接从自己的 swap metadata 所管理的 cluster 中取条目，而不是在全局共享的 swap space 上轮转分配。

第二部分是 opportunistic inter-core swap assistance。如果本地 swap file 已满，或者页面因为共享与迁移而位于别的核心的 swap space 中，请求线程会向目标核心的 per-core delegator 提交一个 `96` 字节的 swap task。该 delegator 是唯一允许修改该核心 swap metadata 的执行者，因此一致性来自所有权，而不是来自一群核心共享同一把锁。更关键的是，委托只负责 metadata 的查找和更新；真正的页面读写仍由请求线程直接对目标 swap space 发起。论文还加入了 cooperative swapping：等待返回的线程可以顺手处理自己核心队列中的任务，而不是纯粹空转。

第三部分是 core-affinity page and LRU management。ScaleSwap 把匿名页的 LRU 从 per-node 改成 per-core，并通过复用 page flag 中的空闲位来记录页面的核心归属。这样，swap-out 时页面从本地核心的 LRU 中被淘汰，swap-in 时又能被重新插回原来的核心 LRU。页面回收路径和 swap 资源路径因此对齐，既减少其他核心的干扰，也提高局部性。

## 实验评估

实现基于 Linux `6.6.8`，运行平台是一台 `128` 核服务器，配有 `96 GB` DRAM 和八块 `2 TB` 的 FireCuda 530 NVMe SSD。主要 microbenchmark 使用 `128` 条线程、`128` 个建在 `ext4` 上的 swap file，以及总共 `288 GB` 的访问内存。这套配置和论文宣称的目标场景是吻合的。

核心结果基本支撑了论文主张。随着 SSD 数量从 `1` 增长到 `8`，ScaleSwap 相对 Linux swap 最高获得 `3.41x` 吞吐提升；随着核心数增加到 `128`，ScaleSwap 基本保持线性扩展，而 Linux swap 在 `32` 核后几乎不再提升。延迟收益同样明显：平均延迟最高下降 `11.5x`，`99.9th` 尾延迟最高下降 `27.2x`。Table 5 解释了原因：Linux 有 `53.27%` 的执行时间耗在 `lru_lock` 上；只做部分改造的 ScaleSwap 变体把瓶颈转移到 `si_lock`；完整版本则把两者都压下去，达到 `14.81 GB/s` 和 `66.34 us` 平均延迟，而 Linux 只有 `4.34 GB/s` 和 `768.67 us`。

更广的工作负载也比较可信。在五个 memory-intensive application 上，ScaleSwap 在八块 SSD 时带来 `1.70x-2.57x` 的吞吐提升；在 Apache Spark 处理 `128` 个 Common Crawl WARC 文件时，它在最大输入规模下达到 `6.3 GB/s`，并获得 `1.75x` 加速。和已有系统相比，它相对 TMO 最高快 `64%`，相对 ExtMEM 最高快 `5.02x`。我认为评测最有说服力的地方在于它直接测了 SSD 扩展性、核心扩展性、锁时间分解和 delegation overhead；主要保留意见是，实验仍局限在单一服务器平台和单一文件系统配置上。

## 创新性与影响

相对于 _Weiner et al. (ASPLOS '22)_ 的 TMO 和 _Bergman et al. (USENIX ATC '22)_ 的 ZNSwap，ScaleSwap 关注的不是“何时 offload”或“如何利用特定 SSD 接口”，而是怎样让传统 OS swap 在 many-core 与 multi-SSD 条件下真正扩展。相对于 _Jalalian et al. (USENIX ATC '24)_ 的 ExtMEM，它也没有把内存策略搬到用户态，而是保留 kernel-managed swap abstraction，并把内核里的并发路径重做了一遍。

因此，这篇论文更像是一篇系统机制论文，而不是单纯的测量工作。它的潜在影响对象会是 kernel memory management、SSD-backed memory extension，以及把 swap 视为 CXL 或 disaggregated memory 之下最后兜底层的系统设计者。

## 局限性

ScaleSwap 的优势主要集中在论文刻意瞄准的区间内：单机、direct reclaim、many-core、all-flash swap array。论文没有深入评估更慢的存储介质、更复杂的多租户干扰，也没有真正展示它在 tiered memory 或 disaggregated memory 体系里如何协同工作。硬件实验本身也只覆盖一台 `128` 核、八块 SSD 的服务器。

设计上也有明确的体系结构取舍。它修改了 swap entry 和 page flag 的位布局，以支持 `247` 个 swap file、`47` 位 offset 和 `7` 位 CPU 标识。这些边界对本文测试机器来说是合理的，但它们毕竟是内核级假设，而不是完全透明的替换件。最后，delegation 之所以便宜，是因为它只碰 metadata；可一旦局部性明显变差，吞吐仍会下降，例如在强制 `96` 个 swap file 填满时，吞吐会从 `14.81` 降到 `12.48 GB/s`。所以它是在压力下仍然稳健，而不是对坏局部性完全免疫。

## 相关工作

- _Bergman et al. (USENIX ATC '22)_ — ZNSwap 主要针对 zoned SSD 重新设计 swap，而 ScaleSwap 解决的是常规 NVMe 设备上的 many-core 并发与资源所有权问题。
- _Weiner et al. (ASPLOS '22)_ — TMO 关注透明内存卸载和压力感知的容量管理，ScaleSwap 则直接优化 swap fast path 本身。
- _Jalalian et al. (USENIX ATC '24)_ — ExtMEM 把内存策略放到用户态以实现 application-aware control；ScaleSwap 保留内核管理的 swap，但把它做成可扩展的。
- _Saxena and Swift (USENIX ATC '10)_ — FlashVM 证明了把 flash 用作 swap 的可行性，而 ScaleSwap 的新意在于 per-core ownership 和 metadata delegation。

## 我的笔记

<!-- 留空；由人工补充 -->

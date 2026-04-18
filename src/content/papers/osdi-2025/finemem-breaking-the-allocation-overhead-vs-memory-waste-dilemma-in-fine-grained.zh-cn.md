---
title: "FineMem: Breaking the Allocation Overhead vs. Memory Waste Dilemma in Fine-Grained Disaggregated Memory Management"
oneline: "FineMem 通过预注册整池内存、按 chunk 发放 MW capability，并用带 contention control 的两层位图分配器，把 RDMA 远端内存分配做成细粒度且高效的操作。"
authors:
  - "Xiaoyang Wang"
  - "Yongkun Li"
  - "Kan Wu"
  - "Wenzhe Zhu"
  - "Yuqi Li"
  - "Yinlong Xu"
affiliations:
  - "University of Science and Technology of China"
  - "Google"
  - "Anhui Provincial Key Laboratory of High Performance Computing, USTC"
conference: osdi-2025
code_url: "https://github.com/ADSLMemoryDisaggregation/FineMem"
tags:
  - memory
  - disaggregation
  - rdma
category: memory-and-storage
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

FineMem 把优化重点从远端访问本身，转移到 RDMA 远端分配。它把整池内存一次性预注册，再通过 Memory Window 发放 chunk 级访问能力，并让 compute node 上的服务进程执行受保护的 one-sided 分配。

## 问题背景

RDMA 的 one-sided 读写只有在 memory 已经完成 registration 和授权之后才便宜，而这一步恰恰很贵。论文报告说，注册一个 4 MB memory region 可能超过 480 us。于是现有系统只能在两个坏选项之间取舍：要么通过 memory-node-side RPC 保留 allocator，这样并发一高就卡在 memory node CPU 上；要么预先映射 1 GB 之类的大块内存，避开运行时注册，但会因为粗粒度保留和碎片造成大量浪费。

论文说明这不是纸面问题。在 FUSEE 里，把分配粒度从 1 GB 缩到 2 MB 虽然减少了浪费，却已经带来大约 17% 的吞吐下降；继续缩到 4 KB，开销更重。对 malloc 风格工作负载，hugepage 级远端 chunk 还会留下大量无法安全回收、也无法在异构系统之间共享的空洞。因此，核心问题是：能不能像本地 allocator 一样做细粒度远端分配，而不重新掉回这两种代价之一。

## 核心洞察

FineMem 的核心主张是，registration、protection 和 allocation 不该绑在一起。registration 可以在启动时一次性完成，把整池内存注册成一个大 MR；protection 则通过 Memory Window 重新收缩到 chunk 级，只发放必要的 rkey；allocation 最终被化简成预注册池上的 metadata problem，由 compute node 上受信任的 allocation service 独占修改 allocator metadata。

一旦这三项责任被拆开，剩下的瓶颈就不再是 RNIC registration，而是远端并发控制。FineMem 随后用位图摘要、contention steering 和轻量级 redo logging 去解决这个更窄的问题。

## 设计

在 memory node 上，FineMem 先把整池内存预注册，再为 chunk、span 和 section 预先创建 Memory Window。系统在 capability table 里保存 main rkey 和 backup rkey，因此 `free` 可以在关键路径里切换到 backup rkey，而新 capability 由后台异步再生。compute node 上运行受信任的 allocation service；应用不能直接改全局 allocator metadata。

分配元数据采用专门为 one-sided CAS 设计的两层位图树。一个 section 包含 16 个 span；每个 span 覆盖 128 KB，并进一步切成 32 个 chunk。第一层 section bitmap 用状态位概括每个 span 是 free、正常使用、contended 还是 full，因此大对象可以直接抓取对齐的 span，小对象再下钻到 span bitmap。FineMem 还会在 compute node 本地缓存位图块，尽量缩短搜索路径。

每个 header 都会记录最近的 CAS 失败次数；如果重试超过阈值，FineMem 就把该 section 或 span 标成 contended，并把后续分配引导到更冷的区域。因为在 one-sided allocator 里，竞争的代价不是本地自旋，而是额外的网络往返。

崩溃一致性通过塞进同一 64-bit header 更新里的 temporary redo log 来实现。位图 CAS 成功就是 commit point；之后线程再把 temporary log 刷进完整的 per-chunk redo log，并借助 timestamp 拒绝过时写入。恢复流程扫描 bitmap 和 redo-log 状态，回收崩溃 compute node 持有的分配，并重新生成 rkey。

## 实验评估

实验部署在 CloudLab 上，使用 16 个 compute node 和 1 个 memory node，网络是 ConnectX-6 100 Gb NIC，并且把 memory node 限制为只用一个 CPU core。对比基线包括按需注册的 RPC allocator、预映射的 RPC allocator，以及 one-sided 的预映射数组式 allocator。

在 4 KB 分配、512 个 client thread 的情况下，FineMem 的平均分配延迟是 43.2 us，而 one-sided 预映射基线是 763 us；tail latency 分别是 79 us 和 16.1 ms。元数据统计也解释了差距来源：FineMem 平均每次分配只需要大约 1.3 次 CAS，而数组式设计需要大约 45 次。它也避免了 RPC 方案那种一旦 memory-node CPU 饱和就快速塌陷的扩展性曲线。

端到端结果同样一致。FineMem-User 相比 coarse pre-mapped 方案把内存利用率提升了 2.25x 到 2.8x，而相对静态预分配仅增加 2.5%-4.1% 的开销。FineMem-KV 在 update-heavy 的 YCSB-A 上，相对最佳 RPC 基线提升了约 27%-110% 吞吐；论文也明确指出，在 read-heavy 的 YCSB-B、YCSB-C 和 YCSB-D 上收益会小很多。FineMem-Swap 则把平均远端内存利用率从 41.39% 提升到 74.06%，并把作业吞吐提高了 17.71%。

## 创新性与影响

相对于 _Shen et al. (FAST '23)_，FineMem 去掉了 FUSEE 暴露出来的 memory-node-side RPC allocation 瓶颈。相对于 _Zhang et al. (SOSP '23)_，它保留了 CXL-SHM 那种 pre-mapped shared pool 的思路，但补上了隔离和可预测的细粒度分配。相对于 _Lee et al. (SOSP '21)_，它追求与 MIND 相似的细粒度隔离目标，但不需要 programmable switch。

这让论文的价值不局限于某一个应用。FineMem 不是新的 far-memory programming model，而是能让 malloc system、KV store 和 swap system 高效共享同一 remote memory pool 的底层 allocator substrate。

## 局限性

FineMem 依赖每个 compute node 上一个受信任的 allocation service，并且每次受保护分配都要付出 2-10 us 的 IPC 开销。它还需要提前预注册整个内存池，因此初始化成本和 NIC 元数据容量仍然重要。论文也没有解决 coherence、replication 或数据路径本身的优化问题；它的范围明确限定在 allocator control 上。

它的故障模型也比完整 DM runtime 更窄。FineMem 处理的是 compute-node crash 和 stale log flushing，而不是 memory-node failure 或复制恢复之类更广义的分布式故障。最后，这套机制明显是 RDMA-specific 的，CXL 只作为未来工作出现。

## 相关工作

- _Ruan et al. (OSDI '20)_ — AIFM 面向应用暴露 far-memory 抽象，而 FineMem 关注的是这类系统之下更基础的 remote allocator substrate。
- _Lee et al. (SOSP '21)_ — MIND 用 programmable switch 做 in-network memory management；FineMem 则依靠 software service 和 commodity RDMA NIC 的 MW 机制。
- _Shen et al. (FAST '23)_ — FUSEE 证明了 disaggregated KV store 的价值，但它的 RPC allocation path 正是 FineMem 要替换掉的瓶颈。
- _Zhang et al. (SOSP '23)_ — CXL-SHM 展示了 one-sided pre-mapped shared memory，而 FineMem 在此基础上加入了隔离机制和可扩展的细粒度分配元数据设计。

## 我的笔记

<!-- 留空；由人工补充 -->

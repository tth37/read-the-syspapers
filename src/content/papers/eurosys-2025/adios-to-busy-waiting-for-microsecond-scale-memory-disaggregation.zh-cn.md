---
title: "Adios to Busy-Waiting for Microsecond-scale Memory Disaggregation"
oneline: "Adios把内存解耦里的 page fault 从忙等改成可让出的处理路径，再用轻量 unithread 和 PF-aware dispatching 同时压低尾延迟并拉高 RDMA 利用率。"
authors:
  - "Wonsup Yoon"
  - "Jisu Ok"
  - "Sue Moon"
  - "Youngjin Kwon"
affiliations:
  - "KAIST"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717475"
code_url: "https://github.com/ANLAB-KAIST/adios"
tags:
  - memory
  - disaggregation
  - rdma
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Adios 把 memory disaggregation 里的 page fault 从忙等改成 yield。它在同一个 OSv unikernel 里把 fault handler、scheduler 和 `unithread` 接起来，让缺页请求发出 RDMA 后先去跑别的请求，因此同时降低队头阻塞并提高链路利用率。

## 问题背景

最近的 paging-based MD 系统之所以忙等，是因为传统中断唤醒和 kernel scheduler 的代价往往比一次 2-3 us 的 RDMA 取页还高。但这会把局部优化变成系统级坏账：worker 一旦自旋，后面的请求就被堵住；同时在途 page fetch 太少，NIC 也吃不满。论文对 DiLOS 的分析很直白：大约到 1.3-1.4 MRPS，P99 延迟已经恶化，但 RDMA utilization 还只有约 50%。先饱和的是 page fault 控制路径，不是远程内存带宽。

## 核心洞察

问题不在 yielding 本身，而在 page-fault handler 和 scheduler 之间那道昂贵的 protection boundary。如果两者和 request context 处在同一 address space，fault 发出 RDMA 后就能便宜地挂起，再在 completion 到来时恢复。Adios 真正证明的是：微秒级 MD 需要 kernel 和 scheduler 协同设计，而不是继续把 busy-wait 打磨得更极致。

## 设计

Adios 跑在 OSv 上，把 memory manager、scheduler、应用放在同一 protection domain。每个请求对应一个 `unithread`，它把 packet payload、保存的上下文和 universal stack 放在同一个预分配 buffer 中；这条栈同时服务应用执行和 kernel exception handling。论文给出的数字是：saved context 只有 80 B，每请求最少 4 KB，context switch 比 Shinjuku 的 `ucontext_t` 快 4.7x。

处理缺页时，handler 发出 one-sided RDMA fetch 后立刻 yield，而不是原地 busy-wait。worker 回到 dispatcher 接新请求，等 completion 被 poll 到，再恢复 fault path，完成 page mapping 后继续原请求。系统还用一个 pinned reclaimer thread 提前回收页，避免 yielded fault 卡在回收唤醒上。

yielding 把并发提上去后，新的麻烦是不同 worker 的 outstanding fault 会失衡，某些 RDMA QP 突然排长队。Adios 用 `PF-aware dispatching` 解决：dispatcher 按 outstanding page fault 数对空闲 worker 排序，把新请求优先发给最不拥塞的 worker。reply path 也做了 polling delegation，不再让 worker 自己等发送 completion。

## 实验评估

实验是独立 compute node、memory node、load generator，链路 100 GbE。主 microbenchmark 里，40 GB working set 只有 8 GB 本地 cache，因此 80% 访问都会去 remote memory。相对 DiLOS，Adios 在 1.3 MRPS 时把 queueing delay 在 P99 和 P99.9 分别压低 16.3x 和 36.8x；峰值吞吐到约 2.5 MRPS，是 DiLOS 的 1.58x，RDMA utilization 拉到 82%，不再像后者那样在 50% 左右停住。

应用结果也基本一致。相对 DiLOS，Adios 把 Memcached 的 P99.9 latency 最多降 10.89x，把 RocksDB GET 的 P99.9 latency 降 7.61x，把 Silo 的 P99.9 latency 降 2.24x，把 Faiss 的 P99.9 latency 降 1.99x；吞吐提升是 1.07x 到 1.64x。RocksDB 最能说明问题，因为论文还加了一个带 preemptive scheduler 的 `DiLOS-P`，而 Adios 依旧在 GET 尾延迟和吞吐上更好。这说明 scheduler 抢不抢占只是表象，page-fault handler 是否参与协作才是本质。要挑剔的话，作者没有给出和 AIFM 这类 library-based 方案的直接对比。

## 创新性与影响

相较 _Gu et al. (NSDI '17)_ 的 Infiniswap，Adios 把 yielding 带回 paging-based MD，而且不再吞掉老式 scheduler 的切换成本。相较 _Qiao et al. (NSDI '23)_ 的 Hermit 和 _Yoon et al. (EuroSys '23)_ 的 DiLOS，它证明了自旋不是唯一答案。后续 far-memory、microsecond scheduler 和 unikernel 工作大概率都会引用它。

## 局限性

现实门槛不低。Adios 是 OSv prototype，不是 Linux 可直接部署的机制；评估里也仍然需要少量应用改动和每应用 100-300 LoC adapter。它最适合高并发、重内存的服务，计算密集或线程很少的程序收益有限。scheduler 依旧是 cooperative 且 single-queue，作者承认大约只能扩到十个 worker core；系统还要为 dispatcher 和 reclaimer 预留 pinned thread。当前网络路径也主要面向 UDP 风格的微秒级栈，而非完整的生产级 TCP。

## 相关工作

- _Gu et al. (NSDI '17)_ - Infiniswap 最早把 paging-based MD 做成系统，但传统 scheduler 太贵，后来很多方案才转去 busy-wait。
- _Qiao et al. (NSDI '23)_ - Hermit 会把部分工作与 fault latency 重叠执行，但 fault path 里仍保留 busy-wait。
- _Yoon et al. (EuroSys '23)_ - DiLOS 是最强的 busy-waiting transparent MD 基线，Adios 则改写了它和 scheduler 的配合方式。
- _Ruan et al. (OSDI '20)_ - AIFM 也避免 busy-wait，不过它是 application-integrated library，而不是 paging-based 系统。

## 我的笔记

<!-- 留空；由人工补充 -->

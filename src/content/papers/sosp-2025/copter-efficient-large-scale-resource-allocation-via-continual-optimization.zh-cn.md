---
title: "COpter: Efficient Large-Scale Resource-Allocation via Continual Optimization"
oneline: "COpter 把轮次式 LP/MILP 分配器改成 continual optimization：稀疏问题就地更新、用 proximal solver 复用上一轮计算，并用轻量 shim 快速恢复整数解。"
authors:
  - "Suhas Jayaram Subramanya"
  - "Don Kurian Dennis"
  - "Gregory R. Ganger"
  - "Virginia Smith"
affiliations:
  - "Microsoft"
  - "Meta"
  - "Carnegie Mellon University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764846"
tags:
  - scheduling
  - datacenter
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

COpter 把连续分配轮次看成缓慢演化的 LP 或 MILP 序列，而不是彼此独立的求解任务。它对稀疏程序做就地更新，用无矩阵分解的 proximal solver 热启动，并在需要整数解时用轻量 shim 收尾，使运行时间相对商业求解器降低了 57-83 倍，而分配质量损失很小。

## 问题背景

优化式资源分配的吸引力在于，它能把公平性、利用率和策略约束直接写进目标函数与约束里，这是启发式很难完整表达的。但生产系统又必须高频重跑这些优化器：GPU 集群调度常常每分钟一轮，WAN traffic engineering 常见是 5 分钟一轮，数据库 shard 负载波动也会不断触发重平衡。在今天的规模下，昂贵的不只是求解本身，而是整条链路：构造巨大的稀疏约束矩阵、求 LP relaxation、再为 MILP 恢复整数可行性。

论文展示了这条链路会如何在最需要频繁全局优化时失控。把 Sia 从 10k GPU 扩到 25k GPU 后，求解时间大约增加 100 倍，只剩 15% 的轮次还能卡在 1 分钟 deadline 内完成。每轮从头重编译会丢掉旧工作，Simplex 和 barrier solver 的内部状态难以增量维护，POP 这类分区方法用全局质量换取速度，而 branch-and-cut 即使面对几乎已经是整数的 LP relaxation，也可能成为主要瓶颈。

## 核心洞察

这篇论文最重要的判断是，许多大规模资源分配工作负载在两个维度上都属于“缓慢演化”：问题规模本身跨轮次变化很小，最优解的位置也几乎不动。作者在 Sia trace 上观察到，相邻轮次里少于 0.01% 的变量会改变取值，而新增或删除的变量通常也只占几个百分点。如果系统把这种时间连续性视为一等公民，那么 allocator 的运行时间就应该跟“变化路径长度”相关，而不是把每一轮都按完整新问题重新付一遍成本。

但这个观察只有在整个求解栈都围绕“复用”重写时才有价值。COpter 因而同时引入可变问题表示、能从相邻最优解中受益的求解器，以及便宜的整数恢复启发式。continual optimization 在这里是一种端到端系统抽象，而不是给现有 solver 加一个 warm-start 开关。

## 设计

COpter 分别处理端到端分配流程里的三个主要阶段。对编译阶段，它提供 differential interface：新增或删除 request 时，只增删对应的变量和约束；资源数量变化时，则只修改右侧向量。为了支撑这种操作，它把稀疏矩阵存成 list-of-lists，而不是更适合连续扫描的 CSR 或 CSC，用部分局部性换来低成本的就地编辑。

在 LP 求解阶段，COpter 选的是 Proximal Point Algorithm，而不是 Simplex 或 interior-point。PPA 不依赖难以复用的矩阵分解，内部状态轻，而且相邻轮次最优解接近时，上一轮解就是天然热启动。作者再用 dual coordinate descent、active set 和稀疏矩阵向量乘，把稀疏性与时间连续性同时利用起来。对 MILP，COpter 则绕开通用 branch-and-cut，改用小型、问题相关的 shim，因为这些工作负载的 LP relaxation 本身已经非常接近二值解。

## 实验评估

实验覆盖三个领域，但验证的是同一个想法。对 GPU cluster scheduling，COpter 把 Sia 的 p99 求解时间从 10k GPU 上的 233.4 秒降到 6.5 秒，在 25k GPU 上则从 2,277 秒降到 40.3 秒，同时平均 JCT 和 makespan 仍接近商业 LP baseline。POP 在较小集群上仍然较快，但到了 25k GPU 更容易丢失质量并错过 deadline。

在 shard load balancing 上，COpter 在满足负载不平衡约束的前提下，相比每轮独立求解 LP relaxation 还快约 2.8 倍。对 WAN traffic engineering，它在大拓扑上仍能把运行时间压到 1 分钟以内，同时达到或逼近最优 max-flow；在 ASN 拓扑和 bimodal traffic 下，它比完整 LP baseline 快约 30 倍，而且分到的总流量还比 POP 高 1.5%。整体评估覆盖面足够广，不过仍主要建立在 trace-driven simulation 上，而不是线上部署。

## 创新性与影响

概念上最接近的对照物是 POP。POP 通过把一个大问题切成许多并行子问题来扩展规模，而 COpter 保留全局问题本身，把“时间”当成额外可利用的结构来摊薄计算。相对 Sia 或 Rebalancer 这类 policy 或 framework 论文，COpter 不是在提出新的优化目标，而是在提供一种能让 LP/MILP allocator 真正高频运行起来的执行策略。

这也是论文最重要的影响所在。凡是已经相信优化建模、却因为求解成本太高而不敢频繁重算的 capacity allocator、reservation system 或 traffic controller，都可能直接受益于这种抽象。

## 局限性

COpter 明确不是通用答案。作者直接指出，如果 request 或 resource 在相邻轮次之间剧烈变化，例如 serverless 调度、数据库 query 调度、细粒度 streaming task 调度，continual optimization 就很难复用到足够多的上一轮状态。

MILP 这一侧也明显是在用保证换速度。各类 shim 都是按领域手工设计的，优先保证可行性而不是最优性，而且它们之所以有效，很大程度依赖这些工作负载的 LP relaxation 本来就接近整数。除此之外，论文没有给出真实生产系统集成，因此运维调参和维护成本仍是开放问题。

## 相关工作

- _Narayanan et al. (SOSP '21)_ - POP 通过资源和请求分区来并行求解子问题，而 COpter 保留全局问题，并沿时间轴复用先前计算。
- _Subramanya et al. (SOSP '23)_ - Sia 是代表性的 MILP 调度策略；COpter 则是让 Sia 这类策略在更大规模下仍能频繁运行的优化执行层。
- _Kumar et al. (OSDI '24)_ - Rebalancer 把调度策略编译成 MILP，并在大规模时退回 local search；COpter 试图把“仍可做全局优化”的规模边界继续往前推。
- _Xu et al. (SIGCOMM '23)_ - Teal 用 learning 加 ADMM 加速 WAN traffic engineering，而 COpter 则利用时间连续性来加速优化本身，不依赖 learned surrogate。

## 我的笔记

<!-- 留空；由人工补充 -->

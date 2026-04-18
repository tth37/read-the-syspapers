---
title: "Kamino: Efficient VM Allocation at Scale with Latency-Driven Cache-Aware Scheduling"
oneline: "Kamino 将排队时间与分层缓存命中一起建模，把每个 VM 请求派发给预测端到端延迟最低的 allocator agent。"
authors:
  - "David Domingo"
  - "Hugo Barbalho"
  - "Marco Molinaro"
  - "Kuan Liu"
  - "Abhisek Pan"
  - "David Dion"
  - "Thomas Moscibroda"
  - "Sudarsun Kannan"
  - "Ishai Menache"
affiliations:
  - "Rutgers University"
  - "Microsoft Research"
  - "Microsoft Azure"
conference: osdi-2025
tags:
  - scheduling
  - virtualization
  - datacenter
  - caching
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Kamino 是一个面向 allocator agent 的 VM 请求调度器，它直接预测端到端延迟，而不是只看负载或 cache hit rate。其核心策略 LatCache 同时建模排队等待、当前剩余服务时间以及分层缓存状态，再把请求送到预测完成时间最短的 AA。论文在 Azure 生产环境中报告 cache miss 下降 33%，allocator 平均延迟下降 21.1%。

## 问题背景

大型云平台的 VM allocation 必须同时满足两个目标：一方面请求要在几十毫秒量级内完成；另一方面调度器又要在几十万台服务器组成的库存上评估大量 placement constraint 与 preference。单次请求的规则求值因此相当昂贵，负载突发时尤其容易成为瓶颈。为此，生产系统通常会在单个节点内运行多个 allocation agent，并用内存缓存复用先前的规则计算结果。

论文指出，现有系统并没有把这两件事真正结合起来。像 round-robin、random assignment 或 shared FIFO queue 这样的 cache-oblivious 调度方式，会把请求派给当下空闲的 AA，即使另一个 AA 已经缓存了该请求类型或其中部分规则结果。在 VM allocation 场景里，这种错误代价很高，因为缓存项很大，hit 与 miss 的代价差异明显，而且缓存还是分层的：同一个请求可能是 top-level hit，也可能只是 lower-level partial hit，或者完全 miss。单纯的 request pinning 也不够，因为热门请求类型会把流量集中到少数 AA，造成排队膨胀。真正的问题是，系统需要在变化中的负载下，同时权衡 locality 与 queueing delay，而且不能依赖共享缓存或高成本同步。

## 核心洞察

Kamino 的核心判断是：AA assignment 应直接优化预测的 request latency，而 cache locality 只是这个预测中的一个输入，不应被当成唯一目标。对每个候选 AA，调度器都应该综合三个量：该 AA 当前正在执行请求的剩余时间、队列里已有请求将消耗的时间，以及这个新请求真正开始执行时在该 AA 上可能产生的 processing time。后者又取决于它届时可能看到的 cache state，而不是到达瞬间的 cache state。

这种表述方式同时避开了两类失败模式。如果某个 AA 虽然缓存最完整，但队列已经很长，LatCache 可以把请求派到别处；如果另一个 AA 很空闲但会经历严重 miss，LatCache 也可以保留 locality。论文还给出理论结果：在 latency estimation 完美的前提下，LatCache 能把不同 AA 的 queue waiting time 控制在彼此相差不超过一个最大 processing time 的范围内；与此同时，它的 cache-aware 估计仍然会鼓励相似请求共置，从而提升 hit rate。

## 设计

Kamino 部署在 allocator node 内部，不改动底层 allocator 真正执行机器选择的逻辑。架构上的变化是：每个 AA 都拥有私有 FIFO queue，而 agent selector 负责决定每个新请求进入哪条队列。请求到达后，request classifier 会根据与该请求相关的 allocation rules 以及这些规则依赖的 request traits，计算出一个 equivalence-class key。这个 key 用来判断某个 AA 是否已经缓存了该请求，或缓存了其中可复用的子结果。

LatCache 随后为每个 AA 估计总延迟，公式由三个部分组成：`processingTime`、`queueTime` 和 `remainingProcTime`。`processingTime` 是新请求一旦真正开始服务后的预计执行时间；`queueTime` 是该 AA 队列中已有请求预计消耗的总时间；`remainingProcTime` 则是当前正在执行的请求还剩多少时间。如果 AA 空闲，这一项就是 0。

真正难的是 `processingTime`，因为 VM allocation 使用的是分层缓存。top-level cache 保存某一整个请求类型的 consolidated candidate-machine list；lower-level cache 保存单条规则的求值结果，这些结果能被相关但不完全相同的请求复用。若是 top-level hit，请求主要做的是对已有缓存结果进行增量更新；若是 top-level miss，Kamino 会继续检查所需规则是否已存在于 lower-level cache 中，对命中的规则按 rule-hit 代价计费，对其余规则按 rule-miss 代价计费。为了估计“请求开始执行时”缓存会长什么样，LatCache 使用一个 augmented cache state：它乐观地假设 AA 会保留当前缓存内容，并且会在新请求开始前把当前队列里请求对应的对象也带入缓存。论文认为这种乐观预测在实践中很准，因为队列中的不同请求类型数量通常远小于缓存能容纳的种类数。

实现上，Kamino 刻意保持轻量。request classifier 和 agent selector 位于 critical path 上；latency estimator 作为后台模块持续收集 hit/miss 时间并更新均值估计。selector 还维护每个 AA 的元数据，包括该 AA 是否 busy，以及一个 `<request type key, count>` 映射，用来快速判断某类请求是否已经在队列中等待。论文报告调度开销只有微秒级，相比 tens 到 hundreds of milliseconds 的 allocation latency 可以忽略。

## 实验评估

这篇论文的实验很扎实，因为它既有 high-fidelity simulator，也有 production rollout。模拟器使用六条来自高流量 allocator node 的真实 24 小时 trace，每条 trace 含 500 到 1.7k 个 unique request type。生产评测则覆盖五个代表性 Azure zone，比较部署前后各 15 天的数据。

在与 Protean 的 shared-queue scheduler、Random、Round-Robin，以及 consistent hashing + work stealing 的 cache-aware baseline 对比时，LatCache 的延迟表现最好。模拟实验中，`LatCache-request` 与更完整的 `LatCache-rule` 都显著优于所有基线，相比 Protean 带来超过 50% 的 tail-latency 改善，并在 burst 时实现约 2x throughput。Table 3 解释了原因：Protean、Random、Round-Robin 的 top-level hit rate 大约都在 81% 左右，Hash+WS 达到 87.4%，`LatCache-request` 达到 93.1%，`LatCache-rule` 达到 95.0%。同一张表还显示，归一化 cache memory usage 从 Protean 的 1.00 降到 `LatCache-rule` 的 0.77。

论文还专门验证 latency model 是否足以驱动正确决策。其基于 augmented cache state 的 hit/miss event prediction 在两个 cache level 上达到 99.1% 准确率。虽然具体 hit/miss 时间的平均估计误差仍有 29%，`LatCache-rule` 依然能为 91.9% 的请求选中真实最优的 AA；即便没选中，所选 AA 的总延迟平均也只比最优方案差 2.3%。作为对照，一个忽略 rule-level cache、future hit prediction 和 remaining processing time 的 naive 版本，只能在 65.4% 的请求上选到最佳 AA。

生产部署使用的是更容易接入现有 cache API 的 `LatCache-request`。即便如此，allocator 平均延迟仍从 185.6 ms 降到 146.3 ms，下降 21.1%；p90 延迟从 378.8 ms 降到 333.5 ms，下降 11.9%。五个 zone 的平均 cache hit rate 从 80% 升到 86.6%，作者据此给出 cache miss 降低 33% 的结果。与此同时，每个 allocator node 的 memory usage 下降 17%，CPU usage 下降 18.6%。

## 创新性与影响

相对于 _Hadary et al. (OSDI '20)_ 提出的 Protean，Kamino 把注意力放在 Protean 仍采用简单策略的部分，也就是节点内部多个 private-cache allocator agent 之间的请求分配。相对于 _Schwarzkopf et al. (EuroSys '13)_ 和 _Tang et al. (OSDI '20)_ 这类更通用的 cluster manager，Kamino 的范围更窄，但它把 VM allocation 中 queueing、hierarchical caching 与 latency 之间的耦合分析得更深。相对于 consistent hashing 这类 cache-affinity 方案，它指出 hit rate 只是 proxy；一旦 queueing 成为主导因素，只追求 locality 反而会做出更差的决定。

这项工作的重要性在于，allocator control plane 运行在 ring-fenced 的管理节点上，这些节点还要同时承载大量其他 control-plane 服务。一个既能降延迟、又能降低 cache memory 和 CPU 成本的调度器，不只是让单次 allocation 更快，而是直接提升单节点可容纳的 AA 数量，并减少 placement system 中的 contention 与 retry。更一般地说，论文给出的系统观点是：在 hit/miss 成本高度可变的缓存系统里，cache-aware scheduling 应优化 predicted completion time，而不是孤立地优化 cache affinity。

## 局限性

Kamino 最强的结果依赖于一组相对具体的架构假设：单节点内有多个使用 private cache 的 AA、队列为 FIFO、不支持 preemption，而且请求一旦入队就不会重新分配。如果未来 allocator 改成 shared cache、不同的 queue discipline，或在 assignment 时引入跨节点协同，那么论文中的分析与算法都不能直接照搬。

实验也有明显边界。模拟器虽然使用真实 trace，但并未完全建模生产环境中的一些效应，例如多个 AA 选中同一台机器后产生的 conflict 与 retry；论文明确指出，这也是 production gain 小于 simulation 的原因之一。真正上线验证的只有较简化的 `LatCache-request`，而不是在模拟中表现最强的 `LatCache-rule`。此外，作者提到方法可能推广到 LSM tree、CDN 和 microservices，但目前证据只停留在 appendix 中一个小型原型，而不是完整系统评测。

## 相关工作

- _Hadary et al. (OSDI '20)_ - Protean 已经把 hierarchical caching 用在 VM allocation 中，但它在 AA assignment 上仍然是 cache-oblivious 的 shared-queue pull 模型；Kamino 直接改造的就是这一层。
- _Tang et al. (OSDI '20)_ - Twine 是面向共享基础设施的通用 cluster manager，而 Kamino 更聚焦于 private-cache allocator agent 下的单请求低延迟调度。
- _Schwarzkopf et al. (EuroSys '13)_ - Omega 研究的是多 scheduler 并行管理大集群的问题；Kamino 则研究单个 allocator node 内如何在多个 AA 间分发请求这一更局部但更 latency-critical 的问题。
- _Yan and Li (USENIX ATC '22)_ - latency-aware CDN caching 也强调不能只看 hit rate，但 Kamino 把这一思想进一步扩展到 VM allocator 内部的分层规则缓存与排队模型。

## 我的笔记

<!-- 留空；由人工补充 -->

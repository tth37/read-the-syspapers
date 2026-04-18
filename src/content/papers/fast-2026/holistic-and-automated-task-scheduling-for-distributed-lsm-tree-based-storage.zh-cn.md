---
title: "Holistic and Automated Task Scheduling for Distributed LSM-tree-based Storage"
oneline: "HATS 把副本分配、按请求重定向和按读负载驱动的 compaction 控制放进同一闭环，在 Cassandra 上把 P99 读延迟最高降低约 79%。"
authors:
  - "Yuanming Ren"
  - "Siyuan Sheng"
  - "Zhang Cao"
  - "Yongkun Li"
  - "Patrick P. C. Lee"
affiliations:
  - "The Chinese University of Hong Kong"
  - "University of Science and Technology of China"
conference: fast-2026
category: indexes-and-data-placement
code_url: "https://github.com/adslabcuhk/hats"
tags:
  - scheduling
  - storage
  - databases
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

HATS 是一个构建在 Cassandra 之上的调度框架，它把“读请求放到哪个副本”和“什么时候、给谁做 compaction”视为同一个控制问题，而不是两个彼此独立的启发式策略。它每 `60` 秒重算一次各副本的目标读负载，再用按请求的瞬时延迟只在确有余量时重定向读请求，并把更多 compaction 预算分给最热的 key range，因此在降低尾延迟的同时还能提升吞吐。

## 问题背景

论文先指出了分布式 KV 存储里一个很常见、但经常被忽略的错位：系统通常在“请求数量”上做负载均衡，用户真正感受到的却是“延迟波动”。在一个同构的 `10` 节点 Cassandra 集群里，副本机制已经把各节点访问频率的最大差距压到 `18.9%`，但最慢节点和最快节点的平均读延迟仍然相差 `4.24x`。如果把时间尺度缩小到秒级，问题更明显：最坏节点上有 `90.8%` 的一秒窗口，其平均延迟落在整体平均值 `0.5x-2.0x` 区间之外。也就是说，请求数均衡并不等于读延迟均衡。

更深层的原因来自 LSM-tree 存储层中的 compaction。Compaction 会消耗 CPU 和磁盘带宽，因此会直接与前台读竞争；但如果长期压制 compaction，SSTable 数量和读放大又会持续上升，最终让读性能进一步恶化。论文用实验把这个矛盾说得很清楚：开启 compaction 后短期内读吞吐会显著下降，但等 compaction 做完，平均读吞吐又会回升，因为读取时需要探测的 SSTable 变少了。现有副本选择或负载均衡方案大多只优化前台请求路径，把后台 compaction 当成噪声；HATS 的判断是，这种层间割裂本身就是核心设计问题。

## 核心洞察

HATS 最重要的主张是：复制型 LSM 存储需要一个同时跨越分发层和存储层的闭环控制。大时间尺度上的不均衡，应该靠调整“每个副本预期承担多少读请求”来修正；小时间尺度上的尖峰，则要靠按请求的瞬时延迟来做细粒度协调，但不能简单追逐“当前最快副本”，否则会像 C3 一类方案那样引入震荡。与此同时，compaction 也不能只靠全局限速或 FIFO 排队，而应该按读热度来分配预算，让最热 key range 优先被整理，因为这既能改善当前延迟，也能改善未来的读放大。

换句话说，HATS 优化的不是“这一刻把请求发给谁”这么局部的问题，而是“如何持续提升未来各副本的服务质量”。这也是它把读调度和 compaction 调度绑定在一起的根本原因。

## 设计

HATS 在 Cassandra 5.0 上增加了三个机制。第一层是粗粒度读任务分配，按 epoch 执行。每个节点把各 key range 的读请求数和平均读延迟 piggyback 到 Gossip 消息里；一个经由 Raft 选出的 seed 节点担任 scheduler，汇总得到整个集群的 current state，再在每个 replication group 内把预期读请求从高负载节点贪心地挪到低负载节点，形成 expected state。之后客户端按这个 expected state 的比例随机选择 coordinator，从而在大时间尺度上把负载推向更均衡的目标。

第二层是 epoch 内部的细粒度读协调。Coordinator 持续测量自己到各副本的瞬时读延迟，这个延迟同时包含网络传输时间和目标副本存储层的处理时间。随后它为每个副本计算一个 unified score，本质上是在估计“这个副本相对其目标负载还剩多少额外服务能力”。只有当其他副本确实存在剩余容量时，请求才会被重定向过去。这样一来，HATS 仍然利用瞬时信号做快速适配，但不会因为盲目追逐当前最快副本而破坏长期均衡。

第三层是 compaction 调度。HATS 借用了 DEPART 的 replica decoupling 思想，让每个 replica 落到独立的 LSM-tree 上，这样一个节点上的 compaction 就不再是混在一起的一条队列，而是可以按 replica 分开控制。HATS 再根据各 key range 的读占比，把节点允许的 compaction 吞吐按比例分配给这些 LSM-tree；最低层 compaction 不限速，因为它对控制读放大最关键；同时系统还设定一个最小 compaction 速率，避免冷数据范围永远饿死。论文把 epoch 长度设为 `60 s`，理由是它与 Cassandra 默认的 compaction 周期对齐。

## 实验评估

实验基于 Cassandra 5.0，在一个 `10` 节点集群上进行，采用三副本、`100 M` 条预加载 `1 KiB` 记录以及 `100` 个客户端线程；扩展性部分还测试了一个 `20` 节点异构集群。对比对象是 mLSM、C3 和 DEPART，而且作者把它们都重新实现到同一 Cassandra 版本上，以减少版本差异造成的偏差。工作负载覆盖 YCSB A-F 以及一个基于 Facebook 生产 traces 构造的负载。

总体结果说明 HATS 在混合负载和读主导负载上最强。对于 YCSB，HATS 在 A、B、C、D、F 上都取得最高吞吐，最多达到 DEPART 的 `2.90x`；摘要还给出，在读主导负载下，相比 C3 和 DEPART，HATS 可把 P99 延迟分别降低 `58.6%` 和 `59.9%`，吞吐分别提升 `2.41x` 和 `2.90x`。在 Facebook 风格工作负载上，HATS 的总吞吐达到 `48.8 KOPS`，而 mLSM、C3、DEPART 分别只有 `17.1`、`20.2` 和 `21.5 KOPS`；P99 Get 延迟则分别最多降低 `83.2%`、`78.9%` 和 `68.3%`。

更重要的是，分解实验基本支持了论文的机制解释。在纯读的 Workload C 中，HATS 只有 `0.04%` 的请求被重定向到远端副本，而 C3 高达 `84.9%`，这直接解释了它为何在 replica selection 和磁盘读取阶段都明显更快。HATS 在 Workloads A-C 上还取得了最低的跨节点延迟变异系数。主要的非优势场景是 scan 主导的 Workload E：这里 HATS 与 mLSM 大致持平，略低于 DEPART，因为 DEPART 的 append-only secondary log 避开了一部分 compaction 成本。

## 创新性与影响

相对于 C3，HATS 的创新点在于不再把副本选择只看成前台请求层的问题，而是把后台 compaction 也纳入控制回路。相对于 DEPART，贡献不在于 replica decoupling 本身，而在于把这种按副本拆分的存储结构变成一个新的控制执行器，用来做按 key range 的 compaction 预算分配。因而，这篇论文不只是一次 Cassandra 参数调优，而是把“compaction 会伤害尾延迟”这个经验事实，落成了一个可部署、可复现的跨层控制设计。

## 局限性

HATS 依赖若干部署前提。首先，它需要 replica decoupling；论文认为这在 Cassandra 中开销很小，但它确实会改变存储布局和 compaction 行为。其次，当读一致性级别升高时，可供选择的副本数减少，HATS 相对 DEPART 的优势也会缩小，因为调度自由度变少了。更广义地说，它主要针对读延迟控制，而不是完整的多租户隔离或复杂故障场景下的策略切换。

论文确实评测了异构集群，并说明系统在不同 key 分布、value size 和饱和度下都比较稳定，但控制环仍然围绕“每个 Raft term 只有一个 scheduler leader”和固定 `60 s` epoch 展开。这个设置对 Cassandra 默认参数很合适，但未必天然适用于所有分布式 LSM 存储。

## 相关工作

- _Suresh et al. (NSDI '15)_ — C3 用自适应副本选择来重定向读请求，但它把 compaction 当成背景噪声，而不是可调度的控制量。
- _Zhang et al. (FAST '22)_ — DEPART 通过把副本拆到独立存储结构中来降低副本管理开销；HATS 则把这种结构进一步用于热点 key range 的 compaction 优先级控制。
- _Wydrowski et al. (NSDI '24)_ — Prequal 指出“平衡 load 并不等于平衡 latency”，HATS 则把这一结论具体落实到复制型 LSM 存储里。
- _Balmau et al. (ATC '19)_ — SILK 解决的是单机 LSM 引擎内部的延迟尖峰，而 HATS 同时处理跨节点读放置和节点内部 compaction 干扰。

## 我的笔记

<!-- empty; left for the human reader -->

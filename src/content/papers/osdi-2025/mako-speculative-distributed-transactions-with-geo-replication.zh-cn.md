---
title: "Mako: Speculative Distributed Transactions with Geo-Replication"
oneline: "Mako 在 WAN 复制完成前先投机认证跨 shard 事务，再用 vector clock 与 vector watermark 把 shard 故障后的回滚限制在受影响事务上。"
authors:
  - "Weihai Shen"
  - "Yang Cui"
  - "Siddhartha Sen"
  - "Sebastian Angel"
  - "Shuai Mu"
affiliations:
  - "Stony Brook University"
  - "Google"
  - "Microsoft Research"
  - "University of Pennsylvania"
conference: osdi-2025
code_url: "https://github.com/stonysystems/mako"
tags:
  - databases
  - transactions
  - fault-tolerance
category: databases-and-vector-search
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Mako 让跨 shard 事务先完成执行和 2PC 认证，再在后台完成 WAN 复制。它用 vector clock 保留投机依赖、用 vector watermark 判断何时能安全 replay、回复客户端或回滚，从而把 geo-replication 移出热路径。

## 问题背景

面向 geo-replication 的 OLTP 系统同时想要 serializability、跨机房容灾和 sharding，但现有设计通常都让分布式提交等待 WAN 复制。Spanner 一类系统会把 2PC 的关键步骤逐步复制；Janus、Tapir、Ocean Vista 则把复制与协调更紧地揉在一起。无论采用哪种做法，广域网延迟都直接落在 commit path 上，所以单机房里更快的 NIC 或 kernel bypass 帮助有限。

投机执行听起来很自然，但真正困难的是带故障的跨 shard 投机。一旦后续事务读到了尚未完成复制的写入，一个丢失参与者就可能让整条依赖链作废。已有投机系统只覆盖更简单的场景：Rolis 只支持单 shard，Aurora 不支持跨 shard 事务。

## 核心洞察

Mako 的核心主张是，WAN 复制和事务协调应该解耦，而不是继续融合。leader 可以先在本地完成执行和认证、把写入投机安装出去，然后在后台复制，同时前台继续处理后续事务。

为了让这件事安全，Mako 不追求精确的逐边依赖日志，而是只维护粗粒度依赖信息。每个事务获得一个 vector clock，它在逐分量意义上不小于自己读过的数据版本；系统再维护一个分布式 vector watermark，表示各 shard 已经持久复制到哪里。正常情况下，只有当 watermark 覆盖该版本时事务才能 replay 或向客户端返回；故障恢复时则计算一个 finalized watermark cut，只回滚落在 cut 之上的事务。

## 设计

每个 shard leader 都是基于 Silo 构建的多核内存型存储引擎。客户端把 one-shot transaction 发给某个 leader，由它担任 coordinator。读取采用乐观执行，并把版本元数据记录进 `ReadSet`；写入先缓存在 `WriteSet` 中。随后，参与的 leaders 之间通过四轮 RPC 完成认证：`Lock`、`GetClock`、`Validate` 和 `Install`。

`GetClock` 是整篇论文最关键的机制。每个被访问的 shard 递增自己的逻辑时钟并返回结果；coordinator 再把这些值与 `ReadSet` 中已有的 clocks 做逐分量最大值合并，得到事务的提交版本。因为读者会继承自己读到的最大版本，所以传递依赖能以粗粒度方式被保留下来：如果 `T1` 读取了 `T0` 的结果，那么 `vc(T1) >= vc(T0)`。认证成功后，写入会以新版本的形式被投机安装，因此后续事务可能在复制完成前就读到这些值。

复制与认证完全独立。每个 worker thread 都把已认证事务追加进自己的 batched MultiPaxos stream，以避免单一 stream 成为瓶颈。follower 只有在事务的 vector clock 低于当前 vector watermark 时才会 replay；其中每个 shard 都独立贡献自己本地各 stream 已复制时钟的最小值，所有 shards 再通过 gossip 交换这些 shard watermark。客户端回复同样要等到这个条件满足。

故障恢复由一个复制过的 configuration manager 通过 epoch 机制驱动。当某个 leader 故障时，系统先关闭旧 epoch、选出新 leader，并收集各 shard 的 finalized shard watermark。健康 shard 如果把旧 epoch 干净地刷完，就可以写入一个 `INF` 标记；恢复中的 shard 则以仍然存活的最小 stream 位置作为终点。它们合起来形成 finalized vector watermark（FVW），所有不低于这个 cut 的旧 epoch 事务都会被整体回滚。它并没有消除 cascading abort，但在不记录细粒度依赖的前提下，把回滚范围限制住了。

## 实验评估

该原型在 Silo、eRPC 和 Janus 之上新增了大约 10K 行 C++ 代码，并运行在 Azure VM 上，每台机器有 32 个 vCPU，广域网通过注入 50 ms RTT 来模拟。在 10 shards、每 shard 24 个 worker threads 的 TPC-C 上，Mako 达到 3.66M TPS；论文称这比最佳对比 geo-replicated 系统高 8.6x。在 microbenchmark 上，它在 10 shards 时扩展到 16.7M TPS，并比 OCC+OR 高 32.2x。这个结果基本支撑了论文的核心论点：真正决定性能的，是把 WAN 复制从执行路径上挪开，而不是再省几个本地 RTT。

论文也明确展示了收益的边界。没有跨 shard 事务时，microbenchmark 能到 60.3M TPS；当所有事务都变成跨 shard 时，吞吐会掉到 1.1M TPS。10-shard TPC-C 的中位延迟是 121 ms，主要由 WAN RTT 和等待 watermark 推进组成。故障实验也很有说服力：健康 shard 会先排队受影响事务，等 FVW 算出后再恢复，而 epoch-commit 变体会把健康 shard 一起卡住。需要保留的实验公平性问题是，一些基线在更大规模下无法持续执行跨 shard workload，因此作者关闭了这些系统的跨 shard 事务。

## 创新性与影响

相对于 _Corbett et al. (OSDI '12)_，Mako 不再把同步复制放在 2PC 的关键路径上，而是先投机执行，再通过 epoch rollback 修复。相对于 _Fan and Golab (PVLDB '19)_ 和 _Mu et al. (OSDI '16)_，它主张在 WAN 场景下应进一步放松复制与协调之间的耦合，而不是把两者做得更紧。相对于 _Shen et al. (EuroSys '22)_，它把 speculative replication 从单 shard 引擎推进到了 sharded、geo-replicated 数据库。

这篇论文最重要的影响是概念上的：它说明，只要把恢复问题表述成跨 epoch 的有界回滚，而不是精确到单事务的恢复，speculative distributed transactions 就可以在强一致 geo-replicated 系统里真正落地。

## 局限性

Mako 只是把 cascading abort 限界住，并没有消除它。由于依赖信号是粗粒度的，一些高于 FVW 的事务即使只是“可能”依赖了丢失工作，也会被保守地回滚。原型还假设 one-shot transactions、静态 sharding，以及一个被视为始终可用的 replicated configuration manager。

它的性能也依赖数据局部性。最佳情形默认相关 leaders 共置；如果 leader 分散到多个 datacenter，或者几乎所有事务都变成跨 shard，吞吐会明显下滑。论文还指出，在没有 geo-replication 的单机房场景里，Mako 比紧耦合的 RDMA 系统慢约 50%；而当 shard 数非常大时，full-sized vector clock 也终究需要压缩。

## 相关工作

- _Corbett et al. (OSDI '12)_ - Spanner 同步复制 2PC 决策，而 Mako 先投机执行，再用 epoch rollback 收敛状态。
- _Fan and Golab (PVLDB '19)_ - Ocean Vista 通过耦合 visibility control 与 replication 降低 geo-latency，Mako 则选择解耦路径。
- _Mu et al. (OSDI '16)_ - Janus 把 concurrency control 与 consensus 合并做提交，Mako 则把两者拆开。
- _Shen et al. (EuroSys '22)_ - Rolis 为单 shard 多核事务做 speculative replication；Mako 进一步加入 sharding 与跨 shard 恢复。

## 我的笔记

<!-- 留空；由人工补充 -->

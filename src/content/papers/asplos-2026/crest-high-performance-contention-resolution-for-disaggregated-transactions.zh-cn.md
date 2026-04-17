---
title: "CREST: High-Performance Contention Resolution for Disaggregated Transactions"
oneline: "CREST 用 cell 级并发控制、本地化执行和依赖感知并行提交，减少 RDMA 解耦事务里的误 abort 与长时间阻塞。"
authors:
  - "Qihan Kang"
  - "Mi Zhang"
  - "Patrick P. C. Lee"
  - "Yongkang Hu"
affiliations:
  - "State Key Lab of Processors, Institute of Computing Technology, Chinese Academy of Sciences, University of Chinese Academy of Sciences, Beijing, China"
  - "State Key Lab of Processors, Institute of Computing Technology, Chinese Academy of Sciences, Beijing, China"
  - "Department of Computer Science and Engineering, The Chinese University of Hong Kong, Hong Kong, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790148"
code_url: "https://github.com/adslabcuhk/crest"
tags:
  - transactions
  - disaggregation
  - rdma
  - databases
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CREST 要解决的是解耦式 OLTP 在热点记录下最容易失控的失败模式：record 级锁把很多本来只是在同一行不同列上重叠的事务也算成冲突，而严格等远端提交完成才可见，又让真正的冲突被多个 RDMA 往返持续放大。它的回答是 cell 级并发控制、本地化执行和依赖感知并行提交。在高冲突负载下，这足以让它相对 Motor 获得最高 `1.92x` 的吞吐提升。

## 问题背景

像 FORD、Motor 这样的系统已经说明，compute pool 和 memory pool 通过 RDMA 连接后，事务处理在常规负载下可以跑得很好；但高冲突工作负载并不会因为资源解耦就消失，反而常常被进一步放大。

作者把问题归纳为两个根因。第一，现有系统基本都做 record 级并发控制，所以两个事务即使访问的是同一条记录里不同的列，也会被判成冲突。在 TPC-C 里这不是边角现象：当 warehouse 数降到 20 时，FORD 和 Motor 的 abort rate 分别达到 `75.9%` 与 `85.2%`，其中约 `40-44%` 其实是假冲突，而不是对同一个字段的真实竞争。第二，真正的冲突也被严格提交流程拖长了。协调器必须一直持有锁，直到验证、写日志、远端更新记录并释放锁全部完成；在解耦架构里，这意味着每次冲突都要额外吃下多次 RDMA round-trip 的阻塞时间。

于是，系统真正要解决的是怎样在保持 serializability 的前提下，同时减少不必要的 abort，以及真实冲突造成的长时间等待。

## 核心洞察

这篇论文最值得记住的一点是：高冲突解耦事务要提速，关键在于把“必须串行化的部分”和“只是碰巧共用一个 record 外壳的部分”区分开来。现代 OLTP schema 里，很多事务只会访问一行中的部分字段，因此冲突跟踪应该落在 cell 粒度。

但更细的粒度只有在“可见性”也跟着改变时才真正有意义。CREST 因此不只做 cell 级冲突检测，还允许同一 compute node 内的事务提早消费本地未提交版本，并把事务逻辑拆成 execution block 做流水线执行。提交阶段也不必把所有事务全局串成一条线；只要追踪依赖关系，并确保只有最后一个合法 writer 把最终版本写回 memory pool，就可以并行推进。

## 设计

CREST 由三个紧密耦合的机制组成。第一是 cell-level concurrency control。系统把 record 划成多个 cell，每个 cell 都带自己的 epoch number 和 commit timestamp，而 record header 聚合了 lock bit 和 epoch-number array。这个布局的作用是把 RDMA 开销压住：协调器可以用一次 masked `CAS` 锁住多个 cell，用一次 `READ` 验证多个 cell，并判断自己读到的是否是跨多个 cell 的一致视图。为了避免 2-byte epoch number 回绕带来的错误验证，CREST 还设置了时间阈值，超出阈值时退回到整条记录验证。

第二个机制是 localized execution。每个 compute node 都维护一个 record cache，本地对象里保存已抓取记录、引用计数、epoch array 和未提交 version list。缺失记录只允许一个协调器负责 cache admission，以避免重复 I/O。若一个事务读取了另一个本地事务的 tentative version，就把这个依赖显式记下来。为了缩短锁持有时间，CREST 进一步采用 pipelined execution，在 block 内用 `2PL`，跨 block 用 execution timestamp 检测 reverse ordering。

第三个机制是 parallel commits。验证阶段先检查 read set 里各 record 的 epoch 是否仍和远端一致，再检查依赖事务是否 abort。通过验证后，事务获得 commit timestamp，把包含更新内容和依赖列表的 redo log 追加到 memory pool 中按 coordinator 划分的 log segment，然后参与一个 last-writer-wins 协议。哪个协调器把 `writers` 计数减到零，哪个就是该记录的最后 writer，由它把最终版本写回 memory pool。论文还说明，系统可以借助 redo log 做 crash recovery。

## 实验评估

这组实验和论文主张是对得上的。作者实现了约 `14 K` 行 C++ 原型，在一个五机 `100 Gbps` RDMA 集群上，与开源的 FORD 和 Motor 直接对比，工作负载则选用会主动制造热点的 TPC-C、SmallBank 和事务型 YCSB。

核心结果是 CREST 在高偏斜下持续领先。在 240 个 coordinators 时，它相对 Motor 在 TPC-C、SmallBank、YCSB 上分别获得 `1.92x`、`1.46x`、`1.85x` 的吞吐提升；相对 FORD 的提升更大。只看 TPC-C，CREST 达到 `743.7 KOPS`，比 Motor 的峰值高 `72.4%`。平均延迟方面，CREST 相对 Motor 下降 `17.7-44.4%`，相对 FORD 下降 `41.1-62.6%`，这说明 localized execution 确实在减少阻塞，而不只是把工作转移到别处。

我觉得最有说服力的是 factor analysis。在高 skew 下，仅仅加上 cell-level concurrency control，就能让 TPC-C 和 YCSB 的吞吐分别提升 `65.9%` 与 `46.6%`，说明假冲突确实是主要瓶颈之一；再加上 localized execution 与 parallel commits，吞吐还会继续提升 `48.9-104.6%`，对应论文关于“长阻塞时间”这个第二瓶颈的论证。论文也没有回避边界条件：在低 skew 的 YCSB 或更偏读的场景下，CREST 有时只是和 Motor 持平，甚至会略慢，因为 cache 管理开销还在，但冲突本身已经很少。

## 创新性与影响

和 _Zhang et al. (TOS '23)_ 相比，CREST 的关键贡献不是再做一条更快的 RDMA 事务路径，而是在控制 RDMA 元数据成本的同时，把冲突检测从 record 下沉到 cell。和 _Zhang et al. (OSDI '24)_ 相比，它不是靠 MVCC 让读绕过写，而是直接针对多列记录上的假冲突以及高冲突更新负载中的长锁持有时间。和 _Li et al. (VLDB '24)_ 相比，它选择的是细粒度 cell locking 加本地早可见，而不是 page ownership。

因此，CREST 最可能影响的是做 RDMA 解耦数据库、解耦事务执行和热点 OLTP 研究的人。

## 局限性

CREST 的部署前提并不弱。它依赖 stored procedure，这样系统才能预先知道事务会访问哪些列、哪些记录会被更新。record header 能聚合的 cell 数量也是有上限的；当表宽超过 20 个 cell 时，CREST 会把超出的列合并成更大的 cell，于是部分假冲突又会回来。跨 execution block 的 reverse-order 冲突也只是“检测后 abort”，而不是在线修复。跨 compute node 的冲突依旧昂贵，这也是为什么在高 skew 的 YCSB 里，它的 tail latency 只是接近基线而不是彻底甩开。epoch number 回绕防护依赖一个保守的时间假设，本地化执行也会引入 cache 管理开销，因此在低冲突或读多写少场景下并不总是占优。

## 相关工作

- _Zhang et al. (TOS '23)_ — FORD 通过批量锁定和读取来优化解耦内存事务，但仍保留 record 级冲突与严格提交可见性，正是 CREST 重点攻击的瓶颈。
- _Zhang et al. (OSDI '24)_ — Motor 用 MVCC 减轻读写冲突；CREST 则把重点放在多列 record 内的假冲突，以及缩短本地真实冲突的阻塞时间。
- _Li et al. (VLDB '24)_ — GaussDB 依赖 page-level ownership 来执行解耦数据库事务，而 CREST 保持共享内存视角，并在 cell 粒度提取并发性。

## 我的笔记

<!-- 留空；由人工补充 -->

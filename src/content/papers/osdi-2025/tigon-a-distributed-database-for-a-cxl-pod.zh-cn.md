---
title: "Tigon: A Distributed Database for a CXL Pod"
oneline: "Tigon 只把跨主机活跃 tuple 放进共享 CXL 内存，用数据库感知的软件一致性维护它们，并让单个主机在不使用 2PC 的情况下提交多分区事务。"
authors:
  - "Yibo Huang"
  - "Haowei Chen"
  - "Newton Ni"
  - "Yan Sun"
  - "Vijay Chidambaram"
  - "Dixin Tang"
  - "Emmett Witchel"
affiliations:
  - "The University of Texas at Austin"
  - "University of Illinois Urbana-Champaign"
conference: osdi-2025
code_url: "https://github.com/ut-datasys/tigon"
tags:
  - databases
  - transactions
  - disaggregation
  - memory
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Tigon 是首个面向小规模 CXL pod 的分布式内存数据库，其中多个主机共享一块 CXL 内存。它的关键做法是只把跨主机活跃 tuple 放进 CXL，把同步密集的元数据放进有限的硬件 cache-coherent 区域，并用数据库感知的软件一致性维护其余数据。这样，单个主机就能在不使用 2PC 的情况下执行并记录多分区事务，相比优化过的 shared-nothing 基线最高提升 2.5x 吞吐，相比基于 RDMA 的解耦内存数据库最高提升 18.5x。

## 问题背景

论文针对的是分布式 OLTP 里的经典瓶颈：一旦事务跨越多个分区，系统就要为远程消息、分布式锁，以及通常不可避免的 two-phase commit 付费。因此，像 Sundial 或 DS2PL 这样的 shared-nothing 系统会随着多分区事务比例上升而快速掉吞吐。基于 RDMA 的方案虽然减少了一部分消息开销，但 tuple 访问和同步仍然建立在微秒级网络往返之上，代价依旧很高。

CXL pod 提供了一个新机会，因为多个主机可以直接对共享内存做 load、store 和 atomic update。但论文并没有把 CXL 当成“便宜的远程 DRAM”。实验表明，CXL 的访问延迟比本地 DRAM 高约 1.6x 到 3.5x，带宽低得多，而且跨主机保持 hardware cache coherence 的区域只能占整个物理地址空间的一小部分。若把整库直接塞进 CXL，系统很快就会耗尽带宽和稀缺的一致性元数据。因此，Tigon 试图回答一个更窄也更关键的问题：到底哪些数据必须以内存速度共享，以及怎样只为这部分数据付出跨主机同步成本。

## 核心洞察

Tigon 的核心判断是，事务数据库并不需要把全部数据库状态都共享给所有主机；真正需要共享的只是那些正在被不同主机上活跃事务同时访问的 tuple。论文把这部分集合称为 Cross-host Active Tuples，简称 CAT。由于单个事务通常只访问少量 tuple，CAT 往往远小于全库。论文以 TPC-C 为例说明：即便有 1,000 个并发事务，活跃 tuple 也只有大约 39K 个，总数据量约 7 MB。

一旦系统把 CAT 作为共享单位，后面的设计就自然展开了。锁、latch、CXL index 这类同步密集元数据放进有限的 hardware cache-coherent 区域；tuple 本体和不那么同步密集的元数据则放进更大的非一致性 CXL 区域，并由软件维护一致性，而且这种一致性直接绑定在数据库自己的锁和 latch 上。这样，Tigon 就能把大量网络消息替换成原子内存操作，同时继续把绝大多数数据留在低延迟、高带宽的本地 DRAM 中。

## 设计

Tigon 仍然从分区式架构出发：每个主机在本地 DRAM 里拥有一个互不重叠的分区，owner-local 访问完全本地化。只有当别的主机需要某个 tuple 时，owner 才把该 tuple 移入共享 CXL 内存。进入 CXL 后，一个 tuple 会被拆成两部分：一个 8 字节的 hardware-coherent record，以及一个 software-coherent row。HWcc record 里放的是 latch、2PL 锁位、用于范围锁的 `has-next-key` 标志、dirty bit、CLOCK 置换位、每主机的软件一致性位图，以及指向 SWcc row 的指针；SWcc row 则保存 tuple payload、有效位和 epoch-version 元数据。

系统依赖两条索引路径来保持高效。每个主机都在 DRAM 中维护自己的 local index。与此同时，Tigon 在 HWcc 区域维护一个 CXL index，用来索引当前驻留在 CXL 中的 tuple。owner 主机还会在本地行上保留一个 shortcut pointer，直接指向 tuple 的 HWcc record，这样 owner 再访问自己已搬入 CXL 的 tuple 时就不必重新查 CXL index。这个 shortcut 很重要，因为远程共享开始之后，owner 仍然会频繁地读写自己的 tuple。

软件 cache coherence 协议是和数据库 latch 一起设计的。一个主机读取 SWcc row 时，先检查自己在 `SWcc-bitmap` 里的那一位；若该位已置位，就可以直接用 cacheable load，否则先 flush 相关 cacheline，再从 CXL 中抓取数据，并把自己的位设为 1。写入者则会清空其他主机的位。这当然不是通用一致性协议，但论文的关键点在于：数据库本来就会通过 latch 串行化 tuple 访问，所以一致性元数据可以直接挂靠在已有的临界区上，而不必另起一套昂贵机制。

在此基础上，Tigon 重新组织事务执行。它采用 strong strict 2PL 和 `NO_WAIT` 的死锁避免策略，并扩展 next-key locking，使范围查询在 CXL index 只缓存了分区子集时仍然满足可串行化。`has-next-key` 位告诉 worker，当前 CXL index 中的后继键是否也是真正 local index 里的后继键；如果不是，就要请求 owner 把更多 tuple 移入 CXL。

最关键的系统结果是 Tigon 可以避开 2PC。只要相关远程 tuple 都已经进入 CXL，一个 transaction worker 就能自己完成全部 tuple 更新；而索引修改可在恢复时重建，所以本地只需记录 tuple 变化即可。Tigon 进一步把 SiloR 的 epoch-based group commit 改造成自己的日志协议：worker 生成 value log，logger thread 刷到本地 SSD，恢复时再并行重放已提交 epoch。为避免稀缺的 HWcc 空间被长期占满，owner 会按需用 CLOCK 而不是 LRU 把 tuple 移回本地 DRAM；同时，若 tuple 自搬入 CXL 后未被改写，owner 还能借助 `is-dirty` 位继续从本地 DRAM 读取它。

## 实验评估

实验运行在一个模拟的 8-host CXL pod 上：8 个 VM 共享一台物理机上的 128 GB CXL 1.1 设备，并把 hardware-coherent 区域限制为 200 MB。基线并不弱。作者给 Sundial 和 DS2PL 都补上了 next-key locking 和同样的日志协议，又把网络传输替换成 CXL 内存队列，并把 I/O 线程改成 worker，形成 Sundial+ 和 DS2PL+；Motor 则代表基于 RDMA 的共享解耦内存设计。

结果支持论文的核心论点：CXL 共享内存的价值不只是“更快的传输层”，而是可以把共享 tuple 直接放在内存里同步。TPC-C 上，在完全没有多分区事务时，Tigon 确实更慢，分别落后 Sundial+ 37% 和 DS2PL+ 8.5%，这说明当共享并非必要时，它会付出额外管理成本。但随着工作负载变成 60% remote `NewOrder`、90% remote `Payment`，Tigon 立刻反超，分别比 Sundial+ 快 75%、比 DS2PL+ 快 2.5x、比 Motor 快 15.9x 到 18.5x。YCSB 上，在 100% 多分区事务条件下，Tigon 在读密集配置里比 Sundial+ 快 2.0x 到 2.3x，并且在测试工作负载中整体比 Motor 快 5.4x 到 14.3x。

扩展性实验呈现出同样趋势：从 1 台扩到 8 台时，Tigon 在 TPC-C 上取得 5.7x 吞吐增长，在 YCSB 上取得 3.5x；而 Sundial+/DS2PL+ 只有 2.4x/2.1x 和 1.4x/1.5x。HWcc 容量实验也很关键。即便只有 50 MB 的 HWcc 内存，Tigon 也只比 200 MB 配置慢 5.8%，说明论文关于 CAT 足够小、适合放进有限一致性区域的判断基本成立。最大的实验保留意见在于，这个 pod 是单机模拟的，因此真实跨主机 hardware coherence 会更慢。作者估算，即便 back-invalidation 的代价是本地 invalidation 的 4 倍，Tigon 在其 TPC-C 设定下仍会比 DS2PL+ 快 45%，比 Motor 快 9.6x。

## 创新性与影响

相对于 _Huang et al. (CIDR '25)_ 提出的 Pasha 架构，Tigon 是第一篇真正把 CXL pod 硬件模型落成完整事务数据库并做系统评测的工作。相对于 _Yu et al. (VLDB '18)_ 这类 shared-nothing 系统，它不是继续围绕网络协调做优化，而是直接改变执行模型，让大量多分区事务退化成共享内存上的“单主机执行”。相对于 _Zhang et al. (OSDI '24)_，它进一步表明：在小规模 pod 内部，CXL 共享内存可以通过去掉热路径上的微秒级远程同步，明显优于基于 RDMA 的解耦内存方案。

更广泛的影响在于，它提出了一种面向新型共享内存互连的数据库分解方式。Tigon 并没有声称 CXL pod 就等于一个更大的 SMP，而是展示了另一种思路：只共享正在跨主机活跃的子集，把稀缺的一致性区域留给元数据，并让数据库自己掌管一致性策略。这样，有限的跨主机 CXL 内存就足以消掉一大类分布式 OLTP 的 2PC 成本。

## 局限性

Tigon 的故障模型比较窄。系统假设 fail-stop，把日志写到本地 SSD，并把任意组件故障都视为整个系统失败然后统一恢复。这避开了真实 CXL pod 必须面对的 partial failure 和独立主机失效问题。论文也依赖“至少有一部分” hardware cache-coherent 的 CXL 内存，并明确把完全非一致性 CXL 设备上的设计留作未来工作。

它的适用范围和协议覆盖也有限。Tigon 目标是大约 8 到 16 台主机的小 pod，而不是数据中心规模的分布式集群。系统实现了 SS2PL 和 next-key locking，但没有支持 OCC 或 MVCC，因此在读密集场景里未必是最优选择。实验在吞吐和公平性方面做得不错，但本质上仍是模拟环境，其一致性开销很可能比未来真实硬件更乐观。最后，Tigon 的优势也建立在 CAT 规模适中的前提上；如果并发共享集合过大，HWcc 容量、atomic contention 或 coherence traffic 都可能成为新的瓶颈。

## 相关工作

- _Huang et al. (CIDR '25)_ — Pasha 提出 CXL pod 上数据库的总体架构，而 Tigon 把这条路线真正实现为带 coherence、locking 和 recovery 的事务系统。
- _Yu et al. (VLDB '18)_ — Sundial 在 shared-nothing 架构内优化分布式 OLTP；Tigon 则通过只共享跨主机活跃 tuple，尽量绕开这一路线中的网络协调成本。
- _Zhang et al. (OSDI '24)_ — Motor 同样试图摆脱传统 partition-local 执行，但它建立在 RDMA 解耦内存和复制之上；Tigon 则利用 pod 内的 CXL 内存让同步本身变得更便宜。
- _Zhang et al. (SOSP '23)_ — CXL-SHM 研究的是 CXL 上的分布式共享内存管理和 partial failure，而 Tigon 是数据库特化设计，把软件一致性和 tuple 锁、索引协同起来。

## 我的笔记

<!-- 留空；由人工补充 -->

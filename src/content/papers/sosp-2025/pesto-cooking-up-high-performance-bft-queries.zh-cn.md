---
title: "Pesto: Cooking up High Performance BFT Queries"
oneline: "Pesto 只在查询相关行上按需同步快照，并用谓词感知冲突检查替代全局排序，让 leaderless BFT 副本也能执行高性能 SQL 事务。"
authors:
  - "Florian Suri-Payer"
  - "Neil Giridharan"
  - "Liam Arzola"
  - "Shir Cohen"
  - "Lorenzo Alvisi"
  - "Natacha Crooks"
affiliations:
  - "Cornell University"
  - "UC Berkeley"
  - "Cornell University / UC San Diego"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764799"
code_url: "https://github.com/fsuri/Pequin-Artifact"
tags:
  - databases
  - transactions
  - consensus
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pesto 把 Basil 的无全局排序 BFT 设计从 key-value store 扩展到了完整 SQL 数据库。它的做法是只让副本在查询真正相关的行上达成一致，再用谓词感知的冲突检查替代“所有请求都先全局排序”的传统路线。

## 问题背景

这篇论文要解决的是 BFT 数据库里一个长期存在的结构性矛盾。若把关系数据库直接叠在 PBFT、HotStuff 或 BFT-SMaRt 这类共识协议之上，那么每次读、写、提交都必须先付出 total order 的代价。这样做当然容易保证正确性，但代价也很直接：并行性被抹掉，交互式事务被拉长成多轮往返，分片之后还要在每个已复制分片之上再跑两阶段提交，整体延迟和协调成本都很难接受。

另一条路线是 Basil 代表的集成式、客户端驱动、无序 BFT 执行。Basil 已经证明，不必先把所有请求排成一个全序，也能把复制、乐观并发控制和提交协调整合在一起。但 Basil 只提供 key-value 接口。它要求客户端逐键读取并在本地完成计算，这意味着 join、scan、aggregation 这类 SQL 工作负载不是很难写，就是非常低效。论文给出的 join 例子很典型：如果客户端必须靠 point read 去重建两张百万行表上的连接，中间结果和通信量会立刻压垮设计。

一旦想支持任意 SQL 查询，问题就变成两个。第一，查询改成服务端执行之后，客户端仍然需要确认返回结果是有效的、足够新的，而且计算本身没有被错误副本伪造；而 Pesto 为了性能又故意允许副本短时间不一致。第二，传统 optimistic concurrency control 对 range query 很不友好，因为它在逻辑上往往要保护大块键空间，幻读冲突会让 abort 率迅速上升。在 Byzantine 环境里，基于锁的方案更糟，因为恶意客户端完全可以拒绝释放锁。Pesto 的目标就是在不放弃 Basil 那种低延迟、leaderless、无全局排序执行模型的前提下，把可串行化的 SQL 查询也带进来。

## 核心洞察

Pesto 最关键的观察是：一个查询并不要求整个数据库在所有副本上完全一致，它只要求“足以影响这个查询结果”的那部分行在副本之间对齐。如果副本本来就在这些相关行上达成一致，客户端就可以立刻完成查询；如果没有，则只需要把这些相关事务状态按需同步出来，再在共同快照上重执行查询即可。

同样的“只关心真正有影响的部分”也体现在并发控制上。Pesto 不把“同一张被扫描表上的任意并发写入”都视为冲突，而是进一步问：这次写入会不会改变查询谓词所定义的 active read set？如果不会，那么强行 abort 这笔事务就是没有必要的。正是这种语义收缩，让 Pesto 能把 Basil 扩展到 SQL，而不必退回到“先全局排序、再执行”的传统 BFT 路线。

## 设计

Pesto 继承了 Basil 的基本姿态：事务执行由客户端编排，副本采用 inconsistent replication，系统没有 leader，也不要求 total order。每个事务在 `BEGIN` 时拿到一个客户端生成的时间戳，这个时间戳同时固定了它在串行化顺序中的位置。写操作会先缓存在本地直到提交；但 SQL 的 `UPDATE` 和 `DELETE` 往往依赖谓词，所以 Pesto 先发一个 reconnaissance query 找出候选行，再由客户端据此计算真正要写入的新版本并放入 write set。

point read 是最简单的情况。若查询显式命中单个主键，客户端就向 quorum 发请求，收集 committed 或 prepared 版本，然后选出最新且有效的那个。Pesto 允许读取 prepared 版本，但此时读者必须把写者记成 dependency，后续提交只有在那个写者最终提交时才能通过。

真正有新意的是 range read 协议。客户端把 SQL 查询发给至少 `3f+1` 个副本。每个副本在不晚于读事务时间戳的本地状态上执行查询，并返回四样东西：查询结果、active read set、对 prepared writer 的依赖，以及一个 snapshot vote，里面记录本次查询所用版本对应的事务 id。如果客户端能看到 `f+1` 份完全匹配的结果和读元数据，这次读就直接结束。否则它进入 snapshot path：从一个 `2f+1` 回复集合里，只保留那些在 `f+1` 份 vote 中都出现过的事务 id，把这些事务合成一个 snapshot proposal 再发回副本；副本若缺少其中某些事务，就向同伴同步缺失内容，然后在共同快照上重新执行查询。这里的关键不是同步整个副本状态，而是只同步与相关行对应的事务集合。

提交阶段则是在 Basil 的客户端驱动投票之上加入新的 `SemanticCC`。副本不仅记录查询读了哪些行，还记录决定 active rows 的谓词集合。验证时，它只检查那些可能改变这些谓词结果的写入是否会让读集合变得不新鲜或不完整。为了让检查成本可控，Pesto 还维护 table-version 摘要，并配合带 grace window 的 write monotonicity，让验证只需查看一个有界的并发写入区间，而不用重扫整张表的历史。副本会先把 prepared write 暂时暴露出去，客户端再像 Basil 一样把各分片投票汇总成两阶段决策。常见情况下，一轮往返就能拿到 durable decision；否则再把决策记录到某个分片，然后异步 writeback。

还有一个对威胁模型很重要的设计点：Pesto 用的是 `5f+1` 个副本，而不是经典 leader-based BFT 常见的 `3f+1`。原因不是论文想要更保守，而是 Byzantine independence 需要保证“恶意客户端加上少数恶意副本”不能单方面决定事务结果。这个额外复制开销是设计里明确接受的代价。

## 实验评估

作者用 C/C++ 在 Basil 和 Peloton 之上实现了一个原型，在 CloudLab 上以内存模式运行，并设置 `f = 1`。实验设计比较扎实，因为它没有只挑一个对自己友好的 workload。TPC-C 主要压测高争用事务和大量 point read；AuctionMark 与 SEATS 更偏向 join 和 range-heavy SQL；基于 YCSB 的微基准则专门去压 snapshot path、副本不一致和故障场景。

在 TPC-C 上，Pesto 达到 `1784 tx/s`，几乎和未复制的 Peloton (`1777 tx/s`) 与 Postgres (`1781 tx/s`) 一样高；同时相对两个 SMR 基线，吞吐最高提升 `2.3x`，延迟下降 `2.7x` 到 `3.9x`。这个结果之所以有说服力，是因为 Peloton-SMR 基线其实已经被“放宽”过：论文没有强制真正的确定性复制执行，而是允许副本并行跑事务，只让一个 primary 回客户端，所以比较并不是靠故意压低基线得来的。Pesto 能接近未复制系统，核心原因是它保住了 Basil 的时延轮廓：写入先缓冲，TPC-C 中 `99.9%` 的 range read 能在一轮往返内完成，`97%` 的提交能走 fast path。

AuctionMark 和 SEATS 呈现出相同趋势，只是吞吐优势没有 TPC-C 那么大，因为 range read 需要更大的 quorum，系统更容易先碰到 CPU 瓶颈。即便如此，Pesto 的吞吐仍分别处于未复制 Peloton 的 `1.36x` 和 `1.22x` 之内，而相对 SMR 基线，延迟大约还能降低 `3x` 到 `5x`。和只有 key-value 接口的 Basil 相比，Pesto 在三分片 TPC-C 上也能把峰值吞吐维持在 Basil 已报告结果的 `1.23x` 之内，尽管它还要承担 SQL 解析、规划和执行的额外成本。更重要的是，Pesto 提供了 Basil 本身缺失的能力：range-read 协议让 10,000 行扫描的延迟下降 `16.6x`，若只有 1/100 的扫描行真正命中谓词，降幅可达 `110x`。

压力测试也没有回避不一致带来的真实代价。若强制每个查询都走 snapshot path，在均匀 workload 上延迟会上升 `1.38x`，吞吐约下降 `9%`；若人为让三分之一副本延迟或缺失写入，整体吞吐也只下降约 `5%`。但在高度争用的 Zipfian workload 上，重执行和更长的冲突窗口会明显放大 abort，吞吐会下降 `32%` 到 `48%`。副本崩溃的影响反而比较温和：由于协议是 leaderless、client-driven 的，失败主要伤害 fast path，而不会像 leader-based SMR 那样先导致整段停顿。

## 创新性与影响

离 Pesto 最近的前作显然是 _Basil_，而这篇论文的贡献并不是“在 Basil 上接一个 SQL parser”这么简单。Basil 不需要处理的两件事，Pesto 都必须补上：第一，服务端执行查询时如何通过 query-specific snapshot synchronization 仍然向客户端返回可被 BFT 信任的结果；第二，如何通过 semantic concurrency control 避免表达能力一上去、冲突范围就退化成整表级别。相对分层式 SMR 数据库，Pesto 用局部乐观验证和按需 rendezvous 取代了全局请求排序；相对 FalconDB 或 ChainifyDB 一类系统，它强调的是 interactive SQL transaction，而不是 stored procedure 或单副本查询卸载。

因此，这篇论文对两类读者都很有价值。做去中心化数据服务、互不信任多方协作数据库的人，可以从中看到一条“让 SQL 真正进入 BFT 环境而不必在每次操作上支付共识级延迟”的具体路径。做数据库并发控制的人，则会看到一个很好的例子：query semantics 不只是单机 DBMS 里的本地优化技巧，也可以成为 leaderless Byzantine 协议维持正确性的核心机制。从论文类型上看，这更像一篇新机制与系统架构论文，而不是单纯的 measurement study。

## 局限性

最直接的局限是复制成本。为了满足 Byzantine independence，Pesto 需要 `5f+1` 个副本，因此在算上密码学和 quorum 通信之前，它就已经比很多 `3f+1` 的 leader-based BFT 设计更贵。整个方案也明显押注了“多数时候副本差异不大、争用不高”这一乐观前提；一旦副本分歧加剧或争用升高，查询就需要更多 snapshot retry 与重执行，Zipfian 压测里这件事带来的吞吐损失并不小。

`SemanticCC` 本身也是保守近似。它用 filter predicate 和 table version 去压缩“查询真正依赖了什么”这件事，比完整追踪所有可能导致 phantom 的行便宜得多，但代价是：只要某次写入满足谓词，它就可能被视为冲突，即便最终端到端查询结果其实不会变化。write monotonicity 加 grace window 也是一种工程化折中，它确实让验证代价有界，但某些“到得较晚”的写者仍可能因为时间戳位置不理想而被迫 abort。

最后，论文最有说服力的仍然是内存型 OLTP 场景，对“完全通用的分布式 SQL 执行”讨论得没那么充分。range-read 协议在正文里是按“单个查询可由单个 shard 满足”来展开描述的，虽然事务本身可以跨分片；实验也只覆盖了 `f = 1`、单区域 CloudLab 环境。对于磁盘型部署、WAN 级部署，或者更高故障阈值下的表现，论文都没有进一步说明。

## 相关工作

- _Suri-Payer et al. (SOSP '21)_ - Basil 是 Pesto 最直接的前身：它已经证明 BFT 事务可以由客户端驱动且不依赖全局排序，但接口停留在 key-value，而不是完整 SQL 查询。
- _Peng et al. (SIGMOD '20)_ - FalconDB 用认证数据结构和有序提交来支持受限 SQL 查询，而 Pesto 保留了 interactive transaction，并避免在正常执行路径上做全局排序。
- _Androulaki et al. (EuroSys '18)_ - Hyperledger Fabric 采用 execute-order-validate 管线和 chaincode 模型，而 Pesto 希望对应用开发者呈现出普通关系数据库的 SQL 事务接口。
- _Schuhknecht et al. (CIDR '21)_ - ChainifyDB 也是把通用 SQL 接口放到 blockchain-backed 数据库上，但 Pesto 把复制、并发控制和查询级同步更深地整合进一个 BFT 关系引擎内部。

## 我的笔记

<!-- 留空；由人工补充 -->

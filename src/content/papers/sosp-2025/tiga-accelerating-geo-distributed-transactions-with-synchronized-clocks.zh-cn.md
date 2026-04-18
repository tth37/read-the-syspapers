---
title: "Tiga: Accelerating Geo-Distributed Transactions with Synchronized Clocks"
oneline: "Tiga 用同步时钟预分配未来时间戳，让跨地域冲突事务通常也能在各分片上按一致顺序执行，并在 1 WRTT 内提交。"
authors:
  - "Jinkun Geng"
  - "Shuai Mu"
  - "Anirudh Sivaraman"
  - "Balaji Prabhakar"
affiliations:
  - "Stony Brook University"
  - "New York University"
  - "Stanford University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764854"
code_url: "https://github.com/New-Consensus-Concurrency-Control/Tiga"
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

Tiga 先用同步时钟和单向时延为每个跨地域事务分配一个未来时间戳，使副本通常能在释放时间之前收到冲突事务，并按相同顺序处理。随后 leaders 再通过 timestamp agreement 和 super-quorum 的日志校验验证这条乐观顺序，因此大多数事务能在 1 个 wide-area RTT 内提交，只有预测失效时才退回到 `1.5-2 WRTTs` 的慢路径。

## 问题背景

geo-replicated OLTP 系统要同时满足两件事：跨 shard 的事务彼此隔离，跨 region 的副本对持久化历史达成一致。最常见的实现方式是把 concurrency control 叠在 consensus 之上。这个组合当然正确，但本质上为“排序”付了两次钱：一次处理事务之间的顺序，一次处理副本之间的顺序。在 wide-area 环境里，这些额外协调直接变成更多 WRTT、更长的锁持有时间，以及更低的吞吐。

已有 consolidated protocol 已经减少了一部分开销，但它们的 fast path 在冲突场景下仍然不稳。Tapir、Janus、Detock 都在不同程度上依赖事务在不同服务器上的到达顺序；而 geo-distributed 网络天然会让这个顺序失配，于是 fast path 退化成 abort、重试，或者昂贵的 dependency-graph 计算。论文追求的目标也比普通 serializability 更强：它要 strict serializability，因为 banking、ticketing、locking service 这类系统需要尊重真实时间顺序，而不只是事后找出某个可行串行顺序。

## 核心洞察

Tiga 的核心命题是：同步时钟可以把排序从“事后补救”变成“事前对齐”。协调者不再等各 shard 发现自己看到的冲突事务顺序不一致，而是在 multicast 之前就预测一个未来时间戳。这个时间戳由发送时刻、每个参与 shard 中某个 super quorum 的最大 one-way delay，以及一小段 headroom 组成，实现里 headroom 取 `10 ms`。只要服务器能在这个时间点之前收到事务，就可以等到同一个释放点，再按统一的 timestamp order 处理。

但时钟不是 correctness 的最终来源。Tiga 明确遵循“依赖时钟提升性能，而不是依赖时钟保证正确性”这一设计原则。leaders 在乐观执行之后仍然要交换时间戳、取最大值作为 agreed timestamp，并修复那些曾在本地把时间戳抬高的情况。真正的收益在于：同步时钟让 arrival-order 的失配从常态变成例外，于是昂贵修复路径不再处在关键路径的中心。

## 设计

Tiga 是一个 consolidated protocol，而不是先跑 concurrency control 再跑 consensus 的串联系统。每个服务器维护一个按时间戳排序的 priority queue、两个记录每个 key 最近释放时间戳的 read/write maps，以及带有 sync-point 和 commit-point 的复制日志。事务被假定为 one-shot stored procedure，或者先被分解成这种形式，因此系统能提前知道 read set 和 write set，conflict detection 成本很低。

提交开始时，coordinator 会带着未来时间戳把事务 multicast 给所有相关副本。服务器收到后，会检查该时间戳是否大于所有已释放冲突事务的时间戳；如果满足，就把事务放入队列。若 leader 收到得太晚，导致该时间戳已经无法进入队列，leader 会把时间戳提升到本地时钟再入队；followers 永远不做 timestamp update，只等待后续同步。当事务的时间戳已经过期、且前面没有更早的冲突事务阻塞时，leader 就会先做 speculative execution。followers 在 fast path 上并不执行事务，只负责释放、写入本地 log，并返回回复。

fast path 的关键在回复内容。每个 fast reply 都携带事务时间戳，以及事务之前 log prefix 的增量 hash。只有当 coordinator 从某个 shard 收到一个包含 leader、且在 hash 和 timestamp 上都一致的 super quorum 时，才会认定该 shard fast-committed。这里必须用 super quorum 而不是简单 quorum，因为系统恢复时必须能区分“真正已经提交的顺序”和“不同 follower 曾经看见过的两个互不兼容的推测顺序”。

在 speculative execution 之后，参与事务的 leaders 要运行 timestamp agreement。若所有 leader 本来就用了同一个时间戳，事务可以立即释放。若当前 leader 已经用了最大时间戳，但其他 leader 还没用到，Tiga 必须先再做一轮交换，防止出现 timestamp inversion，即跨 shard 的真实时间顺序和串行顺序发生冲突。若当前 leader 用的是更小的时间戳，它就要撤销之前的执行，把时间戳抬到 agreed maximum，重新放回队列，之后再执行。论文依赖 multi-versioned data 来完成这种撤销，因此这类回退对应用不可见，只是 Tiga 内部的重执行。

慢路径和故障恢复则负责把这些乐观步骤真正收口。leaders 把 agreed order 写入日志后，会向 followers 发送同步消息，修复分叉的 log entry 或时间戳，推进 sync-point，并最终收集 slow replies。某个 shard 上的事务只要拿到 leader 的 fast reply 加上 `f` 个 followers 的 slow reply，就算 slow-committed。发生故障时，view manager 会安装新 view，新 leader 从 `f + 1` 个存活副本中重建每个 shard，并尽量挑选可 co-locate 的 leaders，把 inter-leader timestamp agreement 挪到执行之前。于是 Tiga 实际上有两种运行模式：leaders 相距较远时用先执行后确认的 detective mode；leaders 能低延迟协同时用先确认后执行的 preventive mode。

## 实验评估

实现建立在 Janus codebase 之上，部署在 Google Cloud 的 South Carolina、Finland、Brazil 三个 region，并额外把部分 remote coordinators 放在 Hong Kong。这个实验设置的价值在于，基线协议共享相近的 RPC 与运行时环境，不是纸面比较；作者还主动补强了一些基线，例如让 Detock 执行同步 geo-replication，并同时评估原始 NCC 与带 fault tolerance 的 NCC+。

在低冲突的 MicroBench 上，Tiga 达到 `157.3K txns/s`，高于 Calvin+ 的 `119.6K`、Janus 的 `77.8K`、Tapir 的 `44.2K` 和 NCC 的 `47.4K`。论文将总体结果概括为：在接近饱和点时，Tiga 比基线高 `1.3x-7.2x` 吞吐、低 `1.4x-4.6x` 中位延迟。更重要的是退化方式不同。Tapir 会因不同副本看到的到达顺序不同而迅速增加 abort；Janus 和 Detock 会越来越被图算法拖慢；Calvin+ 则会遭遇 straggler 问题。即便把 coordinators 放到 Hong Kong，Tiga 仍能维持 1-WRTT 延迟，而 Janus、Tapir、Calvin+ 在这种非 co-located 场景下都至少需要 2 WRTTs。

TPC-C 更能检验论文主张，因为它既有 interactive transaction，也有更高的冲突密度。Tiga 仍以 `21.6K txns/s` 领先，超过 Detock 的 `13.3K`、Janus 的 `10.8K` 和 Calvin+ 的 `6.1K`。2PL+Paxos、OCC+Paxos 与 Tapir 都掉到大约 `1K-2K txns/s`，而 NCC 只有数百 txns/s，NCC+ 还要更低。这说明基于同步时钟的主动排序并不只适用于“友好的一次性事务”，在高冲突多分片 OLTP 场景下也确实能减少协调成本。

次级实验也很关键。Tiga 在 leader failure 后只用 `3.8 s` 就恢复到原有吞吐水平。若故意把 leaders 分散到不同 region，吞吐也只下降 `9.7%`，但延迟会上升，因为更多事务要等待 timestamp agreement 或经历重执行。headroom 敏感性实验表明，默认估计已接近最优：headroom 太小会增加 rollback，太大则只是让事务在服务器端多等。最后，Chrony 的 `4.54 ms` 同步误差与 Huygens 的 `0.012 ms` 几乎表现一致，因为二者相对于 `60-150 ms` 的 WAN delay 都足够小；真正让 Tiga 失去优势的是时钟质量明显恶化的情况。

## 创新性与影响

与 Tapir、Janus、Detock、NCC 相比，Tiga 的新意并不只是“用了时钟”或者“把排序层合并了”，因为这些思路先前都存在。它真正新的地方，是把基于 one-way delay 的 future timestamp、对 speculative log prefix 的 super-quorum 校验、显式规避 timestamp inversion 的规则，以及完整的 failure recovery 机制，组合成了一个能维持 strict serializability 的整体协议。

这使它的意义超出单个系统本身。论文实质上在论证：public cloud 今天的时钟同步质量，已经足以改变 geo-distributed transaction protocol 的设计空间。对数据库研究者而言，这是一个很干净的机制结论；对构建全球复制服务的工程师而言，它提供了一条现实路线，让系统更接近 1-WRTT 提交，而不必牺牲 strict serializability，也不必在热路径上承担 Janus/Detock 式的图处理开销。

## 局限性

Tiga 的最佳情形依赖两个条件：时钟误差必须远小于 WAN delay，而且最好能把 leaders co-locate。若 leaders 分散部署，后续冲突事务就可能被 `0.5-1 RTT` 的 timestamp agreement 挡住，一部分 speculative execution 还需要撤销重放。论文中的吞吐损失不算大，但延迟代价是实实在在的。

协议还默认 read/write sets 在执行前已知，因此最自然的适用对象仍是 one-shot stored procedures；interactive transaction 的支持来自 decomposition，而不是协议原生表达能力。再加上 multi-version revocation、log synchronization、view manager、checkpoints，以及 detective/preventive 两套执行模式，完整系统的实现复杂度并不低。一旦时钟误差开始接近网络时延量级，Tiga 的等待时间和延迟优势也会明显恶化。

## 相关工作

- _Corbett et al. (OSDI '12)_ - Spanner 同样利用同步时钟处理 geo-distributed transaction，但它仍然承担分层的提交与复制成本；Tiga 试图把这条常见路径压缩成更轻的 1-WRTT common path。
- _Zhang et al. (SOSP '15)_ - Tapir 通过 inconsistent replication 追求 1-RTT fast path，而 Tiga 的关键贡献是让冲突事务更不容易在不同副本上形成不一致到达顺序。
- _Mu et al. (OSDI '16)_ - Janus 证明了在冲突场景下合并 concurrency control 与 consensus 的价值；Tiga 延续这一方向，但把 dependency graph 处理换成了主动的 timestamp 对齐。
- _Lu et al. (OSDI '23)_ - NCC 通过在冲突事务之间插入 response-time 间隔来保护 strict serializability，而 Tiga 选择在执行前先尽量把顺序对齐，再对少数失配情况做修复。

## 我的笔记

<!-- 留空；由人工补充 -->

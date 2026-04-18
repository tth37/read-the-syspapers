---
title: "Pineapple: Unifying Multi-Paxos and Atomic Shared Registers"
oneline: "Pineapple 用统一的 pstamp，把 follower 可服务的单键线性化读和 blind write 接到 Multi-Paxos 的 one-shot transaction 排序上。"
authors:
  - "Tigran Bantikyan"
  - "Jonathan Zarnstorff"
  - "Te-Yen Chou"
  - "Lewis Tseng"
  - "Roberto Palmieri"
affiliations:
  - "Northwestern"
  - "Unaffiliated"
  - "CMU"
  - "UMass Lowell"
  - "Lehigh University"
conference: nsdi-2025
category: consensus-and-blockchain
tags:
  - consensus
  - fault-tolerance
  - transactions
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pineapple 把线性化存储拆成两条排序路径：单键 read 和 blind write 走 ABD 风格 atomic register，read-modify-write 与 one-shot transaction 走 Multi-Paxos。它用统一的 `pstamp = (tag, slot)` 把 follower 可服务的寄存器操作与 leader 排序的事务接进同一个顺序里，因此 3 节点部署下 read 可以维持 1 RTT，而更强的操作仍满足 linearizability。结果是 leader 压力更小，并在论文关注的 web-storage workload 上同时改善吞吐与尾延迟。

## 问题背景

线性化存储最常见的实现方式是 leader-based consensus，但这会带来一个老问题：所有 read、write 和 transaction 都想把 leader 放在关键路径上。这样虽然容易讲清 correctness，却浪费了本来就保存了数据的 follower。论文面向的是大规模 web application 的存储后端，这类系统往往以单键读写为主，但又因为弱一致性会显著增加应用复杂度，所以仍然需要强一致性。

现有方案都只解决了局部问题。Multi-Paxos 和 Raft 的排序语义最直观，但 leader 最先饱和。PQR 把 read 下放给 follower，可 write 仍然卡在 leader 上，而且 read 还可能因为等待 committed log entry 而阻塞。Gryff 通过把 EPaxos 与 atomic shared register 结合，让 read 和 write 不必都找 leader，但它的消息和执行开销更高，只支持单键操作，并且 read-modify-write 仍要等待 dependency resolution。

真正困难的地方不只是“把单键操作做快”。一旦某个操作依赖之前的状态，或者同时跨越多个 key，系统就需要稳定的全局顺序。简单地对每个 key 独立跑 ABD 会产生不可比较的多键结果，因为不同 quorum 可能只看到了不同的写入子集。Pineapple 想保留普通读写的廉价 quorum 路径，同时给 transaction 和更强的同步语义提供稳定排序。

## 核心洞察

论文最重要的判断是：线性化存储不必对所有操作使用同一种排序机制。单键 read 和 blind write 只需要 atomic shared register 那种较弱、非稳定的顺序，因为每次 write 都完整定义了新值。相反，read-modify-write 和多键 one-shot transaction 的结果依赖于先前状态，因此必须依赖 state-machine replication 那种稳定顺序。

Pineapple 用 `pstamp` 把这两套机制接起来。`pstamp` 是按字典序比较的 `(tag, slot)` 二元组，其中 `tag` 来自 multi-writer ABD，用于给寄存器式 write 排序；`slot` 来自 Multi-Paxos，用于稳定 leader 执行事务的相对顺序。只要 leader 在事务的 get phase 里看到了当前最新值，它就可以分配一个更晚的 slot，把“某次 write 与这次 transaction 的先后关系”固定下来。真正的关键就在这里：寄存器路径仍然便宜，但一旦 transaction 介入，leader 就能在不把所有操作都塞进 consensus log 的前提下，把顺序钉死。

## 设计

Pineapple 暴露三类操作：`Read(k)`、blind `Write(k, v)`，以及 `OT(f, Kinput, Koutput)` 形式的 one-shot transaction，其中事务代码和输入/输出 key 集在执行前就必须已知。它故意把直接写原语做窄：单键 blind write 只负责覆盖一个 key；compare-and-swap、fetch-and-add、转账式更新、scan 等更强语义都要表示成 one-shot transaction。

每个 replica 对每个 key 保存一个 value 和一个 `pstamp`。`pstamp` 是论文用来统一两条路径的时间戳：其中 `tag = (ts, id)` 来自 multi-writer ABD，`slot` 来自 Multi-Paxos。Pineapple 按字典序比较 `pstamp`，因此普通 write 只推进 tag，普通 read 按最大 `pstamp` 选值，而 leader 执行的 transaction 则在复用最新 tag 的同时推进 slot。正因为这样，寄存器路径的结果与事务路径的结果才可以直接比较先后。

ABD 路径基本保持经典两阶段协议。blind write 先从 quorum 学到最大的 tag，再用 `(tag.ts + 1, writer-id)` 和最近观察到的 slot 把新值写回去。read 则先从 quorum 读取 value-`pstamp` 对，选出 `pstamp` 最大的值，再把这个胜出的 pair 传播到 quorum 后返回。论文继承了前人对 ABD 的优化，因此在 `n = 3` 时 read 总能 1 RTT 完成；在更大部署里，如果同一 key 上没有并发 write 或 one-shot transaction，read 也可以走 1-RTT fast path。

read-modify-write 和多键 one-shot transaction 走 Multi-Paxos leader。leader 的读取 quorum 必须包含自己，因为它可能是唯一已经看见最新 leader-ordered 更新的节点。它先读取最新输入、执行 `f`，再给所有输出分配一个新的 `pstamp`：其中 tag 继承自最新观察到的输入，slot 取 leader 的下一个 Paxos slot，然后把这些输出写到 quorum。一次 transaction 的所有输出共享同一个 `pstamp`，这正是论文用来避免 scan anomaly 的关键：多键操作之所以可比较，是因为 leader 为它们固定了稳定顺序中的位置。

论文还把 “non-blocking execution” 当作核心性质。节点一旦学到相关 quorum 结果或 leader 决定，就可以立即执行；它不需要像 EPaxos 系方案那样等待 dependency graph 清空。遇到 leader change 时，Pineapple 会把 ballot 元数据并入 `pstamp`，并让 read 在探测到更新的竞争 leader 后退避重试，因此安全性仍来自 ABD 与 Multi-Paxos 的组合，而 liveness 仍依赖最终选出稳定 leader。

## 实验评估

评测用 Go 在与 EPaxos、Gryff、Multi-Paxos 相同的框架上实现 Pineapple、PQR 和带 leader lease 的 Multi-Paxos，然后在 CloudLab 上分别跑 10 Gbps LAN 和模拟 WAN。这个设置本身很重要，因为作者还明确关闭了 batching 和 thrifty optimization，目的是比较 tail latency，而不是在有利于 batching 的条件下只追求峰值吞吐。除 etcd 集成外，大多数实验都使用 16 B 的内存对象；etcd 实验则使用带默认 100 KB value 的 YCSB，并开启持久化。

在 5 节点 LAN 的 balanced read/write 负载下，只要 read-modify-write 占比不超过 20%，Pineapple 就处在它最擅长的区间：此时它的吞吐比最接近的对手 EPaxos 高约 10% 到 20%，而且在饱和点附近保持最低的 median 和 p90 latency。这个优势在全 RMW 负载下会消失，因为 Pineapple 的 leader 又重新成为瓶颈；论文图中此时 EPaxos 凭借 leaderless 设计大约快 2.2x。

WAN 结果把这种 trade-off 展示得更清楚。在 3 节点 read-heavy 部署里，Pineapple 和 Gryff 都能把 read 维持在 1 RTT。论文的 WAN 延迟图还展示了 PQR 的代价：当 leader 不在客户端最近的 quorum 中时，follower 必须等待 committed log state 才能回复，因此 read 的 tail latency 会明显变差。在 25% conflict 下，Pineapple 的 RMW p99 比 Gryff 低大约 30 ms，因为 Pineapple 不需要等 dependency resolution 才能执行。在 balanced WAN workload 中，Pineapple 的吞吐大约是次优方案 PQR 或带 lease 的 Multi-Paxos 的 3x 到 4x；但在 read-heavy WAN workload 中，带 lease 的 Multi-Paxos 仍能以约 1.25x 到 1.3x 的优势赢下纯吞吐，因为 Pineapple 的 read 仍要交换 quorum 消息。

etcd 集成是论文最有说服力的现实性检查。把 etcd 中优化过的 Raft 层换成 Pineapple 后，在 balanced YCSB 风格 LAN 负载上，中位延迟下降超过 50%，而论文展示的几组 workload 中，p50 latency 大致也有 20% 到 50% 的下降。代价是吞吐没有超过 Raft；作者把这个差距归因于 Raft 现有的 disk batching，而他们的 Pineapple 原型还没有复现这一优化。

## 创新性与影响

Pineapple 的创新点，与其说是提出了一个全新的 consensus protocol，不如说是把两类通常分开存在的成熟技术认真拼接在了一起：quorum-based atomic register 与 leader-based state-machine replication。相较于 PQR，它不仅下放 read，也下放 write，而且避免了 blocking read execution。相较于 Gryff，它重新把 leader 放回设计里，以换取多键 one-shot transaction 支持和更简单的执行语义，而不是继续背负 EPaxos 的 dependency graph。相较于普通 Multi-Paxos 或 Raft，它不再假设每个操作都必须穿过 leader。

因此，这篇论文对 etcd 一类控制平面、geo-replicated key-value store，以及所有想在 read-heavy 或 balanced workload 下保住强一致性、又不愿完全接受 leader bottleneck 的系统设计者都很有参考价值。我预计它会被当作一篇“设计点”论文来引用：不是因为它发明了新原语，而是因为它证明了两套排序纪律可以按操作类型拆分，再通过一个统一接口和统一时间戳重新拼回线性化语义。

## 局限性

它的适用范围本来就比通用事务数据库更窄。Pineapple 直接提供的 write 是 blind write，不是 conditional write；更强的操作必须落入 one-shot transaction 模型，也就是函数和输入/输出 key 集都要在执行前已知。这对很多基于 key-value 的 web application 已经够用，但它并不能直接替代任意交互式事务。

它的性能包线也天然不均匀。read-modify-write 和 one-shot transaction 在常见情况下仍然要经过 leader，并付出 3 RTT，所以随着 RMW 占比上升，leader 压力会重新出现；论文自己的 LAN 图就显示，当 workload 变成全 RMW 时 EPaxos 会反超，而 WAN 附录也显示在 read-heavy 吞吐上带 lease 的 Multi-Paxos 仍能胜过 Pineapple。Pineapple 对 leader change 还需要额外机制：ballot 必须并入 `pstamp`，read 在发现更新候选 leader 时必须退避，因此它的 liveness 仍依赖 partial synchrony 和稳定 leader。

最后，文中的绝对性能数字来自一个刻意受控的实验区间：大多是内存中的 16 B 对象、closed-loop client、关闭 batching，而且除了 etcd 之外不使用 Zipfian skew。这些选择很适合隔离算法贡献，但也意味着论文并没有完全回答：在热点更集中的生产负载，或者持久化优化占主导的存储栈里，这些收益还能保留多少。

## 相关工作

- _Burke et al. (NSDI '20)_ - `Gryff` 同样把 shared register 与 consensus layer 结合起来，但它对 RMW 依赖 EPaxos dependency，并且只能处理单键操作；`Pineapple` 保留 leader，从而支持 one-shot transaction 和 non-blocking execution。
- _Charapko et al. (HotStorage '19)_ - `PQR` 在 Paxos 之上加入 follower-served read，而 `Pineapple` 连 blind write 也一起下放，并避免 read path 等待 committed log entry。
- _Moraru et al. (SOSP '13)_ - `EPaxos` 把排序责任分散到各 replica，但 conflict 下 dependency graph 会伤害吞吐和尾延迟；`Pineapple` 重新引入 leader，以为更强的操作拿到稳定顺序。
- _Attiya et al. (JACM '95)_ - `ABD` 为 atomic register 提供线性化的 quorum read/write，而 `Pineapple` 则把这套 register discipline 作为 Multi-Paxos 事务排序之下的 fast path。

## 我的笔记

<!-- 留空；由人工补充 -->

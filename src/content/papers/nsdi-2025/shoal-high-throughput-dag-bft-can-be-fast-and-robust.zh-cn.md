---
title: "Shoal++: High Throughput DAG BFT Can Be Fast and Robust!"
oneline: "Shoal++ 用 weak-vote 快速提交、动态多锚点和三条交错 DAG，把 certified DAG-BFT 的平均端到端延迟压到约 4.5 个 message delay。"
authors:
  - "Balaji Arun"
  - "Zekun Li"
  - "Florian Suri-Payer"
  - "Sourav Das"
  - "Alexander Spiegelman"
affiliations:
  - "Aptos Labs"
  - "Cornell University"
  - "UIUC"
conference: nsdi-2025
category: consensus-and-blockchain
tags:
  - consensus
  - fault-tolerance
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Shoal++ 是一个部分同步的 DAG-BFT 协议。它保留了 Narwhal/Bullshark 一系 certified DAG 的鲁棒传播骨架，但把以往 DAG 协议慢的三个来源分开优化：排队、被 anchor 覆盖、以及 anchor 自身提交。它用 `2f+1` 个 proposal 级别的 weak vote 提前提交 anchor，把更多节点动态提升为 anchor，并让三条交错的 DAG 并行运行，把 Shoal 的期望延迟从 10.5 个 message delay 压到 4.5，同时保持高吞吐。

## 问题背景

传统 leader-based BFT 协议，例如 PBFT，一旦 leader 正常，常见情况只需 3 个 message delay 就能提交，这是延迟上的最佳点。但它们把吞吐上限绑死在单个 leader 的网卡和 CPU 上。DAG-BFT 则反过来：让每个 replica 都能提案，并把数据传播与共识拆开，因此更适合大规模区块链部署。代价是延迟变长，事务不仅要等进入某一轮，还要等未来某个 anchor 把它“捞起来”，随后还要再等该 anchor 真正提交。

论文把这笔账拆得很清楚。在 Bullshark 和 Shoal 这类 certified DAG 协议里，平均端到端延迟可以分成三部分：大约 1.5 个 message delay 的排队延迟，加上 anchoring latency，再加上 anchor commit latency。Bullshark 的期望总延迟约为 12，Shoal 也只能降到 10.5。近期一些 uncertified DAG 方案尝试通过去掉 certification 来省延迟，但作者认为这只是把成本挪了位置：replica 现在可能不得不在共识关键路径上抓取缺失数据，而网络抖动或慢节点一来，这种设计就会变脆。

## 核心洞察

这篇论文最重要的判断是，certified DAG 并不天生就慢；真正拖后腿的是 anchor 的保守处理方式。Shoal++ 保留 certification，因为 certified node 能保证 DAG 视图最终收敛，也让缺失数据的抓取可以放到关键路径之外；它选择针对三个延迟分量分别下手，而不是放弃 certified DAG 这条路线。

核心招式是把“proposal 已经到达”也当成有价值的证据。如果某个 anchor 已经被 `2f+1` 个 proposal 指向，那么其中至少 `f+1` 个链接来自正确 replica，最终一定会形成 certification，于是这个 anchor 的命运其实已经基本确定了。再配合更激进的 anchor 调度和多条交错 DAG，Shoal++ 就能在不回到单 leader 设计的前提下，把 certified DAG-BFT 的延迟推近 PBFT 一类协议。

## 设计

Shoal++ 以 Narwhal 的 round-based certified DAG 和 Bullshark 的嵌入式共识为起点。每一轮里，每个 replica 最多提出一个 node，它要引用上一轮的 `n-f` 个 certified node。某些 node 被指定为 anchor；一旦某个 anchor 被提交，它的 causal history 就成为下一段有序日志。Shoal++ 对这个基础流程做了三处关键改造。

第一处是 Fast Direct Commit rule。Bullshark 需要等到后续一轮里有 `f+1` 个 certified node 指向某个 anchor，才能直接提交它，这至少要跨两轮 certification。Shoal++ 额外统计 proposal 级别的引用，把它们记作 weak vote。只要某个 replica 看到 `2f+1` 个 proposal 指向同一个 anchor，它就可以在 4 个 message delay 内安全地 fast-commit：3 个用于认证该 anchor 自己，再加 1 个用于接收下一轮 proposal。因为在不稳定网络里，拿到 `2f+1` 个 weak vote 有时反而比拿到 `f+1` 个 certified vote 更难，原始的 Bullshark direct-commit 规则仍然保留为后备路径，谁先满足就走谁。

第二处是尽量消灭 anchoring latency，让几乎每个 node 都能成为 anchor candidate。直接这么做会把进度串行地卡在最慢 anchor 上，所以论文加入了两层控制。其一，在看到前 `2f+1` 个 node 之后再额外等一个很小的 round timeout，让各 replica 更接近 lock-step 前进，形成更稠密的父边，这样 `GET_ANCHORS` 才有条件从 Shoal 中“只挑信誉最快的少数节点”扩展为“让全部 `n` 个节点都有资格成为 anchor”。其二，协议把每轮里除第一个之外的 anchor 都视作 virtual anchor。每当当前共识实例解决后，replica 只 materialize 下一个真正需要处理的 anchor；如果某个后续已提交 anchor 已经证明更早的 tentative anchor 会被跳过，Shoal++ 就直接越过这些过时实例，而不是把每个被跳过的 Bullshark 路径都显式跑一遍。

第三处是通过并行运行 `k` 条 DAG 来降低排队延迟，并把它们的输出交织成单一总序。实现里使用 `k=3`，三条 DAG 相互错开 1 个 message delay，因此系统不再是每 3 个 message delay 才有一次提案机会，而是几乎每 1 个 message delay 就有一条 DAG 可接收新事务。每条 DAG 独立提交 anchor，再按 round-robin 顺序把各自产出的有序 segment 追加到总日志。论文还选择 inline 传播 transaction batch，而不是使用 Narwhal 的 worker layer，这样就不会在关键路径上为了追 hash 引用而额外取数。

## 实验评估

就论文的核心主张而言，这组评测是比较扎实的。Shoal++ 被实现到 Aptos 的 Rust 代码库中，使用 Tokio、BLS 签名、RocksDB 持久化和 Noise 认证。作者把它与 Bullshark、Shoal、Mysticeti 和 Jolteon 对比，测试平台是分布在 10 个 Google Cloud 区域的 100 个 replica，区域间 RTT 为 25 ms 到 317 ms。客户端提交 310 字节的 dummy transaction，batch size 为 500，并关闭 execution 和 ledger storage 以隔离共识层开销。Bullshark、Shoal 和 Jolteon 都是在同一代码库里按论文描述重实现；Mysticeti 则直接跑其公开代码，而且不做 consensus data 持久化，因此这个 baseline 实际上并不吃亏。

在无故障场景下，Shoal++ 是唯一一个在 100k TPS 时仍能保持 sub-second latency 的系统。它在低负载下约为 775 ms，并可扩展到大约 140k TPS。Bullshark 和 Shoal 大约在 75k TPS 处见顶，而且低负载下延迟已经分别约为 1.9 s 和 1.45 s；Jolteon 低负载约为 900 ms，但在约 2100 TPS 就被 leader 带宽打满。分解实验说明，Fast Direct Commit 的确有帮助，但更大的收益来自 “more anchors”：多数 node 不再等待别的 anchor 来覆盖，因此平均能节省约 3 个 message delay。并行 DAG 在此基础上继续缩短 queueing latency，同时让提案流量更像持续流式发送，而不是按轮突发。

鲁棒性结果也支撑了论文对 certified DAG 的辩护。当 100 个 replica 中有 33 个崩溃时，Shoal++ 和 Shoal 仍能快速调整 anchor 选择，高负载下延迟大致增加到原来的 2 倍；Bullshark 和 Mysticeti 则因为没有 reputation-guided 的 anchor 选择而恶化得多。再看丢包实验：当 100 个节点中的 5 个节点有 1% egress message drop 时，Mysticeti 的延迟会飙升约 10 倍，而 Shoal++ 最多只上升到 1.3 倍，因为它对缺失 certified node 的补抓不在关键路径上。

## 创新性与影响

Shoal++ 的价值不在于提出一个全新的 BFT 模型，而在于把 certified DAG-BFT 这一条技术路线的快路径重新设计了一遍。相较于 Bullshark，它同时改了 anchor 多快能提交，以及 anchor 调度有多激进。相较于 Shoal，它把 reputation 和动态重解释的思想推进到“绝大多数节点都先当 provisional anchor，再按需要 materialize”的程度，并把多条交错 DAG 组合成单一日志。相较于 Mysticeti 这类 uncertified 方案，它的立场很明确：真正的瓶颈不是 certification 本身，而是 anchor 处理方式，鲁棒性不应该被轻易拿去交换。

因此，这篇论文很可能会影响区块链共识栈以及其他 geo-distributed BFT 服务的设计者，尤其是那些希望保留 leader-free throughput、又不愿接受旧 DAG 协议 10 多个 message delay 成本的人。文中多 DAG 并行的技巧也明显具有独立复用价值。

## 局限性

Shoal++ 仍然是部分同步模型下针对常见情况的优化，不是面对强对手时的最坏情况延迟保证。Fast commit 依赖 `2f+1` 个 weak vote 足够快地出现，低 anchoring latency 则依赖 reputation 机制和短 round timeout 维持一个足够稠密的 DAG。论文评测了 crash 和 packet loss，但没有系统性评估更有策略的 Byzantine 行为，例如故意操纵 reputation 或制造极端 weak-vote 分布。

系统资源开销也更高。因为要同时维护多条 DAG，Shoal++ 比 Shoal 消耗更多 CPU、内存和磁盘。即使在无故障的理想情况里，它的目标也只是 4.5 个 message delay，仍高于 PBFT 的 3 个 message delay；除非愿意切换到更昂贵的 all-to-all 通信。最后，实验关闭了 execution 和正常的 ledger stack，因此文中的收益更准确地说是“共识层面的延迟改进”，而不是整个区块链应用端到端体验的直接测量。

## 相关工作

- _Spiegelman et al. (FC '24)_ - `Shoal` 已经通过每轮 anchor 和基于 reputation 的候选选择改善 `Bullshark`；`Shoal++` 则在这条线上继续加入 fast commit、dynamic virtual anchor 和 parallel DAG。
- _Spiegelman et al. (CCS '22)_ - `Bullshark` 是 `Shoal++` 直接针对的 certified DAG-BFT 基线，后者重写了其 direct-commit 快路径和隔轮 anchor 调度。
- _Danezis et al. (EuroSys '22)_ - `Narwhal and Tusk` 奠定了 round-based certified DAG 这一传播骨架，而 `Shoal++` 的贡献是把这条骨架上的 anchor 管理做得更低延迟。
- _Giridharan et al. (SOSP '24)_ - `Autobahn` 通过不使用 DAG、改走 parallel data lanes 来降低 BFT 延迟；`Shoal++` 则坚持 certified DAG-BFT，并试图把这一路线做得足够快。

## 我的笔记

<!-- empty; left for the human reader -->

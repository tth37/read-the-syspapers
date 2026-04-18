---
title: "Runtime Protocol Refinement Checking for Distributed Protocol Implementations"
oneline: "Ellsberg 从部署中服务的消息轨迹对照协议模型做 refinement check，在不修改实现、也不做跨节点协调的前提下发现运行时协议安全 bug。"
authors:
  - "Ding Ding"
  - "Zhanghan Wang"
  - "Jinyang Li"
  - "Aurojit Panda"
affiliations:
  - "NYU"
conference: nsdi-2025
category: network-verification-and-synthesis
tags:
  - verification
  - formal-methods
  - fault-tolerance
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Ellsberg 是一个面向已部署 distributed protocol implementation 的运行时 protocol refinement checker。它观察每个进程的消息轨迹，维护与当前 prefix 一致的协议状态集合，并在某个 outgoing message 没有任何 reachable inducing state 时报警。作者把它用在 Etcd、ZooKeeper 和 Redis Raft 上，复现了已知安全性 bug，并额外找到了一个新的 Redis Raft 重配置 bug。

## 问题背景

论文的出发点很直接：协议被证明正确，并不意味着生产系统里的实现就是正确的。很多广泛部署的 distributed protocol implementation 仍会在 leader election、linearizable read、reconfiguration 这些关键路径上出现 bug。Etcd 的 stale read 和 ZooKeeper 的选主错误就是作者给出的代表性例子。

现有方法各有盲区。静态证明验证的是模型或受限实现风格；测试和 fuzzing 只能覆盖探索到的执行；trace validation 往往假设测试已经结束且日志可被全序化；global runtime verification 常常需要跨节点协调快照。Ellsberg 要解决的，就是如何在不做额外跨节点协调的前提下，为已经部署的 black-box 服务检测协议实现 bug。

## 核心洞察

论文最核心的判断是：在 fail-stop、非 Byzantine 的假设下，局部 refinement checking 就足以暴露安全性违例。只要每个活进程的行为仍可由某个正确协议执行解释，实现就还没有显式违反协议。因此 Ellsberg 按进程独立检查，而不是先构造一个全局一致快照。

真正的难点是并发。checker 看不到内部状态，也不知道并发实现到底按什么顺序处理了 pending message 和 timeout，所以它不能只维护一个模拟状态，而必须维护一组可能状态。每个 outgoing message 就成为证据：Ellsberg 先推断哪些 partial state 可能诱导出它，再判断这些状态是否从当前 simulation set 可达。

## 设计

Ellsberg 需要用户从协议模型出发提供一份专用规范，其中包括协议状态类型、`apply`、`equal`、`infer_inducing`、用于剪枝的保守 `reachable`、标记可立即应用事件的 `apply_asap?`，以及可选的 `lookahead_type`。部署侧只需要给每个 checker 一条本地增量 trace，里面包含全部 incoming/outgoing message，以及同一连接上的接收顺序和 outgoing 的程序顺序。

运行时，每个 Ellsberg instance 维护一个 simulation set `S`。一个 simulation state 同时包含协议状态和 pending-message set，因为不同 schedule 可能到达同一个抽象状态，却留下不同的未处理输入。新的 incoming message 要么加入 pending set，要么在 `apply_asap?` 允许时被立即应用并递归剪枝。

当 trace 中出现 outgoing message 时，Ellsberg 先算出可能诱导出它的 partial target state，再从每个当前 simulation state 调用 `find_reachable`。这个过程在 pending input 和 timeout 组成的 schedule 空间上做 breadth-first search。BFS 的意义在于较短 schedule 会保留更大的 pending set；如果过早丢掉它们，后续输出检查就可能误报。搜索过程中，Ellsberg 会合并语义等价状态、在必要时保留不同的 pending-message set，并用 `reachable` 提前剪掉无用分支。

## 实验评估

原型使用 Go 实现，目标系统是 Etcd、ZooKeeper 和 Redis Raft，部署在 3 节点与 5 节点的 CloudLab 集群上。作者使用 120 个 YCSB 客户端驱动 balanced 与 read-heavy 两类负载，把每个 Ellsberg instance 固定在 2 个核上，并设置为每秒处理一次 trace。作者还先用从 TLA+ 模型生成的合法 trace 去验证派生出来的 Ellsberg 规范：Raft 覆盖了 8,750,468 条 trace，ZooKeeper 覆盖了 1,904,456 条。

最核心的结果是 bug finding。Ellsberg 成功复现并检测了三套系统中已有报告的 bug，覆盖 stale read、leader election 不一致、lost update，以及多类 reconfiguration 错误；它还额外找到了一个此前未公开的 Redis Raft 重配置 bug。它会在 Etcd leader 尚未提交当前 term entry 就开始为 read 做 quorum check 时报警，也会在 ZooKeeper leader 发出任何合法日志状态都无法诱导出的 `DIFF` 消息时报警。

开销结果支持“可部署”这个主张。论文报告被监控服务的吞吐没有下降，最差延迟开销出现在 read-heavy 的 Redis Raft，其 99th-percentile latency 从 7.25 ms 增加到 8.03 ms，也就是 10.7%。Ellsberg 自身处理 outgoing message 的能力还高于被监控系统：相当于 Etcd 的 2.0-51.7x、ZooKeeper 的 1.4-29.7x，以及 Redis Raft 的 3.1-25.5x。配合“一秒一批”的配置，leader 每处理一秒 trace 约耗时 30-700 ms，follower 约 20-180 ms，因此报警延迟大约在 1.7 秒以内。启用 `apply_asap?` 后，平均 simulation set 保持在一个状态，pending message 数保持在 0 到 5。

## 创新性与影响

这篇论文的重要贡献，是在静态 refinement proof 与 runtime verification 之间提出一条中间路线。Ellsberg 在部署后继续复用协议模型，但不要求验证过的代码、不要求全序日志，也不要求跨节点一致快照。inducing-state 的表述方式，再加上 BFS、reachability pruning 和立即应用可安全重排事件的优化，共同让这条路线在实践中可行。

## 局限性

Ellsberg 只能发现那些最终会改变消息内容或消息顺序的 bug。它抓不到 deadlock、livelock、纯性能退化，也抓不到永远不会反映到网络行为上的内部状态损坏。它同样不能证明一个实现“正确”，只能说明当前观察到的 trace prefix 仍然存在协议一致的解释。

它的前提也比较强。这个方法要求协议规范本身正确、增量 trace 真实完整、故障模型是 fail-stop 而不是 Byzantine，而且消息里必须包含足够多的信息去推断协议状态。论文明确指出，一些 MVCC 风格数据库就不满足最后这个条件，因为消息没有暴露足够的版本信息，导致 checker 不得不保留过多 partial state 和 schedule。

## 相关工作

- _Howard et al. (NSDI '25)_ - `Smart Casual Verification` 在测试与 CI 环境里把实现 trace 对照 TLA+ 规范，而 Ellsberg 面向部署期在线检查，并且不要求一个全序化的测试 trace。
- _Hawblitzel et al. (SOSP '15)_ - `IronFleet` 做的是静态、端到端的 refinement proof；Ellsberg 则接受任意现有代码，但代价是只能在违例发生后检测出来。
- _Wilcox et al. (PLDI '15)_ - `Verdi` 从 Coq 中提取已验证的分布式系统，而 Ellsberg 面向不做修改的 black-box 服务，用较弱保证换取可部署性。
- _Yaseen et al. (OSDI '20)_ - `Aragog` 通过分布式状态检查全局运行时性质，而 Ellsberg 只靠消息轨迹检查局部协议 refinement，因此不需要跨节点协调。

## 我的笔记

<!-- empty; left for the human reader -->

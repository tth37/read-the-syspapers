---
title: "Basilisk: Using Provenance Invariants to Automate Proofs of Undecidable Protocols"
oneline: "Basilisk 把难写的全局协议不变量拆成可静态推导的 provenance facts，再用 atomic sharding 在 Dafny 中自动合成归纳不变量。"
authors:
  - "Tony Nuda Zhang"
  - "Keshav Singh"
  - "Tej Chajed"
  - "Manos Kapritsos"
  - "Bryan Parno"
affiliations:
  - "University of Michigan"
  - "University of Wisconsin–Madison"
  - "Carnegie Mellon University"
conference: osdi-2025
code_url: "https://github.com/GLaDOS-Michigan/Basilisk"
tags:
  - verification
  - formal-methods
  - pl-systems
category: verification-and-security
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Basilisk 自动化了分布式协议证明里最耗人的一环：归纳不变量的构造。它的核心做法是把原本需要人工发明的全局协议事实，改写成可机械推导的 provenance invariants，再用 atomic sharding 从主机状态变量的更新方式中自动合成这些不变量。

## 问题背景

论文针对的是分布式协议形式化验证里的一个老大难问题。像 agreement 这样的安全性质通常本身并不具有归纳性，因此验证者必须找到一个更强的归纳不变量，它既能推出安全性质，又能在每一步状态转移后继续保持。在 EPR 这类可判定逻辑里，先前系统确实能自动推导不少不变量，但代价是建模语言很受限，连算术这样的常见写法都难以表达。相反，在 Dafny 或 IronFleet 风格的通用框架里，开发者可以自然地描述协议，却往往要自己把不变量一点点找出来。

真正痛苦的正是这个搜索过程。作者指出，最难写的条款通常不是单机上的局部事实，例如 monotonicity；真正困难的是跨主机、跨步骤的解释性事实，也就是“某个主机现在之所以处于这个状态，是因为另一个主机之前做过什么”。Kondo 虽然减轻了一部分负担，但这类概念上最棘手的性质仍然依赖人类直觉。Basilisk 想回答的问题是：这些看上去需要“创造力”的不变量，能否被拆成工具可自动推导的更简单事实，即使底层逻辑本身是不可判定的。

## 核心洞察

论文的中心命题是，许多看似全局的协议不变量，本质上是因果血缘关系。与其直接写出“如果某个 participant 决定了 Commit，那么 coordinator 也一定决定了 Commit”，不如追踪这个 participant 状态是怎么来的：某个 receive step 写入了这个 decision，这个 step 消耗了一条特定消息，而这条消息又一定来自某个更早的 sender step。只要把这些 provenance links 本身记录成不变量，全局性质就能通过链式推理得到。

这件事成立的关键，是 Basilisk 在一个 history-preserving 的模型上推理。一旦某个主机的 history 记录了某一步发送过某条消息，或某次状态更新曾经发生过，后续转移就无法抹掉这个事实。因此，每一条 provenance invariant 单独看都是归纳的。剩下的问题只在于如何自动找出合适的 provenance witness，而 atomic sharding 正是为此提出：如果一组变量总是被原子地一起更新，那么它们当前出现非初始值这一事实，就能证明一小组候选步骤中至少有一个曾经建立过这些值。

## 设计

Basilisk 引入了两种 provenance 形式。`Network-Provenance Invariant` 把异步网络中当前存在的一条消息，关联到某个可能发送它的 sender step。`Host-Provenance Invariant` 则把某个主机当前本地状态满足的性质，关联到某个必然让该性质从假变真的步骤。论文用 Two-Phase Commit 举例说明这些局部事实如何恢复跨主机推理：一个 participant 的 `Commit` 决策必然来自某条 `DECIDE(Commit)` 消息，而这条消息又必然出自 coordinator 某个发送步骤；该发送步骤执行时，coordinator 的本地状态已经是 `Commit`。

自动化机制是 atomic sharding。Basilisk 先估计每个协议步骤的 footprint，也就是该步骤可能修改的本地变量集合；然后对这些 footprint 做交集分析，计算 maximal atomic shards，也就是总是由同一组步骤一起更新的变量子集。对每个 shard，Basilisk 都会构造一个 provenance witness，大意是“这些变量现在正处于当前值，而且初始时不是这样”。据此，工具生成一个 host-provenance invariant，说明主机 history 里必然存在某个候选步骤把 witness 从假变成真。论文还专门为 set 和 map 这类 collection-valued state 做 refined shards，因为只用 maximal shard 容易把单个元素的 provenance 压扁掉。

整个工具链并不神秘，而是相当工程化。用户在 Dafny 中写出 host type、初始化条件、transition relation，以及 monotonic annotations。Basilisk 随后自动生成一个 history-preserving 的异步协议模型，网络允许消息 delay、drop、duplicate 和 reorder。基于这个模型，它合成 Regular Invariants：新提出的 provenance invariants，加上 Kondo 继承来的 monotonicity invariants 和 ownership invariants。同时，它还生成一份机械检查的证明，说明这些自动合成出来的不变量本身确实具有归纳性。论文中的 prototype 是在 Kondo / Dafny 4.2 代码库上扩展约 2,000 行 C# 实现的。

## 实验评估

这篇论文的评估重点不是运行时性能，而是验证方法是否真的减轻了人工证明负担。作者把 Basilisk 应用到 16 个分布式协议上，包括 Echo Server、多个 Paxos 变体、Raft leader election、Two-Phase Commit、Three-Phase Commit，以及 Multi-Paxos。最重要的结果是，16 个协议在 `User invs` 这一列全是 0，也就是说，Basilisk 在所有案例中都能找到足以完成证明的归纳不变量，而不需要用户手写任何 invariant clause。

与 Kondo 的对比支持了论文的核心论点：provenance 结构确实减少了人类去“发明”不变量的需求。以 Paxos 为例，Kondo 需要 20 条人工不变量，而 Basilisk 不需要任何一条。对 Multi-Paxos，Basilisk 同样不需要用户不变量；最终证明只用了 4 个 monotonic annotations、2 个 provenance hints，安全性证明部分 522 行，总计 565 行，Dafny 验证耗时 61.5 秒。放到全部评测里看，64 条 Host-Provenance Invariants 里只有 6 条需要用户额外提供 witness hint。

Basilisk 还改善了证明的人机工效。Flexible Paxos 在 Basilisk 中的安全性证明是 441 行，而 Kondo 是 559 行；验证时间则是 22.8 秒，对比 Kondo 的 49.4 秒。论文给出的解释是可信的：Basilisk 允许把“接收消息并据此发送响应”描述成一个原子步骤，因此协议模型更接近真实系统，步骤数更少；而且用户是直接针对异步模型写最终证明，而不是先写同步证明再做转换。

## 创新性与影响

相对于 _Zhang et al. (OSDI '24)_，Basilisk 把 Kondo 的 send / receive reasoning 推广成更一般的 provenance taxonomy，并自动化了更大一部分归纳不变量。相对于 _Hawblitzel et al. (SOSP '15)_，它保留了不可判定逻辑验证的表达能力，但去掉了大多数“人工搜索不变量”的工作。相对于 _Mora et al. (OOPSLA '23)_，它不是从执行轨迹里挖规格，而是直接从协议步骤的静态结构里推出关键事实。

这篇论文最可能影响的是那些在高表达力证明框架里验证协议的人。他们真正的瓶颈往往不是 theorem proving 本身，而是不知道该写什么 invariant。Basilisk 没有把最后一步完全自动化，但它把任务从“发明正确的不变量”收窄成“证明生成出的不变量足以推出安全性”，这已经是明显更可控的工作。

## 局限性

论文明确承认 Basilisk 并不完备。Atomic sharding 抓不住某些只在多个步骤共同作用下才隐式建立的关系，尤其是 epoch 切换时对 collection 的重置。在这类情况下，用户仍然需要补一个 provenance witness hint。生成不变量的强度也依赖 footprint 估计的精度；如果 footprint 过度近似，虽然不会出错，但会让推导出的不变量变弱。

它还存在建模和适用范围上的边界。当前 prototype 只接受受限的状态更新语法；如果一个步骤在不同条件下分别更新不同变量，用户需要先把它拆成多个独立步骤。更根本地说，Basilisk 面向的是 crash-fault-tolerant message-passing protocol 的 safety proof，不覆盖 liveness、Byzantine 场景，也不自动证明真实实现与模型一致。和所有定理证明结果一样，这些证明还依赖 Dafny 及其底层工具链本身的正确性。

## 相关工作

- _Zhang et al. (OSDI '24)_ — Kondo 提出了 Basilisk 所继承的不变量分类法，但仍要求开发者手写最困难的 protocol invariants。
- _Hawblitzel et al. (SOSP '15)_ — IronFleet 能在高表达力框架里验证实际分布式系统，但不变量的构造与证明组织仍主要压在用户身上。
- _Mora et al. (OOPSLA '23)_ — Message Chains 同样试图给分布式系统不变量提供结构，但它依赖执行轨迹上的 specification mining，而不是静态 provenance 分析。
- _Padon et al. (OOPSLA '17)_ — Paxos Made EPR 代表了相反的取舍：通过把协议压进可判定逻辑来换取更强自动化。

## 我的笔记

<!-- 留空；由人工补充 -->

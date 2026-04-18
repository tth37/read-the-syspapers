---
title: "Smart Casual Verification of the Confidential Consortium Framework"
oneline: "把 TLA+ 规范与 CCF 的 C++ 测试轨迹校验绑进 CI，让持续演进的 confidential-consortium 服务尽早发现细微协议 bug。"
authors:
  - "Heidi Howard"
  - "Markus A. Kuppe"
  - "Edward Ashton"
  - "Amaury Chamayou"
  - "Natacha Crooks"
affiliations:
  - "Azure Research, Microsoft"
  - "UC Berkeley"
conference: nsdi-2025
tags:
  - consensus
  - verification
  - formal-methods
  - confidential-computing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CCF 是一个生产级 confidential-computing 系统，它的协议和客户端语义已经偏离标准 Raft，普通测试很难覆盖关键角落。作者把 TLA+ 规范和面向生产 C++ 测试的轨迹校验结合起来，接入 CI，并借此在影响用户前发现了六个细微但真实的共识 bug。

## 问题背景

CCF 支撑 Azure Confidential Ledger，把 TEE、状态机复制和可审计日志结合在一起。它的共识协议已经偏离 vanilla Raft 到不能直接沿用既有证明的程度：论文点出的问题包括 signature transaction、单向消息而非 RPC、optimistic acknowledgement、快速 catch-up、`CheckQuorum`，以及带 retiring node 与 `ProposeVote` 的重配置逻辑。这类改动在代码里看起来像工程优化，但很容易引出安全性和活性上的细微角落。

客户端语义也不是标准 linearizability。为了缓解早期 SGX 的 enclave 内存压力，CCF 会在复制完成前先返回结果，因此客户端会看到 `Pending`、`Committed`、`Invalid` 三种状态。作者面对的真实问题是：如何在不重写一个 63 kLoC、还在每周快速演进的 C++ 系统的前提下，同时验证分布式安全性、正式写清客户端保证，并检查生产实现是否真的符合这些规范。

## 核心洞察

论文的核心观点是：工业团队没必要在“完整形式化证明”和“普通测试”之间二选一。更可行的路径，是把 TLA+ 当成协议的活文档，再用 trace validation 把它和真实实现绑起来。高层规范单独存在时，不能说明 C++ 代码真的符合模型；普通测试单独存在时，又很少在每个中间状态检查对的不变量。把两者接上以后，一条实现轨迹如果无法在高层模型里找到匹配行为，就意味着代码、日志或规范三者至少有一个有问题。

这就是作者所谓的 `smart casual verification`：形式化程度足以表达真正关键的分布式不变量，但又足够务实，能进入 CI 和日常调试流程，而不要求做一次完全验证过的新实现。

## 设计

整套方法有三部分。第一部分是 TLA+ 共识规范，用 17 个 action、13 个变量描述 CCF。核心检查包括 `LogInv`、`AppendOnlyProp` 和 `MonoLogInv`，并把真正影响正确性的 CCF 特性都纳入模型，例如重配置时的双 quorum、节点 retirement、消息丢失和若干协议优化。穷举 model checking 只在受限模型上跑，更大的空间依赖带权 simulation。

第二部分是客户端一致性规范。它刻意不再建模节点内部状态，而只保留两个变量：客户端可见事件序列 `history`，以及紧凑表示各 term leader 日志的 `logBranches`。这样就能直接表达 ancestor commit，以及后续只读事务是否必须观察到先前已提交写事务之类的性质。

第三部分是把规范绑到 C++ 实现上的 trace validation。团队扩展了 deterministic test driver，在无副作用的线性化点加入 15 个日志点，再构建一个复用高层 action 的 `Trace` 模型。对不齐的原子性粒度则用 TLA+ 的 action composition 处理，例如把 piggyback 在 `AppendEntries` 上的 term 更新合成到同一个高层步骤里。最后，他们用 DFS 而不是 BFS 做验证，因为只要在“trace 行为集合”和“规范行为集合”的交集中找到一条可行路径就够了。

## 实验评估

论文评估的重点不是性能，而是工程收益。共识主规范有 1,134 行，trace validation 层有 369 行；一致性主规范有 375 行，trace 层 111 行。一个非常实际的结果是：把 trace validation 从 BFS 改成 DFS 后，一致性检查从大约 1 小时降到不到 1 秒。

更重要的是 bug-finding 结果。整套流程在影响生产前发现了六个共识 bug：错误的选举 quorum 统计、允许 previous term 推进 commit、在 `AE-NACK` 上错误推进 commit、由过早 `AppendEntries` 触发的日志截断、不准确的 `AE-ACK`，以及过早 node retirement。第一个 bug 来自在 128 核机器上跑了 48 小时的 model checking；其他 bug 则来自 simulation 与规范-代码对齐过程。

一致性模型还给出一个关键语义结论：已提交的只读事务并不总是 linearizable。TLC 找到一个 12 步反例，说明它们在 CCF 里只能保证 serializability。整体而言，这些结果足以支撑论文“这种方法在工业里确实有价值”的主张，但证据仍然来自单一系统的深入 case study，而不是和其他工业验证流程的受控对比。

## 创新性与影响

这篇论文的新意不在于新的共识算法，而在于为已经部署的分布式系统给出一条可重复的验证流程。把抽象 TLA+ 模型和真实轨迹连起来以后，形式化方法就在“纯测试”和“完全验证重写”之间提供了一个现实可行的中间地带。这对正在交付 consensus-heavy 服务的工业团队，以及研究形式化方法如何面对实现漂移的研究者，都很有价值。

## 局限性

这不是端到端的完整形式化证明。状态空间需要强约束，trace 覆盖仍依赖场景与插桩质量，而共识部分的 trace validation 也花了约两个人月，并要求扩展 TLC 的 DFS、调试和 action composition 能力。作者还提到，Q-learning 对 simulation 的帮助不如手工加权。最后，客户端侧的保证仍弱于线性化只读。

## 相关工作

- _Hawblitzel et al. (SOSP '15)_ - IronFleet 证明分布式实现的端到端正确性，而这篇论文保留已有 C++ 系统，用较弱但更可部署的保证换取现实可用性。
- _Wilcox et al. (PLDI '15)_ - Verdi 用 Coq 构建已证明的容错系统；CCF 的重点则是持续验证一个已经在运行、并且还在快速演进的代码库。
- _Davis et al. (VLDB '20)_ - MongoDB 的 trace-validation 工作同样把实现轨迹与 TLA+ 模型对齐，而这篇论文更强调 action composition 和工业 CI 集成。
- _Bornholt et al. (SOSP '21)_ - Amazon 对 S3 的 lightweight verification 使用可执行 reference model；CCF 则用 TLA+ 来表达重配置、共识安全性以及客户端可见一致性。

## 我的笔记

<!-- 留空；由人工补充 -->

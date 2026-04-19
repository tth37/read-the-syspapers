---
title: "Achilles: Efficient TEE-Assisted BFT Consensus via Rollback Resilient Recovery"
oneline: "Achilles 把 TEE rollback 防护从提交热路径移到节点互助恢复里，让 TEE-assisted BFT 在保住 2f+1 容错的同时拿到线性消息复杂度和四步时延。"
authors:
  - "Jianyu Niu"
  - "Xiaoqing Wen"
  - "Guanlong Wu"
  - "Shenqi Liu"
  - "Jianshan Yu"
  - "Yinqian Zhang"
affiliations:
  - "SUSTech"
  - "University of British Columbia"
  - "The University of Sydney"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3717457"
code_url: "https://github.com/1wenwen1/Achilles"
tags:
  - consensus
  - fault-tolerance
  - confidential-computing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Achilles 的核心判断是，TEE 的 rollback 防护不该绑在每一次 proposal 和 vote 上。它把这件事挪到崩溃后的 peer-assisted recovery：节点从 `f+1` 个副本收集恢复回复，并要求当前 leader 提供最高 view 的那一份，然后只在更高 view 重新开口。再配合去掉 Damysus prepare phase 的 chained commit rules，Achilles 同时拿到 `n = 2f + 1`、`O(n)` 消息复杂度和四步端到端提交。

## 问题背景

TEE-assisted BFT 之所以诱人，是因为一旦 TEE 能阻止 equivocation，系统就有机会摆脱传统 BFT 只能容忍三分之一 Byzantine 节点的约束，把门槛推进到 `2f + 1`。真正卡住这条路的不是 non-equivocation，而是 rollback：恶意操作系统可以让 enclave 重启，再把旧 sealed state 喂回去，节点就可能复用旧计数器、发出冲突消息，最终破坏安全性。

问题在于现有 freshness 机制太贵。论文引用的 TPM counter 数据是一次递增大约 `97 ms`、一次读取大约 `35 ms`，根本不适合高性能共识热路径。软件式 persistent counter 如 ROTE、Narrator 虽然不依赖单颗硬件计数器，但本身也要跑分布式协议。于是 Damysus、OneShot 这类协议在 leader proposal、backup vote 时都得为 rollback prevention 付费；FlexiBFT 则通过把容错门槛放宽到 `3f + 1` 来减轻这件事。Achilles 想解决的正是这个矛盾：保住 `2f + 1`，同时把协议做得像优秀的 CFT 一样，既线性通信，又只需四步端到端提交。

## 核心洞察

Achilles 的核心洞察是：rollback 防护只需要在恢复时精确，不需要在每次提交时都同步完成。正常执行时，TEE 继续给 proposal 和 vote 签名，维持 non-equivocation；节点重启后，它也不需要把历史 enclave 状态逐帧回放，只需要恢复出当前安全 frontier，并确保自己不会在一个可能已经发过消息的 view 里再次开口。

这就是 peer-assisted recovery 成立的原因。其他副本已经持有足够的 block 和 certificate，能让 recovering node 推断自己必须继承的最新状态。Achilles 要求收集 `f+1` 份恢复回复，其中最高 view 的那份必须来自当前 leader；恢复完成后，节点直接跳到 `v' + 2`，而不是 `v' + 1`。这个保守跳转保证它不会在含糊不清的旧 view 里再次发消息，也就把 persistent counter 从高频热路径里拿掉了。

## 设计

Achilles 继续使用 Damysus 的 checker 和 accumulator，但 checker 现在记住的是最新被保存的 leader block，即使这个 block 还没 prepared；accumulator 仍然无状态，只负责证明 leader 在 `f+1` 个 new-view certificate 里，选中了 view 最高的 parent。

正常执行分 new-view、commit、decide 三步。副本先把自己最新保存的 block 发给 leader；leader 用 `TEEaccum` 选 parent，再用 `TEEprepare` 生成新区块；副本验证并存储后，通过 `TEEstore` 回传 store certificate。leader 收到 `f+1` 份 store certificate 后广播 commitment certificate，副本随即提交该 block 及其尚未提交的 ancestor，并直接向客户端回复。正因为 chain 上后代的提交会连带确认祖先，Achilles 才能删掉 Damysus 的 prepare phase，同时做到 `O(n)` 消息复杂度和四步端到端提交。若下一任 leader 已经拿到上一 view 的 commitment certificate，还能跳过常规的 new-view 等待。

恢复流程才是这篇论文最新的部分。节点重启后带着 nonce 向所有副本发 recovery request；其他副本返回自己保存的最新 block 状态和一份恢复证书。`TEErecover` 只接受 `f+1` 份回复，且要求当前 leader 的那份在集合中并且 view 最高；满足后，节点据此恢复 checker 状态，并把本地 view 前推两轮。accumulator 因为没有协议状态，所以不用恢复。

## 实验评估

原型基于 Intel SGX 和 Damysus 代码实现，实验跑在带 SGX 的公有云 8 vCPU、32 GB 虚拟机上，同时覆盖 `0.1 ms` RTT 左右的 LAN 和 `40 ms` RTT 的模拟 WAN，规模最高到 `f = 30`。

最关键的数据能直接支撑论文主张。在 LAN、`f = 30` 时，Achilles 达到 `75.38 KTPS`、`5.12 ms` 延迟；论文报告其吞吐分别是 Damysus-R 的 `17x`、FlexiBFT 的 `6x`、OneShot-R 的 `7x`。WAN 中网络时延会掩盖一部分热路径差异，但 Achilles 在 fault 数、payload 和 batch size 变化下，依然维持最好的吞吐和延迟前沿。

恢复没有把成本偷偷转移到别处。总恢复时间从 3 节点时的 `8.68 ms` 增长到 61 节点时的 `37.09 ms`，其中 recovery protocol 本身只占 `0.61 ms` 到 `12.31 ms`，其余主要是 SGX 与重连开销。作者还拿 Achilles-C 和 BRaft 做对照；在 LAN、`f = 10` 时，Achilles 为 `116.9 KTPS`，Achilles-C 为 `153.2 KTPS`，BRaft 为 `120.1 KTPS`。这说明 persistent counter 一旦离开热路径，剩下的 enclave 成本是可接受的。

## 创新性与影响

和 Damysus 相比，Achilles 改的是 trusted state 可恢复的边界，并借此删掉了一个完整阶段。和 FlexiBFT 相比，它没有用 `3f + 1` 的更弱模型去交换性能。和 OneShot 相比，它把四步提交和 rollback resilience 放进了同一套协议，而不是只在有利执行里才接近这个目标。

更重要的影响是观念上的：TEE-assisted BFT 不一定要在性能和强容错之间二选一，只要把 rollback defense 看成 recovery-time 问题，而不是每条消息都要同步完成的义务。

## 局限性

Achilles 假设固定成员、不超过 `f` 个节点同时重启，并默认 TEE forking 由外部机制处理。恢复还依赖当前 leader 那份最高 view 回复，所以一旦 leader 自己不可用，进展就会被拖慢。实现上它也延续了 Damysus 的 chain 结构，没有覆盖 dynamic reconfiguration 或更激进的并行共识设计。

## 相关工作

- _Decouchant et al. (EuroSys '22)_ - Damysus 已经把 checker 和 accumulator 用进 chained TEE-assisted BFT，但仍保留 prepare phase，也没有把 rollback-resilient recovery 做进协议。
- _Decouchant et al. (IPDPS '24)_ - OneShot 通过 view-adapting 把一部分常见执行压到四步；Achilles 则把四步提交和 rollback resilience 一起做成协议的默认能力。
- _Gupta et al. (EuroSys '23)_ - FlexiBFT 用 `3f + 1` 的更弱容错换取更少的 TEE 热路径访问；Achilles 解决的是同一个瓶颈，但坚持保留 `2f + 1`。
- _Yin et al. (PODC '19)_ - HotStuff 提供了 chaining 和 linearity 的结构基础，但不处理 TEE non-equivocation，也不处理 rollback recovery。

## 我的笔记

<!-- 留空；由人工补充 -->

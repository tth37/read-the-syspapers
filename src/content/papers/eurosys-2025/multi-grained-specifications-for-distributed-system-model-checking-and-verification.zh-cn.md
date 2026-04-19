---
title: "Multi-Grained Specifications for Distributed System Model Checking and Verification"
oneline: "Remix 只把待验证的 ZooKeeper phase 写细、其余 phase 保留交互边界，因此能在秒级抓到六个深层复制错误。"
authors:
  - "Lingzhi Ouyang"
  - "Xudong Sun"
  - "Ruize Tang"
  - "Yu Huang"
  - "Madhav Jivrajani"
  - "Xiaoxing Ma"
  - "Tianyin Xu"
affiliations:
  - "SKL for Novel Soft. Tech., Nanjing University, China"
  - "University of Illinois Urbana-Champaign, IL, USA"
conference: eurosys-2025
category: reliability-and-formal-methods
doi_url: "https://doi.org/10.1145/3689031.3696069"
project_url: "https://zenodo.org/records/13738672"
tags:
  - formal-methods
  - verification
  - consensus
  - fault-tolerance
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Remix 的做法是按 Zab phase 给 ZooKeeper 写多套不同粒度的 TLA+ 规格。验证某个模块时，只把它写细，把其余模块按保留交互边界的方式写粗，再用 deterministic conformance checking 把模型钉回 Java 实现，于是既能抓到深层 bug，也不会把整系统状态空间一起拖爆。

## 问题背景

ZooKeeper 已经有协议级和系统级 TLA+ 规格，但它们没有覆盖实现里最容易出错的地方。论文把这些 model-code gap 概括成三类：TLA+ 里是原子动作，代码里却分步执行；模型把节点内并发压成单一步骤；以及为了简化而省掉的状态转移。对 ZooKeeper 而言，这些问题集中出现在 synchronization 和 log replication，尤其是 `NEWLEADER`、异步日志和恢复逻辑交错的路径上。

如果规格继续写粗，这些 interleavings 永远不会出现；如果整系统都按代码粒度写细，TLC 又根本跑不动。论文给出的数据是，官方 system specification 在 3 节点、3 事务、最多 3 次 crash 和 3 次 partition 的配置下，10 天都跑不完，而且那份模型还没把所有本地并发都放进去。真正的问题因此不是单纯追求精细或可扩展，而是怎样只在目标模块上支付精细建模的成本。

## 核心洞察

作者最核心的判断是：规格粒度应当按模块来选，而不是全局统一。只要待验证模块用 fine-grained specification，周边模块按 interaction-preserving 的方式 coarsen，目标模块能观察到的相关行为就不会丢，但状态空间会小得多。

Zab 的 phase 结构让这件事变得可操作。Election、Discovery、Synchronization、Broadcast 本来就边界较清晰，所以每个 phase 都可以同时有 coarse-grained 和 fine-grained 版本，随后再根据验证协议、验证实现还是验证 bug fix 来混搭。

## 设计

在 fine-grained 这边，Remix 会把误导性的原子 action 改写成更像代码执行路径的多个 actions，并显式建模线程间通信。论文最重要的例子是 follower 处理 `NEWLEADER`：原模型里像一步，代码里却拆成 epoch 更新、把请求放进异步日志队列、回复 leader，以及由日志线程执行的 `FollowerSyncProcessorLogRequest`。这些 enabling conditions 都按 Java 代码重写，因此 TLC 才能真正探索中间状态和本地线程交错。

在 coarse-grained 这边，原则是只保留其他模块看得见的东西。论文用 dependency variables 和 interaction variables 来刻画这一点。比如 Election 和 Discovery 可以被压成一个 `ElectionAndDiscovery` action，只要节点角色、`zabState` 等对外可见更新保持语义不变。作者还给出一个 interaction-preservation theorem，说明从目标模块投影出去看，coarsened system 和原 system 的 traces 是一致的。

组合方式仍然是 TLA+ 的标准套路：整体 `Next` 是所选 phase actions 加上 crash 等 fault actions 的析取。Remix 在外层补上工具链，负责组合模块版本、检查 invariants，并把模型里采样出来的 traces 通过 coordinator 驱动的 AspectJ/RMI instrumentation 在 ZooKeeper 中做 deterministic replay。

## 实验评估

结果上，Remix 在 ZooKeeper v3.9.1 上抓到 6 个严重 bug，后果包括 data loss、data inconsistency 和 data synchronization failure。它们都不是浅层路径：第一次 violation 出现前通常已经走了 12 到 21 个 state transitions，并探索了约 1.4 万到 288 万个 states。作者再用 deterministic replay 在 Java 实现里把这些行为复现出来，确认不是模型假阳性。

效率对比更有说服力。bug 检测表里，6 个 bug 全都在 2 分钟内被找到，其中好几个只要 10 到 20 秒。更系统的实验里，baseline system specification 和完全细化的 `mSpec-4` 在 24 小时内都跑不完，因为 TLC 大部分时间都耗在 leader election。把 Election 和 Discovery coarsen 后，mixed-grained 规格才真正变得实用：`mSpec-2` 在 1 分 15 秒发现第一个 violation，`mSpec-3` 只要 11 秒，而 `mSpec-4` 要 8 小时 32 分钟。论文还给出大约 40 person-hours 的额外建模与 instrumentation 成本，对关键基础设施来说算是能接受的工程投入。

这里的负载是三节点、有限事务数、有限 crash 与 partition 的 model-checking 配置，而不是生产流量。但这正对齐论文的目标：它要证明的是 implementation verification 可行，而不是 ZooKeeper 的运行时性能更好。

## 创新性与影响

这篇论文的创新，不是新的 proof engine，而是一套适用于现有系统的工作流：按协议 phase 写多粒度 TLA+ 规格，按任务组合，再用 deterministic replay 持续对齐代码。这样一来，TLA+ 就不只是设计文档，而开始直接参与实现级 bug 定位和 fix 验证。

它的影响也很具体。ZooKeeper 的实现早已因优化而偏离原始协议描述，作者证明正式方法在这种场景里依然有用，而且验证过程还反过来推动他们修改 Zab，要求 history update 先于 epoch update，让协议本身更容易被正确实现。

## 局限性

作者也明确说明了边界。conformance checking 是 unsound 的，如果实现存在模型没写出的行为，而采样 traces 又没覆盖到，Remix 就可能漏报。它目前只检查 safety，不碰 liveness，而且仍然需要手工决定粒度、补写模块版本、以及维护 model action 到代码事件的映射。

另外，ZooKeeper 是个相对友好的案例，因为 Zab 天然就分成四个清晰的 phases。若系统跨模块耦合更乱，coarsen 其他模块会困难得多。论文对方法通用性的论证主要来自结构分析，而不是跨多个代码库的实证。

## 相关工作

- _Newcombe et al. (CACM '15)_ - AWS 展示了 formal methods 如何帮助系统设计收敛，而这篇论文进一步把 TLA+ 推到实现级验证，直接对付已经演化多年的生产代码。
- _Gu et al. (SRDS '22)_ - 该文用 interaction-preserving abstraction 做 consensus protocols 的组合式验证；本篇借用了 interaction 的思路，但 coarsening 的目标是加速非目标模块，而不是建立 refinement 关系。
- _Tang et al. (EuroSys '24)_ - SandTable 同样把 TLA+ model checking 和 conformance checking 接在一起；Remix 的区别在于多粒度规格组合，以及对 user-level thread interleaving 的显式控制。
- _Yang et al. (NSDI '09)_ - MODIST 直接在未修改实现上做 model checking；Remix 则把大部分搜索留在模型层，只在确认与调试时回到代码里做 deterministic replay。

## 我的笔记

<!-- 留空；由人工补充 -->

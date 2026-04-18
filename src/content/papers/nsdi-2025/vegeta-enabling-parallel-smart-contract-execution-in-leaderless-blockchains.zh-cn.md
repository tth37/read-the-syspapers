---
title: "Vegeta: Enabling Parallel Smart Contract Execution in Leaderless Blockchains"
oneline: "Vegeta 在 leaderless consensus 之前先推测执行区块以提取依赖，再做确定性 replay，并把必要的 re-execution 控制到很低。"
authors:
  - "Tianjing Xu"
  - "Yongqi Zhong"
  - "Yiming Zhang"
  - "Ruofan Xiong"
  - "Jingjing Zhang"
  - "Guangtao Xue"
  - "Shengyun Liu"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Shanghai Key Laboratory of Trusted Data Circulation, Governance and Web3"
  - "Xiamen University"
  - "Fudan University"
conference: nsdi-2025
category: consensus-and-blockchain
code_url: "https://github.com/Decentralized-Computing-Lab/Vegeta"
tags:
  - consensus
  - transactions
  - fault-tolerance
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Vegeta 是一个面向 leaderless BFT blockchain 的 smart contract 并发控制协议。每个 proposer 在 consensus 之前先对自己负责的区块做 speculative execution，提取 read/write set 与依赖关系；随后所有节点按照共识确定的顺序做确定性 replay，只对那些实际访问集合推翻推测结果的交易做 re-execution。这样一来，leaderless consensus 不再只是执行层的麻烦来源，反而成了分摊前置分析工作的手段：单机最高 7.8x，加上 10 个节点的共识后仍有 6.9x speedup。

## 问题背景

现代 BFT consensus 已经能把交易排序做到远高于串行 smart-contract executor 的速度，但执行层仍然卡住整条链。论文直接指出，以 Ethereum 的串行执行引擎为例，吞吐大约只有 100 TPS，因此真正的瓶颈已经从 ordering 转移到 execution。问题在于，blockchain 的并行执行并不是一个脱离 consensus 就能单独优化的模块。

这正是现有两类框架都不够贴合 leaderless 场景的原因。`order-execute` 先共识后执行，任何共识协议都能接，但所有节点都得在共识后重新执行每个区块，而且为了保证结果一致，还得接受很多本可避免的顺序约束。`execute-order-validate` 则把更多工作前移到共识前，但现有方案通常假设存在一个知道完整先行上下文的 leader，或者在发现新增冲突时回到昂贵的 abort-and-retry 路线。

Ethereum 风格的 smart contract 让问题更难，因为它们往往是 dependent transactions：真正访问哪些地址与存储 key，要等交易跑起来才知道。论文用 Uniswap 交易举例说明，一个 swap 可能经由多个合约递归调用，中间资产和实际触碰的 key 只能在执行中暴露出来。所以系统需要一种方法，既能利用多核并发，又能容忍 pre-consensus 执行上下文并不准确，还能保证所有副本最终得到同一个 serializable 结果。

## 核心洞察

论文最重要的判断是：在 leaderless blockchain 里，speculative execution 即使得不到可信的最终值，仍然非常有价值。由于多个 proposer 会并发地产生 proposal，任何一个 proposer 在共识前都拿不到所谓的 perfect context，也就不可能保证“基于当前状态算出来的结果”是正确的。但它往往仍能较准确地暴露交易的 read/write set 和依赖结构，而这些信息已经足够指导后续高效 replay。

因此，Vegeta 把 speculation 定位成 conflict oracle，而不是 tentative result。真正贵的是每个节点都必须做的 post-consensus replay，所以只要 pre-consensus 的额外工作能换来更轻的 replay，它就是值得的。这也是 speculate-order-replay 的基本思想：让所有 proposer 分散做 speculative analysis，通过 consensus 固化这份调度信息，然后只对 speculation 没有看准的部分做确定性修补。

## 设计

Vegeta 在 transaction 粒度上实现 speculate-order-replay。进入 speculation phase 后，proposer 会把一个区块中的所有交易在本地快照上完全并行执行，但不会让这些执行真正更新共享状态。它信任的只有每笔交易暴露出来的 read set 和 write set。拿到这些访问集合后，Vegeta 会按 key 把交易归入 dependency chain，再按链长度从长到短排序，并据此重排区块中的交易顺序。这个策略很务实：长链决定了关键路径，所以应该优先启动长链上的交易。

在完成重排后，proposer 会为整个区块构造一个 DAG，记录交易之间的 `WAW`、`WAR`、`RAW` 依赖。如果两笔交易之间存在多种冲突，Vegeta 优先把它们标成 `WAW`；如果它们在不同 key 上同时形成 `WAR` 和 `RAW`，论文也保守地把它们视作 `WAW`。随后 proposer 把重排后的 block、每笔交易的 read/write set，以及这个 DAG 一起交给 consensus。

Replay 发生在 consensus 之后。所有节点拿到同一个区块后，会反复取出一个 ready batch：这些交易不能依赖尚未完成的 `WAW` 前驱，也不能同时对尚未完成的前驱既有 `WAR` 又有 `RAW` 依赖。batch 内交易可以并行执行，但写入在整批都跑完之前都不会对外可见。这样，系统不需要 multi-version store，也不需要 rollback machinery，仍能保持等价于某个串行顺序的执行结果。

真正微妙的地方在于如何处理 speculation 出错。基础算法里，只要某笔交易在 replay 时得到的 read/write set 与推测阶段不同，就先把它从当前 batch 里拿掉，最后按串行顺序重新执行。Algorithm 3 进一步降低了这类 re-execution。若交易新访问的 key 在 speculation 阶段已经被别的交易碰过，那它很可能引入新的依赖，必须重跑；若它只是读取了一个此前没人访问过的新 key，则可以先等 batch 结束，只有当其他交易新写入了这个 key 才需要再执行；若它写入的是此前没人碰过的新 key，则 writer 本身可以先提交，只需要把这个 key 记录下来并让后续 reader 必要时补跑。也就是说，Vegeta 尽量只为“真的产生了新依赖”的情况付出串行回退代价。

实现上，作者用 Go 在 Geth 的 EVM 之上实现了 Vegeta。世界状态仍然缓存在 `StateDB` 中，但为了支持并发访问，他们用 `sync.Map` 改造了共享访问方式，并为每笔交易启动一个新的 EVM 实例。多节点实验里，他们把 Vegeta 接到 BKR 这个 leaderless consensus 上，让区块 `B_h` 由节点 `h mod n` 负责 speculation；同时设置 `K = 2`，保证 replay 积压不超过两块时就开始新一轮 speculation。

## 实验评估

实验使用真实 Ethereum blocks，在 Amazon EC2 `m6i.4xlarge` 上运行，每台机器 16 vCPU、64 GB RAM，规模最多到 10 个节点。最有说服力的 correctness 证据不是形式化证明，而是工程验证：作者对 5,000 个区块、739,863 笔交易重复处理了 100 次，每个区块最终都得到完全一致的 Merkle Patricia Trie root。

单机实验先拿 101 个区块、15,129 笔交易测各阶段耗时，并在基于最新 world state 的情况下观察到只有 1.47% 的 re-execution rate。Speculation 本身比 replay 更贵，因为它还要做重排和 DAG 构建，但 replay 加 re-execution 的总开销仍明显低于串行执行。在两组各 5,000 个区块的大数据集上，Vegeta 相对串行执行分别达到 7.8x 和 7.7x speedup，已经接近 Table 2 里由最长 dependency chain 给出的上界。

与 AriaFB 的对比更能体现 Vegeta 的价值。AriaFB 把每个区块当成一个 batch 并行执行，只要某笔交易存在 forward dependency 就 abort，然后再借用 Vegeta 的 replay 作为 fallback。这样一来，两组主数据集里分别有 40.2% 和 42.3% 的交易被 abort 并送去回退路径，最终 speedup 只有 3.8x 和 3.6x。Vegeta 的优势并不是放松 correctness，而是靠 pre-consensus 的依赖识别与重排，把 replay 的冲突密度先降下来。

多节点结果则支撑了论文最核心的系统论点。即使把 consensus 集成进去，re-execution rate 仍然低于 2%：S2 数据集在 4 节点和 10 节点下分别是 1.66% 和 1.89%，S4 则分别是 1.58% 和 1.82%。在 10 节点部署中，Vegeta 仍能达到 6.9x speedup。作者还把底层共识替换成 leader-based 的 PBFT，对照发现单个 leader 很快成为 speculation bottleneck，吞吐明显下降，这正说明 Vegeta 的收益依赖于 leaderless consensus 把前置工作分摊到所有节点。

## 创新性与影响

Vegeta 的新意不在于单独提出一种新的 conflict detector，也不只是“再做一个并行 EVM”。它真正重要的地方在于，把 execution layer 和 leaderless consensus 明确地联动设计。与 `Block-STM` 这类 order-execute 系统相比，Vegeta 把有价值的依赖发现工作移到了 ordering 之前，而不是让每个节点在共识后再重复摸索调度。与 `Hyperledger Fabric` 式的 execute-order-validate 相比，Vegeta 不把 speculative output 当作候选结果去信任，也不让冲突交易把整条 pipeline 再走一遍。与 `Forerunner` 这类更偏 leader 语境的 speculative execution 相比，Vegeta 从一开始就接受“任何 proposer 都没有 perfect context”这个现实，并把 replay 而不是 speculation 作为 correctness anchor。

因此，这篇论文为 DAG-BFT、asynchronous BFT 以及其他 leaderless blockchain 给出了一个很清晰的 execution design point：既然 ordering 已经去中心化，那么 pre-processing 也应该一起去中心化，而不是还把分析工作塞回 leader。后续 blockchain execution 论文很可能会把它当成这一设计路线上的代表作来引用。

## 局限性

这篇论文更像 execution engine 的性能研究，而不是完整区块链节点的端到端评测。作者在性能实验里通常关闭 persistence，也跳过了大多数 MPT 更新，因此文中的 speedup 更接近“执行层理论收益上界”，而不是 full node 的最终吞吐。多节点实验也只做到 10 个节点，因为输入 Ethereum blocks 本身是按顺序生成的，这让更大规模下的外推空间有限。

设计本身也明显受 workload 结构影响。长 dependency chain 会直接压低并行度，论文点名指出 WETH 相关应用是其数据集中最长链的重要来源。Vegeta 的 speculation 也只是近似分析：dependency chain 是按 key 聚合出来的，而不是一次精确的全局依赖求解，所以 replay 末尾仍需要 cleanup 式的 re-execution。若 speculative context 过旧，re-execution rate 会抬升，speedup 也会随之下降。

最后，proposer 可以自由重排交易这一点，在真实 DeFi 环境里会和公平性、MEV 收益发生直接冲突。论文也坦率承认，miner 或 proposer 可能更愿意做 frontrunning 或 sandwich attack，而不是最大化并行度。此外，Byzantine 节点虽然破坏不了 Vegeta 的 safety，但完全可以通过伪造空的 read/write set 或错误依赖来显著拖慢系统。所以这篇论文把“如何高效执行”回答得很清楚，但对 fairness、incentive 与 adversarial efficiency 的回答还不完整。

## 相关工作

- _Chen et al. (SOSP '21)_ - `Forerunner` 通过 speculative execution 暴露 Ethereum 交易约束，但它并不是围绕 leaderless BFT consensus 设计的，也没有正面处理 perfect context 缺失的问题。
- _Lu et al. (VLDB '20)_ - `Aria` 是 Vegeta 借鉴 replay 思路的确定性 OLTP 工作，而 Vegeta 增加了 pre-consensus speculation，用来降低 blockchain workload 下的 abort 与 re-execution。
- _Gelashvili et al. (PPoPP '23)_ - `Block-STM` 在 ordering 之后挖掘并行性，而 Vegeta 把依赖发现前移到 leaderless consensus 之前，从而减轻后续 replay 负担。
- _Androulaki et al. (EuroSys '18)_ - `Hyperledger Fabric` 采用 execute-order-validate，冲突交易可能重新走更重的流程；Vegeta 则把 speculative output 仅作为辅助信息，只修补 replay 调度。

## 我的笔记

<!-- 留空；由人工补充 -->

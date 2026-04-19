---
title: "ParallelEVM: Operation-Level Concurrent Transaction Execution for EVM-Compatible Blockchains"
oneline: "ParallelEVM 把 EVM 执行动态记成 SSA operation log，在乐观并发失败后只重做受冲突影响的指令，把真实以太坊区块的平均加速比从 OCC 的 2.49x 提到 4.28x。"
authors:
  - "Haoran Lin"
  - "Hang Feng"
  - "Yajin Zhou"
  - "Lei Wu"
affiliations:
  - "Zhejiang University"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3696063"
tags:
  - transactions
  - scheduling
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ParallelEVM 没有放弃乐观并发，而是把验证失败后的处理粒度从整笔交易缩到指令。它在执行时动态生成一份 SSA operation log，定位真正依赖冲突槽位的 EVM 指令，只重做那一小段；在真实 Ethereum 区块上，平均加速比从 OCC 的 2.49x 提到 4.28x。

## 问题背景

共识层更快，并不等于执行层就够快。论文先说明为什么区块链并发执行在真实负载下很难做：从 2022 年 1 月 1 日到 7 月 1 日，1000 万个合约里只有 0.1% 吃掉了 76% 的调用次数，2 亿个 storage slot 里也只有 0.1% 承担了 62% 的访问次数。最热的那批合约大多还是 ERC20，于是转账会不断在同一个发送方余额和 allowance 上正面相撞。

问题在于，现有并发控制还是按 transaction 处理冲突。两笔 `transferFrom` 只要都碰到 `balances[A]`，2PL、OCC、Block-STM 这类方案就会把整笔交易阻塞或重跑，哪怕 `balances[B]`、`balances[C]` 的更新其实没有被冲突污染。在最需要并行性的热点场景里，这种粒度会把大量本可保留的工作一起扔掉。

## 核心洞察

这篇论文最值得记住的一点是：真实区块链冲突往往比整笔交易窄得多。只要运行时能把 EVM 指令之间的数据依赖显式化，验证失败就不必自动等同于整笔重跑。系统可以把出错的 `SLOAD` 结果替换成已提交值，再沿着 definition-use chain 往后追，只重做真正依赖这份旧值的那部分指令。ParallelEVM 的 SSA operation log 同时还带着一组 guard，用来检查这种局部 repair 会不会改变控制流、运行时地址或 gas 行为。

## 设计

ParallelEVM 在 OCC 之上拆出了四个阶段：read、validation、redo、write。read phase 里，交易先并发投机执行，同时记录 read/write set，并在线生成 SSA operation log。每条 log entry 都显式保存 opcode、operands、result，以及这些输入在 stack、storage、memory 上各自来自哪里。shadow stack 负责 `def.stack`；`latest_writes` 和 `direct_reads` 用来区分事务内写后的读取与直接依赖已提交状态的 `SLOAD`；shadow memory 则给每个字节打上 `<LSN, offset>`，让交叠的 `MSTORE`、`MSTORE8` 依赖关系也能被还原出来。

validation phase 基本沿用 OCC：交易按区块顺序等待前序交易提交，然后重新检查 read set；一旦失败，系统就拿到冲突 slot 以及它们的正确已提交值。redo phase 才是全文的新意。ParallelEVM 先靠 `direct_reads` 找到那些直接读到冲突 slot 的 `SLOAD`，把这些 entry 的 result 改成正确值；接着在 definition-use graph 上做 DFS，把所有受其影响的后继指令找出来，再根据 log 里记下的定义信息重建输入，只重做这一小段。

局部修复能否继续走下去，要看 `ASSERT_EQ` 这类 guard。论文会为控制流判断、非常量运行时地址，以及 `SSTORE` 这类 dynamic-gas 指令插入检查。只要 repair 让分支目标、地址计算或 gas 成本发生变化，redo 就立即失败，事务退回 write phase 里走普通的 abort-and-restart。ParallelEVM 并没有放松 Ethereum 语义，只是把真正必须整笔重跑的范围缩小。

## 实验评估

原型基于 Go Ethereum v1.10.17，实现改动大约 4200 行代码。实验机器是 8 核 16 线程 CPU、16 GB 内存，负载选的是 Ethereum 主网 14,000,000 到 15,000,000 号区块，并把 2PL、OCC、Block-STM 也接进同一套 Geth 里做对比。

最核心的结果很直接：ParallelEVM 相对 baseline Geth 的平均加速比是 4.28x，而 2PL 是 1.26x，OCC 是 2.49x，Block-STM 是 2.82x。大多数区块落在 2-7x 这段；只有 0.88% 的区块比串行更慢，主要是少数耗时很长的交易在 redo 里失败，最后还是付了完整回滚重跑的代价。作者对 Block-STM 落后的解释是，真实 Ethereum 热点会把 transaction-level 的依赖链拉得很长，所以整笔重启的方案会留下更多没法利用的并行度。

支撑这些结论的细节也比较到位。正确性方面，作者让 ParallelEVM 处理了前 1400 万个 Ethereum 区块，每次都得到与主网一致的 Merkle Patricia Trie root。开销方面，SSA 日志生成在无冲突场景下平均只多出 4.5% 的每事务运行时成本；一次真实合约调用平均有 2559 条 EVM 指令，但对应的 SSA log 平均只有 127 条，约为原始轨迹的 5.0%。redo 阶段平均只会重做 7 条 log entry，也就是原始指令数的 0.3%；redo 时间只占整个区块处理时间的 4.9%，而且 87% 的冲突事务都能在这里被修复成功。内存从原版 Geth 的 9.08 GB 增到 9.48 GB，增幅 4.41%。再叠加 state prefetching，平均加速比能到 7.11x；模拟 pre-execution 时则能到 8.81x。整体看下来，实验确实支持作者的核心论点：真正需要重做的那一小段通常很短。

## 创新性与影响

这篇论文的创新点，不是把区块链调度器再调快一点，而是把 partial repair 这类思路真正落到 EVM 执行层，而且不要求事先知道 transaction 的程序结构。ParallelEVM 在运行时从 bytecode 执行过程里动态长出一张 operation-level 依赖图，这让它面对 ERC20 式热点冲突时，比传统 transaction-level 并发控制多拿到一截可用并行度。对 EVM-compatible 链来说，这个方向很有现实价值。

## 局限性

论文的野心比证据范围更大。实现和测量都只落在 Ethereum 和单一客户端上，作者声称这套方法也适用于其他 account-based、stack-machine 区块链，但文中并没有直接展示。另一个现实问题是，仍有不到 1% 的区块会输给串行执行，而作者自己提出的改进方向是让 miner 或 proposer 预先生成更好的 operation-level schedule，再随区块一起下发，这部分还没有做出来。更根本地说，只要冲突会改变控制流、运行时地址或 dynamic gas 行为，guard 就会把事务打回完整重跑，因此收益依然依赖于冲突保持在语义上局部可修复的范围内。

## 相关工作

- _Chen et al. (SOSP '21)_ - Forerunner 依赖约束来提前推测 Ethereum 交易，而 ParallelEVM 是在乐观执行后修复已经暴露出来的冲突，并且同样可以从 speculative pre-execution 里受益。
- _Garamvölgyi et al. (ICSE '22)_ - OCC-DA 试图让智能合约上的 OCC 更适应高冲突场景，但处理单位仍然是整笔交易；ParallelEVM 保留乐观执行框架，只把重做粒度改成了 operation。
- _Gelashvili et al. (PPoPP '23)_ - Block-STM 在执行与验证协同上做得很强，但一旦冲突发生，仍然要阻塞或重启整笔事务；ParallelEVM 则只重做受影响的那段指令链。
- _Dashti et al. (SIGMOD '17)_ - MV3C 也会借助依赖图做部分重执行，不过它默认事先知道 transaction 结构；ParallelEVM 的特点是把这张图从 EVM 运行时里动态恢复出来。

## 我的笔记

<!-- 留空；由人工补充 -->

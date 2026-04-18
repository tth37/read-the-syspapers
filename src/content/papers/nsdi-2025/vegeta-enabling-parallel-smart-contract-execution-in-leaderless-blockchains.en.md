---
title: "Vegeta: Enabling Parallel Smart Contract Execution in Leaderless Blockchains"
oneline: "Vegeta speculates on blocks before leaderless consensus to recover dependencies, then deterministically replays them with limited re-execution for up to 7.8x speedup."
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

Vegeta is a concurrency-control protocol for smart contracts on leaderless BFT blockchains. Each proposer speculatively executes its own block before consensus to infer read/write sets and dependencies, then every node deterministically replays the agreed schedule and only re-executes transactions whose actual accesses invalidate the speculation. The design turns leaderless consensus from a scheduling obstacle into a way to distribute pre-consensus work, reaching up to 7.8x single-node speedup and 6.9x speedup in a 10-node deployment.

## Problem

Modern BFT consensus protocols can already order transactions at a rate far above what a serial smart-contract executor can sustain. The paper cites Ethereum's execution engine as around 100 TPS, so execution, not ordering, is the bottleneck. Adding parallelism sounds straightforward, but blockchain execution is tightly coupled to consensus semantics: if the scheduler assumes a proposer knows the final preceding state, that assumption breaks once multiple proposers race in a leaderless protocol.

That mismatch makes the two standard execution frameworks awkward. In order-execute systems, all nodes wait until after consensus, then deterministically execute every committed block themselves. This is easy to plug into any consensus protocol, but it leaves too much work on the universal post-consensus path and imposes unnecessary ordering constraints. Execute-order-validate systems push work before consensus, but existing versions either assume a single leader with a perfect view of prior proposals or fall back to expensive abort-and-retry behavior when new conflicts appear.

Ethereum-style smart contracts make the problem harder because transactions are often dependent transactions: the accessed addresses and storage keys are not fully known until the transaction runs. The paper's Uniswap example shows why. A token swap may recurse through several contracts and only discover intermediate assets and touched keys during execution. So the system needs a way to exploit parallel hardware, tolerate inaccurate speculative context, and still produce the same serializable result at every replica.

## Key Insight

The paper's core claim is that, in a leaderless blockchain, speculative execution is still valuable even when its output values are not trustworthy. A proposer lacks a "perfect context" because concurrent proposals from other nodes have not yet been ordered, so pre-consensus execution may see stale state and produce wrong results. But the read/write sets and dependency structure it uncovers are often accurate enough to guide a later deterministic replay.

Vegeta therefore uses speculation as a conflict oracle rather than as a tentative commit result. The expensive part that every node must do is replay after consensus, so the system should spend more effort in the per-proposer pre-consensus phase if that shrinks replay cost. This is the broader speculate-order-replay idea: distribute speculative analysis across all proposers, agree on the resulting schedule, then replay only what the speculation could not predict correctly.

## Design

Vegeta instantiates speculate-order-replay at transaction granularity. In the speculation phase, a proposer executes every transaction in a block fully in parallel against its local snapshot, but does not let those executions update shared state. The only outputs it trusts are each transaction's read set and write set. From those accesses, it groups transactions into per-key dependency chains, sorts chains from longest to shortest, and reorders the block so transactions on longer chains start earlier. The point is pragmatic: long chains dominate the critical path, so prioritizing them increases the eventual degree of parallelism.

After reordering, the proposer builds a dependency DAG for the block. Edges record `WAW`, `WAR`, and `RAW` relationships between earlier and later transactions. If a pair exhibits multiple conflicts, Vegeta gives priority to `WAW`, and if both `WAR` and `RAW` exist across different keys it conservatively treats the pair as `WAW`. The proposer then submits the block, the per-transaction read/write sets, and the DAG to consensus.

Replay happens after consensus totally orders proposals. Every node processes the same block and repeatedly extracts a batch of transactions with no forward dependency according to Rule 2: a transaction cannot have an unfinished `WAW` predecessor, and it cannot simultaneously have `WAR` and `RAW` dependencies on unfinished predecessors. Transactions in the batch execute in parallel, but their writes become visible only after the whole batch finishes. This preserves a serializable interpretation without a multi-version store or rollback machinery.

The subtle part is handling speculation mistakes. In the basic algorithm, if a transaction's actual read/write set differs from the speculative one, Vegeta removes it from the current batch and re-executes it later in serial order. Algorithm 3 reduces that rate. Accessing a new key that was already touched by some speculative transaction is treated as dangerous and forces re-execution. Reading a wholly new key is weaker: the transaction can wait until the batch ends, and only if some other transaction newly writes that key does it need another execution. Writing a wholly new key is weaker still: the system records the key, commits the writer with the batch, and only replays readers that now conflict with it. The effect is to reserve serial fallback for changes that actually create new dependencies.

Implementation-wise, the prototype is in Go on top of Geth's EVM. The authors keep `StateDB` as the in-memory world-state cache, modify it for shared concurrent access with `sync.Map`, start a fresh EVM instance per transaction, and intentionally omit persistence from performance measurements. For multi-node experiments they integrate Vegeta with BKR, assign block `B_h` to node `h mod n` for speculation, and start new speculation when at most `K = 2` blocks remain to replay.

## Evaluation

The evaluation uses real Ethereum blocks on Amazon EC2 `m6i.4xlarge` instances with 16 vCPUs and 64 GB RAM, scaling to 10 nodes. The strongest correctness check is operational rather than formal: over 5,000 blocks and 739,863 transactions, repeated 100 times, Vegeta always reproduced the same Merkle Patricia Trie root for every block.

On a single node, the paper first measures a 101-block run with 15,129 transactions and finds only a 1.47% re-execution rate when speculation uses the latest world state. Speculation itself is costlier than replay because it must build dependency chains and the DAG, but replay plus re-execution is still far cheaper than serial execution. On the larger 5,000-block datasets, Vegeta reaches 7.8x and 7.7x speedup over serial execution, close to the workloads' dependency-chain upper bounds in Table 2.

The comparison against AriaFB is important because it isolates the scheduling benefit. AriaFB executes each block as a batch and aborts transactions with forward dependencies, then uses Vegeta's replay as fallback. That leaves it with 40.2% and 42.3% aborted transactions on the two main datasets, and only 3.8x and 3.6x speedup. Vegeta's advantage comes from better pre-consensus ordering and batch construction, not from a more permissive correctness condition.

The multi-node results support the paper's main systems claim. Re-execution stays below 2% even with consensus integration: 1.66% to 1.89% on dataset S2 and 1.58% to 1.82% on S4 for 4 and 10 nodes. In the 10-node deployment Vegeta still reaches 6.9x speedup. When the authors replace leaderless BKR with leader-based PBFT, the single leader becomes the speculation bottleneck and throughput falls, which is exactly the effect Vegeta was designed to avoid.

## Novelty & Impact

The main novelty is not a new conflict detector or another parallel EVM in isolation. It is the explicit co-design of execution and leaderless consensus. Compared with order-execute systems such as `Block-STM`, Vegeta moves useful work before ordering instead of forcing every node to rediscover the schedule after consensus. Compared with `Hyperledger Fabric`-style execute-order-validate, it does not trust speculative outputs and does not send conflicted transactions back through the whole pipeline. Compared with leader-oriented speculative systems such as `Forerunner`, it starts from the premise that no proposer has a perfect execution context and makes replay, not speculation, the correctness anchor.

That makes Vegeta a meaningful design point for DAG-BFT and asynchronous-BFT blockchains where ordering is already distributed and execution is now the limiting stage. I would expect future blockchain execution papers to cite it when arguing that leaderless consensus should also imply leaderless pre-processing of transactions, not just leaderless ordering.

## Limitations

The evaluation is intentionally an execution-engine study, not an end-to-end blockchain deployment. The authors disable persistence and usually skip Merkle Patricia Trie updates during performance runs, so the reported speedups are upper bounds for execution-layer gains rather than full-node throughput numbers. They also evaluate at most 10 nodes because the input Ethereum blocks were generated sequentially, which limits how much one can extrapolate to larger WAN committees.

The design is also sensitive to workload structure. Long dependency chains cap parallelism, and the paper identifies Wrapped Ethereum activity as a dominant source of those chains in its datasets. Vegeta's speculation is only an approximation as well: dependency chains are built per key, not from an exact global dependency analysis, so replay still needs a cleanup mechanism. If the speculative context becomes too stale, re-execution rates rise and speedups fall.

Finally, free proposer-side reordering collides with the economics of real DeFi systems. The paper explicitly notes that miners or proposers may choose an order that maximizes frontrunning or sandwich profit rather than parallelism. Vegeta also preserves safety under Byzantine speculation, but malicious nodes can sharply degrade performance by publishing empty or misleading dependency metadata. So the paper solves the execution-throughput problem more cleanly than it solves fairness, incentives, or adversarial efficiency.

## Related Work

- _Chen et al. (SOSP '21)_ - `Forerunner` speculatively executes Ethereum transactions to expose constraints, but it is not designed around leaderless BFT consensus and its lack of perfect context.
- _Lu et al. (VLDB '20)_ - `Aria` is the deterministic OLTP ancestor Vegeta borrows replay ideas from, while Vegeta adds pre-consensus speculation to cut abort and re-execution under blockchain workloads.
- _Gelashvili et al. (PPoPP '23)_ - `Block-STM` extracts parallelism after ordering, whereas Vegeta shifts dependency discovery before leaderless consensus so replay does less work.
- _Androulaki et al. (EuroSys '18)_ - `Hyperledger Fabric` follows execute-order-validate and may rerun conflicted transactions through a heavier pipeline; Vegeta keeps speculative outputs advisory and repairs only the replay schedule.

## My Notes

<!-- empty; left for the human reader -->

---
title: "ParallelEVM: Operation-Level Concurrent Transaction Execution for EVM-Compatible Blockchains"
oneline: "ParallelEVM logs EVM execution in SSA form and redoes only conflict-dependent instructions, raising average speedup on real Ethereum blocks from OCC's 2.49x to 4.28x."
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

ParallelEVM keeps optimistic execution but redoes only the instructions that depend on a stale read, identified through an SSA-style operation log. On real Ethereum blocks, this lifts average speedup to 4.28x versus 2.49x for conventional OCC.

## Problem

Execution, not consensus, is the bottleneck. The paper shows why naive parallel execution struggles on real chains: between January 1 and July 1, 2022, just 0.1% of 10 million contracts accounted for 76% of invocations, and 0.1% of 200 million storage slots accounted for 62% of accesses. Many of the hottest contracts are ERC20 tokens, so transfers repeatedly contend on the same sender balances and allowances.

Existing concurrency control is too coarse for that workload. If two `transferFrom` transactions both touch `balances[A]`, transaction-level schemes such as 2PL, OCC, and Block-STM block or restart the whole transaction, even though updates like `balances[B]` and `balances[C]` are unaffected.

## Key Insight

The paper's central claim is that blockchain conflicts are often narrow at the operation level even when they look broad at the transaction level. If the runtime can make EVM data dependencies explicit, a failed optimistic validation can be repaired instead of treated as a full restart: replace the stale `SLOAD` result with the committed value, follow the definition-use chain, and redo only the dependent instructions. ParallelEVM's SSA operation log also carries guards that reject partial redo when it would change control flow, runtime addresses, or gas behavior.

## Design

ParallelEVM extends optimistic concurrency control with four phases: read, validation, redo, and write. During read, transactions run speculatively in parallel while the system builds an SSA operation log whose entries store the opcode, explicit operands, result, and definition sites of the inputs across stack, storage, and memory. A shadow stack tracks `def.stack`; `latest_writes` and `direct_reads` distinguish in-transaction storage dependencies from committed-state reads; and shadow memory tags each byte with `<LSN, offset>` so later `MLOAD`s can recover dependencies when writes overlap.

Validation stays close to OCC: transactions validate in block order once earlier transactions commit, and a failure yields the conflicting storage slots plus their correct committed values. The redo phase is the novelty. ParallelEVM first uses `direct_reads` to find the `SLOAD` entries that directly consumed conflicted slots and patches those results. It then runs DFS over a definition-use graph derived from the SSA log to find all downstream instructions that depend on those patched values, reconstructs their inputs from the recorded definition metadata, and re-executes only that slice.

The safety net is a set of `ASSERT_EQ` guards. ParallelEVM inserts them for control-flow decisions, non-constant runtime addresses, and dynamic-gas instructions such as `SSTORE`. If repair would change a branch target, an address calculation, or an instruction's gas cost, redo fails and the transaction falls back to ordinary abort-and-restart in the write phase.

## Evaluation

The prototype modifies about 4200 lines of Go Ethereum v1.10.17. Experiments run on an 8-core, 16-thread machine with 16 GB RAM over Ethereum mainnet blocks 14,000,000 through 15,000,000, comparing against integrated 2PL, OCC, and Block-STM baselines.

ParallelEVM achieves 4.28x average speedup over baseline Geth, compared with 1.26x for 2PL, 2.49x for OCC, and 2.82x for Block-STM. Most blocks fall in the 2-7x range; only 0.88% are slower than serial execution, mainly because some long transactions fail redo and pay the fallback cost.

The supporting numbers fit the mechanism. ParallelEVM validates correctness by processing the first 14 million Ethereum blocks and always matching the Merkle Patricia Trie root of mainnet state. In conflict-free cases, SSA logging adds about 4.5% runtime overhead per transaction. The average contract invocation has 2559 EVM instructions but only 127 SSA log entries, so the repair representation is 5.0% of the original trace. During redo, only seven log entries on average are re-executed, or 0.3% of the original EVM instruction count; redo consumes 4.9% of total block-processing time, and 87% of conflicting transactions are resolved there. Memory use rises from 9.08 GB in stock Geth to 9.48 GB, a 4.41% increase. With state prefetching, average speedup reaches 7.11x, and a simulated pre-execution optimization reaches 8.81x.

## Novelty & Impact

The novelty is not merely a better blockchain scheduler. ParallelEVM brings partial transaction repair to EVM execution by deriving an operation-level dependency graph dynamically from bytecode execution, without requiring prior knowledge of transaction structure.

## Limitations

The evidence is narrower than the paper's ambition. The implementation and measurements are all on Ethereum and a single client; the claim that the idea transfers to other account-based, stack-machine blockchains is argued rather than demonstrated. Some blocks still lose to serial execution, and the authors' proposed fix is a future miner/proposer-generated schedule that ParallelEVM does not yet implement. More fundamentally, whenever a conflict changes control flow, runtime addresses, or dynamic gas behavior, the guards force a fallback to full restart.

## Related Work

- _Chen et al. (SOSP '21)_ - Forerunner speculates on future Ethereum transactions using constraints, while ParallelEVM repairs conflicts after optimistic execution and can additionally benefit from speculative pre-execution.
- _Garamvölgyi et al. (ICSE '22)_ - OCC-DA adapts optimistic concurrency to smart-contract conflicts but still aborts at transaction granularity; ParallelEVM keeps the optimistic structure and changes the repair unit.
- _Gelashvili et al. (PPoPP '23)_ - Block-STM coordinates execution and validation well, but it still blocks or restarts whole conflicting transactions instead of redoing only the dependent instructions.
- _Dashti et al. (SIGMOD '17)_ - MV3C also uses dependency graphs to partially re-execute conflicting work, but it assumes prior knowledge of transaction structure that ParallelEVM reconstructs dynamically from EVM execution.

## My Notes

<!-- empty; left for the human reader -->

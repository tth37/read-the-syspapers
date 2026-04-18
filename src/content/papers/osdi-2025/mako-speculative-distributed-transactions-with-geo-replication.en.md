---
title: "Mako: Speculative Distributed Transactions with Geo-Replication"
oneline: "Mako speculatively certifies cross-shard transactions before WAN replication finishes, then uses vector clocks and vector watermarks to bound rollback after shard failures."
authors:
  - "Weihai Shen"
  - "Yang Cui"
  - "Siddhartha Sen"
  - "Sebastian Angel"
  - "Shuai Mu"
affiliations:
  - "Stony Brook University"
  - "Google"
  - "Microsoft Research"
  - "University of Pennsylvania"
conference: osdi-2025
code_url: "https://github.com/stonysystems/mako"
tags:
  - databases
  - transactions
  - fault-tolerance
category: databases-and-vector-search
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Mako lets cross-shard transactions finish execution and 2PC certification before WAN replication completes. It uses vector clocks to preserve speculative dependencies and vector watermarks to decide replay, client acknowledgment, and rollback safely, pushing geo-replication out of the hot path.

## Problem

Geo-replicated OLTP systems want serializability, datacenter-failure tolerance, and sharding, but existing designs usually make distributed commit wait for WAN replication. Spanner-like systems replicate each critical 2PC step; Janus, Tapir, and Ocean Vista instead entangle replication with coordination. Either way, wide-area delay sits on the commit path, so better intra-datacenter hardware helps much less than it does in a single datacenter.

Speculation sounds attractive, but the hard case is cross-shard speculation under failures. Once later transactions read speculative writes, one lost participant can invalidate an entire dependency chain. Prior speculative systems only cover simpler settings: Rolis is single-shard, and Aurora does not support cross-shard transactions.

## Key Insight

Mako's key claim is that WAN replication and transaction coordination should be decoupled, not fused. Leaders can execute and certify a transaction locally, install its writes speculatively, and keep processing later transactions while replication runs in the background.

To make that safe, Mako tracks only coarse dependency information. Each transaction receives a vector clock that is component-wise greater than the clocks it read, and the system maintains a decentralized vector watermark describing what each shard has durably replicated. Normal execution waits for the watermark before replaying or acknowledging results; failure recovery computes a finalized watermark cut and rolls back only transactions above it.

## Design

Each shard leader is a multi-core in-memory store derived from Silo. A client sends a one-shot transaction to one leader, which acts as coordinator. Reads are optimistic and collect version metadata into a `ReadSet`; writes are buffered in a `WriteSet`. Certification then uses four RPC rounds across participating leaders: `Lock`, `GetClock`, `Validate`, and `Install`.

`GetClock` is the core mechanism. Each touched shard increments its logical clock and returns it; the coordinator then takes the component-wise maximum of those values and of the clocks already present in the `ReadSet`. That merged vector becomes the transaction's commit version. Because readers inherit the maximum of prior versions, transitive dependencies are preserved coarsely: if `T1` reads from `T0`, then `vc(T1) >= vc(T0)` pairwise. After validation, the writes are installed speculatively as new versions, so later transactions may observe them before replication finishes.

Replication is independent of certification. Every worker thread appends certified transactions into its own batched MultiPaxos stream, avoiding the single-stream bottleneck. Followers replay only when the transaction's vector clock is below the current vector watermark, where each shard independently contributes the minimum replicated clock across its local streams and all shards gossip those shard watermarks. Client replies are delayed until the same condition holds.

Failures are handled with epochs managed by a replicated configuration manager. When a leader fails, the system closes the old epoch, elects a new leader, and collects finalized shard watermarks. Healthy shards can emit an `INF` marker when they finish the old epoch cleanly; recovered shards finalize at the minimum surviving stream position. Their combination forms the finalized vector watermark (FVW), and any old-epoch transaction not below that cut is rolled back everywhere. This does not eliminate cascading aborts, but it bounds them without fine-grained dependency logs.

## Evaluation

The prototype adds about 10K lines of C++ on top of Silo, eRPC, and Janus, and is evaluated on Azure VMs with 32 vCPUs and injected 50 ms WAN RTT. On TPC-C with 10 shards and 24 worker threads per shard, Mako reaches 3.66M TPS, which the paper reports as 8.6x higher throughput than the best compared geo-replicated system. On the microbenchmark, it scales to 16.7M TPS at 10 shards and beats OCC+OR by 32.2x. Those results support the main claim that hiding WAN replication from the execution path matters more than shaving a few local RTTs.

The paper is also clear about where the design stops helping. With no cross-shard transactions the microbenchmark reaches 60.3M TPS, but when all transactions are cross-shard throughput drops to 1.1M TPS. Median latency on 10-shard TPC-C is 121 ms, dominated by WAN RTT and waiting for the watermark. The failover experiment is strong: healthy shards queue affected work and recover after the FVW is computed, while an epoch-commit variant stalls healthy shards entirely. A fairness caveat is that several baselines could not sustain cross-shard execution at larger scales, so the authors disabled cross-shard transactions for them.

## Novelty & Impact

Compared with _Corbett et al. (OSDI '12)_, Mako removes synchronous replication from the critical path of 2PC rather than making each 2PC step durable before moving on. Compared with _Fan and Golab (PVLDB '19)_ and _Mu et al. (OSDI '16)_, it argues that WAN settings benefit from looser coupling between coordination and replication, not tighter coupling. Compared with _Shen et al. (EuroSys '22)_, it extends speculative replication from a single-shard engine to a sharded geo-replicated database.

The main impact is conceptual: Mako shows that speculative distributed transactions are practical if recovery is phrased as bounded rollback across epochs instead of exact per-transaction recovery.

## Limitations

Mako bounds cascading aborts but does not eliminate them. Because the dependency signal is coarse, some transactions above the FVW are rolled back even if they were only conservatively suspected to depend on lost work. The prototype also assumes one-shot transactions, static sharding, and a replicated configuration manager that is treated as always alive.

Its performance still depends heavily on locality. The best case assumes related leaders are co-located; when leader placement spans datacenters or nearly all transactions become cross-shard, throughput falls sharply. The paper also notes that without geo-replication Mako is about 50% slower than tightly integrated RDMA systems, and full vector clocks eventually need compression when shard counts grow very large.

## Related Work

- _Corbett et al. (OSDI '12)_ - Spanner replicates 2PC decisions synchronously, while Mako speculates first and repairs with epoch rollback.
- _Fan and Golab (PVLDB '19)_ - Ocean Vista reduces geo-latency by integrating visibility control and replication, unlike Mako's decoupled path.
- _Mu et al. (OSDI '16)_ - Janus coalesces concurrency control and consensus for commits, whereas Mako separates them.
- _Shen et al. (EuroSys '22)_ - Rolis speculates replication for a single shard; Mako adds sharding and cross-shard recovery.

## My Notes

<!-- empty; left for the human reader -->

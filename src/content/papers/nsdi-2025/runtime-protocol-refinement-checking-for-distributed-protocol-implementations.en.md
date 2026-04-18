---
title: "Runtime Protocol Refinement Checking for Distributed Protocol Implementations"
oneline: "Ellsberg checks a deployed distributed protocol implementation against a protocol model from its message trace, catching runtime safety bugs without modifying the service or coordinating across nodes."
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

Ellsberg is a runtime protocol refinement checker for deployed distributed protocol implementations. It watches each process's message trace, tracks protocol states consistent with the observed prefix, and reports a bug when an outgoing message has no reachable inducing state. On Etcd, ZooKeeper, and Redis Raft, it finds reported safety bugs and one new Redis Raft reconfiguration bug.

## Problem

Verified protocols still turn into buggy production services once engineers optimize them. The paper points to Etcd stale reads and ZooKeeper election bugs as examples of implementation mistakes that break safety.

Existing approaches miss part of this space. Static proofs verify the model or a restricted implementation style; testing and fuzzing only cover explored executions; trace validation usually assumes a finished, totally ordered log; global runtime verification often needs coordinated snapshots. Ellsberg targets the practical gap: detecting protocol bugs in already-deployed black-box services without extra cross-node coordination.

## Key Insight

The core proposition is that, under fail-stop and non-Byzantine assumptions, local refinement checking is enough to expose safety violations. If each live process can still be explained by some correct protocol execution, the implementation has not yet shown a protocol bug. Ellsberg therefore checks each process independently against the protocol specification.

The difficulty is concurrency. The checker cannot see internal state or the real order in which a concurrent implementation processed pending messages and timeouts. Instead of simulating one state, Ellsberg maintains a set of possible states. Each outgoing message then becomes evidence: the checker infers the partial states that could have produced it and asks whether any are reachable from the current simulation set.

## Design

Users provide a protocol-specific Ellsberg specification: a protocol state type, `apply`, `equal`, `infer_inducing`, a conservative `reachable` predicate, `apply_asap?` for reorder-safe events, and optionally `lookahead_type` to shrink ambiguity. Deployment only needs an incremental local trace of sent and received messages, with per-connection receive order and outgoing program order.

At runtime, each checker maintains a simulation set `S`. A simulation state contains both a protocol state and pending-message sets, because different schedules can reach the same abstract state with different buffered inputs. Incoming messages are either appended to pending sets or, if `apply_asap?` says they are reorder-safe, applied immediately and recursively pruned.

When an outgoing message appears, Ellsberg computes the partial target state that would induce it and runs `find_reachable` from every current simulation state. `find_reachable` uses breadth-first search over pending inputs and timeouts. BFS is important because shorter schedules preserve larger pending sets; discarding them too early can create false alarms later. The search merges semantically equivalent protocol states, keeps distinct pending-message sets when needed, and prunes branches that `reachable` proves useless.

## Evaluation

The prototype is implemented in Go and evaluated on Etcd, ZooKeeper, and Redis Raft running on 3- and 5-node CloudLab clusters. The authors use 120 YCSB clients, balanced and read-heavy workloads, pin Ellsberg to two cores, and process traces once per second. They also validate the derived specs against TLA+ models with 8,750,468 Raft traces and 1,904,456 ZooKeeper traces.

The main result is bug finding. Ellsberg rediscovers reported bugs in all three systems, including stale reads, election inconsistency, lost updates, and reconfiguration errors, and it also exposes an unreported Redis Raft reconfiguration bug. It flags Etcd when a leader starts a read quorum check before committing a current-term entry, and flags ZooKeeper when a `DIFF` message cannot be justified by any valid log state.

The overhead case is credible. The paper reports no throughput loss for the monitored services and a worst-case 99th-percentile latency increase of 10.7%, from 7.25 ms to 8.03 ms, on read-heavy Redis Raft. Ellsberg can process outgoing messages faster than the services generate them: 2.0-51.7x Etcd's outgoing-message rate, 1.4-29.7x ZooKeeper's, and 3.1-25.5x Redis Raft's. With one-second batching, leaders spend 30-700 ms and followers 20-180 ms per second of trace, so alerts arrive within about 1.7 seconds. With `apply_asap?`, the average simulation set stays at one state and pending messages stay between 0 and 5.

## Novelty & Impact

The paper's contribution is a middle ground between static refinement proofs and runtime verification. Ellsberg reuses protocol models after deployment, but it does not require verified code, total-order logging, or cluster-wide snapshots. The inducing-state formulation plus BFS, reachability pruning, and immediate application of reorder-safe events is what makes that middle ground workable.

## Limitations

Ellsberg only catches bugs that eventually change message contents or message order. It cannot detect deadlock, livelock, pure performance regressions, or internal corruption that never leaks into network behavior. It also cannot prove an implementation correct; it can only say the observed trace prefix still has a protocol-consistent explanation.

Its assumptions matter. The protocol spec must be correct, the trace must be faithful and incremental, failures must be fail-stop rather than Byzantine, and messages must reveal enough state to keep inference tractable. The paper explicitly notes that some MVCC-style databases violate that last condition, causing too many partial states and schedules.

## Related Work

- _Howard et al. (NSDI '25)_ - `Smart Casual Verification` validates implementation traces against TLA+ in tests and CI, whereas Ellsberg performs online checking in deployment and avoids requiring a totally ordered test trace.
- _Hawblitzel et al. (SOSP '15)_ - `IronFleet` proves refinement statically end to end, while Ellsberg accepts arbitrary existing code but only detects violations after they occur.
- _Wilcox et al. (PLDI '15)_ - `Verdi` extracts verified distributed systems from Coq, whereas Ellsberg targets unmodified black-box services and trades proof for deployability.
- _Yaseen et al. (OSDI '20)_ - `Aragog` checks global runtime properties from distributed state, while Ellsberg checks local protocol refinement from message traces without cross-node coordination.

## My Notes

<!-- empty; left for the human reader -->

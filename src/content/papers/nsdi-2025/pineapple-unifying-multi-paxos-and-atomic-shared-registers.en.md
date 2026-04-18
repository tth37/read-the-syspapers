---
title: "Pineapple: Unifying Multi-Paxos and Atomic Shared Registers"
oneline: "Pineapple uses a unified pstamp so followers can serve linearizable single-key reads and blind writes while Multi-Paxos still orders one-shot transactions."
authors:
  - "Tigran Bantikyan"
  - "Jonathan Zarnstorff"
  - "Te-Yen Chou"
  - "Lewis Tseng"
  - "Roberto Palmieri"
affiliations:
  - "Northwestern"
  - "Unaffiliated"
  - "CMU"
  - "UMass Lowell"
  - "Lehigh University"
conference: nsdi-2025
category: consensus-and-blockchain
tags:
  - consensus
  - fault-tolerance
  - transactions
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pineapple splits linearizable storage into two ordering regimes: ABD-style atomic registers for single-key reads and blind writes, and Multi-Paxos for read-modify-write and one-shot transactions. Its unified `pstamp = (tag, slot)` lets follower-served register operations and leader-ordered transactions compare in one order, so reads stay at 1 RTT in a 3-node deployment and stronger operations remain linearizable. The payoff is less leader pressure and better throughput and tail latency than Multi-Paxos, PQR, and Gryff in the paper's target web-storage workloads.

## Problem

Leader-based consensus is the default way to build linearizable storage, but it creates a familiar bottleneck: every read, write, and transaction wants the leader in the critical path. That is tolerable for correctness, but it wastes the follower replicas that already store the data. The paper is aimed at large-scale web applications whose storage backends are dominated by single-key reads and writes, yet still need strong consistency because weaker models complicate application logic.

Prior systems only solve parts of this problem. Multi-Paxos and Raft keep the ordering story simple, but the leader saturates first. PQR offloads reads to followers, yet writes still bottleneck on the leader and reads can block waiting for committed log entries. Gryff pushes reads and writes away from the leader by combining EPaxos with atomic registers, but it pays more message and execution overhead, supports only single-key operations, and its read-modify-write path blocks on dependency resolution.

The hard part is not just making single-key operations fast. Once an operation depends on previous state, or spans multiple keys, the system needs a stable global order. A naive ABD-per-key design can return incomparable multi-key results because different quorums may observe different subsets of writes. Pineapple therefore tries to keep the cheap, quorum-based path for ordinary reads and writes while still giving transactions and stronger synchronization a stable order.

## Key Insight

The paper's main proposition is that linearizable storage does not need one ordering mechanism for every operation. Single-key reads and blind writes only need the weaker, non-stable ordering of atomic shared registers, because each write completely defines the new value. Read-modify-write operations and multi-key one-shot transactions, by contrast, need the stable ordering of state-machine replication because their result depends on prior state.

Pineapple unifies those two worlds with `pstamps`, a lexicographically ordered pair `(tag, slot)`. The `tag` comes from multi-writer ABD and orders register-style writes; the `slot` comes from Multi-Paxos and stabilizes the relative order of leader-executed transactions. Once the leader observes the newest value during a transaction's get phase, it can assign a later slot and make the write-versus-transaction relation stable for everyone. That is the crucial bridge: registers remain cheap, but as soon as a transaction matters, the leader "locks in" the order without forcing all operations through the consensus log.

## Design

Pineapple exposes three operations: `Read(k)`, blind `Write(k, v)`, and `OT(f, Kinput, Koutput)` for one-shot transactions whose code and input/output sets are known ahead of time. The direct write primitive is intentionally narrow: it overwrites a single key, while stronger semantics such as compare-and-swap, fetch-and-add, money-transfer-style updates, or scans are expressed as one-shot transactions.

Each replica stores, per key, a value and a `pstamp`. The `pstamp` is the paper's unifying timestamp: its `tag = (ts, id)` comes from multi-writer ABD, while `slot` comes from Multi-Paxos. Pineapple orders `pstamps` lexicographically, so ordinary writes advance the tag, ordinary reads choose the largest observed `pstamp`, and leader-executed transactions advance the slot while reusing the newest observed tag. That is what makes register results and transaction results directly comparable.

The ABD path stays close to the classic two-phase protocol. A blind write first learns the largest tag from a quorum, then writes back the new value with `(tag.ts + 1, writer-id)` and the most recent observed slot. A read first fetches value-`pstamp` pairs from a quorum, picks the value with the largest `pstamp`, then propagates that winning pair back to a quorum before returning. With the optimizations the authors inherit from prior ABD work, reads always finish in 1 RTT when `n = 3`, and in larger deployments they still hit the 1-RTT fast path when no concurrent write or one-shot transaction touches the same key.

Read-modify-write and multi-key one-shot transactions go through the Multi-Paxos leader. The leader must query a quorum that includes itself, because it may be the only node that already knows the newest leader-ordered update. It reads the latest inputs, executes `f`, assigns every output a new `pstamp` whose tag comes from the newest observed input and whose slot is the leader's next Paxos slot, then writes those outputs to a quorum. Giving all outputs of one transaction the same `pstamp` is what avoids the paper's scan anomaly: multi-key operations become comparable because the leader fixes their place in the stable order.

The paper also emphasizes "non-blocking execution." Once a node learns the relevant quorum result or leader decision, it can execute immediately; it does not have to wait for a dependency graph to drain, as in EPaxos-derived designs. During leader changes, Pineapple extends `pstamps` with ballot metadata and forces reads to back off when they detect a newer competing leader, so safety continues to come from the combined ABD-plus-Multi-Paxos discipline while liveness still depends on electing a stable leader.

## Evaluation

The evaluation uses Go implementations of Pineapple, PQR, and Multi-Paxos with leader lease on the same framework used for EPaxos, Gryff, and Multi-Paxos, then runs them on CloudLab in both 10 Gbps LAN and emulated WAN settings. That setup matters because the authors also disable batching and thrifty optimizations to focus on tail latency rather than peak throughput under favorable batching conditions. Most experiments use 16 B in-memory objects; the etcd integration instead uses YCSB with its default 100 KB values plus durable storage.

In 5-node LAN runs with balanced read/write traffic, Pineapple is in its intended regime when read-modify-write traffic stays below 20% of operations: there it beats the closest competitor, EPaxos, by about 10% to 20% in throughput and keeps the lowest median and p90 latency at saturation. The advantage disappears when the workload becomes all-RMW, where EPaxos's leaderless design wins by about 2.2x because Pineapple's leader again becomes the bottleneck.

WAN results make the design trade-off clearer. In read-heavy 3-node deployments, Pineapple and Gryff both keep reads at 1 RTT. The paper's WAN latency plots also show where PQR pays for blocking execution: when the leader is outside a client's closest quorum, read tail latency grows because the follower must wait for committed log state before replying. Under 25% conflicts, Pineapple cuts Gryff's RMW p99 by roughly 30 ms because Pineapple does not block execution on dependency resolution. In balanced WAN workloads, Pineapple reaches about 3x to 4x the throughput of the next closest competitor, PQR or lease-based Multi-Paxos; in read-heavy WAN workloads, lease-based Multi-Paxos still wins on raw throughput by about 1.25x to 1.3x because Pineapple continues to exchange quorum messages for reads.

The etcd integration is the paper's strongest practicality check. Replacing etcd's optimized Raft layer with Pineapple lowers median latency by more than 50% on the balanced YCSB-style LAN workload, and the paper reports roughly 20% to 50% lower p50 latency across the shown mixes. The trade-off is throughput: Pineapple does not surpass Raft in etcd, which the authors attribute to Raft's disk-batching optimization that their prototype does not reproduce.

## Novelty & Impact

Pineapple is novel less as a new consensus protocol than as a careful composition of two old ideas that normally live apart: quorum-based atomic registers and leader-based state-machine replication. Compared with PQR, it offloads writes as well as reads and avoids blocking execution. Compared with Gryff, it trades a leader back into the design so it can support multi-key one-shot transactions and simpler execution semantics instead of an EPaxos dependency graph. Compared with plain Multi-Paxos or Raft, it removes the assumption that every operation should pass through the leader.

That makes the paper useful to designers of etcd-like control planes, geo-replicated key-value stores, and systems papers that want stronger consistency without paying full leader bottlenecks on read-heavy or balanced workloads. I expect it to be cited as a "design point" paper: not because it discovers a new primitive, but because it shows a practical way to split operation classes across two ordering disciplines while preserving one linearizable interface.

## Limitations

The scope is intentionally narrower than a general transactional database. Pineapple's direct write is a blind write, not a conditional write, and its stronger operations must fit the one-shot transaction model where the function and input/output key sets are known before execution. That is sufficient for many key-value-backed web applications, but it is not a drop-in replacement for arbitrary interactive transactions.

Its performance envelope is also uneven by construction. Read-modify-write and one-shot transactions still go through the leader and take 3 RTT in the common case, so leader pressure returns as the RMW ratio rises; the paper's own LAN plots show EPaxos winning once the workload becomes all-RMW, and the WAN appendix shows leader-lease Multi-Paxos beating Pineapple on read-heavy throughput. Pineapple also needs extra machinery around leader changes: ballots must be folded into `pstamps`, and reads must back off when they detect a newer contender, so liveness still depends on partial synchrony and a stable leader.

Finally, the absolute performance numbers come from a deliberately controlled regime: mostly in-memory 16 B objects, closed-loop clients, no batching, and no Zipfian skew outside the etcd experiments. Those choices are reasonable for isolating the algorithmic contribution, but they leave open how far the wins carry to hotter-key production workloads or storage stacks where persistence optimizations dominate.

## Related Work

- _Burke et al. (NSDI '20)_ - `Gryff` also combines shared registers with a consensus layer, but it uses EPaxos dependencies for RMWs and stays limited to single-key operations, whereas `Pineapple` keeps a leader to support one-shot transactions with non-blocking execution.
- _Charapko et al. (HotStorage '19)_ - `PQR` augments Paxos with follower-served reads, while `Pineapple` offloads blind writes too and avoids the read path waiting for committed log entries.
- _Moraru et al. (SOSP '13)_ - `EPaxos` distributes ordering across replicas, but its dependency graph can hurt throughput and tail latency under conflict; `Pineapple` reintroduces a leader to get stable ordering for stronger operations.
- _Attiya et al. (JACM '95)_ - `ABD` gives linearizable quorum reads and writes for atomic registers, and `Pineapple` uses that register discipline as the fast path underneath a Multi-Paxos transaction order.

## My Notes

<!-- empty; left for the human reader -->

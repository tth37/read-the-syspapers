---
title: "Picsou: Enabling Replicated State Machines to Communicate Efficiently"
oneline: "Picsou gives independent RSMs a TCP-like cross-cluster broadcast protocol that usually sends one copy per message yet still recovers from crashes and Byzantine faults."
authors:
  - "Reginald Frank"
  - "Micah Murray"
  - "Chawinphat Tankuranand"
  - "Junseo Yoo"
  - "Ethan Xu"
  - "Natacha Crooks"
  - "Suyash Gupta"
  - "Manos Kapritsos"
affiliations:
  - "University of California, Berkeley"
  - "University of Oregon"
  - "University of Michigan"
conference: osdi-2025
code_url: "https://github.com/gupta-suyash/BFT-RSM"
tags:
  - consensus
  - fault-tolerance
  - networking
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Picsou defines Cross-Cluster Consistent Broadcast (C3B), a formal primitive for moving committed messages from one replicated state machine to another. Its TCP-inspired QUACKs let the common case use one cross-cluster send per message with constant metadata, while failures trigger targeted retransmissions instead of broadcast storms.

## Problem

Modern systems regularly need one RSM to talk to another: Etcd disaster recovery mirrors updates across datacenters, separate organizations reconcile shared state across sovereignty boundaries, and blockchains need interoperability. Existing approaches are unsatisfying. Kafka inserts a third replicated service into the path; all-to-all broadcast explodes traffic, especially over WAN links; and ad hoc bridges often have vague guarantees. The authors therefore want a primitive with precise semantics, low common-case cost, robustness to crash and Byzantine faults, and enough generality to connect heterogeneous protocols such as Raft, PBFT, and stake-based BFT systems.

## Key Insight

C3B only needs to guarantee that if sender RSM `Rs` transmits message `m`, then at least one correct replica in receiver RSM `Rr` eventually gets `m`; the receiver can strengthen that into full local dissemination or ordering using its own internal mechanisms. That relaxed contract is what makes Picsou practical. Once the receiver need only prove that some correct node has the message, the protocol can mimic TCP: cumulative acknowledgments establish that all messages up to `k` are safely present somewhere, and repeated acknowledgments for `k` expose that message `k+1` is likely missing. Picsou's main contribution is turning that idea into a many-to-many, fault-tolerant setting where nodes may crash or lie.

## Design

Each transmitted item is a committed request `m` plus its sender-log sequence number `k`, an optional cross-RSM stream number `k'`, and a proof that the sender RSM committed it. Picsou partitions the outgoing stream across sender replicas by `k' mod ns`, so exactly one sender handles each message in the common case. That sender also rotates receivers round-robin, which prevents a correct node from being stuck talking forever to the same faulty peer and eventually spreads knowledge of every receiver's state.

When a receiver replica gets a valid message, it does not rerun consensus on it. Instead, it verifies the proof and broadcasts the message inside its own RSM. To tell the sender side what has landed, each receiver maintains the highest contiguous prefix it has observed and sends an `ACK(p)` for that prefix. A message is QUACKed once `ur + 1` distinct receivers cumulatively acknowledge it, which proves at least one correct receiver has seen it. These acknowledgments are piggybacked on reverse-direction traffic when possible, so Picsou adds only two counters' worth of metadata in the failure-free path.

Failure handling is where the protocol gets interesting. A duplicate QUACK for `k` means a correct receiver is still missing `k+1`, so the sender side can infer a dropped or delayed message without extra coordination. To stop Byzantine nodes from forcing spurious resends, duplicate-ack evidence must come from `rr + 1` matching receivers, not just one complainer. Once loss is confirmed, every sender replica can deterministically compute the retransmitter as `(original_sender + resend_count) mod ns`, so exactly one node resends in each round.

The paper also addresses two subtler problems. First, selective drops can stall recovery if cumulative ACKs only talk about the earliest gap, so Picsou adds bounded `phi`-lists that summarize delivery state for a window beyond the current prefix and let multiple missing messages be recovered in parallel. Second, naive garbage collection is unsafe: a message can be QUACKed because one correct receiver saw it, then later become a bottleneck if the faulty receivers that helped form the quorum disappear. Picsou therefore piggybacks the highest QUACKed sequence number after such a mismatch so the receiver side can advance or fetch missing messages before the sender fully forgets them.

For proof-of-stake RSMs, equal round-robin no longer matches voting power. Picsou replaces it with weighted QUACKs and a Dynamic Sharewise Scheduler that uses Hamilton apportionment to assign sender and receiver opportunities proportionally to stake while still preserving parallelism. During failure recovery, it rescales stake using the least common multiple of the two clusters' total stake so retransmission logic does not blow up merely because one deployment uses much larger absolute stake values.

## Evaluation

The implementation is about 4,500 lines of C++20. On synthetic "File RSM" workloads where consensus is not the bottleneck, Picsou beats all-to-all broadcast by 2.5x to 3.2x on 4-node clusters and by 6.6x to 12.1x on 19-node clusters, with the paper's headline result reaching 24x over prior solutions. In geo-replicated 1 MB experiments between US-West and Hong Kong, Picsou is 12x faster than all-to-all at 4 replicas and 44x faster at 19 replicas because it shards traffic across many WAN paths instead of concentrating it at a leader or flooding it everywhere.

The failure experiments support the main claim rather than sidestepping it. With 33% crash failures in each RSM, throughput falls by 22.8% to 30.5%, roughly in line with losing one third of the useful links, yet Picsou still stays 2x to 8.9x faster than ATA, OTU, and leader-to-leader. Under Byzantine selective drops, larger `phi`-lists noticeably improve recovery, and lying acknowledgments hurt much less than crashes because delivery still requires matching quorum evidence.

Application studies are the strongest part of the paper. In Etcd disaster recovery, Picsou spreads five-way cross-region sending so the system exposes 250 MB/s of aggregate WAN bandwidth and then saturates Raft's disk goodput at about 70 MB/s; the paper summarizes this and the reconciliation workload as roughly 2x better than Kafka. In a blockchain bridge across Algorand and PBFT-based ResilientDB, Picsou keeps throughput loss below 15%, which is a credible sign that it behaves like a transport layer rather than a second consensus engine.

## Novelty & Impact

Compared with Kafka, Picsou removes the need to insert a third replicated log just to move state between two existing ones. Compared with all-to-all broadcast, it replaces quadratic cross-cluster traffic with a linear common-case path plus precise recovery. Compared with leader-centric schemes such as OTU, it avoids making one sender or receiver the standing bottleneck.

The main impact is conceptual as much as algorithmic. The paper argues that inter-RSM communication deserves its own primitive, C3B, rather than being treated as an afterthought of consensus or as a special-purpose bridge. That framing is likely useful anywhere independently administered state machines need disciplined, high-throughput communication.

## Limitations

C3B's guarantee is intentionally narrow: delivery means at least one correct receiver gets the message, not that the two RSMs jointly establish a total order or an atomic cross-cluster transaction. Applications must add those stronger semantics themselves. Picsou also assumes rare reconfiguration, known membership, and a way for the receiver to verify that the sender really committed a message.

The performance story is strongest for long-running streams with bidirectional traffic or cheap no-op acknowledgments. Latency still grows with network size, and the weighted design can eventually bottleneck if too much stake accumulates on one physical node. The Byzantine evaluation also does not try to solve volumetric DDoS from invalid traffic; the paper explicitly treats that as out of scope.

## Related Work

- _Aksoy and Kapritsos (SOSP '19)_ - Aegean studies nested requests from replicated services to backend services, whereas Picsou formalizes direct RSM-to-RSM message transfer.
- _Balakrishnan et al. (OSDI '20)_ - Delos uses virtual consensus and a shared log as a common substrate; Picsou instead asks how two already-replicated systems exchange state without inserting another replicated service in the middle.
- _Suri-Payer et al. (SOSP '21)_ - Basil tackles sharded BFT transactions and typically pays for more heavyweight cross-shard coordination than Picsou's narrow C3B primitive.
- _Gilad et al. (SOSP '17)_ - Algorand is a stake-based BFT protocol that motivates Picsou's weighted QUACK and scheduling design, but it solves intra-RSM consensus rather than cross-RSM transport.

## My Notes

<!-- empty; left for the human reader -->

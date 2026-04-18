---
title: "Tiga: Accelerating Geo-Distributed Transactions with Synchronized Clocks"
oneline: "Tiga assigns future timestamps from synchronized clocks so geo-distributed conflicting transactions usually line up across shards and commit in 1 WRTT."
authors:
  - "Jinkun Geng"
  - "Shuai Mu"
  - "Anirudh Sivaraman"
  - "Balaji Prabhakar"
affiliations:
  - "Stony Brook University"
  - "New York University"
  - "Stanford University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764854"
code_url: "https://github.com/New-Consensus-Concurrency-Control/Tiga"
tags:
  - databases
  - transactions
  - consensus
  - fault-tolerance
category: storage-and-databases
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Tiga assigns each geo-distributed transaction a future timestamp using synchronized clocks and measured one-way delays, so replicas usually receive conflicting transactions before their release time and process them in the same order. Leaders then validate that optimistic order with timestamp agreement and super-quorum log checks, letting most transactions commit in 1 wide-area RTT and falling back to 1.5-2 WRTTs only when the prediction fails.

## Problem

Geo-replicated OLTP systems need two guarantees at once: transactions that span shards must be isolated from each other, and replicas in different regions must durably agree on a single history. The usual construction is to stack concurrency control on top of consensus. That solves the problem, but it pays for ordering twice: once among transactions and once among replicas. In a wide-area deployment, those extra coordination steps turn directly into extra WRTTs, longer lock hold times, and lower throughput.

Prior consolidated protocols cut some of that cost, but their fast paths still break down under conflict. Tapir, Janus, and Detock all depend, in different ways, on the order in which transactions arrive at different servers. In a geo-distributed network that order is often inconsistent, so the fast path collapses into aborts, retries, or expensive dependency-graph work. The paper's target is also stricter than plain serializability: it wants strict serializability, because banking, ticketing, and lock services care about real-time order, not just some serial order after the fact.

## Key Insight

Tiga's core proposition is that synchronized clocks can move ordering from a reactive step to a proactive one. Instead of waiting for shards to discover that they saw conflicting transactions in different orders, the coordinator predicts a future timestamp before multicast. It computes that timestamp from the send time, the largest one-way delay to a super quorum in every participating shard, and a small headroom term (`10 ms` in the implementation). If servers receive the transaction before that timestamp, they can wait until the same release point and then process it in one consistent timestamp order.

The clocks are not the correctness oracle. Tiga follows the usual rule of depending on clock synchronization for performance, not correctness. Leaders still exchange timestamps after optimistic execution, agree on the maximum, and repair cases where one leader had to raise the timestamp locally. The gain is that synchronized clocks make inconsistent arrival orders rare enough that expensive repair becomes the exception instead of the common case.

## Design

Tiga is a consolidated protocol rather than a concurrency-control layer followed by a separate consensus layer. Each server keeps a priority queue of pending transactions ordered by timestamp, read and write maps that remember the latest released timestamp per key, and a replicated log with a sync-point and commit-point. Transactions are assumed to be one-shot stored procedures, or decomposed into that form, so read and write sets are known in advance and conflict detection is cheap.

At submission time, the coordinator multicasts the transaction with its future timestamp. On arrival, each server checks whether that timestamp is larger than all conflicting transactions that have already been released. If yes, the transaction enters the priority queue. If a leader receives it too late, the leader updates the timestamp to its local clock and enqueues it anyway; followers never do timestamp updates and instead wait for later synchronization. When a transaction's timestamp has expired and no earlier conflicting transaction blocks it, the leader speculatively executes it. Followers do not execute on the fast path: they release the transaction, append it to their local log, and reply.

The fast path hinges on what those replies contain. Every fast reply includes the transaction timestamp plus an incremental hash of the log prefix before the transaction. The coordinator declares a shard fast-committed only if it receives a super quorum that includes the leader and agrees on both the hash and the timestamp. The super quorum is larger than a simple quorum because recovery must later distinguish a genuinely committed order from two incompatible speculative orders that happened to be observed by different followers.

After speculative execution, participating leaders run timestamp agreement. If every leader already used the same timestamp, the transaction can be released immediately. If this leader already used the maximum timestamp but some others used smaller ones, Tiga runs a second exchange round before release to avoid the timestamp-inversion pitfall, where real-time order and serial order diverge across shards. If this leader used a smaller timestamp, it revokes the speculative execution, raises the timestamp to the agreed maximum, repositions the transaction in the queue, and executes it again later. The paper relies on multi-versioned data so this revocation stays internal to Tiga rather than becoming an application-visible rollback.

The slow path and recovery protocol close the loop. Once leaders append the agreed order to their logs, they synchronize followers, repair divergent log entries or timestamps, advance sync-points, and collect slow replies. A transaction is slow-committed on a shard after the coordinator has the leader's fast reply plus slow replies from `f` followers. On failures, a view manager installs a new view, new leaders rebuild each shard from `f + 1` surviving replicas, and the system tries to choose co-located leaders so inter-leader timestamp agreement can be moved before execution. That gives Tiga two operating modes: a detective mode that executes before agreement when leaders are far apart, and a preventive mode that agrees before execution when leader coordination is LAN-cheap.

## Evaluation

The implementation is built on the Janus codebase and evaluated in Google Cloud with replicas in South Carolina, Finland, and Brazil, plus some remote coordinators in Hong Kong. That setup matters because it keeps the RPC runtime and baseline implementations comparable, and the authors also strengthen several baselines for fairness, such as making Detock perform synchronous geo-replication and evaluating NCC together with a fault-tolerant NCC+ variant.

On MicroBench with low contention, Tiga reaches `157.3K txns/s`, versus `119.6K` for Calvin+, `77.8K` for Janus, `44.2K` for Tapir, and `47.4K` for NCC. Near saturation, the paper summarizes the result as `1.3x-7.2x` higher throughput and `1.4x-4.6x` lower median latency than the baselines. The qualitative behavior is as important as the headline numbers: Tapir degrades because conflicting transactions arrive in different orders, Janus and Detock pay increasingly for graph work, and Calvin+ suffers from stragglers. Tiga also keeps 1-WRTT latency when coordinators run in Hong Kong, whereas Janus, Tapir, and Calvin+ need at least 2 WRTTs there when servers are not co-located with coordinators.

TPC-C is the more convincing stress test because it mixes interactive transactions with much higher conflict. Tiga still leads at `21.6K txns/s`, ahead of Detock at `13.3K`, Janus at `10.8K`, and Calvin+ at `6.1K`. 2PL+Paxos, OCC+Paxos, and Tapir all fall to roughly `1K-2K txns/s`, while NCC is down in the hundreds and NCC+ is lower still. That supports the paper's main claim: proactive time-based ordering is not just a low-contention trick, but remains useful under realistic multi-shard OLTP contention.

The secondary experiments strengthen the story. Tiga finishes a leader-failure recovery and returns to its previous throughput level in `3.8 s`. When leaders are intentionally separated across regions, throughput drops only `9.7%`, though latency rises because more transactions wait behind timestamp agreement or need re-execution. The headroom study shows the default timestamp estimate is close to optimal: too little headroom causes rollbacks, while too much adds unnecessary waiting. Finally, Chrony's `4.54 ms` synchronization error performs almost the same as Huygens' `0.012 ms`, because both are small relative to the `60-150 ms` WAN delays; badly synchronized clocks are where Tiga starts to lose its edge.

## Novelty & Impact

The closest comparison points are Tapir, Janus, Detock, and NCC. Tiga's novelty is not merely "use clocks" or "consolidate ordering," because prior work already explored both ideas. What is new is the full package: future timestamps chosen from measured one-way delays, super-quorum validation of speculative log prefixes, an explicit fix for timestamp inversion, and a complete failure-recovery path that preserves strict serializability.

That makes the paper important beyond this one protocol. It argues that modern public-cloud clock quality has changed the design space for geo-distributed transactions: lightweight timestamp ordering is no longer obviously too fragile to use. For database researchers, that is a clean mechanism result. For practitioners building globally replicated services, it is a plausible route to 1-WRTT commits without giving up strict serializability or adopting Janus/Detock-style graph processing on the hot path.

## Limitations

Tiga's best case depends on clock error being small relative to WAN delay and, ideally, on leaders being co-located. When leaders are separated, later conflicting transactions can block behind `0.5-1 RTT` of timestamp agreement, and some speculative executions need to be revoked and replayed. The throughput loss in the paper is modest, but the latency cost is real.

The protocol also assumes that read and write sets are known ahead of execution, so its natural fit is one-shot stored procedures; interactive transactions are supported through decomposition rather than as a first-class model. And while the fast path is elegant, the full system is not simple: it needs multi-version revocation, log synchronization, a view manager, checkpoints, and two execution modes. That complexity is a real deployment cost, especially if clock quality degrades toward the scale of the network delay.

## Related Work

- _Corbett et al. (OSDI '12)_ - Spanner also uses synchronized clocks for geo-distributed transactions, but it still pays a layered commit/replication cost that Tiga tries to collapse into a lighter 1-WRTT common path.
- _Zhang et al. (SOSP '15)_ - Tapir gets a 1-RTT fast path with inconsistent replication, whereas Tiga's main contribution is to make conflicting transactions much less likely to diverge in arrival order in the first place.
- _Mu et al. (OSDI '16)_ - Janus established the value of consolidating concurrency control and consensus under conflicts; Tiga keeps that consolidation idea but replaces dependency-graph reasoning with proactive timestamp alignment.
- _Lu et al. (OSDI '23)_ - NCC protects strict serializability by inserting response-time spacing between conflicting transactions, while Tiga instead tries to line those transactions up before execution and repair the rare mismatches afterward.

## My Notes

<!-- empty; left for the human reader -->

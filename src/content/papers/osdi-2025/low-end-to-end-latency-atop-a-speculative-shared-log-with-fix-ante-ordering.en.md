---
title: "Low End-to-End Latency atop a Speculative Shared Log with Fix-Ante Ordering"
oneline: "SpecLog lets a shared log deliver durable records before global ordering completes, using fix-ante quotas so shards can usually speculate positions correctly."
authors:
  - "Shreesha G. Bhat"
  - "Tony Hong"
  - "Xuhao Luo"
  - "Jiyu Hu"
  - "Aishwarya Ganesan"
  - "Ramnatthan Alagappan"
affiliations:
  - "University of Illinois Urbana-Champaign"
conference: osdi-2025
code_url: "https://github.com/dassl-uiuc/speclog-artifact"
tags:
  - storage
  - fault-tolerance
  - consensus
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

SpecLog changes a shared log's contract: it can deliver a durably stored record before the system has finished globally ordering it. Belfast, the paper's implementation, makes that safe with fix-ante ordering, which predetermines per-shard quotas so shards can usually predict positions correctly and later confirm them. Against Scalog, Belfast delivers records 3.2x to 3.5x earlier and cuts average end-to-end latency by about 1.6x.

## Problem

The paper starts from a genuine mismatch between what modern low-latency applications need and what current shared logs optimize. Durability-first designs such as Scalog let clients write to arbitrary shards, scale throughput by adding shards, and reconfigure without downtime. But they only deliver records after a sequencing layer has collected batched shard reports, computed a global cut, replicated that cut, and sent it back. For applications such as fraud monitoring, real-time analytics, and high-frequency trading, that ordering delay is not bookkeeping overhead; it is dead time before any useful downstream computation can even begin.

Order-first systems such as Corfu avoid some of Scalog's mechanics, but they pay elsewhere: fixed position-to-shard mappings hurt seamless reconfiguration, flexible placement, and scalability. The authors therefore do not want a new low-latency log that gives up the properties that made durability-first logs attractive in the first place. They want the same elasticity and placement freedom, but with record delivery early enough that application compute can overlap with ordering.

The hard part is correctness. In existing durability-first logs, each shard has too much freedom in how many durable records it reports in a round. Because one shard's positions depend on how many records every other shard reports, a shard cannot confidently predict its own next global positions from local state alone. A naive speculative design would therefore misspeculate often enough to be useless.

## Key Insight

The paper's central claim is that shared logs should speculate on delivery, not wait for exact global order before letting applications start work. SpecLog exposes that idea directly: shards can `deliver` a record with a speculative-position bit, and later the system sends either `confirm_spec` or `fail_spec` notifications. Applications then overlap downstream compute with the log's coordination, externalizing outputs only after confirmation and rolling back if speculation fails.

That interface only works if misspeculations are rare. The key technical idea is therefore fix-ante ordering: instead of letting shards freely report whatever they have, the system predetermines a sequence of global cuts and, from them, exact per-shard quotas. If every shard knows the quotas all shards are supposed to satisfy in a cut, then it can compute where its own local records must land in the lexicographic total order before talking to the sequencer. In other words, the paper removes the source of uncertainty by removing the shards' reporting freedom.

Durability still comes before real ordering. The predetermined cuts are only a prediction scaffold. Belfast still waits for the sequencing layer to compute and disseminate the actual cut, and append acknowledgments still wait for that actual cut to preserve linearizability. The point is narrower but powerful: delivery and application compute can move early, while acknowledgment and confirmation still respect the real order.

## Design

Belfast is built by modifying Scalog. Each shard remains internally fault tolerant using primary-backup replication, and the sequencing layer is a Paxos group that makes actual cuts durable. On the data path, clients append to a shard, the shard makes the record durable locally, and then immediately predicts its global position from the predetermined cut sequence and speculatively delivers it to downstream consumers. Later, once the shard has reported to the sequencer and received the corresponding actual cut, it either confirms or fails that speculative delivery.

The design turns on how shards satisfy quotas. If a shard has exactly its quota's worth of new durable records, it reports them. If it has too few, it fills the gap with no-ops, which downstream consumers ignore. If it has too many, it delays the excess into later reports. Because all shards follow the same cut schedule, their predictions line up with the eventual actual cut in the normal case. The sequencer also waits for all shards with non-zero quota in a cut before issuing that cut; otherwise it could accidentally certify a different order and break speculation.

Most of the rest of the system is about making that discipline practical. Belfast assigns rate-based quotas so each shard naturally reports about once per ordering interval. When one shard bursts ahead, the lag-fix mechanism asks lagging shards to send extra reports, filling no-ops if needed, so the fast shard's speculative deliveries do not sit unconfirmed for many intervals. For longer-term rate changes, Belfast introduces speculation lease windows: all shards use the same predetermined cuts for a window of cuts and only switch to new quotas at window boundaries. That same mechanism lets shards join or leave without downtime, just with a small boundary delay.

Belfast also deals with scale and failures explicitly. With many shards, it uses staggered cuts so each cut waits on only a subset of shards rather than everybody. If one shard becomes a straggler, the sequencer can assign it zero quota in the next window so others keep progressing. If an entire shard fails, Belfast triggers a view change, fails speculation after the last confirmed position, and temporarily has an alive shard fill the failed shard's slots with no-ops so the rest of the log can keep advancing while applications roll back and replay.

## Evaluation

The evaluation targets the right bottleneck: whether speculative delivery actually reduces end-to-end latency, not just append latency or sequencing throughput in isolation. On CloudLab with 4 KB records and Scalog as the main baseline, Belfast delivers records 3.2x to 3.5x earlier and cuts average end-to-end latency by about 1.6x for workloads whose downstream compute takes around 1.5 ms. The benefit curve is believable rather than magical: with only 0.5 ms of compute, Belfast still helps but only by 1.17x because consumers finish early and then wait for confirmation; with 1.5 ms of compute, overlap is best and the gain reaches 1.63x; with very long compute, the benefit naturally approaches 1x because compute dominates.

The append-path cost is also measured honestly. Belfast does pay for quota adherence and sequencer waiting, but the paper reports only a 5.8% append-latency overhead at 10 shards. The quota and lag-fix results are especially important because they show the system is not relying on a fragile steady state: lag-fix bounds burst-induced confirmation delay, quota changes avoid sustained no-op inflation under permanent rate shifts, and no-op overhead stays below 5% of actual throughput in the experiments.

The broader system results support the paper's claim that low latency does not require surrendering the usual shared-log virtues. Belfast adds and removes shards without downtime, retains lower end-to-end latency during those transitions, and scales throughput similarly to Scalog up to 40 shards in emulation. End-application experiments are also convincing: Belfast reduces end-to-end latency by 1.60x for intrusion detection, 1.40x for fraud monitoring, and 1.42x for high-frequency trading. One fairness detail I appreciated is that the authors modified Scalog so only the primary reports durable records, making the comparison isolate fix-ante ordering rather than an implementation artifact.

## Novelty & Impact

Compared with _Ding et al. (NSDI '20)_, Belfast keeps the durability-first shared-log shape but makes delivery speculative instead of strictly post-ordering. Compared with _Luo et al. (SOSP '24)_, it targets low end-to-end latency for immediately consumed streams, not just lower append latency under the assumption that reads are decoupled from writes. Compared with _Balakrishnan et al. (NSDI '12)_, it avoids returning to an order-first design that would give up elasticity and flexible placement.

The contribution is therefore both a new mechanism and a new abstraction boundary. Fix-ante ordering is the mechanism that makes speculation accurate enough to matter; SpecLog is the abstraction that tells applications how to use it safely. I would expect later shared-log, streaming, serverless, and low-latency data infrastructure papers to cite this work either as the first serious attempt to overlap global log coordination with downstream compute or as the cleanest argument that end-to-end latency, not append latency alone, should be the target metric.

## Limitations

The paper is clear that Belfast's wins depend on overlap. If downstream compute is too short, consumers still wait for confirmation; if compute is too long, ordering vanishes into the noise and the advantage shrinks. This is not a flaw in the data, but it does mean Belfast is most compelling for a specific regime of real-time pipelines rather than all shared-log users.

Correctness under failure also comes with application obligations. Whole-shard failures and sequencer reachability problems can still force misspeculation, at which point applications must retain enough in-memory undo information to roll back unconfirmed work. The paper argues this state is small, but that is still a meaningful integration burden compared with a non-speculative log.

Finally, several performance knobs are only partially resolved. Small speculation windows add synchronization overhead, large windows react slowly to long-term rate changes, staggered cuts use a simple static grouping policy, and the paper leaves more aggressive handling of high-burstiness scenarios to future work. The 40-shard results are partly emulated rather than fully end-to-end on real shards, so the largest-scale claims are credible but not as strong as the smaller real-cluster experiments.

## Related Work

- _Balakrishnan et al. (NSDI '12)_ - Corfu offers a total-order shared log by assigning order before writes, whereas Belfast keeps durability-first writes and speculates only delivery.
- _Ding et al. (NSDI '20)_ - Scalog is Belfast's direct predecessor: it already gives seamless reconfiguration and flexible placement, but records are delivered only after the actual global cut arrives.
- _Giantsidi et al. (SOSP '23)_ - FlexLog reuses the durability-first shared-log structure for stateful serverless computing, but it does not address speculative delivery for low end-to-end latency.
- _Luo et al. (SOSP '24)_ - LazyLog reduces append latency for low-latency applications, but it still orders before reads and therefore does not overlap ordering with downstream compute the way SpecLog does.

## My Notes

<!-- empty; left for the human reader -->

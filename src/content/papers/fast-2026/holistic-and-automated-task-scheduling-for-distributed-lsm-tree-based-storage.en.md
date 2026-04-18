---
title: "Holistic and Automated Task Scheduling for Distributed LSM-tree-based Storage"
oneline: "HATS combines epoch-level replica assignment, per-request rerouting, and read-driven compaction control to cut Cassandra P99 read latency by up to 79%."
authors:
  - "Yuanming Ren"
  - "Siyuan Sheng"
  - "Zhang Cao"
  - "Yongkun Li"
  - "Patrick P. C. Lee"
affiliations:
  - "The Chinese University of Hong Kong"
  - "University of Science and Technology of China"
conference: fast-2026
category: indexes-and-data-placement
code_url: "https://github.com/adslabcuhk/hats"
tags:
  - scheduling
  - storage
  - databases
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

HATS is a Cassandra-based scheduler that treats read placement and compaction as one coupled control problem rather than two separate heuristics. Every 60 seconds it rebalances expected read load across replicas, uses per-request latency to reroute only when a replica truly has spare capacity, and gives more compaction budget to the hottest key ranges. That combination cuts tail latency sharply against C3 and DEPART while also raising throughput.

## Problem

The paper starts from a mismatch between what distributed KV stores balance and what users care about. Cassandra can spread requests across replicas, so request counts per node look fairly even, yet the authors still observe a `4.24x` latency gap between the fastest and slowest node in a homogeneous 10-node cluster. At smaller timescales it is worse: on the worst node, `90.8%` of one-second windows fall outside `0.5x-2.0x` of its own average latency. Equalizing access frequency is not enough because latency is being perturbed by what each node is doing inside its storage engine.

For LSM-tree-based stores, the hidden culprit is compaction. It steals CPU and disk from reads, yet suppressing it leaves more SSTables and higher read amplification. Existing replica-selection schemes mostly optimize the foreground request path and treat background work as noise. HATS argues that this separation is the real design bug.

## Key Insight

The core claim is that a replicated LSM store needs one closed loop spanning both the distribution layer and the storage layer. Large-timescale imbalance should be corrected by changing how many reads each replica is expected to serve. Small-timescale spikes should be handled by per-request coordination using instantaneous latency, but without chasing the momentarily fastest node and creating oscillation. At the same time, compaction should be treated as a schedulable resource consumer: the hottest key ranges should get more compaction budget because that improves both current latency and future read cost.

## Design

HATS adds three mechanisms to Cassandra 5.0. Coarse-grained read assignment runs once per epoch: nodes piggyback per-range read counts and average read latency onto Gossip, and a Raft-elected seed node builds a cluster-wide current state, shifts expected read counts from overloaded replicas to underloaded ones, and gossips the resulting expected state back to clients. Fine-grained coordination runs inside the epoch: a coordinator measures instantaneous per-replica latency and computes a unified score that reflects spare service capacity relative to expected load, redirecting only when another replica actually has slack. Compaction scheduling uses DEPART-style replica decoupling so each replica has its own LSM-tree; HATS then allocates compaction bandwidth across those LSM-trees in proportion to read share, leaves lowest-level compaction unthrottled, and enforces a minimum rate so cold ranges still make progress. The epoch is `60 s`, matching Cassandra's default compaction interval.

## Evaluation

The evaluation uses Cassandra 5.0 on a 10-node cluster with three-way replication, `100 M` preloaded `1 KiB` records, and `100` client threads, plus a 20-node heterogeneous cluster. The baselines are mLSM, C3, and DEPART, all reimplemented on the same Cassandra version, and the workloads are YCSB A-F plus a Facebook-trace-based production workload.

HATS is strongest on mixed and read-dominant workloads. It achieves the highest throughput on YCSB A, B, C, D, and F, with gains up to `2.90x` over DEPART; the abstract summarizes this as P99 reductions of `58.6%` and `59.9%` and throughput gains of `2.41x` and `2.90x` over C3 and DEPART, respectively, on read-dominant workloads. On Facebook-style traffic, HATS reaches `48.8 KOPS` overall, versus `17.1 KOPS` for mLSM, `20.2 KOPS` for C3, and `21.5 KOPS` for DEPART, and cuts P99 Get latency by up to `83.2%`, `78.9%`, and `68.3%` relative to those baselines. The breakdown data supports the design: in read-only Workload C, HATS redirects only `0.04%` of reads remotely, versus `84.9%` for C3. The main weak spot is scan-heavy Workload E, where HATS is roughly tied with mLSM and slightly below DEPART.

## Novelty & Impact

Relative to C3, the novelty is moving from foreground-only adaptive replica selection to a controller that also shapes background compaction. Relative to DEPART, the contribution is not replica decoupling itself, but using decoupled replicas as an actuator for per-key-range compaction control. That makes the paper more than a Cassandra tuning exercise: it turns the complaint that compaction hurts tail latency into a concrete cross-layer control design using deployable mechanisms.

## Limitations

HATS depends on deployment assumptions that matter. It needs replica decoupling, which the authors argue is cheap in Cassandra, but it still changes storage layout and compaction behavior. Its gains also shrink as replica choice shrinks: when read consistency rises, the gap over DEPART narrows because there are fewer scheduling degrees of freedom. More broadly, the system is tuned for read-latency control rather than full multi-tenant isolation, and the control loop still centers on one scheduler leader per Raft term plus a fixed `60 s` epoch.

## Related Work

- _Suresh et al. (NSDI '15)_ — C3 adapts replica choice, but it treats compaction as background noise rather than a control input.
- _Zhang et al. (FAST '22)_ — DEPART separates replicas into independent storage structures; HATS reuses that structure to prioritize compaction for hot ranges.
- _Wydrowski et al. (NSDI '24)_ — Prequal argues that balancing load alone does not balance latency, a lesson HATS instantiates inside a replicated LSM store.
- _Balmau et al. (ATC '19)_ — SILK tackles latency spikes inside one local LSM engine, whereas HATS also handles cross-node read placement.

## My Notes

<!-- empty; left for the human reader -->

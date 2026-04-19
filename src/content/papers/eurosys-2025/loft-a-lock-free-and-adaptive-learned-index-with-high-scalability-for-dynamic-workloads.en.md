---
title: "LOFT: A Lock-free and Adaptive Learned Index with High Scalability for Dynamic Workloads"
oneline: "LOFT makes learned indexes scale under writes by replacing locked shifts with CAS-based range insertion, overflow buckets, and shadow-node retraining tuned per node."
authors:
  - "Yuxuan Mo"
  - "Yu Hua"
affiliations:
  - "Wuhan National Laboratory for Optoelectronics, School of Computer, Huazhong University of Science and Technology"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717458"
code_url: "https://github.com/yuxuanMo/LOFT.git"
tags:
  - databases
  - memory
  - transactions
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

LOFT argues that concurrent learned indexes should preserve only a small model-bounded search region, not strict in-node order. It inserts with `CAS` into the first free slot in that range, spills true overflows into small learned buckets, and retrains behind shadow nodes without blocking foreground traffic; the result is up to `14x` higher throughput than prior learned indexes and much lower tail latency on dynamic workloads.

## Problem

Learned indexes save memory and pointer chasing, but dynamic workloads break the assumptions that make them fast. Once inserts arrive, the data distribution drifts and prior systems choose between two bad paths. XIndex and FINEdex buffer inserts out of place, so reads pay extra probing and retraining lag. ALEX+, LIPP+, and SALI insert in place, but collisions trigger shifts, chained nodes, or locks. The paper shows that just `5%` inserts cut learned-index throughput by about `50%` on average, and the best prior concurrent designs stop scaling well past `24` threads.

Retraining compounds the problem. Blocking retraining stalls access to a node; fully asynchronous retraining keeps stale models alive long enough that buffers and prediction error grow. Fixed retraining thresholds are also a mismatch because hot write-heavy, hot read-heavy, and cold nodes need different free-space policies. LOFT's goal is to preserve model-based navigation without lock-heavy insertions or disruptive retraining.

## Key Insight

The paper's central claim is that correctness does not require records inside a learned node to stay fully sorted. Each key only needs to remain inside a small model-predicted range. That weaker invariant makes inserts simple `CAS` claims on free slots rather than shifts or node-level critical sections, while keeping reads fast because the remaining disorder is bounded.

It also simplifies retraining. LOFT can keep the old node as a shadow copy while a background thread builds new nodes and synchronizes missed writes, turning retraining into repair instead of blocking.

## Design

LOFT keeps the usual two-stage `RMI` root over data nodes, but changes the node invariant. A node is initialized with `PLA`, expansion factor `epsilon = 1.5`, and predicted range `pre_ran = 32`. Keys need only remain inside that range, not in strict sorted order.

Insertion computes the predicted position and repeatedly issues `CAS` against `EMPTY_KEY` inside the predicted range. The first successful `CAS` claims the slot; if a failed `CAS` returns the same key, the operation becomes an update. Nothing is shifted. If the whole range is full, the record goes to an expanded learned bucket shared by that range, with expansion factor `beta = 8`. Reads linearly scan the predicted range and then the bucket if needed; deletes are soft deletes so duplicates cannot appear before retraining.

Retraining runs under `RCU` in copy, retraining, and sync stages. A background thread marks the node as retraining, foreground updaters append modified keys to an append-only log, and the background thread copies, sorts, retrains, and builds new nodes. It then atomically swaps the root pointer so the old node becomes a shadow node. During sync, reads and writes can still use the shadow node to fetch or install newer values, so foreground traffic helps finish synchronization instead of waiting. Per-node counters decide whether a node should split, expand, or merge, and LOFT retunes `epsilon` and `pre_ran` accordingly: write-heavy nodes increase free space, read-heavy nodes shrink search ranges, and cold nodes compact aggressively.

## Evaluation

The prototype is implemented in C++ and evaluated on a two-socket Linux server with two `26`-core Xeon Gold `6230R` CPUs and `188 GB` DRAM, against Masstree, DyTIS, ART-OLC, XIndex, FINEdex, ALEX+, LIPP+, and SALI. Workloads include YCSB with varying read/insert ratios and five real datasets of `200` million unique `8`-byte keys.

The main result is that LOFT dominates the dynamic-workload regime the paper cares about. On mixed YCSB workloads it achieves the best throughput across all tested read/write ratios, scaling to `80` threads in read-intensive cases and `48` threads in write-intensive ones. At `80` threads, the paper reports average speedups of `3.1x` over XIndex, `3.4x` over FINEdex, `1.7x` over ALEX+, `14x` over LIPP+, and `3.8x` over SALI. On a workload that shifts access patterns every `400` million operations, LOFT improves average throughput by `16%` over ALEX+ while avoiding the sharp performance cliffs caused by blocking retraining.

Latency results support the same story. LOFT cuts tail read latency by up to `90%`, and the paper summarizes its own tail behavior as roughly `1,000 ns` per read and `5,000 ns` per insert. The caveat is that on hard datasets such as Genome, Fb, and OSM, ART-OLC can match or beat LOFT because the learned fit is poor.

## Novelty & Impact

LOFT's novelty is the abstraction boundary: preserve error-bounded placement instead of exact order. That lets `CAS`-based insertion, learned overflow buckets, shadow-node retraining, and per-node self-tuning work together as one coherent concurrency story. The paper also appears to be the first lock-free learned index, which makes it an obvious reference point for later update-friendly learned structures.

## Limitations

LOFT gives up binary search inside a node, so the design depends on `pre_ran` staying small; on hard datasets such as Genome, Fb, and OSM, the paper shows ART-OLC can match or beat it. The scheme also spends extra memory on expansion, buckets, logs, and shadow nodes, assumes `8`-byte keys and atomically writable `8`-byte values on the fast path, and does not evaluate crash recovery or failures.

## Related Work

- _Kraska et al. (SIGMOD '18)_ - introduced the learned-index framing itself; LOFT keeps that framing but redesigns the update path for dynamic concurrent workloads.
- _Ding et al. (SIGMOD '20)_ - ALEX preserves sorted in-node structure with spare gaps and shifts, whereas LOFT gives up strict local order to avoid locking and data movement.
- _Tang et al. (PPoPP '20)_ - XIndex uses delta buffers and non-blocking retraining, while LOFT keeps inserts in place and uses shadow-node synchronization instead of buffer compaction.

## My Notes

<!-- empty; left for the human reader -->

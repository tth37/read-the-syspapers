---
title: "Understanding and Optimizing Database Pushdown on Disaggregated Storage"
oneline: "Moves pushdown decisions to runtime with table-aware costing, admission control, hybrid DRAM/SSD tables, and critical-path scheduling for modern disaggregated storage."
authors:
  - "Hua Zhang"
  - "Xiao Li"
  - "Yuebin Bai"
  - "Ming Liu"
affiliations:
  - "University of Wisconsin-Madison, Madison, WI, USA"
  - "Beihang University, Beijing, China"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790243"
code_url: "https://github.com/netlab-wisconsin/TapDB"
tags:
  - databases
  - disaggregation
  - storage
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

TapDB argues that database pushdown on modern disaggregated storage is no longer mostly a network-saving problem; it is a compute-scarcity problem on storage nodes. Its answer is to delay pushdown decisions until runtime, learn table-sensitive operator costs in situ, cap pushdown concurrency, spill temporary tables across DRAM and SSD, and schedule operators by query critical path. On SSB and TPC-H over recent storage generations, that combination improves over prior pushdown designs by `1.3x-2.3x`.

## Problem

The paper starts from a hardware trend that quietly invalidates much of the older pushdown literature. Across four storage-node generations in the authors' cluster, network density rises from `1 Gbps/core` to `12.5 Gbps/core`, and storage I/O density rises from `37.5K` to `500K IOPS/core`, while CPU and memory capability per core improve much more slowly. In older systems, pushing operators to storage helped because it traded expensive network and I/O for cheap local computation. In newer systems, the same move often just overloads a weak storage CPU.

That shift breaks both major pushdown families the authors study. Heuristic pushdown and cost-driven pushdown still speed up queries on the older Gen1/Gen2 appliances, but on Gen3/Gen4 they become net losses: the heuristic design slows benchmarks by about `40-55%`, and the cost-driven design by about `36-45%`. The runtime breakdown explains why. On newer nodes, compute dominates pushdown execution time, often around three quarters of the total, so "save bytes on the wire" is no longer the right first-order objective.

The authors then isolate three concrete failure modes. First, existing cost models are table-structure agnostic, so they mispredict operator speed when row layout, data type, skew, or wide-table arithmetic change the true compute cost. Second, newer storage nodes have much smaller interference-free regions: for CPU utilization, the safe window shrinks from roughly `[0, 68%]` and `[0, 65%]` on old nodes to `[0, 33%]` and `[0, 28%]` on new ones, with similar collapse for memory headroom. Third, once queries become compute-bound, the operator scheduler on the storage node matters a lot, yet prior pushdown designs mostly treat it as an implementation detail.

## Key Insight

The central proposition is that pushdown should stop being an early, mostly static policy decision and become a late, runtime-validated execution decision. If the system waits until upstream operators have produced partial data, it can observe the actual table characteristics, estimate the operator's real cost on the current storage target, and reject pushdown when the node is already too contended.

That shift only works if the system also protects the pushed-down operator after the decision is made. TapDB therefore treats runtime estimation, admission control, memory management, and operator scheduling as one connected problem. The paper's memorable claim is not merely "learn a better cost model," but "trade abundant network and storage bandwidth for scarce storage-node compute, and enforce that tradeoff continuously during execution."

## Design

TapDB contributes four mechanisms. The first is a table-aware learning-based cost estimator. Instead of relying on offline per-operator profiles, TapDB waits for partial inputs, uses equidistant sampling to build representative table samples, estimates input cardinality eagerly from upstream messages, and feeds those observations into an online linear regression model. For skewed tables, it inserts a Pre-Scan Balancing Operator that repartitions data into smaller uniform segments before scan, so sampled cost better predicts full-table cost. The goal is pragmatic: make pushdown decisions with the actual table structure in view rather than with a generic operator constant.

The second mechanism is admission control. Even a correctly estimated operator can become a bad pushdown candidate if the storage node is already outside its interference-tolerant window. TapDB therefore scales the predicted execution cost by an adaptive factor `A`, updated online from the gap between estimated and observed runtimes. When contention rises, `A` rises too, making pushdown look more expensive and causing more operators to stay on compute nodes. This is a simple control loop, but it directly targets the paper's second root cause: modern storage nodes have little slack.

The third mechanism is `HBTable`, a DRAM-SSD hybrid temporary table. Each table has a manifest plus DRAM and SSD regions organized as circular buffers. Appends go to memory when possible; otherwise tuples spill to SSD. More importantly, TapDB lets high-priority tables borrow memory from low-priority ones through a ballooning-style lend/redistribute protocol. That expands effective memory capacity and avoids stalling critical operators just because another temporary table is occupying DRAM.

The fourth mechanism is a critical path-driven scheduler. The paper formalizes query execution as an NP-hard scheduling problem over the operator DAG, then uses a priority heuristic: operators on the critical path get highest priority, operators on urgent bypass paths that unblock the critical path come next, and other bypass operators come last. If a high-priority operator becomes runnable but resources are tied up by lower-priority work, TapDB yields the lower-priority operator and reallocates CPU and memory. This is more query-structure aware than `FCFS`, `RR`, `SJF`, or even multi-resource packing alone.

## Evaluation

The prototype extends FPDB, disables caching, adds the River online-learning library and a CAF-based execution engine, and runs on one x86 compute server plus four generations of disaggregated storage nodes. The workloads are SSB and TPC-H at scale factors `1`, `30`, `100`, and `200`, with Parquet tables partitioned into `50 MB` chunks. That is a sensible setup for the paper's claim because it exercises both operator diversity and the storage-node hardware trend the authors emphasize.

Against the cost-driven baseline on Gen3/Gen4 storage, TapDB improves SSB by `2.3x/1.3x/1.4x/1.3x` and `1.9x/1.7x/1.3x/1.5x` across scale factors `1/30/100/200`; on TPC-H the gains are `1.7x/1.7x/1.7x/1.6x` and `1.7x/1.8x/2.1x/1.8x`. Relative to non-pushdown execution, TapDB still gains `1.1x-6.9x` on modern nodes, but only about `6.5%-8.1%` on old nodes, which actually strengthens the paper's story: this is a design for new disaggregated storage hardware, not a universal win regardless of platform.

The component studies are also informative. The table-aware estimator reduces runtime by `22.7%` and `36.3%` on SSB, and `42.1%` and `45.4%` on TPC-H, on Gen4 and Gen3 respectively, with average relative mean absolute error around `0.16`. Admission control adds another `13-15%` average improvement, while `HBTable` contributes roughly `9-17%` depending on workload and node generation. The scheduler beats the best characterization-study baselines, `WFS` and `Tetris`, by around `9-13%`. I found that evidence fairly convincing because each mechanism is evaluated against the exact failure mode it was introduced to address, not just folded into the end-to-end result.

## Novelty & Impact

Relative to _Depoutovitch et al. (SIGMOD '20)_, which presents Taurus for cloud disaggregated databases, TapDB's novelty is not simply "more pushdown," but recognizing that the old heuristic assumption breaks once storage-node compute becomes scarce. Relative to _Yang et al. (VLDB J. '24)_, which adds adaptive pushdown and rejection, TapDB pushes the idea further by making table-sensitive runtime costing, concurrency control, memory expansion, and DAG-aware scheduling all part of one design. Relative to _Yang et al. (PVLDB '21)_, it also deemphasizes caching and focuses directly on execution-time pushdown quality.

That makes the paper likely to matter to two groups. One is researchers working on disaggregated storage and cloud OLAP engines, because it reframes pushdown as a runtime resource-management problem. The other is practitioners building computational-storage or near-data analytics systems, because TapDB offers concrete mechanisms for when storage offload stops being "free."

## Limitations

TapDB depends on offline bootstrapping plus online retraining, so portability is not free. A new hardware platform, storage stack, or operator implementation may require fresh synthetic-query training data before the estimator behaves well. The paper also hard-codes some operator semantics into the scheduler's urgent-bypass classification, which means the scheduler is not purely generic.

The evaluation is strongest on the authors' own FPDB-based prototype and on benchmark OLAP queries. It does not show whether the same gains survive in a production engine with richer optimizers, mixed tenants, or non-Parquet data formats. The design also explicitly trades more network traffic and SSD activity for lower CPU and DRAM pressure, so environments that are bandwidth-poor rather than compute-poor may see smaller gains or even lose. Finally, some overhead numbers in the mechanism studies are modest but nonzero, which means lightly skewed or lightly contended workloads may not need the full TapDB machinery.

## Related Work

- _Depoutovitch et al. (SIGMOD '20)_ — Taurus treats pushdown as a largely heuristic near-storage optimization, whereas TapDB argues that modern storage hardware makes runtime validation and scheduling necessary.
- _Yang et al. (PVLDB '21)_ — FlexPushdownDB combines pushdown with caching in a cloud DBMS, but still assumes the main question is whether data-movement savings justify offload.
- _Yang et al. (VLDB J. '24)_ — FlexpushdownDB's adaptive pushdown adds storage-side rejection under load; TapDB keeps that spirit but replaces static assumptions with table-aware costing and broader execution control.
- _Jo et al. (VLDB '16)_ — YourSQL pushes computation into storage devices themselves, while TapDB targets general-purpose disaggregated storage nodes and focuses on operator-level scheduling and contention.

## My Notes

<!-- empty; left for the human reader -->

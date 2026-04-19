---
title: "CAPSys: Contention-aware task placement for data stream processing"
oneline: "CAPSys profiles per-operator CPU, state, and network cost, then searches Flink task placements that balance contention fast enough to stay inside the auto-scaling loop."
authors:
  - "Yuanli Wang"
  - "Lei Huang"
  - "Zikun Wang"
  - "Vasiliki Kalavri"
  - "Ibrahim Matta"
affiliations:
  - "Boston University"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3696085"
code_url: "https://github.com/CASP-Systems-BU/CAPSys"
tags:
  - scheduling
  - datacenter
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CAPSys argues that task placement in stream processors should not be treated as a random byproduct of scaling. It profiles each operator's CPU, state-access, and network cost, then uses CAPS to search for placements that keep hot tasks balanced across workers fast enough to sit in the DS2 reconfiguration loop. On Apache Flink, that raises throughput, lowers backpressure, and makes auto-scaling converge with fewer bad steps.

## Problem

Slot-oriented stream processing systems such as Apache Flink and Storm compute a static placement at deployment or reconfiguration time, but their built-in policies largely assume task homogeneity. That is a bad fit for real dataflows, which mix lightweight maps, state-heavy windows and joins, and compute-heavy inference operators. The paper shows the gap directly: on `Q1-sliding`, exhaustive search over 80 placements on a 4-worker, 16-slot cluster finds a best plan at `14k` records/s with `6.8%` backpressure and a worst plan at `9k` records/s with `86.4%` backpressure. Bad placement also contaminates elasticity control, because DS2-style auto-scalers learn capacity from the metrics produced by the current deployment. If that deployment is already bottlenecked by co-location, the controller over-provisions or keeps reconfiguring. Existing alternatives are either manual, like R-Storm and Flink's fine-grained hints, or too slow for online use, like ODRP-style exact optimization.

## Key Insight

The paper's central claim is that online placement does not need a precise end-to-end performance model; it needs a fast estimate of resource imbalance on the bottleneck worker. CAPSys therefore scores a plan by how far its hottest worker deviates from an ideally balanced cluster along three dimensions: compute, state access, and network. That abstraction is justified by the empirical study. On `Q2-join`, co-locating too many tumbling-window join tasks drops throughput from about `110k` to `91k` records/s and raises backpressure from at most `4%` to `32%`. On `Q3-inf` with a `1 Gbps` outbound cap, high-contention placements fall from `1555` to `1185` records/s and push backpressure from `12%` to `37%`. CAPSys takes the lesson literally: avoid stacking the same hot resource on one worker, and the search can stay simple enough to run online.

## Design

CAPSys wraps Apache Flink and DS2 with a placement controller. A profiling job first isolates each operator on its own Task Manager and measures per-record CPU utilization, RocksDB read/write bytes, and emitted bytes per second. DS2 then chooses operator parallelism and produces the physical execution graph; the placement controller multiplies target rates by these unit costs, runs CAPS, and hands the result to a custom Flink scheduler implemented with an extended `ResourceProfile` and a custom `SlotMatchingStrategy`. CAPS models a feasible plan over a physical graph `Gp` and a homogeneous worker cluster `Gw`, then assigns it a cost vector `C = [Ccpu, Cio, Cnet]`, where each dimension is a normalized imbalance between the most loaded worker and the ideal balanced load. Search proceeds as DFS with an outer search over operators and an inner search over workers, plus duplicate elimination for equivalent branches. The main optimization is threshold-based pruning with `alpha = [alpha_cpu, alpha_io, alpha_net]`: because partial worker load grows monotonically, any branch that already exceeds a threshold can be cut immediately. CAPS also reorders resource-heavy operators toward the top of the tree for earlier pruning, auto-tunes feasible threshold vectors by gradual relaxation, and parallelizes exploration across threads. The model intentionally assumes homogeneous workers, enough slots, and identical tasks within one operator; skew mitigation, slot sharing, and WAN-aware placement are left outside the core formulation.

## Evaluation

The end-to-end results line up with the paper's mechanism claim. In single-query runs on six workloads over four `m5d.2xlarge` workers with eight slots each, CAPSys beats Flink `default` and `evenly` on throughput, backpressure, and latency every time, cutting backpressure by `84%` and average latency by `48%` on average; on `Q5-aggregate`, it reaches up to `6x` the throughput of `default` and `5.5x` that of `evenly`. In the multi-tenant experiment on an 18-worker, 144-slot cluster, it is the only policy that hits the target throughput for all six concurrent queries. Against ODRP on `Q3-inf`, CAPSys reaches `4236` records/s with `0.5%` backpressure using `27` slots and computes the plan in `0.2 s`, while ODRP takes `1607-4037 s` and either under-provisions badly or needs `32` slots to get close. Under variable workloads, CAPSys lets DS2 hit the target rate in all four controlled scaling steps without over-provisioning and avoids up to eight extra reconfiguration actions in the longer convergence experiment. The scalability numbers are also practical: CAPS finds satisfactory placements in up to `100 ms` for deployments with up to `256` tasks, while offline threshold auto-tuning takes `1.16 s` for `64` tasks and `125.08 s` for `1024` tasks.

## Novelty & Impact

The novelty is not that placement matters, but that placement and auto-scaling are treated as one control problem and reduced to a contention model cheap enough to run inside the loop. The contribution is the combination of profiling, imbalance-based costing, pruning, operator reordering, and scheduler integration that turns that idea into a practical Flink system. For stream-processing researchers, the paper is strong evidence that random or count-balanced placement leaves large performance on the table; for control-plane builders, it is a credible recipe for inserting placement into an existing Flink-plus-DS2 stack.

## Limitations

CAPSys assumes homogeneous workers and treats tasks of the same operator as equivalent, so heavy data skew is outside the model unless another partitioning mechanism first normalizes the work. Its cost profiles are also measured in isolation and cached, which is efficient but risks drift when workloads or interference patterns change; the paper proposes online reprofiling only as future work. More generally, the evaluation is tied to Apache Flink `1.16.2`, six queries, and mostly homogeneous cloud clusters, so the paper establishes practicality for this setting rather than generality across heterogeneous or geo-distributed stream processors.

## Related Work

- _Cardellini et al. (DEBS '16)_ - formulates operator placement for distributed stream processing as an optimization problem, while CAPSys narrows the objective to contention balance so it can run in online reconfiguration settings.
- _Cardellini et al. (SIGMETRICS Perform. Eval. Rev. '17)_ - ODRP jointly optimizes replication and placement with an exact solver, whereas CAPSys trades exact optimality for pruning and fast response inside the control loop.
- _Peng et al. (Middleware '15)_ - R-Storm makes Storm scheduling resource-aware using operator resource descriptions from users, while CAPSys profiles operator costs and searches placements automatically.
- _Jonathan et al. (Middleware '20)_ - WASP targets wide-area adaptive stream processing where network delay dominates, whereas CAPSys focuses on compute, state, and network contention inside a datacenter cluster.

## My Notes

<!-- empty; left for the human reader -->

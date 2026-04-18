---
title: "PRED: Performance-oriented Random Early Detection for Consistently Stable Performance in Datacenters"
oneline: "PRED keeps RED traffic-aware and stable by scaling its marking slope with concurrent flows and tuning it with conservative A/B tests on queue utility."
authors:
  - "Xinle Du"
  - "Tong Li"
  - "Guangmeng Zhou"
  - "Zhuotao Liu"
  - "Hanlin Huang"
  - "Xiangyu Gao"
  - "Mowei Wang"
  - "Kun Tan"
  - "Ke Xu"
affiliations:
  - "Huawei Technologies"
  - "Renmin University of China"
  - "Tsinghua University"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - networking
  - datacenter
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

PRED keeps standard RED/ECN but makes it adaptive in a controlled way. It scales RED's marking slope with measured flow concurrency, then uses conservative A/B-tested queue tuning to move toward the queue length each workload wants. That beats static RED settings without the tail instability the paper observes from DRL-based tuning.

## Problem

The paper starts from a practical fact: RED plus ECN is already widely supported in datacenter switches, while many newer congestion-control proposals need host, NIC, or switch changes that are slow to roll out.

Static RED fails because it encodes one queue target while traffic keeps changing. The paper highlights two effects. First, steady-state queue length grows with the number of concurrent flows at a bottleneck, so one fixed threshold either underutilizes the link at low concurrency or leaves too much queue at high concurrency. Second, flow-size distributions want different queues: short-flow-heavy workloads benefit from a larger queue that avoids over-marking brief bursts, while large-flow-heavy workloads want a smaller queue that suppresses standing backlog. Case-based designs like ECNsharp hard-code a few states, and ACC's DRL controller adapts more broadly, but the paper argues ACC reacts too slowly to fast concurrency changes and sometimes picks bad RED settings, which hurts tail FCT.

## Key Insight

The central move is to reinterpret RED as a controller for steady-state queue length instead of as a pair of thresholds. The paper rewrites RED from `(minK, maxK, maxP)` into point-slope form `(minK, lambda)`, where `lambda = maxP / (maxK - minK)`. In that form, increasing `lambda` monotonically shortens the converged queue.

That lets the paper split adaptation into two jobs. Concurrency changes are fast and structured, so the switch should measure flow count `N` and scale `lambda` explicitly. Workload preference is slower and harder to model, so it should be found by cautious online testing. PRED therefore uses Flow Concurrent Stabilizer (FCS) for the first problem and Queue Length Adjuster (QLA) for the second.

## Design

FCS counts flows directly in the switch. For each port and `T_FCS` interval, PRED hashes packet five-tuples plus an interval sequence number into a bitmap, counts newly seen flows, and estimates concurrency as `N = max(n_last, n)`. It then scales RED's slope with a monotone function `f(N)`. The authors find `f(N) = N` works better than `sqrt(N)` or `N^2` because the analytic model's idealized assumptions do not hold exactly in practice.

QLA handles the residual question: after concurrency is accounted for, where should the queue settle for this workload? It defines a utility over normalized goodput and average queue length, compares `lambda + delta` against `lambda - delta`, and only updates when two controlled trials prefer the same direction. The rule is AIAD rather than binary search or learned prediction because the paper prioritizes stable convergence over speed.

In the prototype, FCS runs on the Tofino data plane, while QLA runs on the control plane because Tofino 1 lacks enough stages for both modules together.

## Evaluation

The paper evaluates PRED on a physical Tofino testbed and in NS-3. On the testbed, PRED keeps throughput near line rate while preventing queue length from growing with flow concurrency. Relative to static-threshold baselines, it reduces queue length by 66%, from about 25 packets to about 15 packets, and cuts short-flow FCT by as much as 80%.

The simulation study is stronger because it removes the control-plane bottleneck and scales to a 128-host leaf-spine topology. Under WebSearch traffic at 90% load, PRED reduces small-flow 99th-percentile FCT by 68% to 80% relative to ECN, ECNsharp, and CoDel. The ablations show that FCS captures most of the benefit over static RED, while QLA is needed to adapt to changing flow-size distributions. Against ACC, even when ACC is trained and tested on the same trace, PRED lowers 99th-percentile FCT by 34%. At 100 Gbps with thousands of concurrent flows, PRED still outperforms ECN-style baselines, though it does not match HPCC's near-zero queues.

## Novelty & Impact

The novelty is not a new congestion signal, but a new way to control an old one. Relative to _Yan et al. (SIGCOMM '21)_, PRED replaces DRL with explicit concurrency stabilization plus verified small-step search. Relative to _Zhang et al. (CoNEXT '19)_, it does not introduce more fixed ECN cases; it makes RED's existing parameters adapt continuously. Relative to _Li et al. (SIGCOMM '19)_, it accepts higher queues than HPCC in exchange for switch-only deployability.

That middle ground is the paper's likely impact: it reframes RED tuning as steady-state queue control and shows that interpretable adaptation can still be competitive in datacenter networks.

## Limitations

The most important limit is control range: in the authors' experiments, PRED cannot keep queues stable once more than about 32 long flows share a bottleneck. They argue that regime is uncommon, but it means the mechanism is not universal. The prototype also runs QLA on the control plane of Tofino 1, so convergence is slower than the intended all-data-plane design.

FCS itself remains heuristic. The choice `f(N) = N` works well empirically, but it is derived from a simplified fluid model and then tuned experimentally; the paper does not give a formal stability proof for the combined controller. The evaluation also says little about multi-tenant fairness or extreme flow-count estimation errors.

## Related Work

- _Yan et al. (SIGCOMM '21)_ — ACC also auto-tunes RED, but it uses DRL over queue and rate features, while PRED uses direct concurrency measurement plus conservative A/B-tested control.
- _Zhang et al. (CoNEXT '19)_ — ECNsharp augments ECN with instantaneous and persistent thresholds, whereas PRED keeps standard RED semantics and adapts its parameters continuously.
- _Li et al. (SIGCOMM '19)_ — HPCC achieves lower queues with INT-guided end-host control, while PRED trades some optimality for incremental switch-only deployment.

## My Notes

<!-- empty; left for the human reader -->

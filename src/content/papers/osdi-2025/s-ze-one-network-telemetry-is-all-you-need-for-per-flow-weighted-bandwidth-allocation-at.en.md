---
title: "Söze: One Network Telemetry Is All You Need for Per-flow Weighted Bandwidth Allocation at Scale"
oneline: "Söze repurposes one per-packet max queueing-delay signal into a decentralized control loop for per-flow weighted max-min bandwidth allocation."
authors:
  - "Weitao Wang"
  - "T. S. Eugene Ng"
affiliations:
  - "Rice University"
conference: osdi-2025
tags:
  - networking
  - datacenter
  - observability
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Söze uses one in-band telemetry signal, the maximum queueing delay on a flow's path, as the only coordination channel for weighted sharing. Each sender compares observed `maxQD` with the target delay implied by its current rate-per-weight and updates multiplicatively until they match, yielding per-flow weighted max-min allocation without per-flow switch state, topology knowledge, or a centralized allocator.

## Problem

The paper targets a gap between what cloud applications want and what datacenter transports normally provide. Critical-path flows, coflow stragglers, and multi-flow jobs often benefit from unequal sharing, yet common transports such as DCTCP, Swift, or HPCC still allocate bandwidth mainly from current contention rather than application-supplied weights. The obvious implementations do not scale cleanly: switch-side WFQ needs per-flow queues and path-wide control-plane updates, while centralized allocators need topology, routing, and flow metadata and must recompute rates whenever flows arrive, finish, or change weight. The key difficulty is that a flow's bottleneck hop is not known in advance, so the system must discover and enforce the right weighted share without explicit global knowledge.

## Key Insight

Söze's core observation is that weighted fairness on a saturated link can be rewritten as two decentralized tests: the link is fully utilized, and all bottlenecked flows have the same rate-per-weight `r / w`. Queueing delay already reveals the first condition because its derivative is tied to whether arrival rate exceeds link bandwidth. Söze then gives queueing delay a second role: a monotonic target function `T(r / w)` makes each fair-share value correspond to a unique target delay, so a sender can compare the observed delay with the delay its own `r / w` should produce.

This extends to arbitrary topologies because, under weighted max-min fairness, a flow has the largest rate-per-weight exactly at its bottleneck hop. The paper shows that the bottleneck therefore appears as the hop contributing the largest relevant queueing delay on that path, so carrying only the maximum per-hop delay, `maxQD`, is enough to expose the right feedback.

## Design

The data path is intentionally tiny. Each packet carries a two-byte field for the maximum queueing delay seen so far. Every switch egress compares its local queueing signal against that field and keeps the larger one; the receiver echoes `maxQD` back in the ACK. No switch needs per-flow state, topology knowledge, or active fair-share computation.

All control logic lives at the sender. Each flow gets a weight from the application via a socket or RPC API. The sender computes a target delay `T(r / w)` using parameters `p`, `k`, `alpha`, and `beta`, then updates its rate with a multiplicative function based on the inverse target function and the observed `maxQD`: if observed delay is above target, it backs off; if below, it speeds up. The paper proves convergence when the gain `m` is between 0 and 2 and the delay scale is large enough to maintain a non-zero queue. The same loop works for a single bottleneck link, kernel TCP, or rate-based eRPC pacing.

## Evaluation

The implementation is lightweight: 9 lines of Tofino code for queueing telemetry, a 241-line Linux congestion-control module, and a 1,972-line eRPC integration. Experiments run on a 25 Gbps eRPC testbed and in NS-3 on a 1,024-server fat-tree.

Söze still behaves like a good transport: in step-in and step-out tests it reaches higher utilization and converges faster than Timely on the testbed, and it produces more stable, more accurate rates than HPCC in simulation. Under RPC workloads it also lowers FCT slowdown, especially for short flows.

For the main claim, the microbenchmarks are stronger than the policy case studies. Söze tracks weighted max-min allocation even when a flow's bottleneck hop changes with its weight, and the new rates settle in about 10 RTTs. It is also more fine grained than approximating weights with integer numbers of connections or a few physical WRR queues. The application studies show why the primitive matters: it shortens critical paths, mitigates coflow stragglers, enables altruistic sharing, and lowers TPC-H completion time to 0.79x of baseline on average and 0.59x for the best job. The caveat is that several policies are hand-crafted examples rather than production controllers.

## Novelty & Impact

Relative to _Nagaraj et al. (SIGCOMM '16)_, Söze removes switch-resident WFQ from the enforcement path. Relative to _Jose et al. (HotNets '15)_, switches no longer compute fair shares; they only stamp telemetry. Relative to host-only heuristics such as _Vamanan et al. (SIGCOMM '12)_ or _Crowcroft and Oechslin (CCR '98)_, Söze aims for a specific weighted max-min equilibrium instead of merely making some flows more aggressive.

The broader impact is conceptual. Söze treats INT not as a visibility feature but as a control substrate: a passive signal from commodity switches is enough for end hosts to coordinate on weighted allocation. That framing is likely to matter beyond this exact algorithm.

## Limitations

Söze still needs deployment hooks: telemetry-capable switches, ACK reflection, and host stacks that accept application-supplied weights. That is lighter than implementing WFQ in hardware, but it is not zero-cost.

The paper also leaves weight policy mostly out of scope. It shows how to realize chosen weights, not how a provider should assign, cap, or audit them in a hostile multi-tenant environment; the discussion's logging-based enforcement sketch is not evaluated. Most evidence also comes from testbeds and simulation under fat-trees and incasts rather than a production deployment. Because queueing delay is the signal, Söze intentionally maintains a non-zero queue.

## Related Work

- _Nagaraj et al. (SIGCOMM '16)_ — NumFabric computes switch-side WFQ weights for datacenter objectives, whereas Söze removes WFQ from switches and enforces weights through host-side control.
- _Jose et al. (HotNets '15)_ — PERC has switches compute and communicate fair shares directly; Söze only needs switches to stamp telemetry and lets end hosts do the math.
- _Vamanan et al. (SIGCOMM '12)_ — D2TCP changes TCP aggressiveness according to deadlines, but it does not aim for precise weighted max-min allocation across arbitrary bottlenecks.
- _Crowcroft and Oechslin (CCR '98)_ — MulTCP makes one flow behave like multiple TCPs, while Söze derives a dedicated control law whose equilibrium corresponds to weighted fairness.

## My Notes

<!-- empty; left for the human reader -->

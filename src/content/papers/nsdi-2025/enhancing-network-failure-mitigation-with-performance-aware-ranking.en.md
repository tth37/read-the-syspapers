---
title: "Enhancing Network Failure Mitigation with Performance-Aware Ranking"
oneline: "SWARM ranks datacenter failure mitigations by estimated end-to-end throughput and FCT, so it can keep, restore, or reweight links when disabling them would hurt users more."
authors:
  - "Pooria Namyar"
  - "Arvin Ghavidel"
  - "Daniel Crankshaw"
  - "Daniel S. Berger"
  - "Kevin Hsieh"
  - "Srikanth Kandula"
  - "Ramesh Govindan"
  - "Behnaz Arzani"
affiliations:
  - "University of Southern California"
  - "Microsoft"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - networking
  - datacenter
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SWARM ranks datacenter failure mitigations by estimated end-to-end throughput and flow completion time, not by residual uplinks, path count, or max utilization. That lets it choose actions such as doing nothing, restoring a previously disabled link, or changing WCMP when blindly disabling hardware would hurt users more.

## Problem

Cloud networks regularly see lossy links, packet corruption, and congestion caused by partial capacity loss, while repair can take hours or days. Operators therefore install temporary mitigations, and large providers increasingly automate that choice. The paper notes that Azure wants mitigations within five minutes of failure localization and already automates most incidents.

Existing ranking logic is too crude. Operator playbooks use local thresholds, CorrOpt uses path diversity, and NetPilot uses proxy metrics such as utilization or loss. Those proxies can pick harmful actions: a mildly lossy link may be worth keeping if disabling it creates worse congestion, and a second failure may even make it optimal to restore a previously disabled link. Good mitigation depends on failure intensity, location, traffic demand, routing, and transport behavior together, not on one local signal.

## Key Insight

The central claim is that mitigation ranking does not require packet-perfect simulation; it only needs enough fidelity to preserve the ordering of candidate actions by user-visible connection-level performance. SWARM therefore estimates distributions of end-to-end throughput and FCT for each action and optimizes those directly.

Two modeling choices make that practical. SWARM samples uncertain traffic and routing instead of assuming fixed inputs, and it separates long and short flows. Long flows are shaped by shifting bottlenecks and loss-limited transport behavior; short flows are dominated by startup, queueing, and a few RTTs. That split gives better ranking fidelity without blowing the response budget.

## Design

SWARM takes the topology, already-active mitigations, the localized failure and its characteristics, probabilistic traffic summaries, a candidate action set, and a comparator. The comparator can be priority-based or a linear combination of CLP metrics. Internally, SWARM models the network as a graph with capacities, drop rates, and routing tables, then samples demand matrices from flow-arrival, flow-size, and server-pair communication distributions. For each demand sample, it also samples ECMP/WCMP routing outcomes; the number of traffic and routing samples is chosen with DKW-style confidence bounds.

The CLPEstimator then splits long and short flows. For long flows, SWARM runs an epoch-based estimator: it adds arrivals over time, recomputes rates each epoch, and combines an empirically measured loss-limited throughput cap with a demand-aware max-min-fair water-filling extension. That is how it distinguishes capacity-limited from loss-limited behavior. For short flows, it estimates FCT as "number of RTTs to finish" times "average RTT on the path," where both the RTT-count distribution and queueing-delay distribution come from offline experiments.

The rest of the design is about scale. SWARM uses approximate fair-share computation, parallel evaluation of traffic and routing samples, pipelining, warm starts to avoid empty-network artifacts, fewer epochs when distant snapshots are effectively independent, and POP-style traffic downscaling. The point is not exact prediction; it is fast, high-fidelity ordering of candidate mitigations.

## Evaluation

The prototype is about 1,500 lines of Python. The main evaluation uses Mininet on a Clos topology and covers 57 incident scenarios across three classes: redundant-path link corruption, congestion after prior capacity loss, and ToR-local corruption. SWARM uses dozens of traffic traces, 1,000 routing samples, 200 ms epochs, and treats flows up to 150 KB as short. It is compared against thresholded versions of NetPilot, CorrOpt, and operator playbooks.

The core result is that SWARM keeps the penalty on the target metric near zero while the baselines often choose much worse actions. In Scenario 1 under PriorityFCT, SWARM's worst-case 99p FCT penalty is 0.1%, versus 79.3% for CorrOpt-75. In Scenario 2, where prior mitigations have already reduced path diversity and a new fiber cut creates congestion, the next-best approach can be 38% worse on 99p FCT because it keeps disabling links. In Scenario 3, which CorrOpt and NetPilot do not support, SWARM's worst-case FCT penalty is 28.9% versus 57% for the best operator rule. The paper also shows that SWARM uses a genuinely broader action space: in more than a quarter of Scenario 1 incidents it chooses no action on the second failure, and sometimes it restores a previously disabled lossy link.

Scalability is the other important result. SWARM finds the best mitigation on a 16K-server Clos in under five minutes. The approximate fair-share routine gives 36.3x speedup with at most 0.9% error, 2x traffic downscaling adds 73.6x speedup, and warm start plus epoch reduction adds another 105.7x with at most 1.2% error. NS3 and a physical Arista-based testbed tell the same story: SWARM picks the optimal or near-optimal action, while poor choices can exceed 1,000% penalty on tail FCT. That supports the paper's claim, though the evidence is still emulation, simulation, and testbed validation rather than live production deployment.

## Novelty & Impact

SWARM's novelty is the objective itself: it ranks mitigations by predicted end-to-end throughput and FCT instead of by proxy metrics. That reframes datacenter incident response from "which local heuristic looks safe?" to "which action hurts users least?" Relative to NetPilot and CorrOpt, it also supports a broader action space and broader failure models, including keeping or restoring capacity and handling failures at or below a ToR. The obvious downstream users are automated datacenter-operations systems and future what-if analysis tools. This is a new mechanism plus a new operational framing, not a pure measurement paper.

## Limitations

SWARM depends on good inputs: accurate enough failure localization, historical traffic distributions, and a predefined mapping from failure type to candidate mitigations. If those inputs drift or are wrong, the ranking can degrade. The paper explicitly expects operators to rerun SWARM as new evidence arrives, which is practical but still an operational dependency.

The estimator is also intentionally approximate. Loss-limited long-flow behavior and short-flow RTT counts come from offline calibration rather than first-principles transport modeling, and the system only models two flow classes. The scope is narrower than the title suggests: the paper focuses on Clos-like ECMP/WCMP datacenters, does not yet model lossless RDMA/PAUSE behavior or transient reboot effects, and does not report a live production deployment. The evidence is strong, but it is still pre-deployment evidence.

## Related Work

- _Wu et al. (SIGCOMM '12)_ - `NetPilot` automates mitigation using utilization-style health metrics, while SWARM optimizes estimated end-to-end CLP under the actual failed network state.
- _Zhuo et al. (SIGCOMM '17)_ - `CorrOpt` decides whether to disable corrupted links based on residual path diversity, whereas SWARM can keep or even restore lossy links when that better preserves throughput and FCT.
- _Alipourfard et al. (SOSP '19)_ - `Janus` estimates the risk of planned datacenter network changes; SWARM instead targets reactive incident mitigation with performance-aware ranking.
- _Bogle et al. (SIGCOMM '19)_ - `TEAVAR` optimizes WAN traffic engineering under failure risk, while SWARM focuses on datacenter incidents and explicitly models short-flow FCT alongside long-flow throughput.

## My Notes

<!-- empty; left for the human reader -->

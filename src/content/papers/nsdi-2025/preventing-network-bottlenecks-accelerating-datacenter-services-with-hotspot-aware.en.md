---
title: "Preventing Network Bottlenecks: Accelerating Datacenter Services with Hotspot-Aware Placement for Compute and Storage"
oneline: "Google cuts persistent ToR hotspots by placing tasks and storage on colder racks, reducing hot ToRs by 90% and Colossus p95 network latency by 50-80%."
authors:
  - "Hamid Hajabdolali Bazzaz"
  - "Yingjie Bi"
  - "Weiwu Pang"
  - "Minlan Yu"
  - "Ramesh Govindan"
  - "Neal Cardwell"
  - "Nandita Dukkipati"
  - "Meng-Jung Tsai"
  - "Chris DeForeest"
  - "Yuxue Jin"
  - "Charlie Carver"
  - "Jan Kopański"
  - "Liqun Cheng"
  - "Amin Vahdat"
affiliations:
  - "Google"
  - "Harvard University"
  - "University of Southern California"
  - "Columbia University"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - networking
  - datacenter
  - storage
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

The paper argues that persistent datacenter hotspots are often a placement problem, not a transport problem. Google adds two lightweight heuristics: Borg prefers cooler ToRs for task placement and migration, and Colossus prefers racks whose uplink capacity is high relative to installed storage. In production, that cuts hot compute ToRs by 90% and materially lowers storage and query tail latency.

## Problem

Month-long fleet telemetry shows ToR-to-aggregation links are the main hotspot location: about 10x more likely to be hot than host-to-ToR links and about 2x more likely than DCNI links. About a third last under an hour, nearly 40% last 1-12 hours, and roughly 13% last 1 day-2 weeks. Mixed and disk racks account for about 90% of hotspots, so storage-heavy services absorb most of the pain.

The cause is structural imbalance plus network-blind placement. ToRs are provisioned with oversubscription, then compute refreshes, denser or faster disks, or temporary uplink reductions change rack-level demand or supply. Borg and Colossus historically place tasks and chunks mostly as if the network were unconstrained, which can concentrate network-intensive workers or too much storage behind the same ToR. Congestion control, load balancing, and traffic engineering help use existing paths, but they cannot create missing ToR uplink capacity.

## Key Insight

Persistent ToR hotspots should be handled by changing where work and data land, not only by improving in-network control. The paper shows a threshold effect: many applications stay reasonable until utilization approaches about 75%, after which tail latency climbs sharply. Since average ToR utilization across the fleet is still low, a best-effort bias toward colder and better-provisioned racks can remove much of the pain without turning the network into a fully reserved first-class resource. The schedulers do not need globally optimal joint placement; they need enough network awareness to stop making obviously bad rack-level decisions.

## Design

The first mechanism is ToR-utilization-aware task placement and migration (UTP) in Borg. Borg already evaluates a random sample of candidate machines against many objectives. UTP leaves that structure intact and changes a lower-priority load-balancing score so machines under cooler ToRs look better. The score combines instantaneous ToR utilization with the task's peak bandwidth estimate. When a ToR exceeds 75% utilization, Borg reactively migrates high-bandwidth, latency-tolerant tasks first, and only when availability budgets permit. The goal is to reduce hotspots with minimal disruption, not to solve a global network optimization problem.

The second mechanism is ToR-capacity-aware chunk placement (CCP) in Colossus. CCP classifies storage racks as High-Uplink, Medium-Uplink, or Low-Uplink depending on how provisioned ToR uplink capacity compares with installed storage capacity, then biases new chunk placement toward High-Uplink racks. The paper keeps CCP deliberately simple and does not specify a more detailed scoring rule beyond this priority ordering.

## Evaluation

The evidence combines fleet telemetry, one day of Dapper HDD traces, seven QuerySys benchmarks, a pilot cluster, and fleet rollout. In QuerySys, the most network-heavy benchmark, shuffle flush, has 1.5x Load-tolerance at 70% utilization; materialize reaches 75%; aggregation reaches 85%; lighter queries sit at 90-95%. The compute-ratio analysis shows why: compute-heavy queries are less sensitive to network hotspots.

Colossus read/write behavior is more striking. HDD reads see 4x network-latency inflation at the 75% hotspot threshold, but only 1.5x total-latency inflation because disk time still dominates; their 2x Load-tolerance is 95%. HDD writes are much more fragile because write-back caching makes network a larger share of latency: 2x Load-tolerance is 50%, and hotspot inflation is about 4x. The paper also shows that the highest-utilization storage requests land almost exclusively on Low-Uplink racks, directly motivating CCP.

The deployment results are the main payoff. Fleetwide UTP cuts hot compute ToRs by 90%. In a pilot cluster, it reduces p98 outbound ToR utilization by 18.5% with no reported regression in Borg's other objectives, and removing proactive placement nearly doubles migrations while making network-intensive jobs about 7x more likely to land on hot ToRs. QuerySys p95 latency improves by up to 13%. In a 15-day CCP pilot, Colossus p95 network latency drops 50-80% and total HDD-read latency drops 30-60%. The evidence is persuasive for Google's environment, though it is mostly before/after operational evaluation rather than controlled comparison against stronger network-aware schedulers.

## Novelty & Impact

The paper's main contribution is a production lesson: persistent rack hotspots are often better addressed by moving work and data than by refining transport or traffic engineering alone. For large datacenter operators, it offers a low-intrusion way to make mature schedulers and storage systems network-aware.

## Limitations

The approach is explicitly best-effort: it does not guarantee SLOs, and the paper scopes itself to traditional compute/storage clusters rather than ML clusters or second-scale bursts. Much of the evidence comes from Google production telemetry and pilots, which is strong operational support but hard to reproduce externally. The paper also does not compare against a scheduler that models network as a full first-class resource, and CCP is only specified at a high level. Finally, the 5-minute hotspot windows and 30-second utilization attribution leave short-lived congestion mostly outside the study.

## Related Work

- _Chen et al. (NSDI '22)_ - NetHint exposes network structure and bottlenecks to tenants so applications can adapt, while this paper keeps hotspot handling inside the provider's scheduler and storage stack.
- _Rajasekaran et al. (NSDI '24)_ - CASSINI makes ML-job placement network-aware, whereas this paper brings the same operational lesson to traditional compute and storage services and focuses on persistent ToR imbalance.
- _Jalaparti et al. (SIGCOMM '15)_ - Corral-style network-aware scheduling reasons about bandwidth for data-parallel jobs, while this paper emphasizes simple best-effort heuristics that can be grafted onto an existing production scheduler.

## My Notes

<!-- empty; left for the human reader -->

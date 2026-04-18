---
title: "Learnings from Deploying Network QoS Alignment to Application Priorities for Storage Services"
oneline: "Aequitas maps storage RPC priorities to DSCP/WFQ queues per RPC and shows in production that fixing QoS misalignment can lower latency even after some downgrades."
authors:
  - "Matthew Buckley"
  - "Parsa Pazhooheshy"
  - "Z. Morley Mao"
  - "Nandita Dukkipati"
  - "Hamid Hajabdolali Bazzaz"
  - "Priyaranjan Jha"
  - "Yingjie Bi"
  - "Steve Middlekauff"
  - "Yashar Ganjali"
affiliations:
  - "Google LLC."
  - "University of Toronto"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - networking
  - datacenter
  - storage
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Aequitas assigns storage RPCs to network QoS classes at RPC granularity instead of trusting user-chosen QoS. The deployment study shows that this fixes priority inversion in production, and that moving traffic to a lower-weight queue can reduce latency when the nominally higher-priority queue is overloaded relative to its weight.

## Problem

The paper addresses a gap between application priorities and the DSCP/WFQ settings that switches actually use to arbitrate contention. In Google storage systems, RPCs have very different latency needs: performance-critical (PC) RPCs are interactive and tail-sensitive, non-critical (NC) RPCs are bulk storage operations, and best-effort (BE) RPCs are background work. Yet users often request QoS opportunistically after seeing SLO misses. Over time this creates the "race-to-the-top" behavior from the earlier Aequitas paper: too much traffic asks for higher QoS, the queue mix becomes unhealthy, and a supposedly higher-priority queue can deliver worse latency than a lower-priority one.

The paper argues that job-level or application-level QoS is too coarse. Even though most jobs use only one priority, the relatively small set of jobs that use two or three priorities accounts for most of the bytes. So a single job can contain latency-critical and throughput-oriented RPCs simultaneously. If all of that traffic inherits the same QoS, the network loses the information it needs to preserve the right ordering.

Deployment also has practical constraints. The system must work across several storage layers, must distinguish intra-cluster traffic from WAN paths with different bandwidth policies, and must not impose enough CPU, memory, or latency overhead to cancel the network-side gains. Most importantly, the rollout has to preserve a positive incentive for applications: if high-priority traffic regresses or users cannot understand why traffic was downgraded, adoption stalls.

## Key Insight

The paper's core claim is that priority, not RPC size, is the right scheduling signal for storage traffic, and that queue health matters more than the nominal rank of a QoS class. Aequitas therefore does not try to predict flow sizes or run a new transport. It takes application metadata, classifies each RPC as BE, NC, or PC, and maps those priorities 1:1 onto `QoSl`, `QoSm`, and `QoSh`.

The non-obvious part is the paper's load-sensitive interpretation of QoS. For two weighted-fair queues, a client can improve its service rate by moving a small amount of traffic from a higher-weight queue to a lower-weight queue when the higher-weight queue is overloaded relative to its weight. This is the paper's explanation for why downgrades are sometimes beneficial: the question is not "which queue is higher?" but "which queue is healthier given the current fleetwide mix?"

## Design

Aequitas is intentionally conservative. It uses existing switch QoS machinery rather than introducing new congestion signals or host protocols. Each storage system provides metadata features for an RPC, and Aequitas maps those features to one of the three application priorities. The network then enforces a static priority-to-QoS mapping through DSCP-marked traffic classes served by weighted fair queuing.

The implementation differs by storage layer. For lower-level (LL) storage, Aequitas runs server-side because the LL layer is mostly invisible to users and server-side deployment lets all traffic hitting the server change together. The first packets of an RPC use the original QoS; once they arrive, the LL server chooses the Aequitas QoS for the RPC and subsequent packets in either direction use the updated class. For upper-level (UL) systems such as Spanner or Bigtable-facing paths, Aequitas runs client-side so users can directly observe which QoS their RPCs will use and reason about regressions against their own SLOs.

The paper also treats rollout machinery as part of the design. Because client performance depends on the entire queue mix, the team could not infer effects from naive before/after snapshots. They added random sampling so only a chosen fraction of RPCs obeyed Aequitas, and they targeted clusters dominated by one or a few users to make cluster-level effects measurable. Analysis combines Dapper traces, which expose per-RPC priority, requested QoS, chosen QoS, and network latency decomposition, with higher-level Monarch dashboards to sanity-check tail behavior.

## Evaluation

The evidence is production-first rather than testbed-first. The team studies heavily loaded clusters, often with 50% random sampling, and compares aligned traffic against misaligned traffic from the same client or cluster.

The first result is that size is the wrong abstraction. Figure 6 shows both small and large RPCs spread across all three priorities, so size alone cannot tell the network what matters. When the authors compare RNL as a fraction of end-to-end latency, PC RPCs benefit the most from being on higher-weight QoS, while BE traffic is the least sensitive.

For a dominant Spanner client accounting for more than half of cluster traffic, aligning only 50% of traffic produces a large asymmetry: BE and NC RNL rise slightly, but PC tail latency drops dramatically. The paper reports that the reduction in maximum p99 RNL for PC traffic is more than 150 times larger than the increase in maximum p99 RNL for NC traffic. Total RPC latency shows the same pattern, which supports the claim that misaligned PC RPCs were genuinely network-bottlenecked.

The paper's most interesting case study is the client whose traffic originally sat almost entirely on `QoSm`. With queue weights `8:4:1` for `QoSh:QoSm:QoSl`, that cluster had a `QoSm:QoSl` mix of `10.69:1`, far above the unhealthy cutoff of `4:1`. Aequitas downgrades BE traffic from `QoSm` to `QoSl`, and the downgrade helps: aligned BE traffic sees lower average and much lower worst-case p99 RNL, with the maximum p99 BE RNL dropping by `18.51` standardized units. After full rollout for that client, NC RNL also improves by `31.04%`, showing that better alignment can reduce contention for everyone rather than simply redistributing pain.

Fleetwide results are similarly incremental but meaningful. For a planet-scale UL system, Aequitas plus pre-existing alignment yields about `72%` of RPCs aligned, covering about `84%` of response bytes and `78%` of request bytes. In a large query service, misalignment across cells is nearly eliminated after rollout; the maximum p99 RNL improves by `68.91%` for NC traffic and `36.45%` for PC traffic, while variance also drops sharply. Appendix D extends the story to SSD LL storage: roughly `30%` of LL-bound SSD RPCs were misaligned before Aequitas and about `0%` after deployment, with one heavily affected user seeing PC RPC latency improve by `6.4%` on average and `11.2%` at p99, and fleetwide PC latency improving by `1.8%` on average and `4.8%` at p99.

## Novelty & Impact

This is primarily a deployment and operational-systems paper, not a new transport protocol. Its novelty is showing that application-priority-aware QoS can be made practical with existing DSCP/WFQ infrastructure, and that the hard part is maintaining a healthy fleetwide queue mix while giving users evidence that downgrades are safe.

Relative to the original _Zhang et al. (SIGCOMM '22)_ Aequitas paper, this work is about the operational phase transition from design to default authority: how to choose RPC granularity, where to enforce, how to stage rollout, and what pathologies appear in real clusters. Relative to size-based datacenter schedulers, the paper makes the case that storage RPC priority is a more robust signal than size because both small and large RPCs can be latency critical. Operators running large storage fabrics or any network with differentiated queues are the likely audience that will cite this paper, because it provides a deployable recipe rather than an idealized scheduler.

## Limitations

The system is intentionally narrow. It covers intra-cluster storage traffic only; the paper explicitly leaves WAN deployment to future work because WAN latency dominates total RPC latency and because Google's BwE bandwidth manager already enforces priority budgets there. The policy space is also restricted to three priority classes and static mappings from application priority to QoS. That simplicity aids deployment, but it means Aequitas depends on storage systems to export good metadata and on the operator already having switch support for differentiated service.

The evaluation is production grounded but not cleanly experimental. There is no true A/B test, so the authors rely on random sampling, dominant-user clusters, and standardized metrics instead of absolute latency values. Those methods are reasonable for production, but they make some conclusions less crisp than a controlled environment would. The paper also admits exceptions: some clients still use bespoke QoS policies, and even LL deployment can only get misalignment to approximately zero because transient traffic can still bypass the framework.

## Related Work

- _Zhang et al. (SIGCOMM '22)_ — introduced Aequitas and early rollout evidence; this paper is the deployment-focused follow-through that expands coverage and sharpens the operational lessons.
- _Seemakhupt et al. (SOSP '23)_ — characterizes cloud RPC latency components at scale; this paper uses the same observation that network latency can dominate some RPCs to justify per-RPC QoS alignment.
- _Zhu et al. (SoCC '14)_ — PriorityMeister uses tail-latency-aware prioritization for shared networked storage, while this paper standardizes a three-class priority scheme across multiple storage services and existing switch QoS.
- _Montazeri et al. (SIGCOMM '18)_ — Homa also exploits priorities for low latency, but it is a transport redesign; Aequitas instead works through already deployed DSCP/WFQ mechanisms for easier incremental adoption.

## My Notes

<!-- empty; left for the human reader -->

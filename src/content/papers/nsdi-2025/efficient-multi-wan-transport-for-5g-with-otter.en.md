---
title: "Efficient Multi-WAN Transport for 5G with OTTER"
oneline: "OTTER jointly picks a 5G flow's compute destination and multi-WAN overlay path, improving throughput/RTT/jitter/loss and allocating 26%-45% more demand than greedy routing."
authors:
  - "Mary Hogan"
  - "Gerry Wan"
  - "Yiming Qiu"
  - "Sharad Agarwal"
  - "Ryan Beckett"
  - "Rachee Singh"
  - "Paramvir Bahl"
affiliations:
  - "Oberlin College"
  - "Google"
  - "University of Michigan"
  - "Microsoft"
  - "Cornell University"
conference: nsdi-2025
project_url: "https://otter-5gwan.github.io/"
tags:
  - networking
  - datacenter
  - virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

OTTER argues that once 5G network functions and applications move into the cloud, end-to-end quality is no longer a routing-only problem. The system jointly chooses where a flow should terminate and which multi-WAN overlay path it should take, using demand functions over throughput, RTT, jitter, loss, and compute capacity. In a continental-US Azure+GCP deployment, the overlay finds materially better trade-offs than default routing, and its periodic optimizer allocates 26%-45% more bytes than greedy placement.

## Problem

The paper starts from a structural change in 5G. Radio access functions are increasingly split into software NFs, with latency-critical pieces pushed toward operator edges and other functions, such as parts of the 5G core and cloud-hosted applications, placed in cloud edges or cloud datacenters. That means a single user flow may now cross both an operator WAN and a cloud WAN before reaching the NF or application that serves it.

Existing mechanisms treat the pieces of that decision separately, and that is the core failure mode. A compute selector such as the 5G NRF can pick a destination based on server availability while ignoring the route needed to reach it. Intra-domain traffic engineering can optimize a path within one WAN, but it does not see the end-to-end route across two administrative domains, nor does it understand that a different destination might yield better overall service. The paper's toy example shows exactly this mismatch: each WAN independently picks its locally best segment, but the composition is worse than another end-to-end path that neither side selects alone.

This matters because 5G traffic is heterogeneous in ways ordinary WAN TE abstractions do not capture. Some flows are throughput-hungry, some are jitter-sensitive, some need tight RTT, and some care most about loss. At the same time, edge sites are compute-constrained while cloud DCs are farther away but richer in capacity. Periodic TE cycles and a handful of coarse priority classes are too blunt for a setting where per-flow demands arrive on demand and where the "right" answer depends on both the chosen endpoint and the path to it.

## Key Insight

The central proposition is that cloudified 5G creates a joint placement-and-routing problem that should be solved directly, not approximated through separate compute selection and separate per-WAN routing. Once the serving NF or application can move between operator edge, cloud edge, and cloud DC, the path and the destination become inseparable control variables.

OTTER's way to make that tractable is to express service requirements as demand functions. Instead of assigning a flow to a fixed priority class, the controller maps each metric value on a candidate path to a tolerance coefficient in `(0, 1]`. That lets one optimization objective compare very different flows without pretending that every service metric reduces to the same scalar notion of "high priority." The paper's broader claim is that overlay-level visibility and aligned operator-cloud incentives are enough to solve this problem without private underlay data, BGP changes, or inter-provider negotiation protocols.

## Design

OTTER has two major pieces: a Controller and an Orchestrator. The Controller accepts per-flow QoS requests through "Quality on Demand" style APIs, including identifiers for the flow and a profile describing desired service. It then solves what the paper calls the multi-WAN flow placement problem: choose a destination site and one or more overlay paths that together satisfy the flow's network and compute needs.

The optimization model is the paper's technical core. Each candidate path carries measured throughput, RTT, jitter, and loss, plus its underlying link set. Each flow has a source, a set of feasible destinations, requested bandwidth, demand functions for each metric, and a resource vector for CPU, memory, and storage. The linear program uses two decision variables: bandwidth assigned to a flow-path pair, and destination resources assigned to that flow. The objective maximizes allocated traffic weighted by the sum of tolerance coefficients, normalized by the flow's requested bandwidth so large flows do not dominate automatically. Constraints enforce requested bandwidth, per-link capacity, destination resource limits, and consistency between how much traffic a flow sends to a destination and how much compute is reserved there.

Because 5G arrivals are on-demand, the paper does not rely on the LP alone. OTTER first places newly arriving flows with a greedy heuristic, then periodically reruns the full optimizer in the background. The reoptimizer can optionally pin sensitive flows to their path or destination to avoid disruption and packet reordering. This is an important engineering compromise: the system accepts some temporary suboptimality to keep reaction time low.

The Orchestrator implements those controller decisions as an overlay spanning GCP and Azure. It uses private subnets, VPN gateways, VPC/VNet peering, multiple regional VNets, and user-defined routes to steer traffic without requiring custom BGP speakers or packet forwarders. A Measurement Coordinator continuously measures throughput with iPerf3 and RTT/jitter with sockperf, stores sliding-window medians in Cosmos DB, and feeds those path metrics back to the optimizer. The prototype is intentionally cloud-native rather than vendor-specific: the contribution is not a new network device, but a way to synthesize multi-WAN paths and endpoint placement from primitives the clouds already expose.

## Evaluation

The evaluation has two distinct parts. First, the Orchestrator is deployed across continental-US Azure and GCP regions, with 64 source-destination VM pairs and 512 candidate paths measured roughly 20 times over a 24-hour period. Against the default path chosen by ordinary cloud routing, OTTER improves throughput by 13% on average and up to 136% in the best case, with peak inter-cloud throughput above 20 Gbps. For latency-sensitive traffic it cuts RTT by 15% on average and up to 42 ms in the best case. Jitter falls by 45% on average, and average loss drops from 0.06% to below 0.001%. The most useful qualitative result is that different overlay paths dominate different metrics, so the system really is exploiting path diversity rather than merely finding one universally best route.

Second, the Controller is evaluated at scale using measured path distributions from that deployment plus synthetic 5G flow arrivals and 3GPP-inspired application profiles. Here the main result is allocator quality: periodic re-optimization with path or destination pinning allocates 26%-45% more bytes than the purely greedy heuristic and comes within about 10% of idealized versions with an infinitely fast optimizer. At a 40K-flows/s arrival rate, the pinned variants raise the fraction of flows with perfect RTT satisfaction to about 47%, versus 41% for greedy allocation, while substantially reducing the number of flows sent on nearly useless RTT paths. The paper also shows that ignoring destination resource constraints is a serious mistake: effective allocated bytes fall by 23%-50% once oversubscribed edge sites are accounted for.

This evaluation largely supports the paper's claim, but with an important split. The path-orchestration gains come from a real multi-cloud deployment and are compelling evidence that the overlay can expose better end-to-end choices. The controller gains are grounded in those measured path distributions, yet the demand mix and resource capacities are synthetic, so they validate the optimization model more than they prove production behavior on a live carrier network.

## Novelty & Impact

OTTER sits at an unusual intersection. Compared with systems such as `Skyplane`, it is not a bulk-transfer overlay that trades cost against throughput for object movement. Compared with single-WAN TE systems such as `SWAN` or `OneWAN`, it does not just repartition traffic among a few classes inside one administrative domain. And compared with inter-domain coordination proposals such as `Nexit` or `Wiser`, it does not depend on explicit negotiation or private information exchange between competing ISPs.

The novelty is therefore both mechanism and framing. Mechanically, the paper combines endpoint placement, multi-metric path selection, and endpoint resource constraints in one LP-backed controller plus a practical overlay implementation. Conceptually, it argues that 5G cloudification changes the control problem itself: once traffic and NFs span operator and cloud WANs, service quality depends on jointly programming both. That makes the paper relevant to future work on cloud-hosted mobile cores, edge-cloud placement, and service-aware transport across administrative boundaries.

## Limitations

OTTER only optimizes over the paths and cloud primitives already exposed at the overlay layer. The paper explicitly leaves hidden underlay paths, monetary WAN cost, and deployments spanning multiple hyperscalers as future work. If more path diversity exists inside either WAN but is not surfaced through the overlay, OTTER cannot exploit it.

There is also a realism gap between prototype and target deployment. The orchestration results use GCP as a stand-in for an operator WAN, not a production carrier backbone, and the controller study relies on synthetic arrivals and sampled resource capacities. Finally, periodic re-optimization means fresh flows are still placed greedily while the LP solves; path pinning reduces disruption for RTT- and jitter-sensitive traffic, but it also prevents some beneficial reallocations. So the paper demonstrates a credible mechanism, not a complete operational answer to every 5G traffic-management problem.

## Related Work

- _Jain et al. (NSDI '23)_ - `Skyplane` also builds a cloud overlay, but it targets bulk inter-cloud transfers with static cost/throughput trade-offs, whereas `OTTER` handles live 5G flows with RTT, jitter, loss, and compute constraints.
- _Hong et al. (SIGCOMM '13)_ - `SWAN` represents periodic single-WAN TE with coarse priority classes, while `OTTER` performs per-flow placement across two WANs and explicitly models destination resource capacity.
- _Mahajan et al. (NSDI '05)_ - `Nexit` coordinates neighboring ISPs through negotiation, whereas `OTTER` exploits already-aligned operator/cloud incentives and avoids protocol changes or private-data exchange.
- _Birge-Lee et al. (HotNets '22)_ - `Tango` improves edge-to-edge path choice by exposing more paths, while `OTTER` additionally provisions cloud resources and chooses which compute destination should serve the flow.

## My Notes

<!-- empty; left for the human reader -->

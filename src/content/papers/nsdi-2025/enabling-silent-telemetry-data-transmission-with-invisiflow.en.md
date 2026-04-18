---
title: "Enabling Silent Telemetry Data Transmission with InvisiFlow"
oneline: "InvisiFlow turns telemetry export into low-priority pull-based gradient routing, steering reports around busy links instead of losing them on collector shortest paths."
authors:
  - "Yinda Zhang"
  - "Liangcheng Yu"
  - "Gianni Antichi"
  - "Ran Ben Basat"
  - "Vincent Liu"
affiliations:
  - "University of Pennsylvania"
  - "Microsoft Research"
  - "Queen Mary University of London"
  - "Politecnico di Milano"
  - "University College London"
conference: nsdi-2025
category: datacenter-networking-and-transport
code_url: "https://github.com/eniac/InvisiFlow"
tags:
  - networking
  - observability
  - smartnic
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

InvisiFlow exports telemetry with low-priority pull requests that follow buffer congestion gradients instead of fixed shortest paths to collectors. It keeps user-traffic overhead near zero while sharply reducing telemetry loss, including 33.8x lower missing-path rate than low-priority UDP at 70% load in the default setting.

## Problem

The paper studies a narrow but important problem: once switches generate fine-grained telemetry, how do those reports reach a small set of collectors without perturbing the very network being measured? Existing designs mostly choose between two bad options. They either embed telemetry into user packets, which taxes every packet, or they emit separate telemetry packets over conventional shortest-path transport. The latter is easier to deploy, but it creates a hard tradeoff between completeness and interference.

The paper quantifies that tradeoff: default-priority telemetry raises collector-adjacent FCT by about 19%, while low-priority telemetry misses about 11% of paths. That loss directly hurts path tracing, load-imbalance detection, and sketch synchronization. The premise is that shortest-path delivery is the wrong abstraction. Telemetry is asynchronous, tolerant of reordering, and off the critical path, so it should chase spare capacity instead.

## Key Insight

The key move is to treat telemetry transport as a distributed buffer-balancing problem. Instead of pushing reports toward collectors, neighboring switches compare telemetry-buffer occupancy and move data from fuller nodes to emptier ones. That local congestion gradient is motivated by max-weight scheduling theory: gradient-based forwarding maximizes the stability region and therefore the sustainable throughput of the telemetry channel.

InvisiFlow realizes that idea with a pull protocol. Switches emit low-priority pull requests carrying current telemetry-buffer usage, neighbors reply only when they are more congested, and collectors act as sinks with occupancy zero. A small slope term biases forwarding toward collectors so packets do not oscillate when occupancies are similar.

## Design

InvisiFlow has three roles: switches, collectors, and optional spare servers used as temporary telemetry storage. Switches periodically generate low-priority seed packets using OrbWeaver-style packet generation. In the egress pipeline, each seed becomes a pull request carrying local buffer occupancy. A neighbor routes that pull back out the same port and compares remote occupancy with its own: if it is fuller, it returns a telemetry packet; otherwise, it reflects the pull with its own occupancy. Collectors send pulls with occupancy zero, so telemetry drains toward them.

The most important implementation choice is late binding of egress ports. Telemetry is stored primarily in egress-pipeline register buffers, so the switch waits until an egress arbiter actually has room for a low-priority packet and only then appends the next telemetry chunk. Around that core, the paper adds three practical controls: a distance-based slope `delta` prevents ping-pong when occupancies are close, seed packets are probabilistically suppressed as local occupancy rises, and once occupancy exceeds about 95%, a switch temporarily falls back to blind pushing because waiting is more dangerous than taking routing risks. The prototype uses about 600 lines of P4-16 on switches plus DPDK collectors/servers, with modest extra hardware cost over an OrbWeaver-based low-priority UDP baseline.

## Evaluation

The evaluation combines ns-3 simulations on a 144-server, 4-pod FatTree with a hardware testbed built from two Wedge100BF-32X switches. The simulator runs four telemetry applications concurrently and compares InvisiFlow with default-priority UDP, low-priority UDP, and a pull-based shortest-path design without congestion gradients.

In the default simulated setting, InvisiFlow keeps telemetry loss at zero below 70% offered load. At 70% load, its missing-path ratio is about 33.8x lower than low-priority UDP and 36.3x lower than pull-based shortest-path forwarding; normalized relative error for flow-size estimation drops by about 2.4x and 4.8x. Under an asymmetric topology with degraded collector links, low-priority UDP and pull-based forwarding often miss more than 40% and 30% of paths, while InvisiFlow only begins dropping telemetry above 70% load. The same pattern holds under the ML workload and buffer-size sweeps. At 40% load, its 99th-percentile telemetry delay is about 80 us, around 3.4x lower than low-priority UDP and 10.9x lower than the pull-based baseline.

The testbed validates the implementation story. When the only shortest path toward the collector is saturated by user traffic, low-priority UDP loses more than 97% of telemetry packets and default-priority UDP still loses more than 80%; InvisiFlow keeps telemetry loss at zero by finding alternate paths. Its FCT overhead on user traffic stays below 0.1%, whereas default-priority UDP still adds about 0.8% overhead and can inflate switch queuing delay by up to 500x relative to InvisiFlow.

## Novelty & Impact

Relative to Planck and Everflow, the novelty is that InvisiFlow stops treating telemetry export as plain shortest-path packet delivery. Relative to PINT and other approximation-oriented systems, it keeps the telemetry content and changes the transport substrate instead. Relative to OrbWeaver, it adds distributed routing and buffering on top of low-priority gap filling. The likely impact is not a new telemetry application, but a better default way to move telemetry from data-plane producers to collectors under load.

## Limitations

InvisiFlow does not eliminate contention. If all relevant ports are continuously occupied by user traffic, low-priority telemetry still waits or drops, and the paper explicitly admits arbitrary delays or losses in that regime. The default design also provides no latency bound; it optimizes sustainable delivery, not freshness. Telemetry payloads must stay small enough for register-based buffering, multiple collector types require separate buffer allocations, optional storage servers add an operational tuning problem, and the empirical evidence is still strongest for datacenter-style topologies.

## Related Work

- _Yu et al. (NSDI '22)_ — OrbWeaver provides the low-priority gap-filling primitive InvisiFlow builds on, but it does not decide where telemetry should move once spare capacity appears.
- _Rasley et al. (SIGCOMM '14)_ — Planck also exports telemetry with dedicated packets, yet it still relies on conventional delivery paths instead of gradient-driven opportunistic forwarding.
- _Ben Basat et al. (SIGCOMM '20)_ — PINT cuts telemetry overhead by approximating what gets exported, whereas InvisiFlow preserves fidelity and changes how telemetry is transported.

## My Notes

<!-- empty; left for the human reader -->

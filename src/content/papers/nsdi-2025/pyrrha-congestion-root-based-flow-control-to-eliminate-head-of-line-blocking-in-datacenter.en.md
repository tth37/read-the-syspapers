---
title: "Pyrrha: Congestion-Root-Based Flow Control to Eliminate Head-of-Line Blocking in Datacenter"
oneline: "Pyrrha tracks downstream congestion roots and pauses only flows that feed each root, eliminating FC-induced HOL blocking without per-flow queues."
authors:
  - "Kexin Liu"
  - "Zhaochen Zhang"
  - "Chang Liu"
  - "Yizhi Wang"
  - "Vamsi Addanki"
  - "Stefan Schmid"
  - "Qingyue Wang"
  - "Wei Chen"
  - "Xiaoliang Wang"
  - "Jiaqi Zheng"
  - "Wenhao Sun"
  - "Tao Wu"
  - "Ke Meng"
  - "Fei Chen"
  - "Weiguang Wang"
  - "Bingyang Liu"
  - "Wanchun Dou"
  - "Guihai Chen"
  - "Chen Tian"
affiliations:
  - "Nanjing University"
  - "TU Berlin"
  - "Huawei, China"
conference: nsdi-2025
category: datacenter-networking-and-transport
code_url: "https://github.com/NASA-NJU/Pyrrha"
tags:
  - networking
  - datacenter
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pyrrha argues that hop-by-hop flow control should isolate traffic by congestion root, not by port, destination, or flow hash. Each switch tracks downstream roots, predicts which roots an arriving packet will traverse, and places the packet into isolation queues associated with those roots. That lets the network pause only culpable traffic and remove flow-control-induced HOL blocking without paying the state cost of per-flow queues.

## Problem

The paper starts from a timing problem in modern datacenters. Link bandwidth keeps rising, buffers do not keep pace, and workloads such as incast, web search, and distributed training generate short but violent bursts. End-to-end congestion control only reacts after congestion signals return to senders, so the loop usually costs at least one RTT and often several RTTs before it settles. That delay is increasingly expensive when a 100 Gbps or faster fabric can inject a large amount of data before the sender has time to slow down.

Per-hop flow control reacts faster, but common designs are too coarse. PFC pauses an upstream queue once a downstream queue crosses a threshold. That protects the congested port, yet it also pauses flows that merely share the queue and never traverse the real bottleneck. The result is HOL blocking: vulnerable and even background flows are throttled by someone else's congestion. Per-flow queues would solve the precision problem, but the paper argues they do not scale because a switch port can observe tens of thousands of concurrent flows. Prior compromises such as per-destination isolation or hashed queue pools reduce state, but they still mix unrelated traffic and therefore cannot eliminate HOL blocking completely.

## Key Insight

Pyrrha's key claim is that the right isolation unit is the congestion root: the most downstream hotspot that is the root cause of a congestion tree. If flow control pauses exactly the flows that traverse a given root, then the paused set matches the culpable set, so innocent flows are not blocked. The paper goes further and argues this is the minimum correct granularity: any design using fewer queues than congestion-root isolation cannot, in general, avoid HOL blocking.

That insight matters because hop-by-hop backpressure naturally creates congestion trees. Once a root is identified, upstream switches do not need to wait until packets physically reach the bottleneck. They can separate traffic earlier according to which downstream roots a packet will encounter and start backpressuring the correct traffic several hops in advance. In other words, Pyrrha uses topology-aware isolation to make per-hop flow control precise enough to complement end-to-end congestion control rather than interfere with it.

## Design

Pyrrha has three tightly connected mechanisms. First, a congested output port can self-nominate as a congestion root when its default output queue exceeds a pause threshold. Root identity is then corrected by a distributed merge procedure. If an upstream hotspot receives a `PAUSE` from a downstream claimed root and some of its traffic also traverses that downstream port, the upstream hotspot realizes it is only a false-positive root. It creates a queue for the downstream root, sends `MERGE` upstream, and lets its old queue enter a soft-merging state so already enqueued packets can drain safely.

Second, each switch identifies congested flows on packet arrival rather than at the bottleneck. To do that, it maintains a downstream congestion-root table and derives the packet's onward path. Pyrrha assumes routing where the onward path is locally reconstructable, such as source routing or hash-based ECMP with known hash functions and seeds. The switch matches the predicted path against the root table; packets that will traverse a root are marked as belonging to that root's congestion tree, while other packets stay on the ordinary path.

Third, Pyrrha uses Hierarchical Isolation Queues (HIQs) so a packet can be controlled by multiple roots without ambiguity. IQs are arranged by topological distance to the matched roots. A packet that traverses several roots must pass through the corresponding IQs from near to far before it can reach the ordinary output queue. This preserves correct pause/resume semantics and in-order delivery even when trees overlap, roots merge, or a root later shifts upstream. The implementation also keeps ordinary output queues out of the pause path, which helps avoid deadlock from cyclic buffer dependencies.

## Evaluation

The evaluation combines a Tofino2 prototype with NS-3 simulations. The hardware prototype uses about 2.5k lines of P4 and 2k lines of Python, and on a representative `k=36` fat-tree with 11,664 hosts the paper reports roughly 11 MB of switch memory consumption. On a 100 Gbps leaf-spine testbed, Pyrrha raises vulnerable-flow throughput to 66.7 Gbps while maintaining 100 Gbps aggregate incast throughput, improving total network throughput by 26.7 Gbps over PFC.

The larger case comes from simulation across a 160-host Clos and a 1024-host fat-tree. Pyrrha is evaluated on Memcached, Web Server, Web Search, incast-mix, multi-root load imbalance, and MoE-style periodic all-to-all traffic, against PFC and BFC and in combination with DCQCN, HPCC, and TIMELY. Across these settings, the paper reports 42.8%-98.2% lower average FCT for uncongested flows and 1.6x-215x lower 99th-percentile latency, without hurting the throughput of congested flows. Maximum buffer occupancy also drops by 1.8x-6.2x because Pyrrha pushes congestion back earlier instead of letting queues build at the root. In the collided-phase MoE workload, adding Pyrrha to DCQCN improves tail latency by 1.46x over DCQCN+PFC. The evidence supports the central claim, though most results still come from controlled simulations rather than production deployment.

## Novelty & Impact

Relative to BFC, Pyrrha does not accept residual collisions from hashing flows into a bounded queue pool; it argues that only congestion-root isolation is both precise enough to remove HOL blocking and still scalable. Relative to Floodgate, which targets last-hop incast via per-destination state, Pyrrha generalizes the problem to arbitrary congestion trees. Relative to HPCC and other end-to-end schemes, it changes the control layer: Pyrrha acts on packets that are already in the network, at sub-RTT timescales, while sender-side congestion control still handles persistent congestion and fairness.

That combination of a formal granularity argument, a distributed root-identification protocol, and a programmable-switch implementation makes the paper more than an incremental queue-management tweak. Even if operators do not deploy Pyrrha exactly as written, the congestion-root abstraction is a useful design rule for dividing labor between per-hop flow control and end-to-end congestion control.

## Limitations

Pyrrha depends on the switch being able to determine a packet's downstream path. That fits source routing and predictable hash-based load balancing, but it is less natural for strongly adaptive routing. The paper shows Pyrrha can complement DRILL for destination-collision cases, yet it does not present a fully general story for all dynamic path-selection schemes.

The strongest scalability story also assumes switch support that current Tofino2 hardware does not natively provide. The prototype emulates HIQs with single-tier queues, so some queue-management costs are higher than the paper's idealized architecture. The paper also assumes the number of concurrent roots per port is moderate; when queue resources are exhausted, Pyrrha falls back to hash-based assignment and gives up some isolation precision. Finally, the evaluation is broad but mostly synthetic, and the paper admits rare pathological cases can still require packet drops plus IRN-style retransmission rather than purely lossless flow control.

## Related Work

- _Goyal et al. (NSDI '22)_ - BFC hashes flows into a limited queue pool to reduce HOL blocking, while Pyrrha argues that congestion-root isolation is the minimum granularity that removes HOL blocking completely.
- _Liu et al. (CoNEXT '21)_ - Floodgate isolates last-hop incast with per-destination windows; Pyrrha instead targets arbitrary congestion trees and avoids destination-granularity control state.
- _Li et al. (SIGCOMM '19)_ - HPCC uses in-band telemetry for end-to-end rate control, whereas Pyrrha performs in-network, hop-by-hop isolation on packets that have already been injected.
- _Cho et al. (SIGCOMM '17)_ - ExpressPass allocates transmission credit proactively, while Pyrrha reacts to emerging roots inside the network and leaves persistent rate control to end hosts.

## My Notes

<!-- empty; left for the human reader -->

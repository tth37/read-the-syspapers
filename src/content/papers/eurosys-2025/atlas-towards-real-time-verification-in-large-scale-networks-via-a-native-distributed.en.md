---
title: "Atlas: Towards Real-Time Verification in Large-Scale Networks via a Native Distributed Architecture"
oneline: "Atlas turns data-plane verification into a three-tier distributed service, keeping loop, blackhole, and policy checks fast as networks scale."
authors:
  - "Mingxiao Ma"
  - "Yuehan Zhang"
  - "Jingyu Wang"
  - "Bo He"
  - "Chenyang Zhao"
  - "Qi Qi"
  - "Zirui Zhuang"
  - "Haifeng Sun"
  - "Lingqi Guo"
  - "Yuebin Guo"
  - "Gong Zhang"
  - "Jianxin Liao"
affiliations:
  - "State Key Laboratory of Networking and Switching Technology, Beijing University of Posts and Telecommunications"
  - "Pengcheng Laboratory"
  - "E-Byte.com"
  - "Huawei Technologies"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3717494"
tags:
  - networking
  - formal-methods
  - verification
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Atlas turns data-plane verification into a three-layer distributed service. Switch adapters maintain per-switch forwarding models, region adapters summarize intra-region reachability, and a center adapter composes those summaries to check cross-region loops and path policies. On most datasets Atlas stays in the sub-second range, and it remains under 1 second in a 500-switch deployment.

## Problem

The paper starts from a simple systems problem: modern DPV tools are still mostly centralized. One server must ingest updates from every switch, maintain the whole network model, and execute each verification task. In large WANs and data centers that server becomes both the compute bottleneck and the update-collection bottleneck. The paper's motivating number is that EPVerifier still needs more than 1 minute on a 48-ary fat-tree with 2,880 nodes.

Simply distributing execution is not enough. Tulkun pushes checking onto devices, but only after an expensive planner computes per-device subtasks. That planner can time out or exceed memory on large topologies, and it must be rerun when the DPV task changes. Atlas therefore asks for a verifier whose steady-state model maintenance and task execution are already distributed, with no heavy centralized planning phase.

## Key Insight

Atlas's key insight is to match the verifier to the network's own hierarchy. If switches, regions, and the global backbone each maintain only the forwarding abstraction they can derive locally, then updates can be processed near their source and higher layers only need compact reachability summaries. Atlas calls this native distribution: model maintenance is local by construction, and verification runs by composing those local models directly rather than synthesizing an external execution plan.

## Design

Atlas has three layers. A Switch Adapter (SA) maintains a switch-model mapping output ports to packet sets, computed from routing-table match fields and priorities and encoded as BDDs. A Region Adapter (RA) merges SAs into a region-model, an edge-labeled graph that captures intra-region forwarding, out-of-region edges, and reachability between backbone nodes. A Center Adapter (CA) builds a backbone-model from RA summaries.

Verification is offloaded by task type. RAs detect intra-region loops while the CA detects inter-region loops over the backbone-model. Blackhole checks reuse the same path reasoning and also let each SA report forwarding-table gaps locally. For user-defined policies, the CA splits the constrained path by region, asks relevant RAs for additional reachability between backbone and non-backbone nodes, and then stitches a task-specific global model. Atlas also updates reachability incrementally: when a model edge changes, the RA performs bidirectional traversals from the changed edge and joins only the affected forward and reverse summaries instead of recomputing everything.

## Evaluation

The evaluation uses seven WAN datasets, three data-center datasets, and a 500-switch commercial deployment. In burst updates, Atlas usually stays under 0.5 seconds on WAN loop and policy checks, and around or below 1 second on most data-center cases. On FT-48 it takes 0.97 seconds for loop-freedom and 1.08 seconds for the user-defined policy task, versus Tulkun's 4.28 seconds and 4.13 seconds and EPVerifier's 63.36 seconds and 32.04 seconds. On the very large INET topology, Atlas still finishes in 14.83 seconds and 17.08 seconds, while Tulkun times out and EPVerifier needs 230.55 seconds and 285.05 seconds.

The incremental-update experiment is even stronger. After 10,000 sequential rule insertions, Atlas verifies at least 96.97% of updates in under 10 ms across all datasets; its 80th-percentile latency is up to 7 times faster than EPVerifier and 2 times faster than Tulkun. The per-switch cost is small, with SA CPU load under 0.3% and max SA memory at 26 MB. In the real deployment, Atlas finishes loop-freedom in 0.62 seconds and the policy task in 0.58 seconds, versus 10.25 seconds and 9.54 seconds for EPVerifier. The evidence strongly supports the scalability claim, though blackhole-freedom is demonstrated more by construction than by a separate benchmark.

## Novelty & Impact

Atlas's main contribution is architectural. APKeep, Flash, and EPVerifier make centralized incremental verification faster, while Tulkun distributes checking but depends on a costly planner. Atlas instead uses hierarchical local models and task-specific composition to make distributed DPV practical without full per-device precomputation. That makes it a useful reference point for production NMS design and for future verifiers that need to operate at WAN or warehouse scale.

## Limitations

Atlas depends on a sensible region partition, which the administrator must choose. It also focuses on ordinary forwarding rules; NAT and ACL handling are deferred to future work. Finally, the implementation uses JDD-based BDDs, which the authors acknowledge may become the next bottleneck in large distributed real-time settings, and the real deployment runs SAs in external VMs rather than directly inside switch software.

## Related Work

- _Zhang et al. (NSDI '20)_ - APKeep keeps centralized real-time verification scalable by merging equivalence classes, while Atlas removes the single verifier and distributes both model maintenance and checking across a hierarchy.
- _Guo et al. (SIGCOMM '22)_ - Flash accelerates centralized verification under update storms, whereas Atlas argues that large-scale networks still need architectural distribution after those centralized optimizations.
- _Zhao et al. (NSDI '24)_ - EPVerifier speeds up incremental verification with edge predicates, but Atlas shifts the work to switch, region, and center adapters so one server no longer owns the whole network state.
- _Xiang et al. (SIGCOMM '23)_ - Tulkun distributes verification onto devices, while Atlas avoids Tulkun's expensive planner by reasoning over hierarchical summaries instead of precomputed per-device subtasks.

## My Notes

<!-- empty; left for the human reader -->

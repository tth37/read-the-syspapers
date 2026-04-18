---
title: "Efficient Direct-Connect Topologies for Collective Communications"
oneline: "Co-designs a degree-constrained direct-connect topology and collective schedule, then searches the Pareto frontier between low-hop latency and load-balanced bandwidth."
authors:
  - "Liangyu Zhao"
  - "Siddharth Pal"
  - "Tapan Chugh"
  - "Weiyang Wang"
  - "Jason Fantl"
  - "Prithwish Basu"
  - "Joud Khoury"
  - "Arvind Krishnamurthy"
affiliations:
  - "University of Washington"
  - "RTX BBN Technologies"
  - "MIT CSAIL"
conference: nsdi-2025
tags:
  - networking
  - gpu
  - llm-training
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

This paper synthesizes direct-connect topologies and collective schedules together instead of accepting ring/tree tradeoffs. It scales small optimal graphs with graph expansions, uses polynomial-time BFB scheduling on large symmetric graphs, and picks the Pareto-efficient design for the workload.

## Problem

The target is a direct-connect cluster where each host has only a few ports. Rings maximize bandwidth but incur linear hop count; double binary trees cut hops but skew link load; switch-oriented algorithms such as recursive doubling or Bruck assume logical full connectivity over time and do not fit low-degree fabrics.

The harder issue is that topology and schedule interact. A low-diameter graph helps small allreduce and all-to-all but may overload some links for large transfers, while a load-balanced graph may saturate bandwidth but pay too many hops. Prior work usually optimizes only one side. This paper asks how to synthesize both together at realistic scale.

## Key Insight

The paper's claim is that direct-connect collectives should be chosen from a workload-specific Pareto frontier, not from one universal topology. It makes that frontier tractable by combining property-preserving graph expansions with a constrained schedule generator.

The expansions reuse good small graphs instead of searching from scratch. For large graphs, BFB restricts schedule generation to eager breadth-first broadcasts over shortest paths and solves only the continuous load-balancing problem with linear programs. That is enough to keep `TL` minimal for the chosen topology and to recover bandwidth-optimal schedules for families such as torus and circulant graphs.

## Design

The paper models collective cost as total-hop latency `TL` and bandwidth runtime `TB`, so the target is a set of Pareto-efficient topology/schedule pairs for given `N` and `d`. The construction toolbox has three operators: line-graph expansion grows a graph to `dN` nodes without raising degree and preserves shortest-path structure; degree expansion scales both node count and degree while preserving bandwidth-optimal schedules because broadcasts from different copies remain disjoint; Cartesian products combine graphs dimension-wise and recover structures such as hypercubes and unequal-dimension tori.

For topologies without a known schedule, BFB generates one. In allgather, each node broadcasts its shard frontier by frontier, and at each step a linear program decides how much data each feasible in-neighbor should send so the most loaded ingress link is minimized. Using continuous fractions instead of discrete chunk placement keeps the algorithm polynomial-time and parallelizable. A topology finder then searches over base graphs plus expansion sequences, predicts `TL` and `TB` with closed-form theorems, prunes dominated candidates, and returns the Pareto frontier. The schedules are lowered to MSCCL on GPUs and oneCCL/libfabric on CPUs.

## Evaluation

On a 12-node optical A100 testbed, against tuned ShiftedRing and double binary tree (DBT), the selected topologies improve allreduce by about 75% over ShiftedRing and 20% over DBT at 1 KB, remain roughly 50% and 45% better at 1 MB, and match bandwidth-optimal ShiftedRing while staying about 50% ahead of DBT at 1 GB.

The training and scale results are the strongest evidence. For small data-parallel models, the design cuts total allreduce time by 30% versus ShiftedRing and 50% versus DBT, yielding 10% and 25% iteration-time gains after overlap; GPT-2 improves by 7% and 25%. Near 1000 nodes, analytical results show 56x and 10x allreduce gains over ShiftedRing and DBT, while generalized Kautz comes within 5.2% of the all-to-all lower bound and beats them by 28x and 42x. In simulated MoE training, ShiftedRing is 4x slower at 256 nodes and 9x slower at 1024 nodes. BFB also scales in schedule generation: it handles 1024-node hypercubes and 2500-node tori in about a minute, where SCCL and TACCL fail much earlier.

## Novelty & Impact

The novelty is the synthesis framework, not any one graph. Relative to _TopoOpt_ (NSDI '23), this paper does not merely permute topology around a ring collective; it changes the collective schedule itself. Relative to _SCCL_ and _TACCL_, it gives up fully general optimal synthesis in exchange for a search-and-generation pipeline that actually reaches large direct-connect fabrics. That makes it valuable for optical ML clusters, TPU-like torus deployments, and any accelerator fabric where port count is scarce and all-to-all is no longer a side case.

## Limitations

The paper does not prove global optimality for the final search. It explores a curated library of base graphs and expansion rules, so a better topology outside that library could exist. BFB is also only conditionally optimal: its scalability comes from restricting schedules to eager shortest-path broadcasts, which can exclude better schedules on irregular graphs. The evaluation further assumes one static topology per job because the patch-panel target reconfigures slowly, and the main treatment assumes mostly homogeneous direct-connect fabrics.

## Related Work

- _Wang et al. (NSDI '23)_ - `TopoOpt` co-optimizes training-job topology and parallelization strategy, but it still runs collectives as rings; this paper jointly changes both topology and collective schedule.
- _Cai et al. (PPoPP '21)_ - `SCCL` synthesizes optimal collective schedules for a fixed topology, whereas this paper uses structured graph expansions and BFB to make topology-plus-schedule search scale.
- _Shah et al. (NSDI '23)_ - `TACCL` accelerates schedule synthesis with communication sketches on a given topology; `BFB` is less general but polynomial-time and effective on much larger graphs.
- _Basu et al. (HPDC '24)_ - the authors' prior all-to-all work for direct-connect topologies optimizes a complementary primitive, while this paper adds allreduce, reduce-scatter, and allgather to the same design space.

## My Notes

<!-- empty; left for the human reader -->

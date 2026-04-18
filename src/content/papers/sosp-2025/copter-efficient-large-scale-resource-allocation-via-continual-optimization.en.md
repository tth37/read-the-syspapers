---
title: "COpter: Efficient Large-Scale Resource-Allocation via Continual Optimization"
oneline: "COpter turns round-based LP/MILP allocators into continual optimizers, updating sparse problems in place, warm-starting a proximal solver, and using cheap integer shims."
authors:
  - "Suhas Jayaram Subramanya"
  - "Don Kurian Dennis"
  - "Gregory R. Ganger"
  - "Virginia Smith"
affiliations:
  - "Microsoft"
  - "Meta"
  - "Carnegie Mellon University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764846"
tags:
  - scheduling
  - datacenter
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

COpter treats successive allocation rounds as a slowly evolving LP or MILP sequence rather than independent solves. It updates sparse programs in place, warm-starts a factorization-free proximal solver, and uses lightweight shims for integer recovery, cutting runtime by 57-83x versus commercial solvers with little quality loss.

## Problem

Optimization-based allocators can encode fairness, utilization, and policy constraints that heuristics struggle to express, but production systems must rerun them frequently. At scale, the cost is not just the solve: each round also recompiles a huge sparse matrix and, for MILPs, pays an expensive integerization step.

The paper shows that this loop breaks down precisely when frequent global optimization matters most. Scaling Sia from 10k to 25k GPUs increases solve time by about 100x and leaves only 15% of rounds within a one-minute deadline. Recompiling from scratch discards prior work, Simplex and barrier solvers keep hard-to-update state, partitioning methods like POP sacrifice global quality, and branch-and-cut can dominate runtime even when the LP relaxation is already nearly integral.

## Key Insight

The key claim is that many large resource-allocation workloads are slowly evolving: problem dimensions change little across rounds and the optimum barely moves. In the Sia traces, fewer than 0.01% of variables change value between consecutive rounds, and only a few percent are added or removed. If that temporal structure is first-class, runtime should depend on the path length of changes across rounds rather than on solving every round from scratch.

That only works if the whole stack is built for reuse. COpter therefore combines a mutable problem representation, a solver that benefits from nearby `l2` warm starts, and cheap integer-recovery heuristics. Continual optimization is the paper's end-to-end systems abstraction, not just a solver option.

## Design

COpter changes all three stages of allocation. For compilation, it offers a differential interface: add or remove requests by editing only the associated variables and constraints, and update resource counts by touching the right-hand side. To make that cheap, it stores the sparse matrix as a list-of-lists instead of CSR or CSC, accepting some locality loss in exchange for in-place updates.

For LP solving, it uses the Proximal Point Algorithm rather than Simplex or interior-point methods. PPA is factorization-free, keeps little internal state, and can exploit a previous round's solution when nearby optima make it a good warm start. Their implementation uses dual coordinate descent, an active set, and sparse matrix-vector operations. For MILPs, COpter skips generic branch-and-cut and uses small domain-specific shims because the LP relaxations in these workloads are already almost binary.

## Evaluation

Across three domains, the results line up with the thesis. For GPU scheduling, COpter reduces Sia's p99 solve time from 233.4 s to 6.5 s on 10k GPUs and from 2,277 s to 40.3 s on 25k GPUs, while keeping average JCT and makespan close to the commercial LP baseline. POP stays fast on smaller clusters but loses quality and misses deadlines more often at 25k GPUs.

For shard load balancing, COpter satisfies the load-imbalance target while running about 2.8x faster than re-solving each LP relaxation independently. For WAN traffic engineering, it stays under a minute while matching or nearly matching optimal max-flow; on the large ASN topology with bimodal traffic it is about 30x faster than the full LP baseline and allocates 1.5% more flow than POP. The evaluation is broad and the baselines are sensible, although it is still mostly trace-driven simulation rather than production deployment.

## Novelty & Impact

The closest conceptual comparison is POP: POP scales optimization by partitioning space, whereas COpter keeps the global problem intact and exploits time. Relative to papers like Sia or Rebalancer, COpter is not a new objective but a reusable execution strategy for running LP and MILP allocators frequently enough to matter. That makes it broadly relevant to slow-moving capacity allocators, reservation systems, and traffic controllers.

## Limitations

COpter is not universal. The authors say it is a poor fit when requests or resources change dramatically between rounds, citing serverless scheduling, database queries, and fine-grained streaming tasks as examples.

The MILP speedups also trade guarantees for speed. The shims are handcrafted per domain, prioritize feasibility over optimality, and rely on LP relaxations being nearly integral. The paper also stops short of a live production integration, so operational tuning and maintenance costs remain open.

## Related Work

- _Narayanan et al. (SOSP '21)_ - POP partitions resources and requests into parallel subproblems, while COpter preserves the global problem and reuses work across time.
- _Subramanya et al. (SOSP '23)_ - Sia is a representative MILP scheduler policy; COpter is the optimization engine that makes Sia-like policies practical at larger scales.
- _Kumar et al. (OSDI '24)_ - Rebalancer compiles scheduling policies to MILPs and falls back to local search at scale, whereas COpter extends the regime where frequent global optimization is still feasible.
- _Xu et al. (SIGCOMM '23)_ - Teal accelerates WAN traffic engineering with learning plus ADMM, while COpter exploits temporal continuity without replacing optimization with a learned surrogate.

## My Notes

<!-- empty; left for the human reader -->

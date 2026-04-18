---
title: "Decouple and Decompose: Scaling Resource Allocation with D E D E"
oneline: "D E D E duplicates the allocation matrix, alternates per-resource and per-demand ADMM solves, and scales cloud allocation without POP's granularity assumption."
authors:
  - "Zhiying Xu"
  - "Minlan Yu"
  - "Francis Y. Yan"
affiliations:
  - "Harvard University"
  - "University of Illinois Urbana-Champaign"
conference: osdi-2025
tags:
  - scheduling
  - networking
  - datacenter
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

D E D E is a general optimization framework for large cloud resource allocation problems whose variables sit at the intersection of per-resource and per-demand constraints. Its key move is to duplicate the allocation matrix, use ADMM to enforce equality between the two copies, and thereby decompose one large solve into many parallel per-resource and per-demand subproblems. Across cluster scheduling, traffic engineering, and load balancing, that gives materially better time-quality trade-offs than POP and approaches the quality of exact solvers much faster.

## Problem

The paper starts from a practical bottleneck: production resource allocators still lean on commercial LP or MILP solvers, but modern cloud allocation problems now involve thousands of resources, thousands of demands, and sometimes millions of variables. In that regime, exact solving can take tens of minutes or hours, which is incompatible with control loops that must react in seconds.

Prior attempts to speed this up have mostly paid for speed with narrow applicability. Some are domain-specific, such as WAN traffic-engineering systems. POP is broader, but it assumes each demand needs only a small interchangeable subset of resources, so the problem can be split into a few random subproblems. The authors argue that this "granular" assumption is brittle in real workloads, where jobs may be pinned to specific GPU types and traffic demands may be constrained to specific paths. When that assumption fails, naive partitioning either loses quality or cannot decompose aggressively enough to matter.

The paper's target, then, is not one allocator but a common structure behind many of them: objectives that sum per-demand or per-resource utilities, plus constraints written separately for each resource and each demand. The difficulty is that every allocation variable still appears in both constraint families, so the problem looks separable on paper but remains entangled in the solver.

## Key Insight

The central claim is that the entanglement is algebraic, not fundamental. If the original allocation matrix `x` is duplicated as an auxiliary matrix `z`, then resource-side terms can be written over `x`, demand-side terms over `z`, and the only coupling left is the equality constraint `x = z`. That reformulation preserves the exact optimum, but it also makes the problem fit two-block ADMM.

Once ADMM is in play, D E D E can alternate between optimizing resource-side variables with demand-side variables fixed, and optimizing demand-side variables with resource-side variables fixed. Because the paper's target problems are separable, each of those alternating steps further splits into independent subproblems: one per resource during the `x` step and one per demand during the `z` step. The framework's scalability therefore comes from removing the need for one monolithic high-dimensional search and replacing it with many smaller solves that still retain access to the full resource or demand space.

## Design

Formally, D E D E starts from problems whose objective is a sum of per-resource utilities `f_i(x_i*)` and per-demand utilities `g_j(x_*j)`, with linear constraints `R_i x_i* = r_i` on each resource and `D_j x_*j = d_j` on each demand. The framework rewrites the problem as minimizing `sum_i f_i(x_i*) + sum_j g_j(z_*j)` subject to the original resource constraints on `x`, the original demand constraints on `z`, and `x - z = 0`.

The interesting step is what happens next. Rather than jointly optimizing `x` and `z` with a penalty method or plain augmented Lagrangian, D E D E applies scaled ADMM. The augmented Lagrangian carries three sets of auxiliary variables: one for resource constraints, one for demand constraints, and one for the equality between `x` and `z`. In each iteration, D E D E solves an `x` minimization, a `z` minimization, and then updates the multipliers.

Because the objective and constraints are separable, the `x` minimization becomes `n` independent per-resource subproblems, each over only the variables associated with one resource. Symmetrically, the `z` minimization becomes `m` per-demand subproblems. The framework therefore preserves global coupling through ADMM's multiplier updates while letting each local solve use an off-the-shelf solver on a much smaller search space. The authors give a rough LP complexity argument: instead of one problem with about `O((n*m)^2.373)` cost, D E D E handles `n` subproblems of roughly `O(m^2.373)` each, assuming convergence in a bounded number of iterations.

The implementation is designed to feel like cvxpy. Users define a variable matrix, declare resource constraints and demand constraints separately, and call `solve(num_cpus=...)`. Internally, D E D E converts inequalities into equalities with slack variables, builds the per-resource and per-demand cvxpy subproblems once, and then only updates parameters during later ADMM iterations. It uses Ray rather than Python threads so the parallel work is not bottlenecked by the GIL. In traffic engineering, the authors also group per-demand subproblems by source to avoid maintaining `|V|^2` separate demand optimizations.

## Evaluation

The evaluation is broad and is the paper's strongest practical argument. On 64 CPU cores, D E D E is compared with exact solving, POP, and a simulated-parallel variant `D E D E*`; in domain-specific settings it is also compared against Gandiva, Pinning, Teal, and a greedy load-balancing heuristic.

For heterogeneous cluster scheduling, D E D E reaches a normalized max-min allocation of 0.94 in 3 seconds and 0.99 in 10 seconds, while exact solving takes 156 seconds and POP-16 settles for lower quality around 0.90 in 3.1 seconds. On proportional fairness, the exact cvxpy-based baseline does not reach optimality even after 5 hours; D E D E and `D E D E*` both exceed the normalized score of that baseline within 100 seconds, whereas POP-4 and POP-16 need 3,053 and 682 seconds to get comparable quality.

For WAN traffic engineering on a 1,739-node topology, D E D E reaches 90.8% satisfied demand in 30 seconds and 92% in 60 seconds. POP-4 eventually reaches similar quality, but only after 1,658 seconds on average, and POP-64 is faster only by giving up much more quality. On the min-max link-utilization variant, D E D E gets to 1.67 in 10 seconds; exact solving gets slightly better at 1.63 but needs 35 seconds, while Teal is much faster at 0.3 seconds on a GPU but is a specialized learned system rather than a general optimizer.

Load balancing is the hardest case because it is non-convex and uses integer variables. Even there, D E D E averages 20.1 shard movements in 15 seconds, better than POP-4's 21.5 movements in 133 seconds and close to exact solving's 20.9 movements, which needs 4,820 seconds. The micro-benchmarks explain where the speedup comes from: `D E D E*` shows 61.7x speedup at 64 cores, practical D E D E still gets 18.2x, warm starts matter substantially, and naive joint optimization with a penalty method or augmented Lagrangian is over 30x and over 3x slower, respectively, than the ADMM-based design at reaching the same traffic-engineering quality target.

## Novelty & Impact

Relative to _Narayanan et al. (SOSP '21)_, D E D E does not randomly carve the allocation graph into a few smaller problems and hope the workload is granular enough; it uses a mathematically exact reformulation that leaves every subproblem connected to the full resource or demand space. Relative to _Xu et al. (SIGCOMM '23)_, it trades away domain-specific learning and GPUs for a general decomposition strategy that can be reused across very different allocators. Relative to classical solver-based production systems, the novelty is not a new objective or domain model but a reusable way to expose parallelism already latent in separable formulations.

That matters because many systems papers and production controllers end up rediscovering bespoke acceleration tricks for one optimization loop at a time. D E D E's contribution is to show that a sizable class of cloud allocation problems can share one theory-backed decomposition template, one implementation model, and one CPU-parallel execution strategy.

## Limitations

The paper is explicit that D E D E is not universal. Its best case is a two-dimensional allocation matrix with separable objectives and linear per-resource and per-demand constraints. If the objective depends on interactions among different allocations, if constraints span multiple resources and demands simultaneously, or if the model introduces extra dimensions such as time, decomposition becomes weaker or ADMM may lose its clean convergence properties.

The quality story is also conditional. ADMM has strong guarantees for convex problems, but load balancing in the paper is non-convex and integer-valued, so D E D E is relying on empirical effectiveness there rather than a proof of optimality. The practical implementation also pays real systems costs that the idealized `D E D E*` model hides: cache contention, process-management overhead, and stragglers limit the realized speedup. Finally, domain-specialized systems such as Teal can still win on raw latency in the domains they were hand-built for.

## Related Work

- _Narayanan et al. (SOSP '21)_ - POP also seeks parallel speedups for large allocation problems, but it depends on a granularity assumption that D E D E is specifically designed to remove.
- _Xu et al. (SIGCOMM '23)_ - Teal accelerates WAN traffic engineering with learned initialization and GPU execution, whereas D E D E offers a general solver decomposition that also transfers to cluster scheduling and load balancing.
- _Abuzaid et al. (NSDI '21)_ - NCFlow decomposes traffic-engineering problems by network structure, while D E D E targets a broader separable optimization pattern independent of one domain's topology.
- _Namyar et al. (NSDI '24)_ - Soroush gives specialized parallel algorithms for max-min fair allocation, whereas D E D E aims for one reusable framework across multiple objectives and allocation domains.

## My Notes

<!-- empty; left for the human reader -->

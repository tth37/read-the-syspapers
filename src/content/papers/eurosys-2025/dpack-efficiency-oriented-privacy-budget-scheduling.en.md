---
title: "DPack: Efficiency-Oriented Privacy Budget Scheduling"
oneline: "DPack treats DP budget as a finite schedulable resource, estimates each block's best RDP order, and packs more private-ML jobs than fairness-first schedulers."
authors:
  - "Pierre Tholoniat"
  - "Kelly Kostopoulou"
  - "Mosharaf Chowdhury"
  - "Asaf Cidon"
  - "Roxana Geambasu"
  - "Mathias Lécuyer"
  - "Junfeng Yang"
affiliations:
  - "Columbia University"
  - "University of Michigan"
  - "University of British Columbia"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3696096"
code_url: "https://github.com/columbia/dpack"
tags:
  - scheduling
  - ml-systems
  - security
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

DPack argues that privacy budget should be scheduled like a scarce cluster resource rather than divided with fairness as the primary goal. It reformulates differentially private ML scheduling as a knapsack-style packing problem, then uses a best-alpha-aware greedy heuristic that consistently schedules more jobs than prior fairness-oriented work.

## Problem

The paper starts from a realistic DP-ML setting: a trusted curator keeps user data in blocks, many training or analytics jobs arrive over time, and the system must maintain a global `(epsilon_G, delta_G)` guarantee across all released results. Once a task spends privacy budget on a block, that budget is gone forever. This makes privacy unlike CPU or RAM: it is finite, non-replenishable, and shared across many future jobs.

Prior work from the same group, DPF in PrivateKube, treated this as a fairness problem. It adapts dominant-resource-fairness ideas so that jobs with smaller dominant privacy share run first. The authors show why that choice can waste budget badly. If one task touches many blocks and several others touch only one block each, dominant-share ordering can burn all blocks on the first task even though a different packing would admit several jobs. The same issue appears under Rényi DP accounting, where each task has multiple alpha-order privacy costs. In the paper's framing, the goal many operators actually want is not max-min fairness but global efficiency: maximize the number of scheduled tasks, or more generally the total task utility.

## Key Insight

The core insight is that privacy scheduling is fundamentally a packing problem, and the right efficiency metric must reflect the shape of privacy demand rather than only its largest coordinate. Under standard DP composition, that means accounting for the normalized demand across all requested blocks. Under RDP, the situation is subtler: each block has multiple alpha-order capacities, but a schedule only needs to stay within budget for at least one alpha order per block after translation back to traditional DP. Treating every alpha as a normal resource dimension, as a fairness-first scheduler would, throws away this flexibility.

DPack therefore tries to guess which alpha order is actually the useful one for each block, and scores tasks mainly by how much they consume on those promising orders. The proposition is simple: if privacy is scarce and heterogeneous, a scheduler should preserve the budget coordinates that are likely to become the final bottleneck, not the ones that merely look largest locally.

## Design

The paper first formalizes efficiency-oriented scheduling under traditional DP as a multidimensional knapsack problem: each task has a weight and a privacy demand vector over blocks, and the scheduler wants the maximum total weight subject to every block staying within remaining budget. This is NP-hard, so exact optimization does not scale. The paper then explains DPF as just one greedy heuristic for this objective, with an efficiency score derived from dominant share, and replaces it with an area-based metric that divides task weight by total normalized demand across blocks.

The more novel step is the RDP formulation. A task now carries a demand `d_{i,j,alpha}` for each block and alpha order, and a schedule is valid if, for every block, there exists some alpha whose total allocated demand stays within that block's capacity. The authors call this the privacy knapsack problem and prove it is also NP-hard. They further show that the single-block case admits a polynomial-time approximation scheme, while the multi-block case does not admit an FPTAS unless `P = NP`.

DPack uses that single-block tractability as a building block. For each block, it solves an approximate single-block knapsack separately at each alpha order to estimate which alpha would pack the most utility on that block. That estimated best alpha becomes the only alpha that matters when scoring tasks for that block. The scheduler then greedily sorts tasks by weight divided by normalized demand on each block's chosen alpha, and allocates tasks while checking the real feasibility condition: every requested block must still have at least one alpha order left under budget. For the online case, DPack batches tasks every `T` time units, gradually unlocks each block's budget in `1/N` increments, and uses privacy filters so adaptive arrivals still preserve the desired `(epsilon, delta)` bound.

## Evaluation

The evaluation has three layers. First, an offline microbenchmark generates 620 RDP curves from five realistic DP mechanisms, then varies two heterogeneity knobs: how many blocks tasks request and how much their best alpha orders differ. On these workloads, DPack stays within 23% of the optimal Gurobi solution while significantly beating DPF once heterogeneity is nontrivial: up to 161% more scheduled tasks when block demands vary widely and up to 67% more when alpha-order heterogeneity rises. The same section also shows why exact optimization is not practical: with 7 blocks, the optimal solver becomes intractable beyond roughly 200 tasks, whereas DPack and DPF remain cheap.

Second, the paper builds Alibaba-DP, a more plausible online workload derived from Alibaba's 2022 ML cluster trace. Privacy usage and block counts are inferred from system metrics, so this is still a proxy workload, but it is less toy-like than prior synthetic traces. Here DPack allocates 1.3-1.7x as many tasks as DPF, or 22-43% more depending on the slice, and the gap persists as the number of available blocks changes. On the authors' Kubernetes prototype, DPack schedules 1269 tasks versus DPF's 1100 while showing similar waiting-delay distributions.

The evaluation supports the paper's main claim with one important qualifier: the win depends on heterogeneity. On a simple Amazon Reviews workload with little variation in block demand and only two best-alpha values, DPack and DPF behave almost identically. That result makes the paper more credible, because it shows DPack is not universally better; it is better exactly where the authors say it should be.

## Novelty & Impact

Relative to _Luo et al. (OSDI '21)_, the novelty is not a new privacy abstraction but a new optimization target. DPack keeps the same worldview of privacy blocks, adaptive arrivals, and DP accounting, then asks what changes when the scheduler optimizes packing efficiency rather than fairness. Relative to general multi-resource scheduling work such as _Ghodsi et al. (NSDI '11)_, the contribution is identifying why dominant share is the wrong objective once privacy is finite and RDP introduces alpha-order slack.

This is best understood as a new formulation plus a practical heuristic, not as a brand-new ML training system. Still, the impact could be real for operators of private analytics and recurring DP-ML pipelines, because a 1.3-1.7x improvement in admitted jobs translates directly into more models trained on the same user data under the same public privacy promise.

## Limitations

The biggest limitation is that much of the evaluation rests on synthetic or proxy-derived workloads. Alibaba-DP is more plausible than prior work, but privacy demand is still inferred from memory and network metrics rather than measured from real DP pipelines. If those proxies are weak, the exact magnitude of the gain could move.

The algorithm is also intentionally unfair by DPF's metric. In the Alibaba experiment, DPF schedules 90% of fair-share jobs while DPack schedules 60%, even though DPack admits 45% more total tasks. That tradeoff may be acceptable, but it means the paper does not solve fairness; it chooses not to prioritize it.

Finally, DPack is still a heuristic in the general case. The paper proves useful properties for special cases, but multi-block privacy knapsack remains hard and the algorithm has no global optimality guarantee there. The threat model is also narrow: the curator and task code are trusted, and the whole system assumes tasks come with correctly specified DP costs.

## Related Work

- _Luo et al. (OSDI '21)_ - PrivateKube and DPF introduce privacy budget scheduling as a systems problem; DPack keeps that model but replaces fairness-first allocation with efficiency-oriented packing.
- _Lécuyer et al. (SOSP '19)_ - Sage contributes privacy filters and block-based accounting over data streams, which DPack reuses when extending its offline heuristic to the online case.
- _Küchler et al. (S&P '24)_ - Cohere also manages DP as a first-class systems resource, but relies more on exact solving or workload structure, whereas DPack focuses on a scalable approximation.
- _Ghodsi et al. (NSDI '11)_ - Dominant Resource Fairness is the conceptual ancestor of DPF; this paper is partly an argument that dominant-share ordering misfires for finite privacy budgets.

## My Notes

<!-- empty; left for the human reader -->

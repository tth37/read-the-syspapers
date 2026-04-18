---
title: "Sailor: Automating Distributed Training over Dynamic, Heterogeneous, and Geo-distributed Clusters"
oneline: "Sailor jointly picks GPU allocation, 3D parallelism, and zone placement, then reconfigures Megatron jobs as heterogeneous resources appear and disappear."
authors:
  - "Foteini Strati"
  - "Zhendong Zhang"
  - "George Manos"
  - "Ixeia Sánchez Périz"
  - "Qinghao Hu"
  - "Tiancheng Chen"
  - "Berk Buzcu"
  - "Song Han"
  - "Pamela Delgado"
  - "Ana Klimovic"
affiliations:
  - "ETH Zurich"
  - "MIT"
  - "HES-SO"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764839"
code_url: "https://github.com/eth-easl/sailor"
tags:
  - llm-training
  - gpu
  - scheduling
  - datacenter
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Sailor argues that heterogeneous and geo-distributed GPUs only help training if the system jointly chooses which GPUs to use, how to partition the model, and where to place each stage. It combines a straggler-aware planner, a more accurate simulator for memory/runtime/cost, and a modified Megatron-DeepSpeed runtime that can execute heterogeneous plans and reconfigure when resources change.

## Problem

The paper starts from a practical cloud reality: large homogeneous clusters of top-end GPUs are scarce, and their availability changes over time. If a user cannot get 32 A100s in one zone, the obvious fallback is to mix A100s with V100s or spread the job across multiple zones. But that fallback can easily backfire. Slow GPUs, weaker links, and extra transfer charges can turn "more resources" into lower throughput or much higher cost.

Existing planners do not solve the full problem. Many assume a fixed resource allocation and only search over DP/PP/TP. Heterogeneity-aware systems like Metis and FlashFlex do not handle multi-zone placement well, while geo-distributed systems like DTFM and Atlas do not jointly optimize heterogeneous GPU types and full 3D parallelism. The result is either a huge search space that takes minutes or hours to navigate, or a simplified model that misses stragglers, OOM risks, and communication costs. Existing training frameworks are also a poor match: Megatron-DeepSpeed assumes uniform parallelism and does not support fast elastic reconfiguration when resources appear or disappear.

## Key Insight

The paper's core claim is that heterogeneous training should be treated as one coupled optimization problem, not as separate decisions for "which GPUs" and "which parallelization plan." The right plan depends on stage-level memory limits, per-GPU compute speed, interconnect bandwidth, pipeline stragglers, and cloud transfer pricing all at once. If those factors are modeled accurately enough, then many bad configurations can be pruned before deployment, and the remaining search can be solved quickly with dynamic programming plus a few domain-specific heuristics.

Just as importantly, the plan is only useful if the runtime can actually execute it. Sailor therefore pairs the planner with a training stack that allows different tensor-parallel degrees across pipeline stages and can re-plan without tearing the whole job down. That combination is what turns heterogeneous capacity into usable capacity.

## Design

Sailor has four pieces: a profiler, planner, simulator, and modified training framework. The profiler runs once per GPU node type and measures per-layer forward, backward, and update times across microbatch sizes and tensor-parallel degrees. It also records parameter counts, activations, and intermediate-state memory, plus pairwise bandwidth curves for different machine types and message sizes.

The planner takes resource quotas, current availability, an objective such as maximum throughput or minimum cost, and optional constraints such as a budget cap. It searches over microbatch size, pipeline degree, and data-parallel degree, while precomputing the minimum tensor-parallel degree needed for each stage/GPU type to avoid OOM. Several heuristics keep the search tractable: tensor parallelism stays within a node; impossible memory configurations are pruned early; data-parallel degrees are explored in the order implied by the objective; data-parallel replicas stay within one region; and zones inside a region are collapsed because their bandwidth is similar.

For a fixed pipeline shape, Sailor uses dynamic programming to choose per-stage resource tuples. Each stage gets a set of replicas described by GPU type, tensor-parallel degree, and region. The recurrence evaluates a stage together with the remaining pipeline, explicitly accounting for the stage straggler, synchronization bottleneck, and pipeline communication to the next stage. When optimizing under a budget, Sailor approximates the current stage as the straggler, solves the remaining stages under the residual budget, and iterates if that assumption was wrong.

The simulator is the planner's scoring function. It computes per-worker memory rather than assuming every stage looks the same, and includes parameters, optimizer state, gradients, activations, and communication-related memory. Runtime uses a 1F1B pipeline model with warmup, steady state, and cooldown, then adds gradient synchronization and update cost. It also computes cost per iteration by combining GPU rental cost with cross-zone or cross-region traffic cost. Finally, Sailor extends Megatron-DeepSpeed to support heterogeneous TP across stages and kill-free elasticity: a controller detects resource changes, re-invokes the planner, tears down communication groups, repartitions the model, and resumes from an asynchronous checkpoint.

## Evaluation

The simulator results are strong. On a homogeneous GH200 cluster for OPT-350M, Sailor cuts average memory-estimation error to 5.56% and runtime-estimation error to 6%, versus roughly 12.5%-74% memory error and 10%-20% runtime error for baselines. On a heterogeneous Titan-RTX / RTX-2080 / RTX-3090 cluster, Sailor's runtime error averages 4.5%, while Metis is around 28% and FlashFlex around 69%.

Those accuracy gains translate into better plans. In homogeneous A100-only experiments, Sailor beats the closest baseline by 1.15x throughput and outperforms Aceso by up to 5.7x. In heterogeneous A100+V100 setups, it beats AMP, FlashFlex, and Metis by 1.15x-2.03x when the mix is 50/50, and by 1.39x-1.57x when V100s are more abundant; it also lowers iteration cost by up to 2.67x because it avoids wasting resources on poorly balanced plans. In geo-distributed A100 experiments, Sailor is 1.9x-2.45x faster than DTFM on small real clusters, and on larger simulated setups it reaches 5.9x higher throughput with 9.48x lower cost per iteration.

The evidence supports the planner/simulator story more strongly than the "production-ready at extreme scale" story. The paper includes real-hardware validation and a reconfiguration microbenchmark, but many of the largest comparisons are simulator-driven and only use OPT-350M and GPT-Neo-2.7B. Even so, the results do show the central point: if the system models memory, stragglers, and transfer costs well enough, heterogeneous and cross-zone training can be beneficial instead of chaotic.

## Novelty & Impact

Relative to prior work, Sailor's contribution is the end-to-end coupling. Varuna, Piper, and Aceso mainly optimize parallelism for fixed, homogeneous clusters. Metis and FlashFlex move toward heterogeneous GPU support, while DTFM and Atlas reason about geo-distributed placement. Sailor is unusual because it combines all of the following in one stack: heterogeneous GPU types, multi-zone placement, objective-and-constraint-aware planning, per-worker memory simulation, and a runtime that can execute heterogeneous plans and reconfigure them online.

That makes the paper more important as a systems integration result than as a single algorithmic trick. It gives cloud training platforms and cluster schedulers a concrete blueprint for turning fragmented GPU supply into useful training capacity without asking users to hand-design every fallback configuration.

## Limitations

The paper has several scope limits. The profiler and simulator target dense models; MoE support is left for future work. The runtime model assumes 1F1B pipeline scheduling and does not incorporate activation offloading or rematerialization. Search time also degrades sharply as heterogeneity grows: with 256 GPUs per type in one zone, the paper reports 0.3 seconds for one GPU type, 6.2 seconds for two, and 4900 seconds for three.

There is also a gap between the planner model and operational reality. Large-scale results are often simulated, not deployed at 100s of GPUs in production. The framework still depends on NCCL-style collectives and acknowledges that NCCL initialization can take minutes at very large scale. Cross-vendor accelerators and highly unreliable geo-distributed links are discussed as future challenges rather than solved parts of the system.

## Related Work

- _Athlur et al. (EuroSys '22)_ — Varuna automates large-model training on fixed homogeneous resources, whereas Sailor jointly chooses the resource allocation and the parallelization plan while modeling heterogeneous memory limits.
- _Um et al. (USENIX ATC '24)_ — Metis targets heterogeneous GPUs, but Sailor adds geo-distributed placement, cost-aware planning, and much faster search under dynamic availability.
- _Yan et al. (arXiv '24)_ — FlashFlex supports heterogeneous LLM training, while Sailor argues that accurate memory/runtime simulation and topology search are necessary to avoid low-throughput or invalid plans.
- _Yuan et al. (arXiv '23)_ — DTFM optimizes decentralized geo-distributed training, but Sailor tackles synchronous 3D parallel training and explicitly accounts for both compute rental and inter-zone transfer cost.

## My Notes

<!-- empty; left for the human reader -->

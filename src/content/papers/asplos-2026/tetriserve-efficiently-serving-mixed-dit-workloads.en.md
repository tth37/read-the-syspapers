---
title: "TetriServe: Efficiently Serving Mixed DiT Workloads"
oneline: "Adapts sequence parallelism at diffusion-step granularity and packs requests round by round to raise DiT deadline hits on shared GPUs."
authors:
  - "Runyu Lu"
  - "Shiqi He"
  - "Wenxuan Tan"
  - "Shenggui Li"
  - "Ruofan Wu"
  - "Jeff J. Ma"
  - "Ang Chen"
  - "Mosharaf Chowdhury"
affiliations:
  - "University of Michigan, Ann Arbor, Michigan, USA"
  - "University of Wisconsin-Madison, Madison, Wisconsin, USA"
  - "Nanyang Technological University, Singapore, Singapore"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790233"
code_url: "https://github.com/DiT-Serving/TetriServe"
tags:
  - ml-systems
  - gpu
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

TetriServe treats DiT serving as a step-level GPU scheduling problem rather than a fixed-parallelism execution problem. It profiles how each resolution scales, then uses a round-based scheduler to choose the smallest GPU allocation that can still meet a request's deadline. On FLUX and SD3, this raises SLO attainment by up to 32% over fixed-parallelism baselines.

## Problem

The paper starts from a mismatch between DiT inference and current serving engines. DiT requests differ mainly in image resolution, so a 256x256 request and a 2048x2048 request impose very different costs. Existing systems such as xDiT still force each request onto one fixed sequence-parallel degree. Low parallelism is efficient for small images but too slow for large ones; high parallelism rescues large images but wastes GPUs on small ones. Because execution is effectively non-preemptive once a request starts, the wrong initial choice also blocks unrelated requests behind it. Under the paper's Uniform workload, no fixed strategy exceeds about 0.6 SLO Attainment Ratio at tight SLOs. The real problem is how to share a fixed GPU pool across mixed-resolution DiT requests while choosing parallelism dynamically enough to maximize deadline hits.

## Key Insight

The central claim is that DiT serving is predictable enough to schedule at diffusion-step granularity. Unlike LLM serving, DiT inference is stateless and compute-bound, and the paper measures per-step runtime variance below 0.7% across tested resolutions and sequence-parallel degrees. That makes an offline cost model credible. Once step latency is predictable, the scheduler can ask two sharper questions: what is the minimum GPU allocation that still lets this request meet its deadline, and how should the current round's GPU budget be spent so that the fewest requests become definitely late by the next round? That reframing turns an intractable global schedule into a tractable per-round decision.

## Design

TetriServe consists of a request tracker, a round-based scheduler, an execution engine, and a latent manager. The paper first formulates DiT serving as a deadline-constrained step-level GPU scheduling problem and proves even a simplified single-step variant is NP-hard, which motivates a heuristic design.

The first heuristic is deadline-aware GPU allocation. TetriServe profiles each step type offline as a function of GPU count, then at runtime chooses the smallest allocation that still satisfies the request's deadline while minimizing GPU-hours. The second heuristic is round-based packing. Time is divided into rounds of duration `tau`; for each request, the scheduler computes which allocations can make progress this round and whether skipping the request would make it definitely late by the next round. That decision has a group-knapsack structure, so TetriServe uses dynamic programming to choose at most one option per request under the GPU-capacity limit.

Two engineering mechanisms make the algorithm practical. GPU placement preservation keeps a request on the same GPU set across adjacent rounds when possible, reducing remapping stalls. Elastic scale-up then hands any leftover GPUs to requests that can benefit from temporarily higher parallelism. TetriServe also uses selective continuous batching for compatible small-resolution requests and runs the VAE decoder sequentially to control memory pressure. The implementation is 5,033 lines of Python and C++.

## Evaluation

The evaluation uses FLUX.1-dev on 8xH100 and Stable Diffusion 3 Medium on 4xA40. The default workload contains 300 DiffusionDB prompts arriving as a Poisson process at 12 requests per minute, with four resolutions from 256x256 through 2048x2048. Baselines are xDiT with fixed `SP=1/2/4/8` and RSSP, a stronger static baseline that chooses the best fixed SP for each resolution offline.

The headline result is that TetriServe consistently achieves the highest SLO Attainment Ratio. On average it beats the best fixed strategy by 10% on the Uniform mix and 15% on the Skewed mix; at tighter operating points the gap reaches 28% at `1.1x` SLO scale on the Uniform mix and 32% at `1.2x` on the Skewed mix. The resolution breakdown shows why: fixed-SP baselines look good only on the resolutions they are implicitly tuned for, while TetriServe stays strong across the full range. TetriServe also degrades more gracefully as arrival rate rises from 6 to 18 requests per minute, remains more stable under bursty traffic, still wins on homogeneous workloads, and finds that about five steps per round is the best granularity under load. The paper also checks that latent-transfer overhead stays below 0.05% of step latency and that placement preservation plus elastic scale-up improve both SAR and mean latency.

## Novelty & Impact

Relative to _Fang et al. (arXiv '24)_, TetriServe's novelty is not sequence parallelism itself, but treating the degree of parallelism as a per-step scheduling decision instead of a fixed runtime choice. Relative to _Huang et al. (arXiv '25)_, it is organized around per-request deadlines and SLO attainment rather than throughput alone. Relative to _Agarwal et al. (NSDI '24)_, it solves the orthogonal problem of how to schedule the denoising work that remains after caching. Its contribution is a scheduling mechanism for an emerging workload, not a new model architecture.

## Limitations

TetriServe depends on offline profiling for each model, hardware target, and GPU count, so portability is not free. Its action space is built around powers-of-two GPU allocations and a small discrete set of image resolutions, which fits the target deployment but narrows the evidence for messier real-world mixes. The round-based abstraction also introduces a real tuning problem: if rounds are too fine, scheduler overhead dominates; if they are too coarse, the system reacts too slowly before deadlines slip. Finally, the evaluation is single-model serving on shared GPUs, so the paper does not address multi-model routing, admission control across fleets, or interference from other tenants.

## Related Work

- _Fang et al. (arXiv '24)_ — xDiT provides the underlying DiT inference engine with fixed sequence-parallel configurations; TetriServe adds deadline-aware, per-step parallelism selection on top.
- _Huang et al. (arXiv '25)_ — DDiT also reallocates resources for diffusion models, but TetriServe is centered on SLO attainment for mixed online workloads rather than throughput-oriented serving.
- _Agarwal et al. (NSDI '24)_ — Nirvana reduces diffusion work through approximate caching, while TetriServe schedules the remaining work more effectively and composes cleanly with caching.

## My Notes

<!-- empty; left for the human reader -->

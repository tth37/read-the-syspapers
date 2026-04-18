---
title: "Aegaeon: Effective GPU Pooling for Concurrent LLM Serving on the Market"
oneline: "Aegaeon pools marketplace LLMs on shared GPUs by autoscaling at token boundaries, pairing phase-split scheduling with sub-second model and KV-cache switching."
authors:
  - "Yuxing Xiang"
  - "Xue Li"
  - "Kun Qian"
  - "Yufan Yang"
  - "Diwen Zhu"
  - "Wenyuan Yu"
  - "Ennan Zhai"
  - "Xuanzhe Liu"
  - "Xin Jin"
  - "Jingren Zhou"
affiliations:
  - "School of Computer Science, Peking University"
  - "Alibaba Group"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764815"
tags:
  - llm-inference
  - gpu
  - scheduling
  - datacenter
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Aegaeon makes GPU pooling work for model-market workloads by autoscaling at token boundaries instead of request boundaries. It splits prefill from decode, schedules the two phases differently, and cuts switching cost with component reuse, explicit memory management, and fine-grained KV-cache synchronization. That yields 2-2.5x higher sustainable arrival rates or 1.5-9x higher goodput than prior systems, plus an 82% GPU reduction in beta deployment.

## Problem

The paper studies a cloud model marketplace with thousands of models, a long popularity tail, and bursty hot models. In Alibaba Cloud Model Studio, 94.1% of models generate only 1.35% of requests, yet those cold models still consume 17.7% of GPUs when each model gets dedicated capacity. The problem is therefore not single-model throughput; it is that sporadic demand makes per-model reservation wasteful.

Current pooling methods both stall. Multiplexing is memory-bound and fits only two or three 14B-class models per 80 GB GPU. Request-level auto-scaling avoids that VRAM cap, but it is still bounded by active model count because LLM requests are long-lived. The paper formalizes `E[m] = M * (1 - e^-lambda*T)` and shows a case where 100 models at 3.7 aggregate requests/s still average 46.55 active models. Since switching occurs only after a request finishes, new arrivals wait behind active ones and suffer head-of-line blocking. TTFT/TBT SLOs make this worse, because a poor switch decision hurts both first-token and per-token latency.

## Key Insight

Aegaeon's central claim is that autoscaling must become a token-level scheduling primitive. If the system can reclaim a GPU between token-generation steps instead of between whole requests, it can break the active-model-count bottleneck behind request-level serverless serving.

That only works if two conditions also hold. Prefill and decode must be scheduled separately, because they have different latency structure and different slack. And the whole scale-down/scale-up path must be cheap enough to sit on the critical path; otherwise token-level control only adds overhead. Aegaeon therefore co-designs phase-specific scheduling with full-stack switching optimizations.

## Design

The control path uses a proxy plus Redis-synchronized metadata to dispatch requests into two GPU partitions: prefill instances and decoding instances. The paper argues this disaggregation avoids the instability of unified heuristics that either over-favor prompt arrivals or starve decode progress.

Prefill uses grouped FCFS. Requests for the same model join bounded groups so one scale-up can serve several prompts, but groups are appended to the least-loaded queue to stay close to arrival order. Batch size stays at one request because prefill latency grows roughly linearly with prompt length.

Decode uses weighted round-robin. Each decoding instance keeps same-model batches in a rotating work list and assigns each batch a time quota based on token slack and total switching overhead in the round. This spreads waiting time across many decode steps instead of turning it into one visible stall, while still leaving room to switch models.

The data path is what makes that control policy viable. A naive vLLM preemptive switch can take up to 26.9 seconds for a 13B model, so Aegaeon reuses executor components across models, allocates a self-managed VRAM buffer to avoid fragmentation and garbage collection, caches weights in host memory with page-locked staging buffers and optional prefetching, stores heterogeneous KV blocks in slab-allocated unified caches, and coordinates KV swap-in/swap-out with CUDA events. The paper reports that these changes remove over 80% of scale-up latency and drive end-to-end preemptive autoscaling latency down by up to 97%.

## Evaluation

The main evaluation uses two nodes with 16 H800 80 GB GPUs, 2 TB DDR5 per node, and 192 Xeon Platinum 8469C CPUs, serving 6B-14B models on ShareGPT-derived workloads with TTFT 10 s and TBT 100 ms. Baselines are ServerlessLLM, MuxServe, and an oracle-aided ServerlessLLM+ variant.

Results support the main claim. At 0.1 requests/s per model, Aegaeon sustains about 2x the goodput of ServerlessLLM and supports up to 70 models with 10 decoding instances, effectively seven models per GPU. At 0.5 requests/s per model, the gap rises to 2.5x as request-level head-of-line blocking worsens. On longer-input/output datasets, Aegaeon remains ahead by up to 2.5x. MuxServe never reaches the same regime because its optimizer refuses to place more than two models on one GPU under realistic memory pressure.

Breakdowns are consistent with the mechanism. Prefetching makes about half of scale-ups nearly instantaneous and the rest stay under one second; KV-transfer overhead is under one second per request; fragmentation stays below 20%. The system still works on 4xA10 nodes and on 72B models with TP=4, though its advantage shrinks under the strictest SLOs, where static multiplexing can catch up by paying no switch cost. In beta deployment, Aegaeon reduces GPU use from 1,192 H20s to 213 while raising average utilization from 13.3%-33.9% to 48.1% with no reported SLO violations in the monitored window.

## Novelty & Impact

Aegaeon is best read as a new mechanism for multi-model LLM serving, not just a faster cold-start system. Relative to _ServerlessLLM_, it moves the control point from request completion to token boundaries. Relative to _MuxServe_, it avoids the VRAM ceiling of static co-location. Relative to _DistServe_, it repurposes prefill/decode disaggregation from single-model throughput optimization into the basis for multi-model fairness and switch amortization. That combination makes it relevant to cloud inference providers and future work on LLM scheduling, autoscaling, and memory management.

## Limitations

Aegaeon needs latency slack. Its gains are strongest when TTFT/TBT budgets are loose enough to spend some of that slack on switching work; under the paper's strictest SLO setting, MuxServe catches up. The main experiments also assume high-end GPUs, large host memory, and fast host-device data paths, so the portability of the same cost structure to weaker deployments is not fully established.

Some policy questions remain open. Prefill and decode partitions are static in the main evaluation, the quota rules are heuristic, and fairness is discussed only through aggregate SLO attainment. The paper also does not quantify mispredicted prefetches, failure recovery, or multi-tenant isolation, which would matter in a more general public-cloud rollout.

## Related Work

- _Fu et al. (OSDI '24)_ - ServerlessLLM speeds up request-level serverless LLM serving, while Aegaeon moves the control point to token boundaries and optimizes repeated preemptive switches that carry KV state.
- _Duan et al. (ICML '24)_ - MuxServe multiplexes several resident models in GPU memory, whereas Aegaeon swaps models aggressively to exceed the memory-limited colocated-model count.
- _Zhong et al. (OSDI '24)_ - DistServe shows that splitting prefill and decode is valuable for LLM serving; Aegaeon turns that split into the basis for multi-model token scheduling and SLO-aware pooling.
- _Zhang et al. (OSDI '25)_ - BlitzScale accelerates live large-model autoscaling with host caching, but Aegaeon tackles the broader preemptive path, including engine reuse, fragmentation control, and KV-cache synchronization.

## My Notes

<!-- empty; left for the human reader -->

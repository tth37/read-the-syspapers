---
title: "NeuStream: Bridging Deep Learning Serving and Stream Processing"
oneline: "NeuStream turns dynamic DNN inference into stream modules, batches at module granularity, and reallocates fine-grained GPU resources to raise SLO-meeting goodput."
authors:
  - "Haochen Yuan"
  - "Yuanqing Wang"
  - "Wenhao Xie"
  - "Yu Cheng"
  - "Ziming Miao"
  - "Lingxiao Ma"
  - "Jilong Xue"
  - "Zhi Yang"
affiliations:
  - "Peking University"
  - "Peking University, Microsoft Research"
  - "Microsoft Research"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717489"
code_url: "https://github.com/Fjallraven-hc/NeuStream-AE"
tags:
  - ml-systems
  - scheduling
  - gpu
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

NeuStream treats dynamic DNN inference as a stream-processing graph of reusable modules instead of one monolithic model. That lets it batch requests whenever they reconverge on the same module and allocate GPU capacity separately across modules under partial SLOs. The paper reports up to 5.26x higher goodput than Clockwork on diffusion and up to 69.31x higher than vLLM on OPT serving under heavy load.

## Problem

Modern serving stacks assume requests follow one fixed graph. That breaks for LLM decode loops, diffusion denoising loops, SkipNet-style branching, and multi-agent pipelines, where requests revisit different sub-models at different times. GPU efficiency still depends on batching, so once two requests are in different phases, a monolithic scheduler loses the opportunity to reuse weights across them.

The paper also shows phase behavior is heterogeneous: Stable Diffusion's CLIP/UNet/VAE and OPT's prefill/decode have different latency-versus-batch curves. Past a phase-specific threshold, larger batches barely improve throughput but do extend waiting time, so SLO-aware serving needs both decomposition and per-phase batch sizing.

## Key Insight

The useful scheduling unit is the repeatedly executed control-flow body. Even if whole requests diverge globally, they often reconverge locally on the same large module, such as UNet or decode. If those bodies become first-class stream modules, the system can batch requests at module boundaries rather than requiring identical end-to-end paths.

With the end-to-end latency budget decomposed into partial SLOs, scheduling separates cleanly into two decisions: pick a profitable batch size within each module, and allocate enough GPU capacity across modules so the slowest stage does not cap pipeline goodput.

## Design

NeuStream introduces `stream`s and `stream module`s with `gather`, `compute`, and `scatter`. `gather` pulls batches from input streams, `compute` runs ordinary tensor code, and `scatter` routes outputs to downstream streams. Loops are expressed by feeding a module's output back into one of its own inputs, which is how the paper models diffusion iterations and LLM decode.

The runtime is a stream graph with a frontend and one worker per module. Workers repeatedly execute `gather-compute-scatter`, pass metadata plus tensor references through streams, and optionally keep per-request state. For LLMs, NeuStream stores decode KVCache as block-based state, updates it each step, and evicts it when the request leaves the loop.

Scheduling has two levels. Intra-module scheduling uses the profiled latency function `L_i(b, a_i)` and the module's partial SLO to cap batch size, then only admits requests whose remaining budget is still non-negative. Inter-module scheduling introduces Streaming Processing Units (SPUs), allocates them to maximize the minimum normalized goodput across modules under memory/resource constraints, and maps them onto GPUs with best-fit placement, optional model parallelism, and optional co-location. SPUs are implemented mostly as a scheduling abstraction: instead of hard MPS partitions, NeuStream converts spatial sharing into Earliest Finish Time First temporal scheduling with high-priority CUDA streams.

## Evaluation

The evaluation covers diffusion models, OPT-6.7B/13B/30B/66B, and MatPlotAgent on RTX 4090, RTX A6000, and H100 GPUs. Goodput is the metric. On diffusion, NeuStream beats the PyTorch-reimplemented Clockwork baseline by up to 5.26x at 4 requests/s on DiT-S/2, by 1.37x-4.04x at CV 4, and by up to 3.13x at SLO scale 1.2. The batching trace matches the mechanism: NeuStream's DiT batch size is 5.35x larger on average when requests have different remaining iteration counts, and still 1.67x larger when that source of heterogeneity is removed.

On LLMs, NeuStream improves OPT-13B decode goodput over vLLM by 1.53x at 2 requests/s and 37.21x at 4 requests/s on A6000, then reaches up to 69.31x on OPT-66B across four GPUs; on H100 the peak reported gain is 11.44x. The results support the claim that phase-aware decomposition prevents decode starvation and prefill congestion. The paper is reasonably careful about fairness, but it does not compare against phase-disaggregated alternatives such as DistServe or Splitwise, so the LLM gains should be read primarily as a win over monolithic serving.

## Novelty & Impact

Clockwork assumes predictable monolithic jobs, vLLM specializes in LLMs, and BrainStorm/Cocktailer focus on dynamic execution inside a model. NeuStream's contribution is to bridge DNN serving and stream processing: make modules the scheduling boundary, allocate GPU capacity at module granularity, and keep iterative state without falling back to one big runtime. That framing feels broadly useful for future pipelines that mix loops, branches, and multiple sub-models.

## Limitations

NeuStream requires manual rewriting: control flow must move into `scatter`, though the paper says the Stable Diffusion rewrite was under 7% of LOC. Its scheduling also depends on stable latency profiles and sensible partial-SLO assignment; the paper does not deeply study drift or misallocation. Benefits shrink on static models with homogeneous phases or when one request already saturates the GPU, and the evaluation mostly stays within single-node settings. Multi-node state migration and stronger LLM baselines are future work.

## Related Work

- _Gujarati et al. (OSDI '20)_ - Clockwork also uses latency prediction and SLO-aware serving, but it assumes monolithic DNN executions rather than dynamic module graphs.
- _Kwon et al. (SOSP '23)_ - vLLM improves LLM serving with PagedAttention and continuous batching, whereas NeuStream generalizes phase decomposition and resource balancing beyond the LLM-only case.
- _Cui et al. (OSDI '23)_ - BrainStorm optimizes dynamic neural networks by exploiting dynamism within an input, while NeuStream focuses on batching opportunities across multiple requests that revisit shared modules.
- _Zhang et al. (OSDI '23)_ - Cocktailer analyzes dynamic control flow from a compiler perspective, but NeuStream addresses runtime scheduling, SLO management, and resource allocation for deployed serving systems.

## My Notes

<!-- empty; left for the human reader -->

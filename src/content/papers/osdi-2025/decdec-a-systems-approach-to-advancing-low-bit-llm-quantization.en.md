---
title: "DecDEC: A Systems Approach to Advancing Low-Bit LLM Quantization"
oneline: "DecDEC keeps quantized weights on GPU but fetches only activation-selected residual channels from CPU, recovering low-bit LLM quality with near-hidden latency."
authors:
  - "Yeonhong Park"
  - "Jake Hyun"
  - "Hojoon Kim"
  - "Jae W. Lee"
affiliations:
  - "Seoul National University"
conference: osdi-2025
tags:
  - llm-inference
  - gpu
  - memory
category: llm-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

DecDEC keeps quantized weights on the GPU, stores weight residuals in CPU memory, and fetches only the residual channels selected by the current activation outliers. On AWQ-quantized 3-bit Llama-3-8B-Instruct, it cuts perplexity from 10.15 to 9.12 on RTX 4050 Mobile with 1.7% slowdown and less than 0.0003% extra GPU memory.

## Problem

The paper targets single-user, on-device LLM inference, where decode is dominated by memory-bound GEMV. Weight-only PTQ fits that regime because it reduces weight traffic without retraining, but 3-bit and 4-bit settings often lose too much quality.

CPU memory looks like an obvious place to store correction data, since desktops and laptops have abundant DRAM attached over PCIe. The difficulty is that PCIe bandwidth is much lower than GPU memory bandwidth, and decode leaves little slack. Prior outlier-aware quantizers rely on calibration-time statistics, but the paper shows that salient channels shift from step to step, so a static mask misses most of the useful corrections.

## Key Insight

Quantization errors matter most when the current activation amplifies them. DecDEC therefore identifies salient input channels at each decode step from the live activation vector and restores only the residual rows for those channels. This concentrates scarce PCIe bandwidth on the channels that dominate output error.

Over 100 decode steps, a static profiler recovers only about 20% of the true top outliers, while DecDEC's dynamic approximate Top-K stays close to exact selection and nearly matches its perplexity.

## Design

Each decode-time linear layer keeps the base path unchanged: the GPU computes `ob = Wq x`. In parallel, DecDEC selects `k` salient input channels from the current activation vector, fetches the corresponding residual rows from CPU memory, multiplies them by `x[sc_indices]`, and adds the correction `odec` back to `ob`. Functionally it computes `(Wq + R ⊙ M)x`, but the mask `M` is built online from current activations.

To fit the bandwidth budget, DecDEC quantizes the residuals themselves. It stores 4-bit symmetric uniform residuals plus one scale per output channel in CPU memory, and fetches only the selected rows.

The systems contribution is the implementation pipeline. DecDEC uses CUDA zero-copy instead of `cudaMemcpy`, because each fetch is only tens of KB. It replaces exact global Top-K with a chunked approximate selector: split the activation vector into 1024-element chunks, assign one thread block per chunk, scatter values into 32 buckets, and gather until `kchunk` slots are filled. Bucket boundaries come from two profiled thresholds, `bk0` and `bk15`. Channel selection, residual fetch, residual GEMV, and accumulation are then fused into one cooperative kernel. Extra GPU memory is tiny: in the paper's largest Llama-3 setting it is an 8.6 KB buffer, less than 0.0003% of model size. A one-time tuner chooses `ntb` and `kchunk` for each model-device pair under a slowdown target.

## Evaluation

On RTX 4090, RTX 4070 Super, and RTX 4050 Mobile, the correction path shows the expected two-phase behavior: small `kchunk` values are mostly hidden under base GEMV, then latency rises once PCIe transfer exceeds the overlap window. Platforms with a better PCIe-to-GPU-memory-bandwidth ratio move that knee to the right, which is why the 4050M can sustain larger `kchunk` than the 4090.

For model quality, DecDEC is added to AWQ and SqueezeLLM on 3-bit, 3.5-bit, and 4-bit Llama-3-8B-Instruct and Phi-3-medium-4k-instruct. Perplexity improves steadily as more salient channels are compensated. Even `kchunk = 8` helps: AWQ 3-bit Llama-3 drops from 10.15 to 9.63, and AWQ 3-bit Phi-3 drops from 5.96 to 5.53. The headline result is the low-end mobile case: on RTX 4050M, DecDEC drives AWQ 3-bit Llama-3 to 9.12 perplexity with only 1.7% slowdown, outperforming the 3.5-bit baseline while keeping the smaller memory footprint.

The ablations support the mechanism. Static channel selection is clearly weaker: DecDEC reaches lower perplexity while using 4x to 8x fewer compensated channels, and its approximate selector nearly overlaps exact dynamic Top-K. Gains are largest for 3-bit models and smaller at 4-bit, where the baseline is already closer to FP16. On server GPUs the method still helps, but less than raw bandwidth ratios suggest, because quantized GEMV becomes L1-bound.

## Novelty & Impact

Relative to _Lin et al. (MLSys '24)_ and similar outlier-aware quantizers, DecDEC does not add another offline protection rule. It moves saliency detection to decode time and couples it to host-memory residual retrieval. Relative to host-memory inference systems, CPU DRAM is not used for capacity, but for selective quality recovery. That makes the paper a new mechanism aimed squarely at consumer and edge deployment.

## Limitations

The approach is aimed at single-query decode, not throughput-oriented serving. It works best when base GEMV remains memory-bound enough that correction can hide underneath it; on server GPUs, the paper shows L1 pressure weakens that assumption. The selector still depends on calibration-derived bucket boundaries, and the tuner must be run once per model-device pair. Finally, the gains naturally shrink as the baseline quantizer approaches FP16, especially in 4-bit settings.

## Related Work

- _Lin et al. (MLSys '24)_ — AWQ protects statically identified salient channels during quantization, while DecDEC identifies saliency at each decode step and fetches residuals only for the currently important channels.
- _Kim et al. (ICML '24)_ — SqueezeLLM uses dense-and-sparse non-uniform quantization to shrink weights; DecDEC is orthogonal and recovers extra quality on top of that compressed model.
- _Lee et al. (OSDI '24)_ — InfiniGen uses CPU memory to offload KV cache capacity, whereas DecDEC spends host-memory bandwidth on correcting quantized weights during decode.
- _Sheng et al. (ICML '23)_ — FlexGen uses external memory for out-of-core, throughput-oriented inference, while DecDEC targets latency-sensitive single-query decode and accuracy recovery.

## My Notes

<!-- empty; left for the human reader -->

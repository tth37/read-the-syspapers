---
title: "MoE-APEX: An Efficient MoE Inference System with Adaptive Precision Expert Offloading"
oneline: "Cuts MoE expert-miss latency on edge devices by loading less important experts in low precision, prefetching across layers, and caching by miss cost."
authors:
  - "Peng Tang"
  - "Jiacheng Liu"
  - "Xiaofeng Hou"
  - "Yifei Pu"
  - "Jing Wang"
  - "Pheng-Ann Heng"
  - "Chao Li"
  - "Minyi Guo"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "The Chinese University of Hong Kong, Hong Kong, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790187"
tags:
  - llm-inference
  - memory
  - caching
  - gpu
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

MoE-APEX is an MoE offloading system for memory-limited edge devices that treats expert precision as a runtime decision. On each cache miss, it uses gating output to choose high precision, low precision, or skipping, then makes prefetching and caching aware of that choice. The result is large inference speedups because expert loading, not GPU math, is the dominant bottleneck.

## Problem

MoE models are attractive on edge devices because each token activates only a few experts, but the full expert pool is still too large to fit in GPU memory. Mixtral-8x7B activates 14B parameters per token yet needs 87 GB to store all 45B parameters, so existing systems keep only non-expert weights and a small expert cache on the GPU and fetch the rest from CPU memory or SSD.

That solves capacity, not latency. Loading one 336 MB Mixtral expert in float16 on Jetson Orin is about 20 times slower than GPU computation and about 5 times slower than non-expert processing. Expert loading accounts for 85.8% of runtime on RTX 4090 and 88.1% on Jetson Orin, so prefetching alone cannot hide the stall. Prior work either accepts large miss latency or skips experts aggressively and risks accuracy loss.

## Key Insight

The key idea is that not every missed expert is equally important. MoE-APEX uses the gating output as a cheap online proxy for expert importance and reports a 0.99 correlation between normalized gating magnitude and output contribution on Mixtral-8x7B. That lets the system decide, at miss time, whether an expert should be fetched in high precision, fetched in low precision, or skipped.

Once miss handling becomes precision-aware, the rest of the stack must be precision-aware too. MoE-APEX therefore co-designs miss-time loading, future-layer prefetching, and cache replacement around miss cost rather than miss count.

## Design

MoE-APEX has three coordinated components. First, the token-level Dynamic Expert Loader ranks the selected top-k experts by normalized gating magnitude and computes a cumulative score. Using thresholds `T1` and `T2`, it always keeps the top expert in high precision, loads less critical experts in low precision, and can skip the least important ones. For Mixtral-8x7B, the paper uses thresholds that produce about 67% high precision, 30% low precision, and 3% skipped selections; int2 is the low-precision fallback and can cut loading cost by up to 8x relative to float16.

Second, the layer-level Adaptive Expert Predictor exploits cross-layer similarity in hidden states and gating inputs. The paper reports about 96% top-1 prediction accuracy for the next layer and about 90% for the next two or three layers. Rather than evaluating future gating modules sequentially, MoE-APEX stacks them and computes them together on the GPU, then prefetches predicted experts and protects them from eviction.

Third, the sequence-level Cost-aware Cache Manager replaces LFU with Least Costly Used (LCU). LCU tracks separate high-precision and low-precision usage frequencies, weights them by loading cost, and adds recency and layer-distance signals. The cache should retain experts whose future misses would cost the most, not merely those with the highest aggregate use count. The prototype extends `Llama.cpp` with about 8,500 lines of C/C++.

## Evaluation

The evaluation uses four MoE models across three memory-limited platforms: Mixtral-8x7B and Phi-MoE on Jetson Orin and RTX 4090, plus DeepSeek-MoE and DeepSeekV2-Lite on RTX 2080 Ti. Baselines include Transformers, DeepSpeed-Inference, Llama.cpp, MoE-Offloading, MoE-Infinity, AdapMoE, and Fiddler where supported.

MoE-APEX wins on both prefill and decode across platforms. On Jetson Orin, it delivers average decoding speedups of 12.0x and 18.57x over Llama.cpp for Mixtral-8x7B and Phi-MoE, while reducing prefill latency by 78% and 80%; against MoE-Infinity, the decode speedups are 3.36x and 9.75x with 58% and 72% lower prefill latency. On RTX 4090, it still beats AdapMoE by 1.34x on Mixtral-8x7B and 1.59x on Phi-MoE. On RTX 2080 Ti with the DeepSeek models, it outperforms the best baseline by 1.49x and 1.68x in decoding speed.

The mechanism studies support the causal story. Mixed precision lowers accuracy by no more than 1% on GSM8K, ARC, and TruthfulQA. Dynamic loading alone contributes 1.22x to 1.53x speedup across settings. Prefetching cuts prefill latency by about 10% and has less than 1% misprediction overhead, while LCU reduces miss penalty by 2.36% to 3.10% versus LFU. The evidence is persuasive for single-request edge inference, though it does not test richer multi-tenant workloads.

## Novelty & Impact

Relative to _Hwang et al. (ISCA '24)_, MoE-APEX's distinctive move is making precision adaptive at miss time rather than only predicting what to preload. Relative to _Zhong et al. (ICCAD '24)_, it argues that low-precision substitution is often a better tradeoff than outright skipping. Relative to _Yu et al. (DATE '25)_, it contributes a more integrated redesign of loading, prefetching, and caching instead of mainly leaning on CPU-side assistance.

That makes the paper useful for researchers and practitioners trying to run MoE models on laptops, embedded GPUs, or small edge servers. Its real contribution is not a new model architecture, but turning adaptive precision into a first-class systems control knob for offloading.

## Limitations

The scope is narrower than the headline suggests. The system assumes precomputed low-precision expert copies and enough CPU memory or SSD space to store them; the paper reports 12% to 16% extra storage overhead. The evaluation is also centered on batch size 1, so continuous multi-request serving is mostly out of scope.

There are also portability questions. Thresholds are profiled per model, and the predictor relies on strong cross-layer similarity, so generalization to very different MoE designs is empirical rather than guaranteed. Baseline coverage is uneven across platforms because several prior systems do not support Jetson-class devices. The paper also shows only small average accuracy loss, not a deep analysis of long-tail inputs where importance estimates might fail.

## Related Work

- _Hwang et al. (ISCA '24)_ — Pre-gated MoE predicts future expert use to overlap loading, while MoE-APEX adds adaptive-precision miss handling and a precision-aware cache policy.
- _Zhong et al. (ICCAD '24)_ — AdapMoE skips low-importance experts; MoE-APEX instead treats low precision as a softer substitute that often preserves accuracy better.
- _Yu et al. (DATE '25)_ — DAOP leans on CPU-side predictive computation for MoE inference, whereas MoE-APEX focuses on reducing the cost of expert movement itself.
- _Kwon et al. (SOSP '23)_ — PagedAttention solves memory management for dense LLM serving; MoE-APEX addresses the different problem of sparse expert placement and fetching in MoE models.

## My Notes

<!-- empty; left for the human reader -->

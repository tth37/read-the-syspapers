---
title: "DiffKV: Differentiated Memory Management for Large Language Models with Parallel KV Compaction"
oneline: "DiffKV gives keys more bits than values, tiers tokens into K8V4/K4V2/pruned states per head, and compacts the irregular KV layout on-GPU for faster LLM serving."
authors:
  - "Yanqi Zhang"
  - "Yuwei Hu"
  - "Runyuan Zhao"
  - "John C.S. Lui"
  - "Haibo Chen"
affiliations:
  - "Huawei"
  - "The Chinese University of Hong Kong"
  - "Shanghai Jiao Tong University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764810"
tags:
  - llm-inference
  - memory
  - caching
  - gpu
category: llm-serving
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

DiffKV argues that KV-cache compression should not treat keys, values, tokens, and heads uniformly. It stores keys at higher precision than values, assigns each token per head to K8V4, K4V2, or prune based on significance, and then uses GPU-side parallel KV compaction to manage the resulting irregular layout efficiently. Across several LLMs, the paper reports 2.7x-5.7x KV-cache compression with near-lossless quality and 1.9x-5.4x higher throughput.

## Problem

The paper starts from a familiar serving bottleneck: during autoregressive inference, the KV cache often dominates memory usage, and its size grows with both sequence length and concurrency. The authors cite prior evidence that the cache can exceed 90% of total memory use, which means serving throughput is often capped not by compute but by how many requests' histories can stay resident.

Prior systems attack that bottleneck with either pruning or quantization, but both use overly uniform policies. Pruning methods decide which tokens to keep, yet typically assign the same memory budget to every head or layer. Quantization methods shrink every key and value vector to the same bit width, even though keys and values do different jobs inside attention. Neither approach adapts well to request-to-request variation: one prompt may be information-dense and require many high-fidelity tokens, while another can tolerate much more aggressive compression.

The harder systems problem is that a better compression policy creates a messier memory layout. If different heads in different requests want different mixtures of high-precision pages, low-precision pages, and pruned tokens, the allocator no longer manages one regular cache shape per request. It has to coordinate thousands of heterogeneous regions every decoding step. Without a memory manager that can exploit that irregularity cheaply, smarter compression would save bytes on paper but not translate into higher serving throughput.

## Key Insight

The central claim is that KV-cache compression should follow the structure of attention itself. Keys matter more than values because they influence the attention-score denominator and therefore affect the weighting of all tokens, while each value vector only contributes to its own token's weighted sum. The authors back this with an empirical observation on Llama3: attention scores span roughly seven orders of magnitude, whereas value norms vary by only about two, so preserving score fidelity matters more than preserving value magnitude exactly.

That is only the first layer of differentiation. Token importance is also highly skewed, and the skew changes across heads and requests. Some heads need many important tokens to preserve 95% of the attention mass; others need far fewer, and the same head behaves differently under different prompts. DiffKV's key insight is therefore not just "quantize asymmetrically," but "combine asymmetric key/value precision, hierarchical token importance, and per-head dynamic allocation." Once those three ideas are combined, the irregularity is not noise to be hidden; it is the signal that allows more aggressive compression.

## Design

DiffKV uses two quantization levels plus pruning. Important tokens are kept in K8V4, moderately important ones in K4V2, and the least important are removed entirely. In the prompt phase, the system computes each token's significance from the attention it receives from later tokens. For GQA or MHA, it aggregates query-head scores by maximum for the corresponding KV head. The most recent 64 tokens are always kept at high precision to avoid premature damage. Older tokens are compared against sequence-length-aware thresholds, `alpha_h / i` and `alpha_l / i`, where `i` is the token position, so the policy becomes more aggressive as the context grows.

The generation phase keeps the same logic but applies it incrementally. When a token exits the recent window, DiffKV decides whether to insert it into the high-precision cache, the low-precision cache, or drop it. If it inserts a new token into a tier, it may also downgrade the least significant existing token in that tier, creating a smooth path from high precision to low precision to pruning. The thresholds are calibrated offline on a reasoning-heavy dataset, and the paper deliberately stops at two precision tiers because extra levels would add metadata and management overhead faster than they help quality.

The real systems contribution is the GPU memory manager. DiffKV introduces unified pages whose format is chosen at allocation time, so a page can store one precision mode compactly instead of reserving the worst-case layout for every token. It keeps all page IDs in a circular free-page list with start and end pointers, which allows page allocation and recycling to be coordinated with prefix sums. It also replaces separate high- and low-precision page tables with a bidirectional page table whose high-precision entries grow from the left and low-precision entries from the right. The planning phase lets each head independently decide how many pages it needs; the coordination phase maps those requests onto physical pages in parallel on the GPU. A custom attention kernel then processes high-precision pages and low-precision pages efficiently with layouts chosen for coalesced memory access.

## Evaluation

The evaluation spans Llama3-8B and 70B, Qwen2.5-7B and 32B, and three reasoning-heavy thinking models: QwQ-32B, R1-Distill-Qwen-14B, and R1-Distill-Llama-8B. Most throughput experiments run on NVIDIA L40 GPUs, with an additional port to Ascend NPUs to show the approach is not tied to one accelerator vendor.

The first important result is that the asymmetric precision choice is real, not aesthetic. K8V4 matches FP16 quality across the tested GSM8K and HumanEval+ settings, while mirror choices such as K4V8 or K2V4 degrade sharply, sometimes to near-zero accuracy. That directly supports the paper's claim that keys deserve more bits than values. The second result is that dynamic sparsity beats static head-equal pruning: on Llama3-8B, DiffKV keeps full GSM8K accuracy even with 50% of tokens pruned, while static sparsity loses more quality at the same pruning ratio.

End to end, the paper reports that DiffKV uses only 19.3%-36.7% of FP16 KV-cache memory on the non-thinking models with just 0.3% average accuracy degradation. On the thinking models, where long chain-of-thought generations make error accumulation much harsher, DiffKV still stays near FP16 quality while using 23.5%-29.4% of the memory. The system results are correspondingly strong: throughput improves by 1.9x-5.4x over vLLM, and on QwQ-32B DiffKV raises sustained batch size from 2.7 to 15.9 and reaches 5.4x higher throughput. Just as importantly, the memory manager is not the bottleneck: parallel KV compaction contributes under 0.2% of prompt-step latency and under 0.9% of generation-step latency.

## Novelty & Impact

The paper's main contribution is the combination of policy and mechanism. Prior work typically improves KV compression by choosing better tokens to drop or better low-bit encodings to apply. DiffKV argues that those choices are inseparable from the allocator and attention kernel, because differentiated compression creates irregular per-head memory demand that a conventional memory manager cannot exploit efficiently. That makes this paper relevant not just to KV-cache researchers, but to anyone building serious LLM serving runtimes: the next serving wins are likely to come from co-designing compression policy, layout, and runtime memory management rather than optimizing any one layer in isolation.

## Limitations

DiffKV depends on offline calibration, and the tuned thresholds are somewhat model-specific. Qwen2.5-7B, for example, is sensitive enough that the paper disables low-precision quantization for it. That does not break the overall story, but it means the method is not yet parameter-free.

The implementation complexity is also nontrivial. The strongest performance results rely on a custom attention kernel, GPU-resident memory-management data structures, and direct integration into vLLM. A simpler framework-level implementation would likely preserve some of the quality gains but not all of the throughput gains. Finally, the evaluation mainly covers two precision tiers, FP16 model weights, and the paper's chosen serving workloads; prefix-sharing multi-tenant deployments and other cache-reuse-heavy scenarios are not explored in depth.

## Related Work

- _Kwon et al. (SOSP '23)_ - PagedAttention/vLLM makes growing KV caches practical with page-based allocation, but it assumes a regular cache format instead of per-head mixed precision and pruning.
- _Lin et al. (arXiv '24)_ - QServe shows that low-bit KV quantization can be system-effective, whereas DiffKV varies precision across keys, values, and tokens rather than fixing one quantization mode for the whole cache.
- _Li et al. (arXiv '24)_ - SnapKV prunes tokens using attention-derived importance, but it allocates cache budgets much more statically across heads than DiffKV's per-head, per-request policy.
- _Liu et al. (arXiv '24)_ - KIVI applies asymmetric low-bit KV quantization without tuning, while DiffKV adds hierarchical token selection and a runtime that can capitalize on the irregular compressed layout.

## My Notes

<!-- empty; left for the human reader -->

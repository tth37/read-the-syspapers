---
title: "CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion"
oneline: "CacheBlend fuses KV caches from multiple reused RAG chunks, selectively recomputes only high-impact tokens, and cuts TTFT by 2.2-3.3x without meaningful quality loss."
authors:
  - "Jiayi Yao"
  - "Hanchen Li"
  - "Yuhan Liu"
  - "Siddhant Ray"
  - "Yihua Cheng"
  - "Qizheng Zhang"
  - "Kuntai Du"
  - "Shan Lu"
  - "Junchen Jiang"
affiliations:
  - "University of Chicago/CUHK Shenzhen"
  - "University of Chicago"
  - "Stanford University"
  - "Microsoft Research / University of Chicago"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696098"
code_url: "https://github.com/LMCache/LMCache"
tags:
  - llm-inference
  - caching
  - gpu
  - datacenter
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CacheBlend fills the gap between safe but limited prefix caching and fast but inaccurate full KV reuse. It reuses each chunk's precomputed KV cache, selectively recomputes only the tokens whose missing cross-attention matters most, and overlaps that work with KV loading. Across four datasets and three open models, the paper reports 2.2-3.3x lower TTFT with negligible quality loss.

## Problem

RAG and similar LLM applications often prepend several retrieved text chunks before the user query. Prefill must scan that entire context and build the KV cache before the first output token appears. The paper cites roughly 3 seconds of prefill for a 4K-token Llama-34B input and 6 seconds for Llama-70B on one A40 GPU, so TTFT becomes the visible bottleneck.

Existing KV reuse schemes fail for different reasons. Prefix caching preserves quality because prefix KV is independent of the suffix, but it only helps for the first chunk; in multi-chunk RAG, most reused text is still re-prefilled. Full KV reuse, in the PromptCache style, can place chunk KV caches at arbitrary positions by correcting positional encoding, but it omits cross-attention from earlier chunks into later ones. The paper shows this omission hurts exactly when several relevant chunks must be reasoned over jointly.

## Key Insight

The key claim is that CacheBlend does not need to recompute the whole input to recover most of the lost quality. Full KV reuse is badly wrong only for a sparse subset of tokens whose representations depend on preceding chunks. If those tokens are refreshed on each layer, the forward attention matrix stays close to full prefill while the cost stays close to reuse.

Two observations make this practical. First, attention is sparse, so only about 10-15% of tokens tend to have large KV deviation. Second, high-deviation tokens on one layer are strongly correlated with those on adjacent layers. That lets the system discover likely problem tokens incrementally instead of rerunning full prefill.

## Design

CacheBlend starts from independently precomputed KV caches for reusable chunks. At serving time it concatenates those caches, restores the right positions for non-prefix chunks, and then runs selective KV recompute layer by layer. On a layer, it masks the input down to a chosen token subset, computes `Q`, `K`, and `V` only for that subset, then merges those entries with reused entries for the remaining tokens before running normal attention. If the recompute ratio is `r%`, the extra compute is roughly `r%` of full prefill.

Selecting the token subset is the main trick. CacheBlend uses gradual filtering: the first layer picks a slightly oversized candidate set using token-wise attention deviation, and later layers only recompute those candidates, shrinking the set toward the target ratio. Tokens that remain problematic across neighboring layers are the ones worth paying to update.

The system hides much of this cost with pipelining. Recompute for layer `i` overlaps with loading the precomputed KV for layer `i+1`, so partial recompute can be absorbed by storage latency. A controller combines offline model profiles with device throughput to pick both recompute ratio and storage device; the paper uses 15% as the quality-preserving floor.

## Evaluation

The evaluation uses Mistral-7B, Yi-34B, and Llama-70B on Runpod machines with A40 GPUs, 128 GB RAM, and 1 TB NVMe SSD. Workloads cover 2WikiMQA, Musique, SAMSum, MultiNews, and extended RAG traces built from retrieved top-6 chunks.

The headline result is consistent across models and tasks. Compared with full KV recompute, CacheBlend lowers TTFT by 2.2-3.3x and improves throughput by 2.8-5x. F1 or Rouge-L stays within about 0.02 of full recompute and prefix caching, while full KV reuse loses much more quality. Relative to full KV reuse, CacheBlend keeps nearly the same TTFT while improving QA by 0.1-0.2 absolute F1 and summarization by 0.03-0.25 Rouge-L.

The evaluation is reasonably fair, and in one place conservative: the prefix-caching comparison assumes zero RAM/SSD-to-GPU loading delay, which helps the baseline. Sensitivity results also match the mechanism. A 5-18% recompute ratio is enough to keep quality loss on Yi-34B within 0.002 while still yielding 4.1-6.6x TTFT reduction.

## Novelty & Impact

The novelty is not simply non-prefix KV reuse, since PromptCache already explored that direction. CacheBlend's contribution is recovering missing cross-attention with selective recomputation and making that extra work cheap enough to pipeline with storage. That turns KV reuse from a template-centric trick into something usable for genuine multi-chunk RAG. This should matter to operators of RAG systems, enterprise assistants, and long-context serving stacks that want to move KV caches out of scarce GPU memory.

## Limitations

The paper is upfront that the method targets transformer models and depends on reuse. If requests rarely share chunks, or if the workload is mostly single-chunk prefix reuse, CacheBlend has much less room to help. The token-selection policy is also empirical rather than guaranteed: the 15% floor, the neighboring-layer correlation, and the storage-controller choices all come from measurement, not proof. The evaluation is limited to three models, four datasets, and single-node vLLM serving, leaving newer engines and cross-node KV sharing to future work.

## Related Work

- _Gim et al. (arXiv '23)_ - PromptCache enables modular KV reuse at non-prefix positions, but it still omits cross-attention, which is precisely the error CacheBlend selectively repairs.
- _Jin et al. (arXiv '24)_ - RAGCache accelerates RAG with prefix-oriented KV reuse and cache management, whereas CacheBlend targets multi-chunk fusion when reused text is not confined to the prefix.
- _Liu et al. (arXiv '23)_ - CacheGen focuses on faster context loading and compressed KV storage; CacheBlend is complementary because it addresses how to fuse multiple loaded chunk caches without hurting quality.
- _Kwon et al. (SOSP '23)_ - vLLM/PagedAttention improves the serving substrate and KV memory management, and CacheBlend builds directly on that substrate to reduce the prefill work itself.

## My Notes

<!-- empty; left for the human reader -->

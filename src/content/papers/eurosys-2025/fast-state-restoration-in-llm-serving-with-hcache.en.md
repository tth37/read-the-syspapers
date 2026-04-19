---
title: "Fast State Restoration in LLM Serving with HCache"
oneline: "HCache stores per-layer hidden states instead of full KV cache, then pipelines loading with cheap KV reconstruction to cut state-restoration TTFT by up to 1.93x."
authors:
  - "Shiwei Gao"
  - "Youmin Chen"
  - "Jiwu Shu"
affiliations:
  - "Tsinghua University"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696072"
tags:
  - llm-inference
  - caching
  - gpu
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HCache argues that cache misses in LLM serving should not be repaired by either replaying the whole prompt or reloading the whole KV cache. Instead it stores per-layer hidden states, reconstructs KV with projection GEMMs plus RoPE, and overlaps that work with storage reads. On ShareGPT4 and L-Eval, the paper reports up to 1.93x lower TTFT than KV offload and up to 5.73x lower TTFT than token recomputation, with less than 4% TBT overhead.

## Problem

The paper targets stateful LLM workloads where a new request depends on prior context: multi-round chat, long-document QA, code understanding, and RAG. These systems want to reuse old state, but GPU memory is too small to keep much of it resident. The authors estimate that one A100-40GB can hold only 7-20 conversation sessions or 1-3 long contexts, so cache misses are common.

Existing restoration methods each fail differently. Token recomputation reruns prefill from the original tokens, paying the full attention and FFN cost again; with long histories, quadratic attention dominates. KV offload skips recompute but moves a huge object back from host storage, with KV cache roughly 105x larger than the original tokens in typical models. On L-Eval, recomputation is 20.0-26.0x slower than an ideal no-restoration system, while KV offload is still 6.5-13.0x slower.

## Key Insight

The reusable state does not have to be the KV cache itself. For each transformer layer, the hidden state is already the input from which the model derives that layer's keys and values, so the system can store hidden states and recreate `K` and `V` by replaying only the projection step.

That swap saves both bandwidth and compute. Hidden states are half the size of KV cache, so transmission is 2x smaller. Reconstructing KV from hidden states skips the expensive attention and FFN work, making the compute side at least 6x cheaper than token recomputation in the paper's model and keeping restoration linear in sequence length. Because hidden-state loading is an I/O task while projection is a compute task, the two can be pipelined.

## Design

During the original request, the serving system dumps each layer's hidden states. On a later cache miss, it reads them back layer by layer, uses cuBLAS GEMMs to project them into `K` and `V`, reapplies RoPE with a custom kernel, and writes the result into the runtime KV cache.

The hard part is keeping that pipeline balanced. HCache's bubble-free scheduler partitions model layers between HCache and a complementary method. On compute-rich, I/O-poor hardware, some early layers use token recomputation while later hidden states are prefetched; on I/O-rich, compute-poor hardware, some layers use direct KV offload so transmission fills otherwise idle time. The paper chooses layer-wise rather than token-wise partition because irregular small-token GEMMs perform poorly. On the storage side, hidden states are laid out as 64-token chunks spread round-robin across SSDs, and saving uses a two-stage path: one `cudaMemcpy` snapshots hidden states to host DRAM, then CPU threads repack and flush large writes to NVMe. Multi-GPU support shards reads by token and reconstructs full states with NVLink all-gather.

## Evaluation

The implementation adds 5,731 lines of CUDA, C++, and Python to DeepSpeed-MII. The main testbed uses 4x A100-40GB SXM4 GPUs, 256 GB DRAM, and 4x Samsung PM9A3 4 TB SSDs, with Llama2-7B, Llama2-13B, and OPT-30B on ShareGPT4 and L-Eval.

On ShareGPT4, HCache improves TTFT by 1.27-1.90x over KV offload and 2.21-3.57x over recomputation; for 7B and 30B it also sustains up to 11% more requests. TBT stays within 4% of the ideal no-restoration case. On representative L-Eval tasks, HCache improves TTFT by 1.62-1.93x over KV offload and 2.66-5.73x over recomputation. Per-token state shrinks from 256/400/672 KiB under KV offload to 132/210/280 KiB for 7B/13B/30B, a 1.92-2.40x reduction. Without the bubble-free scheduler, HCache-O can be 13% slower than KV offload on I/O-sufficient hardware, while direct-to-SSD saving raises TBT by up to 34%.

## Novelty & Impact

The novelty is the representation shift. Prior stateful serving systems mostly keep KV cache as the unit of reuse and then optimize where to place it; HCache instead restores a cheaper representation and materializes KV only at the end. The scheduler and chunk layout are what make that shift practical. This should matter to builders of SSD-backed chat and long-context serving systems, and more broadly it reframes cache misses in LLM serving as a state-representation problem, not just a placement problem.

## Limitations

The benefits depend on misses actually happening. In the paper's Zipfian cache-reuse study, once GPU hit ratio rises to 94%, HCache is still faster than KV offload but only by 1.15x. The design is also hardware-aware rather than universal: the scheduler depends on offline profiling, and the best mix between hidden states, KV offload, and token recomputation changes with the platform. Finally, the evidence is limited to DeepSpeed-MII, three models, and 16K-context traces, while GPU cache management, compression, and admission policy are treated as orthogonal work.

## Related Work

- _Gao et al. (ATC '24)_ - AttentionStore/CachedAttention keeps full KV cache in tiered host storage; HCache reduces miss cost by changing the stored representation from KV to hidden states.
- _Gim et al. (MLSys '24)_ - Prompt Cache improves the GPU-resident reuse path for modular prompts, while HCache focuses on the cache-miss path after state has already left GPU memory.
- _Jin et al. (arXiv '24)_ - RAGCache manages multi-tier KV cache placement for retrieval-heavy workloads; HCache instead makes restoration cheaper even when placement misses are unavoidable.
- _Liu et al. (SIGCOMM '24)_ - CacheGen compresses and streams KV cache to cut transfer cost, whereas HCache is lossless and avoids moving the full KV object in the first place.

## My Notes

<!-- empty; left for the human reader -->

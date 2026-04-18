---
title: "SolidAttention: Low-Latency SSD-based Serving on Memory-Constrained PCs"
oneline: "Co-designs sparse attention, SSD-friendly KV layout, speculative prefetching, and DAG scheduling so 128k-context LLMs run on memory-constrained PCs up to 3.1x faster."
authors:
  - "Xinrui Zheng"
  - "Dongliang Wei"
  - "Jianxiang Gao"
  - "Yixin Song"
  - "Zeyu Mi"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems (IPADS), Shanghai Jiao Tong University"
conference: fast-2026
category: ai-era-storage
tags:
  - llm-inference
  - storage
  - caching
  - memory
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

SolidAttention is an SSD-backed LLM inference engine for AI PCs that cannot keep long-context KV caches in memory. Its core move is to co-design sparse attention with storage behavior: interleave K/V data to make transfers coarse-grained, speculate on future block selections to prefetch early, and schedule GPU work and SSD I/O as microtasks. On 128k-token inputs, that yields up to `3.1x` higher throughput and about `98%` less KV-cache memory usage while keeping accuracy close to the original model.

## Problem

The paper targets a very specific but increasingly important regime: single-user local LLM serving on memory-constrained PCs. The authors argue that this environment is fundamentally different from datacenter serving assumptions. Many shipping PCs still have only `8-16 GB` of DRAM and `6-8 GB` of VRAM, yet long-context models increasingly default to `128k` contexts. For an `8B` model, the KV cache alone can exceed `16 GB`, more than `4x` the footprint of the quantized model weights. That makes the usual assumption of "keep the whole KV cache in memory" unrealistic for local deployment.

Two obvious fixes both break in practice. Aggressive KV-cache quantization saves memory, but the paper argues and later measures that it can hurt accuracy badly, especially when outliers dominate the cache. SSD offloading combined with dynamic attention sparsity is more promising, because the system only needs to fetch context blocks likely to matter for the current decode step. The problem is that prior SSD-based approaches are throughput-oriented: they rely on concurrent requests to hide storage latency behind other computation. Local AI PC inference usually runs with batch size `1`, so that overlap window disappears.

The paper's sharper diagnosis is that sparse attention and SSDs want opposite access patterns. Sparse attention naturally triggers irregular, fine-grained block fetches, while SSDs deliver good performance only for coarse, sequential transfers. If a system preserves the sparsity algorithm but treats storage as a passive backing store, it ends up with poor SSD bandwidth utilization and visible blocking latency during decoding.

## Key Insight

The main proposition is that SSD-backed sparse attention only works well if the attention mechanism and the storage path are redesigned together. SolidAttention is not mainly a better block-selection heuristic. Instead, it asks how to preserve the accuracy benefits of dynamic attention sparsity while reshaping the resulting access stream into something SSDs can serve efficiently.

That leads to three linked ideas. First, enlarge the transfer unit without enlarging the semantic selection unit: instead of coarsening token blocks so far that the representative vector becomes inaccurate, interleave each token's `K` and `V` entries and move them together. Second, exploit the paper's empirical observation that selected blocks are highly stable across consecutive iterations, with about `81%` similarity, so future layers can be prefetched speculatively. Third, treat compute and I/O as one dependency graph rather than a layer-by-layer pipeline, so missing-block loads, projections, attention, and write-back can overlap at microtask granularity.

## Design

SolidAttention keeps the now-familiar block-wise sparse-attention structure but adapts it for storage. The KV cache is partitioned into three block classes: deterministic init blocks for attention sinks, deterministic local blocks for recent context, and dynamically selected blocks chosen by query-to-representative similarity. The system follows InfLLM's style of block representatives, so the selection logic itself is not the primary novelty.

The `KV Consolidator` is the first major systems contribution. Normally, `K` and `V` are generated and stored separately. SolidAttention interleaves them at token granularity and makes that interleaved form the transfer and compute unit. This doubles the transfer size and halves the number of I/O operations without increasing the number of tokens compressed into each representative block, so it avoids the recall loss that comes from simply making attention blocks larger. To avoid runtime reshuffling, the system pre-concatenates the `K` and `V` projection weights at initialization and emits interleaved KV data directly from one matrix multiplication. Attention kernels then read with stride `2H`, which the paper says adds at most `2%` overhead.

The `Speculative Prefetcher` addresses the next bottleneck: block choice for a later layer is not known before that layer's query is computed. SolidAttention exploits temporal locality by recording each layer's prior selection and prefetching those selected blocks for the next iteration, together with the deterministic init and local blocks. When the prediction is wrong, it does not reorder the cache. Instead, it relies on a useful property of self-attention: global KV ordering can be arbitrary as long as each token's `K` and `V` stay aligned. Missing blocks are loaded and directly overwrite incorrectly prefetched ones. That turns misprediction into a cheap overwrite rather than a costly compaction step.

The `SSD-aware Scheduler` is the third piece. The paper decomposes an attention layer into `q proj.`, `kv proj.`, `select`, `prefetch`, `load`, `attention`, and `store` microtasks, then builds a DAG over their dependencies. Critical-path tasks run first; other I/O tasks are launched as early as possible to overlap with GPU work. The scheduler also computes latest start times to prioritize ready tasks that are most likely to stall the critical path. A second optimization reuses synchronization points: non-critical store tasks share handshakes with critical prefetch/load tasks instead of forcing separate CPU-GPU syncs. On unified-memory machines, some of those handshakes disappear entirely.

## Evaluation

The evaluation is well aligned with the claimed deployment setting. SolidAttention is implemented on top of `llama.cpp` with `liburing`, totaling about `25k` lines of code, and runs on both a CUDA laptop with an `RTX 4070 Laptop GPU` and a SYCL laptop with an `Intel Arc 140T` integrated GPU. The models are `Llama-3.2-3B`, `Llama-3.1-8B`, and `Qwen-2.5-7B`, all with INT4 weights but FP16 KV caches. Every experiment uses batch size `1`, max output `512`, and a `16 GB` DRAM limit, which is exactly the low-concurrency local regime the paper is trying to win.

The end-to-end gains are strong. On the CUDA backend with `128k` inputs, SolidAttention improves throughput over `Offload+Sparse` by `2.8x`, `3.1x`, and `2.4x` for the three models, and it beats FlexGen by up to `58.9x` at `16k` context while FlexGen runs out of memory beyond `16k`. On the SYCL backend, the gains over `Offload+Sparse` still reach `2.1x`, `2.5x`, and `1.9x`. Memory savings are equally central: because SolidAttention only allocates enough buffer for one layer's `1k`-budget KV cache, it cuts KV memory by roughly `61.9-62.0x` on the three main models and by about `98%` on a larger `Qwen2.5-14B` study. Accuracy also looks good. Against original `llama.cpp`, SolidAttention stays close on OpenCompass and LongBench, while INT4 KV quantization degrades sharply, especially on `Qwen-2.5-7B`.

The ablations support the mechanism rather than just the headline number. Speculative prefetching reduces blocking latency by up to `3.1x` on SYCL and `3.9x` on CUDA. Interleaved KV layout cuts attention latency by up to `22%`. Fine-grained overlap improves performance by up to `25%`, and synchronization reuse removes another `22%` of attention latency on the SYCL platform. I found the baseline choice mostly fair for the target regime, though one caveat remains: the authors had to extend FlexGen to support Llama and Qwen, so that comparison is somewhat less apples-to-apples than the `Offload` and `Offload+Sparse` baselines.

## Novelty & Impact

Relative to _Tang et al. (ICML '24)_ and _Xiao et al. (NeurIPS '24)_, SolidAttention is not proposing a new sparsity criterion so much as a storage-conscious execution substrate for block-wise sparsity. Relative to _Sheng et al. (ICML '23)_, its novelty is the explicit claim that low-concurrency local decoding needs a different design target from throughput-oriented cloud serving. And relative to _Chen et al. (FAST '25)_, it optimizes direct GPU-SSD KV movement instead of multi-request cloud prefix caching.

That makes the paper important for people building on-device or edge LLM systems. Its likely impact is less in changing how researchers think about attention sparsity itself and more in showing that consumer SSDs can be a viable KV tier if the software stack respects storage granularity, prefetchability, and synchronization cost.

## Limitations

The design wins in a narrow operating region and the paper is honest about that. The strongest case is single-user local inference with low request concurrency. It says much less about multi-tenant serving, large batches, or systems that already have enough concurrency to hide SSD latency in the FlexGen style. The implementation is also fairly intricate: interleaved weights, speculative history, overwrite correction, DAG scheduling, and synchronization reuse all have to work together, which raises engineering complexity.

Performance also depends on SSD headroom. Under concurrent background traffic, SolidAttention's throughput drops by `58%` with `4 GB/s` of bandwidth-bound interference and by `54%` under `800k` random-read IOPS interference. The paper also shows that once the context budget rises to `4k`, I/O becomes the bottleneck again, which is why the chosen `1k` budget matters. So the system is robust within the tested local-PC envelope, but not magic: if SSD bandwidth is scarce or the retained context budget must be much larger, the core latency-hiding argument weakens.

## Related Work

- _Tang et al. (ICML '24)_ — Quest popularizes query-aware block sparsity for long-context inference, while SolidAttention keeps that style of block selection but redesigns layout and prefetch behavior for SSDs.
- _Xiao et al. (NeurIPS '24)_ — InfLLM provides representative-vector block selection and long-context extrapolation in memory; SolidAttention adopts similar identifiers but turns SSD offloading into a first-class systems problem.
- _Sheng et al. (ICML '23)_ — FlexGen also overlaps offloaded KV accesses with compute, but its token-granularity accesses and concurrency-hiding strategy break down in low-concurrency local decoding.
- _Chen et al. (FAST '25)_ — IMPRESS uses multi-tier prefix KV storage for cloud inference with cross-request locality, whereas SolidAttention focuses on single-user decode latency and direct GPU-SSD transfer efficiency.

## My Notes

<!-- empty; left for the human reader -->

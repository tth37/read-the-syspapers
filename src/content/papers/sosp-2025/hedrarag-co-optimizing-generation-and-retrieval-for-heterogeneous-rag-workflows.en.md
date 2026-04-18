---
title: "HedraRAG: Co-Optimizing Generation and Retrieval for Heterogeneous RAG Workflows"
oneline: "HedraRAG turns heterogeneous RAG workflows into a graph, then splits, reorders, speculates, and partially GPU-caches work to keep retrieval and generation aligned."
authors:
  - "Zhengding Hu"
  - "Vibha Murthy"
  - "Zaifeng Pan"
  - "Wanlu Li"
  - "Xiaoyi Fang"
  - "Yufei Ding"
  - "Yuke Wang"
affiliations:
  - "Computer Science and Engineering, UCSD"
  - "Nano and Chemical Engineering, UCSD"
  - "RegAilator Inc"
  - "Computer Science, Rice University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764806"
tags:
  - llm-inference
  - scheduling
  - caching
  - gpu
category: llm-serving
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HedraRAG treats RAG serving as a graph scheduling problem rather than a fixed two-stage pipeline. It splits retrieval and generation into fine-grained sub-stages, reorders work using semantic locality, and caches only hot IVF clusters on the GPU. Across heterogeneous RAG workflows, the paper reports over `1.5x` and up to `5x` throughput improvement.

## Problem

Modern RAG requests are heterogeneous: multistep reasoning, HyDE-style pre-retrieval generation, RECOMP-style post-retrieval processing, and iterative retrieve-generate loops all create different stage counts and durations. Existing frameworks still serve them as compositions of an LLM engine plus a vector-search backend, which is flexible at the API level but poorly coordinated at runtime.

That causes three failures. GPU generation likes continuous token-level batching, while CPU retrieval likes larger fixed batches, so naive composition stalls the pipeline. Multi-round workflows contain semantic locality across stages, but current systems recompute each stage independently. And retrieval access is skewed, yet GPU memory is already dominated by model weights and KV cache, so the full vector index cannot be cached on-device.

## Key Insight

The paper's core claim is that heterogeneity should be exposed as graph structure. If requests are represented as nodes and dependencies rather than coarse stages, the runtime can optimize across three axes with one abstraction: overlap independent generation and retrieval across requests, reuse locality within a request, and accelerate hot retrieval regions across requests.

This works because the real bottleneck is hidden structure. Long retrievals can be split, later queries are often close to earlier ones in embedding space, and only a small fraction of IVF clusters dominate current demand. Once those facts are explicit, the scheduler can rewrite the execution plan instead of obeying original stage boundaries.

## Design

HedraRAG introduces `RAGraph`, whose nodes are Generation or Retrieval operations and whose edges encode dataflow and control flow. The runtime applies graph transformations such as node splitting, reordering, edge insertion, and dependency rewiring.

The first transformation is fine-grained sub-stage pipelining. Generation nodes are broken into groups of decoding steps. Retrieval nodes are broken into searches over one or more IVF clusters, with boundaries chosen by a time budget rather than a fixed cluster count. These smaller units let the scheduler align CPU retrieval with GPU decoding and avoid one long search blocking the whole stream.

The second transformation uses intra-request similarity. HedraRAG caches enlarged top-`k` results from prior retrievals, searches those likely-hit regions first, and reorders the next query's cluster set so ANN search can terminate early. It then speculatively overlaps dependent stages: generation can start from partial retrieval output, or retrieval can start from partially generated text, with rollback only if the speculation was wrong.

The third transformation is partial GPU indexing. The runtime tracks the hottest IVF clusters and keeps only those in a GPU cache; other clusters remain on the CPU. Each retrieval sub-stage is split between GPU-cached and CPU-resident clusters, and the results are merged after parallel search. A wavefront scheduler repeatedly collects runnable nodes across active requests, rewrites the graph, and dispatches work to separate vLLM and Faiss workers.

## Evaluation

Experiments run on a 64-core AMD EPYC 9534 plus NVIDIA H100 80 GB, using Llama 3.1-8B, a roughly `38M`-document Wikipedia corpus, `e5_large` embeddings, and `IVF4096` with `nprobe` from `128` to `512`. The workloads span One-shot, HyDE, RECOMP, Multistep, and IRG. Baselines are LangChain, FlashRAG, a stronger asynchronous vLLM+Faiss baseline, and prior speculative methods.

HedraRAG reduces request latency by `2.2x` to `18.2x` at the same arrival rate and achieves over `1.5x` and up to `5x` higher throughput, with larger gains on more complex workflows and more expensive retrieval. The ablations explain the result: fine-grained partitioning alone cuts vector-search latency by `1.09x` to `1.77x`, similarity-aware reordering plus speculation adds `1.06x` to `1.62x`, and partial GPU indexing adds `1.12x` to `1.49x`. Under mixed concurrent workflows, latency drops by up to `5.5x` and throughput rises by up to `3.3x`. That is good evidence that the claimed bottlenecks are real and that the system attacks the right ones.

## Novelty & Impact

Compared with LangChain or FlashRAG, HedraRAG is not just a modular wrapper around retrieval and generation backends; it is a coordinated runtime that treats heterogeneous RAG as graph scheduling. Compared with point solutions such as speculative or cache-based RAG accelerators, it offers a more general optimization surface. The paper should matter to RAG serving runtimes, hybrid CPU-GPU retrieval systems, and future agentic LLM systems that need to schedule irregular multi-stage workflows.

## Limitations

The implementation and evaluation are single-node. The system also relies on empirically tuned policies for retrieval time budgets, speculation thresholds, and GPU-cache sizing, so behavior may shift with workload drift. Benefits shrink when generation dominates end-to-end time or when retrieval skew is weak, and speculative execution still pays rollback costs on misses. Finally, the evaluation is centered on serving efficiency rather than a broad answer-quality study under every optimization setting.

## Related Work

- _Lewis et al. (NeurIPS '20)_ - Retrieval-Augmented Generation establishes the algorithmic pattern, whereas HedraRAG focuses on serving heterogeneous realizations of that pattern efficiently.
- _Yu et al. (OSDI '22)_ - Orca shows how continuous batching improves LLM serving, while HedraRAG must reconcile that generation model with retrieval stages that prefer different batching behavior.
- _Kwon et al. (SOSP '23)_ - vLLM/PagedAttention makes GPU generation efficient, but it does not coordinate generation with vector search or multi-round RAG structure.
- _Zhang et al. (NSDI '24)_ - Reordered Pipelining accelerates vector queries beyond GPU memory; HedraRAG embeds a related concern inside an end-to-end hybrid RAG runtime.

## My Notes

<!-- empty; left for the human reader -->

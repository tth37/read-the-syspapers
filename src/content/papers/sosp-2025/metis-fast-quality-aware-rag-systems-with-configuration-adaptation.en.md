---
title: "METIS: Fast Quality-Aware RAG Systems with Configuration Adaptation"
oneline: "METIS profiles each RAG query, prunes its configuration space, and then picks the most quality-preserving plan that fits current GPU memory."
authors:
  - "Siddhant Ray"
  - "Rui Pan"
  - "Zhuohan Gu"
  - "Kuntai Du"
  - "Shaoting Feng"
  - "Ganesh Ananthanarayanan"
  - "Ravi Netravali"
  - "Junchen Jiang"
affiliations:
  - "University of Chicago"
  - "Princeton University"
  - "University of Chicago / TensorMesh"
  - "Microsoft"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764855"
tags:
  - llm-inference
  - scheduling
  - datacenter
category: llm-serving
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

METIS argues that RAG serving should not use one static workflow for all queries. It profiles each query, prunes the candidate configuration space, and then runs the strongest remaining plan that fits current GPU memory. Across four RAG-QA datasets, this lowers latency by 1.64-2.54x without hurting answer quality.

## Problem

The paper starts from a mismatch between RAG tuning and RAG serving. Quality depends on how many chunks are retrieved, whether they are read jointly, and whether they are summarized first. Delay depends on those same knobs, because longer contexts and multi-stage synthesis consume more compute and GPU memory. Prior work usually optimizes only one side: serving systems improve batching for a fixed configuration, while RAG-tuning methods search for high-quality configurations without pricing in queueing and memory pressure.

This separation is expensive because queries are heterogeneous. A factoid query may need one chunk and no cross-chunk reasoning; a comparison or "why" question may need multiple pieces of evidence and a synthesis strategy that removes irrelevant text before the final answer. The paper shows that changing `synthesis_method`, `num_chunks`, or `intermediate_length` moves a query to a very different quality-delay point, and that the best point differs sharply across queries. Exhaustive online search is infeasible: even one `map_reduce` family with 30 chunk counts and 50 summary lengths already yields 1,500 configurations for one query.

## Key Insight

METIS's key idea is to split semantic pruning from resource-aware final choice. A small profiler LLM infers four dimensions from the query and a short dataset description: query complexity, whether joint reasoning is needed, how many distinct pieces of information are required, and how much intermediate summarization is useful. That profile is enough to prune the original combinatorial space to a much smaller region that is still likely to keep quality high.

After that, the scheduler no longer needs to reason about semantics in detail. Inside the reduced space, METIS assumes that the highest-memory configuration that fits current GPU memory is usually the best one to run, because it uses slightly more context or richer synthesis without triggering queueing. The contribution is therefore not just "use an LLM to pick knobs," but "use an LLM to define a safe region, then let systems best-fit scheduling choose within it."

## Design

METIS adapts three knobs: `num_chunks`, `synthesis_method` among `map_rerank`, `stuff`, and `map_reduce`, and `intermediate_length` for `map_reduce`. The profiler sees only the query and dataset metadata, not the full retrieved context, and outputs complexity (`high`/`low`), whether joint reasoning is required, the number of information pieces needed (1-10), and a summary-length range (30-200 tokens).

The rule-based mapper then turns that profile into a pruned configuration set. No joint reasoning means `map_rerank` only. Joint reasoning plus low complexity means `stuff`. Joint reasoning plus high complexity keeps both `stuff` and `map_reduce`. For chunk count, METIS uses `[n, 3n]`, where `n` is the estimated number of information pieces, so retrieval has slack to find enough evidence. For `map_reduce`, it keeps the profiler's summary-length range. The paper reports a 50-100x reduction in configuration space.

Scheduling is done jointly with configuration choice. For each candidate in the pruned space, METIS estimates GPU memory from input length, model parameters, and quantization, adds a 2% buffer, and checks what fits in the current vLLM batch. It then chooses the fitting configuration with the largest memory footprint. The reason is that `stuff` may be cheaper in raw compute than `map_reduce`, but if a long prompt cannot fit it waits in queue and becomes slower end to end; a `map_reduce` plan may start sooner because its mapper calls fit individually. If nothing in the pruned space fits, METIS falls back to a cheaper plan just outside the range: `map_rerank` for non-joint queries and `stuff` for joint-reasoning queries.

The system also adds two refinements. It uses the profiler's log-prob confidence with a 90% threshold; low-confidence queries fall back to the pruned configuration space of the recent ten queries. And every 30 queries it creates a feedback prompt using the answer from the most resource-demanding configuration to improve later profiler decisions. The implementation is about 2 KLOC of Python on top of vLLM and uses GPT-4o or Llama-3.1-70B as the profiler, Cohere embeddings, FAISS retrieval, LangChain synthesis chains, and `pynvml` for free-memory checks.

## Evaluation

The evaluation uses four datasets with different query shapes: SQuAD, MuSiQue, KG RAG FinSec, and QMSUM. The main serving model is AWQ-quantized Mistral-7B-v3; some sensitivity experiments use AWQ-quantized Llama-3.1-70B. Experiments run on a server with two NVIDIA A40 GPUs, 384 GB memory, and Xeon Gold 6130 CPUs, with 200 queries per dataset arriving under a Poisson process.

The headline result matches the paper's thesis. Compared with AdaptiveRAG* at equal quality, METIS lowers delay by 1.64-2.54x. Compared with fixed-configuration baselines on Parrot* and vLLM at similar delay, it improves F1 by 12-18%. Throughput is 1.8-4.5x higher at matched quality. The breakdown is also informative: using only the profiler output and a median configuration already cuts delay by 1.4-1.68x relative to the best fixed configuration; batching adds another 1.1-1.2x; full resource-aware adaptation adds a further 1.45-1.75x. Profiler overhead is small, at most 10% of end-to-end delay and typically 3-6%. Even under low load, METIS still reduces delay by 1.48-1.56x.

These experiments mostly support the central claim because they exercise exactly the memory-and-queueing bottleneck that METIS models. The main caveat is that Parrot* and AdaptiveRAG* are author re-implementations rather than original systems, and most experiments center on one 7B serving model and one hardware family.

## Novelty & Impact

The closest prior work splits into two camps, and METIS fills the gap between them. Adaptive-RAG-style systems estimate question complexity but mostly optimize quality and only a narrow knob set. Parrot- and vLLM-style systems optimize batching and memory management but assume the RAG plan is already fixed. METIS is novel because it turns "which RAG plan should this query run?" into a systems decision conditioned on both query semantics and instantaneous resource availability.

That makes the paper useful to people building RAG runtimes, LLM serving stacks, and future agentic RAG systems. The reusable idea is the architecture of semantic pruning followed by resource-aware best-fit execution.

## Limitations

The main weakness is that the profiler-to-configuration mapping is heuristic. The paper uses a hand-written rule table, a fixed 90% confidence threshold, and a fallback to the recent ten queries when the profiler looks unreliable. That is practical, but it gives no strong optimality or robustness guarantee, and the paper explicitly admits that highly under-specified prompts can defeat the profiler.

The evaluation scope is also narrower than the paper's ambition. METIS is tested on classic text RAG pipelines and four QA-style datasets, not on production agentic workflows, multimodal retrieval, or GraphRAG. The baseline comparisons rely partly on re-implementations, and the paper does not show a live production deployment. Finally, the method depends on an extra strong LLM profiler and dataset metadata; the paper argues that the cost is small, but it is still a real dependency.

## Related Work

- _Jeong et al. (NAACL '24)_ - Adaptive-RAG predicts question complexity to choose retrieval behavior, while METIS profiles more dimensions and couples them to GPU-aware scheduling.
- _Lin et al. (arXiv '24)_ - Parrot improves serving for LLM-based applications, but it still assumes a fixed application configuration instead of adapting RAG plans per query.
- _Kwon et al. (SOSP '23)_ - PagedAttention/vLLM provides the memory-management and batching substrate that METIS builds on, but it does not decide which RAG configuration each query should use.
- _Jiang et al. (arXiv '25)_ - RAGO systematically optimizes RAG serving performance, whereas METIS focuses specifically on the quality-delay frontier through profile-guided pruning and best-fit configuration choice.

## My Notes

<!-- empty; left for the human reader -->

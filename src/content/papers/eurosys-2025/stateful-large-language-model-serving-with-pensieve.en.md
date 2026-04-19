---
title: "Stateful Large Language Model Serving with Pensieve"
oneline: "Pensieve keeps per-conversation KV state in a GPU-CPU cache and adds multi-token attention over non-contiguous memory so chat history is not re-prefilled on every turn."
authors:
  - "Lingfan Yu"
  - "Jinkun Lin"
  - "Jinyang Li"
affiliations:
  - "New York University"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696086"
tags:
  - llm-inference
  - caching
  - gpu
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pensieve turns multi-turn chat serving from stateless prompt replay into stateful KV-cache reuse. It keeps conversation history in a two-tier GPU/CPU cache, recomputes only the dropped prefix when necessary, and extends PagedAttention into a multi-token kernel that can run prefill over non-contiguous cached context. On ShareGPT and UltraChat, the paper reports 1.14-1.70x throughput gains on 13B models and up to 3.0x on 70B models versus vLLM and TensorRT-LLM.

## Problem

Existing LLM serving engines are stateless across requests. In a multi-turn chat, every new user turn is sent together with the entire accumulated conversation history, so the system keeps redoing prefill work it has already done. The paper shows that once history grows, prefill quickly dominates generation: under a batch of 32 requests with 200 output steps, recomputing a few thousand history tokens can cost far more than decoding.

The obvious fix is to cache old KV states, but that runs into three systems problems. First, GPU memory is too small to keep many live conversations: for the paper's GPT-3-like 13B configuration, one token's KV state occupies about 0.78 MB across all layers. Second, conversation state cannot be swapped only at whole-request granularity because that wastes space and makes restore latency too large. Third, once some older tokens are swapped out or dropped, the remaining context becomes logically contiguous but physically fragmented, while standard prefill kernels assume the context sits in one contiguous GPU region.

## Key Insight

The paper's central claim is that conversation state should be managed as a cache, not as temporary per-request workspace. If the system evicts old state at token-chunk granularity, prefers older conversations, and preferentially drops the leading edge of a history, then most future turns can reuse exact attention state instead of replaying the whole transcript.

That leading-edge choice is the crucial observation. Because causal attention makes later tokens attend to more context, earlier tokens are cheaper to recompute than later ones. Pensieve therefore combines recency with estimated recomputation cost, then rebuilds only the missing prefix while reusing the middle from CPU and the suffix from GPU. The serving semantics stay exact; only the placement of KV state changes.

## Design

Pensieve has one scheduler and one worker per GPU. The scheduler forms iteration-level batches, but unlike ORCA or vLLM it does not separate prefill and decode into different execution paths. A running request contributes one generated token to the batch, while a new request contributes its prompt tokens. Unified batching matters because it avoids launching small prefill-only kernels and lets old and new requests share one execution step.

KV state is stored in a two-tier cache: GPU first, CPU second. Pensieve groups KV entries into 32-token chunks and assigns each chunk a retention value proportional to recomputation cost and inversely proportional to how recently the conversation was active. Chunks with low retention are evicted first. When GPU free space falls below a threshold such as 25%, the system starts swapping selected chunks to CPU ahead of time so eviction latency can overlap with ongoing GPU work. It also reserves 10% of GPU slots for active decode requests to reduce forced suspension.

When CPU cache is also full, Pensieve drops chunks entirely, again from the leading edge when possible. On the next turn, dropped raw tokens are fetched from persistent conversation history and prepended to the new prompt so they can be recomputed. CPU-resident middle chunks are swapped back layer by layer and overlapped with execution using GPU events. The result is a four-part logical context: recomputed prefix, swapped-in middle, GPU-resident suffix, and new prompt.

The hardest part is attention over that fragmented context. vLLM's PagedAttention already handles non-contiguous KV cache, but only for a single query token in decode. Pensieve builds a multi-token attention kernel for prefill on top of PyTorch's fused attention path and NVIDIA Cutlass. The kernel supports ragged query lengths, non-contiguous KV locations, and fused causal masking. When dropped-prefix recomputation creates two disjoint query ranges, Pensieve treats them as two sub-requests that share one underlying context, avoiding extra copies.

## Evaluation

The evaluation runs on Azure NC A100 v4 machines with A100-80GB GPUs, 24-core AMD EPYC CPUs, and 220 GB of CPU memory per GPU, while fixing 40 GB per GPU for KV cache across systems. The workloads are two conversational datasets: ShareGPT, with 48,159 conversations and 5.56 mean turns, and UltraChat, with 1,468,352 conversations and 3.86 mean turns. Models span OPT-13B/66B and Llama 2-13B/70B; the paper also modifies Llama 2-13B to use grouped-query attention with 10 KV heads so cache density matches the design point it wants to study.

The headline results support the paper's thesis. On one GPU, Pensieve delivers 1.36x the throughput of vLLM and 1.14x of TensorRT-LLM for OPT-13B at 120 ms/token on ShareGPT, and 1.70x and 1.58x respectively for Llama 2-13B at 180 ms/token. On four GPUs with ShareGPT, the gains rise to 2.04x over vLLM and 1.64x over TensorRT-LLM for OPT-66B at 200 ms/token, and 3.0x and 2.47x for Llama 2-70B at 400 ms/token. The behavior also matches the mechanism: gains are larger on ShareGPT than UltraChat because conversations run longer, and larger on GQA-equipped Llama models because KV state is cheaper to retain.

The microbenchmarks are also important. Pensieve's multi-token kernel matches the ideal contiguous-memory baseline, while copy-then-attend and repeated single-token PagedAttention both pay clear overheads. The custom eviction policy beats vanilla LRU once load rises, improving CPU-cache hit rate by up to 4.4 percentage points and reducing recomputed KV tokens by up to 14.6%. The main fairness gap is that the paper compares only against stateless baselines, not against concurrent stateful caching systems.

## Novelty & Impact

Pensieve's novelty is not a new language-model algorithm; it is a serving architecture that makes exact multi-turn state first-class. The paper combines three ideas that are usually studied separately: cache eviction guided by recomputation cost, asynchronous GPU/CPU KV migration, and a prefill-capable attention kernel for non-contiguous memory. That combination is what turns "cache the chat history" from an obvious slogan into a working system.

This paper should matter to authors building LLM serving engines, KV-cache offload systems, and chat-oriented inference stacks. It is especially relevant for work that wants to reuse attention state without changing model outputs, and for systems papers that need to reason jointly about batching, memory layout, and attention-kernel structure.

## Limitations

Pensieve only helps when conversations have temporal locality. As user think time grows, cache hit rates fall; the paper shows the benefit shrinking by 600 seconds even though Pensieve still stays ahead of vLLM. The design also does not attempt cross-user sharing except for manually designated reusable system prompts, so it leaves the broader prefix-sharing problem to systems such as PromptCache or SGLang.

There are evaluation limits too. The baselines are strong but stateless, which means the paper does not show whether Pensieve still wins against later stateful systems such as CachedAttention. One model point, Llama 2-13B, is modified to use GQA, which improves cache density and likely helps Pensieve more than an unmodified 13B model would. The experiments are also confined to A100-class hardware, two datasets, and contexts capped at 16,384 tokens.

## Related Work

- _Kwon et al. (SOSP '23)_ - vLLM introduces paged KV memory inside a single request, while Pensieve keeps that state across requests and extends the attention path to multi-token prefill.
- _Yu et al. (OSDI '22)_ - ORCA establishes iteration-level batching for generative serving, but it still treats requests as stateless and does not unify multi-turn cache recovery with batching.
- _Gao et al. (USENIX ATC '24)_ - CachedAttention also targets multi-turn conversations, whereas Pensieve evicts at token-chunk granularity from the leading edge and recomputes truncated prefixes on demand.
- _Gim et al. (PMLSys '24)_ - PromptCache reuses schema-defined prompt modules across requests, while Pensieve focuses on dynamic per-conversation state without requiring an application-supplied prompt schema.

## My Notes

<!-- empty; left for the human reader -->

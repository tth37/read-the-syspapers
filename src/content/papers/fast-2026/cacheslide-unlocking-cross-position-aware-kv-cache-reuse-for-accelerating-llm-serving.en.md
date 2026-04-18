---
title: "CacheSlide: Unlocking Cross Position-Aware KV Cache Reuse for Accelerating LLM Serving"
oneline: "CacheSlide reuses KV caches across shifted fixed agent-prompt segments with CCPE, selective correction, and spill-aware paging, cutting latency by up to 4.3x."
authors:
  - "Yang Liu"
  - "Yunfei Gu"
  - "Liqiang Zhang"
  - "Chentao Wu"
  - "Guangtao Xue"
  - "Jie Li"
  - "Minyi Guo"
  - "Junhao Hu"
  - "Jie Meng"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Jinan Inspur Data Technology Co., Ltd"
  - "Peking University"
  - "Huawei Cloud"
conference: fast-2026
category: ai-era-storage
code_url: "https://github.com/SJTU-Storage-Lab/CacheSlide"
tags:
  - llm-inference
  - caching
  - memory
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CacheSlide targets agent prompts whose reusable segments move in absolute position but keep the same relative order. It combines a low-sensitivity positional encoding (`CCPE`), top-k token correction (`Weighted Correction Attention`), and a spill-aware KV-cache manager (`SLIDE`) to reuse much more of prefill work than prefix caching or position-independent reuse. Across three models and three agent workloads, the paper reports `3.11-4.3x` lower latency and `3.5-5.8x` higher throughput than prior cache-reuse baselines.

## Problem

The paper focuses on agent-style LLM serving, where prompts are not a simple stable prefix followed by new user text. Instead, they mix long-lived segments such as system prompts, memory, and prior tool traces with dynamic segments such as the latest reasoning step, memory update, or function arguments. Most of the content is reusable, but the reusable pieces are often separated by small updated spans whose lengths change from turn to turn.

That prompt shape breaks both mainstream cache-reuse strategies. Position-dependent caching, such as prefix caching, only works when reusable text stays at a fixed absolute position. In agent prompts that means it can usually reuse the system prompt and little else. Position-independent caching removes the absolute-position constraint, but it resets reused segments to new positions and then pays to repair the resulting drift by recomputing some tokens. The paper argues that this causes two problems: accuracy loss from positional mismatch and systems overhead from loading old KV pages and writing corrected KV pages layer by layer on the critical path.

The authors also test an obvious alternative, window padding, which fixes the length of dynamic spans so fixed segments do not move. That also fails: if the padded window is too small, the agent loses information; if it is too large, fixed segments still drift enough to hurt similarity. For agent workloads, the real need is neither prefix-only reuse nor fully arbitrary reuse, but reuse across segments whose relative order stays stable while their absolute positions slide.

## Key Insight

The paper's main claim is that agent prompts expose a narrower and more tractable reuse regime than prior work assumed. The reusable segments do not move arbitrarily; they usually preserve their relative order and are displaced only by updated spans between them. CacheSlide names this regime `Relative-Position-Dependent Caching` (`RPDC`).

That observation matters because it changes what must be repaired. If positional encoding is chosen and assigned so reused chunks stay close to the positions they would have had in a fresh prefill, then attention inside a fixed chunk and across fixed chunks can be reused almost losslessly. The only attention that still needs explicit recovery is the cross-attention between fixed chunks and the newly updated chunks. In other words, the problem is not "recompute enough tokens to survive arbitrary relocation"; it is "keep fixed chunks aligned enough that only a small corrective computation remains."

## Design

CacheSlide has three components. `CCPE` (`Chunked Contextual Position Encoding`) is the encoding-side mechanism. The system assumes prompts from the same agent task follow a template that can be divided into ordered reuse chunks and recompute chunks. It performs task-specific pretraining with `CoPE`, builds a histogram of the most frequent positional patterns, and assigns reused chunks those learned ranges when it later loads cached KV states. The goal is not perfect positional identity, but a small enough positional gap that cached and recomputed KVs stay highly similar.

`Weighted Correction Attention` then repairs the part CCPE cannot recover by itself. In the first layer, CacheSlide recomputes the full prompt, measures each token's deviation between reused and recomputed KV states, and picks the top-k tokens with the largest drift. In later layers it recomputes only those selected tokens, fuses recomputed and cached KVs with learned weights, and every four layers checks `CKSim` to see whether a token has converged enough to leave the active correction set. The paper's best operating point is around top-k `0.26` and `CKSim` threshold `0.12`, which reflects its broader thesis: repair a small but carefully chosen subset rather than the whole reused segment.

`SLIDE` is the systems contribution that keeps that correction from turning into a storage bottleneck. Implemented in `vLLM 0.8.5`, it preallocates extra KV pages for selected tokens, relocates corrected tokens so loads and writes no longer serialize within a layer, and then reuses those mappings during decode for in-place overwrites. Under memory pressure, it marks pages containing selected tokens as dirty, spills clean pages first, and orders dirty-page eviction by selected-token count to coalesce writes and reduce SSD write amplification.

## Evaluation

The evaluation uses three models (`Mistral-7B`, `MPT-30B`, and `Llama-3 70B`), three agent workloads (`HotPotQA` with Reflexion, `Multi-Session Chat` with MemGPT, and `SWE-Agent-Bench` with SWE-Agent), and a server with A100 GPUs, `500 GB` DRAM, and `2 TB` NVMe SSDs. CacheSlide is compared against recomputation, `ContextCache`, `PromptCache`, `CacheBlend`, and `EPIC`. The core result is strong: across models and workloads, the paper reports `3.11-4.3x` lower latency and `3.5-5.8x` higher throughput than state-of-the-art PIC/PDC baselines, while staying on the best accuracy-TTFT frontier. Relative to `ContextCache`, it cuts TTFT by `2.4-3.3x` with negligible accuracy loss; relative to `CacheBlend`, it reduces TTFT by `1.21-2.11x` while also improving accuracy.

The system-level ablations support the mechanism rather than just the headline result. `SLIDE` reduces layer-wise parallel latency by `26.7-51.5%`, lowers write stalls by `66.9-73.5%`, and reduces SSD write amplification by `3.11-3.62x`. Under parallel inference and beam search, the improvement over the best baseline grows as pressure increases, reaching about `2.3x` at batch size `6` and `2.1x` at beam width `6`. This is credible evidence that the paper is not just a prompt-level caching idea; it is also a storage-management paper about how corrected KV states flow through a paged runtime.

I do think one fairness caveat matters. CacheSlide enables `CoPE` through adapter-based continued pretraining, while the baselines keep their native positional encodings. That makes the comparison partly about the RPDC mechanism and partly about a modified model stack. The paper is explicit about this setup, but it still means the gains are not purely from cache management.

## Novelty & Impact

Relative to _Gim et al. (MLSys '24)_, CacheSlide does not try to support reusable segments by materializing many absolute-position variants; it defines a narrower regime where relative order is stable and exploits that structure directly. Relative to _Yao et al. (EuroSys '25)_ and _Hu et al. (ICML '25)_, it is less general than full PIC, but that restriction is the source of its advantage: less positional drift to repair, fewer corrected tokens, and a cleaner systems path for load/write decoupling. Relative to prefix-only serving work such as _Yu et al. (EuroSys '25)_, it makes agent prompts a first-class systems target rather than treating them as a poor fit for reuse.

That combination makes the paper more than a small optimization. It contributes a new problem framing (`RPDC`), a concrete reuse mechanism (`CCPE` plus `Weighted Correction Attention`), and a runtime design (`SLIDE`) that turns the paper's storage claims into measurable latency and SSD-write benefits. Researchers building agent-serving stacks, prompt-caching layers, or storage-aware LLM runtimes are the obvious audience.

## Limitations

CacheSlide's strongest assumption is structural regularity. `CCPE` depends on prompts being partitionable into reuse and recompute chunks by task template, and it learns the dominant encoding pattern from single-task pretraining. That is a good fit for repeated runs of one agent workflow, but the paper says much less about heterogeneous, rapidly changing prompts where chunk boundaries or update behavior are unstable.

The correction logic is also tuned. The paper identifies top-k `0.26` and `CKSim` `0.12` as the best region, which suggests the method has nontrivial workload sensitivity. The main comparisons are also run at batch size `1`, so the central accuracy-TTFT claim is strongest for low-concurrency serving; the larger-batch results mainly validate `SLIDE` under stress rather than end-to-end quality. Finally, because CacheSlide uses `CoPE` adapters and custom task-specific preprocessing, the deployment cost is higher than a pure runtime-only cache layer, and the paper does not fully quantify how much of the benefit would remain under a strictly frozen base model.

## Related Work

- _Gim et al. (MLSys '24)_ — PromptCache supports modular attention reuse, but it remains position-dependent and pays storage cost for position-specific variants that CacheSlide avoids.
- _Yao et al. (EuroSys '25)_ — CacheBlend is a representative PIC design that repairs positional drift after arbitrary relocation; CacheSlide instead reduces the drift up front by targeting the narrower RPDC regime.
- _Hu et al. (ICML '25)_ — EPIC formalizes position-independent context caching, whereas CacheSlide argues agent prompts usually admit stronger relative-order structure that can be exploited more aggressively.
- _Yu et al. (EuroSys '25)_ — Pensieve is stateful prefix caching for repeated prompts, while CacheSlide handles multi-segment agent prompts whose reusable content is not confined to the prefix.

## My Notes

<!-- empty; left for the human reader -->

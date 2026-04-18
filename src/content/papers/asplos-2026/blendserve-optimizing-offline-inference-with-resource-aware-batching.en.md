---
title: "BlendServe: Optimizing Offline Inference with Resource-Aware Batching"
oneline: "Blends compute-heavy and memory-heavy offline LLM requests with a resource-aware prefix tree and dual scanning so batching keeps overlap without giving up prefix reuse."
authors:
  - "Yilong Zhao"
  - "Shuo Yang"
  - "Kan Zhu"
  - "Lianmin Zheng"
  - "Baris Kasikci"
  - "Yifan Qiao"
  - "Yang Zhou"
  - "Jiarong Xing"
  - "Ion Stoica"
affiliations:
  - "University of California, Berkeley, Berkeley, CA, USA"
  - "University of Washington, Seattle, WA, USA"
  - "University of California, Davis, Sacramento, CA, USA"
  - "Rice University, Houston, TX, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790133"
tags:
  - llm-inference
  - scheduling
  - caching
  - gpu
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

BlendServe treats offline LLM serving as a request-ordering problem. It uses a resource-aware prefix tree and a dual scanner to mix compute-heavy and memory-heavy work while preserving most prefix sharing, reaching up to `1.44x` higher throughput than vLLM/SGLang and about `86.55%-90.8%` of the paper's practical optimum.

## Problem

Offline batch APIs allow long response windows, so the main metric is throughput, not latency. Prior systems exploit the fact that prefills are compute-heavy and decodes are memory-bandwidth-heavy, but they mostly optimize overlap inside an already formed batch. Once workloads mix summarization, chat, benchmarks, and long-output generation, that is not enough: one request cluster can saturate compute while another saturates bandwidth. Reordering helps, but plain DFS order maximizes prefix reuse rather than resource balance; the paper reports only `71.7%` of optimal throughput from DFS alone in one Llama-3-8B setting.

## Key Insight

The key claim is that request-level compute density is a good enough scheduling signal for continuous batching. Long-prompt, short-output requests are compute-intensive; long-output requests are memory-intensive because decode repeatedly reloads KV-cache state. If the scheduler keeps each batch near the workload's target density, compute and memory time overlap better. BlendServe therefore treats prefix sharing as a constrained resource rather than an absolute rule: it accepts a small loss in reuse when that produces better request mixing.

## Design

BlendServe starts with a simple model: for a request with prompt length `p` and output length `d`, it estimates GEMM-dominated compute time and decode-time KV-cache loading time, then defines compute density as `Comp(r) / Mem(r)`. The paper reports at most `6%` relative error against real GEMM and attention timings.

The core data structure is a resource-aware prefix tree. As in RadixAttention, internal nodes represent shared prompt segments and leaves represent requests, but each node stores a density score that already accounts for prefix sharing via `(1 - s) * Tcomp / Tmem`. Because output length is unknown beforehand, BlendServe runs a short warmup: it fully executes a small sample, uses subtree averages for unsampled requests, and falls back to sibling averages when needed. Sampling only `1%` of requests performs similarly to sampling all of them.

The tree is then sorted layer by layer so compute-heavy subtrees drift left and memory-heavy subtrees drift right. If local outliers remain, BlendServe conditionally splits and reinserts nodes when the recomputation cost is below a threshold `t`; in practice it preserves about `99%` of prefix sharing and only `0.1%-1%` of leaves usually need splitting.

Runtime batching is done by the dual scanner, which walks leaves from both ends of the sorted tree. It solves `ML + MR = M` and `ML * rho(RL) + MR * rho(RR) = M * rho(root)` to decide how much memory each side gets, then fills those budgets with compute-heavy and memory-heavy requests. The goal is to make the mixed batch approximate the root density of the workload. In the paper's example, an `80GB` A100 reserves `20GB` for weights and buffers, then splits the remaining `60GB` into `19.3GB` and `40.7GB` to combine densities `3.73` and `0.096` into `1.27`. This preprocessing is a one-time warmup that stays within the first `1%` of total execution time. The same abstraction also supports data-parallel subtree partitioning and works with tensor parallelism.

## Evaluation

The prototype combines an SGLang-derived prefix tree with a NanoFlow-based scheduler and C++ backend. The main workloads are synthesized from BurstGPT, MMLU, OpenVid, WildChat, ShareGPT, and Azure-Trace; each representative run contains at least `400,000` requests and takes about `5` A100 GPU hours.

On Llama-3-8B, BlendServe beats NanoFlow-DFS by `19.34%-22.65%`, averaging `20.84%`, and reaches up to `1.44x` throughput over vLLM-DFS. On Llama-3-70B with `8x` A100, it improves over NanoFlow-DFS by `18.6%` on average and reaches `90.8%` of the practical optimum. The mechanism-level checks line up with that story: BlendServe preserves over `97%` of optimal prefix sharing, NanoFlow-Balance falls below `30%`, and the resource-usage plots show much steadier compute and memory time than NanoFlow-DFS.

The broader regime study shows the win is not just a narrow point result. Across `65` synthesized workloads spanning compute density `0.80-1.40` and prefix sharing `0.05-0.45`, BlendServe beats NanoFlow-DFS by `14%-34%`, averaging `22.53%`, with the best region around density `1.30`. At `DP=4`, throughput reaches `3.78x-3.88x` over `DP=1`, and on four additional models the simulated results still show `15.2%` average improvement and `89.9%` of the practical optimum. The main caveat is that the evidence is mostly synthetic rather than production-trace based.

## Novelty & Impact

Relative to _NanoFlow (OSDI '25)_, BlendServe's novelty is not lower-level overlap but deciding which requests should coexist in a batch. Relative to DistServe, it chooses colocation plus reordering rather than physical phase separation. Relative to RadixAttention-style tries, it turns the prefix tree into a scheduling object instead of just a cache index. That gives offline inference systems a real new policy surface.

## Limitations

BlendServe is clearly an offline design: it assumes a visible request pool and a warmup phase for output-length sampling, so it is not meant for true online serving. Its estimates also work best when prompt similarity implies output-length similarity; the appendix shows weaker gains on higher-variance traces such as ShareGPT and WildChat. The evaluation relies on synthesized workloads because public offline traces do not exist, and the headline numbers exclude CPU-side costs such as tokenization and scheduling. Finally, the system is still heuristic: it reaches a practical upper bound, not the true optimum, with a residual gap of roughly `9%-13%`.

## Related Work

- _Yu et al. (OSDI '22)_ — Orca establishes continuous batching, which BlendServe assumes and then augments with offline request reordering.
- _Strati et al. (EuroSys '24)_ — Orion overlaps operators at fine granularity, but BlendServe changes batch composition itself.
- _Zhu et al. (OSDI '25)_ — NanoFlow is BlendServe's closest substrate; BlendServe keeps operator-level overlap but replaces passive request order with resource-aware batching.

## My Notes

<!-- empty; left for the human reader -->

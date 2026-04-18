---
title: "FastTTS: Accelerating Test-Time Scaling for Edge LLM Reasoning"
oneline: "Makes verifier-guided test-time scaling practical on a 24 GB edge GPU with speculative beam extension, prefix-aware scheduling, and asymmetric KV-cache allocation."
authors:
  - "Hao Mark Chen"
  - "Zhiwen Mo"
  - "Guanxi Lu"
  - "Shuang Liang"
  - "Lingxiao Ma"
  - "Wayne Luk"
  - "Hongxiang Fan"
affiliations:
  - "Imperial College London, London, UK"
  - "Microsoft Research, Beijing, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790161"
tags:
  - llm-inference
  - gpu
  - scheduling
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

FastTTS treats verifier-guided test-time scaling as a serving problem on one edge GPU. It hides beam stragglers with speculative beam extension, schedules beams to preserve dynamic prefix sharing, and allocates KV cache asymmetrically between the generator and verifier. On a single RTX 4090, that raises goodput by `2.2x` on average and cuts completion latency by `38%-68%` relative to a vLLM baseline.

## Problem

Edge hardware usually fits only small reasoning models, often `<= 7B` parameters on an `8-24 GB` consumer GPU, so there is a large quality gap versus cloud reasoning models. TTS tries to close that gap by spending more inference-time compute instead of increasing parameter count, but the paper shows that a naive vLLM implementation can take about `200 s` to match cloud-model accuracy.

The reason is that verifier-guided TTS is not ordinary decoding. A generator expands several reasoning paths, a verifier scores intermediate steps, and the best paths branch again. That loop creates three bottlenecks: irregular beam lengths produce stragglers and idle GPU slots, shared prefixes appear only at run time so naive scheduling loses KV-cache locality, and collocating generator plus verifier on one consumer GPU leaves too little memory for healthy batch sizes. What is missing is a runtime for verifier-guided tree search under edge memory limits.

## Key Insight

The central observation is that most useful TTS methods share the same generation/verification loop, and that loop is predictable in the ways a runtime needs. Previous verifier scores are good enough to prioritize speculative work, prefix overlap between beams is exploitable if scheduling preserves locality, and the two models have sharply different sensitivity to KV-cache size. In the paper's profiling, the verifier reaches about `80%` of peak throughput with less than `1 GB` of KV cache, while the generator needs roughly `5-10x` more memory to reach the same relative throughput. That suggests a simple recipe: speculate past stragglers, schedule for prefix reuse, and bias memory toward the side that is currently throughput-sensitive.

## Design

FastTTS is implemented as about `6,500` lines of Python on top of vLLM `0.9.2`, with generator and verifier in separate worker processes. Its first mechanism is Speculative Beam Extension. During one reasoning step, the system keeps generating normal tokens for unfinished beams; when some beams finish early, it fills the open slots with speculative continuations for promising completed beams, chosen using the previous verifier score as a survival proxy. After the real verifier call, FastTTS verifies only the non-speculative prefix and truncates speculative duplicates so the search remains equivalent to the baseline. The same idea enables LookAhead Verification, where a current step and a speculative next step are verified together to reuse verifier KV state.

This runs inside a two-phase scheduler. Continuous Beam Batching keeps all active beams from the current request in the batch; if the waiting queue is empty, the scheduler enters a speculative phase; if a new request arrives or memory pressure rises, speculative work is dropped immediately.

The other two mechanisms attack memory waste directly. Dynamic Prefix-Aware Scheduling orders beams to reduce KV-cache eviction between adjacent batches and uses a greedy heuristic that groups children of the same parent while preserving parent order. Asymmetric Multi-Model Memory Allocation uses a roofline-guided latency model plus a cheap linear search to decide how much KV cache the verifier and generator should get, with an offloading fallback when memory is extremely tight.

## Evaluation

The evaluation is aligned with the target setting: a single RTX 4090 with `24 GB` VRAM, three generator/verifier pairings (`1.5B+7B`, `7B+1.5B`, and a deliberately constrained `1.5B+1.5B`), and AIME 2024 plus AMC 2023 at `batch size = 1`. The paper also includes extra runs on HumanEval and on smaller GPUs such as the RTX 3070 Ti and 4070 Ti.

The headline numbers support the claim well. Across several search algorithms, FastTTS improves precise goodput by `1.2x-3.9x` over the baseline. On the beam-search configuration that the paper studies most deeply, it improves goodput by `2.2x` on average and up to `5.4x` across beam counts `8-512`, while reducing completion latency by `38%-68%`. Verifier latency falls by `75%-85%`, which fits the LookAhead Verification story, and generator latency falls by `36%-66%`, which fits the speculation plus memory-management story.

The accuracy story is also careful. Top-1 accuracy is essentially preserved and can improve slightly on AIME; Pass@N matches the baseline at large `N` and is a bit better at small `N`, which the authors attribute to scheduler side effects rather than a better search algorithm. The extra checks are directionally consistent: FastTTS gains `1.4x-1.6x` on smaller GPUs and `1.3x-1.8x` on HumanEval, while ablations show that speculation usually contributes the largest gain and prefix-aware scheduling matters most under tight memory.

## Novelty & Impact

Relative to _Kwon et al. (SOSP '23)_, FastTTS is not another general serving substrate; it is a TTS-specific runtime layer on top of that substrate. Relative to _Agrawal et al. (OSDI '24)_, it tackles the reasoning tree inside one request rather than a request stream. Relative to _Fu et al. (arXiv '24)_, it treats beam search itself as a schedulable workload. That makes the paper useful both to edge-agent practitioners and to researchers who care about reasoning runtimes rather than only reasoning algorithms.

## Limitations

The paper's scope is narrower than its motivation. FastTTS is built around discriminative PRMs and explicitly leaves generative PRMs and MCTS-style search out of scope. The strongest results are also for math and code reasoning with `batch size = 1`, so the paper says less about multi-user serving and mixed traffic. Deployment is not free either: the system depends on profiling and lightweight performance modeling, the prefix-aware scheduler is greedy rather than globally optimal, and some gains fade once memory is plentiful. FastTTS is therefore most convincing in the exact resource-constrained edge regime it targets.

## Related Work

- _Kwon et al. (SOSP '23)_ — PagedAttention makes LLM serving practical by fixing KV-cache memory management, while FastTTS adds beam-level scheduling and verifier-aware execution for tree-structured reasoning.
- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve improves the throughput-latency tradeoff for standard LLM serving with chunked prefills, whereas FastTTS targets irregular verifier-guided search inside a single reasoning request.
- _Fu et al. (arXiv '24)_ — Certaindex addresses LLM reasoning efficiency at the query level, but FastTTS focuses on beam-level stragglers, dynamic prefix reuse, and generator/verifier co-location.
- _Sheng et al. (ICML '23)_ — FlexGen expands effective memory with CPU and SSD offloading, while FastTTS instead optimizes how a single edge GPU spends its limited KV-cache budget across two models.

## My Notes

<!-- empty; left for the human reader -->

---
title: "XY-Serve: End-to-End Versatile Production Serving for Dynamic LLM Workloads"
oneline: "Turns mixed prefill, decode, and verify work into unified tiles and meta-primitives so dynamic LLM serving stays efficient on tile-based accelerators."
authors:
  - "Mingcong Song"
  - "Xinru Tang"
  - "Fengfan Hou"
  - "Jing Li"
  - "Wei Wei"
  - "Yipeng Ma"
  - "Runqiu Xiao"
  - "Hongjie Si"
  - "Dingcheng Jiang"
  - "Shouyi Yin"
  - "Yang Hu"
  - "Guoping Long"
affiliations:
  - "Huawei Technologies Co., Ltd., Beijing, China"
  - "Tsinghua University, BNRist, Beijing, China"
  - "Shanghai AI Laboratory, Shanghai, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3760250.3762228"
tags:
  - llm-inference
  - hardware
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

XY-Serve treats production LLM serving as a workload-normalization problem. It converts mixed prefill, decode, and verify work into unified token chunks, tile-level task tables, and two hardware-facing substrates: Meta-Attention for attention variants and SmoothGEMM for dynamic-shape linear layers. That lets the system keep fast accelerator kernels even when prefix reuse, chunked prefills, and speculative decoding make the runtime highly irregular.

## Problem

The paper starts from a real serving trend: operators increasingly combine automatic prefix caching, chunked prefills, speculative decoding, and sometimes disaggregated prefill/decode roles in the same stack. Prompt lengths then change after prefix matches, speculative decoding adds a verify stage with dynamic acceptance lengths and irregular masks, and chunked prefills mix long prefills with latency-sensitive decodes.

That variability is especially painful on tile-based accelerators such as Ascend NPUs, whose kernels want fixed tile sizes, regular memory access, and balanced work assignment. Dynamic GEMM shapes reduce utilization, irregular attention layouts break existing fast paths, and writing one specialized kernel per prefill/decode/verify combination is not scalable. The paper also argues that a batch-by-batch fallback is too expensive because split, rearrange, and merge overhead can exceed 50% in mixed-stage execution.

## Key Insight

The key claim is that most of the apparent diversity in modern LLM serving can be normalized before execution. Instead of treating prefix reuse, speculative decoding, and chunked prefill as separate kernel problems, XY-Serve reduces them to a small set of hardware-friendly meta-primitives.

That works because the runtime moves the complexity upward. Scheduling happens at token granularity, and each scheduled chunk is summarized by compact tables that capture stage boundaries, sequence lengths, and tile assignments. After that, Meta-Attention sees tiled GEMM-Softmax-GEMM work plus explicit K/V-cache and mask metadata, while SmoothGEMM sees a restricted family of tile shapes plus virtual padding. The central proposition is that abstraction, not yet another special-case kernel, is the right way to recover efficiency.

## Design

The control path starts with token-wise scheduling. After automatic prefix caching removes matched prompt tokens, XY-Serve forms fixed-budget chunks that may contain prefill, verify, and decode work together. Prefill is favored for first-token latency, but reserved slots protect decode and speculative work so long prefills do not starve active streams. Each chunk is summarized by a `Token-Table` and a `Task-Table`.

For attention, the runtime records stage offsets, token counts, historical `kvLen`, and `tileSize`, decomposes each stage into logical tiles, sorts tiles by estimated load (`tileSize x kvLen`), and assigns them to cores with a symmetric round-robin policy. For linear layers, all tokens in the chunk are concatenated and mapped into result-matrix tiles for `QKV`, `OProj`, `GateUp`, and `Down`; because the relevant shapes are limited, task orders can be tuned offline and replayed online.

Meta-Attention keeps block-wise K/V-cache management for throughput, but restores token-wise reuse with copy-on-write when a partially matched block diverges. For speculative decoding, it only treats the `specLen x specLen` region as special rather than materializing a full irregular mask, then chooses two-stage, three-stage, or four-stage pipelines based on the workload. SmoothGEMM does the analogous thing for linear layers: optimize a small fixed set of tile shapes, then absorb irregularity with virtual padding in on-chip buffers and selective HBM reads/writes.

## Evaluation

The kernel evaluation is strong and aligned with the paper's thesis. Relative to Ascend baselines `PFA` and `IFA`, Meta-Attention reports `11%` and `26%` average gains on mixed prefill/decode/verify batches for coding and conversation traces, `22.4%` average improvement with arbitrary prefix reuse, up to `22.2%` gain on long-sequence chunked prefills, `28.6%` average gain for verify workloads, and `12.9%` average gain for decode across different context lengths and batch sizes. SmoothGEMM beats torch-npu linear by `14.6%` on average.

The end-to-end numbers are the real selling point. Against Ascend vLLM on the vLLM nightly benchmarks, XY-Serve improves achieved QPS by up to `79%` before enabling prefill-chunked batching and P/D/V fusion, while lowering average `TTFT` by `64%` and `TBT` by `57%`; with those scheduling features enabled, the throughput gain rises to `89%` and average `TBT` drops by `69%`. On an in-house 66B workload with average input length `2169`, the full stack reaches `95%` improvement over the vLLM-APC baseline. I found that evidence convincing for the central claim, though the results remain mostly Ascend-centric and the GPU comparison is narrower, showing rough end-to-end parity against an `A800` with up to `17%` better decode-stage MBU.

## Novelty & Impact

Relative to _Kwon et al. (SOSP '23)_, XY-Serve is not mainly a better KV-cache allocator; it uses cache structure inside a broader execution abstraction that spans prefix reuse, speculative decoding, and chunked prefill. Relative to _Agrawal et al. (OSDI '24)_, its novelty is the claim that mixed prefill/decode/verify execution can be reduced to unified meta-primitives that still map well to hardware. That makes the paper feel more like a serving substrate for dynamic LLM inference than a one-off kernel trick.

## Limitations

XY-Serve buys regularity with a lot of machinery: token-wise scheduling, task decomposition, task reordering, copy-on-write K/V management, multiple attention pipelines, and offline shape tuning. The paper shows that this complexity pays off, but it says less about the engineering cost of maintaining such a stack over time.

The scope is also narrower than the headline might imply. The strongest results are for one-model serving on Ascend NPUs, while the GPU section mainly demonstrates portability. The in-house workload is only described at a high level, and the paper does not really address multi-model routing, autoscaling, or fleet-level admission control.

## Related Work

- _Kwon et al. (SOSP '23)_ — PagedAttention makes continuous LLM serving practical by fixing KV-cache allocation, while XY-Serve builds on that style of cache layout and focuses on mixed-stage execution plus kernel regularization.
- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve shows the value of chunked prefills for the throughput-latency tradeoff; XY-Serve generalizes the serving substrate to include prefix reuse, verify stages, and hardware-oriented task tables.
- _Yu et al. (OSDI '22)_ — Orca popularized iteration-level scheduling for transformer serving, but XY-Serve pushes the decomposition deeper into token-wise chunks and kernel-facing task decomposition.
- _Zhong et al. (OSDI '24)_ — DistServe separates prefill and decode across nodes, whereas XY-Serve explicitly supports both combined and disaggregated P/D/V roles and focuses on making either form efficient on accelerators.

## My Notes

<!-- empty; left for the human reader -->

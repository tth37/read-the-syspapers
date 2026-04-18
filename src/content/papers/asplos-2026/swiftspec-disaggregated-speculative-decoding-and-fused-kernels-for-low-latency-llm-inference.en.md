---
title: "SwiftSpec: Disaggregated Speculative Decoding and Fused Kernels for Low-Latency LLM Inference"
oneline: "Disaggregates draft and target models across GPUs, preserves tree-speculation KV reuse, and fuses low-latency kernels to cut single-request LLM decode latency."
authors:
  - "Ziyi Zhang"
  - "Ziheng Jiang"
  - "Chengquan Jiang"
  - "Menghan Yu"
  - "Size Zheng"
  - "Haibin Lin"
  - "Xin Liu"
  - "Henry Hoffmann"
affiliations:
  - "Bytedance Seed, Bellevue, WA, United States"
  - "University of Chicago, Chicago, IL, United States"
  - "Bytedance Seed, Beijing, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790246"
code_url: "https://github.com/ByteDance-Seed/SwiftSpec"
tags:
  - llm-inference
  - gpu
  - disaggregation
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

SwiftSpec asks what it would take to minimize latency for one LLM request that already occupies an entire multi-GPU node. Its answer is a joint redesign: put draft and target models on different GPU groups, keep speculative tree KV state reusable even when the verified path changes, and replace throughput-oriented kernels with low-batch kernels that fuse communication into compute. On 8xH800, the paper reports 347 tokens/s for Llama-3-70B and an average 1.75x speedup over the best open-source baseline.

## Problem

The paper focuses on an increasingly important serving regime: one interactive request, very tight per-token latency, and enough business value to dedicate many GPUs to that single query. In that setting, speculative decoding is attractive because one target-model invocation can accept multiple tokens. But existing systems still leave two sources of latency on the table.

First, draft generation usually remains on the critical path. Prior speculative decoders typically run draft and verification sequentially, so the target model cannot advance until the draft model finishes proposing its tree or sequence. Second, naive tensor parallelism does not help both models equally. The target model benefits from more GPUs, but the smaller draft model quickly hits diminishing returns, after which communication dominates. Table 1 makes that asymmetry concrete: for Llama3-70B, latency drops substantially as GPU count rises, while smaller draft-scale models flatten much earlier.

The paper argues that existing combinations of speculative decoding and tensor parallelism therefore waste hardware in single-request mode. If both draft and target are replicated across all GPUs, the node pays communication costs for the draft model without getting comparable latency reduction. If tree speculation is parallelized badly, mispredicted branches also desynchronize KV caches and force recomputation. Finally, the kernels themselves are a bad fit for the regime: at batch size at most 16, GEMM, attention, and all-reduce are latency-bound and spend much of their time on synchronization and launch overhead rather than useful work.

## Key Insight

The key proposition is that low-latency speculative decoding should be treated as a two-level co-design problem. The runtime should remove draft generation from the critical path by disaggregating draft and target onto different GPU groups, and the kernel layer should remove per-round synchronization overhead by fusing small-batch communication directly into compute.

That only works if the system can preserve speculative state across the boundary between the two groups. SwiftSpec's real insight is therefore not just "run them in parallel," but "make rerooting cheap enough that parallel tree speculation stays useful." The evolving tree cache is the mechanism that turns asynchronous draft/verify execution from a tempting idea into a viable one: verified tokens move into a contiguous prefix cache, surviving subtrees stay contiguous after that prefix, and wrong branches are discarded without recomputing useful KV states. With that invariant in place, the draft model can keep exploring ahead while the target verifies the previous subtree.

## Design

SwiftSpec splits an 8-GPU node into two tensor-parallel groups, one for the draft model and one for the target model. The target verifies iteration `n-1` while the draft grows the tree for iteration `n`, so the draft phase is no longer serialized ahead of every target step. Each round has a simple control pattern: the draft expands the most probable leaves `d` times, receives the last verified token sequence from the target, reroots the tree and cache, selects a subtree of size `bs`, and sends that subtree back for the next verification pass.

The draft tree itself is probability-driven. Each node stores log-softmax value, path weights are accumulated from root to leaf, and a priority queue selects the most likely leaves in `O(k log s)` time. SwiftSpec sets `bs = 8` and draft width `w = 8` empirically, then picks tree depth `d` so one round of draft expansion finishes at about the same time as one round of target verification. That timing match is what lets the two GPU groups overlap cleanly.

The evolving tree cache is the critical data-path mechanism. The cache is partitioned into a prefix region holding verified tokens and a tree region holding the remaining speculative subtree. After each verification result arrives, the draft worker walks the verified path, reroots at the last accepted token, promotes newly verified tokens into the prefix, compacts the surviving subtree behind it, and only starts a fresh tree if the verified token is no longer present in the current draft tree. The important invariant is that all still-useful KV states survive rerooting, so even a partially wrong speculative tree does not imply wasted work.

The paper also adds one practical feature that is easy to miss but necessary: the draft model needs non-square attention masks. During tree expansion, the draft batch contains candidate leaves that should attend only to their ancestors plus the verified prefix, not to an ordinary square causal window. SwiftSpec therefore implements custom masked attention that accepts shapes such as `(4, 10)` rather than assuming square matrices.

At the kernel layer, SwiftSpec replaces separate low-batch compute and communication steps with fused operators. It uses NCCL LL and LL128 primitives directly: GEMM is fused with the following all-reduce, attention combines compute and synchronization without extra barriers, and SwiGLU fuses both matrix multiplications with activation and pointwise combination. The implementation is substantial rather than notional: about 3 KLOC of CUDA/C++ kernels plus about 4 KLOC of C++/Python runtime.

## Evaluation

The evaluation is well aligned with the claim. Experiments run on one 8xH800 80GB SXM node over five target/draft model families and six datasets, with 80 prompts per dataset for 480 total queries. All systems use greedy decoding, and the authors quantize transformer weights to 4-bit AWQ except for EAGLE models, while keeping embeddings and LM heads in BF16.

The headline result is end-to-end decoding speed. Across the five model families, SwiftSpec is on average 1.75x faster than SpecExec and 2.23x faster than SGLang where compared, and it is faster than the strongest baselines across the full CDF for Llama-3-70B. The paper specifically reports at least 1.7x speedup at the 95th percentile for that model across all 480 requests, which matters because this work is explicitly about tail-sensitive interactive serving rather than average throughput alone.

The ablations explain where the gains come from. For Qwen2-72B, moving from serial tree speculation to SwiftSpec's disaggregated parallel tree generation lowers average acceptance length only modestly, by 9% on average, but cuts draft-model time from 3.72 ms to 3.25 ms while barely changing target time from 10.34 ms to 10.48 ms. That shift raises end-to-end speed from 200 to 274 tokens/s, a 1.37x improvement, showing that taking the draft off the critical path matters more than squeezing out the last bit of acceptance length.

Kernel microbenchmarks support the second half of the thesis. The fused GEMM-plus-all-reduce operator cuts attention-block latency by 23%-43% and MLP-block latency by 16%-25% for smaller models. The fused attention kernel is reported to save 30%-56% relative to FlashAttention under representative context lengths, and the fused SwiGLU kernel reduces latency by 39%-50% on small models, though not on the largest 70B case.

## Novelty & Impact

Relative to _Miao et al. (ASPLOS '24)_, SwiftSpec is not just another tree-speculation runtime. SpecInfer shows the algorithmic value of tree verification, while SwiftSpec asks how to keep that idea effective when the serving objective is minimum single-request latency on a whole node. Its answer is system-level disaggregation plus cache invariants plus kernel fusion.

Relative to _Butler et al. (arXiv '24)_, which pipelines speculative decoding across devices, SwiftSpec's novelty is that it handles tree-based speculation rather than only sequence-style overlap, and it does so with explicit KV rerooting that keeps useful branches alive. Relative to _Ye et al. (MLSys '25)_, SwiftSpec is not a general attention engine; it is a latency-specialized serving system that uses communication-aware kernels because speculative decoding at low batch size is dominated by barriers and launches. This combination makes the paper likely to matter for future single-request serving stacks and for any system trying to turn "one prompt, many GPUs" from a product hack into a principled design point.

## Limitations

The paper is strongest in the exact regime it targets and weaker outside it. All core results come from one 8xH800 NVLink-connected node and single-request greedy decoding, so the evidence for lower-end interconnects, multi-node deployments, or more diverse serving objectives is mostly by argument rather than measurement.

There is also a regime mismatch between the kernels and broader LLM serving. The authors explicitly note that their fused kernels are latency-optimized for small models and small batch sizes; for larger batches, throughput-oriented kernels such as FlashInfer can win once communication and launch costs are amortized. The SwiGLU results already show this pattern, where SwiftSpec loses to existing kernels on the 70B case.

Finally, some comparisons are necessarily incomplete. EAGLE3 is evaluated only on Llama-3.3-70B-Instruct because that is the only public large model with a trained EAGLE3 draft, and SwiftSpec relies on per-model profiling to choose GPU splits and tree depth. That makes the design practical, but not fully plug-and-play.

## Related Work

- _Miao et al. (ASPLOS '24)_ — SpecInfer established tree-based speculative verification, while SwiftSpec redesigns the runtime so tree speculation can run asynchronously across disjoint GPU groups.
- _Butler et al. (arXiv '24)_ — PipeInfer overlaps draft and verification across devices, but it is sequence-oriented; SwiftSpec extends the overlap idea to tree speculation with reroot-safe KV reuse.
- _Zhong et al. (OSDI '24)_ — DistServe disaggregates prefill from decode across serving roles, whereas SwiftSpec disaggregates draft from target inside the decode path itself.
- _Ye et al. (MLSys '25)_ — FlashInfer accelerates attention for LLM serving, while SwiftSpec focuses on the ultra-low-batch regime and fuses communication directly into attention and GEMM.

## My Notes

<!-- empty; left for the human reader -->

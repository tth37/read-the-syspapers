---
title: "DFVG: A Heterogeneous Architecture for Speculative Decoding with Draft-on-FPGA and Verify-on-GPU"
oneline: "Splits speculative decoding across FPGA drafting and GPU verification, then adds adaptive branching and overlap to raise throughput and cut energy."
authors:
  - "Shaoqiang Lu"
  - "Yangbo Wei"
  - "Junhong Qian"
  - "Dongge Qin"
  - "Shiji Gao"
  - "Yizhi Ding"
  - "Qifan Wang"
  - "Chen Wu"
  - "Xiao Shi"
  - "Lei He"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Eastern Institute of Technology, Ningbo, China"
  - "Southest University, Nanjin, China"
  - "Ningbo Institute of Digital Twin, Ningbo, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790153"
code_url: "https://github.com/ShaoqiangLu/DFVG"
tags:
  - llm-inference
  - hardware
  - gpu
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

DFVG argues that speculative decoding should not keep draft and verify on the same class of processor. It places the lightweight draft model on FPGA, keeps the large verifier on GPU, adapts the speculative tree to token confidence and hardware limits, and overlaps both stages through a tightly coupled pipeline. On the paper's workloads, that combination reaches up to `3.26x` speedup and `5.79x` energy-efficiency improvement.

## Problem

The paper starts from a mismatch that speculative decoding systems often hide instead of fixing. The draft model is small, bandwidth-sensitive, and latency-oriented; the verifier is large, compute-heavy, and closer to a prefill-style workload. If both are forced onto GPUs, they compete for memory capacity and bandwidth while using very different kinds of parallelism. If both are forced onto CPUs, verification becomes too slow. Either way, the system spends too much time shuttling weights, idling during phase changes, or underusing one of the devices.

Existing speculative decoders also make two algorithmic choices that worsen the systems problem. First, they often use fixed draft trees, so high-confidence positions do not exploit extra hardware parallelism while low-confidence positions still spawn branches that are unlikely to survive verification. Second, they treat drafting and verification as loosely coordinated stages. When acceptance falls, the pipeline pays twice: rejected tokens trigger rollback, and the other device waits for synchronization. The paper's claim is that these are not separate issues. Hardware placement, branch construction, and pipeline control have to be designed together or speculative decoding's theoretical gain gets eaten by utilization loss.

## Key Insight

DFVG's central proposition is that speculative decoding has a naturally heterogeneous structure. Draft generation is sequential but lightweight, so it benefits from FPGA-style streaming pipelines, fine-grained parallelism, and lower energy per operation. Verification is dense and batchable, so it belongs on a GPU that can execute the large model in parallel. Once the stages are placed on hardware that matches their bottlenecks, the remaining job is to keep both devices busy enough that PCIe and rollback do not dominate.

That leads to the second insight: the speculative tree itself should adapt to both model confidence and hardware budget. Rather than emitting a fixed branching pattern, DFVG tries to maximize the expected number of accepted tokens under limits on total branches, per-layer hardware parallelism, and minimum depth needed to overlap FPGA drafting with GPU verification. The system then makes verification GPU-friendly by reordering the tree into block-structured attention work. In other words, the paper's key move is not just "put draft on FPGA"; it is "shape the speculation so the FPGA and GPU each see work they can execute efficiently."

## Design

The algorithmic core is ADAPT, a budget-constrained formulation for building the speculative tree. The paper defines binary decision variables for whether a token is selected at a node and maximizes the expected number of verified tokens subject to three constraints: total branch budget, per-layer branch count bounded by hardware parallelism, and minimum speculative depth required to hide verifier latency. Because exact integer programming is too expensive online, DFVG uses a greedy approximation that scores paths by cumulative probability, applies a temperature-controlled softmax over candidate extensions, and uses Gumbel sampling to choose non-repetitive branches. The result is a dynamic tree that grows when confidence and hardware headroom are high and stays sparse when they are not.

The second mechanism is TreeSort-Verify. Raw tree verification creates irregular causal masks and poor memory locality on the GPU. DFVG reorders nodes so ancestor relationships become a block-diagonal lower-triangular pattern, then decomposes verification into independent blocks that can use standard high-throughput GEMM kernels. This is important because the paper does not win solely by moving the draft model off GPU; it also reduces the verifier-side tax that tree-based speculation usually introduces.

The hardware design centers on a multi-core FPGA overlay processor. It uses HBM-fed systolic PE arrays, a parallel adder tree, special-function units, and branch-management logic tailored to speculative drafting. Two details matter. First, multiple speculative branches share prefixes, so the processor maps branch groups to cores in a way that increases reuse of weights and activations. Second, the PE microarchitecture uses branch-specific weight buffers and two-BF16 packing per DSP to raise effective throughput. The draft side also maintains its own KV-cache management policy, with temporary buffers for candidate branches, pruning of rejected paths, and contiguous allocation for accepted tokens.

Pipeline control is the final piece. DFVG connects FPGA and GPU through interrupt-driven, asynchronous PCIe communication using shared host memory and ping-pong buffers. While the GPU verifies one batch of candidates, the FPGA continues drafting the next set. If verification finishes early, the GPU can continue forward from the accepted prefix; if rejection occurs, the FPGA rolls back from the returned prefix length and resumes. The paper emphasizes that only compact token metadata crosses devices, not heavyweight model state, which is why communication overhead stays off the critical path in their measurements.

## Evaluation

The implementation uses a V80 FPGA for the draft model and RTX 4090 or A100 GPUs for verification, with experiments on Vicuna-7B, LLaMA-7B, OPT-13B, and Qwen3-8B paired with smaller same-family draft models. Datasets include MT-Bench, translation, summarization, QA, math reasoning, and RAG tasks. The baseline set is broad for this kind of paper: autoregressive decoding, classic speculative sampling, DuoDecoding, SpecInfer, and several optimized inference frameworks including vLLM, LLaMA.cpp, and GPT-Fast.

The headline result is end-to-end speedup of `2.44x-3.26x` and energy-efficiency improvement of `4.33x-5.79x` relative to autoregressive decoding, with the best speedup appearing on Qwen3-8B. The paper also reports token acceptance rates staying around `75%-85%` even as accepted draft lengths vary substantially across iterations, which supports the value of dynamic drafting over fixed-length schemes. Against strong optimized frameworks, the authors argue that software-only kernel and memory optimizations plateau near about `1.5x`, while DFVG keeps scaling because it changes the hardware mapping and overlaps stages instead of only trimming per-kernel cost.

I found the ablation especially useful because it disentangles the gains. Hardware-aware branching alone reaches `2.21x`; adding TreeSort-Verify lifts that to `2.46x`; the FPGA multi-core accelerator reaches `3.08x`; and pipeline overlap finishes at `3.26x`. Communication overhead is reported at only `1.08%-3.2%`, with the verifier remaining compute-bound on PCIe Gen4 x16. The resource-utilization section also supports the implementation story: on V80, the design uses most LUT/FF budget and achieves `86.2%-97.5%` operator efficiency in matrix multiplication. The evaluation is strongest as a proof that heterogeneous draft/verify partitioning can beat GPU-only speculative decoding on single-model inference; it says less about multi-tenant serving, very large batch regimes, or deployment cost-normalized comparisons.

## Novelty & Impact

Relative to _Miao et al. (ASPLOS '24)_, DFVG keeps tree-based speculation but adds hardware-aware branch construction and an explicit FPGA/GPU partition instead of relying on multi-GPU execution. Relative to _Li et al. (ASPLOS '24)_, its contribution is not near-memory acceleration for the whole speculative pipeline, but assigning the small and large models to different processor classes that better fit their bottlenecks. Relative to software-only speculative methods, the paper reframes the bottleneck as a co-design problem across branching policy, verifier layout, and device overlap.

That makes the paper most useful to researchers working on LLM inference acceleration and to architects exploring where FPGAs still matter in modern AI serving stacks. Even if DFVG itself is not the final production answer, it makes a clear case that speculative decoding performance depends on how well the system matches each stage to a hardware substrate, not just on better draft heuristics.

## Limitations

DFVG depends on custom FPGA hardware, a Verilog-based overlay design, and a runtime/compiler stack that is much heavier to deploy than a GPU-only serving system. The dynamic tree builder uses draft-model confidence as a proxy for verification probability, which may drift when draft and target models diverge more sharply than in the tested same-family pairs. The evaluation is also not a full apples-to-apples cost study: it compares heterogeneous FPGA+GPU execution against several software baselines, but does not normalize for procurement complexity, developer effort, or cluster-level scheduling effects. Finally, the paper does not address multi-model serving, long-lived cache sharing across requests, or distributed scaling beyond pointing to those directions in future work.

## Related Work

- _Miao et al. (ASPLOS '24)_ — SpecInfer uses tree-based speculative inference and verification on GPUs, while DFVG adds adaptive branch budgeting, verifier reordering, and FPGA/GPU stage partitioning.
- _Li et al. (ASPLOS '24)_ — SpecPIM accelerates speculative inference with PIM-oriented architecture-dataflow co-design, whereas DFVG keeps verification on GPU and specializes FPGA only for drafting.
- _Fu et al. (ICML '24)_ — Lookahead decoding removes the auxiliary draft model through masked decoding, while DFVG keeps a separate draft model and optimizes the systems pipeline around it.
- _Li et al. (ICML '24)_ — EAGLE revisits speculative decoding at the feature level to reduce uncertainty, while DFVG focuses on hardware placement, dynamic branching, and verifier execution efficiency.

## My Notes

<!-- empty; left for the human reader -->

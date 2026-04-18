---
title: "RedFuser: An Automatic Operator Fusion Framework for Cascaded Reductions on AI Accelerators"
oneline: "RedFuser symbolically detects fusible cascaded reductions, derives incremental fused formulas, and emits GPU kernels that approach hand-tuned attention code."
authors:
  - "Xinsheng Tang"
  - "Yangcheng Li"
  - "Nan Wang"
  - "Zhiyi Shu"
  - "Xingyu Ling"
  - "Junna Xing"
  - "Peng Zhou"
  - "Qiang Liu"
affiliations:
  - "Alibaba Cloud Computing, Shanghai, China"
  - "Alibaba Cloud Computing, Sunnyvale, USA"
  - "Alibaba Cloud Computing, Shenzhen, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790209"
tags:
  - compilers
  - gpu
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

RedFuser targets a pattern that current AI compilers still handle poorly: chains of dependent reductions such as safe softmax, attention, MoE routing, and FP8 quantization followed by GEMM. The paper's main move is to represent those chains symbolically, prove when they can be fused across reduction boundaries, and then derive an incremental form that keeps the fused computation streamable on GPUs. On supported workloads, the generated kernels beat general-purpose compiler stacks by `2x-5x` and come close to, or slightly exceed, hand-written attention kernels.

## Problem

Cascaded reductions appear whenever one reduction feeds another: max followed by sum in safe softmax, softmax followed by GEMM in attention, softmax plus top-k in MoE routing, or abs-max scaling followed by GEMM in FP8 quantization. These patterns are common in modern AI models, but they are awkward for compilers because each reduction stage depends on the root of the previous reduction tree. That serial dependence creates two bottlenecks. First, every stage reloads input or intermediate data, so memory traffic is repeated. Second, the next reduction cannot begin until the previous one finishes, which limits overlap and parallelism.

Existing AI compilers do perform operator fusion, but the paper argues they mostly fuse reductions with surrounding elementwise or compute-heavy operators rather than fusing one reduction stage into the next. As a result, they do not derive a single loop-level kernel for a whole chain of reductions. Manual kernels such as FlashAttention and FlashDecoding solve important special cases, but only after expert authors derive online update rules by hand for one pattern at a time. The gap RedFuser tries to close is therefore not "how do we optimize one more attention kernel," but "can a compiler recognize reduction chains as a structured class and automatically recover the same algebraic trick?"

## Key Insight

The central claim is that many cascaded reductions can be fused if each stage can be decomposed into a product of two parts: one part that depends only on the current input element, and one part that depends only on previous reduction results. More formally, the paper requires the reduction expression to be written as `G_i(X[l]) ⊗ H_i(D_i)`, with `⊗` forming a commutative monoid and the reduction operator distributing over it. When those conditions hold, RedFuser can rewrite the computation so that stage `i` at level `k` depends on the stage outputs of earlier reductions at the same level, rather than waiting for the final root of every previous tree.

That matters because it breaks the most expensive dependency in the original program. The fused form lets the compiler load input once, reuse on-chip results across stages, and merge multiple reduction trees into one level-aligned reduction tree. The second half of the insight is that fusion alone is not enough; the fused tree still wants to cache a whole previous level. RedFuser therefore derives an incremental update rule that corrects the running result whenever a new segment arrives. This lowers storage from `O(L_{k-1})` to `O(1)`, which is what makes long-sequence GPU kernels practical rather than just algebraically elegant.

## Design

RedFuser is implemented on top of TVM. It starts from a model lowered into Relax, identifies cascaded-reduction subgraphs, lowers them to TIR, then normalizes the loop structure with inlining and reordering. A visitor over the TIR AST reconstructs the mathematical expression for each reduction stage, including its dependency on earlier stages. This symbolic expression is the input to the paper's Automatic Cascaded Reductions Fusion (`ACRF`) algorithm.

`ACRF` is the paper's most novel mechanism. It narrows the search space using a domain assumption that AI workloads mostly use reductions such as `sum`, `product`, `max`, and `min`, so the compatible binary operator `⊗` can be looked up from a table. It then checks decomposability with a fixed-point identity: if `F_i(x, d) ⊗ F_i(x_0, d_0) = F_i(x, d_0) ⊗ F_i(x_0, d)`, the function can be separated into input-only and dependency-only parts. From there RedFuser instantiates three families of equations: the first-level fused reduction, the higher-level fused reduction, and the incremental update rule. The appendix adds a repair for non-invertible cases by substituting the identity element when `H_i` would otherwise lack an inverse.

Once it has a fused expression, RedFuser offers two GPU execution strategies. The `Single-Segment` strategy uses incremental updates so one CTA can process a long reduction stream without storing the whole prior level, avoiding inter-block synchronization. The `Multi-Segment` strategy partitions the input across CTAs and later merges partial results with the fused higher-level reduction rule. The rest of the compiler stack is a hardware-aware lowering pipeline: blockization, buffer-scope inference, conversion to TileOps, TileLang code generation, and auto-tuning over tile sizes, thread counts, software-pipeline depth, and segment count. The generated code explicitly targets features such as `cp.async` or `TMA` for copies and `MMA`/`WGMMA` for GEMM-like tiles.

## Evaluation

The main evaluation uses two NVIDIA GPUs, `A10-24GB` and `H800-80GB`, and four representative subgraphs: MHA, MLA, MoE routing, and FP8 PerToken Quant + GEMM. Baselines include PyTorch Eager, PyTorch Dynamo/Inductor, TVM Relax, and hand-optimized libraries where available, namely FlashAttention2 and FlashMLA. This is a good baseline set for the paper's claim, because it compares RedFuser both to general compiler stacks and to pattern-specific expert kernels.

The headline results are strong. For MHA, RedFuser averages `1.09x` the performance of FlashAttention2 and on a LLaMA-65B configuration reaches `2.8x` speedup over PyTorch Dynamo and `2.6x` over TVM. For MLA, it reaches `102%` of FlashMLA while beating Dynamo by `2.4x` and TVM by `8.7x`. On workloads without standard hand-tuned baselines, the paper still reports large wins: `1.7x` over Dynamo and `6.6x` over TVM for MoE routing, and `3.4x` over Dynamo plus `12.1x` over TVM for Quant + GEMM.

The more diagnostic studies are also useful. A safe-softmax experiment comparing intra-thread, intra-warp, intra-block, and inter-block fusion finds that intra-block fusion is best, because it gives enough computation depth to hide memory latency without paying the strongest dependency penalty. The incremental-versus-non-incremental study is also refreshingly honest: non-incremental mode is faster when both modes fit the same hardware budget, but it only works for short segments because it must cache complete prior results on chip. Incremental mode introduces correction overhead, yet it unlocks configurations that non-incremental execution cannot fit at all; the best configuration in that study appears at `Waves per SM = 3` and yields up to `1.25x` over the baseline.

I found the evaluation supportive of the paper's core claim: RedFuser is not merely another attention kernel, but a compiler method that recovers high-performance specialized implementations across several reduction-chain patterns. The main scope limit is that the evaluation is still subgraph-centric rather than end-to-end model training or serving, so system-level effects such as graph partitioning overhead, compile-time cost in full applications, and interaction with larger runtimes remain outside the paper's evidence base.

## Novelty & Impact

Relative to _Dao et al. (NeurIPS '22)_, RedFuser's novelty is not faster attention tiling per se, but the claim that FlashAttention-style online updates can be derived automatically from a symbolic reduction-chain analysis. Relative to _Zheng et al. (ASPLOS '22)_, the contribution is a more specific formalization: instead of a general multi-operator fusion space, the paper isolates cascaded reductions as a class with explicit algebraic feasibility conditions. Relative to _Xia et al. (ASPLOS '24)_ and similar compiler systems, RedFuser's distinctive move is cross-reduction expression fusion, not just aggressive fusion around one reduction stage.

That makes the paper useful to at least two audiences. Compiler researchers can cite it as a concrete bridge between symbolic algebra and GPU code generation for AI workloads. GPU-kernel and systems practitioners can cite it because it argues that several "manual wizardry" kernels, especially attention-style online normalization, are special cases of a compiler-derivable template rather than one-off engineering feats.

## Limitations

The paper is explicit that RedFuser does not apply to arbitrary operator chains. Its fusion rule requires decomposability, algebraic structure, and distributivity; if those conditions fail, the method does not go through. Even when fusion is legal, it may not be profitable, because correction steps add arithmetic work and raise register or on-chip memory pressure. The authors explicitly call for a future cost model to decide when fusion should be skipped.

The implementation scope is also narrower than the title might suggest. The current system is built around TVM, TileLang, and GPUs, with the strongest evidence on NVIDIA hardware. The appendix shows additional non-ML examples and some cross-platform results, but the main body still centers on AI subgraphs rather than full accelerator stacks or full application pipelines. Finally, the fusion search itself is lightweight only because the paper restricts the operator families it handles; broader reduction semantics remain future work.

## Related Work

- _Dao et al. (NeurIPS '22)_ — FlashAttention hand-derives tiled online softmax for attention, whereas RedFuser tries to derive the same style of incremental update automatically from symbolic reduction equations.
- _Zheng et al. (ASPLOS '22)_ — AStitch broadens operator-fusion opportunities in ML workloads, but it does not formalize chains of dependent reductions as a fusible class with explicit algebraic tests.
- _Xia et al. (ASPLOS '24)_ — SOUFFLE aggressively fuses reduction-adjacent tensor operators, while RedFuser focuses on fusing one reduction stage into the next and emitting corrected incremental forms.
- _Zhang et al. (SC '24)_ — MCFuser optimizes memory-bound compute-intensive operator chains, whereas RedFuser targets the harder dependency structure of cascaded reductions themselves.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Trinity: Three-Dimensional Tensor Program Optimization via Tile-level Equality Saturation"
oneline: "Trinity equality-saturates a tile-level IR so compilers can rewrite algebra, memory traffic, and kernel structure together instead of optimizing them in isolation."
authors:
  - "Jaehyeong Park"
  - "Youngchan Kim"
  - "Haechan An"
  - "Gieun Jeong"
  - "Jeehoon Kang"
  - "Dongsu Han"
affiliations:
  - "Korea Advanced Institute of Science and Technology, Daejeon, Republic of Korea"
  - "FuriosaAI, Seoul, Republic of Korea"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790240"
tags:
  - compilers
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Trinity is a tensor compiler that moves optimization down to the tile level and then runs equality saturation over that representation. Its core move is to make algebraic rewrites, memory loads and stores, and kernel-structure choices all first-class terms in the same IR, so the compiler can rediscover FlashAttention-like schedules and also fuse code beyond what hand-written kernels usually cover. Across dense Transformer variants, the paper reports up to `2.09x` lower latency than TensorRT, `3.07x` over Mirage, and `1.35x` over FlashInfer on Vanilla attention.

## Problem

The paper starts from a familiar compiler split. Graph-level optimizers rewrite tensor operators and fuse adjacent nodes, while operator-level compilers separately decide tiling, loop order, memory placement, and parallelization for each operator. That split is workable for ordinary kernel generation, but it blocks exactly the kind of coordinated transformation that made FlashAttention important: algebra must change, tiles must stay on-chip, and the execution order must be reorganized together.

The authors argue that this is not a corner case anymore. Transformer variants continue to proliferate, and accelerator architectures keep changing their memory hierarchies and tensor-core behavior. Hand-specializing every model-hardware pair is no longer sustainable, yet separated compiler pipelines still treat operator internals as opaque at graph level and treat graph structure as fixed at schedule level. The result is a large unexplored space of cross-operator, tile-level programs.

A naive "just search everything jointly" answer also fails. The paper claims even a basic Vanilla Transformer block yields more than `10^17` equivalent programs. Exhaustive multi-level search, as in Mirage, times out or must partition the program into smaller fragments, which destroys exactly the cross-boundary opportunities Trinity wants to capture. So the real problem is to search this coupled space without either losing correctness on stateful memory operations or drowning in combinatorial blowup.

## Key Insight

The paper's central proposition is that tile granularity is the lowest level at which the three important dimensions of tensor-program performance all become simultaneously explicit: algebraic equivalence, memory I/O, and compute orchestration. At tensor-operator granularity, the memory and loop structure are hidden. At lower implementation granularity, the search space becomes too syntactic and too large. Tiles are the point where the compiler can still reason symbolically while talking in the same units that GPUs and NPUs actually execute.

Once the program is expressed in that form, equality saturation becomes attractive because it can keep many equivalent programs alive at once instead of greedily committing early. But that only works if the IR can safely express sequences, loops, loads, and stores, and if extraction can reason about context-dependent cost. Trinity's real insight is therefore two-part: use a tile-level stateful IR so the right choices become expressible, then add enough structure around equality saturation that the statefulness does not make the e-graph unusable.

## Design

Trinity IR has three kinds of first-class objects. For memory I/O, it distinguishes `input`, `output`, and `variable` tensors and makes `load` and `store` explicit. For compute orchestration, it exposes `seq` and `loop`, so kernel boundaries, sequential dependences, and parallel loop nests can all be rewritten. For algebra, it treats each tile as a small tensor and supports ordinary tile-level math such as elementwise operators, reductions, reshapes, and `matmul`. That is the representational foundation for joint optimization.

On top of the IR, Trinity applies two broad families of rewrite rules. Loop rules handle fusion, fission, loop-invariant code motion, loop insertion, and reindexing. Algebraic rules include familiar tensor identities plus a loop-body factoring rule that can hoist divisions or multiplies out of inner loops and remove loop-carried dependences. The case study is the paper's best illustration: Trinity starts from a straightforward QKV projection plus attention program, first fuses inner attention loops, then uses distributivity and algebraic factoring to remove the accumulator dependence, thereby rediscovering FlashAttention's online-softmax structure, and then goes further by fusing QKV projection and reshape into the same final kernel.

Three mechanisms make saturation practical on this stateful IR. First, expression propagation records the symbolic value written by a `store` and rewrites later `load`s of the same tile to that value, so algebraic rules still match across memory boundaries. Second, Trinity canonicalizes all sequences into a right-associative `seq` form to avoid exponential blowup from redundant parenthesizations. Third, it uses `egg` e-class analyses to track read and write regions, aliases, loop-variable dependence, and shapes; rewrite rules fire only if semantic dependence checks show that reordering is safe.

Extraction is also customized. Because the cost of an operation depends on whether it stays on-chip, crosses a kernel boundary, or runs in parallel versus sequentially, Trinity does not use a single fixed-cost extraction pass. Instead it uses two passes: Pass 1 enumerates loop structures with minimal kernel count, treating kernel launches and inter-kernel traffic as the dominant coarse cost; Pass 2 fixes the loop structure and greedily chooses loop bodies that minimize FLOPs per compute unit. The selected candidates are lowered to Triton, where outermost parallel loops become kernels, tile placement is chosen to keep intermediates on-chip when possible, and concrete tile sizes are finalized by profiling.

## Evaluation

The evaluation covers six dense Transformer-style workloads: Vanilla, Pre-Norm, QK-Norm, RoCo, KeyFormer, and SwiGLU FFN. The authors test LLaMA3 8B and Falcon 7B configurations in a speculative decoding setting with a `1008`-token prefix plus `16` verified tokens, and run on `H100`, `A100`, `RTX 4090`, and `RTX 5090`. Baselines include TorchInductor, TensorRT, FlashTensor, Relax, Mirage, and FlashInfer where applicable.

The headline latency numbers are strong. On H100 for the LLaMA3 8B configuration, Trinity reports `1.71x` speedup over TensorRT on Vanilla, `1.43x` on Pre-Norm, `1.63x` on QK-Norm, `1.29x` on KeyFormer, `1.37x` on RoCo, and `1.10x` on SwiGLU FFN. Against Mirage, the best reported gain reaches `3.07x`. On Vanilla attention specifically, Trinity beats FlashInfer by `1.35x` because it fuses not only the attention core but also the preceding QKV projection and reshape stages into one kernel. The Pre-Norm result is particularly revealing: by inserting RMS computation into the projection loop and then using algebraic rewrites to make the program fusible, Trinity gets a `1.40x` gain over Mirage on H100.

The hardware-adaptation story is also convincing. For KeyFormer, Trinity chooses different optimal kernels on H100 and RTX 4090. On the bandwidth-rich H100, the best kernel spills some intermediates off-chip so it can use larger tiles and fewer iterations. On the bandwidth-constrained RTX 4090, the best kernel keeps intermediates on-chip and accepts smaller tiles to avoid saturating memory bandwidth. That supports the paper's claim that memory placement and kernel structure must stay in the optimization space instead of being collapsed away.

Compilation cost is high but still plausible for ahead-of-time kernel generation. Trinity claims search spaces up to `10^21` equivalent programs, yet still optimizes whole components such as RoCo and KeyFormer in `710` and `1459` seconds. The authors also report that Mirage would need `7.5x-38.1x` more time on the same benchmarks after partitioning. I found the evidence broadly supportive of the paper's main claim: the workloads exercise exactly the kind of fused attention and feed-forward structures the optimizer targets, and the comparisons are against serious compiler baselines rather than toy implementations.

## Novelty & Impact

Relative to _Yang et al. (MLSys '21)_, Trinity's novelty is not just using equality saturation for tensor algebra, but extending it to a stateful tile-level IR where memory traffic and loop structure can also be rewritten. Relative to _Shi et al. (OSDI '23)_ and _Park et al. (NeurIPS '23)_, the contribution is broader than better tiling or parallelization across a fixed computation: Trinity tries to make new computations fusible by algebraically changing them first. Relative to _Wu et al. (OSDI '25)_, its main contribution is scalability, because it avoids Mirage's exhaustive µGraph-style search and can keep large unpartitioned program components intact.

That makes the paper important to two groups. Tensor-compiler researchers can cite it as one of the clearest attempts to unify graph rewriting, scheduling, and memory placement in one optimization loop. Kernel engineers can cite it because the fully fused attention case suggests that some "manual-only" optimizations are actually discoverable when the compiler reasons at the right abstraction level.

## Limitations

The paper is still focused on inference-time dense tensor programs, especially Transformer blocks. Training graphs and backpropagation are future work, not part of the evaluated system. Trinity also relies on Triton for code generation, so it does not yet exploit Hopper-specific features such as warp specialization or TMA, which the authors note are important for FlashAttention-3-class kernels.

Compilation is also not cheap. Even with compact e-graphs, the optimizer may spend minutes on extraction and then profile up to `512` candidates; the paper uses eight GPUs to parallelize profiling in evaluation. That is acceptable for ahead-of-time compilation, but not for fast just-in-time deployment loops. Finally, the authors acknowledge that very large combined programs, such as attention plus FFN together, still strain the current "apply all rules for fixed iterations" strategy, and the generated kernels are only numerically equivalent up to floating-point reordering effects rather than bit-identical.

## Related Work

- _Yang et al. (MLSys '21)_ — TENSAT uses equality saturation for tensor-graph superoptimization, but it stays at tensor-operator granularity and cannot reason about tile placement or kernel boundaries.
- _Shi et al. (OSDI '23)_ — Welder improves deep-learning memory scheduling through tile graphs, whereas Trinity treats algebraic rewrites, memory I/O, and loop structure as one joint search space.
- _Wu et al. (OSDI '25)_ — Mirage is Trinity's closest direct baseline, but its exhaustive multi-level search requires partitioning small fragments and misses cross-partition fusion opportunities.
- _Dao et al. (NeurIPS '22)_ — FlashAttention provides the classic manually engineered online-softmax schedule that Trinity is able to rediscover and extend into fully fused attention.

## My Notes

<!-- empty; left for the human reader -->

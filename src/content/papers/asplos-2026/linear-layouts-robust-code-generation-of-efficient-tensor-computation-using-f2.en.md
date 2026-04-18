---
title: "Linear Layouts: Robust Code Generation of Efficient Tensor Computation Using F2"
oneline: "Models GPU tensor layouts as F2-linear maps so Triton can derive conversions, swizzles, and SIMD lowerings generically instead of by hand."
authors:
  - "Keren Zhou"
  - "Mario Lezcano-Casado"
  - "Adam P. Goucher"
  - "Akhmed Rakhmati"
  - "Jeff Niu"
  - "Justin Lebar"
  - "Pawel Szczerbuk"
  - "Peter Bell"
  - "Phil Tillet"
  - "Thomas Raoux"
  - "Zahi Moudallal"
affiliations:
  - "George Mason University, Fairfax, United States"
  - "OpenAI, San Francisco, United States"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3760250.3762221"
tags:
  - gpu
  - compilers
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Linear Layouts replaces Triton's ad hoc layout machinery with a single mathematical abstraction: treat a tensor layout as a linear map over `F2` from hardware-resource bits to logical tensor coordinates. Once layouts live in that representation, the compiler can derive conversions, swizzles, vectorization decisions, and even hardware-intrinsic lowerings generically. The result is a backend that is both more robust and measurably faster than legacy Triton on real kernels.

## Problem

The paper targets a compiler pain point that keeps worsening as deep-learning kernels and GPU hardware diversify. Efficient tensor code depends on layout choices that decide which logical tensor elements land in which registers, threads, warps, and memory banks. Those choices are manageable for ordinary blocked loads and stores, but they become much harder once Tensor Core instructions, shared-memory swizzles, mixed precision, and vendor-specific matrix-multiply units enter the picture.

Legacy Triton handled this with special-purpose layout classes and manually written conversions between them. That creates three failures. Extensibility is poor because every new layout drags in more pairwise conversion logic. Correctness is poor because layout code is easy to get wrong; the paper reports that `12%` of open Triton bugs were layout-related. Performance is also capped by engineering coverage: if a conversion could use warp shuffles, `ldmatrix`, or a better swizzle, Triton would not usually discover it unless someone had encoded that exact case by hand.

So the real problem is not just to support more layouts, but to find a representation that can express blocked, MMA, sliced, and swizzled forms in one language while still letting a compiler derive propagation and conversion rules automatically.

## Key Insight

The central claim is that the tensor layouts relevant to Triton can be modeled as linear maps over `F2`, where addition is XOR and multiplication is AND on individual bits. That fits GPUs surprisingly well because register indices, thread indices, warp indices, bank indices, and many tile sizes are already powers of two, so their binary decompositions are the right representation level.

Once a layout is a matrix over `F2`, composition, inversion, slicing, and products become ordinary linear-algebra operations instead of bespoke compiler code. A blocked layout, an MMA input layout, and an MMA swizzle become instances of the same object. Layout conversion therefore becomes: compute the linear relation between two layouts, then realize that relation with the cheapest available primitive.

This reframes layout handling from an enumeration problem into a synthesis problem. Instead of asking whether the backend authors implemented conversion `X -> Y`, Triton can ask what matrix connects `X` and `Y`, and whether warp shuffles, vectorized shared-memory instructions, or other primitives can implement it.

## Design

The design starts by defining a linear layout as a labeled map over `F2` from hardware spaces such as `Reg x Thr x Wrp` into logical tensor coordinates. Labels preserve which columns belong to registers, threads, warps, or memory offsets, so the compiler can reason about where movement happens. The paper shows that Triton's blocked layouts, MMA input/output layouts, sliced layouts, and swizzled memory layouts all fit this framework. It then formalizes distributed layouts as surjective maps from registers, threads, and warps to logical tensors, and memory layouts as invertible maps whose columns have one or two nonzero bits.

On top of that representation, Triton gets a generic layout engine. Anchor layouts are introduced where hardware or memory operations require them, then propagated through the IR. Shape operations such as `tt.trans`, `tt.reshape`, `tt.split`, `tt.join`, `tt.expand_dims`, and `tt.broadcast` become easier because the family of distributed layouts is closed under them, so the compiler can often propagate layouts rather than inserting explicit conversions. The paper also uses the matrix form to simplify utility questions that were previously heuristic, such as how many elements are contiguous per thread or which lanes hold broadcast duplicates.

The code-generation path is the strongest part. For shared-memory load/store and layout conversion, the compiler composes a distributed layout with the inverse of a memory layout and checks whether the resulting matrix can be factored by the tile shape required by a SIMD primitive. That lets Triton recognize when vectorized `ld.shared`/`st.shared`, `ldmatrix`, or `stmatrix` are legal. For intra-warp conversions, the paper derives a generic warp-shuffle schedule from the differing thread subspaces of the source and destination layouts. For shared-memory swizzles, it constructs a layout that maximizes vectorization while minimizing bank conflicts. The same machinery also improves mixed-precision matmul and `tl.gather` when accesses stay within a warp.

## Evaluation

The evaluation compares baseline Triton with a modified `Triton-Linear` across synthetic tests and 21 TritonBench kernels on `RTX4090`, `GH200`, and `MI250`. The most convincing evidence is correctness. In mixed-precision matrix multiplication, baseline Triton passes only `46.6%` of `784` enumerated cases, while Triton-Linear passes all of them. Broadcasting tests also cover layout families that legacy Triton simply could not support, including MMA-input-derived and custom layouts.

The microbenchmarks show where the gains come from. For load/store contiguity, Triton-Linear raises accessed bitwidth by as much as `7x`. In broadcasting-heavy reductions, shared-memory store counts fall by up to `76%`. In MXFP4 mixed-precision matmul, better layout handling yields up to `1.87x` speedup on GH200. Generic layout conversion via warp shuffles reaches up to `3.93x`, and gather improves by as much as `14.20x` when the relevant elements stay within one warp.

The real-benchmark story is smaller but still meaningful: across `265` TritonBench cases, the paper reports up to `1.40x` speedup and `1.07x` on average. The largest wins on GH200 appear in `int4_gemm`, `gemm`, and `flex_attention`, where the compiler can exploit `ldmatrix`, `stmatrix`, or remove equivalent-layout conversions. RTX4090 reaches up to `1.37x`, while MI250 improves only `1.00x-1.03x`, largely because AMD lacks some of NVIDIA's specialized primitives. That asymmetry is important: the abstraction is portable, but the payoff still depends on the hardware's primitive set.

Overall, the evaluation supports the main claim well. The paper clearly fixes real correctness failures and unlocks several concrete backend optimizations. What it does not do is compare against other compiler stacks such as TVM or XLA; the comparison is mostly new Triton versus old Triton.

## Novelty & Impact

Relative to _Tillet et al. (MAPL '19)_, the novelty is not Triton itself but replacing its informal backend layout algebra with a formal one. Relative to _Hagedorn et al. (ASPLOS '23)_ and _Ding et al. (ASPLOS '23)_, the contribution is narrower than a full tensor-compiler IR, but deeper on layout representation and conversion. Relative to hand-tuned kernels such as _Shah et al. (NeurIPS '25)_, its key move is to make warp-shuffle and swizzle tricks synthesizable by the compiler instead of manually engineered.

That gives the paper unusually high compiler-engineering impact. If adopted, it lowers the marginal cost of supporting new layouts, datatypes, and backend optimizations.

## Limitations

The main theoretical limitation is explicit: linear layouts assume power-of-two structure. The authors argue that larger tensors plus masking cover many non-power-of-two cases, but that is still a workaround rather than native support. They also note that flipping and some slicing patterns are not linear in the strict `y = Ax` sense, though affine layouts `y = Ax XOR b` would recover them.

Practically, the system is tailored to Triton's layout families rather than to every possible accelerator layout. The performance story is also strongest on NVIDIA parts with rich primitives such as `ldmatrix`; on MI250 the gains are much smaller. Finally, the evaluation mostly shows backend robustness and local kernel wins, not end-to-end model-level speedups.

## Related Work

- _Tillet et al. (MAPL '19)_ — Triton provides the compiler substrate; this paper effectively replaces Triton's hand-written layout logic with an algebraic one.
- _Hagedorn et al. (ASPLOS '23)_ — Graphene studies an IR for optimized GPU tensor computation, while Linear Layouts focuses specifically on representing and converting hardware-tensor mappings.
- _Ding et al. (ASPLOS '23)_ — Hidet's task mapping is about expressing tensor-program placement on GPUs, whereas Linear Layouts gives the compiler a first-class model for layout propagation and lowering.
- _Shah et al. (NeurIPS '25)_ — FlashAttention-3 uses manually engineered byte permutes and warp shuffles for data movement; Linear Layouts aims to synthesize comparable moves automatically.

## My Notes

<!-- empty; left for the human reader -->

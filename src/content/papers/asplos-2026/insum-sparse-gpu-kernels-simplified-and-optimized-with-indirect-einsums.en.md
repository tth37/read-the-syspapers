---
title: "Insum: Sparse GPU Kernels Simplified and Optimized with Indirect Einsums"
oneline: "Rewrites sparse GPU kernels as indirect einsums over fixed-length formats so PyTorch/Triton can emit fused Tensor Core code."
authors:
  - "Jaeyeon Won"
  - "Willow Ahrens"
  - "Saman Amarasinghe"
  - "Joel S. Emer"
affiliations:
  - "Massachusetts Institute of Technology, CSAIL, Cambridge, MA, USA"
  - "Georgia Institute of Technology, Atlanta, GA, USA"
  - "NVIDIA Architecture Research Group, Westford, MA, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790176"
code_url: "https://github.com/nullplay/IndirectEinsum"
tags:
  - compilers
  - gpu
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Insum rewrites sparse GPU kernels as indirect einsums over fixed-length sparse formats, so the backend sees gather, dense tensor algebra, and scatter rather than bespoke sparse control flow. The authors then extend TorchInductor to fuse that pipeline and lower the dense core to Tensor Cores. Across four sparse ML kernels, they report `1.14x-3.81x` speedups over hand-written baselines while shrinking implementations to one statement.

## Problem

The paper targets a mismatch between sparse abstractions and GPU-friendly execution. Prior sparse tensor compilers usually separate a format-agnostic Einsum from the storage format, then generate sparse-specific control flow for intersections or variable-length rows. That model fits CPU-oriented sparse-sparse kernels better than the sparse-dense GPU kernels common in ML, where the expensive part is the dense math after irregular gathers.

That gap is why high-performance sparse GPU code is still mostly hand-written. The paper cites about 2,000 lines for Sputnik and more than 4,000 for TorchSparse. Formats such as CSR also expose data-dependent loop bounds that dense compilers dislike. The practical problem is therefore to preserve sparse semantics while rewriting the computation into something regular enough that a dense GPU compiler can fuse and tensorize it.

## Key Insight

The central claim is that sparse GPU kernels become compiler-friendly once sparse metadata is made part of the tensor program itself. Insum rewrites a sparse computation into an indirect Einsum whose operands are dense tensors holding nonzero values and coordinate metadata. A COO SpMM, for instance, becomes a gather from `B`, a dense multiply-accumulate over `AV`, and a scatter into `C`.

That representation matters because it changes the backend's job. Instead of synthesizing bespoke sparse loops, the compiler only needs to optimize gather, dense tensor algebra, and scatter. If the sparse format also uses fixed-length groups, the whole kernel fits regular loop nests that existing dense GPU compilers already know how to tile, fuse, and map onto Tensor Cores.

## Design

The format side begins with COO, then fixes COO's two obvious problems: repeated coordinates and too many scatters. GroupCOO groups nonzeros along one dimension, stores the shared coordinate once, and pads within the group to get fixed-length loops. BlockGroupCOO adds dense blocks on top so the inner work becomes block matmul that naturally targets Tensor Cores. The authors choose group size by minimizing indirect accesses, because runtime tracks gather/scatter count better than raw format size.

The compiler side turns an indirect-Einsum string into a PyTorch FX graph that does three things: gather tensors for indirect reads, run the dense Einsum, and scatter or `index_add` the result back. The main obstacle is TorchInductor's default matmul template, which prevents fusion with surrounding irregular operations. Insum therefore adds an `ops.dot` IR node that lowers directly to Triton's `tl.dot`.

The second compiler change is "Lazy Broadcasting." Instead of eagerly expanding every loop index into its final tensor shape, the compiler delays broadcasting until a value is actually consumed. That removes reshapes and transposes around `tl.dot` and lets gather, matmul, and scatter stay in one fused Triton kernel.

## Evaluation

The evaluation covers four workloads: structured block-sparse SpMM, unstructured SpMM, point-cloud sparse convolution, and equivariant tensor products. The implementation is about 500 lines for Insum plus roughly 1,600 lines of TorchInductor changes. Table 1 reports `1.95x` over TorchBSR, `1.20x` over Sputnik, `1.14x` over TorchSparse, and `3.81x` over e3nn, while reducing code volume by `202x-4491x`.

The structured SpMM results are especially persuasive. Compared with dense matmul, the sparsity crossover where sparse becomes worthwhile shifts from about `40%` to `25%`, and the grouped COO-style format avoids the row-pointer overhead that hurts BCSR in hypersparse settings. For unstructured SpMM, Insum gets the best average result: about `1.2x` over cuSPARSE on FP32 and about `1.18x` on FP16.

The other two workloads show that the formulation is broader than SpMM. On point-cloud convolution, Insum beats both TorchSparse variants and looks even better on H100 because Triton can retune for Hopper. On equivariant tensor products, it is at least `2x` faster than e3nn in every reported setting and up to `8.3x` faster than cuequivariance.

The ablation study supports the mechanism. Grouping alone gives about `8x` over unfused COO by reducing redundant scatters and improving reuse; blocking enables Tensor Cores; native matmul plus lazy broadcasting add another `2.6x` over default PyTorch code generation by fusing gather, matmul, and scatter. The main weakness is compile-time cost: the point-cloud example needs `9.9s` of compilation plus `4.9s` of autotuning.

## Novelty & Impact

Relative to _Kjolstad et al. (OOPSLA '17)_, the novelty is not a new storage abstraction but the choice to encode sparse metadata back into indirect tensor programs. Relative to _Ye et al. (ASPLOS '23)_, the contribution is a more automatic path: one indirect einsum plus backend autotuning instead of large manual schedules. Relative to _Won et al. (MLSys '23)_, the paper generalizes beyond sparse convolution to a small family of sparse-dense GPU kernels.

## Limitations

The scope is narrower than "all sparse tensor programs." The approach works best for sparse-dense kernels; variable-length formats such as CSR do not fit directly and must be converted into grouped or padded representations first. Padding overhead also remains a real tradeoff if the chosen group size is poor.

The implementation depends on backend-specific changes to TorchInductor, including native `tl.dot` lowering and lazy broadcasting, so portability to other compiler stacks is not free. The experiments are also dominated by ML-style workloads on NVIDIA GPUs.

## Related Work

- _Kjolstad et al. (OOPSLA '17)_ — TACO separates computation from sparse storage, whereas Insum pushes metadata into indirect einsums.
- _Ye et al. (ASPLOS '23)_ — SparseTIR also reuses dense compiler infrastructure, but relies on more manual scheduling.
- _Won et al. (MLSys '23)_ — Unified Convolution Framework targets sparse convolution; Insum extends the recipe to SpMM and tensor products.
- _Ahrens et al. (OOPSLA '25)_ — Finch broadens sparse tensor programming, while Insum narrows in on Tensor-Core-friendly kernels.

## My Notes

<!-- empty; left for the human reader -->

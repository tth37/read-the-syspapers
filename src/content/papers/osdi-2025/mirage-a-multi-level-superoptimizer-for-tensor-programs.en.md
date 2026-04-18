---
title: "Mirage: A Multi-Level Superoptimizer for Tensor Programs"
oneline: "Mirage searches tensor programs across GPU kernel, block, and thread levels, then uses pruning and probabilistic verification to synthesize faster custom kernels."
authors:
  - "Mengdi Wu"
  - "Xinhao Cheng"
  - "Shengyu Liu"
  - "Chunan Shi"
  - "Jianan Ji"
  - "Man Kit Ao"
  - "Praveen Velliengiri"
  - "Xupeng Miao"
  - "Oded Padon"
  - "Zhihao Jia"
affiliations:
  - "Carnegie Mellon University"
  - "Peking University"
  - "Pennsylvania State University"
  - "Purdue University"
  - "Weizmann Institute of Science"
conference: osdi-2025
code_url: "https://github.com/mirage-project/mirage"
tags:
  - compilers
  - gpu
  - ml-systems
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Mirage is a superoptimizer for tensor programs that searches across GPU kernels, thread blocks, and threads instead of choosing from a fixed library of expert-written kernels. With `µGraphs`, abstract-expression pruning, and probabilistic equivalence checking, it synthesizes new fused kernels and beats strong baselines by up to 3.3x.

## Problem

Prior systems split the space the wrong way. Schedule optimizers such as Halide, TVM, Ansor, and Triton tune how to run a fixed algorithm, while algebraic optimizers such as TASO and PET rewrite graphs but still depend on expert-written kernels. Modern GPU wins often require all three decisions together: rewrite the algebra, change kernel boundaries, and change the block/thread mapping.

FlashAttention is the motivating example. Its gain comes from a new kernel structure, not just a better schedule for an existing operator. Existing automated tools cannot discover that joint transformation space, so experts still hand-write large Triton or CUDA kernels for common DNN and LLM operators.

## Key Insight

Mirage's core idea is to optimize one hierarchical object rather than separate IRs. A `µGraph` represents the computation at kernel, block, and thread levels, so algebraic rewrites, schedule choices, and kernel synthesis all become transformations on the same graph.

That is tractable because Mirage prunes aggressively with abstract expressions and verifies only the `LAX` fragment exactly. For multilinear operators plus division and limited exponentiation, finite-field random testing gives theorem-backed error bounds.

## Design

At the top, a kernel graph connects device-memory tensors. Nodes can be library kernels or graph-defined kernels that expand into block graphs. Block graphs live in shared memory and use `imap`, `omap`, `fmap`, loop dimensions, and accumulators to describe tiling and cross-iteration reduction. Thread graphs live in registers and fuse short elementwise sequences.

The RMSNorm plus MatMul case study shows why this helps. Mirage discovers one custom kernel that reorders the RMSNorm division with MatMul, overlaps the RMS and MatMul accumulations, and keeps the final elementwise work in registers. That generated `µGraph` beats handwritten kernels by 1.5x on A100 and 1.9x on H100.

Search is exhaustive at the kernel and block levels up to bounded size, but rule-based at the thread level. The key pruning mechanism maps each edge to an abstract expression built from `sum`, `mul`, `div`, `exp`, and `sqrt`, then asks Z3 whether the current prefix can still be a subexpression of the target computation. The axioms intentionally omit cancellation rules so pruning stays effective.

Candidates that survive pruning are verified probabilistically on two finite fields, one used inside exponentiation and one outside it. After correctness is established, Mirage still optimizes layouts with an ILP, orders operators by depth to reduce `__syncthreads()`, and searches memory plans for buffer reuse.

## Evaluation

Mirage is implemented in about 30K lines of C++, CUDA, and Python on top of cuDNN, cuBLAS, CUTLASS, PTX, and Z3. On A100 and H100, it compares against TASO/PET, PyTorch with `torch.compile` and FlashAttention, TensorRT/TensorRT-LLM, FlashAttention/FlashDecoding, and Triton on GQA, QKNorm, RMSNorm, LoRA, GatedMLP, and nTrans. The headline result is up to 3.3x over the best baseline.

The case studies are concrete. Mirage gets up to 2.2x on GQA by choosing better grid dimensions and tensor-dimension parallelization than fixed heuristics. It fuses QKNorm into attention for up to 1.4x, rewrites LoRA into a concatenation-based fused kernel for 1.1-2.4x, and executes the two GatedMLP MatMuls in parallel inside one block graph for 1.5-3.3x. nTrans is the main negative result: TensorRT stays faster because Mirage's current graph-defined kernels always stage through shared memory, which is too expensive for light kernels.

The paper also shows system-level relevance. In PyTorch, Mirage-generated kernels improve end-to-end latency by up to 1.9x on Chameleon-7B, LLaMA-3-8B, GPT-3-7B-LoRA, and nGPT-1B, though one GPT-3-7B-LoRA point is slightly worse than baseline. Search is offline and can take up to four hours, but abstract-expression pruning is what makes the system workable: on the RMSNorm search, the same 11-operator block-graph budget drops from more than 10 hours to 28 seconds.

## Novelty & Impact

Relative to _Jia et al. (SOSP '19)_ and _Wang et al. (OSDI '21)_, Mirage expands superoptimization beyond kernel-level graph rewrites. Relative to Triton-style schedule search and _Shi et al. (OSDI '23)_, it treats scheduling as only one dimension inside a larger hierarchical search. The contribution is therefore a new mechanism, not just a stronger benchmark sheet.

The likely impact is on tensor compilers and LLM runtime stacks. Mirage argues that future systems should synthesize kernels from hierarchical IRs with correctness checks instead of growing ever larger libraries of hand-written fused kernels.

## Limitations

The verifier with the strongest guarantees only covers the `LAX` fragment, and the implementation used during search is weaker than the full theorem: it uses small primes (`p=227`, `q=113`) and a single random test, with a stronger final pass left to future work. The pruning axioms also omit cancellation, so some equivalent `µGraphs` are never explored.

Search is still expensive, adding new operators requires new floating-point, modular-arithmetic, and abstraction support, and the shared-memory-first code generation can lose on light kernels, as nTrans shows.

## Related Work

- _Jia et al. (SOSP '19)_ - TASO performs kernel-level algebraic substitutions, while Mirage searches across kernel, block, and thread levels and can synthesize new custom kernels.
- _Wang et al. (OSDI '21)_ - PET adds partially equivalent transformations with automated correction, but it still operates at the kernel level rather than on a hierarchical GPU representation.
- _Tillet et al. (MAPL '19)_ - Triton is a strong schedule optimizer for user-provided kernels, whereas Mirage also searches over algebraic structure and kernel boundaries.
- _Shi et al. (OSDI '23)_ - Welder uses a multi-level representation to improve scheduling and memory access, while Mirage extends the idea to superoptimization and correctness verification.

## My Notes

<!-- empty; left for the human reader -->

---
title: "FuseFlow: A Fusion-Centric Compilation Framework for Sparse Deep Learning on Streaming Dataflow"
oneline: "FuseFlow compiles sparse PyTorch models into fused SAMML graphs, exposing fusion granularity and dataflow order instead of assuming maximal fusion is always best."
authors:
  - "Rubens Lacouture"
  - "Nathan Zhang"
  - "Ritvik Sharma"
  - "Marco Siracusa"
  - "Fredrik Kjolstad"
  - "Kunle Olukotun"
  - "Olivia Hsu"
affiliations:
  - "Stanford University, Stanford, USA"
  - "SambaNova Systems, Inc., Palo Alto, USA"
  - "Barcelona Supercomputing Center, Barcelona, Spain"
  - "Carnegie Mellon University, Pittsburgh, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790165"
tags:
  - compilers
  - hardware
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

FuseFlow is a compiler stack for sparse deep learning on reconfigurable streaming-dataflow accelerators. Its key move is to make cross-expression fusion a first-class scheduling choice rather than a side effect of lowering one kernel at a time, using a partial-order-graph-based fusion algorithm and a new "fusion table" IR to emit factored-iteration SAMML graphs. Across GCN, GraphSAGE, sparse autoencoders, and GPT-3 with BigBird attention, the paper shows meaningful gains, but also that full end-to-end fusion is not universally optimal for sparse models.

## Problem

The paper starts from a mismatch between emerging hardware and existing compiler support. Sparse deep learning increasingly relies on specialized accelerators and dataflow architectures because sparsity lowers arithmetic and memory demand but creates irregular access patterns that GPUs handle poorly. The authors illustrate that point with PyTorch Geometric GCN inference on an RTX 5090, where average SM utilization is only 16.7% and memory utilization is around 1%, suggesting that conventional architectures leave a great deal of efficiency untapped.

Prior sparse-dataflow compiler work, especially SAM/Custard, can lower a single sparse tensor algebra expression to a dataflow graph, but that is not yet a usable compilation story for whole ML models. Modern models have sequences of kernels, nonlinearities, masking, and reshape-like boundaries where the best implementation depends on how much intermediate state is materialized versus recomputed. Existing sparse compilers either stop at one expression, fuse only known operator templates, or assume one fixed notion of "more fusion is better." For sparse ML, that assumption breaks: excessive fusion can amplify coordinate-processing costs or nested recomputation, while too little fusion spills intermediates and increases memory traffic.

So the systems problem is twofold. First, how can a compiler fuse across multiple sparse expressions without violating each tensor's storage-order constraints? Second, how can it lower that fused program to a streaming dataflow machine without collapsing into an inefficient global iteration space? FuseFlow is proposed as the first sparse compiler that tackles both issues together for end-to-end sparse DL inference pipelines.

## Key Insight

The paper's central insight is that sparse fusion should be expressed as a constrained global ordering problem, then lowered into a factored iteration plan rather than a fully materialized global loop nest. Once multiple sparse expressions are fused, each tensor view brings its own required traversal order from its storage format, and each local kernel may impose an additional user-chosen dataflow order. FuseFlow captures those requirements in a partial order graph (POG), so "can these kernels be fused?" becomes "does there exist a concordant topological order that respects all mode-order and producer-consumer constraints?"

That insight matters because it separates correctness from aggressiveness. FuseFlow can fuse across expressions when the POG stays acyclic, share equivalent tensor views, and fall back to materializing a permuted copy only when conflicting views make a concordant order impossible. Then, instead of emitting one globally fused sparse iteration space, it lowers the fused program into factored subspaces that interleave input iteration and computation. The proposition the reader should remember is that sparse ML fusion pays off when the compiler preserves sparse-format constraints while keeping coordinate processing local, not when it blindly maximizes fusion depth.

## Design

FuseFlow begins from PyTorch lowered through Torch-MLIR or MPACT into MLIR's `Linalg + SparseTensor` dialects. The input model may contain sparse tensors from any source, including graph adjacency, pruned weights, or masked activations, as long as the sparse structure type is known before compilation. Users can annotate sparse formats and mark fusion regions explicitly with `Fuse{}` schedules; they can also control dataflow order, parallelization, and related knobs.

The first main mechanism is the cross-expression fusion algorithm. For each expression inside a fusion region, FuseFlow renames local reduction indices, turns repeated tensor uses into distinct tensor views, and inserts mode-order and dataflow-order constraints into the POG. Producer outputs are then inlined into consumer expressions. If multiple views are equivalent, they are merged; if they induce cycles, the compiler breaks the conflict by materializing a transposed view. A topological sort of the final POG yields valid fused dataflow orders.

The second main mechanism is the fusion table IR. This is the paper's most novel lowering device. Rows encode fused iteration order, columns encode tensor views and intermediate expressions, and cells either instantiate SAMML primitives or reference future streams by name. That indirection is important because dataflow graphs need spatial wiring, not just loop transformations: later computations may need to point to streams that have not yet been materialized. Fusion tables let FuseFlow defer graph construction, move cells to create intersects/unions and higher-order reductions, and ultimately emit SAMML graphs whose input-iteration and compute regions are interleaved in a factored style.

Around those two mechanisms, the implementation adds the optimizations needed to make the compiler practical: user-guided parallelization via stream duplication and merging, sparsity blocking for block-sparse tensors such as BigBird attention, dataflow-order enumeration, and a fast heuristic that estimates FLOPs and bytes to prune poor schedules before cycle-accurate simulation.

## Evaluation

The evaluation covers four sparse model classes: 3-layer sparse autoencoders, 2-layer GCN, 2-layer GraphSAGE, and GPT-3 Small with BigBird attention at sequence length 1024. Datasets span 50% to 99.9% sparsity and include both lossless input sparsity and lossy weight or mask sparsity. The implementation compiles all evaluated models in under 750 ms, then targets Comal, a cycle-accurate simulator backed by Ramulator 2.0 for HBM2 modeling. To check that this is not merely a simulator artifact, the authors also compare selected kernels against FPGA RTL generated through Vitis HLS and report strong agreement with `R^2 = 0.991`.

The core fusion results are nuanced and therefore credible. GPT-3 with BigBird benefits most from full fusion, reaching about `2.7x` speedup. GCN and GraphSAGE do not: for them, partial fusion is best, yielding up to `2.6x` on OGB-Collab and `3.9x` on OGB-MAG, while full fusion loses performance because nested sparse matrix multiplications increase recomputation overhead. Sparse autoencoders behave differently again: full fusion reaches `1.94x`, but partial fusion does almost nothing because the dominant sparse matrix multiply in each layer already swamps the smaller follow-on operators. That directly supports the paper's headline claim that fusion granularity is model dependent.

The comparison against prior sparse dataflow compilers is also well chosen. On GCN over OGB-Collab, handwritten rewrites for Custard/Stardust-style compilation obtain `1.97x` over the unfused baseline, while FuseFlow reaches `2.63x`, an additional `1.33x` beyond that manually rewritten version. The paper attributes the gain to automatic cross-expression fusion and to factored iteration reducing coordinate overhead. The heuristic is reasonably accurate too, with average FLOP error of `1.8%-2.8%` and byte error of `5.7%-11.5%` on the reported workloads, which is good enough for pruning. My main reservation is scope: the workloads are diverse, but the paper still evaluates inference-centric pipelines and simulator-backed accelerators rather than a deployed end-to-end hardware stack.

## Novelty & Impact

Relative to _Hsu et al. (ASPLOS '23)_, FuseFlow's main novelty is moving from single-expression SAM lowering to general cross-expression fusion for sparse ML programs, then pairing that with a lowering strategy that deliberately emits factored iteration instead of global iteration. Relative to CPU/GPU sparse compilers such as ReACT, the paper contributes both a new constrained-fusion formulation and a path to streaming dataflow hardware. Relative to accelerator modeling work, its contribution is executable compilation, not just performance analysis.

That gives the paper real impact potential in two communities. Sparse-compiler researchers can cite it as the first credible attempt to make fusion granularity a first-class scheduling dimension for sparse dataflow programs. Accelerator architects can cite it because it clarifies that hardware-friendly sparse fusion depends on compiler support for tensor-view ordering, not only on new functional units. The paper feels like a new mechanism rather than a measurement study or a simple repackaging of existing fusion tricks.

## Limitations

FuseFlow depends on the sparse structure type being known before compilation, so it is not a solution for workloads whose sparsity format itself changes unpredictably at runtime. It also asks the user to mark fusion regions and expose scheduling intent; the authors mention autoscheduling only as future work, which means the current interface is powerful but expert-oriented.

On the performance side, the paper is honest that full fusion can hurt. That is a strength scientifically, but it also means deployment requires schedule exploration instead of one default recipe. The heuristic helps prune the search space, yet even the constrained dataflow-order space can still be large. Finally, the hardware story is partial: the simulator is carefully validated, but end-to-end sparse ML support on real accelerators is still immature, and some supporting infrastructure such as nonlinear and masking-capable hardware backends remains a moving target.

## Related Work

- _Hsu et al. (ASPLOS '23)_ — SAM/Custard lowers single sparse tensor expressions to dataflow graphs; FuseFlow keeps that substrate but adds multi-expression fusion and ML-specific operators.
- _Hsu et al. (CGO '25)_ — Stardust targets sparse dataflow hardware from higher-level tensor algebra, but still stops at single expressions instead of full sparse ML pipelines.
- _Zhou et al. (PACT '22)_ — ReACT also generates factored iteration code and attacks redundancy in sparse tensor algebra, but it targets CPU/GPU-style execution and does not fuse independent expressions for dataflow hardware.
- _Nayak et al. (MICRO '23)_ — TeAAL models cascaded Einsums and sparse accelerators declaratively; FuseFlow instead compiles those fused computations into executable SAMML graphs.

## My Notes

<!-- empty; left for the human reader -->

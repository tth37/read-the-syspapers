---
title: "SpaceFusion: Advanced Deep Learning Operator Fusion via Space-Mapping Graph"
oneline: "SpaceFusion models nested operator dependencies as a space-mapping graph, then slices the fused space to synthesize GPU fusion schedules beyond fixed hand-written kernels."
authors:
  - "Liang Zhu"
  - "Jianguo Yao"
  - "Haibing Guan"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696087"
tags:
  - ml-systems
  - compilers
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SpaceFusion targets operator fusion cases where the hard part is not deciding that two operators should fuse, but finding a schedule that respects nested reductions and still uses the GPU memory hierarchy well. It introduces a middle-granularity abstraction, the Space-Mapping Graph (SMG), plus spatial and temporal slicers that turn one fused dependency space into parallel blocks and serial intra-block fragments. On V100, A100, and H100 GPUs, the paper reports up to 10.35x subgraph speedup and up to 8.79x end-to-end speedup over HuggingFace PyTorch, while reaching up to 2.21x over FlashAttention-powered hand-tuned inference stacks.

## Problem

The paper starts from a real limitation in deep-learning compilers: graph-level fusion abstractions are good at element-wise cleanup, but they mostly stop at operator boundaries, so they cannot reason about the internal dependency structure of GEMM, Softmax, LayerNorm, or similar operators. Low-level models such as Halide-style loop IRs or polyhedral representations do preserve that information, but the search space becomes too large for practical operator-fusion scheduling.

That gap matters most for fused kernels like Multi-Head Attention. The paper's MHA example has deeply nested and wide dependencies: one output element depends on `(2LK + 4K + 2)` elements from eight tensors, with six layers of nesting, six One-to-All mappings, and four All-to-One mappings. A naive fusion schedule that simply aligns intermediate tiles either creates poor intra-block locality or exceeds shared-memory limits. The core problem is therefore to preserve enough dependency structure to transform the computation, while still searching a manageable schedule space under GPU register and shared-memory constraints.

## Key Insight

The central claim is that operator fusion needs an abstraction between graph nodes and loop nests: rich enough to encode dependency direction and reduction structure, but coarse enough to analyze and schedule holistically. SpaceFusion's SMG does this by representing both data spaces and iteration spaces as geometric nodes, and by labeling edges with the dependency type and direction: One-to-One, One-to-All, or All-to-One.

Once dependencies are expressed that way, scheduling becomes a slicing problem instead of a monolithic search problem. Some dimensions can be cut spatially into independent SMG blocks for thread-block parallelism; others can be cut temporally into serial intra-blocks that reuse on-chip storage. The paper's insight is that the missing ingredient in prior auto-fusion systems is not more brute-force search, but a representation that exposes which dependency transformations are legal and profitable.

## Design

SpaceFusion builds an SMG for each operator, then connects multiple operator SMGs by aligning intermediate spaces across dimensions. That is how it turns a chain such as GEMM plus Softmax plus GEMM into one fused optimization space rather than a sequence of pairwise decisions. Compared with a normal dataflow graph, SMG adds dimensional information to nodes, makes iteration spaces explicit, and decouples dependencies into typed directional mappings.

The spatial slicer exploits only dimensions whose cuts do not introduce cross-block flow dependencies. In practice that means it is willing to slice input One-to-All mappings, because kernel inputs live in global memory and are visible to every block, but it avoids slicing mappings that would make one block depend on another. The result is a set of independent SMG blocks that can be mapped to GPU thread blocks.

The temporal slicer handles the opposite tradeoff: it serializes part of an SMG block into multiple intra-block stages so the same shared memory and registers can be reused. This is straightforward for independent reductions, but MHA-style pipelines contain chains of dependent reductions. SpaceFusion addresses that with `Update then Aggregate` (UTA). It first performs broadcast postposition to expose the shortest dependency paths between reductions, then synthesizes update functions such as `updateSum` and `updateOut` so an older partial result is corrected before it is aggregated with the current slice. Resource-aware auto-scheduling first tries spatial slicing, then temporal slicing, bounds candidate block sizes by shared-memory and register budgets, and if the fused SMG is still too large, partitions it into smaller sub-SMGs and retries. Triton is used as the backend for intra-block code generation.

## Evaluation

The evaluation covers three NVIDIA generations, V100, A100, and H100, with CUDA 12.2 and FP16 Tensor Core execution. The subgraph benchmarks are broad enough to show that the method is not only about attention: for fused MLP stacks, SpaceFusion reaches up to 3.15x speedup and 2.35x on average over cuBLASLt; for a simplified LSTM cell, up to 2.87x and 2.29x on average over cuBLAS; for LayerNorm, 7.25x on average over PyTorch and up to 4.03x over a hand-written Triton implementation; and for MHA, up to 10.35x and 5.40x on average over PyTorch, with performance comparable to FlashAttention 2.

The end-to-end results are stronger because they include both hand-tuned libraries and other DL compilers. Across Bert, Albert, T5, ViT, and Llama2-7B inference, SpaceFusion delivers up to 8.79x speedup and 3.54x on average over HuggingFace PyTorch, plus average speedups of 1.27x over TensorRT, 1.34x over Kernl, 2.27x over BladeDISC, and 1.21x over NNFusion on Volta. The memory analysis supports the mechanism: compared with fused or unfused baselines, it reports up to 83.0% fewer L1 cache misses, 94.1% fewer L2 misses, and 96.45% less device-memory traffic. The evaluation is reasonably fair because it compares against the strongest available baseline for each subgraph and also includes end-to-end systems, though some compiler baselines are missing on some architectures and the best comparator changes by workload.

## Novelty & Impact

The novelty is not just a new search heuristic. Welder's tile-graph gives fine-grained inter-operator tile stitching but leaves intra-operator dependencies implicit; AStitch broadens fusion for memory-intensive operators; Chimera focuses on compute-intensive ones. SpaceFusion's contribution is to give one abstraction that spans both compute-intensive and memory-intensive fusion and to make dependency transformation part of the scheduler rather than a one-off hand optimization.

That makes the paper important for DL compilers that want broader fusion coverage without writing one bespoke kernel per workload. The paper reports that SpaceFusion discovers 50 distinct fusion patterns in its compiled workloads, versus 30 for NNFusion and 14 for BladeDISC. It also keeps compilation manageable: for example, the auto-scheduling part of MHA takes only milliseconds, while the search space for MHA `(32,1024)` is fully tuned in 33.04 seconds, and complete model compilation is 68.4 seconds for Bert, 76.9 seconds for ViT, and 131.7 seconds for T5.

## Limitations

The paper's scope is narrower than the headline might suggest. It explicitly focuses on globally ranged mappings and does not tackle partially ranged cases such as 2D convolution fusion, so this is not a universal fusion abstraction. The implementation and measurements are also NVIDIA-only and FP16-centric, so the paper does not show whether the same scheduling logic transfers cleanly to other accelerators or precision regimes.

The method also relies on algebraic simplification opportunities. Broadcast postposition is necessary before UTA can expose reduction dependencies, but the paper notes that not every dependent All-to-One chain simplifies under those rules. Finally, most of the compilation time still sits in tuning rather than analysis, and the performance gains are smaller for workloads like Llama2 where large head counts and large weight tensors already give the baseline substantial parallelism and unavoidable weight traffic.

## Related Work

- _Shi et al. (OSDI '23)_ - Welder uses a tile-graph to stitch intermediate tiles across operators, but it does not model intra-operator dependencies well enough to perform the reduction transformations SpaceFusion relies on.
- _Zheng et al. (ASPLOS '22)_ - AStitch expands the search space for memory-intensive operator fusion, whereas SpaceFusion also targets compute-intensive operators and mixed CI/MI fused subgraphs.
- _Zheng et al. (HPCA '23)_ - Chimera analytically optimizes compute-intensive operator fusion, while SpaceFusion aims for a broader abstraction that also covers dependency-heavy mixed pipelines such as MHA.
- _Dao et al. (NeurIPS '22)_ - FlashAttention is a hand-designed MHA kernel with equivalent attention math, whereas SpaceFusion tries to synthesize comparable schedules automatically and for more than one pattern.

## My Notes

<!-- empty; left for the human reader -->

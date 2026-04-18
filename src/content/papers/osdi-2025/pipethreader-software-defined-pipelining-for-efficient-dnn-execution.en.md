---
title: "PipeThreader: Software-Defined Pipelining for Efficient DNN Execution"
oneline: "PipeThreader turns fused DNN kernels into sTask graphs and software-schedules TMA, TensorCore, and CUDA-core pipelines to match or beat hand-tuned kernels."
authors:
  - "Yu Cheng"
  - "Lei Wang"
  - "Yining Shi"
  - "Yuqing Xia"
  - "Lingxiao Ma"
  - "Jilong Xue"
  - "Yang Wang"
  - "Zhiwen Mo"
  - "Feiyang Chen"
  - "Fan Yang"
  - "Mao Yang"
  - "Zhi Yang"
affiliations:
  - "School of Computer Science, Peking University"
  - "Microsoft Research"
  - "Imperial College London"
  - "Shanghai Jiao Tong University"
conference: osdi-2025
code_url: "https://github.com/tile-ai/tilelang"
tags:
  - ml-systems
  - gpu
  - compilers
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

PipeThreader moves pipelined scheduling for fused DNN kernels out of opaque GPU hardware behavior and into the compiler. It represents a kernel as a graph of specialized tile tasks, maps those tasks onto TMA, TensorCore, and CUDA-core sub-units, and jointly searches tiling plus execution order. That is enough to recover FlashAttention-like schedules automatically and to beat prior compiler or hand-tuned baselines on several Mamba2 and attention workloads.

## Problem

Modern GPUs are no longer collections of interchangeable cores. Inside one H100 SM, TensorCores, CUDA cores, and TMA engines have different roles, different async properties, and different bottlenecks. At the same time, high-performance DNN kernels increasingly fuse many stages together, so performance depends on overlapping loads, matrix multiplies, reductions, rescaling, and data movement instead of just choosing a good tile size. Existing DNN compilers mostly expose homogeneous execution units and spatial tiling, which means they can express data parallelism across SMs but not fine-grained pipeline order within an SM. The result is under-utilization on modern hardware and a growing reliance on large, hardware-specific handwritten kernels such as FlashAttention.

## Key Insight

The core claim is that tile-level GPU execution is predictable enough that pipelining should be scheduled explicitly in software, not left to implicit hardware heuristics. PipeThreader makes this possible with two abstractions. An sTask-graph breaks a fused operator into fine-grained tasks such as `load`, `mma`, `softmax`, `exp`, or `rescale` over tiles, while specialized execution units (sEUs) model the heterogeneous engines inside each SM. Once the compiler reasons about both task dependencies and hardware heterogeneity, it can jointly choose reduction tiling and pipeline order instead of optimizing them in isolation.

## Design

PipeThreader starts from a DNN operator graph or a small sTask IR and converts the computation into an sTask-graph. The important choice is that it partitions not only spatial dimensions, as prior tile compilers do, but also reduction dimensions. That extra partitioning exposes work from adjacent loop iterations that can overlap in time. In the Mamba2 ChunkScan example, the compiler turns one fused loop body into separate `load_cb`, `load_dA`, `load_dt`, `exp`, `load_x`, and `mma` sTasks, then explores different ways to interleave them.

The hardware model is equally explicit. PipeThreader treats each SM-like unit as an EU and the heterogeneous engines inside it as sEUs. On H100, the relevant sEUs are TMA for bulk copies, TensorCores for matrix multiply-accumulate, and CUDA cores for scalar or reduction-style work. A candidate schedule is encoded as an sProgram: an ordered per-sEU task table plus barrier tasks that preserve dependencies.

Three primitives define the scheduling mechanism. `Append` places an sTask on a specific sEU. `Wait` inserts synchronization before a task. `Propagate` infers legal tile shapes backward from a chosen output tile through the rest of the graph. With these pieces, PipeThreader does two-level scheduling: inter-EU scheduling partitions work across homogeneous EUs in SPMD style, while intra-EU scheduling greedily orders ready tasks on heterogeneous sEUs using profiler feedback. The scheduler prefers asynchronous tasks that unlock downstream work, checks local-memory feasibility, and balances the tension between larger tiles and deeper overlap. The paper’s Mamba2 example captures this well: a decoupled optimizer chooses a larger tile and runs in 12.150 ms, while PipeThreader’s joint optimizer chooses a smaller 64x64 tile that pipelines better and cuts latency to 6.981 ms.

The implementation fills in the device details automatically. It infers layouts so connected sTasks agree on memory layout and thread binding, lowers TensorCore work through CUTLASS/CuTe-style templates, uses `cp.async.bulk` and `wgmma.mma_async` on H100, and applies warp specialization so producer warps handle TMA loads while consumer warps run compute stages. The authors emphasize that this keeps the user-facing kernel description short: their FlashAttention kernel needs 68 lines of Python versus 840 lines of handwritten CUDA in FlashAttention-3.

## Evaluation

The evaluation covers operator microbenchmarks and end-to-end inference on NVIDIA H100 and AMD MI300X. The pattern is consistent: PipeThreader helps more as the pipeline gets deeper. On H100, standard MatMul improves by 1.24x over PyTorch, 1.13x over Triton, and 2.07x over Ladder. Those are solid but not transformative gains. The bigger wins come from kernels with more stages. Low-bit MatMul is 3.92x faster than PyTorch with bitsandbytes and 2.48x faster than Ladder. FlashAttention averages 1.36x over Triton and 1.07x over FlashAttention-3. For Mamba2, ChunkScan and ChunkState average 1.71x and 1.98x over Triton, and Triton fails on some long-sequence cases.

The end-to-end story is also strong. For FP16 LLaMA3-8B and LLaMA3-70B on H100, PipeThreader averages 2.17x over Ladder and 2.45x over ONNXRuntime, while still beating PyTorch-Inductor, TensorRT, and vLLM by 1.79x, 1.28x, and 1.10x on average. On Mamba2-1.3B it beats PyTorch-Inductor by 1.92x and Ladder by 45.93x, largely because the baselines struggle with fused linear attention. The portability result matters too: on MI300X, the compiler still reports 1.16x-5.42x gains over Triton across operators and meaningful end-to-end wins over PyTorch-Inductor, ONNXRuntime, and Ladder. The evaluation therefore supports the central claim that compiler-controlled pipelining is useful across vendors, not only on one NVIDIA path.

The main caveat is methodological. Large-model LLM results use a single decoder layer as a proxy for whole-model inference because of GPU memory limits, and some of the largest Mamba2 wins come from baseline failures rather than from clean head-to-head competition between equally mature kernels.

## Novelty & Impact

Relative to _Ma et al. (OSDI '20)_ and _Zhu et al. (OSDI '22)_, PipeThreader is less about better homogeneous tiling and more about making heterogeneous pipeline stages first-class compiler objects. Relative to _Shi et al. (OSDI '23)_ and _Wang et al. (OSDI '24)_, it extends tile-centric compilation from memory optimization and low-precision transformation to joint scheduling across TMA, TensorCore, and CUDA-core work. That is the paper’s real contribution: not a single new kernel trick, but a compiler abstraction that can synthesize expert-style pipelines for multiple patterns and multiple GPUs with much less manual effort.

## Limitations

The evidence is strongest for single-GPU inference. Multi-GPU overlap, TPU-like devices, and grouped MatMul for MoE are discussed as natural extensions, but they are not implemented in this paper. Some headline results also benefit from the fact that existing systems do not support or fail on newer operators, especially Mamba2, so the gap is partly about ecosystem maturity. Finally, the search space is not free: PipeThreader reports 5.26 minutes of compilation time for one FlashAttention case on H100, versus 0.74 minutes for Triton.

## Related Work

- _Ma et al. (OSDI '20)_ — Rammer introduces rTasks for holistic DNN compilation, but still assumes homogeneous execution units rather than pipeline scheduling across heterogeneous sub-units.
- _Zhu et al. (OSDI '22)_ — Roller optimizes tensor compilation around tile-level spatial mappings, whereas PipeThreader adds reduction tiling and explicit per-unit pipeline order.
- _Shi et al. (OSDI '23)_ — Welder focuses on memory-access optimization via tile graphs and vertical fusion; PipeThreader instead asks how those fused stages should overlap on TMA, TensorCore, and CUDA cores.
- _Wang et al. (OSDI '24)_ — Ladder transforms tensor programs for efficient low-precision execution, while PipeThreader treats scheduling itself as the optimization target and searches directly over sPrograms.

## My Notes

<!-- empty; left for the human reader -->

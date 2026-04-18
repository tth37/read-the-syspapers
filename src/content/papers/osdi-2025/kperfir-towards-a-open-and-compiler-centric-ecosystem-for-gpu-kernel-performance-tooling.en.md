---
title: "KPerfIR: Towards an Open and Compiler-centric Ecosystem for GPU Kernel Performance Tooling on Modern AI Workloads"
oneline: "KPerfIR turns GPU kernel profiling into Triton IR passes, preserving loop and region semantics so tools can explain overlap bottlenecks and guide FA3 optimizations."
authors:
  - "Yue Guan"
  - "Yuanwei Fang"
  - "Keren Zhou"
  - "Corbin Robeck"
  - "Manman Ren"
  - "Zhongkai Yu"
  - "Yufei Ding"
  - "Adnan Aziz"
affiliations:
  - "University of California, San Diego"
  - "Meta"
  - "George Mason University"
  - "OpenAI"
conference: osdi-2025
code_url: "https://github.com/triton-lang/triton/tree/main/third_party/proton/dialect"
tags:
  - gpu
  - compilers
  - observability
category: ml-compilers-and-gpu-kernels
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

KPerfIR makes GPU profiling a first-class compiler concern instead of an external post hoc tool. It adds profiling operations to Triton's IR stack, lowers them into backend-specific counter reads and buffer stores, and uses that structure to build reusable tools such as a region-based timing profiler. The paper shows that this is accurate enough to guide real kernel changes, including a faster FlashAttention-3 implementation.

## Problem

The paper starts from a mismatch between modern AI compilers and modern GPU profilers. Compilers such as Triton now expose high-level scheduling structure, software pipelining, warp specialization, and backend-specific features like Tensor Cores and TMA. But the dominant profiling tools still mostly see the world as kernels plus counters. They can report aggregate utilization or instruction stalls, yet they do not retain enough compiler semantics to answer the questions kernel developers actually care about: which loop stage is stalling, which warp role is on the critical path, or which region boundary should a compiler pass move.

That gap matters because AI kernels increasingly depend on delicate intra-kernel overlap. The paper uses FlashAttention-3 as the running example: different warp groups load K and V tiles, launch GEMMs, and execute softmax with asynchronous barriers between them. Traditional profilers can tell the user that time is being spent, but not how the overlap evolves across iterations or how to connect a timing anomaly back to TTIR or TTGIR structure. The same disconnect also hurts compiler automation. If performance feedback lives outside the compiler, then autotuners and optimization passes need awkward side channels to correlate a metric with a concrete transformation.

## Key Insight

The central claim is that performance tooling should live inside the compiler's IR ecosystem, not beside it. KPerfIR treats profiling regions as explicit IR markers, then lowers those markers through Triton's multi-level pipeline into concrete hardware-counter reads, storage, and runtime decoding. Because the tool starts from IR rather than binary code, it preserves semantic context such as loops, regions, warp-group roles, and backend-independent structure long enough for both humans and compiler passes to reason about it.

That changes the role of a profiler. Instead of a fixed external utility, a profiling tool becomes another compiler pass with programmable semantics. Users can define custom regions, compilers can insert them automatically, and the same abstraction can be reused across Nvidia and AMD backends. The paper argues that this compiler-centric design simultaneously enables richer measurements, easier composition with compiler optimizations, and better portability than ad hoc toolchains.

## Design

KPerfIR is organized as a multi-level instrumentation stack inside Triton. At the highest level, the KPerfIR dialect introduces `RecordOp`, which marks the start or end of a named profiling region without committing to a specific metric or storage policy. Lowering then converts those abstract markers into KPerfGPUIR operations such as `ReadCounterOp`, `StoreCounterOp`, `InitOp`, and `FinalizeOp`, plus allocation operations for local, shared, global, or stack storage. Pass options choose the metric type, profiling granularity, buffer strategy, and storage placement, so one IR interface can back several tools.

This split is deliberate. Instrumenting at MLIR level preserves access to loops, region structure, and data objects, but it is too early to know exact low-level behavior. Instrumenting only at LLVM would improve fidelity but lose the connection to the original program structure. KPerfIR therefore spans both: it inserts semantic markers at TTIR or TTGIR, lowers them to GPU-oriented profiling ops, and finally lowers those ops to LLVM IR and backend code. The runtime patches the kernel signature with an extra profiling-memory argument, decodes the returned records on the host, and exposes command-line and Python APIs so users or compiler passes can apply and remove instrumentation.

The paper's concrete demonstration is a region-based timing tool for intra-kernel overlap. Each profiling region emits compact 8-byte start and end records into per-warp-group shared-memory buffers. Because long traces do not fit in the small leftover shared-memory budget of real kernels, the tool uses circular buffers and keeps the trace tail. The subtle part is trace replay: asynchronous instructions make naive timing misleading because the instrumentation itself perturbs barrier wait time. KPerfIR compensates by placing multiple markers around asynchronous issue and wait points, then subtracting the bookkeeping overhead in post-processing to reconstruct more faithful execution intervals.

## Evaluation

The evaluation runs on Nvidia H100-HBM3 and AMD MI300X systems with Triton 3.0.0 and LLVM 19.1. At a high level, the tool is lightweight enough to be practical: the abstract reports 8.2% average overhead and about 2% relative error, and the detailed measurements show end-to-end latency overhead below 10% for most kernels and below 15% in the worst benchmarked case. At the instruction level, one record costs about 33 cycles on H100 and 60 cycles on MI300. When the authors compare theoretical slowdown from the inserted instructions with actual slowdown, the extra optimization degradation stays within about 2%, which is evidence that the IR-level instrumentation does not badly disrupt compilation.

Memory overhead is also controlled. The region profiler stores records in shared memory and flushes them once per kernel, rather than constantly spilling to global memory. Even the most storage-hungry benchmark leaves 10.9 KB of shared memory unused and can still retain 16 iterations of trace data for four profiled regions. That is important because the paper's target kernels already consume significant on-chip resources.

The strongest result is the FlashAttention-3 case study. KPerfIR identifies a critical path in Triton's warp-specialized FA3 kernel where the V-load stage is blocked by an arrival barrier, stretching the overlap window. Using that trace, the authors move the barrier earlier and add extra prologue preloading so GEMM work overlaps more fully with loading. The resulting Triton-FA3 implementation is 24.1% faster than the vanilla Triton FA3 kernel in their benchmark and 7.6% faster than the best manual FA3 kernel they compare against. The paper also derives simple overlapping models for software pipelining and warp specialization from the profiled stage latencies, showing how the same infrastructure can inform compiler decisions instead of only visualization.

## Novelty & Impact

The novelty is not merely that KPerfIR measures GPU kernels, but that it makes profiling a reusable compiler substrate. Existing profilers are usually either vendor tools that know the hardware but not the compiler's semantics, or custom instrumenters tied to one DSL or one backend. KPerfIR's contribution is to define a profiling dialect, lowering pipeline, and runtime contract that let performance tools share the same abstractions as the compiler itself.

That is likely useful to several audiences. Kernel developers get region- and iteration-aware traces for debugging overlap. Compiler engineers get a way to connect optimization passes directly to runtime feedback. And because the design sits on Triton and MLIR-style abstractions, the paper positions it as the seed of a broader open tooling ecosystem rather than a one-off FA3 profiler.

## Limitations

The paper is explicit that KPerfIR cannot expose every metric a vendor profiler can. Some useful counters remain available only through proprietary tooling interfaces, so a compiler-centric profiler still has less raw hardware visibility than Nsight Compute or ROCm's internal tools. The design also does not eliminate perturbation entirely. Instrumentation can interfere with scheduling, especially on AMD where more instruction scheduling is software visible, so KPerfIR adds mitigation knobs rather than claiming zero distortion.

There are also scope limits. The current system is integrated with Triton and demonstrated on AI kernels, not on arbitrary MLIR compilers or general GPU software. The circular-buffer design intentionally keeps only the recent tail of long traces. And although the paper sketches distributed and non-AI use cases, those remain future extensions rather than evaluated results.

## Related Work

- _Tillet et al. (MAPL '19)_ - Triton provides the multi-level GPU compiler substrate that KPerfIR extends with profiling dialects and lowering passes.
- _Lattner et al. (CGO '21)_ - MLIR makes multi-level IR composition practical; KPerfIR applies that philosophy to dynamic profiling semantics instead of only static compilation.
- _Villa et al. (MICRO '19)_ - NVBit instruments Nvidia binaries at runtime, whereas KPerfIR instruments compiler IR and preserves loop, region, and backend-portability information.
- _Shah et al. (NeurIPS '24)_ - FlashAttention-3 is the kind of warp-specialized asynchronous kernel whose overlap behavior KPerfIR can expose and improve, but it is a workload, not a tooling framework.

## My Notes

<!-- empty; left for the human reader -->

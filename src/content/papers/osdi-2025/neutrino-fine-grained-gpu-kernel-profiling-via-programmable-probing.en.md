---
title: "NEUTRINO: Fine-grained GPU Kernel Profiling via Programmable Probing"
oneline: "NEUTRINO injects programmable assembly probes into GPU kernels, recovering instruction-level timings and memory traces across vendor stacks with low overhead for lightweight probes."
authors:
  - "Songlin Huang"
  - "Chenshu Wu"
affiliations:
  - "The University of Hong Kong"
conference: osdi-2025
code_url: "https://github.com/open-neutrino/neutrino"
tags:
  - gpu
  - observability
  - compilers
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

NEUTRINO turns GPU kernel profiling into programmable assembly probing. It injects small snippets at instruction-level tracepoints, writes results into structured maps, and reconstructs traces such as the Densified Memory Access Timeline (DMAT). Lightweight probes average about 1.04x slowdown, yet the framework can still expose scheduling, synchronization, and memory-access behavior that kernel-level profilers hide.

## Problem

GPU profiling tools mostly miss fine-grained runtime behavior. Hardware profilers rely on vendor counters and PC sampling, so they summarize kernels rather than explain which instruction, warp, or block caused a slowdown. Framework profilers sit even higher and time whole kernels while treating the body as opaque. Compiler- or binary-instrumentation tools exist, but they are usually tied to one compiler or one vendor. That gap matters because modern AI kernels depend on subtle behavior inside the kernel itself: block scheduling, synchronization, memory coalescing, and overlap among thousands of threads.

The host OS cannot simply reuse its normal tracing techniques here. GPU kernels are effectively atomic to the CPU side, and GPUs do not offer the timer-interrupt model that makes classic OS profilers work. The paper therefore asks for something closer to eBPF for GPU kernels: a runtime, instruction-granular, programmable interface that can capture both timestamps and values without requiring source changes.

## Key Insight

The paper argues that the right substrate is the GPU assembly layer. Assembly is low enough to expose hardware-relevant operations such as memory instructions and special timing registers, yet high enough to be shared by both ahead-of-time CUDA libraries and JIT systems such as Triton. That gives NEUTRINO a single place to cover both hand-written and generated kernels.

The second insight is that programmable probes only become broadly useful if they can cooperate without breaking the original program. NEUTRINO achieves that with a virtualized execution model: probes use logically separate registers, preserve control flow, and persist results through structured maps. That lets the system capture both value traces and time traces while staying close enough to the original execution to be credible.

## Design

Each probe has three parts: a `snippet`, a `tracepoint`, and a `structured map`. Snippets are small assembly fragments inserted before or after matched instructions; tracepoints can also target kernel entry or exit; maps pre-allocate per-thread or per-warp storage so persistence is race-free and metadata-light. The verifier rejects three unsafe behaviors: overwriting original registers, changing control flow, and using shared memory.

The runtime has three modules. A hook driver intercepts user-space CUDA/HIP driver APIs, tracks loaded binaries and launched kernels, allocates probe buffers, and swaps in the instrumented kernel. A probe engine disassembles the target kernel, matches tracepoints, fills helper operands such as addresses or clocks, injects snippets, and reassembles the result. On top, an optional Python DSL compiles into PTX or GCN assembly. DMAT builds on the resulting traces by plotting memory accesses using physical time and access density, so the tool can reveal both temporal structure and parallel access intensity.

## Evaluation

Evaluation on A100 and RTX4090 focuses on correctness, overhead, and usefulness. Probed and unprobed kernels produced matching outputs, and overlapping metrics agreed with Nsight Compute. For DMAT, microbenchmarks with known access patterns achieved zero address-sequence mismatch and sub-200-cycle mean timing error, under 7% of loop time. That is not perfect reconstruction, but it is good evidence that the probes measure intended events rather than arbitrary perturbation.

The overhead results support the central claim with an important caveat. Lightweight probes such as `block_sched`, `gmem_bytes`, and `tensorop_count` averaged about 1.04x slowdown and about 3.78 extra registers. Heavy DMAT tracing averaged 7.12x slowdown, so the low-overhead story clearly applies to narrow probes, not always-on memory tracing. The debugging examples are strong: on a `torch.zeros` kernel, `block_sched` shows about 20% of time spent on block scheduling, and replacing the kernel with memset or a persistent kernel cuts latency from 34,493 ns to 24,630 ns or 24,891 ns, about 28% faster. The FlashAttention-v2 case study is also persuasive: NEUTRINO exposes synchronization-induced tailing in shared-block configurations, with up to 24.69% tail inflation, and similar effects appear in GEMM.

## Novelty & Impact

NEUTRINO's novelty is that it makes GPU profiling a reusable programmable substrate rather than a fixed profiler. Unlike vendor tools, users can place probes exactly where they need them; unlike compiler-specific instrumenters, the design spans both AOT and JIT GPU stacks. That makes the paper relevant to kernel developers, ML systems engineers, and compiler researchers who need explanations tied to concrete instructions and scheduling events.

## Limitations

Assembly-level probing cannot observe unprogrammable hardware events such as cache misses, so vendor profilers remain necessary for some questions. The verifier is incomplete and conservative, and the current runtime is process-local and blocks until kernel completion. Most importantly, the strong portability claim is only partially validated: the paper implements NVIDIA and AMD support, but the main evaluation is almost entirely on NVIDIA. DMAT is also expensive enough that always-on deployment would be hard.

## Related Work

- _Villa et al. (MICRO '19)_ - NVBit instruments NVIDIA machine code at runtime, but NEUTRINO moves one layer up to assembly, targets multiple vendor stacks, and supports cooperative probes with structured persistence.
- _Braun and Froning (PMBS '19)_ - CUDAFlux provides lightweight instruction profiling for CUDA applications, whereas NEUTRINO aims to be a programmable tracing interface rather than a single-purpose profiler.
- _Skaletsky et al. (ISPASS '22)_ - GTPin brings flexible binary instrumentation to Intel GPUs, while NEUTRINO emphasizes runtime probing on the common assembly layer used by current CUDA and ROCm ecosystems.
- _Diamos et al. (PACT '10)_ - Ocelot showed PTX can be a useful systems interface, but it was not designed as an eBPF-like runtime observability substrate for production GPU kernels.

## My Notes

<!-- empty; left for the human reader -->

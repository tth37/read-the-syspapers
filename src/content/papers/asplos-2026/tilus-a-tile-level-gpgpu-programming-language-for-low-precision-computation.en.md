---
title: "Tilus: A Tile-Level GPGPU Programming Language for Low-Precision Computation"
oneline: "Builds low-precision GPU kernels around tile-level layout algebra, explicit memory-hierarchy control, and zero-copy register reinterpretation to make 1-8 bit kernels practical."
authors:
  - "Yaoyao Ding"
  - "Bohan Hou"
  - "Xiao Zhang"
  - "Allan Lin"
  - "Tianqi Chen"
  - "Cody Hao Yu"
  - "Yida Wang"
  - "Gennady Pekhimenko"
affiliations:
  - "University of Toronto, Toronto, ON, Canada"
  - "Carnegie Mellon University, Pittsburgh, PA, USA"
  - "University of Waterloo, Waterloo, ON, Canada"
  - "Independent Researcher, Santa Clara, CA, USA"
  - "Amazon Web Services, Santa Clara, CA, USA"
  - "NVIDIA"
  - "Vector Institute"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762219"
code_url: "https://github.com/NVIDIA/tilus"
tags:
  - gpu
  - compilers
  - pl-systems
  - llm-inference
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Tilus is a tile-level GPU language and compiler stack for low-precision kernels, motivated by LLM inference regimes where 4-bit is often too inaccurate and 8-bit too expensive. Its core move is to make layout and memory placement explicit enough that packed bytes can be loaded normally, reinterpreted in registers at zero cost, and only then cast for computation.

## Problem

Matrix multiplications dominate LLM serving cost, and 4-bit quantization improves throughput and bandwidth dramatically, but recent work still reports noticeable accuracy loss at 4 bits. Using 5-7 bits can recover accuracy, yet modern GPU software stacks do not provide efficient kernels for those awkward widths.

Prior approaches break down for opposite reasons. Hand-written kernels such as QuantLLM and Marlin are fast but narrow: each new bit width, format, or GPU generation requires more custom engineering. Triton is more programmable, but it lacks native sub-byte support and hides too much of the memory hierarchy, so users end up writing manual unpacking and paying for awkward layout conversions. Ladder adds low-precision support, but its packing model is most natural for power-of-two widths and its scheduling interface does not expose enough structure for optimizations like software pipelining. The missing piece is a GPU programming model that treats arbitrary-bit low precision as a first-class compilation target rather than as a collection of special cases.

## Key Insight

The paper's central claim is that arbitrary-bit kernels become manageable once layout is explicit at thread-block granularity. Tilus programs manipulate register, shared-memory, and global-memory tensors directly, so the compiler can reason about where each logical tile element lives across threads and local registers.

Tilus then gives that layout a small algebra. Primitive `local` and `spatial` layouts, combined with Kronecker-product composition, let the compiler decide when two register tensors are compatible even if they have different element types and shapes. That compatibility is the key to the fast path: packed bytes can be reinterpreted as low-precision tensor tiles without moving data. The paper's main insight is therefore that arbitrary-bit support is primarily a layout problem, not a long list of per-format unpacking tricks.

## Design

Tilus has three core pieces. First is the algebraic layout system. A register layout is modeled as a mapping from thread index plus per-thread local index to logical tensor coordinates. `local(...)` layouts keep data within a thread, `spatial(...)` layouts distribute it across threads, and more complex layouts are built by composition.

Second is the programming model. Tilus works at thread-block granularity rather than forcing the programmer into explicit SIMT code. Programs are written using block-level tensor instructions such as `LoadGlobal`, `LoadShared`, `StoreGlobal`, `CopyAsync`, `View`, `Cast`, and `Dot`. That matters because low-precision kernels are usually limited by data movement. Exposing registers, shared memory, and global memory directly gives the programmer and compiler explicit control over pipelining and placement.

Third is the low-precision path. Values below 8 bits are stored compactly in `uint8` containers, but the optimized route avoids repeated bit manipulation. Before execution, weights are rearranged in global memory into a hardware-friendly packed layout. During execution, a kernel loads the packed bytes, uses `View` to reinterpret them as a low-precision tensor tile, and then casts them to a standard type such as `float16` for tensor-core computation. The paper's `int6` example shows the mechanism clearly: three `uint8` values per thread can be reinterpreted as four `int6` values because both occupy 24 bits.

## Evaluation

The evaluation is centered on quantized matrix multiplication for LLM inference. The authors test Gemma-2-9B, Qwen2.5-32B, and Llama-3.3-70B-Instruct, mainly on NVIDIA L40S and additionally on A100 and H100. Baselines include cuBLAS, Triton, Ladder, QuantLLM, Marlin, and end-to-end integration with vLLM.

At the operator level, Tilus supports the broadest precision range in the paper: `uint1-uint8`, `int2-int8`, and `float3-float8`. The abstract reports improvements over Triton, Ladder, QuantLLM, and Marlin of `1.75x`, `2.61x`, `1.29x`, and `1.03x`, respectively, on the kernels those systems support. The full-spectrum experiment is especially persuasive because all of those variants come from one parameterized Tilus template rather than from separate hand-tuned kernels.

The end-to-end results tell a similar story. Integrated into vLLM, Tilus outperforms Ladder in both decode and prefill across the three models, with especially visible gains at larger decode batches. Some baseline failures are also informative: vLLM runs out of memory on L40S for large models, and Ladder hits an illegal-instruction error on H100 in one experiment. That supports, though does not fully prove, the paper's portability claim across recent NVIDIA generations.

## Novelty & Impact

Relative to _Tillet et al. (MAPL '19)_, the novelty is not another tile language, but one whose central abstraction is explicit low-precision layout control. Relative to _Wang et al. (OSDI '24)_, Tilus turns reinterpretation plus layout algebra into the main design principle rather than treating low precision as a packed-type scheduling extension. Relative to _Hagedorn et al. (ASPLOS '23)_ and _Ding et al. (ASPLOS '23)_, it is narrower than a general tensor compiler but deeper on the compiler-hardware interface needed by arbitrary-bit kernels.

## Limitations

The biggest limitation is scope. Although the language design is broad, the evaluation is almost entirely about quantized matrix multiplication for LLM inference; the paper does not show comparable coverage for attention kernels, convolutions, or non-LLM workloads. The implementation is also clearly NVIDIA-centric, relying on CUDA-specific instructions, `nvcc`, and recent NVIDIA memory-movement primitives. Finally, the best results often assume an offline weight-layout transformation and nontrivial tuning effort: the paper reports around 200 configurations per operator and about one minute of compile time.

## Related Work

- _Tillet et al. (MAPL '19)_ — Triton established tile-level GPU programming, while Tilus adds explicit layout algebra and native arbitrary-bit support that Triton lacks.
- _Wang et al. (OSDI '24)_ — Ladder targets low-precision deep learning through tensor transformations, but Tilus exposes a lower-level block programming model that can express pipelining and non-power-of-two bit widths more naturally.
- _Hagedorn et al. (ASPLOS '23)_ — Graphene offers an IR for optimized tensor computation on GPUs, whereas Tilus focuses specifically on how tile elements are distributed across threads and reinterpreted across data types.
- _Ding et al. (ASPLOS '23)_ — Hidet provides the compiler backend and a task-mapping programming model, but Tilus builds a dedicated low-precision language and layout system on top of that style of GPU compilation.

## My Notes

<!-- empty; left for the human reader -->

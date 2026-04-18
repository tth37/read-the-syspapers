---
title: "Triton-Sanitizer: A Fast and Device-Agnostic Memory Sanitizer for Triton with Rich Diagnostic Context"
oneline: "Interprets Triton kernels at tile granularity, proves masked accesses with SMT when possible, and falls back to eager simulation for indirect loads."
authors:
  - "Hao Wu"
  - "Qidong Zhao"
  - "Songqing Chen"
  - "Yang Chen"
  - "Yueming Hao"
  - "Tony CW Liu"
  - "Sijia Chen"
  - "Adnan Aziz"
  - "Keren Zhou"
affiliations:
  - "George Mason University, Fairfax, Virginia, USA"
  - "Google, Mountain View, USA"
  - "Anthropic, San Francisco, USA"
  - "Meta, Menlo Park, USA"
  - "OpenAI, San Francisco, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790241"
tags:
  - gpu
  - compilers
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Triton-Sanitizer checks memory safety at Triton's tile semantics instead of instrumenting low-level memory instructions. It symbolically reconstructs address and mask expressions, asks Z3 whether an out-of-bounds access is possible for the launch, and falls back to CPU eager evaluation for indirect loads. That gives richer bug reports and better end-to-end cost than vendor sanitizers.

## Problem

Triton makes it easy to write high-performance GPU kernels in a Python-like DSL, but it does not make memory bugs disappear. The paper highlights two recurring mistakes from real repositories: missing `mask` arguments on `tl.load`/`tl.store`, and masks that still admit invalid indices. Vendor sanitizers can catch some of these errors, but they are a poor fit for Triton: they add substantial overhead on JIT-specialized kernels, are tied to particular backends, and report faults as addresses and binary frames instead of tensors, offsets, and Triton operations. The challenge is to build a checker that matches Triton's abstraction level closely enough to be both cheap and debuggable.

## Key Insight

The key idea is that Triton exposes just enough structure to reason about memory accesses at tile granularity rather than scalar granularity. Addresses are usually built from a small set of operators such as `tl.program_id`, `tl.arange`, pointer arithmetic, and masking, so the sanitizer can symbolically reconstruct the accessed range, combine it with runtime tensor metadata, and ask whether any masked access for the current launch can fall outside the legal bytes of the intended tensor. This is faster than instrumenting every memory instruction, and it is more informative because the same symbolic expression also explains the bug. When symbolic reasoning breaks on indirect loads, Triton-Sanitizer falls back to eager CPU evaluation for that sub-expression and then resumes symbolic checking.

## Design

Triton-Sanitizer intercepts Triton's kernel entry path before normal lowering and GPU launch. A decorator, CLI wrapper, or environment variable enables a host-side interpreter that extracts launch dimensions, scalar parameters, constants, and tensor metadata, then executes each logical Triton program sequentially on the CPU. Its core representation is a `SymExpr` tree: `tl.program_id` and `tl.arange` introduce symbolic variables and bounds, arithmetic composes them, `tl.where` becomes a conditional expression, and indirect accesses trigger a temporary NumPy-based eager evaluation on CPU.

For each `tl.load` or `tl.store`, the tool builds an address formula `A_o(x)`, a mask `M_o(x)`, a launch-domain `D(x)`, and the legal byte set `U` for the target tensor, including strided layouts. Z3 checks whether there exists any `x` such that `D(x)` holds, the mask is true, and `A_o(x)` lies outside `U`; `sat` gives a concrete counterexample and `unsat` proves safety for that launch. The report then identifies the intended tensor, valid range, violating offset, exact source location, filtered Python/Triton call stack, and a backtracking tree of symbolic operations. To reduce overhead, the implementation caches SymExpr-to-Z3 translations, loop iterators, solver state, and repeated kernel launches.

## Evaluation

Across 112 Triton kernels from seven open-source repositories, Triton-Sanitizer finds 24 previously unknown memory-access bugs, with 8 fixes already merged upstream. The bug classes include host/kernel shape mismatches, missing or incorrect masks, and alignment-hint mistakes; it can also catch inter-object overflows because it tracks pointer provenance back to the intended tensor. On NVIDIA RTX 4090, its end-to-end normalized overhead is `0.86x-0.95x` versus `1.36x-1.59x` for `compute-sanitizer`; on AMD MI250x, it averages `0.89x` versus `3.05x` for AddressSanitizer with caches enabled. The kernel-only numbers are more mixed: Triton-Sanitizer costs about `10.22x` on NVIDIA and `10.11x` on AMD, much better than `compute-sanitizer`'s `34.06x` on NVIDIA but worse than AMD's inline LLVM checks at `2.10x`. The end-to-end win comes from bypassing compilation, launch, and framework instrumentation. The ablation study shows a `3.11x` average speedup from the cache hierarchy, with up to `38.95x` on repetitive workloads.

## Novelty & Impact

The novelty is the abstraction boundary. Instead of treating Triton as code that eventually becomes PTX or LLVM IR, the paper treats Triton's tile semantics as the right place to check memory safety and combines that structure with concrete launch metadata. That makes the system device-agnostic and much more informative than vendor tools. Relative to _Ibn Ziad et al. (PLDI '23)_, the contribution is not the fastest CUDA sanitizer but a Triton-native checker; relative to hardware proposals such as _Lee et al. (ISCA '22)_ and _Lee et al. (HPCA '25)_, it sacrifices some kernel-time efficiency to run on commodity hardware. The likely impact is on Triton kernel authors, compiler/backend engineers, and researchers interested in domain-scoped symbolic execution.

## Limitations

The guarantees are dynamic rather than universal: Triton-Sanitizer proves safety only for the concrete launch, tensor metadata, and runtime values it sees. Its fallback for indirect loads requires CPU-side eager evaluation, which can be costly on pointer-heavy kernels. Coverage is incomplete for mixed pipelines that include CUDA or other low-level GPU code, and reports are still weak for `torch.compile`-generated Triton kernels because the tool lacks provenance back to the original PyTorch source and TorchInductor pass. The paper also cannot directly compare against stronger research systems such as cuCatch or Let-Me-In, since those depend on specialized compilers, drivers, or hardware.

## Related Work

- _Tillet et al. (MAPL '19)_ — Triton introduced the tile-oriented DSL and compiler stack that Triton-Sanitizer now exploits as its semantic boundary.
- _Ibn Ziad et al. (PLDI '23)_ — cuCatch detects CUDA memory-safety violations with compiler instrumentation and driver support; Triton-Sanitizer gives up some raw efficiency to stay Triton-native and device-agnostic.
- _Lee et al. (HPCA '25)_ — Let-Me-In pushes fine-grained GPU memory safety further with hardware metadata in pointers; Triton-Sanitizer instead leverages DSL semantics and symbolic reasoning in software.

## My Notes

<!-- empty; left for the human reader -->

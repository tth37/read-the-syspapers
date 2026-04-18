---
title: "CHERI-SIMT: Implementing Capability Memory Protection in GPUs"
oneline: "Adds CHERI to SIMT GPUs by compressing capability metadata and amortizing rare CHERI operations, keeping full spatial safety near baseline cost."
authors:
  - "Matthew Naylor"
  - "Alexandre Joannou"
  - "A. Theodore Markettos"
  - "Paul Metzger"
  - "Simon W. Moore"
  - "Timothy M. Jones"
affiliations:
  - "University of Cambridge, Cambridge, United Kingdom"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3760250.3762234"
code_url: "https://github.com/CTSRD-CHERI/SIMTight"
tags:
  - gpu
  - security
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CHERI-SIMT shows that capability memory protection is not inherently too expensive for GPUs. By compressing regular capability metadata across SIMT threads and moving rare CHERI operations into a shared unit, the design keeps full spatial memory safety and referential integrity at 1.6% average run-time overhead.

## Problem

GPU kernels are still mostly written in CUDA- or OpenCL-style C/C++, so they suffer from the same out-of-bounds and memory-corruption bugs seen on CPUs. The paper argues that this matters more now because GPUs increasingly share address spaces with CPU-side processes.

CHERI is appealing because it strengthens C/C++ without forcing a language rewrite: pointers become capabilities with bounds, permissions, and validity tags. But GPUs look like the worst possible target. SIMT designs already spend heavily on per-thread registers, CHERI roughly doubles architectural register width, and replicating CHERI logic across many lanes also looks costly. The paper's question is simple: can a GPU get CHERI-class protection without making register files and execution logic prohibitively expensive?

## Key Insight

The key claim is that SIMT regularity applies to capability metadata as well as to ordinary values. Threads in a warp often access adjacent elements of the same object, so addresses vary but bounds and permissions often do not. Metadata can therefore be compressed separately from pointer addresses.

The paper pairs that observation with an instruction-frequency argument. Frequent capability operations, such as pointer arithmetic and bounds checks, stay in each lane's fast path. Rare and expensive operations, especially those that inspect or set bounds, are handled once per streaming multiprocessor in a shared-function unit. The remembered insight is: CHERI is affordable on GPUs if the design follows SIMT regularity instead of mechanically copying a CPU-style implementation into every lane.

## Design

The implementation extends the open-source SIMTight RISC-V GPU and NoCL runtime with a large subset of CHERI-RISC-V. The central hardware change is a second compressed register file for the 33 metadata bits that accompany each 32-bit architectural value. The metadata file detects only uniform vectors. The optimized design then shares vector-register backing storage between ordinary values and metadata, and adds a null-value optimization so partially invalid metadata can stay compressed.

In the pipeline, the authors use CheriCapLib for compressed-bounds handling but split it into a fast path and slow path. Pointer arithmetic and access checks stay per lane; `CGetBase`, `CGetLen`, `CSetBounds`, and similar infrequent instructions go to a shared-function unit. PCs are also extended to program-counter capabilities, with an optional restriction that PC metadata stays static during a kernel.

The memory subsystem keeps SIMTight's 32-bit fabric and implements 64-bit capability loads and stores as paired multi-flit transactions. Tag bits are carried for scratchpad memory and for main memory via a tag controller, preserving CHERI's non-forgeability semantics.

## Evaluation

The evaluation uses 14 NoCL benchmarks on a single-SM FPGA implementation of SIMTight with 64 warps and 32 threads per warp. The key comparison is between baseline, a direct CHERI port, and an optimized CHERI design with metadata compression, shared backing storage, null-value optimization, shared-function-unit support, and static PC metadata.

The headline storage result is strong. A straightforward CHERI design would increase register-file storage by 103%, but the optimized design reduces that overhead to 14%. Because no benchmark uses more than half of its registers to hold capabilities, the authors project that compiler support could lower the overhead to 7%. In a fuller GPU, they estimate total storage overhead would likely fall below 3.5%.

The performance story is similarly favorable. DRAM bandwidth is almost unchanged, so doubled pointer width does not create a major traffic penalty. The optimized design adds only 1.6% geometric-mean execution-time overhead. `BlkStencil` is the main outlier because compiler transformations create divergent metadata and trigger more `CSC` instructions. The optimized design also cuts logic-area overhead by 44% relative to the unoptimized CHERI version, ending at an added 708 ALMs per vector lane.

A like-for-like Rust port of NoCL shows 46% average overhead overall, with 34% coming from bounds checking alone. The point is not that safe languages are wrong, but that hardware capabilities look much cheaper for retrofitting protection onto existing CUDA-like kernels.

## Novelty & Impact

Relative to prior CPU CHERI work, the novelty is not the protection model but the GPU-specific implementation strategy: compress metadata separately, share backing storage, and amortize rare capability logic across lanes. Relative to GPUShield, the paper trades somewhat higher hardware cost for much stronger guarantees. Relative to Descend and other safe-language approaches, it preserves the existing CUDA-like programming model instead of requiring a new language or proof discipline.

The likely impact is on CHERI researchers, GPU architects, and teams that want safer accelerator software without porting large codebases. This is best read as a capability-aware SIMT co-design paper.

## Limitations

The evaluation platform is still a single-SM prototype GPU without production-class caches or multi-SM interactions, so some conclusions are projections rather than direct measurements on a full design. The security scope is also narrow: the paper focuses on spatial safety and referential integrity, not a full GPU study of temporal safety or compartmentalization.

Some of the best numbers also depend on support the paper does not yet implement, especially compiler help for limiting which registers hold capabilities. Finally, the optimized design uses restrictions such as static PC metadata within a kernel, which are sensible for the evaluated workloads but may be less attractive for more dynamic GPU control flow.

## Related Work

- _Watson et al. (S&P '15)_ — introduces the CHERI capability architecture on CPUs; CHERI-SIMT asks how to preserve those guarantees in a SIMT GPU without prohibitive register and logic costs.
- _Lee et al. (ISCA '22)_ — GPUShield adds region-based bounds checking to GPUs, but CHERI-SIMT argues for capability metadata and tags because they support stronger integrity and more flexible bounds manipulation.
- _Naylor et al. (ICCD '24)_ — SIMTight provides the compressed-register-file and scalarization substrate that this paper extends with capability-aware metadata handling.
- _Köpcke et al. (PLDI '24)_ — Descend pursues safe low-level GPU programming through language design and static checking, whereas CHERI-SIMT keeps CUDA-like C++ and moves safety into the hardware substrate.

## My Notes

<!-- empty; left for the human reader -->

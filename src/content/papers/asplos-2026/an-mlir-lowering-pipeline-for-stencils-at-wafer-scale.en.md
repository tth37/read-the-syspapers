---
title: "An MLIR Lowering Pipeline for Stencils at Wafer-Scale"
oneline: "Keeps stencil semantics in MLIR long enough to synthesize chunked actor-style CSL for Cerebras WSE, matching hand-tuned code across WSE2 and WSE3."
authors:
  - "Nicolai Stawinoga"
  - "David Katz"
  - "Anton Lydike"
  - "Justs Zarins"
  - "Nick Brown"
  - "George Bisbas"
  - "Tobias Grosser"
affiliations:
  - "Technische Universität Berlin, Berlin, Germany"
  - "EPCC, University of Edinburgh, Edinburgh, United Kingdom"
  - "School of Informatics, University of Edinburgh, Edinburgh, United Kingdom"
  - "Imperial College London, London, United Kingdom"
  - "University of Cambridge, Cambridge, United Kingdom"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790124"
code_url: "https://github.com/xdslproject/wse-stencil"
tags:
  - compilers
  - hardware
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

This paper keeps stencil semantics explicit deep into MLIR lowering, then converts them into chunked communication, actor-style callbacks, and CSL for the Cerebras WSE. The result is generated code that runs unchanged from existing Fortran and Python stencil frontends, matches hand-written WSE kernels, and sometimes beats them.

## Problem

The paper targets a major adoption barrier for the Cerebras Wafer-Scale Engine. WSE offers huge on-chip parallelism and SRAM, which should suit stencil codes well, but programming it is awkward because communication is asynchronous, each processing element has only `48 KB` of local memory, and control flow around communication must be rewritten as tasks and callbacks. A normal time-step loop in Fortran therefore becomes callback-heavy CSL.

That mismatch hurts both portability and performance engineering. Users must manually rewrite working stencil codes into Cerebras-specific CSL, and the decisions about decomposition, chunked halo exchange, buffer usage, and communication/computation overlap are left to experts. Existing frontends already know stencil shapes and dependencies, but before this work there was no MLIR path that preserved that information long enough to generate efficient WSE code automatically.

## Key Insight

The central claim is that stencil semantics must survive deep into lowering because the information needed for WSE code generation is exactly what generic low-level IR throws away too early: neighborhood shape, remote versus local accesses, reduction structure, and constant coefficients. If the compiler keeps that information, it can translate a synchronous stencil into an actor-style program mechanically.

That is why the authors lower through staged dialects instead of jumping directly from `stencil` to generic loops. The compiler first makes communication explicit, then separates remote-data handling from local compute, then lowers those regions into tasks triggered by chunk arrival or completion. Treating processing elements as hardware actors and CSL tasks as software actors gives the compiler a consistent target model.

## Design

The pipeline starts from PSyclone, Devito, and Flang, all of which feed the MLIR/xDSL `stencil` dialect. The first transformation group maps `x` and `y` across the WSE's 2D grid and tensorizes `z` so each PE owns a column. Existing `distribute stencil` machinery inserts `dmp.swap` operations that explicitly mark halo exchanges.

The second group lowers into a new `csl-stencil` dialect with `prefetch`, `apply`, and `access` operations. Its crucial feature is that `csl-stencil.apply` has two regions: one processes remote chunks as they arrive and partially reduces them into an accumulator, and the other performs the local computation after remote data is ready. This matches the WSE memory budget and lets the compiler fuse coefficient application into communication.

The rest of the pipeline progressively realizes execution. `csl-wrapper` packages the PE program with the layout metaprogram and compile-time parameters, while `csl-ir` mirrors CSL closely enough to print final source. MLIR bufferization and `linalg` convert tensors into destination-passing memory operations. Then each asynchronous stencil application is split into actor-like tasks, one running per chunk and one after communication completes. Top-level loops become a control-flow task graph, and the last stage lowers arithmetic to CSL-oriented `csl-ir` using Data Structure Descriptors and builtins such as fused multiply-accumulate. A runtime library handles the star-shaped exchanges and callback wiring.

## Evaluation

The evaluation uses five benchmarks from three frontend technologies: Jacobian from Flang, Diffusion and Acoustic from Devito, UVKBE from PSyclone, and a 25-point seismic kernel derived from optimized Cerebras CSL. Experiments run on both WSE2 and WSE3 with single-precision arithmetic and problem sizes up to `750 x 994` in `x` and `y`.

The clearest result is against hand-written WSE code. On the 25-point seismic benchmark, the generated WSE2 code beats the manually tuned CSL version by up to `7.9%`. The paper explains that win concretely: the compiler communicates only needed columns, fits the exchange into one chunk instead of two, and cuts task count by about `50%`. The same pipeline also targets WSE3, where the generated code is up to `38.1%` faster than on WSE2.

The broader systems claim comes from the Acoustic benchmark. There, WSE3 is reported as about `14x` faster to solution than `128` Nvidia A100 GPUs and `20x` faster than `128` ARCHER2 CPU nodes. The paper notes that this is not perfectly apples-to-apples because the CPU/GPU runs use larger problem sizes and an OpenACC baseline. Even so, the roofline analysis supports the main argument: on WSE3 the stencil kernels are mostly compute-bound, while the A100 Acoustic baseline remains memory-bound.

## Novelty & Impact

Relative to _Bisbas et al. (ASPLOS '24)_, the novelty is not the stencil dialect itself but redirecting that shared stencil stack from MPI-style distributed memory toward the asynchronous Cerebras WSE. Relative to _Jacquelin et al. (SC '22)_, the contribution is not a better hand-written stencil, but a compiler that absorbs those communication and chunking tricks automatically. Relative to _Sai et al. (SC '24)_, the key differentiator is frontend independence.

That gives the paper practical impact beyond one accelerator. It shows that keeping domain-specific information alive deep into lowering is what makes portability and good code generation possible when the target execution model differs radically from the source program.

## Limitations

The biggest limitation is scope. The runtime currently targets star-shaped stencils of up to three dimensions, and the chosen decomposition assumes one `z` column per PE. More general communication patterns or mappings would need additional library and routing work.

The strategy still depends on domain-specific assumptions. The paper does not synthesize arbitrary hardware routes, and its cross-platform headline numbers need caution because the GPU baseline uses OpenACC and different problem sizes. The productivity story is also supported mainly by lines-of-code comparisons rather than a controlled development-time study.

## Related Work

- _Bisbas et al. (ASPLOS '24)_ — Provides the shared MLIR/xDSL stencil compilation stack that this paper extends from MPI-style distributed systems to the Cerebras WSE.
- _Jacquelin et al. (SC '22)_ — Shows the hand-written 25-point stencil and chunked communication strategy whose implementation tricks this compiler effectively internalizes.
- _Rodriguez-Canal et al. (SC-W '23)_ — Demonstrates lowering the same stencil abstractions to FPGAs, whereas this paper targets a much more asynchronous wafer-scale machine.
- _Sai et al. (SC '24)_ — Also generates stencil code for a Cerebras-style dataflow architecture, but through a bespoke frontend/compiler path rather than a reusable MLIR backend for existing DSLs.

## My Notes

<!-- empty; left for the human reader -->

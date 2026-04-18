---
title: "The Configuration Wall: Characterization and Elimination of Accelerator Configuration Overhead"
oneline: "Models accelerator setup as a first-class bottleneck and uses an MLIR dialect plus compiler passes to remove redundant configuration and hide the rest."
authors:
  - "Josse Van Delm"
  - "Anton Lydike"
  - "Joren Dumoulin"
  - "Jonas Crols"
  - "Xiaoling Yi"
  - "Ryan Antonio"
  - "Jackson Woodruff"
  - "Tobias Grosser"
  - "Marian Verhelst"
affiliations:
  - "KU Leuven, Leuven, Belgium"
  - "The University of Edinburgh, Edinburgh, United Kingdom"
  - "University of Cambridge, Cambridge, United Kingdom"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3760250.3762225"
code_url: "https://github.com/kuleuven-micas/snax-mlir"
tags:
  - hardware
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

The paper argues that many accelerators are limited first by host-side setup rather than by arithmetic throughput or memory bandwidth. It formalizes that regime as the configuration wall, then introduces an MLIR dialect, `accfg`, plus two compiler optimizations: delete redundant configuration writes and overlap setup with execution when the hardware allows it. On OpenGeMM, the full stack delivers a `2x` geomean speedup.

## Problem

The paper starts from a common accelerator control pattern: the host writes configuration registers, launches the macro-operation, then waits for completion. As accelerators gain more features, that setup sequence grows in both bytes and host instructions. Those cycles are not useful work for either the CPU or the accelerator, but they increasingly dominate end-to-end time as the datapath itself gets faster.

The authors call the point where setup dominates the configuration wall. Existing tools do not describe it well. Traditional roofline analysis separates compute-bound from memory-bound execution, but it does not treat host-to-accelerator setup as an independent bottleneck. Compilers are not much better, because accelerator control code is usually written as volatile inline assembly or other opaque side effects. Since those writes are target-specific, order-sensitive, and stored in external registers, ordinary optimizations cannot safely remove or move them.

## Key Insight

The central claim is that configuration overhead should be modeled the way we already model memory pressure. The paper introduces operation-to-configuration intensity, `IOC`, and configuration bandwidth, `BWConfig`, then shows that attainable performance is limited by the configuration term whenever setup takes longer than useful accelerator work. For sequential accelerators the bound is even harsher because setup and execution cannot overlap.

That framing makes the optimization strategy obvious. A compiler can move a workload rightward on the roofline by increasing `IOC`, meaning less setup per unit of useful work, or upward by overlapping setup with ongoing execution. To do either safely, it needs a precise representation of accelerator configuration state.

## Design

The design has two parts. First, the model distinguishes concurrent from sequential configuration and adds effective configuration bandwidth so host-side parameter calculation, such as bit-packing, counts toward setup cost instead of disappearing into the noise.

Second, the paper introduces an MLIR/xDSL dialect called `accfg` with three main operations: `setup`, `launch`, and `await`. `setup` produces an SSA value representing accelerator state, `launch` consumes that state, and `await` synchronizes with completion. The key move is that configuration registers stop being opaque external state and become compiler-visible dataflow. Effects annotations mark unknown operations as possible state clobbers unless they are explicitly known to preserve accelerator state.

Two compiler passes build on top of that abstraction. Configuration deduplication walks backward through the setup chain and removes writes that would store the same value to the same field again; it also hoists loop-invariant setup fields and restructures some control flow to preserve more known state. Configuration-computation overlap targets accelerators with concurrent setup hardware: it software-pipelines loops so the next iteration's pure setup work can run before the previous `await`, hiding part of the control path behind ongoing accelerator execution.

## Evaluation

The evaluation uses tiled matrix multiplication on two open accelerator platforms. Gemmini is sequentially configured, so it mainly tests whether the abstraction can remove redundant setup and expose ordinary compiler optimizations. By tracing Spike execution, the authors estimate that a `64x64` kernel with `524,288` operations achieves only `41.49%` utilization under theoretical configuration bandwidth and `26.78%` when host-side parameter calculation is included via effective bandwidth.

For measured Gemmini performance, the `accfg` flow is compared with Gemmini's `GCC -O2` baseline on weight-stationary tiled matrix multiplication. The gain is `11%` geomean, with the largest benefit near matrix size `128`, where repeated launches create enough redundant state to exploit.

OpenGeMM is the stronger case because it supports concurrent configuration. On a cycle-accurate Verilator model of a `1024 ops/cycle` accelerator, the full optimization stack delivers a `2x` geomean speedup, with individual sizes improving by `1.86x` to `2.71x`. The roofline plots match the paper's argument closely: deduplication moves points up and to the right by increasing `IOC`, while overlap moves them upward toward the concurrent roofline without changing `IOC`. Both case studies are still matrix accelerators in relatively bare-metal environments, but they do exercise exactly the control path the paper targets.

## Novelty & Impact

Relative to prior roofline-style work, the paper's novelty is to treat configuration as an independent throughput limiter rather than collapsing it into compute or memory effects. Relative to accelerator-compilation systems such as _Agostini et al. (CGO '24)_ and interface work such as _Suresh et al. (PACT '24)_, its contribution is more compiler-centric: make accelerator state explicit, reason about it with SSA-like structure, and use that structure to remove or hide setup cost across backends.

## Limitations

The paper is careful about scope. Both evaluated platforms are matrix accelerators, so the claim of generality comes more from the abstraction design than from workload diversity. The overlap pass also depends on concurrent-configuration hardware and on setup logic being pure enough to move safely; accelerators with richer side effects or heavier software protocols may be harder to optimize this way.

The abstraction remains conservative around control flow and calls. Unknown functions are treated as possible state clobbers unless annotated, conditional invocations still lose optimization opportunities, and fault handling or OS-mediated control paths are out of scope. So the results are strongest for bare-metal or compiler-controlled accelerator stacks, not yet for driver-heavy production systems.

## Related Work

- _Cardwell and Song (HPCAsia '19)_ — Their extended roofline adds communication awareness; this paper adds configuration as a distinct host-controlled bottleneck.
- _Agostini et al. (CGO '24)_ — AXI4MLIR automates host-side code generation, whereas `accfg` exposes configuration state for optimization.
- _Wei et al. (ASPLOS '23)_ — Cohort studies software-oriented acceleration pipelines for heterogeneous SoCs; this paper targets simpler register-configured accelerators.
- _Suresh et al. (PACT '24)_ — Mozart redesigns accelerator interfaces, while The Configuration Wall contributes a model plus compiler passes for setup overhead.

## My Notes

<!-- empty; left for the human reader -->

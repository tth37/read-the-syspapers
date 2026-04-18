---
title: "RTeAAL Sim: Using Tensor Algebra to Represent and Accelerate RTL Simulation"
oneline: "Recasts full-cycle RTL simulation as a sparse tensor kernel, replacing giant generated binaries with compact kernels optimized through tensor formats and loop unrolling."
authors:
  - "Yan Zhu"
  - "Boru Chen"
  - "Christopher W. Fletcher"
  - "Nandeeka Nayak"
affiliations:
  - "University of California, Berkeley, Berkeley, CA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790214"
code_url: "https://github.com/TAC-UCB/RTeAAL-Sim"
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

RTeAAL Sim replaces giant straight-line RTL-simulator binaries with a sparse tensor algebra kernel. By keeping circuit structure in tensors and optimizing format plus loop structure, the prototype slashes compilation cost and reaches performance competitive with Verilator.

## Problem

CPU-based RTL simulation is still the day-to-day tool for hardware design, but state-of-the-art simulators scale badly because they compile the circuit into large, almost straight-line C++ programs. That strategy exposes optimization opportunities to `clang`, yet it also ties simulator speed directly to binary size.

The result is a two-sided bottleneck. As designs grow, compilation time and compiler memory rise sharply. At run time, the simulator becomes frontend-bound: instruction-cache pressure is high, code reuse is low, and fetch stalls dominate. ESSENT mitigates some of that by unrolling even more aggressively, but the paper shows that this simply trades less branch overhead for even worse compilation cost.

## Key Insight

The central claim is that synchronous RTL simulation can be written as sparse tensor algebra without losing the semantics needed for realistic circuits. Once the next-state dataflow graph is encoded as tensors, one cycle becomes a cascade of extended Einsums. The key benefit is representation-level: the circuit mostly lives in data, while a small kernel interprets that structure, so simulator behavior is no longer hard-wired into a giant binary.

That matters because tensor algebra already comes with a mature optimization toolkit. Using TeAAL's separation of concerns, the paper can optimize the cascade, mapping, format, and binding independently. Sparse formats, rank swizzling, and selective loop unrolling become first-class RTL-simulation optimizations rather than simulator-specific tricks.

## Design

The formulation starts with three tensors for one graph layer: `LI` for current inputs, `OIM` for the operation-input mask, and `LO` for outputs. To cover arbitrary synchronous circuits, `OIM` gains ranks for layer `I`, output index `S`, operation type `N`, operand order `O`, and operand source `R`. One cycle is then a cascade of extended Einsums over these tensors.

That structure handles more than simple arithmetic. Reducible operations use a custom reduce operator keyed by `N`; unary operations are handled in the map stage; select operations such as muxes use a populate-stage operator that sees the whole operand fiber. To support arbitrary graphs, the compiler levelizes the dataflow graph and inserts identity operations to forward values between layers, then elides most of their cost by aligning source and destination coordinates.

The optimization work is concentrated in `OIM`, whose density is only `10^-7` to `10^-9`. Dense ranks stay uncompressed, sparse ranks are compressed, and redundant payload arrays are removed entirely. The compiler then explores a spectrum of bindings, from mostly rolled kernels to heavily unrolled ones. A key step is swizzling `S` and `N` so same-type operations become contiguous, enabling partial unrolling without recreating a huge straight-line binary. The proof-of-concept compiler takes FIRRTL, applies graph rewrites such as operator fusion and copy propagation, emits `OIM` metadata as JSON, and generates a configurable C++ kernel.

## Evaluation

The authors evaluate RocketChip, BOOM, Gemmini, and SHA3 on Intel, AMD, and AWS Graviton machines, comparing seven RTeAAL Sim kernels against Verilator and ESSENT. The most important compilation result is on 1- to 24-core RocketChip designs: the partially unrolled `PSU` kernel compiles in `4.26` seconds and about `0.203 GB` of peak memory across the whole range, while Verilator grows from `92` to `724` seconds and ESSENT from `121` to `13,700` seconds. That supports the core claim that keeping the circuit in data makes compile cost nearly flat in design size.

Run time is a trade-off rather than a clean win. Fully unrolled kernels execute fewer dynamic instructions but become badly frontend-bound as code size rises. On Xeon, the sweet spot is the middle-ground `PSU` kernel, which keeps most of the instruction-count savings without blowing up the instruction cache.

Against prior simulators, the prototype reaches the paper's advertised position. With `clang -O3`, ESSENT is still fastest on large Xeon RocketChip runs, but only at extreme compile-time cost. RTeAAL Sim is generally competitive with Verilator and often faster on larger, cache-stressed designs. The clearest evidence is the LLC-throttling experiment on 8-core SmallBOOM: when Xeon LLC shrinks from `10.5 MB` to `3.5 MB`, RTeAAL Sim's `PSU` speedup over Verilator rises from `1.32x` to `1.55x`, while ESSENT degrades sharply. The main caveat is SHA3: on that small design, Verilator still wins, so the benefits are strongest when simulation is truly cache- and frontend-limited.

## Novelty & Impact

Relative to _Beamer and Donofrio (DAC '20)_, the novelty is not another code-generation trick, but a representation change: keep the kernel compact and move the circuit into sparse tensor data. Relative to _Wang and Beamer (ASPLOS '23)_ and _Wang et al. (ASPLOS '24)_, which optimize conventional RTL-simulation flows, this paper proposes a more general substrate on which such optimizations can be restated. It is also a strong application of _Nayak et al. (MICRO '23)_, showing that TeAAL-style reasoning can describe a workload that does not initially look tensor-like.

## Limitations

The paper is clear that this is a proof-of-concept, not an industrial replacement. It focuses on full-cycle CPU simulation, assumes a single clock domain in the core formulation, and evaluates only a subset of the optimization space it sketches. Multi-clock support, event-driven simulation, GPU mappings, and accelerator co-design are largely future work.

Performance is also conditional. The prototype is competitive with Verilator, but it does not uniformly beat ESSENT and can lose on small designs such as SHA3 where straight-line code remains effective. The best kernel depends on both machine and design size, so a practical deployment would probably need autotuning or a cost model. The paper also leaves a cleaner formal treatment of traversal-order constraints for the `O` rank to future work.

## Related Work

- _Beamer and Donofrio (DAC '20)_ — ESSENT reduces branch overhead and frontend waste with aggressively straight-line code, whereas RTeAAL Sim keeps a rolled kernel and moves circuit structure into sparse tensor data.
- _Wang and Beamer (ASPLOS '23)_ — RepCut accelerates parallel RTL simulation through replication-aided partitioning; RTeAAL Sim treats that kind of strategy as a mapping or cascade optimization on top of its tensor substrate.
- _Nayak et al. (MICRO '23)_ — TeAAL provides the separation-of-concerns framework that RTeAAL Sim uses to reason about format, mapping, and binding choices for simulation kernels.

## My Notes

<!-- empty; left for the human reader -->

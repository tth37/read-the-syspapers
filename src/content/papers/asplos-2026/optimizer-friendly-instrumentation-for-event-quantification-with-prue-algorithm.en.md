---
title: "Optimizer-Friendly Instrumentation for Event Quantification with PRUE Algorithm"
oneline: "Zircon uses local delta-counters plus post-optimization PRUE rewriting to preserve exact event counts while making instrumentation much easier for compilers to optimize."
authors:
  - "Hao Ling"
  - "Yiyuan Guo"
  - "Charles Zhang"
affiliations:
  - "The Hong Kong University of Science and Technology, Hong Kong, China"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790196"
code_url: "https://github.com/zirconinstrumentation/ZirconInstrumentation"
tags:
  - compilers
  - fuzzing
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Zircon argues that exact event counting should not be treated as "increment a global counter everywhere the event happens." Instead, it first records counts in local per-function delta-counters that compilers can reason about, then runs PRUE after optimization to move, split, or delete the delayed global updates. That combination keeps counts exact, exposes loops and scalar expressions to existing LLVM optimizers, and cuts instrumentation overhead substantially versus SanCov, Nisse, and other baselines.

## Problem

The paper studies exact event quantification: coverage counting, function-call counting, memory-operation counting, and similar instrumentation that downstream tools rely on for debugging, profile-guided optimization, tuning, and fuzzing. The data itself is simple, but the implementation is not. To make counters visible to external tooling, most systems increment global memory-resident counters at the event site. Those increments have side effects, create may-alias relationships, and introduce cross-function dependencies. As a result, optimizers that would normally simplify loops, sink or hoist code, or reason about value ranges become conservative.

The obvious alternatives both lose. Early instrumentation preserves source-level structure, but the extra side effects block optimization; the paper cites prior work showing average slowdowns from optimization failure, and its own experiments see early instrumentation become up to 5x slower than late instrumentation. Late instrumentation avoids poisoning the optimizer, but then the optimizer has already lowered or split the code, so instrumentation quality gets worse. Nisse, for example, depends on loop structure that can disappear after loop fission, and its SESE-style reuse opportunities shrink at `-O2`/`-O3`.

Local counters look like the natural fix, because compilers can optimize local variables far more aggressively than globals. But local counters are not directly observable outside the function, so the system still needs global updates somewhere. If those updates happen too early, they recreate the original barrier. If they happen only at function exit, many paths execute useless `counter += 0` updates and keep the local values live for too long. The hard problem is therefore not merely "use locals," but "decide where exact global updates should be materialized after optimization has changed the CFG."

## Key Insight

The central insight is that exact counting can be decomposed into two phases with different optimization needs. Inside the function, Zircon records event occurrences in local delta-counters whose full scope and lifetime are visible to the compiler. Outside the optimization window, it materializes the externally visible global update. Once the optimizer has simplified loops and branches, many exact counts become ordinary scalar values such as loop trip counts, branch-dependent constants, or vector-reduced sums.

PRUE, the Partially Redundant Update Elimination algorithm, turns the delayed-update problem into a sparse SSA rewrite problem instead of a pre-optimization placement guess. Starting from a late `inc(v)` update, PRUE walks backward along the SSA def-use structure and keeps only the "living" value-flow paths that can contribute non-zero counts. Paths that only carry zero are pruned. That lets Zircon preserve exactness while avoiding both optimization barriers and redundant late updates.

## Design

Zircon has two stages. In the first stage, before the normal optimization pipeline, it injects per-function delta-counters. LLVM `alloca` variables hold mutable counters initially, then `Mem2Reg` promotes them into SSA values and phi nodes. Zircon also unifies function exits and emits placeholder global updates at the unified exit, intentionally giving each delta-counter the longest possible lifetime so optimizers can see through the local arithmetic before any observable side effect occurs. To keep value flow tractable, Zircon adopts a single-assignment policy: each delta-counter is incremented in only one basic block, and multi-site schemes get separate counters.

The second stage runs PRUE at the end of LLVM's optimizer pipeline. PRUE is a worklist algorithm over tasks of the form "update `inc(v)` at block `u`." Every transformer moves the update closer to the function entry or splits it so that zero-carrying paths become explicit. `eliminate` removes `inc(0)`. `relocate` hoists an update to the topmost safe dominator in the same loop structure, shortening live ranges without changing which paths execute it. `split` breaks an update on a phi value into per-edge updates, inserting fresh edge blocks when needed so duplicated updates remain mutually unreachable.

Loops need extra handling because moving an update inward can accidentally execute it multiple times. For that, PRUE adds two loop-aware transformers. `offload` finds an outer delayed update whose only non-zero contribution comes from one inner-loop addition, rewrites phi inputs from outside the loop to zero, and creates a dedicated loop-exit update for the living addend. `unpack` is the fallback when all nested loops still contain partial redundancy: it peels apart addition expressions and turns the non-local operand into a new update task. The paper's correctness argument rests on two invariants: every living value from an original update must be captured by exactly one derived subtask, and subtasks from the same original update must be mutually unreachable. Because each rewrite moves toward the function entry, the process terminates.

## Evaluation

The evaluation uses LLVM 17 at `-O3` on SPEC CPU 2017, plus Jotai with CFGGrind for instruction-count measurements and AFL++ with the Magma benchmark for downstream fuzzing impact. The comparison is reasonably fair: SanCov provides the shared runtime support, Nisse is reimplemented on top of that runtime because its public prototype cannot handle multi-file software, and an EarlyQ baseline approximates Odin-style early quantification.

The headline result is broad rather than cherry-picked. Zircon adds `0.2%-44%` runtime overhead on SPEC, with a `19%` geometric mean. SanCov is `16%-263%` with `51%` mean overhead, Nisse is `9%-246%` with `40%`, EarlyQ is `10%-484%` with `105%`, and PGOInstrumentation is `3%-131%` with `46%`. The most dramatic single case is `nab`, where Zircon is about `2.5x` as fast as SanCov and Nisse because its local counting lets loop optimizers recover scalar summaries instead of leaving per-iteration global increments in place. The paper is careful, though, to note that when optimizer effects are small, Nisse or EarlyQ can still win on some programs because MST-based pruning physically removes more counters.

The paper also shows that PRUE itself is necessary rather than decorative. Without PRUE, delayed updates create an average redundant-update ratio of `8.45%`, which slows Zircon by `1.15x-7.53x`; with PRUE, the ratio falls to `0.68%`, eliminating more than `90%` of the redundant updates. On Jotai, Zircon's instruction growth averages `1.13x`, lower than SanCov (`1.17x`), Nisse (`1.19x`), PGOInstrumentation (`1.21x`), and EarlyQ (`1.33x`). Compiler statistics tell the same story from the other side: compared with late instrumentation, Zircon triggers roughly `10x` more reassociation, `7x` more instruction simplification, `6x` more induction-variable replacement, and `3x` more LICM-style sinking. Compile-time cost rises only modestly, about `12.4%` over SanCov, versus `54.9%` for Nisse. Finally, on Magma, AFL++ with Zircon finds `17.5%` more bugs than SanCov and `20%` more than Nisse within the fixed budget, while reducing RMST by `13.43%` and `10.70%`.

## Novelty & Impact

Relative to _Frenot and Pereira (CC '24)_, Zircon's contribution is not another way to infer missing counters from an MST, but a new way to make exact counters optimizer-friendly before inference is even needed. Relative to _Wang et al. (PLDI '22)_, it does not trade away observability by removing instrumentation on demand; it preserves precise counts throughout execution. Relative to _Wang et al. (USENIX ATC '21)_, it does not mainly optimize counter addresses or indexing, but the value-update side that dominates exact-count overhead.

That makes the paper useful to compiler engineers, sanitizer and profiler authors, and fuzzing-system builders. Its broader claim is that instrumentation overhead is not only a runtime-systems problem; it is often a compiler-compatibility problem. Zircon's impact is therefore a new mechanism and a useful reframing: exact instrumentation can be expressed so that existing optimization passes do most of the hard work.

## Limitations

The paper is honest about where the technique stops. Zircon is a compiler-IR solution, so binary instrumentation would first need lifting into IR. It also assumes event identifiers remain stable within a function invocation; that is fine for many context-insensitive or calling-context-sensitive schemes, but harder for highly dynamic identifiers. The implementation further relies on dominance/post-dominance structure, so unusual control flow such as non-local exceptions weakens the assumptions.

There are also practical limits that matter to a reader evaluating deployment. The prototype and evaluation are centered on exact edge counting translated into block counting, with SanCov's runtime as the common support layer. That keeps the study controlled, but means the paper does not fully show how Zircon behaves under more exotic instrumentation schemes or under runtimes with different counter-management costs. And because Zircon deliberately avoids MST-style pruning by default to stay general-purpose, it can lose on workloads where pruning matters more than optimization friendliness.

## Related Work

- _Frenot and Pereira (CC '24)_ — Nisse reduces exact profiling overhead by reusing affine variables and MST structure, while Zircon instead restructures exact updates so the optimizer can simplify them directly.
- _Wang et al. (PLDI '22)_ — Odin lowers fuzzing overhead through on-demand instrumentation and recompilation, whereas Zircon targets always-on exact quantification without dropping information.
- _Wang et al. (USENIX ATC '21)_ — RIFF shrinks coverage-guided fuzzing cost with hard-coded counter addresses, a counter-index optimization that Zircon treats as complementary rather than competing.
- _Ball and Larus (MICRO '96)_ — classic path profiling optimizes dynamic path indexing; Zircon addresses the different bottleneck of exact counter-value updates after compiler optimization.

## My Notes

<!-- empty; left for the human reader -->

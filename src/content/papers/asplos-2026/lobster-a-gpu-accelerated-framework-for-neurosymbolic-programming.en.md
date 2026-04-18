---
title: "Lobster: A GPU-Accelerated Framework for Neurosymbolic Programming"
oneline: "Compiles Datalog-based neurosymbolic programs into a GPU-oriented APM IR so joins, provenance tags, and fixpoint evaluation all run on GPUs."
authors:
  - "Paul Biberstein"
  - "Ziyang Li"
  - "Joseph Devietti"
  - "Mayur Naik"
affiliations:
  - "University of Pennsylvania, Philadelphia, Pennsylvania, USA"
  - "Johns Hopkins University, Baltimore, Maryland, USA"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3760250.3762232"
code_url: "https://github.com/P-bibs/Lobster"
tags:
  - gpu
  - compilers
  - ml-systems
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Lobster is a GPU-native execution framework for Datalog-based neurosymbolic programs. Its core move is to compile relational-algebra plans into a constrained intermediate language, `APM`, whose instructions already fit GPU execution: columnar tables, explicit allocation, SIMD-friendly operators, and semiring-tag propagation. That lets Lobster accelerate discrete, probabilistic, and differentiable reasoning without asking users to rewrite their programs.

## Problem

The paper starts from a systems mismatch inside modern neurosymbolic stacks. Neural components already run efficiently on GPUs or TPUs, but the symbolic side of the pipeline still tends to execute on CPUs. That imbalance is especially painful in frameworks like Scallop, where symbolic execution is not just post-processing: it sits inside training and inference loops, and it must carry probabilistic or differentiable provenance alongside tuples. As reasoning chains get longer, the system must manipulate both more derived facts and more complicated tags, so time and space blow up together.

Prior work does not solve the whole problem. Classical high-performance Datalog engines such as Souffle optimize CPU execution, but they do not support the provenance machinery needed for neurosymbolic learning. GPU Datalog systems such as FVLog accelerate discrete relational execution, but not differentiable or probabilistic reasoning. An expert could hand-write CUDA kernels for a specific task, but that does not scale as a programming model. The paper therefore targets a broader question: can a general Datalog-based neurosymbolic language be mapped onto GPUs without giving up the richer semantics that make neurosymbolic programming useful in the first place?

## Key Insight

The central claim is that the right abstraction boundary is not “compile Datalog directly to CUDA,” but “compile Datalog to a GPU-shaped relational IR that makes efficient execution almost inevitable.” Lobster calls this IR `APM` (Abstract Parallel Machine). `APM` is deliberately restrictive: no general control flow, explicit register allocation, SSA-style buffers, and a columnar table representation. Those constraints line up with how GPUs actually want to run code, especially for joins, projections, scans, sorting, and deduplication.

That abstraction also provides a place to encode provenance systematically. Instead of treating probabilistic or differentiable reasoning as special cases bolted onto an otherwise discrete engine, Lobster stores semiring tags as another column-register pack and defines the relevant `⊕` and `⊗` operations inside the runtime. In other words, the same IR simultaneously exposes data parallelism and preserves tagged semantics.

## Design

Lobster’s compilation pipeline begins from a Datalog program that an existing front-end lowers into a relational-algebra machine (`RAM`). Lobster then flattens each `RAM` expression DAG into sequential `APM` instructions. Relations become packs of equal-length registers: one register per column plus one extra register for provenance tags. Projection is easy because each row can be transformed independently; join is the hard case, so the system lowers joins into a hash-based GPU pipeline using `build`, `count`, `scan`, `join`, and `gather` operators. Provenance for joined facts is combined by multiplying the input tags during the `gather`.

Execution uses least-fixpoint iteration with semi-naive evaluation. The runtime partitions facts into `stable`, `recent`, and `delta` sets, then only applies recursive rules to the frontier instead of recomputing against the full relation every round. Importantly, the paper does not describe this as an external evaluation trick; the semantics are encoded directly in the compiled `APM` program, so sorting, uniqueness, frontier maintenance, and merges also run on the GPU.

The provenance framework is broader than a single benchmark. Lobster implements seven semirings spanning discrete, probabilistic, and differentiable reasoning, including `unit`, `max-min-prob`, `add-mult-prob`, `top-1-proof`, and differentiable variants. The pragmatic compromise is that it does not implement fully general `top-k-proofs`; instead, it focuses on `top-1-proof`, which tracks one proof per fact and uses a fixed maximum proof size known ahead of time. The paper sets that limit to 300 for its benchmarks.

Several optimizations matter in practice. Because `APM` allocations are explicit and loop structure is fixed, Lobster can use arena allocation when memory permits and buffer reuse otherwise. When a join input comes from an EDB relation that does not change across fixpoint rounds, the compiler marks the built hash table as static so it can be reused. Batched training is handled by prepending a sample-id register to each table, which prevents cross-sample joins while keeping the rest of the semantics intact. The implementation reuses Scallop’s front-end and query planner, then adds roughly 2,000 lines of Rust and 9,000 lines of CUDA/C++ for the compiler and runtime.

## Evaluation

The evaluation is broad enough to support the paper’s “general framework” claim. Lobster is tested on ten tasks spanning image reasoning, natural-language reasoning, program analysis, bioinformatics, planning, and graph analytics, and across differentiable, probabilistic, and discrete modes. The main baseline is Scallop for tagged neurosymbolic workloads, with additional comparisons to ProbLog, Souffle, and FVLog where appropriate.

The headline result is an average `3.9x` speedup over Scallop, with some cases far larger. On end-to-end training, Lobster improves total runtime by `1.2x` to `16.46x`; PacMan-Maze benefits most because symbolic reasoning dominates there. On inference workloads, it achieves `3.69x` speedup on CLUTRR, `1.55x` on Pathfinder, and `2.11x` on PacMan. On probabilistic static analysis, several programs see `12x-19x` improvements over Scallop. RNA secondary-structure prediction is especially telling: Lobster is slower on the shortest 28-base sequence, but for longer sequences it often wins by two orders of magnitude, which is exactly the regime where symbolic scaling matters.

The discrete results are also useful because they show Lobster is not merely “acceptable despite generality.” On transitive closure, it consistently beats the CPU-only Souffle and is often competitive with or better than FVLog, the closest GPU discrete engine. On Same Generation, Lobster is at least `2x` faster than FVLog on every completed dataset, though both systems hit out-of-memory cases on some graphs. Overall, the evaluation supports the paper’s thesis: the design is not a one-off accelerator for one provenance mode, but a reusable GPU execution substrate for tagged Datalog.

## Novelty & Impact

Relative to _Li et al. (PLDI '23)_, Lobster’s main step is moving Scallop-style neurosymbolic semantics onto GPUs rather than improving the language surface. Relative to _Shovon et al. (USENIX ATC '23)_ and later FVLog work, Lobster’s novelty is adding provenance-aware probabilistic and differentiable execution instead of accelerating only discrete Datalog. Relative to _Manhaeve et al. (NeurIPS '18)_, it treats symbolic execution as a systems bottleneck to be compiled and optimized, not just as a reasoning abstraction.

That combination makes the paper important to two communities. For neurosymbolic researchers, it expands the scale of problems that Datalog-based methods can plausibly handle. For systems researchers, it is an existence proof that provenance-rich logic execution can be mapped onto GPUs without abandoning compiler structure.

## Limitations

The paper is honest that Lobster is not fully general. Its most obvious semantic restriction is the absence of full `top-k-proofs`; `top-1-proof` is a useful but narrower approximation. Proof sizes must also be bounded in advance, which the authors set to 300 for their experiments. The best join optimization, hash reuse through static registers, relies on linear-recursive structure where one join input is fixed across iterations, so the benefit is workload dependent.

There are also systems limitations. The engine parallelizes within relational operators, not across operators, and the paper explicitly says pipelining operators did not help because there was little CPU-GPU transfer to hide. Some datasets still run out of memory, especially in the discrete comparisons, which is a reminder that generality and provenance tracking carry storage cost. Finally, the implementation inherits Scallop’s front-end and query planner, so Lobster is best understood as a new execution substrate rather than a full neurosymbolic language stack built from scratch.

## Related Work

- _Li et al. (PLDI '23)_ — Scallop provides the Datalog-based neurosymbolic language that Lobster accelerates; Lobster keeps similar semantics but replaces CPU execution with a GPU-oriented IR and runtime.
- _Shovon et al. (USENIX ATC '23)_ — iterative relational algebra on GPUs motivates Lobster’s hash-join approach, but Lobster adds provenance-tag propagation and differentiable/probabilistic semantics.
- _Sun et al. (2025 arXiv)_ — FVLog is the closest discrete GPU Datalog engine; Lobster is more general and often competitive, but pays extra memory cost for that generality.
- _Manhaeve et al. (NeurIPS '18)_ — DeepProbLog combines neural and symbolic reasoning, while Lobster focuses on making the symbolic core itself fast enough to stop being the bottleneck.

## My Notes

<!-- empty; left for the human reader -->

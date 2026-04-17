---
title: "Finding Reusable Instructions via E-Graph Anti-Unification"
oneline: "Uses e-graph anti-unification to find semantically reusable, vectorizable custom instructions and choose Pareto-optimal ones with a hardware-aware cost model."
authors:
  - "Youwei Xiao"
  - "Chenyun Yin"
  - "Yitian Sun"
  - "Yuyang Zou"
  - "Yun Liang"
affiliations:
  - "School of Integrated Circuits, Peking University, Beijing, China"
  - "Peking University, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790162"
code_url: "https://github.com/pku-liang/ISAMORE"
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

ISAMORE is a custom-instruction discovery framework that treats reusable instructions as semantic patterns, not just syntactically similar hotspots. It encodes LLVM IR into a structured e-graph, uses phased equality saturation plus anti-unification to mine common patterns, and then picks instruction sets with a profiling-driven hardware cost model. On the paper's benchmarks it reaches up to `2.69x` speedup, while its library and hardware case studies suggest the method scales beyond toy kernels.

## Problem

The paper targets a familiar pain point in ASIP and RISC-V specialization: useful custom instructions still depend heavily on human insight, while prior automation solves a weaker proxy problem. Fine-grained approaches enumerate convex subgraphs inside basic blocks; coarse-grained ones merge hotspots such as whole basic blocks. Both mostly optimize for local frequency or syntactic similarity rather than for reuse across a domain.

That distinction matters because custom instructions consume area and integration effort. A large instruction that accelerates one hotspot but appears only a few times is often a poor trade. The authors show this on CImg: syntactic merging yields an oversized instruction reused at only 8 sites, while their semantic approach finds instructions reused 93 times on average and achieves better speed with much less area. Prior work also stays mostly scalar, so it misses data-level parallelism. Simply applying existing e-graph anti-unification such as LLMT also fails in practice, because general programs contain control flow, equality saturation can blow the e-graph up exponentially, and exhaustive anti-unification over e-class pairs becomes intractable.

## Key Insight

The paper's core claim is that reusable custom instructions can be discovered as anti-unified patterns over semantically equivalent e-classes, provided the program is encoded in a structure that preserves both dataflow and enough control-flow semantics. Once equality saturation exposes equivalent rewrites, anti-unification can generalize them into patterns that must occur at least twice, which bakes reuse directly into the search objective. This sees through syntactic accidents, for example turning expressions like `a*2 + b*2` and `(1+i)<<1` into the same underlying pattern after rewrites. The paper then extends that idea to parallelism: repeated scalar instances in one basic block can be packed into vector lanes and mined again as vectorizable patterns.

## Design

ISAMORE starts by lowering LLVM IR into a structured DSL with arithmetic and memory operators plus explicit `If`, `Loop`, `List`, `Get`, `Vec`, and `App` constructs. That is the key move that lets the system put general programs, not just straight-line expressions, into an e-graph. The DSL is strongly typed, and the type information later helps prune impossible anti-unification pairs.

The main RII loop is phase-oriented. Instead of saturating the e-graph with every rewrite at once, ISAMORE applies carefully chosen rulesets over multiple phases. It fully saturates early integer and floating-point phases, then uses bounded applications of non-saturating rules later. Previously discovered patterns are also re-applied as rewrites, so later phases can build more reusable patterns out of earlier ones.

Scalability comes from "smart AU." ISAMORE pairs only e-classes with consistent result types and similar 64-bit structural hashes, then samples representative anti-unification outputs instead of keeping every pattern. Vectorization is handled by packing scalar seeds from the same basic block into `Vec` nodes, expanding vector structure with rewrites, and pruning cycles such as `Get -> Vec -> Get`. A hardware-aware selector then combines profiled cycles-per-operation with HLS latency and area estimates to keep Pareto-optimal instruction sets, followed by a final extraction pass that refines the chosen solutions.

## Evaluation

The evaluation is solid because it tests both tractability and end-to-end usefulness. On nine kernels plus an "All" composition benchmark, vanilla LLMT consistently runs out of memory above the paper's `30GB` cap, while RII keeps runs within `145s` and `799MB`. Against `ENUM`, `NOVIA`, and a `NoEqSat` ablation, the paper also makes a good faith fairness effort by aligning I/O constraints and even updating NOVIA with ISAMORE's profiling-driven cost model.

The results support the central claim. ISAMORE's maximum-speedup solutions are on average `1.52x` better than NOVIA's, with benchmark-wise gains ranging from `1.12x` to `1.94x`. Relative to `NoEqSat`, it achieves on average `1.12x` higher maximum speedup while using `84.9%` of the area, which is strong evidence that semantic equivalence helps. The library studies show the same pattern at larger scale: `1.39x` over NOVIA on `liquid-dsp`, `1.18x` on CImg with only `975 um^2`, and `1.64x` on PCL with up to `2.73x`. The hardware case studies remain concrete rather than speculative, with `2.15x` speedup for BitNet `BitLinear` and `5.15x` for CRYSTALS-KYBER.

## Novelty & Impact

Relative to _Trilla et al. (MICRO '21)_, ISAMORE optimizes for semantic reuse rather than syntactic basic-block merging. Relative to _VanHattum et al. (ASPLOS '21)_, it uses e-graphs to invent new reusable instructions instead of mapping code onto an existing vector ISA. Relative to _Melchert et al. (ASPLOS '23)_, it stays focused on ISA-level reusable instruction discovery rather than processing-element design-space exploration. The lasting idea is therefore not one particular instruction set, but a workflow that connects program equivalence reasoning, reuse-aware mining, and hardware cost estimation in a single loop.

## Limitations

The system is heuristic throughout, and the paper is open about that. Phase scheduling, similarity thresholds, AU sampling, and acyclic pruning all trade completeness for tractability, so globally best patterns can be missed. The vectorization path also depends on LLVM exposing the right scalar structure; the paper notes that `2DConv` misses some DLP because bounds checks block if-conversion. The hardware model is practical but still approximate, since selection uses profiled software costs plus an HLS estimator at a `1GHz` target and refines only the chosen solutions. Deployment is also non-trivial: the nicest results rely on RoCC integration, RTL simulation, and OpenROAD physical design, so the framework is better suited to offline processor specialization than lightweight just-in-time customization.

## Related Work

- _Trilla et al. (MICRO '21)_ — NOVIA discovers inline accelerators by syntactic merging of hotspot regions, while ISAMORE searches for semantically equivalent reusable patterns across a domain.
- _VanHattum et al. (ASPLOS '21)_ — Diospyros uses equality saturation to target existing DSP vector instructions; ISAMORE uses related machinery to create new custom instructions.
- _Melchert et al. (ASPLOS '23)_ — APEX mines frequent subgraphs for processing-element exploration, adjacent to this paper's goal but not centered on semantic anti-unification for ISA extensions.
- _Coward et al. (ASPLOS '24)_ — SEER applies e-graph rewriting inside high-level synthesis, whereas ISAMORE applies e-graphs earlier to discover what hardware instructions are worth building.

## My Notes

<!-- empty; left for the human reader -->

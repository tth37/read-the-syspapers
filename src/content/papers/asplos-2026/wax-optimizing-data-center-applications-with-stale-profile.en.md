---
title: "Wax: Optimizing Data Center Applications With Stale Profile"
oneline: "Maps stale profiles onto fresh binaries by combining debug info, source-code alignment, and source-aware function/basic-block matching."
authors:
  - "Tawhid Bhuiyan"
  - "Sumya Hoque"
  - "Angélica Aparecida Moreira"
  - "Tanvir Ahmed Khan"
affiliations:
  - "Columbia University, New York, NY, USA"
  - "Microsoft Research, Redmond, WA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790248"
code_url: "https://github.com/ice-rlab/wax"
tags:
  - compilers
  - datacenter
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Wax tackles a practical PGO problem: production teams often optimize today's binary with last release's profile, but most of that profile is already stale. The paper argues that binary-only matching is too brittle for C++ applications because names, inlining decisions, and basic-block contents drift quickly across releases. Wax therefore uses source code and debug information as a more stable anchor, then maps stale functions and basic blocks onto the fresh binary well enough to recover most of the benefit of a fresh profile.

## Problem

The paper starts from a deployment reality at Google- or Meta-like operators: frontend stalls from large code footprints waste a meaningful amount of CPU efficiency, so teams rely on profile-guided code layout tools such as AutoFDO, BOLT, and Propeller. The catch is that representative profiles can only be collected from live traffic, which means the profile always lags the binary that is about to be deployed. In the release cadence the paper targets, source code changes every one or two weeks, and prior work reports that `70-92%` of samples can become stale over that interval.

That staleness matters because layout optimizers need a concrete mapping from the stale binary's hot functions and basic blocks to the fresh binary's code. The paper shows that the then-state-of-the-art stale-profile approach by Ayupov et al. recovers only a fraction of fresh-profile benefit: across `gcc`, `clang`, `mysql`, `postgresql`, and `mongodb`, stale-profile optimization yields `3.9%-18.6%` speedups, while fresh profiles yield `7.64%-38.45%`. The authors argue that the loss is not because stale profiles are useless in principle, but because the mapping layer fails before the optimizer ever sees the right hot paths.

Two failure modes dominate. Function mapping by mangled-name edit distance breaks when namespaces, basenames, parameters, or LTO suffixes change, creating name ambiguity; the paper reports that prior work can miss `2%-33.9%` of function samples for this reason. Basic-block mapping by binary hash is similarly fragile: small source edits, opcode changes, or different inlining decisions perturb instruction content and CFG neighborhoods enough to strand `9.5%-39.3%` of basic-block samples. The systems problem is therefore to make stale profiles usable again without requiring a fresh online profiling pass for every release.

## Key Insight

Wax's core claim is that profile staleness is not fundamentally a binary-similarity problem. In the compilation pipeline, the source tree and debug metadata already connect machine code back to files and lines, and those anchors change more gracefully across versions than raw mangled names or hashed basic blocks. If stale and fresh binaries are aligned through source locations first, the profile can survive many binary-level changes that defeat prior techniques.

That argument has two important consequences. First, function identity should be reconstructed component by component rather than as a single opaque string: the source file often stays stable even when parameters or LTO partitions change. Second, basic blocks should be matched through the source locations of their instructions, not just through whole-block hashes, because function inlining and small edits frequently change block boundaries without destroying the underlying source correspondence. In short, Wax treats debug information as a bridge between stale profile samples and fresh generated code.

## Design

Wax has three modules: Function Mapping, Source Mapping, and Basic-block Mapping. Function Mapping begins with easy wins by pairing functions whose mangled names are identical. For the remaining stale functions that still carry profile samples, Wax first maps source files by path names, parent directories, and Levenshtein similarity when needed. Inside a matched file pair, it demangles function names and compares namespace, basename, parameters, and suffix step by step, restarting whenever a new 1-to-1 match is discovered. This is deliberately more structured than a single edit-distance comparison, because the characterization showed that different name components drift at different rates.

Source Mapping then builds a finer-grained bridge between stale and fresh source trees. Wax maps source files, reads their lines, and first locks in exact line matches. Those exact matches partition the search space so remaining lines are only compared inside plausible regions, after which Wax uses sequential matching and fuzzy matching for the rest. The paper distinguishes source lines from source locations: a source location is a `(mapped function, file, line)` tuple. That distinction matters because the same line may appear in multiple functions after inlining, so basic-block matching needs function context as well as textual line identity.

Basic-block Mapping is the most technical part. Using debug information, Wax groups stale and fresh instructions into partitions induced by mapped source locations. Within each partition it matches instructions by opcode and operand similarity, prioritizing opcode and breaking ties by sequential order. It then lifts those instruction matches to basic-block matches by summing instruction similarities for every stale/fresh block pair. Ambiguity is resolved first by control-flow neighbors that are already mapped, and finally by preserving sequential order inside the containing function. This design avoids whole-block hashing, which is exactly what the paper identified as too brittle under inlining and small source edits.

The implementation is intentionally practical rather than invasive. Wax is a Python tool that reads symbols and debug info with LLVM utilities, adds a small amount of LLVM code to extract CFG/basic-block data, and then feeds the mapped stale profile to existing optimizers such as BOLT or Propeller. The contribution is therefore not a new optimizer, but a profile-translation layer that lets existing optimizers make better decisions.

## Evaluation

The evaluation uses five open-source applications with large code footprints as stand-ins for production data-center binaries: `gcc`, `clang`, `mysql`, `postgresql`, and `mongodb`. Experiments run on an Intel Platinum 8380 server with LBR-based profiling. The baseline flow follows prior work closely: compile stale and fresh binaries, collect stale and fresh profiles, then optimize the fresh binary with BOLT. This is a sensible setup because it isolates whether Wax improves stale-profile mapping rather than changing the optimizer itself.

The headline result is strong. Wax delivers `5.76%-26.46%` speedups across the five applications, averaging `14.32%`, which the authors report as `77.14%` of the `18.56%` average speedup obtained with fresh profiles. Against Ayupov et al., Wax improves absolute speedup by `1.20%-7.86%`. The paper also backs that result with mapping evidence: for example, on `gcc` it maps `166,669` of `166,943` stale function samples versus `110,127` for prior work, and `2,977,511` of `3,598,300` basic-block samples versus `1,562,178`. Similar gains appear across the other applications.

I found the secondary experiments useful because they test whether the mechanism is robust rather than overfit. Wax continues to outperform prior work across multiple `mysql` query mixes, across both minor and major version gaps for `mysql` and `gcc`, and across binaries compiled with additional optimizations like inlining, `LTO`, and `AutoFDO`. The microarchitectural measurements also line up with the paper's story: Wax reduces more L1I, L2I, iTLB, and BTB misses than prior techniques. On the cost side, the full source-plus-debug pipeline takes up to `3.25` minutes and `48.4 GB` of memory, which is not trivial but still reasonable for an offline release-time optimization step.

## Novelty & Impact

Relative to _Ayupov et al. (CC '24)_ and older binary-matching work such as _Wang et al. (JILP '00)_, Wax's novelty is not just "better matching," but the reframing that stale-profile recovery should exploit the source/debug information already present in modern PGO toolchains. Relative to _Panchenko et al. (CGO '19)_, Wax is complementary to BOLT: it improves the profile handoff rather than the binary optimizer. Relative to online systems like _Zhang et al. (MICRO '22)_, it argues that an offline stale-profile pipeline can still beat an online optimizer if the mapping layer is strong enough.

That makes the paper relevant to two communities. Compiler and binary-optimization researchers can view it as a new way to propagate profile information across versions. Datacenter performance engineers can view it as a pragmatic release-engineering tool: if fresh-profile collection is operationally slow, Wax recovers much of the missing benefit without changing the serving path.

## Limitations

Wax inherits the limits of the environment it assumes. It depends on source code and usable debug information for both stale and fresh builds, so it is less applicable to stripped third-party binaries or pipelines where debug fidelity is poor. The paper explicitly notes that aggressive optimizations can degrade debug quality, even though Wax still maps most identical functions and basic blocks in its experiments.

The evaluation is also narrower than the motivating narrative. The five applications are reasonable open-source proxies, but they are not the warehouse-scale proprietary services invoked in the paper's introduction. Most main comparisons use one stale-to-fresh step per application, then use sensitivity studies for larger version gaps. Finally, the prototype's memory use can reach tens of gigabytes, which is acceptable for offline optimization but may be awkward in smaller build environments.

## Related Work

- _Ayupov et al. (CC '24)_ — The closest direct baseline; it propagates stale profiles with binary-only similarity, while Wax adds source- and debug-aware mapping to recover many more stale samples.
- _Panchenko et al. (CGO '19)_ — BOLT is the post-link optimizer Wax feeds; Wax does not replace BOLT, but improves the quality of the profile information BOLT receives.
- _Shen et al. (ASPLOS '23)_ — Propeller performs profile-guided relinking, and the paper shows that Wax's mappings also help Propeller optimize `clang` with stale profiles.
- _Zhang et al. (MICRO '22)_ — OCOLOS avoids staleness with online optimization, whereas Wax shows that a stronger offline mapping pipeline can outperform that online approach in the paper's `mysql` experiment.

## My Notes

<!-- empty; left for the human reader -->

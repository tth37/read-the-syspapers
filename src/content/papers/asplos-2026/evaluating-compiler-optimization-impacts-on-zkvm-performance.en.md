---
title: "Evaluating Compiler Optimization Impacts on zkVM Performance"
oneline: "Measures 64 LLVM passes on RISC-V zkVMs, shows dynamic instruction count and paging dominate proof cost, and finds small zkVM-aware tweaks can beat stock -O3."
authors:
  - "Thomas Gassmann"
  - "Stefanos Chaliasos"
  - "Thodoris Sotiropoulos"
  - "Zhendong Su"
affiliations:
  - "ETH Zürich, Zürich, Switzerland"
  - "Centre for Blockchain Technologies, University College London, London, United Kingdom"
  - "zkSecurity, New York, United States"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790159"
tags:
  - compilers
  - pl-systems
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

This paper is a compiler study, not a new zkVM. It measures how 64 LLVM passes, standard `-O` levels, and autotuned pass sequences behave on two production RISC-V zkVMs, and shows that the right mental model is proof cost, not CPU microarchitecture. Standard optimization still helps, but much less than on x86; once the compiler is nudged to care about dynamic instruction count and paging, it can beat stock `-O3`.

## Problem

zkVMs promise a practical way to build zero-knowledge applications: developers write ordinary Rust or C, compile to RISC-V, and let the zkVM emulate the binary while producing a proof. That convenience comes with inherited baggage. The same LLVM pipeline that was tuned for caches, branch predictors, instruction-level parallelism, and out-of-order execution is now targeting a machine whose dominant costs are proving constraints and page movement during trace generation.

That mismatch matters because performance is the main bottleneck for zkVM deployment. The paper points out that every percentage point saved in zkVM execution or proving time can translate into seconds or minutes, whereas many familiar compiler heuristics are optimizing hardware effects that zkVMs simply do not have. The core question is therefore not whether LLVM helps at all, but which optimizations still make sense once execution is replayed inside a proof system and which ones quietly become counterproductive.

## Key Insight

The main claim is that zkVM performance is driven primarily by two low-level costs: how many instructions the guest actually executes, and how much paging overhead the zkVM incurs while replaying that execution. Once the paper measures passes through that lens, many otherwise puzzling results become understandable. Passes that reduce dynamic instruction count tend to help. Passes that introduce extra address computation, stack spills, or page traffic often hurt, even when they are classically good CPU optimizations.

This is why standard LLVM optimization levels still deliver substantial wins, but smaller ones than on x86. LLVM is not fundamentally wrong; it is just using the wrong cost model. The study's lasting insight is that zkVM-aware compilation does not require replacing the whole toolchain. It requires retuning existing passes so their heuristics target proof-centric costs instead of nonexistent microarchitectural ones.

## Design

The paper's design is a systematic measurement workflow over two production RISC-V zkVMs, RISC Zero and SP1. The benchmark suite has 58 programs drawn from PolyBench, NPB, SPEC CPU 2017, and several zkVM-oriented crypto suites, plus small targeted programs such as `sha256`, `regex-match`, and `loop-sum`. Across them, the authors evaluate 71 optimization profiles: an unoptimized baseline, six standard LLVM optimization levels, and 64 individual LLVM passes applied in isolation. For isolated-pass experiments, they also disable Rust MIR optimizations so the baseline is clean.

They measure three metrics on zkVMs: cycle count, zkVM execution time, and proving time. To compare with traditional hardware, they also run the same optimization profiles on x86 and measure native execution time. For combinations of passes, they use OpenTuner to search sequences up to depth 20, with cycle count as the fitness proxy because it is fast to measure and largely tracks the more expensive end-to-end metrics.

The paper then drills into root causes using dynamic instruction count and, for RISC Zero, paging cycles. That analysis yields four concrete principles: avoid transformations that create paging pressure; inline when it removes dynamic work but not when it triggers stack spills; unroll loops only when total executed instructions fall; and avoid branch elimination when it replaces a cheap branch with extra arithmetic that both must be proven. The authors validate those principles with simplified examples and a small prototype LLVM patch set: a zkVM-aware RISC-V cost model, retuned inlining and `simplifycfg` heuristics, and disabling passes such as speculative execution and loop-data prefetch that assume CPU features zkVMs lack.

## Evaluation

The most important single-pass result is the split between `inline` and `licm`. `inline` is the best pass overall, improving proving time by `22.4%` on both zkVMs and reducing cycle count by about `30%`. `licm` is the worst, increasing execution time by `11.8%` on RISC Zero and `7.1%` on SP1, and increasing proving time by `13.5%` and `8.4%`, respectively. The paper's case studies make the reason concrete: loop transformations in LLVM's `LCSSA` form can inject extra `getelementptr`, load/store, and spill behavior, which raises both dynamic instruction count and paging overhead.

At the optimization-level granularity, the story is positive but qualified. Excluding `-O0`, standard levels never hurt on average relative to the paper's unoptimized baseline. `-O3` is the best default, improving zkVM execution time by `60.5%` on RISC Zero and `47.3%` on SP1, while improving proving time by `55.5%` and `51.1%`. That is a strong result for "just use the stock compiler," but the comparison to x86 shows these gains are still muted relative to conventional machines because the underlying pass heuristics are not proof-aware.

Autotuning shows there is still headroom beyond `-O3`. With only 160 iterations, OpenTuner already finds configurations that beat `-O3` on 18 of 58 programs on RISC Zero and 20 of 58 on SP1. On the NPB suite, longer autotuning runs improve execution and proving time by roughly `17%-19%` on average, and `npb-sp` exceeds `2x` speedup on both zkVMs. Even crypto-heavy workloads benefit despite precompiles. An especially striking by-product is that autotuning exposed a security-critical SP1 bug: a pass sequence could make the guest silently abort mid-execution while still producing a proof that verified.

The prototype LLVM changes are modest but persuasive. Fewer than 100 lines of changes make modified `-O3` beat vanilla `-O3` on 39 of 58 benchmarks on RISC Zero, for an average execution-time gain of `4.6%`, and on 19 of 58 benchmarks on SP1, for an average gain of `1%`. The best case reaches `45%` faster execution on `fibonacci`. The evaluation supports the paper's thesis well because the case studies, correlations, and patch results all line up around the same mechanism: dynamic instruction count is the dominant signal, and paging is the main secondary effect.

## Novelty & Impact

The novelty is not a new proving system, VM, or ISA. It is the first systematic pass-level study of how a mainstream compiler behaves once its output is executed inside a zkVM. That sounds narrower than a new zkVM design, but it is exactly the kind of result practitioners need: if RISC-V zkVMs are going to inherit LLVM, then someone needs to say which inherited heuristics still hold and which are optimizing ghosts.

That makes the paper useful to several audiences. zkVM vendors can mine it for immediate backend improvements. Engineers shipping proving-heavy applications can treat autotuning as a practical knob for hot code. Researchers get a sharper agenda for superoptimizers, profile-guided optimization, and zkVM-specific compiler backends. The paper is also a reminder that compiler work can move proving performance materially even when proof-system research gets more attention.

## Limitations

The paper studies only two RISC-V zkVMs, and its comparison to traditional hardware is limited to x86. That is enough to establish the mismatch with CPU-oriented heuristics, but not enough to claim universality across all zkVM designs, especially systems with custom ISAs such as Cairo-style stacks. The authors also evaluate 64 passes mostly in isolation with default parameters, which is methodologically clean but cannot cover the full phase-ordering space.

There are also measurement constraints. Some benchmarks use reduced input sizes to keep proving tractable. SP1 proving time is noisier because the prover is closed-source and accessed through RPC. The cost model based on dynamic instruction count plus paging explains most variation, but not everything; the paper itself notes proof sharding and precompile effects as additional zkVM-specific factors. Finally, the prototype LLVM changes are intentionally lightweight, so they demonstrate feasibility rather than a finished production backend.

## Related Work

- _Ben-Sasson et al. (USENIX Security '14)_ — introduces succinct proofs for a von Neumann architecture; this paper starts much later in the stack and asks how inherited compiler passes behave once VM execution is already practical.
- _Ansel et al. (PACT '14)_ — OpenTuner provides the autotuning substrate used here, but this paper contributes the zkVM-specific search space and the finding that pass autotuning can materially reduce proof cost.
- _Ernstberger et al. (SCN '24)_ — zk-Bench benchmarks ZK systems and DSLs at the proving-framework level, whereas this work isolates compiler-optimization effects inside two production zkVM toolchains.

## My Notes

<!-- empty; left for the human reader -->

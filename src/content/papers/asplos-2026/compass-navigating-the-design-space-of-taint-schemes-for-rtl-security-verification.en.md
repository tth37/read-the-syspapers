---
title: "Compass: Navigating the Design Space of Taint Schemes for RTL Security Verification"
oneline: "Applies CEGAR to RTL taint analysis, refining only the hardware locations needed to prove a given security property with lower verification overhead."
authors:
  - "Yuheng Yang"
  - "Qinhan Tan"
  - "Thomas Bourgeat"
  - "Sharad Malik"
  - "Mengjia Yan"
affiliations:
  - "Massachusetts Institute of Technology, Cambridge, Massachusetts, USA"
  - "Princeton University, Princeton, New Jersey, USA"
  - "École Polytechnique Fédérale de Lausanne, Lausanne, Switzerland"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790144"
code_url: "https://github.com/MATCHA-MIT/Compass"
tags:
  - security
  - hardware
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Compass treats RTL taint-scheme design as a CEGAR loop instead of a one-shot global choice. It starts with a coarse module-level abstraction, refines only the locations responsible for spurious taint counterexamples, and uses the resulting property-specific scheme to reduce overhead while improving verification coverage.

## Problem

Hardware information-flow tracking is attractive for RTL security verification because it turns a two-trace non-interference check into a single-trace taint check. But every practical taint scheme is an over-approximation: precise schemes blow up the instrumented design, while coarse schemes create false taint and spurious counterexamples.

The paper's key motivation is that this tradeoff is not uniform across a processor. A branch predictor behind a correct speculation defense might only need one summary taint bit for the whole module, while a reorder buffer needs finer granularity because different entries can legitimately hold different taint states. Existing schemes such as GLIFT, RTLIFT, and CellIFT each pick one global point in the design space. What users actually need is a way to derive the lightest scheme that is still precise enough for one property on one RTL design.

## Key Insight

Compass's central claim is that taint-scheme design should be treated as abstraction refinement. A coarse taint scheme is an abstraction of true information flow; a spurious taint counterexample shows where that abstraction is too coarse; and refinement should happen only at the local hardware elements responsible for the false flow.

This changes the goal from building a universally precise taint discipline to building a property-specific one. False taint becomes a debugging signal for the taint scheme itself.

## Design

Compass organizes the taint space along three axes: unit level (gate, cell, module), taint-bit granularity (per-bit, per-word, grouped/module), and logic complexity (naive, partially dynamic, fully dynamic). The framework starts from the cheapest point in that space: one taint bit per module with naive propagation.

After instrumenting the RTL, Compass model-checks a secure-speculation information-flow property. If it gets a counterexample, it asks whether the relevant signal is truly tainted or only falsely tainted. The paper gives an exact bounded model-checking formulation and then uses a faster approximation in practice: flip the secret inputs in simulation and check whether the signal value changes.

For falsely tainted sinks, Compass backtraces through the taint propagation graph. It only follows fan-ins that are both falsely tainted and observable under the concrete counterexample, which prevents the tool from wasting effort on unselected MUX inputs and similar dead ends. When the walk can no longer move upstream, that point is treated as the local source of imprecision.

Refinement then follows a fixed order: first try more dynamic logic, then finer taint-bit granularity, and only later manual higher-level customization. Each successful change acts like a cut in the false taint path, after which Compass re-simulates the counterexample and re-runs model checking. All explored schemes remain sound over-approximations, but the framework explicitly leaves correlation-based imprecision to manual handling, and the final choice among candidate refinements is still human-guided.

## Evaluation

The evaluation uses four open-source RISC-V processors: Sodor, Rocket, BOOM-S, and ProSpeCT-S. The target task is speculative-execution verification expressed as a software-hardware contract, which is a strong test because it is both security-critical and notoriously hard for formal methods.

Against CellIFT, Compass cuts average taint gate overhead from `293%` to `46%` of the original design, and taint-register-bit overhead from `100%` to `15%`. Average simulation overhead on RISC-V benchmarks falls from `351%` to `205%`. On Sodor, proof time drops from `1.6 hours` with CellIFT to `9.8 seconds` for the final scheme, or `5.2 minutes` including refinement. On Rocket, the bounded-proof depth improves from `41` cycles after seven days with CellIFT to `159` cycles in `25.3` hours including refinement. On ProSpeCT-S, Compass keeps the same `29`-cycle bound but reaches it much faster than CellIFT and self-composition. The study also found two ProSpeCT bugs that the authors confirmed and fixed.

The most convincing qualitative result is the Rocket postmortem. Compass does not uniformly refine the whole design; it spends precision at the secret/public boundary, such as cache data arrays and selector-heavy datapaths, while leaving purely public decode logic coarse.

## Novelty & Impact

Relative to _Solt et al. (USENIX Security '22)_, Compass does not propose a stronger universal taint scheme; it proposes a way to navigate among schemes and buy precision only where the property demands it. Relative to _Yang et al. (CAV '18)_, it makes CEGAR-style taint refinement concrete for RTL hardware and automates the search for refinement sites through false-taint backtracing. Relative to _Tan et al. (ASPLOS '25)_, it offers a lighter-weight alternative to self-composition for secure-speculation contracts.

The impact is methodological. Compass turns taint-scheme selection from expert trial-and-error into a guided workflow, and shows that property-specific tainting can improve both simulation throughput and model-checking scalability on realistic processors.

## Limitations

Compass is not fully automatic. It can find candidate refinement locations automatically, but humans still choose among candidate schemes in a predefined order. It also excludes correlation-based imprecision, so some false-taint patterns still need manual higher-level reasoning.

Its precision guarantee is also bounded. The paper only claims precision for the checked property up to the cycle bound reached during refinement, not for all future properties or unbounded executions. Compass also still depends on model checkers to generate spurious counterexamples, and the loop can accumulate refinements that later become unnecessary.

## Related Work

- _Solt et al. (USENIX Security '22)_ — CellIFT is the paper's main precise baseline: cell-level, per-bit, and largely fully dynamic, but still global rather than property-specific.
- _Ardeshiricham et al. (DATE '17)_ — RTLIFT provides operator-level taint tracking with a limited precision/complexity tradeoff, but it does not use counterexamples to selectively refine different RTL regions.
- _Yang et al. (CAV '18)_ — Lazy self-composition is the closest conceptual ancestor in applying CEGAR to security verification, though it targets software-style transition systems rather than RTL taint design.
- _Tan et al. (ASPLOS '25)_ — Contract Shadow Logic verifies secure speculation through self-composition; Compass shows taint refinement can reach the same contract family with better scalability.

## My Notes

<!-- empty; left for the human reader -->

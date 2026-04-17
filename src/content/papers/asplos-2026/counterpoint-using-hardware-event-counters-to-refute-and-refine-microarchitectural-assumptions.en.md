---
title: "CounterPoint: Using Hardware Event Counters to Refute and Refine Microarchitectural Assumptions"
oneline: "Checks an expert-written microarchitectural model against noisy event counters, then uses violated constraints to infer hidden hardware behavior."
authors:
  - "Nick Lindsay"
  - "Caroline Trippel"
  - "Anurag Khandelwal"
  - "Abhishek Bhattacharjee"
affiliations:
  - "Yale University, New Haven, Connecticut, USA"
  - "Stanford University, Stanford, California, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790145"
tags:
  - hardware
  - memory
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CounterPoint checks whether an expert's microarchitectural story is compatible with observed hardware event counters. It encodes the story as a `muDD`, derives the implied counter constraints automatically, and compares them against tight confidence regions built from noisy multiplexed measurements. On Intel Haswell's MMU, that process exposes likely hidden behaviors including TLB prefetching from the load-store queue, merged page-table walks, abortable walks, and evidence for a root-level MMU cache.

## Problem

Modern CPUs expose many hardware event counters, but the promise of "observe the hardware directly" breaks down in practice. Counter names are underspecified, implementations are opaque, and multiplexing introduces noise. As a result, researchers often interpret counters with ad hoc reasoning instead of a disciplined test of whether their assumed hardware model and the observed data can both be true.

The paper shows why this matters for virtual-memory hardware. Even a simple Haswell assumption such as "PDE-cache misses should not exceed page walks" fails on real measurements. As more counters are involved, the number of implied constraints grows quickly, and each constraint depends on subtle interactions among page size, cache hits, walk completion, and abort behavior.

## Key Insight

Experts should not hand-derive counter constraints. They should describe the hardware as possible `mu-op` execution paths, then let the tool derive the constraints implied by those paths. CounterPoint's `muDD` does exactly that: each path carries a counter signature, and the model is feasible only if some non-negative combination of those signatures can explain the measurements. It then uses multi-dimensional confidence regions that exploit counter correlations, so multiplexing noise does not erase genuine violations.

## Design

The workflow has three stages. First, the expert writes a compact DSL of actions, counter increments, and decision points, and CounterPoint compiles it into a `muDD`. From that graph it enumerates `mu-path` counter signatures and defines a `model cone`: the set of all counter vectors producible by non-negative flow through the diagram.

Second, CounterPoint turns noisy samples from tools such as `perf` into `counter confidence regions`. It estimates covariance across counters, constructs a 99% confidence ellipsoid, and approximates that ellipsoid with a principal-component-aligned bounding box so feasibility can still be solved with linear programming.

Third, the tool supports guided refinement. If the confidence region intersects the model cone, the observation is feasible; otherwise CounterPoint reports violated half-space constraints, and the expert adds or removes candidate hardware features. The paper frames this as a discovery phase followed by an elimination phase. The implementation is a roughly 3K-line Python library built with Pandas, pulp, and Docker.

## Evaluation

The evaluation uses the Intel Haswell MMU and focuses on data-side native execution. The workloads span GAPBS, SPEC2006, PARSEC, YCSB, plus linear and random microbenchmarks, with memory footprints from 250 MB to 600 GB and page sizes of 4 KB, 2 MB, and 1 GB. In total, the authors collect about 20 million counter samples.

The first result validates the statistical design. Across dozens of representative `muDD`s, correlated confidence regions detect over 24% more constraint violations than regions that assume independent counters, and for some models the gain exceeds 75%. More than 25% of counter pairs have Pearson correlation above 0.9. Starting from an initial Haswell model with 31 constraints, the authors find 8 violations and iterate from there.

Those violations lead to the paper's most interesting findings. CounterPoint suggests a load-store-queue-driven TLB prefetcher whose trigger depends on sequential accesses crossing a page boundary; for increasing addresses the trigger appears after cache lines 51 and 52, and for decreasing addresses after 8 and 7. The paper also argues that these prefetches use the page walker itself rather than bypassing it. The refined models further indicate that walks to the same virtual page can merge, cutting distinct walks by nearly half for some workloads; that 1 GB page workloads are consistent with a root-level MMU cache when walk bypassing is absent; and that aborted walks can happen even before any memory access is issued.

## Novelty & Impact

CounterPoint's novelty is methodological rather than architectural. It turns informal hardware assumptions into explicit path models, derives all implied constraints automatically, and uses statistically grounded counter regions to refine those models. Relative to BayesPerf or CounterMiner, the contribution is not just better denoising but denoising in service of microarchitectural feasibility testing. The paper should matter most to simulator builders, performance modelers, and researchers studying opaque CPU behavior.

## Limitations

The authors do not claim proof from first principles. Full confirmation of the Haswell behaviors would require proprietary RTL, so the results are best read as high-confidence explanations consistent with the data. The study also stays within one CPU family, data-side address translation, and native execution; multiple cores, multiple sockets, hyperthreading, kernel activity, and accelerators are left to future work.

Methodologically, CounterPoint depends on a rich workload set and a feature space broad enough to expose the missing behavior. The refinement loop is expert guided rather than fully automatic, and the confidence region uses a box approximation around an ellipsoid, which is tractable but potentially looser than more exact formulations.

## Related Work

- _Lindsay and Bhattacharjee (IISWC '24)_ - studies address-translation scaling with hardware counters, whereas CounterPoint turns counter interpretation into a reusable model-checking workflow.
- _Banerjee et al. (ASPLOS '21)_ - BayesPerf reduces PMU measurement error statistically; CounterPoint similarly exploits structure in noisy counters but uses it to build feasibility regions for microarchitectural models.
- _Zhao et al. (USENIX Security '22)_ - Binoculars uses counters to analyze page-walker contention, while CounterPoint targets the broader problem of finding which hidden MMU features make the observations possible.
- _Hsiao et al. (MICRO '24)_ - RTL2MuPATH synthesizes microarchitectural paths from RTL, whereas CounterPoint starts from expert-authored `muDD`s and checks them against real hardware measurements.

## My Notes

<!-- empty; left for the human reader -->

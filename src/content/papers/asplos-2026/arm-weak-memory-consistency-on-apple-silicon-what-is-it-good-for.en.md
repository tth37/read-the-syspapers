---
title: "Arm Weak Memory Consistency on Apple Silicon: What Is It Good For?"
oneline: "Tests Apple silicon's runtime TSO mode against native Arm mode and finds most slowdowns are tiny, while the big ones come from implementation quirks rather than TSO itself."
authors:
  - "Yossi Khayet"
  - "Adam Morrison"
affiliations:
  - "Tel Aviv University, Tel Aviv, Israel"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790129"
tags:
  - hardware
  - formal-methods
  - verification
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

The paper uses Apple silicon's runtime-switchable TSO mode to test, on one commercial CPU, whether Arm's weaker memory model really buys meaningful performance over TSO. On M-series chips, it usually does not: across 49 applications, TSO is typically within `3%` of Arm, and the big slowdowns mostly come from artifacts of Apple's TSO implementation rather than from inherent TSO ordering costs.

## Problem

Weak memory models such as Arm's make concurrent software, compiler mappings, and verification tools harder to reason about because they admit behaviors that x86 TSO forbids. The paper frames this as a continuing "complexity tax": Linux keeps adding explicit memory-ordering code, and weak-memory checking must consider many more executions.

That tax is only justified if it buys performance that TSO cannot realistically match. Earlier work on efficient TSO implementations suggested otherwise, but almost all of that evidence came from simulators or FPGA prototypes. Prior M1 measurements had reported larger TSO slowdowns, so the open question is whether those gaps are the true cost of stronger ordering or just artifacts of one implementation.

## Key Insight

The core proposition is that TSO need not be materially slower than Arm if the processor keeps Arm-style weak-memory optimizations whenever they are not program-visible as TSO violations. The relevant comparison is therefore not "fully conservative TSO" versus Arm, but "aggressively optimized TSO that only squashes when visibility would break TSO" versus Arm on the same silicon.

Apple's M-series CPUs make that test possible because the kernel can flip a core between Arm mode and TSO mode. That lets the authors separate architectural necessity from implementation choice: if a slowdown comes from conservative squashing logic, load/store handling, or instruction quirks, it is evidence about Apple's implementation, not about TSO in general.

## Design

This is a measurement-and-explanation paper, not a proposal for a new memory system. Its first tool is targeted microbenchmarking to reverse engineer which Arm-style optimizations Apple preserves in TSO mode. The authors show that Apple silicon still performs speculative out-of-order loads in TSO mode and squashes only when L1 invalidations imply a possible visible violation. On M4 P cores, TSO mode also lets L1-hitting stores effectively get ahead of older cache-missing stores, which shows that Apple's TSO mode does not simply turn weak-memory machinery off.

The second tool is an application study over 49 workloads from SPEC CPU 2017, PARSEC, SPLASH-2x, and OpenBenchmarking on M1 and M4 systems, with both single-core and multicore runs. The authors control P-core versus E-core placement, randomize benchmark order, and repeat runs until the `95%` confidence interval is within `1%` of the median.

## Evaluation

The headline result is that TSO mode is much closer to Arm mode than conventional wisdom suggests. On M4 P cores, excluding seven severe outliers, the harmonic mean of per-application average TSO slowdowns is `1.9%`, and most applications are within `3%`. Even with the outliers included, the overall harmonic-mean slowdown is only about `4.2%`.

The most convincing part is the root-cause analysis of the outliers. Four SPEC programs (`bwaves`, `cactuBSSN`, `wrf`, and `roms`) slow down because TSO mode's load-squash mechanism reacts badly to benign self-conflicts in L1, reducing effective memory-level parallelism; randomizing intra-page allocation offsets largely removes the problem. `fluidanimate -O0` slows down because TSO mode appears to serialize partial store-to-load forwarding pairs. On M1 P cores, `ffmpeg_x264` hits a different artifact: NEON loads larger than `16 B` become much slower in TSO mode, and that issue disappears on M4. The one outlier that does look tied to a genuinely missing optimization is `lbm` on M4 E cores, where TSO mode lacks the store-store optimization visible on P cores.

These results support the central claim because many of the worst slowdowns appear in single-core runs, where there is no possible inter-core TSO violation to begin with. That strongly suggests the dominant penalties are implementation artifacts, not unavoidable ordering costs.

## Novelty & Impact

Relative to _Guiady et al. (ISCA '99)_ and later optimized-TSO proposals, the novelty is not another simulator argument, but a direct measurement on commercial Apple hardware that can switch between Arm and TSO. Relative to _Wrenger et al. (JSA '24)_ and _Beck et al. (ASPLOS '23)_, the main advance is causal analysis: the paper traces the major slowdowns to concrete microarchitectural artifacts.

That makes the work important to both hardware and software researchers. It suggests that weak-memory ISA complexity is not obviously justified by performance on aggressive OoO cores, and gives PL and verification researchers evidence that the software cost of weaker hardware models may exceed their practical benefit.

## Limitations

The paper is deliberately scoped. It measures run time rather than power or energy, and it studies Apple's single-die M-series systems rather than simpler cores, multi-die chips, or other Arm vendors, so the conclusions are strongest for high-performance Apple silicon.

There is also a broader interpretive limit: showing that "TSO can be this fast" on Apple hardware is not the same as proving that all TSO implementations will be equally close to Arm. The workload suite is broad, but it may still miss codes that stress barriers, atomics, or coherence differently.

## Related Work

- _Guiady et al. (ISCA '99)_ — argues via simulation that strong consistency plus aggressive hardware can approach weaker models, whereas this paper tests that thesis on shipping Apple CPUs.
- _Ros et al. (ISCA '17)_ — proposes non-speculative load-load reordering for TSO; the Apple measurements support the broader idea that strong models can keep much of weak-model performance.
- _Wrenger et al. (JSA '24)_ — reports M1 TSO slowdowns on SPEC FP, while this paper expands the workload set and traces the main outliers to specific implementation artifacts.
- _Beck et al. (ASPLOS '23)_ — observes large Geekbench slowdowns on M1 TSO mode; this paper argues such gaps should not be attributed to TSO itself without root-cause analysis.

## My Notes

<!-- empty; left for the human reader -->

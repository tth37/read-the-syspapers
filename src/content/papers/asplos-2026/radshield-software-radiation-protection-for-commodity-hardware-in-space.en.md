---
title: "Radshield: Software Radiation Protection for Commodity Hardware in Space"
oneline: "Radshield uses idle-time current modeling and conflict-aware parallel triple execution to catch radiation latchups and SEUs on commodity spacecraft computers."
authors:
  - "Haoda Wang"
  - "Steven Myint"
  - "Vandi Verma"
  - "Yonatan Winetraub"
  - "Junfeng Yang"
  - "Asaf Cidon"
affiliations:
  - "Columbia University, New York, NY, USA"
  - "Jet Propulsion Laboratory, California Institute of Technology, Pasadena, CA, USA"
  - "Aptos Orbital, Palo Alto, CA, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3760250.3762218"
tags:
  - hardware
  - fault-tolerance
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Radshield argues that spacecraft using commodity Linux systems do not need to choose between no protection and fully radiation-hardened hardware. `ILD` detects latchups by comparing measured current against an idle-time current model, while `EMR` catches `SEUs` with conflict-aware parallel redundancy that avoids shared unprotected caches. The result is practical protection with much less runtime and energy overhead than naive redundancy.

## Problem

The paper starts from an economic shift in space computing. Launch costs have fallen enough that operators increasingly want many cheap satellites, and those satellites now need meaningful onboard compute for imaging, navigation, networking, and other local processing. Radiation-hardened processors remain reliable but far behind commodity chips in both performance and price, so real missions are already flying off-the-shelf Linux systems such as Raspberry Pis, x86 CPUs, and mobile SoCs.

That move creates a reliability gap. The paper focuses on the two radiation faults that operators say matter most in practice. Single-event latchups (`SELs`) create localized short circuits that raise current draw and can physically damage the chip unless the device is power-cycled. Single-event upsets (`SEUs`) flip bits or inject spurious signals, producing crashes or, worse, silent data corruption. The authors point out that these are not hypothetical corner cases: they cite damaged SmallSat computers, SEU-induced rover software failures, and prior observations of corrupted inference and cryptographic execution.

Prior mitigations are unsatisfying for opposite reasons. Existing `SEL` detectors treat the device as a black box and watch current alone, which breaks once modern CPUs naturally swing across wide current ranges due to load and DVFS; a micro-`SEL` may change current by only `0.07A`, far below ordinary variation. Existing `SEU` mitigation mostly relies on sequential triple modular redundancy (`3-MR`) or checksumming, which is costly in runtime, energy, and heat. For spacecraft with limited power and thermal headroom, that overhead directly cuts useful mission work.

## Key Insight

The paper's core idea is that radiation protection improves once the system stops treating the computer as a black box. For `SELs`, the useful question is not whether current is absolutely high, but whether measured current is unexpectedly high given what the machine is doing right now. Because spacecraft spend much of their time idle between bursts of work, Radshield can look for latchups during quiescent periods where normal current is stable enough that small anomalies become visible.

For `SEUs`, the key proposition is that parallel redundancy only works if the redundant copies do not accidentally share the same vulnerable state. Running three copies simultaneously is attractive because it shrinks exposure time, but naive parallelism lets all replicas touch the same unprotected cache lines, so one cache upset can fool every copy at once. Radshield's answer is to reason about data overlap explicitly: redundant jobs may run in parallel only when their working sets do not conflict below the reliability frontier.

## Design

Radshield has two components. `ILD` handles latchups. It reads real current from the spacecraft's power monitor instead of using CPU-estimated power counters, collects OS-visible performance metrics every millisecond, and uses a lightweight linear model to predict what current should be. The chosen features include instruction completion, bus cycles, frequency, branch misses, cache hits, and disk I/O. Detection is restricted to quiescent windows, because maintenance activity during idle periods has far lower variance than application execution. If long jobs run without natural idle time, `ILD` injects three-second "bubbles" of quiescence and then pauses further injections for three minutes if nothing suspicious is found. It also tracks a rolling minimum current around each sample to filter transient spikes before deciding to reboot.

`EMR` handles upsets. Developers express a workload as repeated execution of the same function over many datasets, each dataset being a collection of memory regions. Radshield turns those into jobs, creates three redundant executors, and automatically detects conflicts when two jobs would access overlapping memory. Non-conflicting jobs are grouped into jobsets and can run in parallel; conflicting jobsets run at different times, with cache lines flushed between them so an upset in shared cache state cannot contaminate multiple replicas.

The reliability-frontier abstraction is the design's most important systems concept. Anything on the protected side of the frontier, such as ECC storage and sometimes ECC DRAM, is assumed trustworthy and does not need triplication. Everything past that frontier, including pipelines, caches, and sometimes DRAM, must be protected by software redundancy. This lets the same runtime adapt to different spacecraft hardware rather than hard-coding one policy. To reduce the cost of cache flushes, EMR also replicates frequently shared "common data" such as an encryption key or template image into executor-local memory. The implementation stays in userspace on unmodified Linux, which matches the paper's deployment goal.

## Evaluation

The evaluation separates `ILD` and `EMR` and is grounded in realistic hardware. `ILD` is tested on a Raspberry Pi Zero 2 W matching the authors' SmallSat deployment, with latchups emulated by adding a controlled parallel resistor and running a real flight-software workload. Over `960` hours, `ILD` misses no induced `SELs`, while the black-box baselines fare badly. The paper also shows a sensitivity sweep where `ILD` reaches zero false negatives once added latchup current exceeds `0.05A`, below the minimum `0.07A` micro-latchup reported in prior work. Runtime overhead while under load is about `3%`, and the worst-case overhead from induced idle bubbles is about `2%`.

`EMR` is evaluated on five representative workloads: AES encryption, DEFLATE compression, regex-based intrusion detection, image processing, and a neural-network benchmark. Against sequential `3-MR`, EMR delivers the same correctness target with much better efficiency because it parallelizes compute and amortizes cache clears. Across workloads, the paper reports an average `63%` reduction in runtime overhead and `60%` lower energy use than state-of-the-art protection. The detailed plots show that EMR remains only `7-77%` slower than an unsafe parallel baseline while still protecting the full vulnerable region, whereas protected `3-MR` is dramatically slower. The reliability-frontier study also matters: storing trusted state in DRAM is much faster than falling back to disk, but EMR still beats `3-MR` in both regimes. Fault injection on the image-processing workload finds no silent data corruptions for either `EMR` or `3-MR`; both schemes only expose a tiny residual vulnerability window during final result comparison.

The evaluation supports the paper's main claim well. The workloads are diverse enough to exercise different conflict graphs and data-sharing patterns, not just one hand-picked kernel, and the Mars deployment anecdote strengthens the "this is actually usable" story. The main caveat is that some of the reliability evidence is indirect: cache faults are reasoned about analytically and through runtime structure because the QEMU-based injector cannot faithfully target cache state.

## Novelty & Impact

Relative to _Dorise et al. (RADECS '21)_, Radshield's `SEL` contribution is to stop classifying current spikes in isolation and instead predict current from software-visible execution state during quiescence. Relative to _Shen et al. (DSN '19)_, its `SEU` contribution is not just multicore redundancy, but conflict-aware scheduling over memory regions so shared unprotected caches do not defeat parallel voting. Relative to checksum-based mitigation such as _Borchert et al. (DSN '23)_, Radshield aims for a more general runtime that operators can deploy across mixed spacecraft workloads without per-application redesign.

That makes the paper notable for both architecture researchers and space-systems practitioners. Its impact comes from reframing the deployment baseline: if commodity hardware in space is already reality, the right comparison is what software can make safe enough today.

## Limitations

Radshield is deliberately a best-effort userspace mitigation, not end-to-end protection. The kernel is mostly out of scope, and the authors rely on operational arguments that spacecraft workloads spend negligible time there. If a mission has more kernel activity, device-driver complexity, or interrupt load than the paper's target setting, that assumption weakens. `ILD` also depends on hardware exposing trustworthy current telemetry and on having enough idle time, natural or injected, to observe latchups before heat damage accumulates.

`EMR` assumes a specific workload structure: repeated computation over many datasets with analyzable overlap. That covers important image-processing, crypto, and pattern-matching workloads, but not every onboard application. Performance also depends heavily on where the reliability frontier sits and how much common data can be profitably replicated. The paper's fault-injection methodology cannot inject cache-only corruption directly, so part of the argument rests on design reasoning rather than direct measurement.

## Related Work

- _Dorise et al. (RADECS '21)_ — uses machine learning to detect radiation high-current events from current traces alone, while Radshield adds white-box execution-state features and idle-time detection logic.
- _Shen et al. (DSN '19)_ — explores redundant execution on COTS multicores for fault tolerance, but Radshield extends the idea to data-flow correctness under shared-cache conflicts.
- _Borchert et al. (DSN '23)_ — compiler-implemented differential checksums protect memory values, whereas Radshield targets a broader runtime model that also covers cache and pipeline upsets.
- _Wang et al. (HotNets '23)_ — motivates software protection against space radiation at a higher level; Radshield turns that line of thought into a deployable two-part system with ground evaluation and flight deployment.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Tintin: A Unified Hardware Performance Profiling Infrastructure to Uncover and Manage Uncertainty"
oneline: "Tintin turns hardware-counter multiplexing error into runtime uncertainty and uses first-class profiling contexts to schedule events and attribute them precisely."
authors:
  - "Ao Li"
  - "Marion Sudvarg"
  - "Zihan Li"
  - "Sanjoy Baruah"
  - "Chris Gill"
  - "Ning Zhang"
affiliations:
  - "Washington University in St. Louis"
conference: osdi-2025
code_url: "https://github.com/WUSTL-CSPL/tintin-kernel"
project_url: "https://github.com/WUSTL-CSPL/tintin-user"
tags:
  - observability
  - kernel
  - hardware
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Tintin is a Linux kernel profiling infrastructure for hardware performance counters that attacks two failures at once: multiplexing error when too many events compete for too few counters, and misattribution when existing tools can only profile tasks or cores. Its core move is to estimate measurement uncertainty online, schedule events to minimize that uncertainty, and represent arbitrary profiling scopes as first-class Event Profiling Contexts (ePXs).

## Problem

The paper starts from a basic mismatch. Modern CPUs expose dozens to thousands of event types, but a core usually has only 2-6 programmable counters, and Linux often reserves one of them. Real applications still want many events at once: derived metrics such as Intel Top-Down categories or Pond’s latency-sensitivity model can require tens of raw counters. Linux `perf_event` handles that overload by round-robin multiplexing, then interpolates totals. The authors show that once the number of requested events exceeds the available counters, reported counts become noticeably unstable.

Attribution is the second problem. Counters are just per-core devices, so the OS has to decide which execution scope should receive a measured event. Existing infrastructure binds events to tasks or cores, which is too coarse for code-region profiling and too rigid for overlapping scopes such as "this VM" plus "this function" plus "this core." That leads to two pathologies: unrelated work gets charged to the target scope, and overlapping scopes can starve one another because `perf_event` schedules them independently. The DMon example in the paper makes this concrete: coarse whole-program aggregation can hide the loop that is actually backend-bound.

## Key Insight

Tintin’s main claim is that multiplexing error is not an opaque artifact that user space must simply tolerate. Because interpolation error grows when event rates vary during the time an event is not being measured, the kernel can estimate expected error online from observed variance and surface it as uncertainty alongside the count. Once uncertainty is explicit, scheduling events becomes an optimization problem rather than a fixed round-robin policy.

The second insight is architectural rather than statistical: profiling scope should be elevated into its own kernel object. If code regions, threads, processes, VMs, and user-defined combinations are all translated into one common abstraction, the kernel can jointly manage overlapping scopes, place measurement calipers at the right boundaries, and attribute the same raw hardware reading to multiple active scopes when appropriate.

## Design

Tintin has three cooperating components. `Tintin-Monitor` reads counters, interpolates multiplexed counts with a trapezoid-area method, and treats expected count error as the square root of variance over the event’s unmonitored time. Because the kernel cannot afford full-history recomputation, it uses a weighted version of Welford’s incremental variance update. The implementation runs from `hrtimer`, hooks existing `perf_event` PMU interfaces, and uses fixed-point arithmetic to avoid floating-point work in the kernel.

`Tintin-Scheduler` turns the measurement problem into weighted elastic scheduling. Each event gets a utilization share, meaning the fraction of time it occupies a hardware counter, and the scheduler minimizes the sum of weighted squared normalized errors subject to the limited number of counters. The paper maps this to elastic scheduling theory, extends the solver to multiple counters by building one virtual resource, then lays out per-counter time slices over a repeating hyperperiod. It also supports event groups, a simpler "Uncertainty-First" fallback policy, and a minimum scheduling quantum to avoid unstable tiny slices and excessive timer interrupts.

`Tintin-Manager` solves attribution. Its Event Profiling Context, or ePX, is a first-class object that bundles a scope and its events. An ePX can denote a thread, process, core, VM, function, or a user-defined association of several of them. For execution scopes, Tintin listens to CPU scheduling events; for code scopes, it inserts syscalls at entry and exit points so counting is enabled only inside the target region. When multiple ePXs overlap, Tintin jointly schedules their event sets, keeps counts and uncertainty separately per ePX, and attributes a counter read to every active ePX that asked for that event. The exposed API largely mirrors `perf_event`, with extensions for creating contexts, associating them, changing weights, and reading uncertainty.

## Evaluation

The evaluation supports the paper’s central claim that uncertainty-aware scheduling and richer scope control materially improve online profiling. On SPEC CPU 2017 and PARSEC, Linux `perf_event` has 9.01% average count error against pinned-counter ground truth, and CounterMiner’s cleaned results are similar at 8.80%. Tintin’s elastic scheduling lowers that to 2.91% on average; the simpler Uncertainty-First policy helps too, but only reaches 6.51%. Runtime cost stays low: Tintin averages 2.4% overhead versus 1.9% for `perf_event`, while the CPU implementation of BayesPerf is far too heavy, reaching up to 31.3%.

The case studies show why attribution matters, not just raw count accuracy. In Pond’s resource-orchestration emulator, using Tintin’s VM-thread scope improves prediction scores in 95 of 100 trials, by 0.51 on average over Intel EMON’s core-scoped baseline. Elastic scheduling adds another 0.15 on average over round robin, and feeding uncertainty into the model gives a smaller but still positive gain of more than 0.02. Under overlapping-scope conflicts, workload counting error rises only slightly from 3.11% to 3.56%, and Pond’s score drops by just 0.01.

For DMon, `perf_event` misses the real backend-bound code in 9 of 10 runs, while Tintin’s loop-level ePXs identify the culprit region consistently, with backend time always above 91.1%. For Diamorphine rootkit detection, the AUC rises from 0.57 with `perf_event` to 0.66 with Tintin, and to 0.70 when uncertainty is included. The evidence is broad enough for an infrastructure paper, though most application studies are still reconstructed or single-workload demonstrations rather than production deployments.

## Novelty & Impact

Relative to _Banerjee et al. (ASPLOS '21)_, Tintin does not infer unscheduled events from Bayesian models and algebraic event relations; it instead treats uncertainty as a runtime quantity the kernel can estimate cheaply for arbitrary events. Relative to _Lv et al. (MICRO '18)_, it is explicitly online rather than a multi-run offline cleaning pipeline. Relative to _Khan et al. (OSDI '21)_, it contributes a general scope primitive that tools like DMon can build on, rather than another specialized profiler. That combination makes the paper feel like systems infrastructure, not just a better heuristic.

Its likely impact is on any system that wants HPCs in the control loop, such as performance diagnosis, resource orchestration, and anomaly detection. The paper’s real contribution is reframing HPC profiling from "read whatever the counters can spare" into "surface the confidence of the measurement and make scope explicit."

## Limitations

Tintin does not make HPC data ground truth. Its uncertainty model uses variance as a proxy for interpolation error, which is reasonable but still indirect. The paper is also explicit that several uncertainty sources remain out of scope, including polling-versus-sampling tradeoffs, skid effects, architectural counter corruption, and other microarchitectural quirks. So Tintin improves one major class of error without becoming a universal correctness layer for PMUs.

There are also deployment limits. Code-region profiling currently depends on source-level or compiler-inserted instrumentation, with binary-only support left to future work. Support for PMUs where some events can only run on specific counters is limited. Scalability is good up to hundreds of events, but with 1024 event types the in-kernel sorter can make the machine unresponsive. The evaluation is also centered on Intel Skylake without Hyper-Threading, so cross-architecture behavior is argued through reuse of `perf_event` hooks more than directly demonstrated.

## Related Work

- _Banerjee et al. (ASPLOS '21)_ — BayesPerf also reduces online multiplexing error, but it relies on event relations and heavy inference; Tintin uses a general variance-based uncertainty model and an in-kernel scheduler.
- _Lv et al. (MICRO '18)_ — CounterMiner improves measurements by mining and cleaning multi-run traces offline, whereas Tintin is designed for one-shot online control loops.
- _Khan et al. (OSDI '21)_ — DMon shows why precise attribution matters for diagnosing locality bugs; Tintin provides the scope abstraction that makes such attribution reliable.
- _Demme et al. (ISCA '13)_ — Prior malware detection work consumes HPC features at task granularity; Tintin improves the quality and confidence of those features rather than proposing a new detector.

## My Notes

<!-- empty; left for the human reader -->

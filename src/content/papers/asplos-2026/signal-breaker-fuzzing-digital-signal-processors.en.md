---
title: "Signal Breaker: Fuzzing Digital Signal Processors"
oneline: "Moves mutation, execution, and coverage filtering onto the DSP so bare-metal signal processors can be fuzzed without per-test host round trips."
authors:
  - "Cameron Santiago Garcia"
  - "Matthew Hicks"
affiliations:
  - "Virginia Tech, Blacksburg, Virginia, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790220"
code_url: "https://github.com/FoRTE-Research/SBFuzz"
tags:
  - fuzzing
  - security
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

SBFUZZ treats DSP fuzzing as a decomposition problem, not just a porting problem. It moves mutation, execution, and local coverage checks onto the DSP, and leaves the host only the rare work: crash recovery, global corpus maintenance, and binary rewriting. On 15 DSP benchmarks, that split yields `17.4x` higher throughput, `2.6x` more code coverage, and `2491` crashing inputs corresponding to `34` unique bugs.

## Problem

The paper starts from a mismatch between existing embedded fuzzers and actual DSP targets. Systems such as `uAFL` and `SHiFT` assume the target can exchange a test case and a coverage report with the host on every iteration. That is workable for richer embedded boards, but DSPs are often bare-metal Type-3 devices with small memories, low-bandwidth out-of-band interfaces, no operating-system services, and often no practical public emulator. On such hardware, host-device coordination becomes the bottleneck. That matters because DSPs sit in telecommunications, medical devices, transportation, and other cyber-physical pipelines, and their failures look like infinite loops, bus errors, or divergent-but-continuing execution rather than clean process exits.

## Key Insight

The core claim is that fuzzing duties should be split by frequency, not by convenience. Work that happens on nearly every input, such as seed selection from a local pool, mutation, execution, and local coverage checks, belongs on the DSP. Work that happens rarely, such as crash storage, global coverage merging, pool refresh, and binary rewriting, belongs on the host. Once that split is enforced, the host leaves the steady-state critical path.

The second insight is that AFL-style full bitmaps are the wrong coverage abstraction here. Most inputs are not coverage-increasing, so building and shipping a full bitmap each time wastes RAM and bandwidth. SBFUZZ instead uses what the paper calls dynamic coverage-guided tracing: it logs compact code offsets, reports only rare interesting executions, and rewrites discovered tracing sites to `NOP`s so coverage reporting gets cheaper as fuzzing progresses.

## Design

SBFUZZ has a host engine and a DSP engine. The host keeps the global seed pool, the global coverage list, crashing inputs, and a coherent copy of the instrumented binary. The DSP keeps only a local pool that fits in on-chip memory and runs an endless fuzzing loop; the host periodically refreshes that pool instead of mirroring the full corpus on-device.

Inside the loop, the DSP performs AFL-style deterministic and random mutations. The paper adds "mutation digression": after repeated cycles on one seed, only about `10%` of it is mutated at a time, on the theory that deeper coverage often needs small perturbations. Execution is persistent rather than process-per-input: the DSP saves register context, repeatedly invokes the SUT, and restores state after each iteration to avoid false crashes from leftover machine state.

Crash handling uses the hardware model directly. Timers detect hangs, interrupts catch bus and data-log errors, and a host-visible breakpoint marks the crash handler so the host can recover the input and reflash or reset the board. Coverage tracing is done with assembly-time trampoline calls that record basic-block offsets rather than full PCs. When the DSP finds a coverage-increasing input, the host merges the local trace into global coverage and rewrites those tracing sites to `NOP`s in its own binary copy, preserving coherence for later reflashes while steadily reducing tracing cost.

Communication is organized around three hardware-breakpoint coordination points rather than continuous polling: pool refresh, crash handling, and coverage-increasing execution. That detail matters because it makes the host event-driven. In the steady state, the DSP mutates and executes locally while the host waits for one of those rare conditions and can, in principle, serve multiple devices concurrently.

## Evaluation

The evaluation uses a TI `TMS320C5515` at `100MHz`, 24-hour campaigns, and five trials per benchmark. The workload set contains 15 programs: six kernels from BDTImark2000 and Embench DSP 1.0 plus nine larger DSP applications. The reference system is a direct `uAFL`/`SHiFT`-style port to the same DSP, with seed selection and mutation kept close to SBFUZZ so the comparison isolates decomposition and tracing.

The results match the bottleneck story. SBFUZZ improves throughput by `17.4x` on average and by as much as `1900x` on `servo`, where per-input host coordination dominates. The smallest gain is `1.3x` on `telecom`, which crashes often enough that both systems keep returning to the host. Coverage rises by `2.6x` on average, with about `83%` mean absolute coverage. The paper reports `2491` crashing inputs, reduced by manual triage to `34` unique bugs, and instrumentation overhead averages only `7.0%` extra binary size, which the authors position as a `28x` improvement over traditional desktop-style instrumentation overhead. For the main claim, this is convincing: the workloads exercise the targeted bottlenecks, though the evidence is stronger on mechanism than on broad portability.

## Novelty & Impact

Relative to _Li et al. (ICSE '22)_ and _Mera et al. (USENIX Security '24)_, the novelty is not merely fuzzing embedded hardware, but rejecting the standard host-centric split and showing that a DSP-centric steady state matters. Relative to _Nagy and Hicks (S&P '19)_, it adapts coverage-guided tracing to a bare-metal DSP with compact, assembly-level, dynamically erasable instrumentation.

That makes the paper useful beyond DSPs. Security researchers get a concrete recipe for a neglected device class. Systems readers get a broader lesson: when communication is expensive and execution semantics are specialized, performance comes from pushing the common case onto the device and reserving the host for rare coordination events.

## Limitations

The main limitation is portability. The implementation is tied to one TI C55x-class DSP, one closed compiler toolchain, one JTAG/debug setup, and one assembly environment. The paper also claims support for emulated targets, but evaluates only physical hardware.

There are also workload limits. The DSP can hold only a 15-seed local pool, crash recovery still requires host reflashing or power cycling, and the workloads are benchmark programs rather than large firmware stacks with rich peripheral behavior. The paper also stays with mutation-based fuzzing and does not explore stronger seed scheduling or concolic extensions.

## Related Work

- _Li et al. (ICSE '22)_ — `uAFL` shows how hardware tracing can fuzz microcontroller firmware, but it still relies on per-test host-side trace handling that is too costly for DSP links.
- _Mera et al. (USENIX Security '24)_ — SHiFT is the closest semi-hosted baseline; SBFUZZ differs by moving mutation and local coverage decisions onto the target instead of synchronizing every iteration.
- _Nagy and Hicks (S&P '19)_ — Full-Speed Fuzzing contributes coverage-guided tracing on commodity binaries, and SBFUZZ adapts that idea into compact, self-pruning DSP instrumentation.
- _Trippel et al. (USENIX Security '22)_ — Fuzzing Hardware Like Software motivates treating continuously running targets differently, but SBFUZZ assumes a known DSP SUT and instruments it directly at assembly time.

## My Notes

<!-- empty; left for the human reader -->

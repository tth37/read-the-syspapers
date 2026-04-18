---
title: "Signal Breaker: Fuzzing Digital Signal Processors"
oneline: "Moves mutation, execution, and coverage filtering onto the DSP so bare-metal signal processors can be fuzzed without per-test host round trips."
authors:
  - "Cameron Santiago Garcia"
  - "Matthew Hicks"
affiliations:
  - "Virginia Tech, Blacksburg, Virginia, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790220"
code_url: "https://github.com/FoRTE-Research/SBFuzz"
tags:
  - fuzzing
  - security
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

SBFUZZ argues that DSP fuzzing fails if it inherits the host-centric structure of embedded fuzzers for richer devices. Its main move is to push mutation, execution, and per-test coverage filtering onto the DSP itself, while reserving the host for rare events such as crash recovery, global corpus updates, and binary rewriting. On 15 DSP benchmarks, that design delivers `17.4x` higher throughput, `2.6x` more code coverage, and `2491` crashing inputs corresponding to `34` unique bugs.

## Problem

The paper starts from a mismatch between where fuzzing has succeeded and where DSP software lives. Coverage-guided fuzzing works well for desktop software and has been adapted to embedded devices, but those embedded fuzzers usually assume an operating system, convenient utilities, and fast out-of-band communication. DSPs look very different: they are bare metal, memory-constrained, and often exposed only through slow debug or control paths. A design that sends every test case and every coverage bitmap across that boundary spends more time coordinating than fuzzing.

That mismatch matters because DSPs sit in safety- and security-critical pipelines, and their failures do not look like ordinary process exits. A DSP may spin forever in an invalid control path, trigger a bus error, or keep running after corrupting hardware-visible state. The paper therefore frames DSP fuzzing as a systems problem with three constraints at once: very limited memory, very expensive host-device interaction, and failure modes closer to hardware than to conventional software.

## Key Insight

The central claim is that a DSP fuzzer should be decomposed around event frequency rather than programmer convenience. The work that happens for almost every test case, such as seed selection from a small local pool, mutation, execution, and deciding whether local coverage increased, belongs on the DSP. The heavyweight work that happens rarely, such as storing crashing inputs, maintaining a global corpus, and rewriting instrumentation, belongs on the host. If the system respects that split, the host stops being on the critical path of ordinary fuzzing iterations.

The second insight is that classic bitmap-based coverage reporting is the wrong abstraction for this target. Most inputs are uninteresting, so paying to materialize and transmit full coverage state every time wastes scarce RAM and communication bandwidth. SBFUZZ instead embeds the current coverage frontier into the instrumented binary itself. When a block has already been discovered, the host later rewrites the corresponding tracing call into `NOP`s, so the DSP gradually stops paying for already-known coverage. That turns coverage into a self-pruning signal and is what makes a DSP-centric decomposition practical.

## Design

SBFUZZ is split into a host engine and a DSP engine. The host stores the global seed pool, the global coverage list, crashing inputs, and a host-side copy of the instrumented binary. The DSP keeps only a local pool of seeds that fits in on-chip memory and runs an endless fuzzing loop. Periodic pool refresh lets the system expose the whole corpus over time without requiring it to reside on the device at once.

On the DSP, mutation is intentionally simple and cheap. The engine borrows AFL-style deterministic and random mutators, including bit and byte flips, arithmetic tweaks, zeroing, insertion, and deletion. The paper also adds mutation digression: as fuzzing progresses, only about `10%` of a seed is mutated at once, reflecting the observation that nested coverage is often reached by small perturbations rather than by repeatedly destroying the whole input. After a new coverage-increasing seed is found, mutation aggressiveness resets so the new region can be explored again from a wider radius.

Execution is organized like persistent fuzzing rather than process-per-input fuzzing. The DSP saves register context once, repeatedly invokes the SUT in an internal loop, and restores the saved context between iterations so stale machine state does not become false crashes. For crash detection, SBFUZZ uses watchdog-style timers plus hardware interrupts to catch hangs, bus errors, and data log errors, then breaks to a host-visible handler so the host can pull the input and reflash the board.

Coverage tracing is the most distinctive mechanism. The authors instrument at assembly time with tiny trampoline calls that log basic-block execution using offsets from the code segment rather than full program-counter values. The tracer saves and restores full register state, exploits C55x parallel move instructions to reduce cost, and avoids instrumenting inside hardware-loop bodies where function calls are disallowed. When the DSP reports a coverage-increasing input, the host merges the local trace into global coverage and rewrites matching instrumentation sites out of its binary copy. Future flashes therefore preserve coherence between host and board while steadily shrinking tracing overhead.

## Evaluation

The evaluation uses a TI `TMS320C5515` DSP running at `100MHz`, 24-hour campaigns, and five trials per benchmark. The corpus contains 15 programs: six kernels from BDTImark2000 and Embench DSP 1.0, plus nine more complex DSP applications spanning speech, image processing, biomedical code, machine vision, sonar, and telecommunications. As a reference, the authors port a `uAFL`/`SHiFT`-style embedded fuzzer to the same platform, deliberately keeping seed selection and mutation similar so the comparison isolates decomposition and tracing strategy.

The throughput results are large and consistent. SBFUZZ averages `17.4x` the throughput of the reference design across all 15 benchmarks, reaches a best case of `1900x` on `servo`, and still improves `telecom` by `1.3x` even though frequent crashes force both systems back into host coordination. Coverage and bug-finding move in the same direction: SBFUZZ averages `2.6x` the code coverage of the reference, reaches about `83%` average absolute coverage, and finds `2491` crashing test cases that boil down to `34` unique bugs, including buffer overflows, endless loops, divide-by-zero stalls, bus errors, and floating-point overflows. Instrumentation overhead is also modest for this setting, with average binary size rising by `7.0%`.

Overall, the evaluation supports the paper's main claim well. The reference implementation is a fair enough baseline for the stated question, and the numbers line up with the proposed bottlenecks. The main limitation is breadth rather than internal validity: all experiments are on one TI DSP family, and the workloads are benchmarks rather than large deployed firmware stacks.

## Novelty & Impact

Relative to _Li et al. (ICSE '22)_, SBFUZZ rejects the assumption that hardware-assisted embedded fuzzing can afford per-input host-side analysis. Relative to _Mera et al. (USENIX Security '24)_, it takes the semi-hosted model but flips the control structure so the target, not the host, performs the common-case fuzzing work. Relative to _Nagy and Hicks (S&P '19)_, it adapts coverage-guided tracing from commodity systems into a bare-metal DSP environment with dynamic on-device tracing removal and host-side binary coherence.

That makes the paper important for two adjacent communities. Embedded security researchers get a concrete recipe for fuzzing a class of devices that had mostly been skipped. Systems and architecture researchers get a more general lesson: when the target sits at the hardware-software boundary, the right decomposition may look less like "port AFL" and more like co-designing the runtime around the device's memory hierarchy, instruction set, and debug interface.

## Limitations

The biggest practical limitation is scope. The implementation and evaluation are centered on one TI C55x-class DSP board, one proprietary compiler toolchain, and a benchmark-heavy workload mix, so portability to other DSP families is more asserted than demonstrated. The system also relies on a local seed pool of only 15 inputs because on-chip memory is tight, so corpus management remains strongly constrained by hardware capacity.

Some design choices also shift rather than remove complexity. Crash recovery still needs host-driven reflashing and external power cycling, so campaigns with frequent crashing benchmarks lose some of SBFUZZ's advantage. The paper also stops at mutation-based fuzzing on DSP benchmarks; it does not study production firmware with rich peripherals or integrate concolic techniques for later-stage path exploration.

## Related Work

- _Li et al. (ICSE '22)_ — `uAFL` uses hardware tracing for microcontroller firmware, but still assumes a host-visible trace collection path that is too expensive for low-bandwidth DSP targets.
- _Mera et al. (USENIX Security '24)_ — SHiFT is the closest semi-hosted baseline; SBFUZZ's main departure is moving mutation and per-test coverage decisions onto the device rather than coordinating every iteration.
- _Nagy and Hicks (S&P '19)_ — Full-Speed Fuzzing introduces coverage-guided tracing on commodity binaries, and SBFUZZ adapts that idea to self-pruning DSP instrumentation.
- _Trippel et al. (USENIX Security '22)_ — Fuzzing Hardware Like Software informs SBFUZZ's view of continuously executing targets, but SBFUZZ instruments only the DSP SUT instead of discovering the target region dynamically.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Optimistic Recovery for High-Availability Software via Partial Process State Preservation"
oneline: "Phoenix restarts from main while reusing selected long-lived process state, using unsafe-region checks and optional cross-checking instead of rebuilding everything after faults."
authors:
  - "Yuzhuo Jing"
  - "Yuqi Mai"
  - "Angting Cai"
  - "Yi Chen"
  - "Wanning He"
  - "Xiaoyang Qian"
  - "Peter M. Chen"
  - "Peng Huang"
affiliations:
  - "University of Michigan"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764858"
code_url: "https://github.com/OrderLab/phoenix"
tags:
  - fault-tolerance
  - kernel
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Phoenix targets the gap between full restart and full-state checkpointing. It restarts execution from `main` but preserves selected long-lived in-memory state, then uses unsafe-region checks and optional background cross-checking to keep that fast path aligned with the application's normal recovery semantics.

## Problem

High-availability software needs recovery that is both fast and correct, and existing choices force an ugly trade-off. A plain process restart is attractive because it discards all buggy runtime state, but the new process must rebuild everything: reload data, replay logs, reconstruct caches, and slowly warm up before it can serve traffic normally again. The paper's Redis example is the failure mode in concrete form: a 15-second hang triggers a restart, then recovery from a 6 GB RDB file takes 53.5 seconds, and the cache still needs 361.7 seconds to regain 90% of its steady-state throughput.

The obvious alternative, checkpointing or full-state restore, improves restart latency by keeping memory around, but that same property makes it dangerous for software faults. If the bug has already contaminated the checkpointed state, recovery simply reinstalls the bug. If the checkpoint is older, the system loses recent updates. Finer-grained ideas like microreboot or Orleans reduce restart scope, but they require applications to be restructured into independently restartable components. The paper's question is therefore whether a server can keep the large, stable state that is expensive to rebuild while still discarding the transient execution context where many bugs actually live.

## Key Insight

The core claim is that many real failures do not corrupt the application's important long-lived state, even though that state dominates recovery cost. The authors' survey of 64 bug reports across Redis, MySQL, Hadoop, MongoDB, Ceph, and ElasticSearch found that 35 failures touched only temporary state, and another 21 left global state intact; only 8 actually corrupted long-lived state. Bugs and bytes are distributed asymmetrically: intricate control logic and request-local data cause many failures, while the largest data structures are often manipulated by comparatively simple, well-tested code.

That asymmetry makes a third design point viable. Instead of preserving everything or nothing, Phoenix preserves the largest few state structures that are semantically central and expensive to reconstruct, discards the rest, and restarts execution from the beginning. The catch is that this cannot be generic. The system depends on application-specific knowledge about what state is worth saving and, just as importantly, whether the crash happened in the middle of mutating that state. Phoenix therefore frames correctness relative to the application's default recovery path: the fast path is acceptable only if it produces a state equivalent to what normal recovery would have produced.

## Design

Phoenix is a coordinated kernel, runtime, libc, and compiler stack. At the API level, developers register a restart handler with `phx_init`, invoke `phx_restart` when a crash or watchdog event occurs, and use `phx_is_recovery_mode` plus recovery logic in `main` to reconnect preserved objects to freshly initialized state. The key kernel primitive is `preserve_exec`, a variant of `exec` that installs selected preserved pages into the new process at their original virtual addresses. That choice avoids pointer swizzling and lets the restarted process reuse preserved data structures directly while still getting a fresh executable image and fresh stacks.

State selection is supported in three ways. Heap preservation is implemented by instrumenting glibc `malloc` so Phoenix can track arena, `mmap`, and `brk` allocations and restore the relevant pages. Static data can be preserved more cleanly through `.phx.data` and `.phx.bss` ELF sections, so developers can annotate variables instead of manually copying them through a recovery struct. For more custom layouts, Phoenix also exposes raw range-based preservation. Because heap tracking is intentionally an over-approximation, the restarted program may retain unreachable objects; Phoenix therefore adds mark-and-sweep cleanup hooks, plus special reinitialization rules for synchronization objects and recomputation for reference counts that became stale when discarded state vanished.

Correctness hinges on unsafe regions. Developers mark the minimal code interval that truly mutates preservable state, and Phoenix refuses fast recovery if the crash lands inside that interval. The paper also provides an LLVM-based analyzer that approximates these regions automatically by tracking when a transaction first and last mutates preserved data. For users who want stronger assurance, Phoenix can run the normal recovery path in a background process, compare the recovered reference state against the preserved state, and hot-switch if they differ. Finally, for long-running computational jobs where most execution would otherwise look unsafe, the `phx_stage` API provides stage-based progress recovery with explicit save and restore hooks.

## Evaluation

The microbenchmark result establishes that the mechanism itself is cheap: restart latency is about 1.20 ms when the preserved state is under 4 MB, 1.56 ms for 32 MB, and 220.6 ms even for 32 GB of preserved memory. The more important results come from six real applications: Redis, LevelDB, Varnish, Squid, XGBoost, and VPIC. Porting Phoenix required 260.2 lines of code on average, or 0.52% of each codebase, which is small enough to make the design plausible outside a one-off artifact.

On 17 reproduced real bugs, Phoenix consistently lands near the best point on the availability/correctness frontier. In Redis, it keeps the near-instant restart flavor of a vanilla restart while recovering pre-failure availability within about 2 seconds instead of the 6-minute warm-up of built-in RDB recovery or the 25-minute tail of a no-persistence restart. In LevelDB, it preserves the in-memory skiplist and avoids log replay, cutting downtime by 130x relative to built-in recovery and 14x relative to CRIU while still recovering the same logical progress. Varnish and Squid regain near-normal hit-rate service almost immediately because the in-memory cache survives. For computational workloads, the benefit is progress reuse: Phoenix cuts effective unavailability by 19.8x for XGBoost and 76.4x for VPIC relative to built-in checkpointing.

The fault-injection campaign is the strongest evidence that the fast path is not merely optimistic hand-waving. Across 8,400 injected-failure runs, Phoenix successfully recovered 7,190 times, an 85.6% success rate. Unsafe-region checks proactively diverted 732 cases to the application's default recovery, and another 478 failed quickly after restart and fell back rather than silently running with bad state. With unsafe regions enabled, the paper reports no additional data corruption for Redis, Varnish, Squid, or LevelDB beyond what the vanilla system already suffered. Runtime overhead averages 2.7%, far below CRIU's 22.5%, and Phoenix safely reuses 88.4% of process memory on average.

## Novelty & Impact

Relative to CRIU and classical checkpointing, Phoenix's novelty is not "faster restore" in the abstract, but a different recovery model: fresh execution with partial state salvage. Relative to microreboot-style work, it does not require the application to be refactored into crash-only components. Relative to whole-system persistence, it targets software faults instead of power-loss scenarios and treats preservation as an application-semantic choice rather than a hardware-level all-memory property.

That combination makes the paper more than an engineering mash-up. It offers a practical methodology for high-availability software whose recovery pain is dominated by rebuilding large in-memory structures, and it shows that kernel/runtime/compiler support can make application-aware recovery substantially easier to deploy. The most likely adopters are caches, databases, and long-running services that already have a "safe but slow" recovery path and enough semantic structure to identify what state is worth keeping.

## Limitations

Phoenix is only as correct as the application's default recovery semantics. If buggy state has already been durably persisted to disk, or if the failure is a logic error that survives any restart until the code is fixed, Phoenix cannot help. The paper is explicit that "correct" means equivalent to the default recovery result, not stronger than it.

The system also asks developers to do real work. They must choose preservable state, ensure that preserved objects do not point into discarded memory, annotate or validate mutation boundaries, and often provide cleanup and object-reinitialization logic. The LLVM tool reduces that burden but is conservative, does not fully model external effects such as related file writes, and is weaker on complex C++ code with heavy STL use. Finally, Phoenix preserves only memory state: sockets, files, and threads are rebuilt by normal startup logic, so applications with little expensive long-lived memory or with failures that often strike inside long mutation windows will see less benefit.

## Related Work

- _Candea et al. (OSDI '04)_ - Microreboot reduces recovery scope by restarting components, whereas Phoenix keeps a monolithic process model and salvages selected in-memory state across a fresh restart.
- _Qin et al. (SOSP '05)_ - Rx recovers by rolling back to a checkpoint and re-executing in a modified environment, while Phoenix reuses only chosen long-lived state and discards the rest of the runtime.
- _Narayanan and Hodson (ASPLOS '12)_ - Whole-system persistence keeps full memory for fast reboot after failures, but Phoenix argues that software-fault recovery needs selective preservation precisely to avoid reloading buggy state.
- _Russinovich et al. (EuroSys '21)_ - VM-PHU preserves VM state across host updates, whereas Phoenix works at application data-structure granularity and is designed around software crash recovery rather than maintenance.

## My Notes

<!-- empty; left for the human reader -->

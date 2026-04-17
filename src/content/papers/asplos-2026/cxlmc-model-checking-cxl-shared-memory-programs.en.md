---
title: "CXLMC: Model Checking CXL Shared Memory Programs"
oneline: "Extends constraint-refinement model checking to x86-CXL shared memory so individual node crashes and cache-induced data loss can be explored systematically."
authors:
  - "Simon Guo"
  - "Conan Truong"
  - "Brian Demsky"
affiliations:
  - "University of California, Irvine"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790150"
code_url: "https://github.com/uciplrg/cxlmc-evaluation.git"
tags:
  - disaggregation
  - memory
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CXLMC is a crash-consistency model checker for x86-CXL shared-memory programs. Its main move is to adapt Jaaru-style cache-line constraint refinement to CXL's partial-failure setting, where one machine can fail while others continue and remote reads can themselves force cache lines back to shared memory. On adapted RECIPE and CXL-SHM benchmarks, it finds 24 bugs while keeping the search cost to seconds for most cases and under a minute for the slowest one reported.

## Problem

CXL shared memory makes it plausible to treat remote DRAM as a coherent, shared heap across many machines, which is exactly the sort of abstraction systems builders want for shared indexes, allocators, object stores, and coordination structures. The problem is that the failure model underneath that abstraction is much nastier than ordinary shared memory. If a compute node crashes before its dirty cache lines are written back, the newest stores may exist only in that node's cache and are therefore lost. A single crashed node can leave a cluster-wide shared data structure inconsistent.

That sounds similar to persistent memory, but the paper argues that existing PM tools are not enough. PM usually assumes whole-system failure; CXL's important case is partial failure, where one machine dies while others keep running and may even run recovery code concurrently. CXL also changes visibility rules: a remote read can force a cache line to be written back, which means reads can refine what must have persisted. A brute-force checker would have to enumerate too many possible post-crash cache states, especially because any subset of live machines may fail at each step. The result is a correctness problem that is both more distributed and more hardware-dependent than prior crash-testing tools were designed for.

## Key Insight

The paper's central claim is that CXL crash states can be explored lazily if the checker tracks write-back intervals rather than concrete cache contents. For each cache line, CXLMC records a constraint on when its most recent write-back could have happened. Flushes provide lower bounds, and post-crash reads narrow the interval further by revealing which stores must already have reached memory.

That representation matters because CXL failures are per-machine, not global. CXLMC therefore keeps cache-line constraints per failed machine, not per execution epoch, and augments the read-from search so that a load can discover additional failed machines whose constraints affect its result. Remote loads are treated as semantically important events rather than passive observations: because cache coherence can force write-back on a remote read, the read itself changes what crash states remain possible. This is the step that makes a persistent-memory-style constraint refinement scheme fit CXL instead of merely approximating it.

## Design

CXLMC works by compiling C and C++ programs through an LLVM pass that instruments memory accesses, fences, and flushes, then executing the instrumented code inside a runtime that emulates x86-TSO plus CXL shared memory. Each CXL machine becomes a separate process with its own local address space; the common shared-memory region is mapped identically into all forks. Inside a process, CXLMC can schedule multiple threads, intercepts relevant `pthread` operations, and preserves thread-local storage across context switches.

The memory-model emulation follows the paper's x86 target closely. Each thread gets a store buffer and a separate flush buffer so that `store`, `clflush`, `clflushopt`, `sfence`, and `mfence` obey the right ordering rules. Globally visible stores are recorded as triples of value, sequence number, and source machine. For each cache line, the checker tracks the interval in which its latest write-back may have occurred. A normal `clflush` advances the lower bound directly; `clflushopt` is split into enqueue and later commit so its weaker reordering semantics are preserved.

The algorithmic heart is the read-from construction plus failure exploration. `BuildMayReadFrom` first enumerates candidate stores consistent with the current failed-machine set, then recursively adds failed machines when an older store may still matter because a machine's cache-line constraint leaves room for it. When a load resolves to a particular store, `DoRead` tightens the corresponding cache-line interval so future reads stay consistent. The outer `Explore` procedure alternates between committing buffered operations and executing program steps; if a flush advances past a store from a still-live machine, CXLMC forks an execution where that machine fails at that point. This is effectively a DPOR-style search over crash-relevant distinctions rather than an eager enumeration of all cache states.

The implementation work is not trivial bookkeeping. Because the target programs are multi-process, CXLMC needs deterministic scheduling across forks, TLS preservation for user threads, and failure-aware mutex semantics so benchmarks adapted from PM code can release locks held by a crashed process. That engineering is part of what makes the paper more than a proof-of-concept algorithm sketch.

## Evaluation

The evaluation uses two benchmark sources: six adapted RECIPE persistent-memory indexes, plus two benchmarks from CXL-SHM. The authors exclude `P-HOT` because LLVM could not compile it, and they modify some RECIPE programs to fit partial failure, for example by recording process ownership in locks. This is a pragmatic benchmark set rather than a polished application suite, but it is appropriate for exposing crash-consistency bugs.

Bug-finding results are the headline. CXLMC reports 22 bugs in the RECIPE-derived benchmarks and 2 more in CXL-SHM. The paper highlights several interesting new failures rather than only missing-flush bugs: incorrect padding in `FAST_FAIR`, nonatomic counter updates and an N16 flush mistake in `P-ART`, a partial-failure-only recovery bug in `P-MassTree`, and an unimplemented free path plus a divide-by-zero bug in CXL-SHM. The authors also say they iteratively fixed bugs and reran until no more were found, which is the right workflow for a checker of this kind.

The performance study is smaller but still useful. On fixed RECIPE runs with 2 processes, 2 threads per process, and 10 keys, CXLMC explores between `20` and `4128` executions without GPF, with total runtimes from `0.03s` to `42.96s`; the GPF-mode runs range from `15` to `4119` executions and up to `44.6s`. That supports the paper's narrow central claim: the lazy search avoids combinatorial explosion well enough to be interactive on these benchmarks. The limitations are equally clear. There is no competing CXL checker to compare against, the performance inputs are tiny, and real CXL 3.x hardware is not yet available.

## Novelty & Impact

Relative to _Gorjiara et al. (ASPLOS '21)_, CXLMC's novelty is taking cache-line constraint refinement out of the full-system persistent-memory setting and making it work under per-machine crashes plus remote-read-induced write-backs. Relative to fault-injection work for distributed systems, its important move is to treat shared-memory cache state as the search object rather than messages or RPC traces. Relative to CXL systems papers, it contributes a debugging tool and executable semantics for a class of bugs that deployment papers usually assume away.

That makes the likely impact fairly specific but real. Anyone building allocators, indexes, or coordination structures over CXL shared memory now has an example of what "correctness tooling" for this domain should look like. I would expect the paper to be cited by future CXL programming-model work, CXL runtimes that claim partial-failure tolerance, and follow-on verification tools that check stronger properties than crash/assertion failure.

## Limitations

CXLMC deliberately narrows scope to stay tractable. It targets x86-TSO, assumes a single shared memory device, and does not model mixed-architecture sharing or persistent remote memory. It checks only whether executions crash or violate existing assertions, not semantic invariants like linearizability unless a benchmark encodes them explicitly. The tool also does not systematically explore concurrency nondeterminism; instead, it explores crash nondeterminism for a fixed schedule and relies on different random seeds to surface additional interleavings.

The evaluation leaves open how well the approach scales to larger applications. The benchmarks are mostly adapted microbenchmarks, not production CXL services, and the performance table is collected only after bugs are fixed. Memory poisoning is supported as an option but not exercised because the authors had no application designed for it. There is also an unresolved paper-level ambiguity around "new bug" counts: the narrative and tables do not appear perfectly aligned, which does not change the tool's core contribution but slightly weakens the presentation.

## Related Work

- _Gorjiara et al. (ASPLOS '21)_ — Jaaru provides the persistent-memory constraint-refinement template; CXLMC generalizes that idea to partial machine failures and multi-process CXL programs.
- _Lantz et al. (USENIX ATC '14)_ — Yat eagerly enumerates post-crash states for persistent memory, which the CXLMC paper uses as the expensive baseline style it is trying to avoid.
- _Zhang et al. (SOSP '23)_ — CXL-SHM is a partial-failure-resilient CXL memory-management system, and CXLMC uses it as evidence that real CXL software already needs dedicated bug-finding support.
- _Assa et al. (ASPLOS '26)_ — CXL0 formalizes the semantics of disaggregated memory over CXL, while CXLMC complements that line with executable model checking for x86-CXL programs.

## My Notes

<!-- empty; left for the human reader -->

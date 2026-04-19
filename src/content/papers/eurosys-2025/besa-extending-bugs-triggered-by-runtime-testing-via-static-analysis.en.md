---
title: "BESA: Extending Bugs Triggered by Runtime Testing via Static Analysis"
oneline: "BESA treats one runtime-triggered null dereference as a seed, then uses call-stack-guided backward propagation and alias-aware forward tracking to find sibling bugs."
authors:
  - "Jia-Ju Bai"
affiliations:
  - "Beihang University"
conference: eurosys-2025
category: reliability-and-formal-methods
doi_url: "https://doi.org/10.1145/3689031.3696089"
tags:
  - formal-methods
  - fuzzing
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

BESA uses one runtime-triggered null-pointer dereference as a search seed. It walks backward along the observed call stack to find source assignments, then forward through alias relations, typestate checks, and SMT-feasible paths to locate sibling dereferences that should inherit the same NULL state. On 25 known bugs, it finds 57 extra bugs, including 18 confirmed new ones, without generating new test cases.

## Problem

Runtime testing proves a bug exists, not that nearby bugs are gone. Coverage gaps, rare paths, and alternative call chains let related failures survive even after fuzzing or sanitizer-backed debugging. Developers therefore patch the observed crash and often miss another use of the same bad value elsewhere.

The SQLite example captures the issue. Two null dereferences, NPD1 and NPD2, were reported 1.5 years apart even though their buggy fields were aliases of the same propagated source. Re-running tests is weak because the missing bug may require an infrequent context, while unguided whole-program static analysis overreports because possible aliases need not share the runtime state seen in the crash.

## Key Insight

The paper's claim is that the crash trace supplies exactly the context static analysis is missing. If runtime testing gives the buggy variable and concrete call stack, static analysis can backtrack only along that stack to recover source variables, then search feasible paths where other variables become aliases of the same bad value. That reframes the job from whole-program bug detection to bug extension: where else can the observed NULL reappear?

## Design

BESA works on LLVM bytecode. It first compiles the program and records per-function metadata, then collects trace information either from PoC execution or from an ASan/KASAN-style failure log. The trace collector extracts the buggy variable and the crash call stack.

Backward propagation starts at the crashing instruction and walks backward through assignments only inside the observed stack. When propagation crosses a function boundary, BESA maps argument positions back to the caller and recurses upward. To keep field-level precision, it records access-path-style connections showing which field of a source variable aliases the buggy variable, then deduplicates dominated source instructions.

Forward target tracking starts from each source instruction. BESA runs an interprocedural, flow-sensitive, field-sensitive dataflow analysis that maintains an alias set for variables currently sharing the key fields connected to the buggy variable. Basic-block and function summaries, keyed by the alias set, cut repeated traversals. A candidate use becomes a report only if a typestate-style FSM shows the variable can stay NULL until use and Z3 confirms the path is feasible.

## Evaluation

The evaluation covers 25 known null dereferences: 15 application CVEs from SQLite, VIM, and GPAC, plus 10 Linux kernel bugs. Application bugs are replayed with PoCs under ASan and BESA; kernel bugs are analyzed from failure logs. The codebases range from more than 200 KLOC to more than 600 KLOC, with the kernel at more than 20 million lines.

BESA finds 57 extra bugs, 33 in applications and 24 in the kernel. Eighteen were still live in the latest code at evaluation time, were reported to developers, and were confirmed as new. Just as important, 35 of the 57 occur in different functions from the original bug, which supports the paper's emphasis on cross-function propagation rather than local pattern matching.

The patch and efficiency results strengthen the claim. Thirty-nine extra bugs had already been fixed by later commits, including 36 by the same patch series as the known bug, suggesting BESA often rediscovers real sibling bugs rather than arbitrary warnings. With summaries, analysis stays under 10 seconds per bug; without them, `BESA_NoSum` times out at 300 seconds on 10 of 25 bugs and still averages 42 seconds on the rest. Clang Static Analyzer, Infer, and CppCheck find none of the 18 new bugs.

## Novelty & Impact

BESA is novel because it treats runtime testing as a way to bound static analysis, not as a separate stage. Prior work either diagnoses one observed failure or does pure static typestate and alias reasoning over source code. BESA uses the first crash as a seed for finding a family of related bugs. That is useful both for testing researchers and for maintainers deciding whether a patch fixed the root cause or only the first manifestation.

## Limitations

The approach is deliberately narrow. It currently supports only single-variable null dereferences in C, and log-only mode expects well-formed ASan or KASAN reports. The paper explicitly excludes multi-variable and concurrency-heavy bugs such as buffer overflows and deadlocks.

The analysis is also unsound for recall. BESA has incomplete bottom-up handling of callees, unrolls loops and recursion only once, and skips some hard cases such as global variables and non-constant array indices to control false positives. The evaluation reports no false positives, but the likely cost is missed bugs rather than universal precision.

## Related Work

- _Bai et al. (TSE '21)_ - SDILP also extends dynamic bug findings, but only for data races and with much simpler intra-procedural, non-alias analysis; BESA generalizes the idea to null dereferences with interprocedural alias tracking.
- _Li et al. (ASPLOS '22)_ - performs path-sensitive, alias-aware typestate analysis for OS bug detection from source code alone, whereas BESA uses a concrete runtime failure to narrow the search before applying similar static machinery.
- _Cui et al. (ICSE '16)_ - RETracer uses static reasoning to diagnose one observed crash, while BESA uses the runtime trace as a seed for finding additional bugs beyond the original failure.
- _Rubio-González et al. (PLDI '09)_ - tracks propagation of error-related values across code, but BESA inverts the flow first by recovering sources from a triggered bug and then tracking sibling target variables forward.

## My Notes

<!-- empty; left for the human reader -->

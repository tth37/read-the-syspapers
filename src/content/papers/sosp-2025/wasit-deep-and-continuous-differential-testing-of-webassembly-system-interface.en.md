---
title: "WASIT: Deep and Continuous Differential Testing of WebAssembly System Interface Implementations"
oneline: "WASIT turns the sketchy WASI spec into executable constraints and abstract resource states, generating deep differential tests that found 48 bugs across six runtimes."
authors:
  - "Yage Hu"
  - "Wen Zhang"
  - "Botang Xiao"
  - "Qingchen Kong"
  - "Boyang Yi"
  - "Suxin Ji"
  - "Songlan Wang"
  - "Wenwen Wang"
affiliations:
  - "University of Georgia"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764819"
code_url: "https://github.com/yagehu/wasit"
tags:
  - fuzzing
  - formal-methods
  - isolation
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

WASIT treats the evolving WASI specification as something closer to an executable contract than a comment-only reference manual. It augments the spec with resource types, call preconditions, and output effects, then uses SMT solving plus differential testing to generate stateful WASI call sequences across six runtimes. Over four months, that combination uncovered 48 WASI-specific bugs, including sandbox escapes, data-corruption issues, and three CVEs.

## Problem

WASI is the layer that makes WebAssembly useful outside the browser, but it inherits an awkward combination of properties. Its functions are stateful like system calls, they are implemented on top of host-kernel services whose semantics do not line up perfectly with WASI, and the specification itself is still sketchy and fast-moving. A function such as `path_open()` can be correct or incorrect depending on previously created descriptors, flags, path shape, and host-platform behavior. That means shallow single-call testing misses the bugs that actually matter.

Existing Wasm-runtime testing mostly focuses on Wasm instructions, not WASI semantics. The few approaches that do reach WASI either generate isolated calls or rely on heuristics that cannot maintain deep cross-call dependencies. The stakes are high: the paper points to silent data corruption, filesystem sandbox escapes, and already assigned CVEs in popular runtimes. The obvious alternative, white-box analysis of each runtime, is unrealistic because the implementations span multiple languages and ecosystems. WASIT is therefore solving a practical gap: how to systematically test a polyglot, underspecified, rapidly evolving interface without first building a full formal model of every implementation.

## Key Insight

The paper's central claim is that a WASI tester does not need implementation-specific white-box knowledge if it can recover just enough semantics from the interface itself. WASIT does that by enriching the specification with three kinds of information: what counts as a resource, when a function call is semantically valid, and how successful execution should mutate abstract resource state. Once those are explicit, dependent call sequences can be synthesized mechanically rather than hand-scripted.

That proposition matters because it shifts the modeling burden away from the runtimes and onto a lightweight, interface-level abstraction. The same abstract file descriptor can be lowered into runtime-specific integers, lifted back after execution, and checked for consistent effects even when different runtimes choose different concrete descriptor values. In other words, WASIT wins by tracking semantic identity and state transitions instead of chasing raw concrete values.

## Design

WASIT has three main phases. First, it augments the `witx`-style WASI specification with a small DSL. `@resource` annotations promote ordinary WASI values such as handles into structured abstract resources, for example file descriptors with fields like offset, flags, type, and path. `@input` annotations express call preconditions as quantifier-free Boolean formulas, while `@output` annotations describe how a successful call creates, consumes, or updates resources. Because the annotations reuse WASI's own value types, the model stays close to the interface rather than inventing a separate semantics framework.

Second, WASIT keeps a global abstract system state shared across all tested runtimes and a per-runtime resource context that maps abstract resources to concrete local values. Before a call, WASIT lowers abstract resources into each runtime's concrete descriptors or handles. After execution, it lifts the returned concrete values back into the shared abstract state. This is what lets the framework tolerate benign differences such as one runtime choosing file descriptor 5 while another chooses 100, while still checking whether both runtimes opened the same abstract file and updated the same abstract offset correctly.

Third, the framework uses SMT solving to drive both call generation and state transition. It encodes each function's input requirements against the currently live resources, eagerly instantiating resource references with concrete members of the abstract state so the resulting constraints stay decidable. A satisfiable constraint makes a function eligible for selection; repeated solving plus blocking clauses samples multiple legal argument sets. After execution, a second constraint encoder uses the function's output effects and the observed result to compute the next abstract state. This reuse of the same symbolic machinery on both the input and output sides is one of the cleaner parts of the design.

The implementation choices are also important. WASIT is about 6.7 KLoC of Rust plus a C executor, targets WASI preview1, and reportedly needed about 170 lines of spec annotations on top of the 1,301-line official specification. The authors also normalize mismatched initial runtime states, transparently retry partially completed operations such as short writes, and snapshot sandboxed filesystems after calls so they can catch implicit side effects rather than only explicit return values.

## Evaluation

The evaluation tests six widely used runtimes: Node.js, WAMR, WasmEdge, Wasmer, Wasmtime, and Wazero, across Linux, macOS, and Windows. The headline result is strong: intermittent testing over four months found 48 new WASI-specific bugs, with 41 confirmed, 37 fixed, and three CVEs assigned. Fifteen of the fixed bugs had apparently survived for more than four years. The bug table is not just full of crashes; it includes offset mishandling, path-sandbox violations, timestamp bugs, append-flag errors, and directory-validation mistakes, which supports the paper's claim that the hard part is deep semantic correctness rather than mere parser robustness.

The case studies make that concrete. One Wasmtime bug came from a sequence that opened a file with append semantics, wrote to it, queried the offset, and then used `fd_pwrite()` in a way that exposed stale offset tracking and corrupted file contents. A Wazero bug appeared when resetting descriptor flags caused the runtime to reopen a host file but lose the prior offset, so `fd_tell()` later returned 0 incorrectly. These are exactly the sorts of bugs that shallow single-call testing is unlikely to hit.

The comparative evidence mostly backs the mechanism claims. Against Wasix, DrWASI, and a `syzkaller`-like ablation without resource tracking, WASIT reaches much deeper resource chains, up to a max depth of 1,310, while Wasix and DrWASI stay at depth 1. It also achieves the highest reported branch coverage in every instrumented runtime, for example 1,216 covered branches on Node.js versus 1,204 for the ablation and 748 for Wasix. Finally, after roughly 10 person-hours of adding semantic constraints, WASIT reportedly generated zero inconsistencies in a 10-minute run where the competing tools produced hundreds to thousands of inconsistencies, all of them false positives. The main caveat is that some coverage comparisons exclude Wasmer and Wazero, and DrWASI could not be adapted to Node.js, so the comparison is not perfectly uniform, but it is still persuasive.

## Novelty & Impact

Relative to prior Wasm-runtime testers such as WADIFF and WASMaker, the novelty is that WASIT targets WASI as a stateful interface rather than Wasm instructions or binary generation. Relative to DrWASI and Wasix, it contributes a more explicit semantic model: live resource abstraction, executable preconditions and effects, and a decoupled architecture that lets the control strategy evolve without rewriting call-generation code. This is a new mechanism, not just a new benchmark.

The likely impact is twofold. For Wasm-runtime maintainers, WASIT is already an effective bug-finding tool with direct practical value. For systems-testing researchers, it offers a plausible design pattern for other resource-centric APIs that sit between underspecified interfaces and polyglot implementations, where full formalization is too expensive but blind fuzzing is too shallow.

## Limitations

The current implementation targets WASI preview1 rather than the newer 0.2 line, and the paper is explicit that 0.2 support was too inconsistent at the time. That means part of the contribution is time-sensitive: co-evolution with WASI is a design goal, but the paper does not yet demonstrate it on the stabilized next-generation interface.

The other limitation is methodological. The annotation burden is light compared with full formal modeling, but it is still manual and still depends on human triage of divergences. As a differential tester, WASIT is also weakest when multiple runtimes share the same wrong behavior or when the specification remains too ambiguous for developers to agree that a divergence is truly a bug. The authors reduce noise well, but they do not eliminate the basic limits of differential testing.

## Related Work

- _Zhou et al. (ASE '23)_ - WADIFF performs differential testing on WebAssembly runtimes at the instruction level, whereas WASIT targets stateful WASI semantics and dependent resource manipulation.
- _Cao et al. (ISSTA '24)_ - WASMaker generates semantically aware Wasm binaries, but it does not model live WASI resources or synthesize long interface-level call chains.
- _Zhang et al. (TOSEM '25)_ - DrWASI uses LLM-generated C programs to reach WASI indirectly through toolchains, while WASIT calls WASI directly and uses explicit resource tracking to reach deeper states.
- _Ridge et al. (SOSP '15)_ - SibylFS offers formally grounded POSIX testing, whereas WASIT trades formal completeness for a lightweight symbolic model that can operate across diverse Wasm runtimes.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Deterministic Client: Enforcing Determinism on Untrusted Machine Code"
oneline: "DeCl statically verifies x86-64 and Arm64 machine code for deterministic execution and deterministic gas accounting, so untrusted native code can run without a trusted JIT or interpreter."
authors:
  - "Zachary Yedidia"
  - "Geoffrey Ramseyer"
  - "David Mazières"
affiliations:
  - "Stanford University"
  - "Stellar Development Foundation"
conference: osdi-2025
tags:
  - security
  - isolation
  - compilers
category: verification-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

DeCl is a software sandbox that enforces determinism directly on untrusted x86-64 and Arm64 machine code. It treats determinism as a machine-code safety property: verify that only deterministic instructions can execute, instrument code for deterministic metering, and optionally combine that with lightweight software isolation. The result is near-native execution with a much smaller trusted base than interpreter- or JIT-based smart-contract runtimes.

## Problem

The paper targets adversarial determinism, mainly for smart contracts. An untrusted party supplies the program, but every honest replica must observe the same behavior and side effects. Existing systems mostly get that property by compiling to a deterministic intermediate language such as WebAssembly or EVM bytecode and then trusting an interpreter or JIT. That keeps execution consistent, but it expands the trusted code base and gives up native-code performance.

Memory isolation is not sufficient. A sandbox may stay in bounds and still behave nondeterministically because the ISA exposes undefined or unpredictable instructions, architecture-dependent flags behavior, or timer-driven preemption that fires on different sides of an external effect. DeCl therefore asks for something stricter than classic SFI: a verifier that accepts only programs whose execution is deterministic across all valid microarchitectures of the target ISA, while still supporting bounded execution and low startup cost.

## Key Insight

The central claim is that determinism can be enforced with the same overall architecture that SFI uses for memory safety: restrict execution to a verifier-understood machine-code subset and reject anything whose semantics are not fully controlled. For DeCl, the verifier proves not just "this program stays in bounds," but "every instruction it can execute is deterministic, and every path to undefined behavior has been ruled out by static checks or local rewrites."

That makes native code viable without trusting the compiler or a binary translator. LLVM or GCC may generate the assembly, but DeCl rewrites it into a verifier-friendly form and then verifies the final binary directly. Deterministic preemption follows the same idea: gas accounting is embedded into the verified machine code rather than delegated to wall-clock timeouts.

## Design

The pipeline is compile to assembly, rewrite, assemble/link, then verify the final executable before native execution. The verifier accepts only instructions from a deterministic subset. On Arm64, fixed-width instructions plus W^X are enough to make decoding trustworthy. On x86-64, DeCl also uses aligned bundles so jumps cannot land in the middle of a variable-length instruction and reinterpret bytes differently from the verifier.

The verifier then handles ISA-specific nondeterminism. On Arm64, it rejects malformed encodings, exclusive-access operations, and unallocated or undefined instructions other than `udf #0` as an explicit trap. On x86-64, DeCl first restricts the program to a fully enumerable instruction subset represented by a BDD derived from the Fadec encoder, then adds semantic checks. Instructions such as `SHLD`, `SHRD`, `BSR`, and `BSF` are guarded so they cannot receive undefined-result inputs, while a data-flow analysis rejects any path that could read an undefined flag.

Metering is the second major component. Branch-based metering stores gas in a reserved register and requires every basic block to end with a metering epilogue that subtracts the block cost and traps on underflow; the verifier reconstructs leaders and checks these epilogues cannot be skipped. Timer-based metering uses a nondeterministic timer only to notice that gas may have become negative; the runtime then checks gas before any runtime call can create an externally visible effect. That keeps observable behavior deterministic while reducing steady-state overhead.

For LFI integration, DeCl adds position-oblivious code. Because an LFI sandbox in a shared address space could otherwise observe its own load address and branch on it, DeCl reserves absolute-address registers and allows them to be observed only through their low 32 bits. Calls, returns, stack-pointer reads, and PC-relative address generation are rewritten to preserve that invariant.

## Evaluation

The evaluation covers both microarchitectural overheads and an end-to-end smart-contract use case. On integer SPEC CPU2017 benchmarks that run under LFI, DeCl-LFI with position-oblivious code is close to plain LFI: 9.3% geomean overhead on x86-64 and 9.4% on Arm64, versus 9.5% and 8.5% for LFI itself. Metering is the real extra cost. Timer-based metering adds 19.2% on x86-64 and 19.1% on Arm64, while branch-based metering costs 39.3% and 24.1%. Against Wasmtime with fuel metering, DeCl is much cheaper: 35.0% versus 76.5% on the WebAssembly-compatible x86-64 subset, and 19.7% versus 109% on Arm64.

The Groundhog integration is where the systems argument lands. The authors preallocate 128 KiB code and 128 KiB data regions per sandbox and use page aliasing so code can be writable in the runtime and executable in the sandbox without repeated `mprotect` calls. With that setup, loading, executing, and exiting an empty contract takes 15 us on the M2 and 2 us on the Ryzen 7950X, and Figure 8 shows that DeCl preserves Groundhog's scaling to 192 cores.

For CPU-heavy contracts, the gap is larger still. On zero-knowledge proof verification, DeCl-timer verifies Groth16 in 0.344 s on x86-64 and 0.202 s on Arm64, compared with 0.745 s and 0.587 s for Wasmtime-fuel. Wasm3 is far slower at 10.5 s and 5.38 s. Those results support the core claim that verified native code can give smart-contract systems both a smaller trusted base and a much better performance envelope.

## Novelty & Impact

Relative to _Haas et al. (PLDI '17)_ and the broader WebAssembly model, DeCl moves determinism enforcement from a trusted language runtime into a verifier over native binaries. Relative to _Yedidia (ASPLOS '24)_, it extends lightweight software isolation into deterministic semantics, deterministic metering, and position-oblivious execution. Relative to _Aviram et al. (OSDI '10)_, it targets hostile inputs and machine-code verification rather than deterministic execution for ordinary programs.

That combination matters for replicated state machines, especially blockchains. The paper makes a credible case for "bare-metal smart contracts": users can ship native cryptographic code, keep deterministic execution, and avoid the large steady-state tax of interpretation or a trusted JIT.

## Limitations

The most obvious limitation is portability. A DeCl program is only deterministic within one ISA subset, not across x86-64 and Arm64, and the verifier excludes floating point entirely. That is a practical engineering boundary, not a complete determinism story.

The implementation is also brittle in familiar low-level ways. x86-64 support depends on carefully modeled instruction semantics, undefined-flag analysis, aligned bundles, and hand-maintained knowledge of problematic encodings. The paper assumes hardware correctness for the accepted subset and notes that hardware bugs could still break determinism until the verifier is patched. Current toolchains also do not separate integer SIMD from floating point cleanly, so useful code may be rejected or require rewriting. Finally, the strongest application results rely on a custom runtime with fixed-size preallocated sandboxes and deterministic runtime calls.

## Related Work

- _Yedidia (ASPLOS '24)_ - LFI shows that static verification plus reserved-register conventions can deliver lightweight software isolation; DeCl builds directly on that machinery but upgrades the target property from memory safety to determinism.
- _Wahbe et al. (SOSP '93)_ - classic SFI established the model of rewriting and verifying native code before execution, which DeCl repurposes for deterministic semantics rather than just address-space confinement.
- _Haas et al. (PLDI '17)_ - WebAssembly provides determinism through a language-defined execution model and trusted runtime, whereas DeCl preserves native code and shrinks the trusted base to a verifier and runtime API.
- _Aviram et al. (OSDI '10)_ - Determinator offers deterministic execution for conventional programs, but it is not an adversarial machine-code sandbox and does not solve deterministic gas metering.

## My Notes

<!-- empty; left for the human reader -->

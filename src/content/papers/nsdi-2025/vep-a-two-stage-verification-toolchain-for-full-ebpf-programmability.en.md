---
title: "VEP: A Two-stage Verification Toolchain for Full eBPF Programmability"
oneline: "VEP moves eBPF proof search to annotated C in user space, compiles proofs into bytecode, and leaves the kernel with only a small proof checker."
authors:
  - "Xiwei Wu"
  - "Yueyang Feng"
  - "Tianyi Huang"
  - "Xiaoyang Lu"
  - "Shengkai Lin"
  - "Lihan Xie"
  - "Shizhen Zhao"
  - "Qinxiang Cao"
affiliations:
  - "Shanghai Jiao Tong University"
conference: nsdi-2025
category: network-verification-and-synthesis
code_url: "https://github.com/yashen32768/NSDI25-VEP-535"
tags:
  - ebpf
  - kernel
  - verification
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

VEP turns eBPF verification into a proof-carrying pipeline. Users annotate eBPF-flavored C with specs and loop invariants, `VEP-C` discharges the hard reasoning in user space, `VEP-compiler` carries code, assertions, and proofs down to bytecode, and `VEP-eBPF` leaves the kernel with only a small proof checker. On 41 programs, the prototype accepts every properly annotated safe program and rejects every unsafe one, while existing automatic verifiers still reject many safe cases.

## Problem

eBPF is useful precisely when programs are nontrivial: loops walk packet state or map contents, helpers acquire kernel resources, and safety depends on aliasing, bounds, and release discipline. Current verifiers protect the kernel by staying conservative. The Linux verifier symbolically follows paths with register tracking, so it limits program size and loop complexity to contain path explosion. PREVAIL merges states with abstract interpretation, but the paper shows that loops whose exit or memory behavior depends on runtime data still defeat its precision.

The obvious fixes do not fit the deployment model. A stronger fully automatic kernel verifier would need a large SMT solver or theorem prover in the kernel, which expands both resource cost and the trusted computing base. Trusting only a user-space C verifier is also insufficient, because then developers must trust the compiler to preserve the verified meaning. A bytecode-only verifier has the opposite usability problem: once optimization rewrites the program, bytecode-level failures are hard for developers to debug. The paper therefore targets three constraints at once: accept any safe eBPF program given enough annotations, keep the in-kernel trusted component small, and let programmers work at the C source level.

## Key Insight

The central idea is to separate proof search from proof checking. Proof search is expensive, heuristic, and solver-heavy, so it belongs in user space over annotated C. Proof checking should happen at the bytecode boundary with only simple symbolic execution and proof replay, so the kernel needs to trust only a compact checker.

That split makes annotations the escape hatch for programmability. Instead of forcing the verifier to infer every loop invariant, memory-disjointness fact, and helper protocol automatically, VEP lets the programmer state them explicitly. The system can then generate and transport machine-checkable proofs down to the eBPF artifact that is actually loaded.

## Design

VEP has three components. `VEP-C` verifies annotated C programs using first-order logic plus separation logic. Function specs use `With`, `Require`, and `Ensure`; loop invariants state what must hold at each iteration boundary. The assertion language can express array and pointer permissions, disjoint memory regions, helper-acquired resources, acquire-release discipline, and functional properties beyond memory safety. `VEP-C` symbolically executes the program, computes strongest postconditions, asks its built-in SMT solver to prove entailments, and records proof terms. A notable design choice is that undefined C behavior is rejected early even if a backend compiler might later produce seemingly safe bytecode.

`VEP-compiler` is not just a code generator. It must keep assertions and proofs aligned with the compiled program through IR lowering, BPF calling conventions, frame layout, spills, and register allocation. The paper's interesting detail here is how it preserves facts when source variables disappear: if a value is dead after allocation, the corresponding assertion does not simply drop it, but replaces it with an existential logic variable. Helper-function specifications are also lowered so bytecode-level reasoning still knows what resources are acquired or released.

`VEP-eBPF` is the only component that must be trusted at load time. It symbolically executes annotated bytecode again, re-checks safety conditions, and validates the transported proofs instead of invoking an SMT solver. Spatial derivations are checked with simple separation-logic rules, and pure propositions are checked with a cvc5-style proof language. Because the checker only replays proofs rather than discovering them, the kernel-side verifier stays much smaller than a general-purpose automatic verifier.

## Evaluation

The evaluation covers 41 programs: 10 Linux kernel samples, 10 PREVAIL samples, 10 C `StringLib` functions, 10 unsafe programs, and one larger `Key_Connection` case study. All three tools reject the 10 unsafe programs. The difference is safe-code acceptance. VEP accepts all three safe categories at `10/10` and also verifies `Key_Connection`. The Linux verifier accepts `9/10` Linux samples, `6/10` PREVAIL samples, `3/10` `StringLib` routines, and fails on `Key_Connection`. PREVAIL reaches `10/10` on Linux samples, `8/10` on its own suite, only `1/10` on `StringLib`, and also fails on `Key_Connection`.

The cost numbers support the two-stage argument, though they still look like research-prototype costs rather than production fast paths. The Linux verifier remains the cheapest baseline at under 1 ms average with under 5.2 MB across the table. `VEP-C` is heavier because it performs solver-backed source verification: on Linux samples it averages 39.46 ms and 32.6 MB. The compiler stage is minor. The kernel-side `VEP-eBPF` checker is much lighter, averaging 8.42 ms and 8.0 MB on Linux samples, 2.76 ms and 3.0 MB on PREVAIL samples, and 2.63 ms and 3.0 MB on `StringLib`. That is enough to support the paper's claim that expensive reasoning has been pushed out of the kernel while preserving a final in-kernel check.

The annotation story is the real tradeoff. For 618 lines of Linux sample code, users write 76 assertions and VEP generates 64,840 proof lines. The 63-line `Key_Connection` example expands to 350 lines of annotated bytecode and 5,800 proof lines. So VEP is not annotation-free; it is claiming that a modest number of high-level annotations can drive a large amount of automatic proof generation.

## Novelty & Impact

The paper's novelty is the end-to-end composition. Prior eBPF verifiers are either automatic and conservative, or powerful but exposed at the bytecode or theorem-prover layer. VEP instead offers a source-level annotation interface, an annotation-aware compiler, and a proof-carrying bytecode checker designed to sit on the kernel loading path. That is a more deployable answer to "full programmability" than simply bolting a stronger solver onto today's verifier.

If this line of work matures, its impact is clear. It would let eBPF developers write programs with richer loops, more precise helper-resource protocols, and even functional-correctness properties that current automatic verifiers cannot prove. The `Key_Connection` case study also hints at why this matters operationally: more complicated L7 logic might stay inside eBPF rather than being pushed out to external proxies purely because verification is too weak.

## Limitations

VEP's strongest claim depends on user-supplied annotations. The paper is explicit that any safe program can pass only if the user provides sufficient preconditions, postconditions, and loop invariants. That is a real labor cost, especially once verification moves from memory safety to functional correctness.

The current prototype is also limited in engineering scope. The compiler intentionally includes only a few optimization passes, so the generated bytecode is not meant to be optimal. Helper specifications are built in rather than discovered automatically. The evaluation is convincing for feasibility but still benchmark-sized: Linux samples, teaching-style `StringLib` routines, and one larger case study are not the same as large, evolving production eBPF codebases. Finally, `VEP-eBPF` checks that bytecode matches its annotations and proofs, not that those annotations capture the programmer's true intent.

## Related Work

- _Gershuni et al. (PLDI '19)_ - `PREVAIL` keeps eBPF verification fully automatic through abstract interpretation, while `VEP` spends user annotations to avoid rejecting safe but complex programs.
- _Nelson et al. (LPC '21)_ - `ExoBPF` also explores proof-carrying in-kernel verification for eBPF, but it asks users to reason at the bytecode level instead of annotating C and compiling the proof artifacts downward.
- _Nelson et al. (SOSP '19)_ - `Serval` scales symbolic evaluation for systems code, whereas `VEP` specializes that style of reasoning to a source-to-eBPF pipeline with a kernel-resident checker.
- _Necula (POPL '97)_ - Proof-Carrying Code provides the basic producer/checker split that `VEP` adapts to Linux's eBPF loading path.

## My Notes

<!-- empty; left for the human reader -->

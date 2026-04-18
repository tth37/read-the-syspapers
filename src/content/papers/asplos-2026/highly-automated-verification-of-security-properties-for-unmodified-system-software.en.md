---
title: "Highly Automated Verification of Security Properties for Unmodified System Software"
oneline: "Turns security verification of unmodified system software into many small SMT checks with transition slicing, cone-of-influence pruning, and pointer abstraction."
authors:
  - "Ganxiang Yang"
  - "Wei Qiang"
  - "Yi Rong"
  - "Xuheng Li"
  - "Fanqi Yu"
  - "Jason Nieh"
  - "Ronghui Gu"
affiliations:
  - "Columbia University, New York, NY, USA"
  - "CertiK, New York, NY, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790171"
code_url: "https://github.com/VeriGu/spoq3"
tags:
  - verification
  - formal-methods
  - security
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Spoq2 is a verification framework for proving security properties of unmodified kernels, firmware, and hypervisors with much less manual proof work than prior Coq-heavy approaches. Its core move is to reduce security proofs to transition-local inductive checks, then aggressively simplify those checks with per-transition cone-of-influence analysis, pointer abstraction, and Z3 caching.

## Problem

The paper starts from a practical pain point in systems verification: we know how to state strong properties such as confidentiality, integrity, and noninterference, but proving them on real kernels, firmware, and hypervisors still costs too much. Real system software mixes C, assembly, concurrency, hardware state, and overloaded pointers. That combination defeats both manual proof engineering and automated SMT reasoning.

Previous work falls into two unsatisfying camps. Manual Coq-heavy efforts can establish strong guarantees, but they require thousands of proof lines and deep expertise. More automated systems such as Serval lower the burden, but they do not scale to the pointer-heavy unmodified code that released system software actually uses. Even when the property is conceptually simple, automated verification still runs into path explosion from branching and solver explosion from huge machine states and bit-vector-heavy pointer expressions.

The paper's target is therefore crisp: verify released, unmodified system code as it exists, and do so by turning the proof into obligations small enough that an SMT solver can actually finish.

## Key Insight

The paper's central claim is that many system-security properties can be reduced to inductive invariants over individual transitions, and that this decomposition is what makes automation practical. Instead of proving a relational security theorem over a whole execution at once, Spoq2 proves that an invariant holds initially and is preserved by each atomic transition, or by each transition pair in a composed two-run system for information-flow properties.

That localization creates room for aggressive simplification. Once the goal is "this transition preserves this invariant," Spoq2 can compute a cone of influence for just that transition, drop irrelevant state fields, eliminate impossible paths, and remove clauses already implied by dependence analysis. The same structure makes pointer abstraction effective: overloaded pointers become records with fields like `id`, `ofs`, and `valid`, so Z3 can use linear arithmetic rather than expensive bit-vector reasoning. The key idea is therefore not merely "use SMT," but "rewrite relational security proofs into many tiny checks whose irrelevant structure has already been cut away."

## Design

Spoq2's workflow has six stages. It compiles unmodified C to LLVM IR, takes a user-provided machine configuration for the abstract machine state, translates LLVM IR and supported assembly into Coq, and then applies verified transformation rules to produce self-contained transition functions. The user still writes the target security property as an invariant or a relation on a composed system, plus loop invariants and ranking functions where needed. Spoq2 checks those loop obligations with Z3 and then generates proof goals for initial states and transition paths.

The most important optimization is per-transition cone-of-influence analysis. For each property and transition, Spoq2 computes which variables can actually affect the result, removes irrelevant state updates, simplifies the Coq representation, and prunes proof goals whose path constraints are impossible under the assumption that the two runs differ only in private state. For relational proofs it also removes clauses that need not be checked explicitly. This is much more effective than whole-program COI because it works after the proof has already been decomposed into local goals.

Pointer abstraction is the second major idea. The user provides lightweight descriptions of bit layouts, usage hints, and optional memory-layout facts for overloaded pointers. Spoq2 rewrites common pointer manipulations into structured attributes and abstract operations, so a page-table entry exposes fields like `addr` and `valid` instead of forcing Z3 to reason about masks and shifts over 64-bit bit-vectors. It also caches generated Z3 expressions and full queries so repeated symbolic conditions are not re-solved from scratch.

## Evaluation

The evaluation is strong because it uses released, unmodified code rather than tool-friendly benchmarks. The authors verify four codebases: TF-RMM v0.3.0 for Arm CCA (`5.5K` LoC), TF-A v2.13 EL3 runtime firmware (`10.0K` LoC), SeKVM on Linux 6.1 (`4.0K` LoC), and Komodo (`1.5K` LoC). Across them, Spoq2 proves safety and information-flow properties such as Realm confidentiality and integrity, VM confidentiality and integrity, and enclave noninterference.

The headline results cover both effort and runtime. Relative to prior baselines, Spoq2 cuts manual effort by `80%` for RMM and `78%` for SeKVM, while TF-A, which had no previous baseline, requires only `1.6K` lines of manual inputs. End-to-end verification takes `255` minutes for RMM, `83` minutes for TF-A, `48` minutes for SeKVM, and `40` seconds for Komodo on a workstation. The framework also found two real bugs in the SeKVM Linux 6.1 port: inconsistent vCPU identifiers and a missing page-table lock acquisition in the `GRANT` hypercall.

The ablation study supports the mechanism claims well. With all optimizations enabled, Spoq2 reduces proof goals by `73%` on RMM, `85%` on TF-A, `82%` on SeKVM, and `92%` on Komodo, and cuts end-to-end time by `71%`, `86%`, `77%`, and `97%` respectively. Different systems benefit from different optimizations, which makes the story credible: state simplification matters most for RMM's large machine state, path pruning matters most for TF-A, and Z3 caching is especially important for Komodo. The Komodo comparison to Serval is also notable: Spoq2 verifies the same target about `7x` faster on the authors' machine. That supports the paper's intended claim well, though not a stronger claim of universal automation, since the framework still depends on user-written invariants and configurations.

## Novelty & Impact

Relative to _Li et al. (OSDI '23)_, Spoq2's novelty is not the LLVM-to-Coq pipeline itself, but repurposing that foundation for automated security proofs over unmodified system software. Relative to _Nelson et al. (SOSP '19)_, the key difference is support for the pointer-heavy and concurrent code patterns that blocked Serval from scaling to targets like TF-A and SeKVM. Relative to prior manual confidential-computing proofs such as _Li et al. (OSDI '22)_, the paper's contribution is reducing the proof burden enough that released codebases become realistic targets instead of research prototypes. The impact is practical: it offers a path from one-off expert verification to repeated verification of evolving low-level security software.

## Limitations

The framework is highly automated, not fully automatic. Users must still define the security property, machine configuration, pointer configuration, loop invariants, and ranking functions, and the paper says that writing the inductive invariants remains the most laborious part of the workflow. Its proof model also excludes important classes such as availability properties that do not reduce to inductive invariants. The current implementation only supports ARMv8 assembly, and soundness still depends on trusting user-provided configurations, the translators, the proof checker, and Z3.

There is also a scope limitation in the evaluation. The four targets are substantial, but they are all low-level security monitors, firmware, or hypervisors rather than a broader spread of systems code. A reasonable concern is how much extra engineering is required when new pointer idioms or concurrency patterns fall outside the current abstraction library.

## Related Work

- _Li et al. (OSDI '23)_ — Spoq scales LLVM-to-Coq translation for functional verification of real C systems code, and Spoq2 builds directly on that pipeline to automate security proofs instead of requiring manual Coq proof scripts.
- _Nelson et al. (SOSP '19)_ — Serval shows that symbolic automation can verify security properties of systems code, but Spoq2 targets unmodified pointer-rich and concurrent software that Serval cannot handle cleanly.
- _Li et al. (OSDI '22)_ — VIA verifies the Arm CCA architecture and an early RMM prototype with much heavier manual effort, whereas Spoq2 pushes similar security goals onto released TF-RMM code with far less proof scripting.
- _Lattuada et al. (SOSP '24)_ — Verus offers a practical verification foundation for systems written in Rust, while Spoq2 focuses on low-level C and assembly security reasoning for existing system software.

## My Notes

<!-- empty; left for the human reader -->

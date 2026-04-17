---
title: "Borrowing Dirty Qubits in Quantum Programs"
oneline: "QBorrow formalizes dirty-qubit borrowing and reduces safe-uncomputation checks for X/MCX-style circuits to SAT over just the `|0⟩` and `|+⟩` cases."
authors:
  - "Bonan Su"
  - "Li Zhou"
  - "Yuan Feng"
  - "Mingsheng Ying"
affiliations:
  - "Tsinghua University, Beijing, China"
  - "Institute of Software, Chinese Academy of Sciences, Beijing, China"
  - "University of Technology Sydney, Sydney, Australia"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790134"
code_url: "https://github.com/SugarSBN/QBorrow"
tags:
  - hardware
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

The paper introduces QBorrow, a quantum language extension that makes dirty-qubit borrowing explicit with `borrow ... release`. Its key result is a semantic definition of safe uncomputation as "the program acts like the identity on the borrowed qubit," plus a specialized SAT-based verifier for `X`/MCX-style circuits.

## Problem

Dirty qubits matter because they let a program reuse idle qubits instead of demanding new clean ancillas, which is valuable when NISQ-era qubits are scarce. But they are much harder to reason about than clean ancillas: the computation must be independent of the dirty qubit's unknown initial state, and the program must return not only that local state but also any entanglement the qubit had with the rest of the system. The paper's counterexample shows why the obvious basis-state check is too weak: a circuit can restore `0` and `1` correctly and still fail on `|+⟩`. The real problem is therefore to define safe dirty-qubit borrowing for programs with explicit control flow and then verify it without reasoning over all quantum states.

## Key Insight

The paper's key insight is that safe uncomputation should be defined as identity behavior, not as a narrow restoration rule over computational-basis inputs. If every execution is equivalent to `I_q ⊗ E'`, then the borrowed qubit is observationally untouched. This unifies three natural requirements: arbitrary pure states are restored, external entanglement is preserved, and the nondeterminism of choosing one idle qubit rather than another becomes unobservable. For circuits built only from `X` and multi-controlled `NOT`, the paper then proves that this condition can be checked using only the `|0⟩` and `|+⟩` initial states, which turns the problem into SAT.

## Design

QBorrow extends QWhile with `borrow a; S; release a`, where `a` is a placeholder instantiated nondeterministically from the syntactic idle set `idle(S)`. Programs therefore denote sets of quantum operations, with borrowing as the source of nondeterminism. This matters because nested borrows and explicit lifetimes now have a direct semantic account instead of being left to informal circuit reasoning. On top of that semantics, the paper defines safe uncomputation per qubit: `S` safely uncomputes `q` iff every operation in `JSK` factors as `I_q ⊗ E'`. The authors prove that this is equivalent both to restoring arbitrary pure states of `q` and to preserving any entanglement between `q` and an external hypothetical system.

The verifier then specializes to classical reversible dirty-qubit circuits. It tracks each qubit with a Boolean formula describing how `X` and controlled-`NOT` gates transform its basis value. Safe recovery of `|0⟩` becomes one unsatisfiability condition; safe recovery of `|+⟩` becomes another, requiring all other outputs to be independent of the dirty qubit's value. The resulting tool parses a restricted QBorrow language and submits the generated formulas to CVC5 or Bitwuzla.

## Evaluation

The evaluation asks a focused question: does the specialized verifier scale on circuits that really use dirty ancillas? The implementation is in C++ with ANTLR4, compiled with `g++ -O3`, and run on an 8-core Apple M3 MacBook Air with `24 GB` RAM. Benchmarks are MCX circuits adapted from Gidney and constant adders adapted from Häner et al. Formula construction takes under one second, so solver time dominates.

The scaling story is strong. On MCX, CVC5 goes from under `1s` at size `500` to `19s` at size `3500`, while Bitwuzla grows from `3s` to `189s`. On adders, the tool verifies up to Adder-200, with Bitwuzla reaching `303s` and CVC5 `1079s` on the largest case. The AutoQ comparison is the most convincing result: AutoQ needs `32s` at MCX-500 and `3065s` at MCX-3500, and it overruns on all reported adder cases even after simplifying the task to verify only one dirty qubit and only the `|+⟩` condition. By contrast, the paper's method verifies both `|0⟩` and `|+⟩` recovery for all dirty qubits. That supports the main claim well: exploiting the structure of dirty-qubit safety pays off dramatically in scalability.

## Novelty & Impact

Relative to _Svore et al. (RWDSL '18)_, the novelty is not the word `borrow`, but the formal semantics that say what safe dirty-qubit return means. Relative to clean-ancilla work such as _Bichsel et al. (PLDI '20)_, the contribution is showing that dirty ancillas need identity-style preservation rather than simple reinitialization. Relative to AutoQ, the paper's impact is methodological: it carves out a useful special case where quantum verification reduces to SAT and becomes practically scalable. The paper is most relevant to quantum PL, compiler, and verification researchers.

## Limitations

The biggest limitation is scope. The semantic framework covers full QBorrow programs with measurements and loops, but the efficient verifier only handles classical-function circuits built from `X` and multi-controlled `NOT`. That includes important dirty-ancilla patterns such as MCX and constant adders, but not arbitrary quantum subroutines. The experiments are also concentrated on two benchmark families and mostly measure solver cost, not end-to-end compiler integration. Finally, `idle(S)` is syntactic, so the paper does not yet deliver the more aggressive compiler-discovered reuse opportunities discussed in the closing section.

## Related Work

- _Svore et al. (RWDSL '18)_ — Q# already includes a `borrow` construct, but it does not formalize or verify safe dirty-qubit uncomputation the way QBorrow does.
- _Bichsel et al. (PLDI '20)_ — Silq gives safe uncomputation for clean ancillas; this paper shows dirty ancillas require identity-style preservation of state and entanglement instead of simple reinitialization.
- _Paradis et al. (PLDI '21)_ — Unqomp synthesizes uncomputation for clean-ancilla circuits, whereas QBorrow focuses on characterizing and checking when borrowed dirty qubits are returned safely.
- _Abdulla et al. (POPL '25)_ — AutoQ is a general-purpose quantum-circuit verifier, but this paper's SAT reduction trades generality for much better scaling on dirty-qubit safety checks.

## My Notes

<!-- empty; left for the human reader -->

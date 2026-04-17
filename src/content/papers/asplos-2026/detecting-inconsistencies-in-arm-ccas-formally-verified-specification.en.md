---
title: "Detecting Inconsistencies in Arm CCA’s Formally Verified Specification"
oneline: "Reconstructs Arm CCA's RMM spec into a Verus model and cross-checks tables, diagrams, and ABI rules to expose 35 Arm-confirmed inconsistencies."
authors:
  - "Changho Choi"
  - "Xiang Cheng"
  - "Bokdeuk Jeong"
  - "Taesoo Kim"
affiliations:
  - "Samsung Research, Seoul, Republic of Korea"
  - "Georgia Institute of Technology, Atlanta, GA, USA"
  - "Samsung Research / Georgia Institute of Technology, Seoul, Republic of Korea / Atlanta, GA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790152"
code_url: "https://github.com/islet-project/scope"
tags:
  - confidential-computing
  - verification
  - formal-methods
  - security
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Scope audits Arm CCA's Realm Management Monitor specification without needing an implementation. It parses the PDF, reconstructs a Verus model of RMM ABI semantics, and then checks whether summarized tables, diagrams, and command-level rules are mutually consistent. On multiple RMM versions, it reports 38 candidates, 35 of which Arm confirmed as real specification bugs.

## Problem

The paper starts from an uncomfortable fact about formal verification: proofs are only as trustworthy as the specification they prove against. If the specification is wrong, formally verified code can still be insecure, and the proof may only increase confidence in the wrong thing. Arm CCA is a particularly high-stakes target because the Realm Management Monitor (RMM) sits in the trusted computing base for confidential computing, and its specification evolves before implementations appear.

That makes the usual validation strategies weak fits. Testing against an implementation is impossible when the implementation does not exist yet. Manually proving meta-properties of the specification is expensive to maintain under frequent ABI updates. And the RMM document is not a small clean model; it is a long specification split across prose, tables, state-transition figures, command-condition functions, and ASL fragments. The practical problem is therefore to detect internal contradictions inside the specification itself, before those contradictions propagate into implementations, downstream formal models, or derived design documents.

## Key Insight

The central proposition is that a specification can be checked against itself if the document exposes two different views of the same behavior. Scope treats summarized tables and diagrams as statements of architectural intent, then asks whether the detailed ABI semantics and command conditions imply the same facts. If the two views cannot both be true, at least one of them is wrong.

That idea only becomes useful once the detailed parts of the document are turned into a machine-checkable oracle. Scope therefore reconstructs an executable logical model of the RMM specification in Verus and uses contradiction checking as the main auditing primitive. The paper's deeper insight is that this can be done even when many helper functions remain uninterpreted: one does not need a bit-precise implementation model to catch missing preconditions, impossible state transitions, or omitted outputs.

## Design

Scope has two analysis paths: formal reasoning and rule-based consistency checking. Both start from the same pipeline. The tool runs `pdftotext`, strips document noise, and parses the RMM PDF into logical components: command interfaces, data types, command-condition functions, footprints, and ASL snippets. It then translates those fragments into Verus. Commands become Boolean spec functions over inputs, outputs, and both old and new system states, which lets the model distinguish pre-state requirements from post-state effects. Scope also adds deduced conditions, such as "if no failure precondition holds, the command succeeds" and "unmodified fields stay unchanged."

For formal reasoning, Scope uses the reconstructed RMM model as an oracle. It manually or semi-manually converts summarized views into proof queries. For example, if a table says a command succeeds only when a particular `RIPAS` or `HIPAS` state holds, Scope emits Verus assertions that successful executions imply exactly those dependencies and state updates. If the solver finds an assertion violation, the table and the detailed command semantics disagree. The same mechanism is used for state-transition diagrams and implicit invariants derived from type definitions, such as protected versus unprotected IPA state constraints.

The second path is lighter weight but still valuable. Scope applies heuristic rules over parsed commands to catch missing footprint entries and dangling outputs. A missing footprint means a success condition mutates state that the footprint never says is modified. A dangling output means a command returns a register value whose postcondition is never specified. These checks do not require SMT reasoning, but they uncover specification bugs that would otherwise mislead implementers and downstream verifiers.

## Evaluation

The evaluation is strong because it measures both bug-finding utility and coverage over evolving specifications. Across multiple RMM versions, Scope reported 38 candidate inconsistencies, 35 of which Arm confirmed. Some bugs had persisted for as long as 33 months, and 13 were in newly introduced ABIs, which supports the paper's claim that the approach is useful precisely because the specification changes frequently.

On the main effectiveness study, formal reasoning on versions `1.0-eac5` and `1.0-rel0` produced precision of `33.33%` and `25%`, while the rule-based checks achieved `84.62%` on both versions. When the authors compare against LLM-based baselines on `1.0-rel0`, Scope reaches `61.90%` precision, versus `8.00%` for GPT-o1 and lower numbers for the other tested models. Coverage is also materially better than prior formal approaches: Scope covers `28/41` commands (`68%`) on the older versions and up to `79/101` (`78%`) on `1.1-alp12`, compared with `22` commands for VIA and `8` for Arm's published model-checking harnesses.

The results support the main claim well, with one caveat. The paper is excellent at showing that internal contradictions are common and actionable, but some precision loss still comes from underspecified uninterpreted functions and from document patterns the parser cannot fully normalize. So the win is not "push-button truth extraction"; it is "substantially more scalable and precise auditing than prior manual or LLM-heavy alternatives."

## Novelty & Impact

Relative to _Reid (OOPSLA '17)_, Scope automates specification auditing instead of relying on a largely manual validation workflow around architect-defined views. Relative to _Goldweber et al. (OSDI '24)_, it targets inconsistencies inside a formal specification document rather than checking whether formal properties capture developer intent at the implementation boundary. Relative to _Li et al. (OSDI '22)_ and _Fox et al. (OOPSLA '23)_, its contribution is not another proof of Arm CCA properties, but a method for questioning whether the thing being proved is internally coherent in the first place.

That makes this paper likely to matter to two communities: people building confidential-computing standards and firmware, and people doing system verification who are worried about specification trustworthiness. The main contribution is a new methodology rather than a new TEE mechanism, but it is a methodology with direct security consequences.

## Limitations

The paper is candid that Scope is not a full semantic model of Arm CCA. It uses many uninterpreted functions, is neither bit-precise nor byte-precise, and does not reason about ordering among failure conditions. Some summarized views still require manual translation into proof queries. Coverage also drops on commands whose descriptions are empty, highly prosaic, or use unsupported ASL syntax, so the tool is not yet a universal parser for evolving architecture specs.

There is also a reviewer-style concern the paper only partly addresses: if both the summarized view and the detailed command text copy the same wrong assumption, cross-checking them will not reveal the error. The method is best at catching mismatches between two views, not globally reconstructing intent from scratch. Still, the empirical bug count suggests that mismatch-style failures are common enough to make the approach worthwhile.

## Related Work

- _Reid (OOPSLA '17)_ — validates the Arm v8-M architecture specification using architect-defined views, but Scope pushes that idea into a more automated contradiction-checking workflow.
- _Li et al. (OSDI '22)_ — formally verifies parts of Arm CCA, whereas Scope focuses one layer earlier on whether the underlying RMM specification is itself internally consistent.
- _Fox et al. (OOPSLA '23)_ — presents a verification methodology for Arm CCA implementations and specifications, while Scope complements it with automated bug finding in the spec text and tables.
- _Goldweber et al. (OSDI '24)_ — argues that developer intent should audit formal specifications; Scope operationalizes a similar trust concern using summarized tables, diagrams, and rule-based checks.

## My Notes

<!-- empty; left for the human reader -->

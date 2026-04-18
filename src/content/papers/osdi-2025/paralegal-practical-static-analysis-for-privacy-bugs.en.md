---
title: "Paralegal: Practical Static Analysis for Privacy Bugs"
oneline: "Paralegal lets privacy engineers write marker-based privacy policies and checks them on Rust PDGs that approximate library behavior through ownership-aware types."
authors:
  - "Justus Adam"
  - "Carolyn Zech"
  - "Livia Zhu"
  - "Sreshtaa Rajesh"
  - "Nathan Harbison"
  - "Mithi Jethwa"
  - "Will Crichton"
  - "Shriram Krishnamurthi"
  - "Malte Schwarzkopf"
affiliations:
  - "Brown University"
conference: osdi-2025
code_url: "https://github.com/brownsys/paralegal"
tags:
  - security
  - formal-methods
  - pl-systems
category: verification-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Paralegal is a static analyzer for privacy bugs in Rust applications. Its central move is to separate privacy policy from source code using markers, then check those marker-level policies on a flow-, context-, and field-sensitive program dependence graph that can still reason about library code through Rust's ownership and lifetime information. Across eight real applications, it found seven privacy bugs, including two previously unknown ones.

## Problem

The paper starts from a practical gap between privacy requirements and the tools engineers actually use. Real applications must satisfy rules such as "all user data must be deletable", "a consent check must happen before collection", or "authorization must happen before a write". In practice, teams mostly rely on manual audits by privacy experts or consultants. That workflow is expensive, infrequent, and fragile under constant code churn.

Existing technical options each break down in a different way. Domain-specific privacy analyzers can be practical, but only because they hard-code one application model, one framework, or one kind of query language. Information-flow type systems can express some secrecy properties, but they are poor at "must happen" liveness-like requirements such as deletion, and they often require intrusive annotations or programming styles. General code-analysis systems such as CodeQL are flexible, but in return they force policy writers to talk about syntax, regular expressions over identifiers, and hand-maintained models of library behavior.

Paralegal is trying to solve the human-organization problem as much as the static-analysis problem. Privacy engineers understand policies, while application developers understand where those concepts live in code. A practical system therefore has to let those two groups collaborate without forcing either one to own the whole specification stack.

## Key Insight

The key claim is that privacy analysis becomes practical when the tool splits the job into three layers. Privacy engineers should write policies over semantic labels such as `user_data`, `deletes`, or `executes`. Developers should attach those labels to code entities they already understand. The analyzer should then answer whether the required dependency paths exist between those marked entities.

That separation only works if the analyzer can still model realistic Rust programs without drowning developers in manual library summaries. Paralegal's second insight is that Rust's type system gives it useful approximations for unknown code. Ownership and lifetimes constrain mutation and aliasing enough that the analyzer can often infer what an external function may affect from its type alone. Combined with markers, this means Paralegal can avoid expanding large parts of the call graph unless policy-relevant code is actually reachable.

## Design

Paralegal has three main pieces: a Program Dependence Graph (PDG), markers, and a policy DSL. The PDG is built from Rust MIR and is explicitly flow-sensitive, context-sensitive, and field-sensitive. Those choices matter to the paper's running Plume example. Without flow sensitivity, a program could appear to execute deletion after building queries even if the order were wrong; without context sensitivity, multiple calls to the same helper would get conflated; without field sensitivity, `posts` and `comments` inside the same structure would become indistinguishable and the missing comment-deletion bug would disappear.

To make that PDG practical on real code, Paralegal leans heavily on Rust. It monomorphizes trait-based calls using statically available types, clones callees per call site for precision, and uses a modular approximation for library functions whose bodies are unavailable or too expensive to analyze. That approximation starts conservative: arguments may influence outputs. It then sharpens the result with Rust-specific facts. Immutable references cannot be mutated, and lifetimes bound what returned references may alias. The tool therefore gets a much tighter library model than a language with unconstrained pointers would allow.

Markers are the bridge between code and policy. Developers can attach them to functions, arguments, return values, and types, and Paralegal propagates them onto concrete PDG nodes. Type-based propagation is intentionally broad: if a marked type appears anywhere inside another type, the enclosing value can inherit that marker. Paralegal also uses markers to prune analysis. If a callee and everything reachable from it cannot reach any marker, the tool skips building that subgraph and approximates the call from its type signature instead. This adaptive approximation is a core performance optimization, not a side detail.

Policies are written in a controlled natural-language DSL that compiles into graph queries. The primitive relations are simple but expressive: a marked value can "go to" a sink, "affect whether" an operation happens, or reach a sink "only via" some disclosure point. That is enough to encode deletion requirements, access-control preconditions, and purpose-limitation constraints. Error reporting then maps a failing quantified clause back to concrete source locations, so developers see which marked source failed to reach which marked sink.

## Evaluation

The evaluation is broad enough to support the practicality claim. The authors apply Paralegal to eight production-style Rust applications spanning graph databases, social platforms, payments, advertising, authentication, and homework submission. Across those applications they formalize 11 policies, mark between 4 and 145 program locations, and analyze between 1 and 72 entry points depending on the workload.

The bug-finding result is the headline: Paralegal reports seven privacy bugs across Plume, Atomic, and Lemmy, including two previously unknown bugs that the Lemmy developers confirmed. It also rediscovers previously fixed bugs, which is a useful sanity check that the policies are not overfit to one toy example. On the expressiveness side, the comparison with IFC and CodeQL is persuasive. IFC can only express six of the eleven policies because deletion and retention have a "must reach" shape rather than a classic noninterference shape. CodeQL's query language can encode the relevant policies, but its engine runs into missing interprocedural control flow, hidden library semantics, missing alias analysis, and async/C++ impedance mismatches. The authors' qualitative breakdown that only 36% of CodeQL predicates were actual policy logic is a strong argument that markers really are doing meaningful ergonomic work.

The maintenance and performance numbers are also good. Running one Atomic policy over 1,024 commits spanning 2.5 years, the authors find only two commits that affected markers, while the policy itself never had to change. In the "Workspace Only" configuration, most applications finish in under 2.2 seconds, with Hyperswitch at 12 seconds and Lemmy at 22.5 seconds; per-endpoint latency averages 0.8 seconds and stays under five seconds in the worst case. In the "All Dependencies" configuration, most applications still finish in under five seconds, while Lemmy reaches 94 seconds because it has 72 endpoints. Adaptive approximation cuts runtime by 35% on average and is necessary for Lemmy and Plume to terminate in the fixed-depth comparison.

## Novelty & Impact

Paralegal's main novelty is not the bare use of PDGs or the fact that it targets privacy. The new contribution is the combination of marker-based policy decoupling, Rust-aware library approximation, and a policy DSL that can express both forbidden flows and required flows. Relative to domain-specific compliance tools, it gives up baked-in semantics in exchange for broader applicability. Relative to IFC, it handles a wider class of policies. Relative to query engines like CodeQL, it shifts a large amount of brittle "find the right syntactic thing" work out of the policy and into reusable marker assignments plus language-aware analysis.

That makes the paper useful beyond privacy narrowly construed. The authors already note internal interest in checking cryptographic-key secrecy, encryption-at-rest, and speculative-execution mitigations. More broadly, the paper shows a credible way to turn legal or policy language into something a CI pipeline can check without forcing the whole application into a special framework or type discipline.

## Limitations

The paper is careful not to oversell soundness. Paralegal is a static bug finder, not a proof that an application is privacy-correct. Its soundness and completeness are policy-dependent because the PDG can include false dependencies and, in some cases, miss real ones. Unsafe code, interior mutability, shared-memory synchronization, and effects on external systems such as filesystems or databases can all hide dependencies from the type-based approximation.

There are also usability boundaries. Markers currently attach only to functions, arguments, return values, and types, not to fields or constants, which sometimes forced the authors to add no-op helper functions or refactor code. The tool deliberately drops control flow introduced by `await` state machines to reduce confusing false positives, which means it may miss some malicious async patterns. Finally, the fastest local analysis mode can miss markers in dependencies; the paper's answer is to pair quick local checks with a slower whole-dependency CI run.

## Related Work

- _Crichton et al. (PLDI '22)_ - Flowistry provides the ownership-aware information-flow machinery that Paralegal builds on, but Paralegal adds markers, a policy DSL, and a privacy-bug-finding workflow aimed at developers and privacy engineers.
- _Johnson et al. (PLDI '15)_ - Pidgin also uses program dependence graphs to enforce security guarantees, but Paralegal relies on Rust's ownership types to approximate libraries and makes policy code less entangled with low-level analysis details.
- _Ferreira et al. (S&P '23)_ - RuleKeeper achieves GDPR-style compliance by modeling one web-framework stack, whereas Paralegal targets general Rust applications without assuming a fixed framework semantics.
- _Albab et al. (SOSP '25)_ - Sesame enforces end-to-end privacy compliance with Rust types plus runtime policy containers, while Paralegal keeps checking entirely static and lightweight enough for CI-style bug finding.

## My Notes

<!-- empty; left for the human reader -->

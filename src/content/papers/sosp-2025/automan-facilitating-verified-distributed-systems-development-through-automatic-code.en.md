---
title: "AutoMan: Facilitating Verified Distributed Systems Development Through Automatic Code Generation and Manual Optimizations"
oneline: "AutoMan turns Dafny TLA actions into verified code plus refinement scaffolding, so developers hand-optimize only the hot path instead of building the whole system manually."
authors:
  - "Zihao Zhang"
  - "Ti Zhou"
  - "Christa Jenkins"
  - "Omar Chowdhury"
  - "Shuai Mu"
affiliations:
  - "Stony Brook University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764822"
tags:
  - verification
  - formal-methods
  - pl-systems
  - fault-tolerance
category: verification-and-reliability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

AutoMan is a Dafny/TLA workflow that automatically turns state-machine actions into executable Dafny code, abstraction functions, and refinement proof obligations, then lets developers manually optimize only the hot actions. Across Multi-Paxos, PBFT, a sharded KV store, and CausalMesh, it cuts manual implementation effort by 70%-97%; for Multi-Paxos, the optimized result reaches 97% of IronFleet's throughput.

## Problem

The paper starts from a familiar systems dilemma. Refinement-based verification frameworks such as IronFleet can produce machine-checked distributed systems, but the human cost is high because engineers still have to write large implementations and the proof structure that connects them back to the spec. At the other extreme, compilers from formal models to code lower developer effort, but they either generate conservative, slow implementations or force users to trust the compiler itself. For distributed systems, that trust gap matters: if the generator is wrong, the whole "correct by construction" story collapses.

The authors argue that this is especially painful in the parts of the workflow between a verified protocol design and a runnable implementation. Distributed protocols are often already described as TLA-style state machines, but those declarative predicates do not directly tell developers how to implement the corresponding actions efficiently. Worse, a lot of implementation code lives in performance-insensitive recovery or control logic, so spending expert effort on every line is a bad use of scarce verification time. The paper therefore asks whether we can mechanically generate the correct baseline implementation, keep end-to-end refinement guarantees, and reserve human effort for the few places where performance really matters.

## Key Insight

The core proposition is that action-level refinement gives exactly the right seam for automation. A TLA-style distributed system is decomposed into action predicates, and each action can be connected to a generated implementation function plus a refinement obligation stating that the function's input/output behavior matches the predicate. If the generator emits code together with those obligations, developers do not need to trust the generator: Dafny still checks that the generated code refines the original specification.

That same seam also makes hybrid development practical. Most actions can remain auto-generated and functional, while developers selectively replace a few hot actions with imperative, hand-optimized code and prove that those replacements either refine the original spec directly or are equivalent to the generated version. In other words, AutoMan is not trying to synthesize a perfect final system. It is trying to make the "correct first, optimize later" workflow verification-friendly and cheap enough to use.

## Design

AutoMan assumes a four-layer refinement story: an abstract centralized model `S0`, a concrete distributed protocol specification `S1`, an automatically generated implementation `I0`, and an optionally optimized implementation `I1`. The input is a TLA-style state-machine specification written in Dafny, plus user mode annotations that mark each predicate argument as input or output. Those annotations are necessary because TLA predicates are relational, while generated code must be functional: given the inputs, the outputs must be computable.

The translator itself is organized as `Parser -> Annotator -> Mode Validator -> Checker -> Code Generator`. The validator enforces syntactic restrictions that keep translation deterministic, such as disallowing output-defining disjunctions or existential quantifiers and requiring annotations to match arity and naming. The checker then performs semantic, flow-sensitive analysis to ensure every output variable is assigned completely and uniquely, that dependencies between outputs are ordered correctly, and that quantified collection updates fall into patterns the generator can compile. When a predicate falls outside the supported fragment, AutoMan emits a stub instead of guessing, leaving that action for manual implementation.

For predicates that pass, the generator produces functional Dafny code by turning conjunctive constraints into explicit computations. Equalities become local bindings, predicate calls become function invocations, and quantified collection updates become comprehensions. The important second output is refinement scaffolding. AutoMan synthesizes `Valid` predicates and `Abstract` functions for implementation types, then inserts `requires` and `ensures` clauses showing that inputs are valid refinements, outputs remain valid, and the generated function satisfies the original action predicate after abstraction. Because this scaffolding is generated systematically, the proof boilerplate for `I0` is drastically reduced.

Manual optimization targets `I1`. The paper focuses on three recurring bottlenecks in generated code: unnecessary traversals induced by quantifiers, failure to exploit semantic data properties such as sortedness, and verification-friendly immutable data structures that are expensive at runtime. Developers rewrite those hot functions imperatively, often with auxiliary metadata or mutable maps, and verify them with the same scaffolding. When mutable state complicates reasoning, the paper uses ghost variables to mirror the abstract state and prove refinement in two steps: first over the ghost view, then between ghost and concrete state. Verified generated and manual actions are finally composed with external glue such as the event loop and networking framework to form a runnable system.

## Evaluation

The evaluation is broad enough to test the methodology rather than a single toy example. The authors implement the translator in OCaml and apply it to Multi-Paxos, PBFT, a sharded key-value store, and CausalMesh. The reported implementation-effort numbers are substantial. For Multi-Paxos, AutoMan generates 2,119 lines of code and needs only about 200 manual lines plus roughly four hours to obtain `I0`; a fully manual IronFleet implementation is about 8,100 lines. For the sharded KV store, `I0` needs about 80 manual lines and two hours versus roughly 2,700 manual lines in IronKV. Those comparisons support the headline 97% effort reduction for the baseline generated systems, and the optimized versions still reduce manual work by 70% for Multi-Paxos and 56% for the KV store.

Performance is more nuanced, which makes the evaluation credible. The automatically generated Multi-Paxos baseline is not competitive enough on its own: its peak throughput is only 36% of IronRSL and it collapses under overload. But after optimizing five hot actions, throughput improves by 2.7x and reaches 97% of IronRSL, while leader recovery stays within 100 ms just like the manual system. PBFT shows the same pattern: optimizing four hot actions cuts their CPU share from 61.2% to 18.2% and doubles peak throughput by 2.04x. The simpler sharded KV store is the counterexample that supports the paper's broader claim: even without significant tuning, the generated implementation already achieves over 90% of IronKV's throughput, and the optimized version merely adds another 8% to match IronKV. CausalMesh improves by 1.92x after optimization, but still trails the original unsafe Rust version by over 4.7x, which is an important reminder that AutoMan closes much of the gap to verified implementations, not necessarily to aggressively engineered unverified ones.

## Novelty & Impact

The main novelty is not just "code generation for specs" and not just "verification in Dafny." The paper's contribution is the combination: a translator that is intentionally untrusted, because every generated action comes with refinement obligations, plus a workflow that treats manual optimization as a first-class refinement step rather than a post-verification escape hatch. That distinguishes AutoMan from IronFleet and Verdi, which show how to verify distributed implementations but still demand large manual proof effort, and from PGo, which compiles models to code but does not close the trust loop with proof obligations for the generated output.

If this approach matures, it gives verification teams a more realistic adoption path. They can continue writing TLA-style specs, get a correct baseline implementation quickly, and invest scarce expert time only where profiling says it matters. The likely impact is therefore on practitioners building verified consensus, replication, and coordination services, as well as on PL/systems researchers looking for middle ground between full synthesis and fully manual proofs. This is best read as a new workflow and mechanism for verified systems construction.

## Limitations

The strongest limitation is that AutoMan only handles a restricted Dafny fragment. Some actions with existentially quantified state transitions cannot be translated and must be implemented manually, and the translator's left-to-right local analysis is more restrictive than the semantics really require. The authors are explicit that richer inter-predicate analyses or SyGuS-style synthesis could extend coverage, but that is future work.

The second limitation is that "automatic" still stops well short of full system construction. Developers must still write the TLA spec, prove the protocol-level refinement from `S1` to `S0`, add glue code such as networking and event loops, and sometimes add proof annotations when Dafny does not discharge generated obligations automatically. Finally, the performance story depends heavily on targeted manual tuning for complex systems, and AutoMan does not yet generate multithreaded code. The paper's own CausalMesh result, still far behind the unsafe Rust baseline, shows that refinement-friendly generated code does not eliminate the classic tension between proof convenience and peak performance.

## Related Work

- _Hawblitzel et al. (SOSP '15)_ - IronFleet proves practical distributed systems correct in Dafny, but the implementation and much of the refinement structure are still written manually; AutoMan tries to automate exactly that spec-to-implementation step.
- _Wilcox et al. (PLDI '15)_ - Verdi offers a framework for implementing and verifying distributed systems in Coq, whereas AutoMan emphasizes generated code plus SMT-checked refinement obligations in Dafny to reduce proof-to-code effort.
- _Hackett et al. (ASPLOS '23)_ - PGo also compiles distributed-system models into executable implementations, but it does not verify the generated code; AutoMan's distinguishing feature is the scaffolding that lets Dafny check the generated code afterward.
- _Sharma et al. (SOSP '23)_ - Grove reduces verification effort with reusable distributed-systems proof libraries, while AutoMan attacks a different bottleneck by synthesizing large parts of the implementation itself.

## My Notes

<!-- empty; left for the human reader -->

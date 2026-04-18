---
title: "Basilisk: Using Provenance Invariants to Automate Proofs of Undecidable Protocols"
oneline: "Basilisk turns hard global protocol invariants into local provenance facts, then uses atomic sharding to synthesize inductive invariants automatically in Dafny."
authors:
  - "Tony Nuda Zhang"
  - "Keshav Singh"
  - "Tej Chajed"
  - "Manos Kapritsos"
  - "Bryan Parno"
affiliations:
  - "University of Michigan"
  - "University of Wisconsin–Madison"
  - "Carnegie Mellon University"
conference: osdi-2025
code_url: "https://github.com/GLaDOS-Michigan/Basilisk"
tags:
  - verification
  - formal-methods
  - pl-systems
category: verification-and-security
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Basilisk automates a part of distributed-protocol verification that usually dominates the human effort: inventing the inductive invariant. Its core move is to replace hand-written global protocol facts with mechanically derived provenance invariants, then use atomic sharding to infer those invariants from how a host's state variables are updated.

## Problem

The paper starts from a real bottleneck in formal verification of distributed protocols. Safety properties such as agreement are usually not inductive on their own, so the verifier needs a stronger inductive invariant that both implies safety and is preserved by every step. In decidable fragments such as EPR, prior systems can infer many such invariants automatically, but the price is a restrictive modeling language that excludes common patterns like arithmetic. In general-purpose frameworks such as Dafny or IronFleet-style proofs, the developer can model the protocol naturally, but then they usually have to discover the invariant manually.

That search process is the painful part. The authors argue that the difficult clauses are rarely local facts like monotonicity; they are the cross-host and cross-step facts that explain why one host's current state is justified by another host's earlier action. Kondo reduced some of the burden, but still left these conceptually hard properties to human intuition. The question Basilisk asks is whether those "creative" invariant clauses can be decomposed into simpler facts that a tool can derive automatically even in an undecidable logic.

## Key Insight

The central claim is that many protocol invariants that look global are really causal lineage statements. Instead of writing "if a participant decides Commit, the coordinator must also have decided Commit" directly, Basilisk traces how that participant state arose: some receive step wrote the decision, that step consumed a particular message, and that message must itself have been sent by an earlier sender step. If those provenance links are recorded as invariants, the global fact follows by chaining them.

This works because Basilisk reasons over a history-preserving model. Once a host's history records that a step sent a message or changed a local field, no future transition can erase that fact. Each provenance invariant is therefore individually inductive. The remaining challenge is finding the right provenance witnesses automatically, and that is where atomic sharding enters: if a group of variables is always updated together, then a non-initial current value proves that one of a small set of steps must have established that value.

## Design

Basilisk introduces two provenance forms. A `Network-Provenance Invariant` ties a message currently in the asynchronous network to one of the sender steps that could have emitted it. A `Host-Provenance Invariant` ties a property of a host's current local state to one of the steps that must have made that property become true. The paper uses Two-Phase Commit to show how these local facts recover inter-host reasoning: a participant's `Commit` must come from a `DECIDE(Commit)` message, and such a message must come from a coordinator send step whose local state already held `Commit`.

The automation mechanism is atomic sharding. Basilisk first estimates each step's footprint, meaning the set of local variables the step may modify. It then intersects these footprints to compute maximal atomic shards: subsets of variables that are always updated together by exactly the same steps. For each shard, Basilisk creates a provenance witness saying, in effect, "these variables currently have their present values and they were not initially so." From that, it derives a host-provenance invariant whose witness step must appear somewhere in the host's history. The paper also refines shards for collection-valued state such as sets and maps, because maximal shards can otherwise collapse the provenance of individual elements.

The full tool flow is practical rather than magical. The user writes host types, initial conditions, transition relations, and monotonic annotations in Dafny. Basilisk then generates a history-preserving asynchronous protocol model with an unreliable network that may delay, drop, duplicate, and reorder messages. On top of that model it synthesizes regular invariants: the new provenance invariants plus Kondo's monotonicity and ownership invariants. It also emits a machine-checked proof that the generated invariant is inductive. The prototype is implemented by extending the Kondo/Dafny 4.2 codebase with about 2,000 lines of C#.

## Evaluation

The evaluation is a methodology study rather than a performance benchmark. Basilisk is applied to 16 distributed protocols, including Echo Server, Paxos variants, Raft leader election, Two-Phase Commit, Three-Phase Commit, and Multi-Paxos. The strongest headline result is that the `User invs` column is zero for all 16 protocols: Basilisk finds inductive invariants sufficient for the proofs without any user-written invariant clauses.

The comparison against Kondo supports the main claim that provenance structure removes human invariant discovery. For Paxos, Kondo needed 20 manual invariant clauses, while Basilisk needed none. For Multi-Paxos, Basilisk still needed no user invariants; the final proof used 4 monotonic annotations, 2 provenance hints, 522 lines in the safety proof, and 565 lines total, and Dafny verified it in 61.5 seconds. Across the full evaluation, only 6 out of 64 Host-Provenance Invariants required a manual witness hint.

Basilisk also improves proof ergonomics. Flexible Paxos needed a 441-line safety proof in Basilisk versus 559 lines in Kondo, and verified in 22.8 seconds instead of 49.4 seconds. The paper's explanation is credible: Basilisk lets the user model receive-and-send behavior as a single atomic step, so the protocol description is smaller and the proof is authored directly for the asynchronous model instead of being translated from a synchronous one.

## Novelty & Impact

Relative to _Zhang et al. (OSDI '24)_, Basilisk generalizes Kondo's send and receive reasoning into a broader provenance-based taxonomy and automates much more of the inductive invariant. Relative to _Hawblitzel et al. (SOSP '15)_, it keeps the power of undecidable-logic verification but removes the need to manually search for most of the invariant. Relative to _Mora et al. (OOPSLA '23)_, it derives the key facts statically from protocol steps instead of mining them from executions.

The likely impact is on people who verify protocols in expressive proof frameworks and are blocked less by theorem proving than by invariant discovery. Basilisk does not eliminate the final proof obligation, but it changes the job from "invent the right invariant" to "show the generated invariant implies safety," which is a materially narrower task.

## Limitations

The paper is clear that Basilisk is not complete. Atomic sharding misses some relationships that are only established implicitly across multiple steps, especially epoch changes that reset collections. In those cases the user must supply a provenance witness hint. The strength of the generated invariants also depends on footprint precision: over-approximated footprints are safe but can weaken the resulting disjunctions.

There are also modeling and scope limits. The current prototype accepts a restricted update syntax and rejects steps whose different variables are conditionally updated under different conditions unless the user rewrites them as separate steps. More fundamentally, Basilisk is about safety of crash-fault-tolerant message-passing protocols; it does not address liveness, Byzantine settings, or the correctness of the real implementation unless the user separately proves the model matches the code. As with any theorem-proving result, the proof also trusts Dafny and its underlying stack.

## Related Work

- _Zhang et al. (OSDI '24)_ — Kondo introduced the invariant taxonomy Basilisk builds on, but still required developers to write the hard protocol invariants by hand.
- _Hawblitzel et al. (SOSP '15)_ — IronFleet verifies practical distributed systems in an expressive setting, but places invariant invention and proof construction on the user.
- _Mora et al. (OOPSLA '23)_ — Message Chains also structure distributed-system invariants, but infer them via specification mining over executions rather than static provenance analysis.
- _Padon et al. (OOPSLA '17)_ — Paxos Made EPR shows the opposite tradeoff: more automation by forcing the protocol into a decidable logical fragment.

## My Notes

<!-- empty; left for the human reader -->

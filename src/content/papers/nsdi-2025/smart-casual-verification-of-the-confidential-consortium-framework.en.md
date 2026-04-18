---
title: "Smart Casual Verification of the Confidential Consortium Framework"
oneline: "Pairs TLA+ specs with trace validation against CCF’s C++ tests so a production confidential-consortium service can catch subtle protocol bugs in CI."
authors:
  - "Heidi Howard"
  - "Markus A. Kuppe"
  - "Edward Ashton"
  - "Amaury Chamayou"
  - "Natacha Crooks"
affiliations:
  - "Azure Research, Microsoft"
  - "UC Berkeley"
conference: nsdi-2025
tags:
  - consensus
  - verification
  - formal-methods
  - confidential-computing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CCF is a production confidential-computing system whose protocol and client semantics differ enough from Raft that ordinary tests left important gaps. The authors pair TLA+ specs with trace validation against the production C++ test harness, integrate the flow into CI, and use it to find six subtle consensus bugs before customer impact.

## Problem

CCF backs Azure Confidential Ledger and mixes TEEs, state-machine replication, and an auditable log. Its consensus has diverged enough from vanilla Raft that prior proofs are no longer a good fit: CCF adds signature transactions, unidirectional messaging, optimistic acknowledgement, fast catch-up, `CheckQuorum`, and reconfiguration with retiring nodes and `ProposeVote`. Those features are exactly the kind of changes that look incremental in code but create subtle safety and liveness corner cases.

The client side is also nonstandard. To cope with early SGX memory limits, CCF replies before replication completes, so clients can observe `Pending`, `Committed`, and `Invalid` states. That improves resource usage, but it makes the externally visible guarantees more subtle than plain linearizability. The problem, then, is to verify distributed safety, formalize what clients may rely on, and check the shipping 63 kLoC C++ system without rewriting it or slowing a codebase that changes every week.

## Key Insight

The key idea is to treat TLA+ as living documentation of the protocol, then bind it to reality with trace validation. A high-level spec alone cannot show that the C++ code matches the model, and ordinary testing rarely checks the right invariants in every intermediate state. But if each implementation trace constrains the high-level actions, then a failed match means either the code, the logging, or the spec is wrong.

That is what the authors mean by `smart casual verification`: formal enough to capture real distributed invariants, pragmatic enough to live inside normal CI and debugging workflows. The method keeps the leverage of model-based reasoning while avoiding a fully verified rewrite.

## Design

The verification stack has three pieces. The consensus spec models CCF in TLA+ with 17 actions and 13 variables. Its main safety checks are `LogInv`, `AppendOnlyProp`, and `MonoLogInv`, and it includes the CCF-specific mechanisms that matter for correctness: dual quorums during reconfiguration, node retirement, message loss, and protocol optimizations. Exhaustive checking runs on bounded models, while larger spaces are explored with weighted simulation.

The client-consistency spec deliberately abstracts away node internals. It uses only `history`, an append-only sequence of client-visible events, and `logBranches`, a compact representation of leader logs across terms. That is enough to formalize properties such as ancestor commit and whether a later read must observe an earlier committed write.

Trace validation ties both specs to the C++ implementation. The team extends a deterministic test driver, adds 15 log points at side-effect-free linearization points, and builds a `Trace` model that reuses the high-level actions. Action composition aligns mismatched atomicity, such as term updates piggybacked on `AppendEntries`, and DFS makes validation practical because the checker only needs one behavior in the intersection of the trace and the spec.

## Evaluation

The paper evaluates engineering payoff rather than runtime performance. The consensus spec is 1,134 lines plus a 369-line trace-validation layer; the consistency spec is 375 lines plus 111 lines of trace logic. A concrete optimization matters a lot here: switching trace validation from BFS to DFS cuts consistency checking from about an hour to under a second.

The main result is bug-finding. The workflow uncovered six consensus bugs before production impact: incorrect election quorum tally, commit advance for previous terms, commit advance on `AE-NACK`, truncation from early `AppendEntries`, inaccurate `AE-ACK`, and premature node retirement. The first came from 48 hours of model checking on a 128-core machine; others surfaced during simulation and spec-code alignment. The consistency model also exposes a 12-step counterexample showing that committed read-only transactions are not always linearizable, only serializable. That evidence supports the paper’s central claim, although it remains a single-system case study rather than a controlled comparison with other industrial verification stacks.

## Novelty & Impact

The novelty is not a new algorithm but a repeatable process for verifying an already-deployed distributed system. By connecting abstract TLA+ models to real traces, the paper shows a middle ground between pure testing and fully verified rewrites. That makes it useful both to industrial teams shipping consensus-heavy services and to researchers studying how formal methods survive implementation drift.

## Limitations

This is not end-to-end formal verification. State spaces are bounded, trace coverage still depends on scenarios and instrumentation, and consensus trace validation cost about two engineer-months plus TLC extensions for DFS, debugging, and action composition. The authors also report that manual action weighting worked better than their Q-learning attempt. Finally, the client contract still stops short of linearizable reads.

## Related Work

- _Hawblitzel et al. (SOSP '15)_ - IronFleet proves distributed implementations end to end, while this paper keeps an existing C++ system and accepts lighter guarantees in exchange for deployability.
- _Wilcox et al. (PLDI '15)_ - Verdi builds verified fault-tolerant systems in Coq, whereas CCF emphasizes continuous verification of an already-running codebase rather than extraction of a new implementation.
- _Davis et al. (VLDB '20)_ - The MongoDB trace-validation work also checks implementation traces against TLA+ models, but this paper focuses more explicitly on action composition and industrial CI integration.
- _Bornholt et al. (SOSP '21)_ - Amazon’s lightweight verification of S3 uses executable reference models, while CCF uses TLA+ to reason about reconfiguration, consensus safety, and client-visible consistency.

## My Notes

<!-- empty; left for the human reader -->

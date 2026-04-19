---
title: "Multi-Grained Specifications for Distributed System Model Checking and Verification"
oneline: "Remix verifies ZooKeeper with phase-wise mixed-grained TLA+ models, exposing six deep bugs without paying full-system state-space cost."
authors:
  - "Lingzhi Ouyang"
  - "Xudong Sun"
  - "Ruize Tang"
  - "Yu Huang"
  - "Madhav Jivrajani"
  - "Xiaoxing Ma"
  - "Tianyin Xu"
affiliations:
  - "SKL for Novel Soft. Tech., Nanjing University, China"
  - "University of Illinois Urbana-Champaign, IL, USA"
conference: eurosys-2025
category: reliability-and-formal-methods
doi_url: "https://doi.org/10.1145/3689031.3696069"
project_url: "https://zenodo.org/records/13738672"
tags:
  - formal-methods
  - verification
  - consensus
  - fault-tolerance
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Remix verifies ZooKeeper by mixing TLA+ specifications at different granularities per Zab phase. It models the target phase finely, coarsens the rest with preserved interactions, and ties the model back to Java with deterministic conformance checking, exposing six severe bugs efficiently.

## Problem

ZooKeeper already has protocol and system specifications, but they abstract away exactly where implementation bugs hide. The paper highlights three recurring model-code gaps: actions that are atomic in TLA+ but not in code, local multithreading collapsed into one model action, and simplified state transitions that omit real branches. Those gaps are especially dangerous in synchronization and log replication, where `NEWLEADER`, asynchronous logging, and recovery interact in ways the coarse model never explores.

The alternative is not attractive either. If everything is modeled at code granularity, TLC becomes unusable: the official ZooKeeper system specification does not finish in ten days even for three nodes, three transactions, and up to three crashes and partitions, and that model still omits some concurrency details. The paper therefore asks how to make the model faithful enough for the checked module without paying for a fully fine-grained system model.

## Key Insight

The central claim is that granularity should be a per-module choice. If the target module is modeled finely while surrounding modules are coarsened only in ways that preserve dependency and interaction variables, then the target still sees the same relevant behaviors at much lower cost. That lets the checker focus its state-space budget exactly where the model-code gap matters.

Zab's phase structure makes this practical. Election, Discovery, Synchronization, and Broadcast already form relatively clean modules, so each phase can have coarse- and fine-grained variants composed differently for protocol verification, implementation verification, or checking a local fix.

## Design

For fine-grained specs, Remix rewrites misleading atomic actions into code-shaped ones and models inter-thread communication explicitly. The running example is follower handling of `NEWLEADER`: instead of one atomic step, the refined model separates epoch update, queueing of requests for asynchronous logging, leader reply, and the logging-thread action `FollowerSyncProcessorLogRequest`. The enabling conditions are derived from the Java code so TLC can explore intermediate states and local thread interleavings.

For coarse-grained specs, Remix keeps only what other modules can observe. Election and Discovery, for example, can be collapsed into one abstract `ElectionAndDiscovery` action as long as externally visible updates such as node role and phase are preserved. The paper formalizes this with dependency variables, interaction variables, and an interaction-preservation theorem over projected traces.

The mixed-grained system is then a normal TLA+ `Next` relation over the chosen per-phase actions plus fault actions. Remix adds tooling that composes module variants, checks invariants, and runs conformance checking by sampling model traces and replaying them deterministically in ZooKeeper through coordinator-driven AspectJ/RMI instrumentation.

## Evaluation

On ZooKeeper v3.9.1, Remix finds six severe bugs causing data loss, data inconsistency, or synchronization failure. These are not shallow traces: first violations appear after 12-21 state transitions and roughly 14 thousand to 2.88 million explored states, and all six are confirmed by deterministic replay in Java.

The efficiency comparison is the strongest evidence. Every bug appears in under two minutes, several in around 10-20 seconds. In the controlled study, the baseline system specification and a fully fine-grained composition (`mSpec-4`) fail to finish within 24 hours because TLC spends most of its effort in leader election. Once Election and Discovery are coarsened, the mixed-grained models become practical: `mSpec-2` finds the first violation in 1 minute 15 seconds and `mSpec-3` in 11 seconds, while `mSpec-4` needs 8 hours 32 minutes. The authors also report roughly 40 person-hours to write the extra specifications and instrumentation.

The workloads here are model-checking configurations over bounded three-node clusters, not production traces. That is appropriate to the paper's claim: the evaluation is about verification feasibility, not runtime performance of ZooKeeper itself.

## Novelty & Impact

The novelty is a workflow for existing systems, not a new proof engine: write multi-grained TLA+ specifications, compose them by protocol phase, and keep them synchronized with code through deterministic replay. That moves TLA+ beyond design documentation into implementation-oriented bug finding and fix validation.

The impact is strongest for systems like ZooKeeper whose implementations have drifted from the original protocol through optimization. The authors even use the exercise to revise Zab so history update must precede epoch update, making the protocol easier to implement correctly.

## Limitations

The authors are explicit that conformance checking is unsound: implementation behaviors absent from sampled traces may still be missed. The framework checks safety only, not liveness, and it still depends on manual work to choose granularities, write module variants, and map model actions to instrumented code events.

ZooKeeper is also a favorable case because Zab already decomposes into four clear phases. A system with messier cross-module entanglement may be harder to coarsen cleanly, and the paper argues for generality more than it demonstrates it across multiple codebases.

## Related Work

- _Newcombe et al. (CACM '15)_ - documents how AWS uses formal methods to validate system designs, whereas this paper pushes TLA+ toward code-level verification of an evolving production implementation.
- _Gu et al. (SRDS '22)_ - uses interaction-preserving abstraction for compositional checking of consensus protocols; this paper borrows the interaction idea but uses it to coarsen non-target modules without requiring refinement.
- _Tang et al. (EuroSys '24)_ - SandTable also combines TLA+ model checking with conformance checking, while Remix adds multi-grained composition and explicit control of user-level thread interleavings.
- _Yang et al. (NSDI '09)_ - MODIST model-checks unmodified distributed implementations directly, whereas Remix keeps the search at the model level and uses deterministic replay only to confirm and debug behaviors in code.

## My Notes

<!-- empty; left for the human reader -->

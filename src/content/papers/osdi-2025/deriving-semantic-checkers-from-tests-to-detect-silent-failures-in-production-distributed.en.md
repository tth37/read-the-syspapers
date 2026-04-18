---
title: "Deriving Semantic Checkers from Tests to Detect Silent Failures in Production Distributed Systems"
oneline: "T2C turns existing system tests into runtime semantic checkers by slicing out assertions, inferring trigger preconditions, and validating the result against other passing tests."
authors:
  - "Chang Lou"
  - "Dimas Shidqi Parikesit"
  - "Yujin Huang"
  - "Zhewen Yang"
  - "Senapati Diwangkara"
  - "Yuzhuo Jing"
  - "Achmad Imam Kistijantoro"
  - "Ding Yuan"
  - "Suman Nath"
  - "Peng Huang"
affiliations:
  - "University of Virginia"
  - "Bandung Institute of Technology"
  - "Pennsylvania State University"
  - "Johns Hopkins University"
  - "University of Michigan"
  - "University of Toronto"
  - "Microsoft Research"
conference: osdi-2025
code_url: "https://github.com/OrderLab/T2C"
tags:
  - observability
  - formal-methods
  - fault-tolerance
category: verification-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

T2C turns existing tests into runtime semantic checkers. It slices out semantic assertions, infers the production conditions under which they should fire, and validates the result before deployment. Across four systems, the derived checkers detect most reproduced silent failures with modest overhead.

## Problem

The paper starts from a common distributed-systems failure mode: the system stays up, emits no explicit error, yet violates a user-visible semantic contract. Examples include ephemeral nodes lingering after session expiration, range queries returning incomplete rows, and snapshots changing after creation. These failures are serious, but hard to debug because operators get neither a crash nor a clean exception.

Hand-written production semantic checkers would help, but they do not scale across large feature surfaces. Generic monitors for CPU, timeouts, or exceptions do not help because the failure is semantic, and trace-based invariant miners are too low-level and noisy. The paper's practical observation is that many of these semantics are already encoded in tests, but only for one concrete setup. T2C asks whether those tests can be generalized into production monitors.

## Key Insight

The key claim is that test code already contains the two parts of a semantic checker: an oracle that states what "correct" means, and a workload prefix that indicates when the property should hold. If T2C can separate those pieces, replace concrete examples with symbolic parameters, and keep only the observational logic, then a unit or integration test can become a reusable production checker.

That move avoids both of the obvious alternatives. T2C is not inferring semantics from traces alone, and it is not replaying an entire test in the background. It preserves the human-written oracle from the test, which gives it much stronger meaning than mined event pairs or low-level invariants. The feasibility study supports this: of 210 sampled tests from six systems, 183 use explicit assertions, and about two thirds look generalizable enough for production checking.

## Design

T2C represents a checker as three pieces: a parameterized checker function `C_f`, a symbolic precondition `C_p`, and additional constraints `C_r`. The offline pipeline starts with static analysis. T2C finds assertions, runs backward slicing to collect the instructions needed to compute their inputs, and separates arguments from local temporaries so the result is an executable checker rather than a raw slice. A key refinement is side-effect filtering: purity analysis plus a curated unsafe-operation list exclude writes, deletes, restarts, and similar operations, because the checker should observe production state rather than generate workload.

T2C then derives the trigger condition. It instruments system-side entry points and the assertion itself, executes the original test, and records the system-operation sequence before the assertion fires. Operations used only to compute assertion arguments are removed; the remainder becomes the candidate precondition. T2C symbolizes concrete values, merges repeated values into one symbol, records simple equality, inequality, and containment relations as constraints, and can mutate the precondition with bounded reduce, insert, duplicate, and reorder operations to produce relaxed variants.

Generated checkers must then compile, pass JVM verification, pass self-validation by replacing the source assertion in the original test, and survive cross-validation against other passing tests. That last step filters over-generalized checkers that alarm on unrelated but correct workloads. In production, a verifier stores traces in a circular buffer, indexes preconditions in a trie, and invokes `C_f` only when the current trace suffix satisfies `C_p` and any configuration constraints. The implementation also includes adapters for setup-style test utilities and a cluster mode for multi-node checks.

## Evaluation

The evaluation spans ZooKeeper, Cassandra, HDFS, and HBase. T2C targets the subset of tests that check system semantics with useful assertions, then generates and validates checkers from that pool. The result is 672 verified checkers: 46 for ZooKeeper, 100 for Cassandra, 230 for HDFS, and 296 for HBase. They average 4.3 assertions each and cover request processing, storage behavior, replication, compaction, and snapshot correctness.

The headline result is failure detection. The authors reproduce 20 real-world silent semantic failures and compare T2C against three baselines: in-vivo test execution, state invariants inspired by Dinv, and event rules inspired by Oathkeeper. T2C detects 15 of the 20 failures, while the combined baselines detect 8. Detection is also fast: the median time is 0.188 seconds after the failure manifests. For failures such as HDFS snapshot mutation or Cassandra range-query truncation, the decisive signal is a feature-specific semantic assertion rather than a generic event order or state relation.

Operationally, the results are also solid. Under Jepsen-style failure-free stress runs, false-alarm rates are 1.3% for ZooKeeper, 1.0% for Cassandra, 3.2% for HDFS, and 0.6% for HBase. Runtime throughput overhead averages 4.0% across the four systems, versus 1.8% for event checkers, 2.4% for in-vivo checkers, and more than 50% for state checkers. Memory overhead stays within 6%, and only 56% of T2C's checkers are activated in the authors' workloads, which helps explain the modest runtime cost.

## Novelty & Impact

Relative to _Grant et al. (ICSE '18)_, T2C does not infer generic likely invariants from state traces; it reuses human-written semantic oracles and therefore captures richer properties. Relative to _Lou et al. (OSDI '22)_, it does not require regression tests for known failures, but mines ordinary existing tests for future runtime monitors. Relative to _Liu et al. (NSDI '08)_ and _Huang et al. (OSDI '18)_, it pushes monitoring beyond explicit error indicators into silent semantic violations.

The likely impact is on the boundary between testing and observability. The paper argues that test suites are not only for pre-release bug finding; they are also a source of deployable semantic monitors. The contribution is mainly a new mechanism and workflow rather than a new theory of correctness.

## Limitations

T2C is only as good as the tests it starts from. The paper misses five of the twenty reproduced failures because some violated semantics had no useful tests, some tests lacked meaningful assertions, and some were too tangled to generalize safely. That means T2C amplifies existing test quality rather than replacing it.

There are also technical limits in the generalization logic. Symbolic constraints are inferred with heuristics, so T2C may over-constrain or under-constrain a checker. Precondition mutation is bounded and enumerative rather than semantically principled. Safety is improved by purity analysis and cross-validation, but the authors explicitly say these steps do not fully guarantee side-effect-free checkers. Finally, T2C is a detection system, not an automatic mitigation framework.

## Related Work

- _Grant et al. (ICSE '18)_ — Dinv infers distributed invariants from test traces, while T2C keeps the test's original semantic oracle instead of mining low-level state relations.
- _Lou et al. (OSDI '22)_ — Oathkeeper derives event rules from past failure regressions; T2C starts earlier by mining ordinary tests that predate any concrete incident.
- _Huang et al. (OSDI '18)_ — Panorama improves observability for explicit failures, whereas T2C targets silent semantic violations that do not necessarily emit an error signal.
- _Liu et al. (NSDI '08)_ — D3S provides a model for developers to write runtime checks manually; T2C reduces that manual effort by synthesizing many checks from existing tests.

## My Notes

<!-- empty; left for the human reader -->

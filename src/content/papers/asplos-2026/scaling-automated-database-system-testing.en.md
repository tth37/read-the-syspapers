---
title: "Scaling Automated Database System Testing"
oneline: "Learns which SQL features a DBMS accepts, then reuses generic logic-bug oracles and feature-set deduplication to test many SQL engines with little hand porting."
authors:
  - "Suyang Zhong"
  - "Manuel Rigger"
affiliations:
  - "National University of Singapore, Singapore, Singapore"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790215"
project_url: "https://doi.org/10.5281/zenodo.18289297"
tags:
  - databases
  - fuzzing
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

SQLancer++ learns a target DBMS's SQL dialect online instead of requiring a hand-written generator up front. That lets it reuse generic logic-bug oracles across 18 systems and report 196 previously unknown bugs, 180 fixed.

## Problem

Oracle-based DBMS testing already works, but it does not scale operationally. Tools like SQLancer need per-engine generators for statements, expressions, metadata access, and dialect quirks. The CrateDB case study is the warning sign: reusing SQLancer's PostgreSQL generator still required 1,296 lines of changes, and simply tolerating syntax failures would drive validity below 1%. Even after porting, analysts face a second bottleneck because campaigns can produce hundreds or thousands of bug-triggering cases, many of them duplicates. So the problem is not only finding a good oracle; it is reducing both the per-DBMS engineering cost and the per-bug triage cost enough that many engines can be tested continuously.

## Key Insight

The key idea is to replace manual dialect modeling with online feature learning. SQLancer++ treats keywords, operators, functions, and type expectations as candidate SQL features, generates them speculatively, and uses execution feedback to infer which ones the target DBMS supports. Two complementary moves make that practical: the framework maintains its own schema model instead of querying DBMS-specific metadata interfaces, and it summarizes bug-triggering tests by their enabled feature sets so later failures can be deprioritized as likely duplicates.

## Design

SQLancer++ centers on an adaptive statement generator. The implementation covers six common statements, ten clause/keyword categories, 58 functions, 47 operators, and three base data types, plus abstract properties such as whether the engine behaves more like a dynamically or strictly typed system. For schema-building statements, repeatedly failing features are disabled. For query features, the paper uses a Bayesian success-probability estimate and suppresses features whose posterior mass lies mostly below a user threshold. The generator also starts with shallow expressions and increases depth gradually so unsupported features are identified early.

The second design choice is the internal schema model: successful `CREATE TABLE` and `CREATE VIEW` statements update SQLancer++'s own representation of tables, columns, and types, which it later consults when generating new statements. On top of that, the paper plugs in two DBMS-agnostic logic-bug oracles, TLP and NoREC. When either oracle finds a discrepancy, SQLancer++ stores the feature set used to generate the failing test; if a previous bug's feature set is a subset of the new one, the new case is treated as a likely duplicate and deprioritized.

## Evaluation

The evaluation shows real reach. Across roughly four months of intensive testing on 18 DBMSs, SQLancer++ produced 196 bug reports, including 140 logic bugs, and 180 fixes. That breadth matters because many targets, such as CrateDB, Dolt, RisingWave, Umbra, Virtuoso, and Vitess, were outside SQLancer's original support set. The portability motivation is also empirically justified: in a cross-DBMS feature study, only 8% of bug-inducing tests ran successfully on more than 90% of the 18 systems, and the overall cross-system validity rate was just 48%.

The feedback loop is doing real work. On SQLite, validity rises from 24.9% without feedback to 97.7% with feedback; on PostgreSQL, from 21.6% to 52.4%. SQLancer++ still reaches lower coverage than hand-written SQLancer generators on SQLite, PostgreSQL, and DuckDB, but the tradeoff is not fatal: the paper reports new bugs that SQLancer missed, including 10 in DuckDB and 3 in SQLite. The CrateDB prioritization result is especially persuasive operationally: over 67K bug-inducing cases per hour shrink to 35.8 prioritized cases and 11.4 unique bugs on average.

## Novelty & Impact

Relative to _Rigger and Su (OSDI '20)_, the novelty is not a new oracle but a portability layer for oracle-based DBMS testing. Relative to _Liang et al. (USENIX Security '22)_, SQLancer++ gives up coverage guidance to work across more engines and implementation languages. Its impact is therefore practical: it offers smaller DBMS teams a path to logic-bug testing without first building thousands of lines of dialect-specific generator code.

## Limitations

The scope is still narrow. SQLancer++ focuses on a mostly standardized SQL subset, so unusual DBMS-specific features remain uncovered until someone adds them. Its feature model is also mostly independent; the appendix notes that it does not yet represent richer relationships such as mutual exclusion or prerequisite constraints. The bug prioritizer is heuristic rather than semantic, so it can merge distinct bugs or split one root cause across several feature sets. And despite the paper's portability gains, each new DBMS still needs basic connection and operational hookup, averaging 16 lines of code per system.

## Related Work

- _Rigger and Su (OSDI '20)_ — SQLancer demonstrates that oracle-based DBMS testing can find many logic bugs, while SQLancer++ focuses on removing the per-DBMS generator rewrite that limits SQLancer's reach.
- _Rigger and Su (OOPSLA '20)_ — Ternary Logic Partitioning provides one of the DBMS-agnostic logic-bug oracles that SQLancer++ reuses rather than redesigns.
- _Liang et al. (USENIX Security '22)_ — SQLRight adds coverage-guided logic-bug testing, but it still does not solve the cross-dialect generator portability problem that SQLancer++ targets.
- _Fu et al. (ASE '22)_ — Griffin broadens DBMS fuzzing without grammar engineering, but it is oriented toward crash bugs, whereas SQLancer++ is built around logic-bug detection.

## My Notes

<!-- empty; left for the human reader -->

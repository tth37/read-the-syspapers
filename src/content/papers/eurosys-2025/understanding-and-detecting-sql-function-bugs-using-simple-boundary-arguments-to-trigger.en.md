---
title: "Understanding and Detecting SQL Function Bugs: Using Simple Boundary Arguments to Trigger Hundreds of DBMS Bugs"
oneline: "Soft turns SQL-function testing into boundary-argument synthesis, using bug-derived patterns over literals, casts, and nested functions to expose 132 new DBMS bugs."
authors:
  - "Jingzhou Fu"
  - "Jie Liang"
  - "Zhiyong Wu"
  - "Yanyang Zhao"
  - "Shanshan Li"
  - "Yu Jiang"
affiliations:
  - "KLISS, BNRist, School of Software, Tsinghua University, China"
  - "National University of Defense Technology, China"
conference: eurosys-2025
category: reliability-and-formal-methods
doi_url: "https://doi.org/10.1145/3689031.3696064"
tags:
  - databases
  - fuzzing
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

The paper argues that most crash-inducing built-in SQL function bugs are boundary-argument bugs rather than exotic whole-query corner cases. Soft operationalizes that claim by extracting 10 generation patterns over literal values, type castings, and nested-function results, then uses them to synthesize short SQL statements that found 132 confirmed bugs across seven DBMSs.

## Problem

Built-in SQL functions sit on the hot path of ordinary database use, so bugs in them have both wide blast radius and real security consequences. The paper notes that 31 of PostgreSQL's 121 published CVEs since 2004 came from built-in SQL functions, and that those CVEs have a higher average score than PostgreSQL CVEs overall. If an application exposes regex, JSON, XML, or formatting features to users, a crafted argument may be enough to reach a flawed implementation.

Existing testing methods do not fit this surface well. Traditional library-function testing assumes explicit call sequences over objects and APIs, while SQL functions are nested SQL expressions whose behavior depends on argument formats and implicit casts. General DBMS fuzzers focus on statement structure, optimizer behavior, or logic oracles, not on systematically generating semantically meaningful function arguments at the boundary where implementations are brittle.

## Key Insight

The key claim is that SQL function testing becomes tractable once you model where boundary arguments come from. In the authors' corpus of 318 historical bugs, 87.4% reduce to improper handling of boundary values, and those values arise from only three sources: literal constants, type-casting results, and return values from nested functions. A second observation makes this actionable: 87.5% of bug-inducing statements contain no more than two function expressions.

So the hard part is not generating arbitrarily complex SQL. It is generating arguments that are just valid enough to pass parsing and type checking, yet close enough to format, range, length, or nesting boundaries to trigger latent implementation flaws. Once the problem is reframed that way, pattern-based synthesis becomes more effective than generic random generation.

## Design

The design starts with a manual bug study rather than with a mutator. The authors mined 14,111 candidate reports from PostgreSQL, MySQL, and MariaDB trackers, parsed the PoCs, and narrowed them to 318 built-in SQL function bugs. That study yields the design priors: among bugs with backtraces, 70.0% crash during execution; string and aggregate functions account for over 40% of bug-inducing function occurrences; and 47.5% of bugs require both table creation and inserted data, while 41.5% can be triggered without any table at all.

From there the paper distills ten boundary-value-generation patterns into three families. P1 targets boundary literals such as extreme numbers, empty strings, `NULL`, `*`, and structure-preserving edits for typed strings like JSON, IP addresses, hex strings, and regexes. P2 targets boundary type castings through explicit `CAST`, `UNION`-induced implicit casts, and cross-function argument reuse. P3 targets nested-function results, for example by wrapping arguments with another function or using `REPEAT` to build values with extreme length or recursion depth.

Soft turns those patterns into a testing pipeline. It collects seed function expressions by scanning DBMS documentation and regression tests for real function names and `func(...)` forms, rewrites those expressions using the boundary patterns, substitutes the rewritten expressions back into SQL statements, and executes them via DBMS Python clients. The implementation deliberately stops when an expression already contains more than two functions, matching the empirical finding that most real bugs do not need deeper nesting.

## Evaluation

Soft tests PostgreSQL 16.1, MySQL 8.3.0, MariaDB 11.3.2, ClickHouse 23.6.2.18, MonetDB 11.47.11, DuckDB 0.10.1, and Virtuoso 7.2.12 on a 128-core Ubuntu server using Dockerized instances. Over two weeks it finds 132 previously unknown bugs: 1 in PostgreSQL, 16 in MySQL, 24 in MariaDB, 6 in ClickHouse, 19 in MonetDB, 21 in DuckDB, and 45 in Virtuoso. All 132 were confirmed by vendors, and 97 were fixed by the time of writing.

The coverage comparison explains why. In 24 hours, Soft triggers 2,956 built-in SQL functions across supported targets, versus 74 for Sqirrel, 202 for SQLancer, and 446 for SQLsmith. On the DBMSs each baseline actually supports, that corresponds to +984, +1567, and +181 triggered functions for Soft. Soft also reaches 73,798 branches in built-in SQL function modules and improves branch coverage by 433.93%, 98.70%, and 19.86% over Sqirrel, SQLancer, and SQLsmith, respectively. The paper reruns generated queries to normalize coverage accounting, which makes the comparison more defensible than a raw one-pass count.

The evidence supports the main claim: bug-derived boundary synthesis is a better fit for SQL functions than whole-query fuzzing. The main caveat is that the baselines are general DBMS testing tools rather than SQL-function-specific ones. The paper is also candid about noise: Soft produced seven false positives when generated values simply exceeded resource limits, and it also triggered 14 assertion failures.

## Novelty & Impact

The novelty is the combination of a bug taxonomy and a tool that encodes that taxonomy directly into test generation. Prior DBMS fuzzers mostly search over query structure, mutate existing statements, or rely on logic-testing oracles. Soft instead asks a narrower question: what boundary arguments does a built-in SQL function implementation mishandle, and how can a tester synthesize those arguments systematically?

That framing gives the paper durable impact. It offers DBMS implementers an actionable checklist for hardening function code, gives testers a concrete way to reach deep function logic without generating massive queries, and connects DBMS fuzzing with classic domain testing.

## Limitations

The authors study only crash-style bugs, not correctness bugs where a function silently returns the wrong answer. That keeps the corpus precise, but it means the resulting patterns are tuned to memory safety and robustness failures rather than semantic misbehavior. The study also likely misses the most severe privately handled vulnerabilities, since some vendors route security bugs outside public trackers.

The historical analysis covers only PostgreSQL, MySQL, and MariaDB, even though Soft is later evaluated on seven DBMSs. The implementation cap of two nested functions is empirically motivated rather than principled, so there may be deeper interaction bugs that Soft will never synthesize. Finally, the lack of a function-specialized baseline means the evaluation proves usefulness more clearly than optimality.

## Related Work

- _Zhong et al. (CCS '20)_ - Squirrel preserves SQL validity through IR-based mutation, but it does not make boundary-valued function arguments a first-class generation target.
- _Rigger and Su (OSDI '20)_ - Pivoted Query Synthesis builds logic-testing oracles for DBMS correctness bugs, whereas Soft targets crash and security bugs inside built-in SQL functions.
- _Fu et al. (ASE '22)_ - Griffin broadens DBMS fuzzing beyond hand-written grammars, while Soft narrows the scope to function expressions and gains leverage from a manual bug taxonomy.
- _Fu et al. (ICSE '24)_ - Sedar improves seed quality for DBMS fuzzing, but Soft's main contribution is rewriting function arguments along literal, cast, and nested-function boundary patterns.

## My Notes

<!-- empty; left for the human reader -->

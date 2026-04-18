---
title: "Understanding Query Optimization Bugs in Graph Database Systems"
oneline: "Studies 102 graph-DB query optimizer bugs, distills recurring causes and bug-trigger patterns, and turns those findings into a tester that found 10 new optimization bugs."
authors:
  - "Yuyu Chen"
  - "Zhongxing Yu"
affiliations:
  - "Shandong University, Qingdao, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790244"
tags:
  - databases
  - graph-processing
  - fuzzing
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

This paper treats graph-database query optimization bugs as a first-class systems problem rather than a side effect of generic DBMS complexity. It studies 102 real bugs from Neo4j, Memgraph, RedisGraph, and Kuzu, extracts recurring causes and bug-trigger patterns, then builds a GDSmith-based tester that found 20 unique bugs, including 10 optimization bugs.

## Problem

The paper starts from a mismatch between where graph database systems spend complexity and where current testing tools focus. In Cypher-based GDBMSs, query optimization is central to performance, but the optimizer is exposed to graph-specific semantics such as variable-length traversals, path objects, explicit scope boundaries, and changing graph state as clauses execute. That combination makes the optimizer look less like a simple cost model and more like a compiler pipeline with normalization, plan generation, search, and rule-based rewrites. If compiler optimizers are notoriously bug-prone, the authors argue, graph query optimizers should be expected to fail too.

Existing GDBMS testing tools do find real bugs, but they are mostly general-purpose differential or metamorphic testers. That breadth is useful, yet it can dilute coverage for one bug class. The paper's goal is therefore not to propose another generic oracle, but to answer narrower questions that matter for systems builders: what root causes dominate graph query optimization bugs, what kinds of LPGs and Cypher queries expose them, how do the bugs fail in practice, and can those patterns drive a more effective testing tool?

## Key Insight

The central insight is that graph query optimization bugs are not random. Across 102 bugs, the authors find repeatable structure in both where the bugs come from and what kinds of inputs trigger them. On the cause side, most bugs arise in plan generation and selection, especially from incomplete or incorrect plan spaces, inaccurate cost estimation, and defective search algorithms. On the input side, many bugs do not require elaborate graphs at all: 75% of identifiable bug-exposing LPGs are "simple" by the paper's threshold, and about 37% can be exposed on an empty graph.

The harder part is the query, not the data. Around 32% of bug-exposing queries use subquery clauses, often nested, and 40% exhibit the paper's "Single Clause Multiple Bound Variables Interaction" feature, where one clause combines several previously bound variables. Those patterns stress variable scope, graph state, and clause semantics in ways existing tools often under-generate. Once the authors recognize that structure, they can bias test generation toward the optimizer logic that actually fails in practice instead of sampling the Cypher space uniformly.

## Design

The paper has two layers of design: a manual characteristic study and a testing tool derived from it. For the study, the authors mine issue trackers for four popular Cypher-based systems and keep 102 representative optimization bugs with enough information to analyze. They read issue reports, patches, tests, commit messages, and surrounding code to classify root causes, manifestations, and fixes. The resulting taxonomy tracks the optimizer pipeline. Seventeen bugs arise in optimization and normalization, sixty-nine in plan generation and selection, nine in rule-based plan transformation, and seven have unresolved causes. The largest category is incomplete or incorrect plan space construction with 40 bugs, followed by 14 defective plan-space exploration bugs and 9 inaccurate cost-estimation bugs.

The qualitative examples make the taxonomy concrete. Some bugs come from ignoring legal but uncommon Cypher forms such as zero-argument functions or unusual clause shapes. Others arise because the optimizer mishandles graph state after deletions, misunderstands `OPTIONAL MATCH` or subquery semantics, assigns impossible zero cardinalities, or assumes fixed relations between plan operators that do not always hold. A separate fix study shows that these are not uniformly "deep algorithm bugs": 46 fixes require larger design changes, but about 32% can be repaired by changing simple conditionals, conditions, or parameters/operators.

The tool then encodes the most actionable findings. It reimplements about 10K non-comment lines on top of GDSmith. For graphs, it intentionally keeps LPGs modest because complex graphs are usually unnecessary and make debugging harder. For Cypher generation, it adds full support for four subquery forms, `CALL{}`, `COLLECT{}`, `COUNT{}`, and `EXISTS{}`, and biases production probabilities toward subquery-heavy clause skeletons. It also performs clause-impact analysis so expression generation prefers reusing already bound variables, increasing the chance of triggering cross-scope and data-dependency mistakes. For oracles, the tool concentrates on internal errors, crashes, and wrong results, using returned messages and cross-version result comparison instead of trying to solve general performance-oracle ambiguity.

## Evaluation

The evaluation first shows that the study is grounded in a non-trivial bug set. Across the 102 historical bugs, all four failure modes are common: 24 internal errors, 24 crashes, 23 performance issues, and 15 wrong-result bugs, with 16 more unknown. Fixing these bugs is also error-prone: among 82 bugs where the authors can judge the patching process, 25 had at least one buggy fix, or 30.5%.

The tool evaluation is the more direct systems result. Tested on Neo4j and Memgraph, the tool generated 456.3K and 986.5K inputs respectively, with average query lengths of 23.1 and 22.6 clauses. It found 20 unique bugs in total, 12 in Neo4j and 8 in Memgraph; all were confirmed by developers, 11 were fixed, and 10 were optimization bugs. The feature analysis is especially persuasive: among the 10 minimal bug-exposing optimization queries, 6 use subquery clauses, 4 use Single Clause Multiple Bound Variables Interaction, and every one uses at least one of those two targeted characteristics. That strongly supports the paper's claim that optimizer-specific bug patterns can be operationalized.

Against seven prior GDBMS testing techniques, the new tool does not win every coverage number, but it is competitive and often better where the paper cares most. In 24-hour runs on Neo4j 5.25.1, it reports 5 unique bugs versus at most 1 for the other compared tools, while keeping false reports to 2 out of 79 bug reports. On Memgraph 3.0.0, it reports 3 unique bugs versus at most 2 for baselines. The authors are also candid about residual misses: in a false-negative study over 33 known optimization bugs whose symptoms are detectable by their oracle choices, the tool finds 13 and misses 20, largely because of unsupported syntax, very large LPGs, or insufficient time. So the evaluation supports the paper's main claim that characteristic-guided testing works, but it also shows the tool is still incomplete rather than a universal optimizer-bug detector.

## Novelty & Impact

Relative to _Rigger and Su (ESEC/FSE '20)_, the novelty is not merely "testing optimizer bugs again," but doing the first systematic optimizer-bug study for graph databases, where Cypher scope rules and graph semantics create different failure surfaces from relational engines. Relative to general GDBMS testers, the paper's key move is to specialize around empirically observed optimizer-bug triggers instead of relying on broad query diversity alone.

That makes the paper valuable in two ways. For graph database implementers, it is a bug taxonomy and a debugging checklist for optimizer code. For testing researchers, it is evidence that bug-class-specific empirical studies can lead to better generators and cheaper oracles. The tool itself is useful, but the longer-lived contribution is probably the characterization of where graph optimizer implementations go wrong.

## Limitations

The study's empirical base is still bounded. It only covers four Cypher-based GDBMSs, so the results may not transfer cleanly to engines centered on Gremlin, GQL, or very different storage/execution architectures. The bug corpus also comes from issue trackers, which means the paper can only analyze bugs that were reported and documented clearly enough; seven bugs remain without established causes. I am inferring from the methodology that silent optimizer misbehavior is likely underrepresented, even though the paper does not quantify that gap directly.

The tool is likewise targeted rather than complete. It is evaluated only on Neo4j and Memgraph, not RedisGraph or Kuzu. It intentionally deemphasizes performance-oracle detection, does not yet support some Cypher constructs such as `FOREACH` and query parameters, and misses bugs that require very large LPGs, random functions, or especially complex patterns. Those limitations do not invalidate the paper's contribution, but they narrow the range of bugs the current system can expose.

## Related Work

- _Rigger and Su (ESEC/FSE '20)_ — studies optimization bugs in relational database engines with a non-optimizing reference engine, whereas this paper characterizes graph-database optimizer bugs and uses the findings to guide test generation.
- _Hua et al. (ISSTA '23)_ — GDSmith provides broad differential testing for Cypher engines; this paper builds on it but focuses specifically on optimizer-bug-triggering query features such as nested subqueries and cross-scope variable interactions.
- _Mang et al. (ICSE '24)_ — GRev uses equivalent query rewriting to test GDBMSs in general, while this paper argues that optimizer bugs need more targeted handling of scope, dependencies, and subquery-heavy query shapes.
- _Liu et al. (ISSTA '24)_ — GraspDB adds a graph-state persistence oracle for GDBMS testing, but it is still a general bug-finding technique rather than a characteristic study plus optimizer-specific generator.

## My Notes

<!-- empty; left for the human reader -->

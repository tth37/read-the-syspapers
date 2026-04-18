---
title: "Orq: Complex Analytics on Private Data with Strong Security Guarantees"
oneline: "Orq fuses oblivious joins with decomposable aggregation so MPC can run multi-way analytics without leaking result sizes or materializing quadratic intermediates."
authors:
  - "Eli Baum"
  - "Sam Buxbaum"
  - "Nitin Mathai"
  - "Muhammad Faisal"
  - "Vasiliki Kalavri"
  - "Mayank Varia"
  - "John Liagouris"
affiliations:
  - "Boston University"
  - "UT Austin"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764833"
code_url: "https://github.com/CASP-Systems-BU/orq"
tags:
  - databases
  - security
  - pl-systems
category: storage-and-databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Orq is an MPC query engine for outsourced collaborative analytics that avoids the usual quadratic blowup of oblivious joins. Its key move is to fuse joins with decomposable aggregation, so the system never has to materialize the full Cartesian product even when both inputs contain duplicate keys. With that design plus protocol-agnostic oblivious operators and a vectorized runtime, Orq runs the full TPC-H benchmark under MPC and scales well beyond prior no-leakage systems.

## Problem

The paper targets a painful gap in secure analytics. In outsourced MPC, data owners secret-share tables to a small set of non-colluding servers, and those servers must evaluate queries without learning anything about the data, including intermediate result sizes. That requirement makes relational operators expensive, but joins are the real bottleneck. A fully oblivious join on two tables of size `n` may need to hide the true output by producing a worst-case `n^2` Cartesian product, and multi-way joins compound that blowup across stages.

Prior systems deal with this in unsatisfying ways. Some preserve strong security but accept quadratic joins and expensive bitonic sorting. Others regain speed by leaking join result sizes, offloading work to trusted compute, or assuming a narrow ownership model such as one table per party or a fixed small number of participants. Those assumptions break down in the more general outsourced setting, where many owners may contribute to the same logical table and the computing servers never see plaintext. The paper argues that this is exactly the setting where secure analytics should be most useful, yet it is also where complex join-heavy workloads have looked impractical.

## Key Insight

Orq's central claim is that the hard part is not "joins under MPC" in the abstract, but joins whose intermediate cardinalities are not bounded independently of the data. The authors observe that the multi-way analytics used in prior MPC work and in TPC-H usually end in aggregated answers whose size is worst-case `O(n)` in the input size, even when some joins involve duplicate keys on both sides. If the final aggregation is decomposable and the group-by keys live in one input, the system can partially aggregate before a join, combine partials during the join, and finalize afterward.

That changes the execution strategy from "materialize every match, then aggregate" to "aggregate on the fly while preserving obliviousness." Once the system knows it can keep the working set bounded, it can fuse join and aggregation into one oblivious control flow. This is why Orq avoids both leakage and quadratic intermediates: it is not discovering the true join size and trimming afterward, but restructuring the computation so the worst-case valid output is bounded from the start.

## Design

Orq is built as a full query engine rather than a single cryptographic operator. Users write queries in a dataflow API resembling Spark or Conclave, and Orq compiles the plan into MPC programs over secret-shared tables. Every table carries a secret-shared validity bit per row so operators can pad to worst-case sizes, invalidate rows obliviously, and later mask and shuffle before any output is opened.

The first design pillar is a library of oblivious building blocks. Orq implements filters, deduplication, multiplexing, aggregation, and sorting over tabular data. Its `TableSort` protocol extracts sorting permutations from key columns, composes them right-to-left, and applies the final permutation to the full table only once, avoiding repeated column shuffles. It uses oblivious quicksort for wider keys and radixsort for smaller keys, both adapted to the supported MPC protocols through generalized shuffling primitives.

The core contribution is `Join-Agg`. For a basic one-to-many equality join, Orq concatenates the left and right tables into one working table, adds an origin marker, sorts rows so valid records with the same join key cluster together, marks group boundaries, and then runs an aggregation network. In that network, one internal function copies payload columns from the left row into matching right rows, another propagates validity, and a user-provided aggregation computes per-key results in the same pass. The operator can then trim unnecessary rows and keep the output size bounded by the larger input instead of the hidden join cardinality.

The design generalizes with small control-flow changes. Semi-joins, anti-joins, and outer joins are mostly different ways of invalidating rows. Theta-joins are supported when an equality predicate bounds the output and the remaining conditions can be reduced to oblivious filters. Many-to-many joins are handled by decomposing the aggregation into pre, post, and optional final stages: Orq pre-aggregates multiplicities or partial sums on one side to make join keys unique, runs the basic join, and post-aggregates on the desired output key. Around these operators, the system adds a columnar format, vectorized secure primitives, data-parallel worker threads, and a communication layer that batches network traffic across workers. The same operator library is instantiated atop ABY, Araki et al., and Fantastic Four, so Orq can trade off between semi-honest and malicious security without rewriting the query engine.

## Evaluation

The evaluation is strong because it measures both end-to-end analytics and the lower-level operators that dominate cost. Orq runs on AWS `c7a.16xlarge` instances and evaluates 31 workloads: all 22 TPC-H queries plus nine queries collected from prior relational MPC papers. At TPC-H Scale Factor 1, queries process millions of rows, and the hardest query, Q21, performs up to 12 sorts. Even under malicious security in LAN, Q21 finishes in 42 minutes, while all non-TPC-H prior-work queries complete in under 10 minutes. In WAN, a 75x RTT increase raises times by only 1.2x-6.9x, which supports the paper's claim that vectorization and message batching matter at the system level, not just asymptotically.

The comparison results are more important than the raw times. Against Secrecy, the closest open-source outsourced system without leakage, Orq reports 478x-760x lower latency on expensive join and semi-join queries, 17x-42x on group-by or distinct-heavy queries, and up to 827x overall. Against SecretFlow, which leaks matching rows and can offload work to trusted data owners, Orq still wins by 1.1x-1.5x on join queries and by much larger margins on simpler queries. On oblivious sorting alone, Orq's radixsort is up to 5.5x faster than SecretFlow and up to 189x faster than MP-SPDZ. The scalability section closes the loop: Orq runs the full TPC-H benchmark at SF10 entirely under MPC, and its default quicksort handles 537 million elements in a little over 70 minutes.

## Novelty & Impact

The paper's novelty is not just a faster sort or a cleaner MPC abstraction. It is the combination of a workload observation, a fused join-aggregation mechanism, and a runtime engineered around that mechanism. Prior work often treated leakage, trusted compute, or schema restrictions as the price of scaling relational MPC. Orq shows that a large and practical class of complex queries can stay fully oblivious if the system exploits decomposable aggregation aggressively enough.

That matters to both systems builders and applied cryptography researchers. For practitioners, Orq makes outsourced collaborative analytics plausible for hospitals, companies, or public-sector collaborations that cannot accept intermediate-size leakage. For researchers, it provides a reusable operator design that is protocol-agnostic and open-source, which should make it easier to test new MPC backends or new secure analytics workloads without rebuilding the whole query stack.

## Limitations

Orq is not a universal answer for secure SQL. Its efficient path is restricted to acyclic conjunctive queries, one-to-many joins, or many-to-many joins that are followed by decomposable aggregation with group-by keys contained in one input. Cyclic joins or joins whose aggregation semantics require combining across both tables without decomposition still fall back to an oblivious `O(n^2)` join. That is an honest limitation, but it means the paper's "complex analytics" class is broad rather than complete.

There are also practical constraints. Query text and schema are public and must be agreed upon before execution, so Orq is not hiding workload shape. The current implementation lacks fixed-point arithmetic and substring operations, and users still write queries in Orq's dataflow API rather than through an automatic SQL planner. Finally, the maliciously secure configuration remains expensive at large scale: the paper's WAN SF10 results include Q21 taking 18 hours, and the sorting plus padding costs remain dominant for the hardest workloads.

## Related Work

- _Liagouris et al. (NSDI '23)_ - Secrecy is the closest outsourced relational MPC system with no leakage, but it uses quadratic joins and `O(n log^2 n)` bitonic sort where Orq reduces supported join-aggregation workloads to `O(n log n)`.
- _Fang et al. (VLDB '24)_ - SecretFlow-SCQL scales some private analytics by relying on peer-to-peer execution and leakage of matching rows, whereas Orq targets the outsourced setting and keeps intermediate sizes hidden.
- _Bater et al. (PVLDB '18)_ - Shrinkwrap made the cascading-effect problem explicit and used controlled leakage to tame it; Orq's contribution is showing that many practical workloads can avoid that leakage through fused join and aggregation.
- _Asharov et al. (CCS '23)_ - Secure Statistical Analysis on Multiple Datasets studies secure join and group-by operators, but it is tailored to a narrower outsourced protocol setting and does not provide Orq's end-to-end system treatment of many-to-many analytics.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Weave: Efficient and Expressive Oblivious Analytics at Scale"
oneline: "Weave samples shuffle-key frequencies and injects only enough fake traffic to hide mapper/reducer patterns, keeping oblivious MapReduce within constant-factor overhead."
authors:
  - "Mahdi Soleimani"
  - "Grace Jia"
  - "Anurag Khandelwal"
affiliations:
  - "Yale University"
conference: osdi-2025
code_url: "https://github.com/yale-nova/weave"
tags:
  - security
  - confidential-computing
  - databases
category: verification-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Weave secures MapReduce shuffle by combining random redistribution, histogram estimation, and just-enough fake traffic. It hides split-based and distribution-based leakage with constant-factor overhead instead of the log-linear costs of oblivious sort or oblivious shuffle.

## Problem

Encryption and TEEs do not stop an honest-but-curious cloud from learning from access patterns. In MapReduce, split-based leakage comes from which mappers send data to which reducers, and distribution-based leakage comes from how many records each reducer receives. The paper's medical-record example shows that encrypted shuffle traffic can still reveal which reducer is handling COVID-19 cases.

Prior defenses are expensive or restrictive. Opaque uses oblivious sort, which adds multiple sort rounds and makes non-associative reductions awkward. Shuffle & Balance uses oblivious shuffle and equal-size bins, which is cheaper but still log-linear and does not support sort-based or user-defined partitioning. The authors also prove a hard boundary: if `Map` can emit arbitrarily many outputs per record, no IND-CDJA-secure scheme can keep bounded bandwidth overhead. Weave therefore focuses on the common bounded-expansion case.

## Key Insight

Weave's key claim is that secure analytics does not need exact oblivious permutation of all intermediate records. It only needs observable network and memory traces to be statistically independent of the underlying data distribution under IND-CDJA. That weaker target opens the door to distribution-aware noise injection instead of exact shuffling.

A random first hop makes each downstream worker see an approximate sample of the global key distribution. Workers then share that histogram and inject only enough fake traffic so every reducer receives the same quota. Weave is therefore replacing "hide every record's precise path" with "make all reducer-facing traffic look alike," while keeping the sensitive bookkeeping small enough to fit in enclave-protected memory.

## Design

Weave keeps map and reduce code inside TEEs, but replaces the standard shuffle with random-shuffle, histogram, and balanced-shuffle. In random-shuffle, each mapper sends every intermediate record to a pseudorandomly chosen weaver, breaking the link between input splits and reducer destinations.

In histogram, each weaver counts its received keys, pads the local histogram, and broadcasts it so all weavers reconstruct the same global histogram. Those counters sit in EPC because their access frequencies are data-dependent. For scale, Weave can sample only a fraction of records and cover the estimation error with a small amount of extra noise.

In balanced-shuffle, each reducer is assigned a fixed quota `kv_tot = alpha * n_hat / r`. Weavers greedily place real key groups while keeping all values for a key together, then fill the remaining space with fake records. A shared PRG lets all workers agree on fake-record ownership without extra coordination, and reducers discard fake entries before running `Reduce`.

Two extensions matter. For associative reductions, Weave can split a boundary key across reducers and merge the partials, eliminating fake traffic and allowing `alpha = 1`. For `c > 1` map expansion, it pads each map output to a declared upper bound `C` with filler records. It also supports sort-based or user-defined partitioning by ordering keys accordingly.

## Evaluation

The authors implement Weave as about 1,500 lines of Scala in Apache Spark over Gramine/SGX, and compare against Opaque, Shuffle & Balance, and an insecure TEE baseline on Enron Email, NY Taxi, and Pokec. The workloads span associative aggregation, non-associative analytics, sorting, and iterative graph processing.

The headline result is 4-10x lower end-to-end time than prior secure systems, while staying within 1.65-2.83x of the insecure baseline. Weave is 1.5-2.7x slower than insecure shuffle, versus 3.9-8.3x for Shuffle & Balance and 7.2-20.2x for Opaque. It scales linearly, and even runs over a billion records use less than 5% of total EPC capacity. That is strong evidence that the gain comes from the shuffle design.

## Novelty & Impact

The novelty is the change in abstraction. Rather than demanding exact oblivious rearrangement, Weave formalizes indistinguishable shuffle traces via IND-CDJA and builds a distribution-aware noise-injection pipeline around that target. That yields a genuine secure analytics mechanism, not just another TEE wrapper over Spark.

This matters to confidential analytics and enclave-backed data processing work. The paper also makes the tradeoff explicit: arbitrary MapReduce semantics and bounded secure-shuffle cost are incompatible, so practical systems should optimize bounded-expansion cases.

## Limitations

Weave's main limitation is the bounded-expansion assumption. If `Map` can emit unbounded outputs, the theory says bounded overhead is impossible. Even when `c > 1` is bounded, users must provide `C`, and filler records directly inflate cost.

Performance also depends on skew staying moderate. `alpha` must be large enough that the most popular key fits inside one reducer's quota; very skewed workloads raise fake traffic and erode the constant-factor win. Security still relies on SGX-style EPC protection plus proxy-style defenses against page-fault, interrupt, and cache attacks, while variable-length and timing channels are explicitly out of scope. The design also assumes batch shuffle rather than streaming micro-batches.

## Related Work

- _Ohrimenko et al. (CCS '15)_ - Shuffle & Balance also targets leakage in secure MapReduce, but it depends on oblivious shuffle and equal-size reducer bins, so it retains log-linear shuffle overhead and narrower partitioning flexibility.
- _Zheng et al. (NSDI '17)_ - Opaque hides access patterns with oblivious sort inside secure data analytics, but its sort-heavy execution path is slower and fits associative reductions better than general reduce semantics.
- _Grubbs et al. (USENIX Security '20)_ - Pancake uses frequency-smoothing noise injection for encrypted storage systems; Weave adapts the same high-level idea to mapper/reducer traffic rather than client-to-store accesses.
- _Vuppalapati et al. (OSDI '22)_ - SHORTSTACK studies distributed oblivious data access under faults, whereas Weave specializes in all-to-all analytics shuffle and exploits MapReduce structure to keep overhead low.

## My Notes

<!-- empty; left for the human reader -->

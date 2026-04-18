---
title: "CacheMind: From Miss Rates to Why — Natural-Language, Trace-Grounded Reasoning for Cache Replacement"
oneline: "Turns cache-trace analysis into a trace-grounded assistant that retrieves exact PC/address slices and explains why replacement policies behave differently."
authors:
  - "Kaushal Mhapsekar"
  - "Azam Ghanbari"
  - "Bita Aslrousta"
  - "Samira Mirbagher-Ajorpaz"
affiliations:
  - "North Carolina State University, Electrical and Computer Engineering, Raleigh, North Carolina, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790136"
code_url: "https://github.com/kaushal1803/cachemind"
tags:
  - caching
  - hardware
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CacheMind argues that cache analysis should not stop at miss rates. It builds a retrieval-augmented assistant over ChampSim and gem5 traces so an architect can ask natural-language questions about a specific PC, address, workload, or policy and get a trace-grounded explanation back. The payoff is not a new online replacement policy, but a new analysis workflow that makes policy debugging and insight extraction far more interactive.

## Problem

The paper starts from a familiar gap in cache-replacement research. The field has many increasingly sophisticated policies, from RRIP and SHiP to Hawkeye, Glider, and PARROT, yet the way architects inspect their behavior is still mostly manual. ChampSim and gem5 can report aggregate statistics, but answering a concrete "why" question still means digging through millions of trace entries offline: which PC missed, which line got evicted, what its reuse distance was, and whether another policy would have made a different decision. That is slow, brittle, and poorly suited to comparing learned policies whose behavior is already hard to interpret.

The paper also argues that there is no accepted benchmark for trace-grounded reasoning in this domain. Existing LLM reasoning suites test generic math or commonsense, while cache-policy papers evaluate hit rate or IPC rather than whether a system can correctly answer per-PC, per-address, cross-policy questions. Without a verified benchmark, it is hard to tell whether a language-model assistant is actually reasoning from the trace or simply sounding plausible. So the systems problem here is twofold: make cache traces queryable at the level architects actually care about, and make that capability measurable.

## Key Insight

The central claim is that useful cache-analysis questions become tractable once retrieval precision is treated as the first-class systems problem. A language model does not need the whole trace in its context window; it needs the exact slice relevant to the question, plus enough policy and code context to explain what happened. If the system can reliably narrow "why is PC X bad under policy Y on workload Z?" to a small, verifiable evidence bundle, then the LLM can be used for synthesis instead of guesswork.

That leads to a deliberate split between retrieval and explanation. CacheMind uses one retriever, Sieve, for high-precision symbolic filtering over workload, policy, PC, and address, and a second retriever, Ranger, for open-ended cases where fixed templates are too rigid. The paper's deeper point is that "reasoning over traces" is mostly a data-access problem before it becomes a language-model problem. The experiments support that framing strongly: better retrieval quality changes outcomes more than prompt tricks or fine-tuning.

## Design

CacheMind is organized around an external trace database plus a generator LLM. The database stores per-access records keyed by workload and policy, along with metadata such as miss rates, reuse distances, recency, evicted addresses, assembly context, and short source snippets mapped from PCs. In the paper's main setup, the traces come from ChampSim runs over `astar`, `lbm`, and `mcf`, using Belady, LRU, PARROT, and an MLP policy; the authors also describe a gem5-based variant for richer software-intervention use cases.

Sieve is the structured path. It first identifies the workload and policy named in the query, then applies symbolic PC and address filters, computes helper statistics for the filtered slice, and hands a compact response template to the generator. This path is designed for exact questions such as hit/miss classification, per-PC miss rate, or filtered counting. Ranger is the flexible path. Instead of matching against predefined templates, it gives an LLM the database schema and asks it to generate executable Python that extracts the needed evidence. That lets CacheMind handle more compositional queries, such as ranking hot sets or explaining why one policy beats another for a specific PC.

The paper also adds a conversational memory layer so prior results can be reused across turns. That matters because the authors want CacheMind to function like a "microarchitectural microscope": an architect can ask follow-up questions, refine the slice, and move from a miss-rate report to a causal explanation or a design suggestion. This is a sensible architecture for the stated goal. Importantly, the paper keeps the generator downstream of retrieved evidence rather than letting it act as an unconstrained oracle.

## Evaluation

The evaluation has two parts: a benchmark and several end-to-end use cases. CacheMindBench contains `100` verified questions. The first tier has `75` trace-grounded questions covering hit/miss checks, miss-rate queries, policy comparisons, counting, arithmetic, and trick questions. The second tier has `25` architectural reasoning questions covering microarchitecture concepts, code generation, policy analysis, workload analysis, and semantic analysis. Trace-grounded items are scored by exact match; reasoning items use a `0-5` rubric.

The retrieval story is the strongest part of the paper. On ten evaluation queries, LlamaIndex retrieves correct context only `10%` of the time, while Sieve reaches `60%` and Ranger reaches `90%`. On the full trace-grounded tier, the abstract reports `66.67%` accuracy with Sieve and `89.33%` with Ranger; Ranger also reaches `100%` accuracy on four of the six trace-grounded categories. That convincingly supports the paper's main design decision: generic embedding-based RAG is a poor fit for bit-level trace records, and explicit structured retrieval matters.

The reasoning results are more mixed, which the paper mostly acknowledges. GPT-4o paired with CacheMind obtains the best weighted total score at `74.9%`; o3 reaches `64.8%`, and fine-tuned GPT-4o-mini does not beat the untuned version. Some categories remain weak: all models score `0/5` on the Count category, arithmetic is low, and semantic analysis is still the hardest open-ended tier. That means CacheMind is already useful for targeted trace interrogation, but not yet a reliable universal analyst. The actionable demos are nevertheless interesting: using CacheMind-derived bypass candidates improves hit rate by `7.66%` and IPC by `2.04%` on one mcf case, stable-PC training gives `0.7%` speedup for Mockingjay on milc, and a software-prefetch intervention yields `76%` speedup on a microbenchmark.

## Novelty & Impact

Relative to _Jain and Lin (ISCA '16)_, _Shi et al. (MICRO '19)_, and _Liu et al. (ICML '20)_, CacheMind is not another replacement policy that tries to approximate Belady online. Its contribution is orthogonal: it makes those policies inspectable by turning traces into queryable evidence and explanations. Relative to generic RAG tooling, its novelty is pairing cache-specific symbolic filtering with an agentic retriever that can generate database queries instead of relying only on embeddings.

That makes the paper most relevant to two groups. The first is architecture researchers who design or debug cache policies and want something more interactive than aggregate trace reports. The second is simulator and tooling builders who may take seriously the paper's broader claim that next-generation simulators should answer arbitrary per-event questions, not just dump summary metrics. If the idea sticks, the influence will likely be on tooling and methodology more than on a new deployed cache mechanism.

## Limitations

The paper's scope is narrower than its framing. CacheMindBench covers only three SPEC CPU2006-derived workloads and four replacement policies, so it is not yet evidence that the approach generalizes to modern warehouse-scale or heterogeneous memory behavior. The reasoning tier is also author-constructed and rubric-graded, which is useful for progress tracking but leaves room for subjectivity.

There are also system-level limits. CacheMind depends on a curated external database with source and assembly annotations, so the setup cost is real. Ranger is more accurate than Sieve, but it also relies on an LLM generating executable retrieval code, which may complicate portability and trust in other environments. Finally, the most compelling practical wins come from a few case studies rather than a large deployment, so the paper demonstrates plausible utility more than broad operational maturity.

## Related Work

- _Jaleel et al. (ISCA '10)_ — RRIP is a classic lightweight replacement policy; CacheMind does not replace such heuristics, but helps explain where they fail on specific PCs and addresses.
- _Jain and Lin (ISCA '16)_ — Hawkeye learns from Belady-guided labels to improve online replacement, while CacheMind analyzes and explains policy behavior offline from traces.
- _Shi et al. (MICRO '19)_ — Glider uses deep learning plus distillation to build a deployable policy; CacheMind is complementary infrastructure for understanding those learned decisions.
- _Liu et al. (ICML '20)_ — PARROT imitates Belady with a PC-centric learner, and CacheMind explicitly uses PARROT traces to show where PC-local heuristics diverge from global optimality.

## My Notes

<!-- empty; left for the human reader -->

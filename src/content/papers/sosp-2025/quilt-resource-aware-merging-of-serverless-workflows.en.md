---
title: "Quilt: Resource-aware Merging of Serverless Workflows"
oneline: "Quilt profiles workflows and resource limits, then merges only the profitable serverless subgraphs into one LLVM-level process, replacing remote invokes with local calls."
authors:
  - "Yuxuan Zhang"
  - "Sebastian Angel"
affiliations:
  - "University of Pennsylvania"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764830"
code_url: "https://github.com/eniac/quilt"
tags:
  - serverless
  - scheduling
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Quilt is a background optimizer for serverless workflows that merges only those functions whose joint CPU and memory demand still fits the provider's container limits. It profiles call graphs and resource use, chooses merge groups with a resource-constrained graph-clustering algorithm, and then rewrites inter-function RPCs into direct calls by compiling functions to LLVM IR. Across DeathStarBench workflows, it cuts median completion time by 45.63%-70.95% and improves throughput by 2.05x-12.87x.

## Problem

The paper targets a familiar serverless pain point: workflows are decomposed into many functions for modularity, language choice, and independent deployment, but every internal function call is still a network RPC that traverses an API gateway, a controller, and often a cold start path. For short functions, the orchestration overhead can dominate the useful work. Warm invocations still cost milliseconds, while many serverless functions themselves run for only tens of milliseconds.

Prior fusion systems show that colocating or merging functions can help, but the paper argues that naive "merge everything" is wrong for two reasons. First, a merged workflow can become too large for the provider's CPU and memory limits, causing fragmentation, throttling, or OOM kills. Second, prior systems often assume one interpreted language and source-level rewriting, whereas modern serverless workloads increasingly use compiled languages such as Rust, C++, Swift, and Go. Quilt therefore asks whether a platform can keep serverless's scheduling flexibility while recovering monolith-like performance, without requiring developers to rewrite code.

## Key Insight

Quilt's central claim is that workflow fusion should be treated as a constrained optimization problem rather than a blanket transformation. The right unit is not "the whole workflow" but "the largest subgraph whose calls are frequent enough to matter and whose aggregate resource demand still fits one container." If the platform can infer call frequencies, CPU use, and peak memory, it can internalize only the expensive edges and leave bursty or resource-heavy fan-out remote.

This becomes practical because serverless functions already communicate through narrow interfaces: string payloads over HTTP. Quilt exploits that simplification twice. At decision time, it can model a workflow as a rooted DAG with weighted edges and profiled node costs. At merge time, it only needs to bridge string representations across languages, which makes LLVM-level cross-language fusion feasible without understanding arbitrary application types.

## Design

Quilt runs as an opt-in background service. Developers still upload ordinary functions, and Quilt transparently swaps a workflow entry point with a merged binary once it has enough profile data. Isolation is preserved across tenants and workflows, but not between functions inside the same merged workflow; the paper explicitly treats them more like linked library code than isolated microservices.

Profiling is lightweight and transparent. Quilt inserts an nginx ingress in front of the API gateway, enables OpenTelemetry tracing to observe caller-callee pairs, and uses cAdvisor plus InfluxDB to collect average CPU and peak memory per function. From that it builds a rooted call DAG whose edges are weighted by invocation frequency and normalized into per-workflow call counts. The optimization problem allows overlapping subgraphs, because a callee may need to appear under multiple roots. Each candidate merged subgraph must remain a connected rooted DAG, and its estimated CPU and memory use must stay under platform limits. The objective is to minimize cross-subgraph edge weight, i.e. the number of remaining remote calls.

For small graphs, Quilt enumerates candidate root sets and solves an ILP to find the optimal assignment. For larger graphs, it uses the Downstream Impact Heuristic, which ranks candidate roots not just by local edge weight but by how much downstream CPU and memory pressure they carry. That heuristic is the key systems insight in the planner: it prefers splitting off resource-heavy subtrees before they force bad global packings.

Once a grouping is chosen, Quilt compiles functions to LLVM IR, renames conflicting symbols, links caller and callee modules, and rewrites `sync_inv`/`async_inv` sites into local calls. Same-language merges are straightforward; cross-language merges use small shims that translate each language's string type through `char *`, exploiting the fact that the serverless ABI is effectively string-in/string-out. Quilt then reruns optimization passes, deduplicates libraries, delays libcurl initialization so merged code does not pay HTTP startup cost unless it actually makes a remaining remote call, and merges subgraphs in BFS order until one binary is produced.

## Evaluation

The evaluation uses a six-machine cluster and focuses on Fission plus Rust to keep the platform variables under control. Workloads come from three DeathStarBench applications: Social Network, Hotel Reservation, and Movie Review. The main baselines are the status quo where each function stays in its own container, and a container-merge baseline that places all workflow functions in one container behind an internal API gateway but still keeps them as separate processes.

For latency, Quilt merges the evaluated workflows under profiled resource limits and compares them to the same total container budget as the baseline. It reduces median latency by 45.63%-70.95% and tail latency by 15.64%-85.47% on 9 of 11 workflows; the two exceptions are Hotel Reservation paths that already spend seconds inside the functions, so invocation overhead is not the bottleneck. The result matches the paper's thesis: Quilt matters most when workflows are built from short-lived functions.

For throughput, Quilt outperforms both baselines because it removes RPC work and shares CPU/memory more efficiently. On the `compose-post` workflow, Quilt reports 65.74% lower latency and 11.24x higher throughput than the baseline for synchronous calls, and 51.0% lower latency plus 12.87x higher throughput for asynchronous calls. The container-merge baseline lowers latency somewhat, but it can still run into memory blowups because Fission may schedule multiple instances of the whole workflow into one container. Quilt avoids that by producing a smaller merged binary and eliminating per-process duplication.

The paper also shows why resource-aware splitting matters. In a modified `nearby-cinema` workflow designed to stress CPU limits, merging everything into one binary improves latency but makes throughput 11.64% worse than baseline because the merged container is throttled. Splitting into two merged binaries according to Quilt's optimizer instead yields 50.75% higher throughput. On the planning side, the Downstream Impact Heuristic finds solutions with an optimality gap of 0.0394 at 25 nodes and takes under 0.27 s up to 200-node random graphs, while compilation and linking dominate end-to-end merge time at roughly 1.5 minutes. Conditional local-vs-remote invocation also prevents crashes when profile-based fan-out estimates are too low.

## Novelty & Impact

Quilt's novelty is the combination of three ideas that earlier serverless fusion papers usually separate: transparent deployment on unmodified platforms, cross-language fusion at LLVM IR, and a formal resource-aware merge planner that explicitly reasons about CPU and memory limits. The mechanism is not just "make calls cheaper"; it is "decide which calls are worth internalizing under realistic provider constraints."

That makes the paper useful to both serverless researchers and platform builders. Researchers can treat it as evidence that workflow structure should remain visible to the runtime, while providers can read it as a practical recipe for recovering much of monolithic performance without giving up the existing scheduler. The paper also broadens the fusion conversation beyond Python-style source rewriting by showing that compiled-language workflows can be merged in one address space with relatively little developer involvement.

## Limitations

The paper is candid about several limitations. Quilt only helps when functions call each other directly; interactions routed through external systems such as SQS stay outside its optimization scope. Function-level isolation is weakened inside a merged workflow, so security-sensitive functions should opt out or require extra sandboxing. Failures also become coarser grained: if one function crashes inside a merged process, the whole merged workflow instance can fail.

There are also evaluation and deployment caveats. The cross-language implementation is demonstrated on five languages, but the paper does not explore stranger runtimes or GC interactions in depth. Merge time is nontrivial, with compilation and linking taking about a minute and a half. Finally, much of the evidence comes from benchmark workflows and synthetic graph experiments rather than a production multi-tenant serverless fleet, so questions about long-term workload drift, fairness, and rollback policy are only partially answered.

## Related Work

- _Jia and Witchel (ASPLOS '21)_ - Nightcore colocates related functions in one worker and replaces remote communication with local channels, but it is not transparent to existing platforms and does not solve Quilt's cross-language merge problem.
- _Mahgoub et al. (ATC '21)_ - SONIC optimizes data passing among chained serverless functions in the same VM, whereas Quilt fuses code into one process and makes the merge decision subject to explicit CPU and memory limits.
- _Kotni et al. (ATC '21)_ - Faastlane accelerates FaaS workflows by fusing same-language functions with additional isolation machinery; Quilt instead targets transparent LLVM-level fusion across compiled languages.
- _Mahgoub et al. (POMACS '22)_ - WiseFuse characterizes workloads and transforms workflow DAGs, but Quilt contributes a richer resource-aware clustering model and a concrete cross-language compilation pipeline.

## My Notes

<!-- empty; left for the human reader -->

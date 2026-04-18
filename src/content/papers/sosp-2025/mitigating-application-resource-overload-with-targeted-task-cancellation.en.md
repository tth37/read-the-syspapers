---
title: "Mitigating Application Resource Overload with Targeted Task Cancellation"
oneline: "Atropos traces per-task use of internal application resources and cancels the request causing overload, preserving SLOs with near-zero request loss."
authors:
  - "Yigong Hu"
  - "Zeyin Zhang"
  - "Yicheng Liu"
  - "Yile Gu"
  - "Shuangyu Lei"
  - "Baris Kasikci"
  - "Peng Huang"
affiliations:
  - "Boston University"
  - "Johns Hopkins University"
  - "University of Michigan"
  - "University of California, Los Angeles"
  - "University of Washington"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764835"
code_url: "https://github.com/OrderLab/Atropos"
tags:
  - scheduling
  - datacenter
  - observability
category: datacenter-scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Atropos treats overload control as a targeted cancellation problem: once an admitted request starts monopolizing an internal application resource, the system should cancel that culprit instead of dropping innocent requests at the front door. Across six applications and 16 reproduced overload cases, the paper reports 96% of baseline throughput, 1.16x normalized p99 latency, and under 0.01% request drop.

## Problem

The paper studies overload on application-defined resources such as table locks, buffer pools, and internal queues. These bottlenecks are invisible to simple CPU or NIC counters, and requests stress them very unevenly. A small number of pathological requests can therefore collapse performance even when global system load does not obviously identify the culprit.

The MySQL examples show why existing approaches fail. In the buffer-pool case, adding dump queries at only 0.001% or 0.01% of requests cuts maximum throughput from about 25 KQPS to 18 KQPS and 12 KQPS because those queries monopolize cache space and induce thrashing. In the table-lock case, one backup query interacting with long scans drives throughput down to about 11 KQPS, while removing either party restores it to about 25 KQPS. Admission control sees only global delay and drops many victim requests; isolation frameworks can repartition resources but cannot remove the request already holding the contended resource.

## Key Insight

The core proposition is that this kind of overload should be handled after admission, not before. Once requests start running, the system can observe which task is actually monopolizing the resource and cancel that culprit instead of throttling unrelated arrivals.

This is feasible because many applications already have safe, application-specific cancellation logic. The authors' survey of 151 open-source systems finds that 76% support task cancellation, and 95% of those expose an initiator that can trigger it. Atropos therefore reuses existing cancellation hooks rather than inventing a generic kill mechanism.

## Design

Atropos is built around two abstractions. Developers wrap requests or background jobs as cancellable tasks with `createCancel` and `freeCancel`, and register the application's own cancellation initiator with `setCancelAction`. Separately, Atropos models internal bottlenecks as application resources and traces three events: acquire, release, and wait. The implementation covers synchronization resources, queues, and memory-like resources such as buffer pools and caches.

The runtime manager attributes those events to the current task. Detection is conservative: Atropos first notices latency rising past the SLO while throughput stays flat, then checks whether a particular application resource is responsible. The estimator computes a contention level for each resource and a resource gain for each task. Contention is derived from wait-versus-use time for locks and queues, and from eviction behavior for memory pools. Resource gain estimates how much future pain disappears if a task is canceled. For locks and memory, Atropos multiplies current usage by remaining task progress, so a nearly finished request is less likely to be chosen just because it currently holds a lot.

The policy is multi-objective rather than greedy. Atropos normalizes contention as a fraction of execution time lost, finds tasks that are not dominated across resources, and then scores them by weighting each resource gain with that resource's contention level. The chosen cancellation is therefore the one expected to buy the largest combined improvement when several resources are overloaded together. To mitigate starvation, each canceled request is retried once after resources recover and is then marked non-cancellable.

## Evaluation

The evaluation integrates Atropos into MySQL, PostgreSQL, Apache, Elasticsearch, Solr, and etcd across C/C++, Java, and Go, and reproduces 16 real overload bugs taken from bug trackers and community reports. The cases cover lock contention, thread-pool limits, memory pressure, CPU contention, and I/O contention. Added code is small, from 22 lines for etcd to 74 for MySQL, though the paper is clear that identifying the right resources still required days of manual work.

The main results are strong. Relative to non-overloaded baselines, Atropos preserves 96% throughput on average and keeps normalized p99 latency at 1.16. It substantially outperforms Protego, pBox, DARC, and PARTIES, whose average normalized throughputs are 50.7%, 53.9%, 36.3%, and 37.8%. The advantage comes from selectivity: Atropos drops fewer than 0.01% of requests on average, while Protego, which drops victims rather than culprits, drops about 25%.

The SLO and overhead results are also persuasive. With a 20% latency-growth SLO, Atropos succeeds in 14 of 16 cases and keeps the average latency increase to 10.2%; the two misses involve workloads with many noisy tasks where several cancellations are needed before recovery. Runtime overhead is low under normal load, reducing throughput by only 0.59% on average, and rises to 7.09% under overload when Atropos switches to finer-grained tracing.

## Novelty & Impact

This is a mechanism paper, not just a better threshold. Its novelty is to make targeted cancellation the actuation point for overload control, then provide the machinery needed to do that safely and generally: task boundaries, resource-agnostic tracing hooks, future-gain estimation, and a multi-resource policy. That should matter to overload-control and SLO-aware serving work, because it shows that admission control is the wrong lever when the real bottleneck lives inside application logic.

## Limitations

Atropos depends heavily on application cooperation. Developers must identify internal resources, place tracing hooks, expose progress signals, and already have or add safe cancellation points. The gain model is also heuristic: future demand is approximated from remaining progress, which is sensible for long monopolizing requests but can still mis-rank candidates. The system is evaluated only as a single-node framework, leaving distributed cancellation and partition handling to future work. Finally, not every application has clean task-level cancellation; Apache needed a `pthread_cancel` fallback for PHP scripts, which highlights that safety ultimately depends on the application's own semantics.

## Related Work

- _Cho et al. (OSDI '20)_ - Breakwater adapts admission using queueing-delay signals, whereas Atropos waits until requests execute and then cancels the task actually causing internal resource contention.
- _Cho et al. (NSDI '23)_ - Protego handles unpredictable lock contention by dropping requests nearing SLO violation; Atropos instead tries to identify and cancel the lock holder or other culprit task and generalizes beyond locks.
- _Hu et al. (SOSP '23)_ - pBox pushes performance isolation into applications via request-aware resource control, while Atropos argues that isolation alone is insufficient once a harmful request is already running.
- _Banga et al. (OSDI '99)_ - Resource Containers partition server resources for isolation, whereas Atropos argues that partitioning is too blunt for highly variable request behavior and overloads centered on application-defined resources.

## My Notes

<!-- empty; left for the human reader -->

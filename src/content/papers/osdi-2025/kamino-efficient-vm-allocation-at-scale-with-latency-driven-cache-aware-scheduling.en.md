---
title: "Kamino: Efficient VM Allocation at Scale with Latency-Driven Cache-Aware Scheduling"
oneline: "Kamino estimates queueing and hierarchical-cache effects together, then routes each VM request to the allocator agent with the lowest predicted end-to-end latency."
authors:
  - "David Domingo"
  - "Hugo Barbalho"
  - "Marco Molinaro"
  - "Kuan Liu"
  - "Abhisek Pan"
  - "David Dion"
  - "Thomas Moscibroda"
  - "Sudarsun Kannan"
  - "Ishai Menache"
affiliations:
  - "Rutgers University"
  - "Microsoft Research"
  - "Microsoft Azure"
conference: osdi-2025
tags:
  - scheduling
  - virtualization
  - datacenter
  - caching
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Kamino is a VM-request scheduler for allocator agents that explicitly predicts end-to-end latency, not just load or cache hit rate. Its LatCache policy combines queueing delay, remaining service time, and a hierarchical cache model, then sends each request to the agent whose predicted completion time is smallest. In Azure production zones, that reduces cache misses by 33% and cuts average allocator latency by 21.1%.

## Problem

Large clouds need VM allocation to be both fast and high quality: requests should finish within tens of milliseconds, but the allocator must still consider many placement constraints and preferences across inventories with hundreds of thousands of servers. That makes request processing expensive, especially when request bursts arrive. Providers therefore parallelize allocation with multiple allocation agents (AAs) and rely on in-memory caches to reuse prior rule evaluations.

The paper argues that current systems do not coordinate these two mechanisms well. A cache-oblivious scheduler such as round-robin, random assignment, or a shared FIFO queue may send a request to an idle AA even when another AA already has the relevant request type or sub-rules cached. In VM allocation, that mistake is expensive because cache entries are large, hits and misses have very different costs, and the cache itself is hierarchical: a request may be a top-level hit, a partial lower-level hit, or a full miss. Simple request pinning is not enough either, because popular request types can create hotspots and long queues. The scheduling problem is therefore to trade off locality against queueing delay under changing load, without shared caches and without expensive coordination across AAs.

## Key Insight

The core claim is that AA assignment should optimize predicted request latency directly, with cache locality treated as one input into that prediction rather than as the objective by itself. A scheduler should prefer the AA whose request will finish first after accounting for three pieces of state: the remaining time of the request currently executing on that AA, the time consumed by requests already queued there, and the processing time the new request is likely to incur once it reaches service, given the cache contents it will probably see at that future moment.

This framing lets Kamino avoid the failure modes of both naive load balancing and naive cache affinity. If one AA has the right cached objects but a long queue, LatCache can still route elsewhere. If another AA is lightly loaded but would suffer a miss, LatCache can keep locality. The paper's theorem shows that with perfect latency estimates, LatCache keeps AA queue waiting times tightly balanced, within one maximum processing time of each other, while its cache-aware estimates still encourage co-location of similar requests.

## Design

Kamino runs inside each allocator node and leaves the actual placement logic of the underlying allocator unchanged. The architectural change is that each AA now owns a private FIFO queue, and an agent selector decides where every incoming request goes. A request classifier first computes an equivalence-class key from the request traits relevant to the allocation rules. That key identifies whether the request, or part of it, already exists in an AA's cache.

LatCache then estimates the request's latency on each AA as the sum of three terms: `processingTime`, `queueTime`, and `remainingProcTime`. The first term predicts how long the request itself will take once it begins service. The second aggregates the predicted service times of the requests already queued at that AA. The third estimates how much work is left in the request currently being executed, if the AA is busy.

The nontrivial part is `processingTime`, because VM allocation caches are hierarchical. The top-level cache stores a consolidated candidate-machine list for an entire request type. The lower-level cache stores individual rule evaluations that can be reused across related request types. On a top-level hit, processing mainly updates cached state incrementally. On a top-level miss, Kamino checks whether the needed rules are already present in the lower-level cache; if so, it charges rule-hit cost for those rules and rule-miss cost for the rest. To estimate what will be in cache when the request eventually starts, LatCache uses an "augmented cache state": it assumes the AA will still retain its current cached objects and will also contain the queued requests' objects by the time the new request reaches service. The paper says this optimistic prediction is accurate in practice because the number of distinct queued request types is small relative to cache capacity.

Kamino's implementation is intentionally lightweight. The request classifier and agent selector stay on the critical path, while a latency estimator runs in the background and continuously updates hit and miss time estimates from observed history. The selector also keeps per-AA metadata, including whether the AA is busy and a map from request-type key to queue count, so it can cheaply test whether a request type is already cached or queued. Scheduling overhead is reported in microseconds per request, far below the tens-to-hundreds of milliseconds spent inside allocation itself.

## Evaluation

The evaluation is unusually strong because it includes both a high-fidelity simulator and a production rollout. The simulator uses six real 24-hour traces from high-traffic allocator nodes across multiple zones, with 500 to 1.7k unique request types per trace. The production study measures five representative Azure zones over 15 days before and after deployment.

Against Protean's shared-queue scheduler, Random, Round-Robin, and a cache-aware consistent-hashing-plus-work-stealing baseline, LatCache delivers the best latency results. In simulation, both `LatCache-request` and the fuller `LatCache-rule` beat all baselines, with more than 50% tail-latency improvement over Protean and up to 2x throughput during bursts. Table 3 shows why: Protean, Random, and Round-Robin sit around 81% top-level hit rate, Hash+WS reaches 87.4%, `LatCache-request` reaches 93.1%, and `LatCache-rule` reaches 95.0%. The same table reports normalized cache memory use dropping from 1.00 for Protean to 0.77 for `LatCache-rule`.

The paper also checks whether the latency model is actually good enough to drive decisions. Its optimistic hit/miss-event prediction over the two cache levels is 99.1% accurate. Even though hit and miss time estimates themselves have 29% average error, `LatCache-rule` still picks the true best AA for 91.9% of requests, and when it misses, the chosen AA is only 2.3% worse in total latency on average. A naive variant that ignores lower-level cache state, future hit prediction, and remaining processing time picks the best AA only 65.4% of the time.

The production rollout uses the simpler `LatCache-request` variant for easier integration. Even so, average allocator latency falls from 185.6 ms to 146.3 ms, a 21.1% reduction, while p90 latency drops from 378.8 ms to 333.5 ms, an 11.9% reduction. Across the five zones, cache hit rate rises from 80% to 86.6% on average, which the authors translate into a 33% reduction in cache misses. They also report 17% lower memory use and 18.6% lower CPU use per allocator node.

## Novelty & Impact

Compared with _Hadary et al. (OSDI '20)_, which introduced Protean, Kamino changes the part Protean leaves simple: the intra-node assignment of requests to private-cache allocator agents. Compared with generic cluster managers such as _Schwarzkopf et al. (EuroSys '13)_ and _Tang et al. (OSDI '20)_, it is narrower in scope but deeper about one systems bottleneck, namely the interaction between VM-allocation latency, queueing, and hierarchical caching. Compared with cache-affinity approaches such as consistent hashing plus work stealing, it argues that hit rate is only a proxy and can be misleading when queue buildup dominates.

That matters because allocator control planes live on ring-fenced machines that already host many other control-plane services. A scheduler that improves latency while simultaneously reducing cache memory and CPU cost is not just a polish improvement; it expands how many AAs a node can host and reduces contention and retries in the placement system. The paper's more general contribution is the idea that cache-aware scheduling in systems with variable hit and miss costs should optimize predicted completion time, not cache affinity in isolation.

## Limitations

Kamino's strongest results depend on a fairly specific workload and architecture model. The design assumes multiple private-cache AAs per node, FIFO queues, no preemption, and immediate irreversible assignment once a request enters an AA queue. If the allocator architecture changes to use shared caches, different queue disciplines, or cross-node coordination at assignment time, the analysis does not directly carry over.

The evaluation is also bounded by the authors' environment. The simulator is driven by real traces, but it omits some production effects such as conflicts and retries from multiple AAs choosing the same machine; the paper explicitly cites those as a reason why production gains are smaller than simulated ones. The field deployment validates only `LatCache-request`, not the more aggressive rule-aware variant that produces the best simulation numbers. Finally, the paper argues the approach could generalize to LSM trees, CDNs, and microservices, but the evidence there is only a small appendix prototype rather than a full systems study.

## Related Work

- _Hadary et al. (OSDI '20)_ - Protean already uses hierarchical caching for VM allocation, but its shared-queue pull model is cache-oblivious at AA assignment time; Kamino changes that assignment policy.
- _Tang et al. (OSDI '20)_ - Twine is a large-scale cluster manager with policy-rich placement, whereas Kamino focuses specifically on reducing per-request allocator latency under private caches.
- _Schwarzkopf et al. (EuroSys '13)_ - Omega studies scalable multi-scheduler cluster management, while Kamino studies the more local but latency-critical question of how to dispatch requests among AAs inside one node.
- _Yan and Li (USENIX ATC '22)_ - latency-aware CDN caching also reasons about latency instead of raw hit rate, but Kamino applies that idea to hierarchical rule caches and queueing inside a VM allocator.

## My Notes

<!-- empty; left for the human reader -->

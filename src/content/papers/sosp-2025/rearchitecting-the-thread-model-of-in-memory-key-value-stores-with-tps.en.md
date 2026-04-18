---
title: "Rearchitecting the Thread Model of In-Memory Key-Value Stores with μTPS"
oneline: "μTPS splits KVS work into cache-resident and memory-resident thread pools, then auto-tunes cores, LLC ways, and hot-item placement to beat RTC servers."
authors:
  - "Youmin Chen"
  - "Jiwu Shu"
  - "Yanyan Shen"
  - "Linpeng Huang"
  - "Hong Mei"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Tsinghua University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764794"
tags:
  - databases
  - scheduling
  - caching
category: storage-and-databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`μTPS` argues that a modern in-memory KVS should stop running request handling as one monolithic run-to-completion function. Instead, it splits the pipeline into a cache-resident layer for NIC polling, response handling, and hot keys, plus a memory-resident layer for full-index traversal and cold-item access, then auto-tunes cores, LLC ways, and hot-set size online. Across two implementations, the paper reports `1.03-5.46x` throughput gains over closely matched RTC baselines while keeping latency roughly comparable.

## Problem

The paper targets a regime where a single cache miss is no longer a rounding error. Modern RDMA-capable NICs can deliver more than `10M` requests per second, while a key-value operation may take only a few hundred nanoseconds. In that setting, the usual non-preemptive KVS design, thread-per-queue with run-to-completion execution, becomes structurally awkward: one worker thread polls the network buffer, parses the request, traverses the index, touches the value, and prepares the response. Those sub-tasks have very different memory footprints and contention behavior, but the runtime forces them to share the same instruction stream, cache footprint, and core.

That coupling hurts in two ways. First, it is cache-unfriendly. Polling a carefully sized userspace receive buffer can be very cache-resident because DDIO/DCA places packet data into the LLC, while index traversal and value access are pointer-heavy and memory-resident. Packing both into one hot loop causes cache thrashing. Second, it makes contention harder to manage. Skewed workloads create hotspots in index and data updates, and the usual alternatives both have clear downsides: share-nothing designs reduce locking but suffer load imbalance, while share-everything designs balance load but pay synchronization costs. Existing work on cache allocation or data-structure layout helps, but it does not change the fact that the thread architecture still executes heterogeneous stages monolithically.

## Key Insight

The paper's central claim is that the right stage boundary in a high-speed KVS is not "one software module per stage" but "one cache-behavior class per stage." Request polling, parsing, response handling, and accesses to the hottest items can be kept mostly cache-resident and scale well. Full-index traversal, cold-item access, and conflict-heavy updates are fundamentally memory-resident and benefit from batching, prefetching, and tighter control over how many threads execute them.

That reframing matters because it lets the system optimize the two layers independently without reviving the worst part of classic TPS. `μTPS` does not decompose the KVS into many queues and dozens of thread pools; it uses only two layers, minimizing communication frequency while still isolating the stages that pollute each other's caches or block on contention. Once the hot path and the cold path are separated, the system can assign different cores and LLC ways to them, keep hot keys in cache, and reduce the number of threads that contend on the cold update path without stalling the rest of request processing.

## Design

`μTPS` organizes the server into a cache-resident (`CR`) layer and a memory-resident (`MR`) layer. The `CR` layer owns network polling, request parsing, response transmission, and direct handling of hot items. The `MR` layer owns the full index and all data items, processing misses from the `CR` layer. A request therefore takes one of two paths: if its key is hot, the `CR` worker finishes it locally; otherwise it is forwarded through a `CR-MR` queue, processed in `MR`, and the result is returned through a response buffer.

The RPC path is redesigned around reconfiguration. Instead of giving every worker thread its own receive queue, the server uses a single shared receive queue backed by RDMA SRQ. Clients append requests into one receive buffer, and worker `i` processes slots whose position satisfies `m mod n = i`, where `n` is the current number of `CR` workers. That lowers buffer memory overhead and, more importantly, lets the system change thread counts by updating server-side state rather than coordinating with all clients. Responses use small per-thread response buffers, and multi-packet receive queues reduce verb-posting overhead.

The `CR` layer also maintains a resizable hot set rather than an LRU-style cache. A background thread samples recent accesses, uses a count-min sketch plus min-heap to identify hot keys, and swaps in a new hot set with epoch-based publication. For tree indexes, the hot index is stored as a sorted array to avoid pointer overhead; for hash indexes, the main structure is reused. Worker execution is a small FSM with a hit path and a miss path: on a hit, the request is completed locally; on a miss, it is forwarded to `MR` and the `CR` worker immediately resumes non-blocking polling.

The `MR` layer is built to hide memory latency. It batches requests popped from the `CR-MR` queue, transforms put/get indexing into C++20 stackless coroutines, inserts prefetches before pointer dereferences, and switches among coroutines while outstanding cache lines are fetched. Data movement is direct: `MR` copies values between the network buffer and KV storage rather than moving payloads through the inter-layer queue. Concurrency control stays share-everything, reusing thread-safe `MassTree` or `libcuckoo`; values embed version and lock bits so reads are lock-free and larger writes use CAS-based locking.

Inter-layer communication is handled by an all-to-all `CR-MR` queue: each `CR`/`MR` thread pair gets a dedicated lock-free ring buffer, and each slot can hold a batch of requests. Queue entries are only `16` bytes, carrying a compact key, request type, size, and buffer pointer. Completion is piggybacked on the queue tail pointer rather than sent as explicit messages. Above all of this sits an auto-tuner that reassigns threads between `CR` and `MR`, resizes the hot set, and allocates LLC ways via `PQOS`. It searches thread allocations and cache-way splits hierarchically, using trisecting where the performance curve is approximately convex and linear probing for cache size. The paper reports that a full reconfiguration takes about `0.9 s` without stopping request processing.

## Evaluation

The implementation comes in two variants: `μTPS-H` with `libcuckoo` and `μTPS-T` with `MassTree`. Evaluation uses a server with `28` cores on one NUMA node, `200 Gbps` RDMA, and a `10M`-item preloaded database. The main comparisons are against `BaseKV`, which keeps the same optimizations but uses a run-to-completion thread pool, `eRPC-KV`, and passive RDMA KVSs such as `RaceHash` and `Sherman`.

The strongest results are in read-heavy and skewed settings, exactly where cache locality and hotspot isolation should matter most. With a tree index, `μTPS` averages `1.30x` and `1.29x` the throughput of `BaseKV` on `YCSB-B` and `YCSB-C`. The paper also shows that the idealized split architecture already wins before counting the full system design: a communication-free NP-TPS prototype improves throughput by `1.22-1.54x` over NP-TPQ, and isolating just `0.1‰` of hottest keys yields about `1.08x` more lookup throughput in `MassTree`.

The wins persist on scan-heavy and real workloads. For range queries, `μTPS-T` beats `BaseKV` by `33.1%` on `YCSB-E` and `25.1%` on a scan-only workload. On Meta's ETC-like workload, it exceeds `BaseKV` by `29.1%`, `13.0%`, and `26.6%` at `10%`, `50%`, and `90%` get ratios, and it is substantially faster than `eRPC-KV`. On three Twitter traces, the gains over `BaseKV` are `44.5%`, `39.8%`, and essentially flat (`0.1%`), which is a useful nuance: the design still works on a uniform, write-dominant trace, but it does not magically create headroom where the workload offers little hot/cold separation.

The evaluation is also honest about where the benefit shrinks. Under uniform write-heavy workloads, especially with small items, `μTPS` gains are modest and `eRPC-KV` can occasionally do slightly better because its share-nothing design avoids locking and its RPC path is more optimized than the paper's single-queue receive path. Latency remains close rather than strictly lower: the added inter-core hop costs roughly `100 ns`, and the paper reports median and P99 latencies that are usually similar to `BaseKV`, with slightly higher medians in some hash-index cases. The ablations support the design logic: batching improves throughput by `51.6%` in `μTPS-T` and `93.7%` in `μTPS-H`, while the auto-tuner reacts to a dynamic workload change in about `0.9 s` and improves throughput by roughly `20%` once reconfiguration completes.

## Novelty & Impact

Relative to systems like `MICA` and `FaRM`, the novelty is not "another faster RDMA KVS." The contribution is architectural: the paper reintroduces thread-per-stage into a non-preemptive environment, but only after redefining stages around cache residency and contention rather than software modularity. That gives the paper a stronger thesis than a bag of optimizations. Reconfigurable RPC, hot-set caching, batched coroutine indexing, the compact `CR-MR` queue, and the auto-tuner are all in service of that one thesis.

This is likely to matter to both practitioners and researchers building CPU-managed in-memory stores on very fast networks. The paper shows that the de facto RTC recipe is not obviously optimal once NIC and memory latencies shrink enough that cache behavior dominates. Its impact is therefore a new mechanism and a new framing: the thread model itself becomes a first-class optimization target, not a fixed background assumption.

## Limitations

The paper does not show a universal win. Its own results say the gains are strongest for tree indexes, skewed accesses, and read-heavy or mixed workloads; under uniform small-item writes the advantage narrows, and `eRPC-KV` can sometimes outperform it. That means `μTPS` depends on there being enough hot/cold asymmetry or contention structure for the split to exploit.

The RPC stack is also a partial design point rather than a definitive endpoint. The authors explicitly note that `Reconfigurable RPC` is slower than `eRPC` in some settings and suggest that combining `μTPS` with `eRPC` could improve results, but they do not implement that combination. Similarly, the auto-tuner is empirical rather than analytic: it searches over threads, hot-set size, and LLC ways, and although `0.9 s` is acceptable for the workload shifts the authors expect, it would be less comfortable under highly volatile traffic.

Finally, the evaluation scope is narrower than the headline might suggest. Most results are on one NUMA node with `28` cores, so the paper does not deeply explore cross-socket effects or larger server-scale coordination. The design also assumes CPU-involved, thread-safe indexes and explicit concurrency control on shared data, so it is not aimed at passive one-sided RDMA KVSs that remove the server CPU from the critical path.

## Related Work

- _Lim et al. (NSDI '14)_ - `MICA` popularized high-performance run-to-completion KV serving; `μTPS` keeps non-preemptive polling but argues that collapsing all stages into one worker loop wastes cache locality.
- _Dragojević et al. (NSDI '14)_ - `FaRM` also relies on pinned threads and fast RDMA request handling, but `μTPS` focuses on the cache-thrashing and contention costs that appear when the worker remains monolithic.
- _Roghanchi et al. (SOSP '17)_ - `ffwd` shows that delegation-based inter-core communication can be much cheaper than it looks; `μTPS` applies the same optimism to a multi-producer, multi-consumer KVS pipeline.
- _Pismenny et al. (OSDI '23)_ - `ShRing` improves packet reception with shared receive rings, while `μTPS` uses a shared receive queue as part of a reconfigurable RPC path and a broader hot/cold stage split.

## My Notes

<!-- empty; left for the human reader -->

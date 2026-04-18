---
title: "Getting the MOST out of your Storage Hierarchy with Mirror-Optimized Storage Tiering"
oneline: "MOST mirrors only a small hot-data class, then load-balances reads and writes by routing and allocation instead of migrating whole working sets."
authors:
  - "Kaiwei Tu"
  - "Kan Wu"
  - "Andrea C. Arpaci-Dusseau"
  - "Remzi H. Arpaci-Dusseau"
affiliations:
  - "University of Wisconsin–Madison"
  - "Google"
conference: fast-2026
category: cloud-and-distributed-storage
tags:
  - storage
  - caching
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

MOST adds a small mirrored hot-data class to classic two-tier storage management. Instead of rebalancing load mainly by migrating blocks, it changes request routing and new-write placement based on which device currently has lower end-to-end latency. Implemented as Cerberus inside CacheLib, it matches tiering's space efficiency much more closely than full caching or mirroring while outperforming prior tiering and caching baselines on both static and bursty workloads.

## Problem

Modern devices such as Optane, fast NVMe SSDs, SATA SSDs, and remote NVMe over Fabrics no longer fit a clean "fast tier above slow tier" pyramid. Their latency and bandwidth overlap, and the effective performance ratio shifts with request size, read/write mix, and concurrency. Traditional storage hierarchy managers assume a more stable gap than current devices actually provide.

Single-copy tiering wastes no capacity, but it can rebalance load only by moving data, so it reacts slowly, adds write traffic, and interferes with foreground I/O. Multi-copy approaches fail in the other direction: full mirroring wastes too much space, and caching-based designs often underuse the capacity tier, especially for writes. The paper's core problem is how to exploit both devices' bandwidth without paying either tiering's migration cost or mirroring's duplication cost.

## Key Insight

MOST mirrors only a small hot subset and uses those duplicate copies as a fast load-balancing surface. Once hot data exists on both devices, the system can immediately shift reads and some writes by changing routing and allocation, instead of waiting for migrations to converge.

The control objective is simple: equalize end-to-end latency across the performance and capacity devices. If the performance device is still faster, mirrored traffic stays there; if it becomes slower, some mirrored requests and new allocations move to the capacity device. Most data remains single-copy, so capacity efficiency stays close to classic tiering.

## Design

MOST has two storage classes. The mirrored class keeps a hot subset on both devices. The tiered class keeps a single copy, with warm data on the performance device and cold data on the capacity device. Cerberus tracks hotness at 2 MB segment granularity using per-segment counters; in the experiments, letting the mirrored class grow to at most 20% of total capacity was enough.

The central control variable is `offloadRatio`, the probability that a mirrored request or a newly allocated write will go to the capacity device. Every 200 ms, a pinned optimizer estimates per-device end-to-end latency from Linux block-layer counters, smooths it with EWMA, and adjusts `offloadRatio` in 0.02 steps. Under light load MOST behaves like ordinary tiering; under heavy load it offloads enough traffic to equalize latency.

Migration is limited and one-sided. If the mirrored class is too small, Cerberus duplicates the hottest performance-tier segment onto the capacity device; if the mirrored class is full, it swaps in hotter tiered segments and evicts colder mirrored ones. It migrates only away from the device with higher observed latency, so the control plane does not amplify the bottleneck.

Writes are the paper's most distinctive mechanism. For mirrored data, Cerberus updates only one copy and tracks validity at 4 KB subpage granularity with invalid and location bits, so writes can be load-balanced too. A background cleaner rebuilds missing copies only for blocks with large rewrite distance, avoiding useless cleaning of data likely to be overwritten again. The paper also allows a maximum `offloadRatio` to cap tail-latency exposure to the capacity device.

## Evaluation

The authors implement Cerberus in about 1.5K lines inside CacheLib and compare it against in-framework implementations of HeMem, BATMAN, Colloid, and Orthus on a 40-core Xeon with 64 GB DRAM and two local hierarchies: 750 GB Optane plus 1 TB NVMe, and 1 TB NVMe plus 1 TB SATA.

The static results support the main claim. On synthetic workloads, Cerberus reaches up to 2.34x higher throughput and up to 75% lower P99 latency than the baselines cited in the abstract. The Orthus comparison is especially revealing: on one random-read workload Orthus needs 690 GB of duplicated data to reach similar throughput, while Cerberus uses 50 GB of mirrored data. Against Colloid, the advantage comes from avoiding migration-driven instability when device latency spikes.

The dynamic results are stronger still. On bursty workloads, Cerberus adapts in under 10 seconds by changing routing, while Colloid can need more than 800 seconds if migration is capped at 100 MB/s. Across the dynamic workloads, Cerberus mirrors on average 86 GB to the capacity tier, whereas Colloid migrates about 252 GB to the performance tier and 229 GB to the capacity tier. The paper argues that those extra writes would cut the rated lifetime of the studied capacity SSD from three years to 129 days.

End-to-end CacheLib experiments show up to 1.86x higher throughput and up to 90% lower P99 GET latency on production traces; averaged across four traces, Cerberus lowers mean latency by 14% and P99 by 19% versus the best baseline. The evaluation is strong on synthetic, bursty, and production cache workloads, but it remains mostly a two-tier, cache-oriented study on one server platform.

## Novelty & Impact

Compared with _Raybuck et al. (SOSP '21)_ on HeMem and _Vuppalapati and Agarwal (SOSP '24)_ on Colloid, MOST is not just a better migration policy inside single-copy tiering. It changes the layout so a small amount of steady-state redundancy becomes the mechanism for fast load control. Compared with _Wu et al. (FAST '21)_ on Orthus, it does not devote the whole performance tier to duplicates and it can balance writes as well as reads.

That makes the paper a new storage-hierarchy mechanism, likely useful to flash caches, tiered key-value stores, and block layers above heterogeneous devices. Its broader contribution is conceptual: cross-tier redundancy can be used as a bandwidth-management primitive, not just for reliability or hit rate.

## Limitations

The paper is explicitly a two-tier design, and its multi-tier extension is left as future work. Its consistency story is also incomplete: the authors note that stronger guarantees for migration-induced mapping updates would likely need a write-ahead log, but they do not build or evaluate that mechanism. Cerberus also works below tenant identity and therefore does not offer isolation or QoS controls across applications.

There are empirical limits too. The implementation lives inside CacheLib's user-level storage layer, so the evidence is strongest for cache-like workloads rather than general block or filesystem stacks. Although the motivation discusses remote and disaggregated devices, the main experiments use only local Optane, NVMe, and SATA hierarchies. The scheme also assumes a relatively small mirrored class can cover the region where fast rerouting matters; if the hot set spreads out or writes repeatedly invalidate mirrored copies, the benefit should shrink and cleaning pressure should rise.

## Related Work

- _Raybuck et al. (SOSP '21)_ — HeMem uses single-copy hotness-based tiering, so it can only rebalance load by migrating data between tiers.
- _Vuppalapati and Agarwal (SOSP '24)_ — Colloid also tries to balance heterogeneous-tier latency, but it remains single-copy and therefore pays heavily in migration time and write amplification under bursts.
- _Wu et al. (FAST '21)_ — Orthus redirects reads across modern storage devices with non-hierarchical caching, but it wastes performance-tier capacity on duplicates and handles writes poorly.
- _Xiang et al. (OSDI '24)_ — Nomad keeps temporary duplicate copies during migration, whereas MOST makes selective steady-state mirroring the primary load-balancing mechanism.

## My Notes

<!-- empty; left for the human reader -->

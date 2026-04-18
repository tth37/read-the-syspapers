---
title: "Scalable Far Memory: Balancing Faults and Evictions"
oneline: "Mage keeps far-memory paging scalable by fully decoupling eviction, pipelining batches, and partitioning metadata so multi-core workloads can offload much more memory."
authors:
  - "Yueyang Pan"
  - "Yash Lala"
  - "Musa Unal"
  - "Yujie Ren"
  - "Seung-seob Lee"
  - "Abhishek Bhattacharjee"
  - "Anurag Khandelwal"
  - "Sanidhya Kashyap"
affiliations:
  - "EPFL"
  - "Yale University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764842"
tags:
  - memory
  - disaggregation
  - rdma
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Mage says page-based far memory fails at high core counts because faults and evictions are coupled too tightly. It restores scalability by keeping eviction off the application path, pipelining batches across TLB flush and RDMA waits, and sharding the metadata that used to serialize paging.

## Problem

Page-based far memory is attractive because it preserves application compatibility, but the workloads that need it most are now multi-core analytics and serving jobs. Existing systems such as Hermit and DiLOS make single page operations cheaper, yet under high thread counts they collapse long before remote memory or RDMA should be the limit. On 48-thread GapBS, offloading 10% of memory already drops throughput by 50% in DiLOS and 75% in Hermit, far worse than an ideal baseline that charges only RDMA latency. The authors trace that gap to three bottlenecks: TLB shootdowns across many cores, globally contended page-accounting structures such as LRU lists, and local or remote page allocators whose tail latency spikes under pressure.

## Key Insight

The central claim is that fault-in and eviction should be optimized as separate pipelines. Fault-in is latency-critical and should only grab a free page, fetch remote data, and do minimal bookkeeping. Eviction is throughput-oriented background work and should absorb the expensive coordination. Once faulting threads have to evict pages themselves, TLB flushes, victim selection, and allocator contention land on the critical path and create a feedback loop where more faults make eviction slower and slower eviction makes faults costlier. Mage therefore bans synchronous eviction and relies on a small dedicated evictor pool.

## Design

Mage has three design principles. First, always-asynchronous decoupling pins a small number of evictor threads to dedicated cores and keeps faulting threads out of eviction entirely. The paper finds four evictor threads are enough to maintain the free-page supply without creating excessive IPI contention.

Second, cross-batch pipelined eviction overlaps stages from different batches. Each evictor keeps a TLB staging buffer for unmapped pages waiting on shootdown completion and an RDMA staging buffer for pages waiting on remote-write completion. While one batch waits for TLB ACKs or RDMA ACKs, the thread prepares or reclaims other batches, hiding coordination latency behind network waits.

Third, Mage favors coordination avoidance over perfect policy accuracy. It replaces a global LRU with partitioned LRU lists scanned round-robin by evictors, hashes incoming pages across partitions, shards free-page caches, and in MageLib uses a three-level allocator. Remote allocation is simplified by mapping local offsets directly to remote offsets rather than managing swap entries. The ideas are implemented twice: MageLnx in Linux 4.15 with specialized MM fast paths, and MageLib in OSv with a unified page table and staged allocator.

## Evaluation

The evaluation covers random-access analytics, prefetchable scans, phase-changing workloads, Memcached, and microbenchmarks on a 200 Gbps RDMA testbed. The main throughput result is on 48-thread GapBS: at 10% far memory, MageLib and MageLnx lose only 15% and 19% throughput, versus 51% for DiLOS and 74% for Hermit. On XSBench, Mage can tolerate about 20% offloading for a 20% throughput loss, giving 3.6-3.8x more offloadable memory than the baselines.

The microbenchmarks show why. MageLib reaches 181 Gbps, about 94% of the 192 Gbps RDMA limit, which is 3.1x faster than DiLOS and 7.1x faster than Hermit; p99 fault latency falls to 12 us in MageLib and 31 us in MageLnx, versus 82 us and 255 us in the baselines. For Memcached under a 200 us p99 SLO, MageLib can offload 21% more memory than DiLOS and 36% more than Hermit. The evidence matches the paper's claim well, though the comparison is not perfectly symmetric because Hermit runs on bare metal while MageLib and MageLnx run in VMs.

## Novelty & Impact

Relative to Hermit and DiLOS, Mage's novelty is not a new far-memory backend or a better prefetcher, but a new decomposition of the paging system. The paper argues that transparent far memory only scales when eviction becomes its own throughput pipeline with dedicated resources and low-contention metadata. That reframes page-based far memory from "make page faults cheaper" to "remove coordination from the fault path."

The impact is broader than RDMA. The authors argue the same OS-level ideas should apply to any fast swap backend, including SSD-backed swap and zswap.

## Limitations

Mage spends resources and sacrifices policy precision. It assumes dedicated eviction cores, and its partitioned LRU plus simplified remote allocation are intentionally less globally accurate than a fully coordinated policy.

The evaluation also shows practical limits. MageLib and MageLnx are slower than Hermit with 100% local memory because of virtualization overheads and, for OSv, less mature userspace libraries. MageLnx is additionally constrained by Linux network-stack interference and lacks the prefetching support shown for MageLib. Finally, Mage still pays page-granularity I/O amplification; it makes paging scale better, but it does not make paging disappear.

## Related Work

- _Qiao et al. (NSDI '23)_ — Hermit also chases transparent remote memory on Linux, but its feedback-directed asynchrony still falls back to synchronous eviction and collapses under high thread counts.
- _Yoon et al. (EuroSys '23)_ — DiLOS removes a large fraction of Linux paging overheads with a specialized LibOS, whereas Mage argues specialization alone is insufficient without scalable eviction and low-contention metadata.
- _Ruan et al. (OSDI '20)_ — AIFM avoids page faults through application-integrated far memory, while Mage stays compatible with unmodified applications by redesigning the paging subsystem instead.
- _Weiner et al. (ASPLOS '22)_ — TMO shows that page-based memory offloading is deployable at hyperscaler scale; Mage focuses on the multicore paging bottlenecks that limit how much of that remote capacity can be exploited.

## My Notes

<!-- empty; left for the human reader -->

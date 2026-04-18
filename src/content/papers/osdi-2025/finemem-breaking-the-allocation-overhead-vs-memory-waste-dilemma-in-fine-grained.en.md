---
title: "FineMem: Breaking the Allocation Overhead vs. Memory Waste Dilemma in Fine-Grained Disaggregated Memory Management"
oneline: "FineMem makes disaggregated memory allocation fine-grained by pre-registering memory, handing out per-chunk MW capabilities, and allocating via a contention-aware bitmap tree."
authors:
  - "Xiaoyang Wang"
  - "Yongkun Li"
  - "Kan Wu"
  - "Wenzhe Zhu"
  - "Yuqi Li"
  - "Yinlong Xu"
affiliations:
  - "University of Science and Technology of China"
  - "Google"
  - "Anhui Provincial Key Laboratory of High Performance Computing, USTC"
conference: osdi-2025
code_url: "https://github.com/ADSLMemoryDisaggregation/FineMem"
tags:
  - memory
  - disaggregation
  - rdma
category: memory-and-storage
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

FineMem treats remote allocation, not remote access, as the main systems problem in RDMA disaggregated memory. It pre-registers the pool once, grants chunk-scoped access with Memory Windows, and allocates through a compute-node service backed by a contention-aware one-sided bitmap allocator.

## Problem

RDMA one-sided I/O is fast only after memory has been registered and authorized. That setup is expensive on the memory node: the paper reports that registering a 4 MB memory region can take more than 480 us. Existing systems therefore choose between two bad options. They either keep a memory-node allocator in the loop via RPC, which stops scaling under client concurrency, or they pre-map very large chunks such as 1 GB, which avoids registration on the hot path but wastes memory through coarse reservation and fragmentation.

The paper shows that this is not a theoretical nuisance. In FUSEE, shrinking allocation size from 1 GB to 2 MB reduces waste but already costs about 17% throughput, and 4 KB is worse. For malloc-style workloads, hugepage-scale remote chunks leave substantial unused space that cannot be safely reclaimed or shared across heterogeneous systems in the same pool. The question is whether a shared DM pool can support local-allocator-like granularity without falling back to one of those two costs.

## Key Insight

FineMem's key claim is that registration, protection, and allocation should not be coupled. Registration can be paid once by pre-registering the entire pool as a large MR. Protection can then be recovered by using Memory Windows to mint chunk-specific rkeys. Allocation finally becomes a metadata problem: only a trusted compute-node service can touch allocator metadata, while applications receive access only to the chunks they have been granted.

Once these responsibilities are split, the remaining bottleneck is remote concurrency control, which FineMem handles with bitmap summaries, contention steering, and lightweight redo logging.

## Design

The memory node pre-registers the whole pool and pre-creates Memory Windows for chunks, spans, and sections. FineMem keeps both main and backup rkeys in a capability table, so `free` can swap to a backup rkey in the critical path while fresh keys are regenerated asynchronously. On each compute node, a trusted allocation service exposes `malloc(size)` and `free(addr)`; applications never directly modify global allocation metadata.

Allocator metadata is a two-layer bitmap tree tuned for one-sided CAS. A section contains 16 spans; each span covers 128 KB and is divided into 32 chunks. The section bitmap summarizes each span as free, normal in-use, contended, or full, so large allocations can take aligned spans directly while small allocations descend to a span bitmap. FineMem also caches bitmap blocks locally to keep the search path short.

Headers track recent CAS failures, and spans or sections that exceed a threshold are marked contended so later allocators move elsewhere. This matters because contention costs network round-trips, not just local spin time.

For crash consistency, the successful bitmap CAS is the commit point. FineMem packs a temporary redo log into the same 64-bit header update, later flushes it into a full per-chunk log, and uses timestamps to reject stale writes. Recovery scans bitmap and redo-log state to reclaim allocations held by crashed compute nodes and regenerate rkeys.

## Evaluation

The evaluation uses 16 compute nodes and 1 memory node on CloudLab with ConnectX-6 100 Gb NICs, while limiting the memory node to one CPU core. FineMem is compared against on-demand RPC allocation, pre-mapped RPC allocation, and a one-sided pre-mapped array allocator.

With 4 KB allocations and 512 client threads, FineMem averages 43.2 us allocation latency versus 763 us for the one-sided pre-mapped baseline, and its tail latency is 79 us versus 16.1 ms. The paper traces that gap to metadata behavior: FineMem needs about 1.3 CAS attempts per allocation on average, while the array design needs about 45. It also avoids the early scalability collapse of RPC allocators once the memory-node CPU saturates.

End-to-end results are consistent with that story. FineMem-User improves memory utilization by 2.25x-2.8x over coarse pre-mapped approaches with only 2.5%-4.1% overhead relative to static pre-allocation. FineMem-KV improves update-heavy YCSB-A throughput by about 27%-110%, though the paper notes that read-heavy YCSB-B/C/D benefit much less. FineMem-Swap raises average remote-memory utilization from 41.39% to 74.06% and improves job throughput by 17.71%.

## Novelty & Impact

Relative to _Shen et al. (FAST '23)_, FineMem removes the memory-node RPC allocation bottleneck exposed by FUSEE. Relative to _Zhang et al. (SOSP '23)_, it keeps the pre-mapped spirit of CXL-SHM but adds isolation and predictable fine-grained allocation. Relative to _Lee et al. (SOSP '21)_, it pursues MIND's fine-grained isolation goal without requiring programmable switches.

The broader contribution is a reusable allocator substrate. FineMem is not a new far-memory programming model; it is the low-level mechanism that lets malloc systems, KV stores, and swap systems share one remote pool efficiently.

## Limitations

FineMem assumes a trusted per-compute-node allocation service and pays 2-10 us of IPC overhead on each protected allocation. It also pre-registers the whole pool, so initialization cost and NIC metadata capacity still matter. The paper does not try to solve coherence, replication, or data-path optimization; its scope is allocator control.

Its fault model is narrower than a full DM runtime. FineMem handles compute-node crashes and stale log flushing, but not memory-node failure or replicated recovery. The mechanism is also RDMA-specific, and CXL appears only as future work.

## Related Work

- _Ruan et al. (OSDI '20)_ — AIFM exposes far-memory abstractions to applications, while FineMem focuses on the lower-level allocator substrate that such systems need underneath.
- _Lee et al. (SOSP '21)_ — MIND uses programmable switches for in-network memory management, whereas FineMem stays in software and commodity RDMA NIC features.
- _Shen et al. (FAST '23)_ — FUSEE shows the value of disaggregated KV storage, but its RPC allocation path becomes the bottleneck that FineMem replaces.
- _Zhang et al. (SOSP '23)_ — CXL-SHM demonstrates one-sided pre-mapped shared memory, while FineMem adds isolation and a scalable metadata design for fine-grained allocation.

## My Notes

<!-- empty; left for the human reader -->

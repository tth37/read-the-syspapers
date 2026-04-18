---
title: '"Range as a Key" is the Key! Fast and Compact Cloud Block Store Index with RASK'
oneline: "RASK indexes contiguous block ranges directly, then uses log-structured leaves and range-aware maintenance to cut cloud block-store index memory by up to 98.9%."
authors:
  - "Haoru Zhao"
  - "Mingkai Dong"
  - "Erci Xu"
  - "Zhongyu Wang"
  - "Haibo Chen"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Alibaba Group"
conference: fast-2026
category: indexes-and-data-placement
tags:
  - storage
  - datacenter
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`RASK` is an in-memory ordered index for cloud block stores that treats a contiguous block range, not an individual block, as the key. It combines `ART` internal nodes with log-structured leaves, then handles overlap and fragmentation through ablation-based search, two-stage garbage collection, and range-conscious split/merge. On production traces, that cuts index memory by up to `98.9%` and raises throughput by up to `31.0x`.

## Problem

Alibaba Cloud EBS keeps its active block-store index in DRAM, and that index has become a dominant memory consumer: the paper reports about `57.1%` of node memory, with some clusters risking roughly `35%` stranded storage because new data cannot be indexed. The mismatch is granularity. Existing designs map individual LBAs or tiny request fragments, yet after compaction `65.0%` to `81.5%` of Alibaba writes belong to longer consecutive-write sequences, with similar patterns in Tencent, Google, and Meta traces. Direct range indexing would save entries, but it creates overlap between old and new ranges and fragmentation when leaf boundaries cut through long writes.

## Key Insight

RASK makes range-as-a-key practical by turning each leaf into a small append-only log of range versions. Writes append cheaply and reclaim fully covered entries only when a leaf is full; reads scan newest entries first and progressively remove already-satisfied pieces of the target range. Structural maintenance then optimizes for range boundaries, not just entry counts, so the range index does not collapse back into many fragments.

## Design

`RASK` uses `ART` internal nodes and log-structured leaves indexed by an anchor key, the minimum left bound in the leaf's range space. Reads find the last leaf whose anchor is no greater than the target left bound, then follow the doubly linked leaf list if the request spans multiple leaves.

The read path uses ablation-based search. Each lookup tracks an ordered `Unfound List` of target subranges whose newest values are still missing. The leaf is scanned backward; intersections with unfound subranges are added to the result and removed from the list, so search stops once the target range is fully reconstructed.

Writes append new ranges to the target leaf. If full, RASK first runs lightweight GC, which uses a left-bound map and catches `73.8%` of reclaimable entries in replay, then normal GC, which uses a `NonOverlap List` representing the union of newer ranges to identify entries covered by multiple later writes. Splits prefer non-overlapping boundaries; repeated cross-leaf inserts increment `Nfrag` and trigger merge/resplit. Applications whose values encode extents provide `DivideValue` and `MergeRange` callbacks. Concurrency uses optimistic locking, but cross-leaf reads are not a perfectly global snapshot; the measured inconsistency rate is about `0.0394%`.

## Evaluation

The main evaluation replays post-compaction traces from `1.8k` virtual disks across four Alibaba Cloud clusters and compares RASK with the original EBS index plus nine ordered indexes. On the full dataset, RASK delivers `2.76x` to `37.8x` baseline throughput and `1.15x` to `1.82x` over the original EBS index. Memory savings are larger: RASK uses about `19.9%` of the original EBS index's memory and `1.15%` to `54.7%` of the baselines' memory. It also lowers `P99` latency by `23.9%` to `97.6%` and `P99.999` by `34.2%` to `99.7%`.

The breakdown supports the mechanism. Relative to an `ART` starting point, log-structured leaves give `1.50x` higher throughput and `90.3%` lower memory; normal GC adds `70.6%` more throughput; lightweight GC adds `24.1%`; ablation-based search adds `12.6%`; range-conscious split cuts memory by `26.0%`; and merge/resplit saves another `7.70%` of memory. The sensitivity study is honest: when average write length is at most `2`, RASK still beats other ordered indexes by at least `1.56x` but trails the original EBS index by `6.64%`.

The idea also generalizes. On Tencent EBS traces, RASK improves throughput by `2.35x` to `49.21x`. Replacing RocksDB's MemTable with RASK on Meta Tectonic traces yields up to `7.46x` higher throughput, and simulated Google flash-cache indexing improves throughput by `1.52x` to `37.52x`. Taken together, the results support the main claim: range-heavy storage metadata really can be indexed more compactly and faster when the index natively understands ranges.

## Novelty & Impact

RASK's novelty is not merely "use intervals instead of points." Its contribution is the maintenance machinery that makes range keys viable on the hot path: log-structured leaves to defer overlap cleanup, ablation-based reads to recover newest subranges, and split/merge rules that try to preserve whole ranges. Relative to ordered point indexes, the paper shows that eager or lazy overlap handling is still too expensive; relative to interval-style indexes, RASK is unusual because it aggressively reclaims covered ranges.

That makes the paper relevant anywhere storage metadata tracks long physical extents: cloud block stores, flash caches, and metadata services that map logical blocks to files. The broader lesson is that once workloads naturally operate on ranges, forcing point granularity down to the in-memory index is an avoidable tax.

## Limitations

The paper is strongest for range-write-heavy workloads. If writes are mostly tiny and sparse, RASK still looks good against generic ordered indexes, but its advantage over a hand-tuned point-oriented incumbent shrinks or disappears. This is a workload-structure win, not a universal replacement for every point index.

There are also integration and semantics costs. RASK is currently in-memory only; persistence is delegated to the embedding system. Applications whose values encode ranges must provide correct `DivideValue` and `MergeRange` callbacks, and the concurrency scheme guarantees per-leaf consistency but not a fully atomic cross-leaf snapshot.

## Related Work

- _Zhang et al. (FAST '24)_ — Alibaba Cloud's EBS paper explains the incumbent LBA-oriented architecture that RASK targets; RASK replaces per-block indexing with a native range-key design.
- _Leis et al. (ICDE '13)_ — `ART` provides the compact trie-style internal nodes RASK builds on, but it does not address range overlap, covered-range reclamation, or fragmentation.
- _Wu et al. (EuroSys '19)_ — `Wormhole` is a fast ordered point index; RASK shows that even strong point indexes remain expensive once range overlap must be handled eagerly or lazily.
- _Christodoulou et al. (SIGMOD '22)_ — `HINT` is a modern in-memory interval index for interval queries, whereas RASK focuses on overwriting workloads where covered old ranges should be reclaimed to save memory and speed reads.

## My Notes

<!-- empty; left for the human reader -->

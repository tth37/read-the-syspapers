---
title: "Deft: A Scalable Tree Index for Disaggregated Memory"
oneline: "Deft keeps a DM B+ tree shallow but reads only bucket pairs and sub-nodes, then adds one-sided SX locks and OPDV to scale writes and searches."
authors:
  - "Jing Wang"
  - "Qing Wang"
  - "Yuhao Zhang"
  - "Jiwu Shu"
affiliations:
  - "Tsinghua University"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696062"
code_url: "https://github.com/thustorage/deft"
tags:
  - databases
  - memory
  - disaggregation
  - rdma
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Deft is an RDMA-oriented B+ tree for disaggregated memory that keeps `1 KB` nodes for shallow height, but exposes much smaller remote access units: hash bucket pairs in leaves and segmented slices in internal nodes. It couples that layout with a one-sided shared-exclusive lock and on-path decoupled versioning (OPDV), reaching up to `42.7 Mops/s` on skewed YCSB-A and `91.0 Mops/s` on skewed YCSB-C while outperforming Sherman, SMART, and dLSM.

## Problem

Disaggregated memory forces compute nodes to traverse indexes with one-sided RDMA because memory nodes have little CPU. That turns a normal in-memory tree-design problem into a network problem. Large tree nodes reduce height and round trips, but every lookup has to fetch the whole node, so bandwidth is wasted. Smaller nodes or radix-like structures reduce bytes per read, but they raise tree height, enlarge the uncached upper tree, and add more remote hops. The paper’s Sherman experiment shows the tradeoff clearly: once node size exceeds `1 KB`, a single CN can already saturate a `100 Gbps` RNIC; shrinking nodes raises height instead.

Concurrency makes this worse. A remote exclusive lock acquired with `RDMA_CAS` scales badly under skew: the authors measure peak lock throughput below `4 Mops/s` at `40` threads, then watch performance fall as retries queue at the NIC. Correct read-write synchronization is also expensive. Checksum validation burns CPU, classic versioning needs three separate `RDMA_READ`s, and FaRM-style per-cache-line versions force whole-object rewrites. On disaggregated memory, all of those costs are visible.

## Key Insight

The paper’s central claim is that a DM index should keep coarse logical nodes for fanout, but expose fine-grained physical access and update units inside each node. If the real cost is bytes transferred and cross-network coordination, then it is worth spending extra local CPU on hashing, short unsorted scans, and pointer arithmetic instead of shipping entire `1 KB` pages or serializing every writer behind one exclusive lock.

That idea lets Deft keep the shallow-tree advantage of a B+ tree without accepting the normal per-node I/O and locking costs. Once point operations become entry-granular rather than node-granular, exclusive mode can be reserved for structural changes, and lock-free search becomes practical with a lighter validation scheme.

## Design

Leaves are hash-based. A leaf still covers an ordered key range, but stores entries in buckets chosen by hash. Two main buckets share one overflow bucket, and a point lookup fetches only the relevant bucket pair with one `RDMA_READ`, cutting the remote read granularity from `1 KB` to `128 bytes` in the current implementation. Updates change only the value with `8-byte RDMA_CAS`; inserts use extended `RDMA_CAS` to place a whole entry atomically when possible. A leaf splits only when both a main bucket and its overflow bucket are full.

Internal nodes keep the same `1 KB` size but are divided into key-range sub-nodes, typically `4` of them. Entries inside a sub-node are unsorted except that the largest key stays in the rightmost slot. Search computes the target range, fetches only that sub-node, and uses granularity bits stored in the child pointer to infer the next slice without extra pointers. If a sub-node fills, Deft first merges adjacent sub-nodes; only a full internal node triggers a normal split.

Concurrency is organized around shared-mode upserts. Writers acquire a shared lock and attempt update or insert directly with `(extended) RDMA_CAS`; only structural modification operations upgrade to exclusive mode. The `64-bit` one-sided SX lock is implemented with masked `RDMA_FAA`, so uncontended shared or exclusive acquisition usually costs one round trip. For lock-free search, OPDV stores data-side versions in the child node and moves the commit version into the parent pointer, letting readers validate consistency along the search path without a third read or a whole-node rewrite.

## Evaluation

The prototype runs on a `10`-server cluster with `18`-core Xeon `6240M` CPUs, `96 GB` DRAM, and `100 Gbps` ConnectX-5 NICs. The main YCSB study uses `2` memory nodes, `10` compute nodes, `400 million` keys, `8-byte` keys and values, and `1 GB` of index cache per CN. Baselines are Sherman, a corrected checksum-based Sherman-C, SMART, and dLSM.

The results support the paper’s main claim for point workloads. On skewed YCSB-A, Deft reaches `42.7 Mops/s`, beating dLSM, Sherman, Sherman-C, and SMART by up to `3.7x`, `6.1x`, `9.5x`, and `1.3x`. On skewed YCSB-C, it reaches `91.0 Mops/s`, ahead of dLSM, Sherman, and SMART by up to `34.2x`, `3.7x`, and `2.2x`. The ablation is also convincing: with cache enabled, OPDV adds `46%`, scalable concurrency coordination adds `2.5x`, and hash-based leaves add `2.1x`; with cache disabled, segmented internal nodes add `56%`. The main caveat is scans: on YCSB-E, Deft is only similar to Sherman because it still fetches whole leaves for scans and its leaf layout is unsorted.

## Novelty & Impact

Deft’s main novelty is the node-layout decision: keep B+ tree fanout large, but stop treating node size as the unit of remote access and synchronization. That puts it between Sherman’s large-page B+ tree and SMART’s finer but taller radix tree. The paper’s broader lesson is useful beyond this prototype: on disaggregated memory, extra local computation inside a node is often a good trade if it removes bytes on the wire and exclusive-lock retries.

## Limitations

Deft is strongest on point lookups and updates, not on every ordered-index task. On YCSB-E it is only similar to Sherman because scans still fetch whole leaves and search unsorted entries. The design also leans on Mellanox masked and extended atomics, forces deletes into exclusive mode to avoid duplicate-key races, and defers crash recovery to future work. Performance also drops once keys exceed `64 bytes`, and large-value Twitter storage workloads shrink the win over Sherman to about `20.2%` because value transfer, rather than index traversal, becomes the bottleneck.

## Related Work

- _Wang et al. (SIGMOD '22)_ - Sherman is the closest B+ tree baseline on disaggregated memory; Deft keeps the shallow-tree goal but reduces per-node I/O and relaxes exclusive-lock dependence.
- _Luo et al. (OSDI '23)_ - SMART uses an adaptive radix tree to get fine-grained remote accesses, while Deft tries to obtain similar granularity inside a shallower B+ tree.
- _Wang et al. (ICDE '23)_ - dLSM wins inserts through batching and range sharding, whereas Deft targets ordered point operations without multi-SSTable reads or client-side sharding.
- _Li et al. (FAST '23)_ - ROLEX uses a learned front-end over disaggregated memory; Deft stays tree-based but attacks the same DM bottlenecks of bandwidth waste and write-side coordination.

## My Notes

<!-- empty; left for the human reader -->

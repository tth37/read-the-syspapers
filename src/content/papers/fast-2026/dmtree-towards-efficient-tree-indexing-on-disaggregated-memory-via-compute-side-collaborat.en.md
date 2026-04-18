---
title: "DMTree: Towards Efficient Tree Indexing on Disaggregated Memory via Compute-side Collaborative Design"
oneline: "DMTree moves fingerprint lookup and leaf locking from memory servers to peer compute servers so a disaggregated-memory tree index can balance RDMA bandwidth and IOPS."
authors:
  - "Guoli Wei"
  - "Yongkun Li"
  - "Haoze Song"
  - "Tao Li"
  - "Lulu Yao"
  - "Yinlong Xu"
  - "Heming Cui"
affiliations:
  - "University of Science and Technology of China"
  - "The University of Hong Kong"
  - "Anhui Provincial Key Laboratory of High Performance Computing, USTC"
conference: fast-2026
category: indexes-and-data-placement
code_url: "https://github.com/muouim/DMTree"
tags:
  - disaggregation
  - memory
  - rdma
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

DMTree is a disaggregated-memory tree index that keeps the leaf data on memory servers but moves the fine-grained metadata path to compute servers. Its main move is to store fingerprint tables and leaf locks collaboratively on peer compute nodes, so the memory server mostly serves the bulk key-value reads and writes that actually need remote memory. On the authors' 100 Gbps RDMA cluster, that gives up to `5.7x` higher throughput than prior DM range indexes while staying strong on both point operations and scans.

## Problem

The paper starts from a real tension in disaggregated memory. Compute servers have many cores but little memory; memory servers have large memory but little CPU. One-sided RDMA makes that architecture attractive, but it also makes index design unusually sensitive to two different bottlenecks: RDMA bandwidth and RDMA IOPS on the memory side.

Existing designs each solve only half of the problem. B+-tree-style and learned indexes such as Sherman and ROLEX keep leaf entries in contiguous ranges, which is good for scans, but they still have to fetch an entire leaf to read or update one entry. That creates read amplification and burns bandwidth. ART-style designs such as SMART do the opposite: they locate a single entry precisely and avoid read amplification on point lookups, but scans and inserts now require many small RDMA operations, so IOPS becomes the limiter. Hybrid designs like CHIME and FP-B+-tree combine contiguous leaf storage with fingerprint- or hash-based in-leaf locating, but they still send extra RDMA requests to the memory server for fingerprint-table access and leaf-node locking. The result is that the supposedly "small" control-path metadata becomes the source of the bottleneck.

The paper's argument is that this is a placement mistake, not just an algorithmic one. The memory server is already the aggregation point for requests from many compute servers, so it bottlenecks first, while RDMA resources between compute servers remain underused. A good DM index therefore needs to move the high-IOPS control path away from the memory server without giving up the scan-friendly layout of a tree.

## Key Insight

The central claim is that a DM index should split its work by resource type. Bulk key-value storage belongs on memory servers because that is where the large leaf data lives. But precise locating metadata and short-lived lock state are tiny, frequently touched, and IOPS-heavy, so they should live on compute servers and be shared collaboratively across them.

That reframes the design space. Instead of choosing between contiguous leaves that waste bandwidth and precise leaves that waste IOPS, DMTree keeps contiguous leaves for range efficiency while offloading the metadata accesses that make those leaves expensive for point operations. The design works because fingerprint tables are small enough to replicate and synchronize on compute nodes, and because optimistic version checking can repair temporary inconsistency more cheaply than forcing strict synchronous coherence on every update.

## Design

DMTree keeps the FP-B+-tree style overall shape. Internal nodes point to child nodes; leaf nodes store a contiguous range of key-value entries plus a fingerprint table that lets the system locate one entry inside the leaf without reading the whole leaf for every point query. Each leaf also keeps metadata such as `Kmin`, `Kmax`, a right-sibling pointer, a version, and CRC or lock fields used for correctness.

The first major mechanism is a two-part cache on the compute side. Each compute server keeps a private internal-tree cache, but only for the bottom-level internal nodes; upper levels are reconstructed locally to simplify coherence. More importantly, fingerprint tables are no longer fetched from the memory server as ordinary remote metadata. Every leaf's fingerprint table has one primary copy on a compute server and may be cached on others. A server that wants to search or update a leaf first consults its local cache to find the leaf and then reads the fingerprint table from a peer compute server, not from the memory server. DMTree assigns the primary owner through consistent hashing on the fingerprint-table offset, which also gives it a basic load-spreading story as the number of compute servers changes.

The second mechanism is consistency verification. Collaborative fingerprints are updated asynchronously in caches, so a stale cached fingerprint can mis-locate an entry or hide a newly inserted one. DMTree handles that optimistically. If the cached fingerprint says a key should be present but the fetched key-value entry does not match, or if the fingerprint is missing when the key may still exist, the server fetches the primary fingerprint table from the responsible compute peer and refreshes its cache. To keep the private internal cache coherent with remote leaf structure, DMTree stores version IDs in internal entries, leaf nodes, and fingerprint tables. When a leaf splits, merges, or changes range, the version changes; a mismatch invalidates the stale cached internal entry and forces a remote re-traversal. CRC checks play a similar role for read-write races.

The third mechanism is collaborative locking. Prior DM indexes optimized conflicted locking, but the paper argues that even non-conflicted lock and unlock operations still consume too much memory-side IOPS. DMTree therefore stores leaf-node lock fields alongside the primary fingerprint tables on compute servers. Writers acquire locks with `RDMA_CAS` against compute peers, update the remote leaf entry on the memory server, and then unlock. For inserts, DMTree embeds unlock into the fingerprint-table write-back so one `RDMA_WRITE` both persists the updated fingerprint metadata and releases the lock. On the data path, DMTree also uses the fingerprint table to filter empty slots during scans, avoiding wasteful reads of unwritten entries, and it batches concurrent requests from the same compute server while capping batch size to avoid pathological tail latency.

## Evaluation

The evaluation is thorough and well matched to the claim. The authors use six compute servers and one memory server, each with two 40-core Xeon Gold CPUs, `128 GB` DRAM, and a `100 Gbps` ConnectX-6 RNIC; the memory server is intentionally limited to one CPU core to reflect the usual DM asymmetry. They preload one billion 32-byte key-value entries, run 100 million operations per experiment, and compare against Sherman, dLSM, ROLEX, SMART, and CHIME.

The headline result is that DMTree gets close to the ideal trade-off on both sides at once. On search-heavy microbenchmarks it matches the "one remote read per lookup" regime and beats Sherman and ROLEX by `4.5-5.2x`, largely by avoiding leaf-level read amplification. On inserts it beats SMART and CHIME by `2.3-3.5x` and beats dLSM by up to `5.7x`, because fingerprint access and locking no longer pile up on the memory server. On scans it outperforms SMART by `3.2x` by keeping range entries contiguous, and it still edges out Sherman and CHIME by `1.1-1.3x` because it can skip empty entries inside leaves. Under YCSB, the same pattern holds: DMTree exceeds Sherman and ROLEX by `3.8-9.7x` on search- and write-intensive mixes, improves over dLSM by `1.4-8.6x`, and is `3.2x` faster than SMART on the scan-heavy workload E.

The overhead story is also credible. Fingerprint traversal adds only about `5%` of search latency, while fingerprint synchronization and traversal together account for `19.4%` of write latency. On each compute server, DMTree needs `5.4 GB` of memory by default, split into `2.3 GB` for the internal-tree cache and `3.1 GB` for collaborative fingerprint storage. That is higher than Sherman and CHIME, but far below SMART's `22.5 GB`. The memory-side metadata overhead is also modest: for one billion 32-byte entries, DMTree uses `60.1 GB` versus Sherman's `54.2 GB`. Importantly, when compute-side cache size drops, SMART loses up to `72%` of search throughput, while DMTree remains stable, which supports the paper's claim that the design is less fragile under realistic memory budgets.

## Novelty & Impact

Relative to Sherman and ROLEX, DMTree's contribution is not a better private cache or a better leaf predictor; it is the decision to relocate the metadata path itself. Relative to SMART, it deliberately accepts contiguous leaves and their coarse storage granularity, but removes the control-path IOPS explosion that usually comes with them. Relative to CHIME and FP-B+-tree, its novelty is to treat fingerprint tables and locks as shared compute-side objects rather than memory-side remote metadata.

That makes the paper a genuine mechanism paper, not just an implementation polish paper. The core idea, "put tiny, hot, coordination-heavy metadata on the peer fabric instead of on the memory server," is likely to matter for other RDMA-based disaggregated-memory structures beyond this exact tree. People building key-value stores, ordered indexes, or transactional data structures on DM will cite it because it gives a reusable systems lesson about where the control plane should live.

## Limitations

The design depends on a specific bottleneck profile: memory servers are the first point of IOPS or bandwidth saturation, while compute-to-compute RDMA remains underused. If a deployment has a different balance, or if future interconnects reduce the penalty of memory-side metadata access, the gains may shrink. The paper argues that CXL still leaves room for the same idea, but that claim is discussed rather than validated experimentally.

DMTree also pays for its wins with control-path complexity. It combines private internal caches, collaboratively placed fingerprint tables, version-based invalidation, optimistic repair, CRC checks, and distributed lock placement. That is a large correctness surface, especially under failures. The paper sketches failure detection and primary re-election for fingerprint tables, but does not evaluate recovery cost or fault scenarios directly. Finally, the evaluation is index-centric and fixed to a single-memory-server setup with mostly 32-byte entries; that is appropriate for isolating the mechanism, but it leaves open how much the benefit survives inside a full application stack or with more heterogeneous memory-server deployments.

## Related Work

- _Wang et al. (SIGMOD '22)_ — Sherman uses a DM-optimized B+-tree with private internal-node caching, but still pays leaf-level read amplification that DMTree avoids with compute-side fingerprints.
- _Li et al. (FAST '23)_ — ROLEX reduces traversal cost with a learned model, yet its point accesses still suffer from bandwidth waste when predicted spans are read remotely.
- _Luo et al. (OSDI '23)_ — SMART's ART layout removes read amplification for point lookups, while DMTree instead keeps contiguous leaves so scans and inserts do not explode into many small RDMA requests.
- _Luo et al. (SOSP '24)_ — CHIME already combines tree layout with in-leaf precise locating, but DMTree goes further by moving fingerprint access and leaf locking off the memory server onto compute peers.

## My Notes

<!-- empty; left for the human reader -->

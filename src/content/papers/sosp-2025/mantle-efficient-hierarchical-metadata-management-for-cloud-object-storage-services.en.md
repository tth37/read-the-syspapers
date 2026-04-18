---
title: "Mantle: Efficient Hierarchical Metadata Management for Cloud Object Storage Services"
oneline: "Mantle splits COSS metadata between a per-namespace IndexNode and shared TafDB, turning deep path lookups into single-RPC reads and hot updates into append-only deltas."
authors:
  - "Jiahao Li"
  - "Biao Cao"
  - "Jielong Jian"
  - "Cheng Li"
  - "Sen Han"
  - "Yiduo Wang"
  - "Yufei Wu"
  - "Kang Chen"
  - "Zhihui Yin"
  - "Qiushi Chen"
  - "Jiwei Xiong"
  - "Jie Zhao"
  - "Fengyuan Liu"
  - "Yan Xing"
  - "Liguo Duan"
  - "Miao Yu"
  - "Ran Zheng"
  - "Feng Wu"
  - "Xianjun Meng"
affiliations:
  - "University of Science and Technology of China"
  - "Baidu (China) Co., Ltd"
  - "Tsinghua University"
  - "Institute of Artificial Intelligence, Hefei Comprehensive National Science Center"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764824"
project_url: "https://mantle-opensource.github.io/"
tags:
  - storage
  - filesystems
  - caching
category: storage-and-databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mantle redesigns cloud object-storage metadata around a per-namespace `IndexNode` and a shared sharded database, `TafDB`. `IndexNode` keeps only lightweight directory access metadata in memory, so deep hierarchical lookups become a single RPC, while `TafDB` stores full metadata at scale. Mantle then removes the remaining update bottlenecks with append-only delta records and local rename-loop detection, reaching up to `1.89M` lookups/s and `58.8K` contended `mkdir` operations/s.

## Problem

The paper starts from a very practical observation: modern cloud object storage services are no longer serving mostly flat, loosely structured blobs. At Baidu, namespaces that back analytics and ML workloads have billions of entries, average directory depths around `11`, maximum depths up to `95`, and peak per-namespace metadata rates in the hundreds of thousands of operations per second. Those workloads repeatedly open deep paths and concurrently create, remove, or rename directories while expensive compute jobs wait on metadata.

The standard COSS design handles hierarchical metadata poorly. A proxy receives a REST request, then resolves the path level by level against a sharded metadata table. Because each level needs the parent inode ID to know which shard holds the next level, path resolution becomes a chain of RPCs with permission checks at every hop. In the paper's measurements, lookup accounts for `89.9%`, `91.2%`, and `63.1%` of the latency of `objstat`, `dirstat`, and `delete`, respectively.

Directory updates are the second bottleneck. Operations such as `mkdir` and cross-directory `dirrename` must update metadata in more than one place, which turns them into distributed transactions when parent directories land on different shards. Under the shared-output-directory pattern common in interactive Spark jobs, throughput for `mkdir` and `dirrename` collapses by `99.7%` and `99.4%` relative to no-conflict cases. Prior distributed-filesystem optimizations do not transfer cleanly because COSS proxies are stateless, APIs are narrow, and clients cannot cooperate in metadata caching or speculation.

## Key Insight

Mantle's key claim is that COSS metadata should separate the metadata that must scale out from the metadata that makes lookups fast. A lookup or rename coordinator does not need full directory state; it mainly needs parent-child structure, IDs, permissions, and a lock bit. If that access metadata lives in a per-namespace in-memory service, while the complete metadata remains in a scalable shared database, path resolution can become a single RPC without giving up large namespace capacity.

That split also changes the update story. Once `IndexNode` holds the authoritative in-memory directory index for one namespace, rename loop detection can be done locally instead of as a distributed search. And once hot directory-attribute updates in `TafDB` stop overwriting the same row in place, most write contention disappears. Mantle therefore attacks lookup latency and update contention with one architectural move rather than with isolated point optimizations.

## Design

Mantle has three pieces: the existing proxy layer, a shared sharded metadata database called `TafDB`, and one `IndexNode` per namespace. `TafDB` stores all metadata for all namespaces. `IndexNode` stores only about `80` bytes per directory: parent directory ID, directory name, directory ID, permissions, and a lock bit. The paper calls this the split between directory access metadata and directory attribute metadata. Lookups and permission checks go to `IndexNode`; scalable object metadata storage and most attribute reads and writes stay in `TafDB`.

Single-RPC lookup is the first mechanism. A proxy sends the whole path to `IndexNode`, which resolves it in memory rather than bouncing across database shards. To keep CPU cost under control, Mantle adds `TopDirPathCache`, which caches only truncated prefixes that stay at least `k` levels away from leaf directories. The idea is that upper prefixes are stable while leaf-adjacent paths are the ones most likely to be renamed. Each cache entry stores the resolved directory ID and the permission mask aggregated along the prefix. The chosen default, `k = 3`, keeps only `12%` of the memory footprint of caching all paths while retaining most of the latency benefit.

Cache coherence is handled by `Invalidator`, which combines a `RemovalList` of directories being modified and a radix-tree `PrefixTree` over cached paths. A lookup first checks whether the requested path overlaps an in-flight modification; if so, it bypasses the cache and walks the index directly. Otherwise, it can start from the cached prefix and resolve only the remaining suffix. Cached results are inserted only if no conflicting modification happened during the lookup. This avoids heavy locking while keeping stale path prefixes from surviving renames and attribute changes.

Mantle also uses the Raft replication group behind `IndexNode` more aggressively than a pure standby design. Followers and learners can serve path resolution after checking the leader's `commitIndex` and waiting until their `applyIndex` catches up, so read throughput is not capped by one node. Cache invalidation metadata is replicated through the Raft log, which keeps followers' local caches coherent enough for these reads.

For updates, Mantle introduces delta records inside `TafDB`. Instead of rewriting a hot parent-directory attribute row in place, a `mkdir` or `rmdir` appends a per-transaction delta keyed by parent ID, a special `/_ATTR` name, and the transaction timestamp. Background compaction later folds those deltas back into the main attribute record. This removes the write-write conflicts that otherwise trigger aborts and retries under contention. Because scanning deltas makes `dirstat` more expensive, the mechanism is enabled selectively when a directory shows sustained contention.

Cross-directory `dirrename` is coordinated through `IndexNode`. The proxy asks `IndexNode` to resolve source and destination paths, set a lock on the source directory, and test whether the destination lies under the source by examining the path from the least common ancestor to the destination. If there is no lock conflict and no loop, the proxy finishes the rename with a distributed transaction that updates both `TafDB` and `IndexTable`. Raft log batching then amortizes `fsync` cost on the `IndexNode` write path. Fault tolerance comes from Raft replication plus request UUIDs that let a new proxy safely resume an interrupted rename.

## Evaluation

The evaluation uses a `53`-server cluster, preloads each system with a `1B`-entry namespace at a `10:1` object-to-directory ratio, and compares Mantle with reimplemented versions of Tectonic, LocoFS, and InfiniFS. The workload mix is broad: mdtest microbenchmarks, Spark analytics, and AI-oriented audio preprocessing. That is enough to test the paper's two central claims separately: lookup-heavy read paths and contention-heavy directory updates.

For object operations and directory reads, Mantle is consistently fastest. The paper summarizes lookup-latency reductions of `83.9-89.0%` versus Tectonic, `80.0-84.2%` versus InfiniFS, and `16.4-74.5%` versus LocoFS, with throughput gains of `2.49-4.30x`, `1.96-3.44x`, and `1.07-2.50x`, respectively. A ten-level path increases Tectonic's lookup latency by `6.82x` and InfiniFS's by `6.4x` relative to a one-level path, while Mantle rises only `1.09x`, which directly supports the paper's claim that single-RPC lookup removes path-depth sensitivity.

For directory modifications, the main story is contention. Mantle reports speedups of `1.20-20.90x` over Tectonic, `1.16-116.00x` over InfiniFS, and `2.87-80.78x` over LocoFS. In large-scale experiments it reaches `58.8K` contended `mkdir` operations/s and `38.0K` `dirrename` operations/s. The ablation study is convincing: `TopDirPathCache` doubles `dirstat` throughput, Raft log batching improves non-conflicting `mkdir`, delta records eliminate most of the failures in contended `dirrename`, and follower reads scale `objstat` to `1.8945M` operations/s with two followers and two learners.

The application results matter most. With data access enabled, Mantle cuts end-to-end completion time for Spark analytics by `73.2%`, `93.3%`, and `63.3%` versus Tectonic, InfiniFS, and LocoFS, and improves audio preprocessing by `47.7%`, `40.1%`, and `38.5%`. The paper also strengthens its case with a production deployment across `19` internal namespaces over more than `1.5` years. The main evaluation caveat is that all baselines are reimplemented because their original systems are not public, so some comparison risk remains even though the authors claim alignment with published results.

## Novelty & Impact

Relative to _Pan et al. (FAST '21)_ on Tectonic, Mantle replaces path-length RPC traversal inside a sharded object-store metadata service with a per-namespace in-memory index that answers the common lookup in one RPC. Relative to _Li et al. (SC '17)_ on LocoFS, it does not simply move all directory logic onto a special node; it keeps only the narrow access metadata there and leaves full metadata in a scalable database. Relative to _Lv et al. (FAST '22)_ on InfiniFS, it avoids speculative parallel lookup and instead makes the normal case fundamentally cheaper.

The broader impact is that Mantle reframes hierarchical object-storage metadata as a split-control-plane problem rather than as a faster database-table problem. That makes it likely to be cited by cloud storage teams and researchers building S3-like services for analytics and AI workloads. This is a new mechanism and architecture paper, not a measurement study: its contribution is the combination of access/attribute metadata splitting, cache-safe single-RPC lookup, and contention-eliminating updates in a design that has already survived production deployment.

## Limitations

Mantle does not eliminate the single-node nature of `IndexNode`; it makes that node efficient enough for current workloads. The paper itself notes that CPU at `IndexNode` is the next scalability bottleneck, and its write throughput is still bounded by one Raft group. The authors' own proof-of-concept with RDMA suggests there is more headroom, but the current system remains sensitive to the efficiency of that central per-namespace service.

The design also relies on workload structure. `TopDirPathCache` works because upper path prefixes are relatively stable and most renames happen near leaves. The paper does not deeply evaluate flatter namespaces or workloads that frequently rename higher-level directories, where the cache hit rate and invalidation cost could look worse. Delta records also trade write scalability for more expensive `dirstat`, which is why the system enables them only selectively.

There are evaluation limits as well. The strongest competitors are reimplemented rather than run from original code. Tectonic is evaluated with relaxed consistency, and metadata caching is discussed largely as an extra experiment rather than as a first-class baseline dimension. Those choices do not invalidate the results, but they mean the exact size of Mantle's lead should be read with some caution.

## Related Work

- _Pan et al. (FAST '21)_ - Tectonic represents the DB-table approach inside cloud object storage; Mantle keeps the scalable database backend but removes multi-round path traversal with `IndexNode`.
- _Li et al. (SC '17)_ - LocoFS also separates directory and object metadata, but its dedicated directory node remains the coordination hotspot that Mantle avoids with a narrower access-metadata split.
- _Lv et al. (FAST '22)_ - InfiniFS accelerates lookup through speculative parallel RPCs and caching, whereas Mantle makes lookup single-RPC and scales reads with followers and learners.
- _Wang et al. (EuroSys '23)_ - CFS shrinks critical sections for distributed file-system metadata, while Mantle targets the COSS setting and adds delta records plus local loop detection for rename-heavy workloads.

## My Notes

<!-- empty; left for the human reader -->

---
title: "OdinANN: Direct Insert for Consistently Stable Performance in Billion-Scale Graph-Based Vector Search"
oneline: "Moves updates from buffered merges to direct on-disk inserts, using GC-free page-local rewrites and approximate concurrency control to stabilize billion-scale vector search."
authors:
  - "Hao Guo"
  - "Youyou Lu"
affiliations:
  - "Tsinghua University"
conference: fast-2026
category: indexes-and-data-placement
tags:
  - storage
  - databases
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

OdinANN argues that on-disk graph ANN indexes should stop buffering inserts in memory and merging them later. Instead, it directly inserts each vector into the on-disk graph, then makes that affordable with GC-free out-of-place updates and approximate concurrency control. The result is a graph index that keeps search latency much steadier under continuous updates without giving up the accuracy advantage of graph navigation.

## Problem

Billion-scale ANN services increasingly operate on datasets that change continuously: product catalogs, fresh embeddings for web search, and RAG corpora all keep adding vectors. Existing on-disk graph indexes handle that with buffered insert: keep new vectors in an in-memory index, search both the memory and disk graphs, and periodically merge the buffered vectors into the on-disk structure. The paper shows that this strategy solves one problem only to create three others.

First, merges visibly disturb the foreground search path. During a merge, the system must traverse the on-disk graph again to find neighbors for buffered vectors, which competes with user queries for SSD bandwidth; on SIFT100M the median search latency rises by `1.54x` during merge. Second, buffered insert is memory-hungry because the system must retain the in-memory index plus buffered disk updates; the paper cites `125 GB` of memory to merge `3%` of vectors into a billion-scale index. Third, batching is less powerful than it looks: the expensive part of merge is still the per-vector neighbor search, so throughput plateaus around `3000 QPS` even with very large batches.

Direct insert seems like the obvious alternative because it spreads update cost over time and removes the bulky in-memory tier. But a naive direct-insert design would be unusable. Every inserted vector changes not only its own record but also tens or hundreds of neighbor records, causing scattered random SSD writes. And because inserts search the graph before updating it, conventional locking would serialize on frequently visited near-root nodes and crush concurrency. The paper is therefore asking a more interesting question than "can we update graph ANN online?": can we make direct insert stable enough that foreground search no longer oscillates whenever the index is updated?

## Key Insight

The core claim is that direct insert becomes practical if the system stops treating exact operation-level isolation as sacred. OdinANN exploits two structural facts about on-disk graph ANN indexes. The first is physical: records are fixed-size, so updated records can be relocated into spare slots on the same page, letting one page write absorb several logical record updates without needing log-structured garbage collection. The second is semantic: ANN search and neighbor selection are already approximate, so inserts and searches do not need a globally consistent graph snapshot; they only need consistent per-record snapshots and a reasonable, approximate neighbor set.

That proposition matters because it reframes the update problem. Buffered insert tries to hide update cost by batching. OdinANN instead reduces the inherent cost of each insert and then relaxes concurrency control so the remaining cost does not block everyone else. The system is not promising exact transactional graph maintenance. It is promising that the approximation budget already tolerated by ANN can be spent on systems concerns, namely fewer writes and shorter critical sections.

## Design

OdinANN keeps the familiar on-disk graph layout: each fixed-size record stores one vector plus up to `R` outgoing neighbor IDs, and DRAM holds PQ-compressed vectors for navigation. Its first major mechanism is GC-free update combining. The system overprovisions disk space so that each page retains free record slots. When an insert updates the new vector and a set of neighbors, OdinANN writes the new versions out of place into those free slots, preferably on the same page, updates an in-memory ID-to-location table, and immediately recycles the old slots. Because the records are fixed-size, nothing needs compaction; the old slots are reusable holes rather than garbage requiring a separate collection pass. The allocation policy prioritizes empty pages, then partially empty pages already visited on the insert's search path, and only then allocates brand-new pages. With the default setting of roughly half-full pages, the paper argues this yields about `2x` space consumption and `2x` write amplification relative to ideal in-place update, but avoids the garbage-collection pathologies of a log-structured design.

The second mechanism is approximate concurrency control. Searches take only per-record locks while reading a record's ID-to-location mapping, which guarantees a consistent snapshot of that record but not of the entire graph. Inserts first search to collect candidate neighbors, accept that this is only an approximate snapshot, then lock the affected records and pages, reload neighbor records to avoid lost updates, and publish the new records. This design intentionally allows a search to miss a record inserted halfway through its traversal or see it only later in the traversal. The paper argues that this is acceptable because approximate graph navigation never depended on serializable execution in the first place.

OdinANN adds two optimizations to shrink the critical path further. It uses a write-back page cache and background I/O thread so that most reloads come from cache and record updates are written back asynchronously rather than synchronously in the locked region. It also replaces DiskANN's `O(R^2)` pruning step with delta pruning: check the newly inserted neighbor against existing neighbors first, and fall back to full pruning only when needed. That pushes most insert-side pruning toward `O(R)` while keeping the same pruning rule. Deletes are handled differently: OdinANN buffers deleted IDs in memory, uses a dynamic candidate pool so deleted nodes can still aid navigation without polluting the returned top-k, and periodically runs a lightweight two-pass merge to rewrite edges around deleted nodes. That split is revealing: the paper is not claiming all updates should be direct, only that inserts are the update type where buffering causes the worst instability.

## Evaluation

The evaluation is well aligned with the claimed target. The authors compare OdinANN with DiskANN and SPFresh on SIFT100M, DEEP100M, and SIFT1B using one server with `2 x 28-core` Xeons, `512 GB` RAM, and a `3.84 TB` SSD. The headline result is stability under concurrent inserts and searches. On SIFT100M, OdinANN's median search-latency fluctuation is only `1.07x`, versus `2.44x` for DiskANN, and its average P50 latency is `13.3%` lower. Tail latency improves more: P90 and P99 are `34.6%` and `19.5%` lower than DiskANN on average. Against SPFresh, OdinANN lowers average P50/P90/P99 by `51.7%`, `36.5%`, and `28.4%` while also preserving higher accuracy.

Throughput and memory tell the same story. On SIFT100M, OdinANN delivers `1.15x` DiskANN's search throughput and `1.99x` SPFresh's, while its peak memory is only `29.3%` of DiskANN's because it eliminates the large in-memory merge state. At billion scale, the system reaches about `5000 QPS` search throughput and `1100 QPS` insert throughput with a steady median search latency around `3 ms`; DiskANN still exceeds `200 GB` of memory even when its merge threshold is cut to `3%`. The breakdown analysis is useful because it separates the paper's ideas: asynchronous I/O trims latency, out-of-place page-local updates drive the large throughput gain, and delta pruning lifts the optimized system to about `2000 QPS` inserts with `11.1 ms` median insert latency.

The paper also surfaces the tradeoff honestly. OdinANN's relaxed update path slightly lowers index quality: after large update runs on DEEP100M, it needs about `4.5%` more page reads than DiskANN to reach the same recall. That is a real cost, but it is much smaller than the stability and memory gains, so the empirical case for direct insert is convincing.

## Novelty & Impact

Relative to _Subramanya et al. (NeurIPS '19)_, OdinANN's novelty is not a new graph-search algorithm but a new update path for on-disk graph indexes. Relative to _Xu et al. (SOSP '23)_, it shows that graph indexes can retain their search-quality advantage over cluster-based updatable systems without inheriting buffered-merge instability. Relative to _Wang et al. (SIGMOD '24)_, which improves disk-resident graph search for mostly static data, OdinANN focuses on the harder online-update regime.

That makes the paper important for vector-database builders and practitioners operating continually refreshed embedding corpora. I expect it to be cited less for its pruning details than for the broader lesson: approximate search structures do not need database-grade isolation everywhere, and spending that slack carefully can buy stable performance at billion scale. This is a new update mechanism, not a new ANN objective or a pure measurement paper.

## Limitations

OdinANN pays real costs for its stability. The most obvious is storage amplification: the default design uses about `2x` disk space, which the authors defend economically against DRAM but which still matters operationally. The concurrency protocol also weakens the graph slightly; the paper measures the quality hit indirectly as extra pages per search, and that gap may grow under workloads that are more adversarial than the SIFT and DEEP insertion sequences studied here.

The delete story is also less elegant than the insert story. Deletes are buffered, not direct, and the merge path may intentionally load only part of each deleted node's neighbor set to meet a memory budget, trading some final accuracy for lower memory use. More broadly, the evaluation stays within a single-node, single-SSD setting. That is the right target for this paper, but it leaves open how well the design behaves with multiple devices, harsher interference, or stronger durability requirements than the paper's journaling scheme discusses.

## Related Work

- _Subramanya et al. (NeurIPS '19)_ — DiskANN established the basic on-disk graph ANN recipe that OdinANN inherits, but it targets mostly static indexes rather than stable online updates.
- _Chen et al. (NeurIPS '21)_ — SPANN represents the cluster-based path to billion-scale ANN, while OdinANN argues that graph indexes can remain updateable without giving up finer-grained search behavior.
- _Xu et al. (SOSP '23)_ — SPFresh adds in-place updates to SPANN, whereas OdinANN tackles the harder neighbor-maintenance problem in graph indexes and wins on latency and accuracy.
- _Wang et al. (SIGMOD '24)_ — Starling improves I/O efficiency for disk-resident graph indexes, and OdinANN is largely orthogonal because it asks how to keep such an index stable while updates continue online.

## My Notes

<!-- empty; left for the human reader -->

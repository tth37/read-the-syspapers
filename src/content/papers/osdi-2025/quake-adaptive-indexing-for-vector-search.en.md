---
title: "Quake: Adaptive Indexing for Vector Search"
oneline: "Quake keeps dynamic vector search fast by splitting and merging hot partitions with a latency cost model, then using geometric recall estimation to stop scanning as soon as a target recall is met."
authors:
  - "Jason Mohoney"
  - "Devesh Sarda"
  - "Mengze Tang"
  - "Shihabur Rahman Chowdhury"
  - "Anil Pacaci"
  - "Ihab F. Ilyas"
  - "Theodoros Rekatsinas"
  - "Shivaram Venkataraman"
affiliations:
  - "University of Wisconsin-Madison"
  - "Apple"
  - "University of Waterloo"
conference: osdi-2025
code_url: "https://github.com/marius-team/quake"
tags:
  - databases
  - ml-systems
  - memory
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Quake is a partitioned ANN index built for vector workloads whose data and query skew keep changing. It continuously reshapes partitions with a latency cost model, picks per-query scan depth with a geometric recall estimator instead of offline tuning, and uses NUMA-aware intra-query parallelism to make partition scans competitive with graph indexes on dynamic workloads.

## Problem

The paper starts from a practical mismatch in vector databases. Graph indexes such as HNSW, DiskANN, and SVS are excellent at static search, but frequent inserts and deletes are expensive because graph rewiring is random-access-heavy and can dominate update cost. Partitioned indexes such as Faiss-IVF and ScaNN are easier to update because writes are mostly append-like and sequential, but they age badly under skew. If some regions become hot or receive many new vectors, partitions become imbalanced, queries must scan more data, and latency rises.

The authors argue that this is not a corner case. Their Wikipedia-derived workload shows both read skew and write skew over 103 monthly updates, with popular entities absorbing disproportionate traffic while new content accumulates unevenly in embedding space. Existing maintenance schemes, such as splitting large partitions or reclustering drifted ones, help only partially because query-time parameters stay static. Once the partition layout changes, the old `nprobe` is often wrong: keep it fixed and recall drops; raise it conservatively and latency rises. The real problem is therefore not just "maintain the index" or just "early terminate the scan," but maintaining low latency at a fixed recall target while both the data and the workload evolve.

## Key Insight

Quake's central claim is that partitioned ANN indexes can remain competitive on dynamic workloads if they adapt two things together: the partition layout and the query's scan budget. The layout should change according to each partition's actual contribution to latency, not just its raw size. The scan budget should then be chosen per query from the current geometry of the index and the intermediate top-k results, rather than by a globally tuned constant.

That combination matters because it preserves the structural advantage of partitioned indexes, namely cheap updates and sequential scans, while directly attacking their two failure modes under drift: hot, oversized partitions and stale `nprobe` settings. The paper's third observation is that the remaining search gap versus graph indexes is largely a memory-bandwidth problem. Once queries are expressed as partition scans, NUMA-aware placement and scheduling can turn much of that cost into local-memory bandwidth instead of remote traffic.

## Design

Quake is a multi-level partitioned index. At the base level, vectors are grouped into disjoint partitions with centroids; higher levels recursively partition those centroids so search can descend top-down rather than compare against every base centroid. Inserts traverse the hierarchy to the nearest leaf partition and append there. Deletes use a map to find the owning partition and compact it immediately.

The maintenance mechanism is the paper's first major contribution. For each partition `(l, j)`, Quake tracks its size and sliding-window access frequency, then estimates its latency contribution as `A_l,j * lambda(s_l,j)`, where `lambda` is an empirically profiled scan-latency function. Total estimated query cost is the sum across all partitions and levels. Quake can split a hot partition, merge a cold small partition, add a hierarchy level when the top level becomes too crowded, or remove one when it becomes too sparse. The important systems move is the decision procedure: estimate, verify, then commit or reject. A tentative split or merge is first scored using lightweight assumptions; after it is executed, Quake measures the actual resulting partition sizes and recomputes the cost delta. If the action no longer improves the model, it is rolled back. This protects the system from pathologies such as an imbalanced split that looked beneficial in expectation but creates one large and one tiny child in reality. After a split, Quake also runs local k-means refinement on nearby partitions to reduce overlap.

The second contribution is Adaptive Partition Scanning (APS). For a query, Quake first considers an initial fraction of candidate partitions, scans the nearest one to establish the current top-k radius, and then estimates the probability that each remaining partition contains a true neighbor. The estimate comes from a geometric approximation: treat the query neighborhood as a hypersphere and approximate how much of that sphere lies inside each partition. APS then scans partitions in descending probability order until the estimated cumulative recall crosses the user target. To keep this cheap, Quake precomputes expensive beta-function values and recomputes probabilities only when the current k-th-neighbor radius shrinks enough to matter. In multi-level indexes, higher levels are searched at a fixed 99% recall target to avoid compounding approximation errors.

The third piece is NUMA-aware execution. Quake distributes partitions across NUMA nodes, binds partitions to worker cores for locality and cache reuse, and lets workers steal only within the same NUMA node. A main thread periodically merges partial top-k results from local workers and asks APS whether enough recall has already been reached; if so, it terminates the remaining scans early. This turns adaptive stopping into a bandwidth-aware parallel execution policy rather than just a single-thread heuristic.

## Evaluation

The implementation is about 7,500 lines of C++ with a Python API. The evaluation is broad enough to test the paper's actual claim rather than a toy setting: a Wikipedia-12M workload built from page additions and page views, an OpenImages-13M workload with both inserts and deletes, synthetic MSTuring workloads, SIFT microbenchmarks, and a 4-socket Xeon server for large-scale NUMA experiments.

The strongest result is on dynamic workloads. On Wikipedia-12M, multi-threaded Quake processes search in `1.53` hours, versus `12.11` for DiskANN and `165.8` for Faiss-IVF; the paper summarizes this as `1.5x-13x` lower search latency than HNSW, DiskANN, and SVS, plus `18x-126x` lower update latency. On OpenImages-13M, Quake-MT needs `0.03` hours of search time versus `0.22` for DiskANN, while graph indexes pay heavily for deletion handling. APS also does what it is supposed to do: on SIFT1M it stays within `17%-29%` of an oracle `nprobe` chooser while requiring no offline tuning, and it matches or beats Auncel, LAET, and SPANN once tuning cost is counted. The NUMA story is credible too. On MSTuring100M, Quake reports roughly `20x` lower query latency than single-threaded execution and `4x` lower latency than a non-NUMA-aware parallel version, peaking near `200 GB/s` scan throughput.

The evaluation is also honest about regime changes. On the static read-only MSTuring10M workload, SVS still wins with `0.33` hours of search time versus Quake-MT's `0.63`. That supports the narrower claim the paper should make: Quake is strongest where the workload is dynamic enough that graph maintenance and static `nprobe` settings become liabilities.

## Novelty & Impact

Compared with _Xu et al. (SOSP '23)_ on SPFresh/LIRE, Quake does not trigger maintenance from size thresholds alone; it uses a latency cost model tied to access frequency and verifies actions before committing them. Compared with _Li et al. (SIGMOD '20)_ on LAET and _Zhang et al. (NSDI '23)_ on Auncel, it avoids per-dataset training or calibration and keeps working even as the index structure itself changes. Compared with _Guo et al. (ICML '20)_ on ScaNN, it treats dynamic maintenance and query adaptivity as first-class design goals rather than assuming a mostly static partition layout.

The impact is practical. Vector databases for recommendation, semantic search, and RAG often want the cheap updates of partitioned indexes but the latency profile of graph indexes. Quake does not invent a new ANN primitive; it shows that a partitioned design can be made workload-adaptive enough to stay competitive in the operating regime many production systems actually face.

## Limitations

Quake is not a universal replacement for graph indexes. The paper's own results show that on static read-heavy workloads, a strong graph implementation such as SVS can still be faster. Its win is tied to dynamic and skewed regimes where maintenance quality and adaptive stopping matter.

The system also still exposes important tuning knobs. The initial candidate fraction `f_M` has the largest effect on APS performance, and the split/merge threshold `tau` controls how aggressively the index evolves. The authors say defaults worked across their workloads, but these are still parameters rather than self-tuning control laws. Finally, the current implementation executes searches, updates, and maintenance serially; the paper explicitly leaves copy-on-write concurrency, filtered search, distributed placement, and compression-aware cost models as future work rather than demonstrated features.

## Related Work

- _Xu et al. (SOSP '23)_ — SPFresh incrementally splits and deletes partitions for streaming vector search, while Quake replaces size-threshold maintenance with a cost model and adds adaptive query-time recall control.
- _Li et al. (SIGMOD '20)_ — LAET learns when to stop scanning per query, whereas Quake uses an analytic recall estimator and avoids offline training.
- _Zhang et al. (NSDI '23)_ — Auncel also uses geometry to reason about recall, but Quake couples recall estimation with index maintenance and argues that Auncel's calibration is too conservative on changing indexes.
- _Guo et al. (ICML '20)_ — ScaNN is a highly optimized partitioned baseline for approximate search, while Quake focuses on preserving that style of index under inserts, deletes, and shifting skew.

## My Notes

<!-- empty; left for the human reader -->

---
title: "PolarStore: High-Performance Data Compression for Large-Scale Cloud-Native Databases"
oneline: "PolarStore combines 16 KB software compression with byte-granular CSD compression and DB-specific fast paths, giving PolarDB a 3.55 ratio and about 60% lower storage cost at scale."
authors:
  - "Qingda Hu"
  - "Xinjun Yang"
  - "Feifei Li"
  - "Junru Li"
  - "Ya Lin"
  - "Yuqi Zhou"
  - "Yicong Zhu"
  - "Rongbiao Xie"
  - "Ling Zhou"
  - "Bin Wu"
  - "Wenchao Zhou"
  - "Junwei Zhang"
affiliations:
  - "Alibaba Cloud Computing"
conference: fast-2026
category: indexes-and-data-placement
tags:
  - storage
  - databases
  - hardware
  - datacenter
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`PolarStore` splits database compression into two layers: software keeps the flexible decisions, while `PolarCSD` keeps byte-granular placement and space reclamation inside the device. That lets PolarDB keep the space efficiency of fine-grained compression without paying the full software indexing cost. With extra fast paths for redo writes and page reads, the deployed system reaches a `3.55` compression ratio and cuts storage cost by about `60%` while staying close to the performance of uncompressed clusters.

## Problem

The paper starts from a cloud-native RDBMS reality: disaggregated compute already makes CPU and memory elastic, so storage becomes the cost users keep paying for even during quiet periods. Compression is the obvious lever, but the familiar software and hardware approaches each fail in a different way. Software compression can choose its algorithm and input size per workload, yet it must also manage variable-length compressed data. That means indexes, rewrites, and space reclamation all become more complicated and can land directly on the latency path of the database.

The authors make this trade-off concrete with a `408.37 GB` dataset. Using `4 KB` index granularity instead of byte-level indexing consumes about `80.5%` more space. Using larger compression inputs helps too: `1 MB` blocks reach a compression ratio of `6.85`, while `4 KB` blocks reach only `3.59`. More advanced algorithms also help. But those same choices raise I/O amplification or decompression cost. Hardware compression goes the other direction: it removes much of the CPU overhead, but existing CSD and accelerator designs usually lock the system into fixed `4 KB` inputs or fixed algorithms, which is a poor fit for a database whose hot pages, cold pages, logs, and archive data have very different needs.

## Key Insight

The paper's main claim is that compression responsibility should be split along the storage-stack boundary. The software layer should keep only the flexible parts of the problem: choose algorithms, choose input sizes, and package database pages into simple `4 KB`-aligned blocks. The device layer should do the byte-granular placement, space accounting, and garbage collection that software struggles to do cheaply. In other words, PolarStore treats "flexibility" and "fine-grained indexing" as separate concerns and assigns them to the layers that can implement them best.

The second insight is that not every database I/O deserves the same treatment. The latency-critical operations are redo log writes at commit time and page reads on buffer-pool misses. If those two paths are protected explicitly, the system can afford more expensive compression work off the critical path and still look fast to the user.

## Design

`PolarStore` sits under the disaggregated PolarDB architecture, where one read-write node and multiple read-only nodes share a replicated storage service. In the default path, a storage leader receives a database write, compresses a `16 KB` page into one or more `4 KB`-aligned blocks in software, replicates those compressed blocks with `3`-way Raft, writes them to `PolarCSD`, logs allocator and index updates, and only then makes the new mapping visible. The software space manager is intentionally simple: a centralized allocator manages `128 KB` chunks per device, bitmap allocators manage `4 KB` subregions, and a hash index maps original `16 KB` page addresses to compressed addresses. PolarStore also exposes three write modes: normal compression, no compression for unaligned or designated data, and heavy compression for archival ranges that can be recompressed as a larger segment.

The hardware half is what makes that software simplicity viable. `PolarCSD` exports a standard NVMe interface and implements `gzip` level `5`, but internally extends a page-mapping FTL from fixed-length `4 KB` mappings to variable-length mappings from `4 KB`-aligned LBAs to byte-granular PBAs. The key invariant is that software never needs byte-level free-space management even though the device stores variable-length compressed outputs. That is the core co-design move.

The DB-specific optimizations focus on the two hot paths. Redo logs bypass compression entirely and go to an `Intel Optane` SSD, because commit latency matters more than squeezing a tiny, quickly reclaimed log. Page reads use an adaptive `lz4` versus `zstd` choice decided at write time. If CPU utilization is above `20%`, PolarStore stays with `lz4`; if page updates exceed `30%`, it tries both algorithms and switches to `zstd` only when the saved bytes per extra decompression microsecond exceed `300 B/us`; otherwise it reuses the prior choice. Finally, PolarStore exploits CSD space decoupling to keep a per-page log area: when redo logs fall out of memory, the storage node pre-merges all logs for one page into a dedicated `4 KB` area so a lagging read-only node can regenerate a page with one read instead of several scattered reads. At deployment scale, the authors also redesign `PolarCSD2.0` to move FTL logic back on-device and add compression-aware chunk scheduling so logical and physical space stay balanced across the cluster.

## Evaluation

The production results are the paper's strongest evidence. PolarStore is deployed on thousands of storage servers in PolarDB, manages more than `100 PB`, and in the second-generation `C2` clusters achieves a `3.55` compression ratio. Table 2 translates that into economics: effective cost per logical GB drops to `0.37`, versus `0.91` for the matched uncompressed `P5510` cluster, which is roughly the advertised `60%` cost reduction. On Sysbench, those `C2` clusters reach performance parity with the uncompressed `N2` clusters, while the earlier `C1` deployment with `PolarCSD1.0` still trailed its baseline by about `10%`.

The ablation studies line up well with the authors' bottleneck story. Hardware-only compression already gives `2.12x` to `3.84x` space savings across the tested datasets, and adding software compression improves that by another `21.7%` to `50.3%`. The cost is latency on critical paths: using `zstd` in software slows redo writes enough to cause a `19.6%` throughput drop versus hardware-only compression. Bypassing redo compression cuts that loss to `8.9%`, and the adaptive `lz4`/`zstd` selection reduces it further until throughput is only `2.1%` below the uncompressed baseline. The per-page log experiment is also convincing in its intended regime: when a read-only node lags by about `1 s`, it cuts P95 latency by `28.9%` to `39.5%` at `16` to `128` threads. The evaluation is therefore strongest exactly where the paper claims it should be: I/O-bound, shared-storage database workloads and operational production scale.

## Novelty & Impact

Relative to classic software compression in `InnoDB`, `MyRocks`, or log-structured storage, PolarStore's novelty is not just "compress more." It moves compression into the shared storage layer of a cloud-native RDBMS and divides the job between software flexibility and hardware indexing. Relative to earlier computational-storage work on PolarDB, such as using CSDs for analytical acceleration, this paper repurposes the hardware for an always-on space-efficiency service with database-specific latency protections. That makes the paper useful both to people building cloud database storage engines and to hardware teams trying to justify computational storage with a production-scale, costed deployment story.

## Limitations

PolarStore is not a generic recipe for commodity storage fleets. It depends on custom `PolarCSD` hardware, specialized FTL changes, and a fast side device for redo logs. The heaviest compression mode is only appropriate for archival or snapshot-style data that is read mostly sequentially; the paper is explicit that random access would suffer from the resulting I/O amplification. Several policy thresholds, including the `20%` CPU cutoff, the `30%` update threshold, and the `300 B/us` benefit test, are tuned to the authors' environment, and the paper does not show how robust those thresholds are under different SSD latencies or database page sizes.

There is also an operational caveat. The first-generation deployment exposed real host-level instability from host-managed FTLs, and the final system fixes that by redesigning the hardware rather than by simplifying the software stack. That is a practical success, but it also means the paper demonstrates portability less strongly than it demonstrates deployability inside PolarDB.

## Related Work

- _Verbitski et al. (SIGMOD '17)_ — `Amazon Aurora` established the disaggregated shared-storage RDBMS model that PolarStore targets, but not the compression design for that storage layer.
- _Cao et al. (FAST '20)_ — `POLARDB Meets Computational Storage` uses CSDs to accelerate analytical workloads, whereas PolarStore uses the device as the byte-granular second stage of a production compression pipeline.
- _Qiao et al. (FAST '22)_ — this work narrows the B+-Tree versus LSM-tree write-amplification gap with built-in compression, while PolarStore targets a shared storage service beneath many database instances.
- _Chen et al. (IPDPS '24)_ — `HA-CSD` also coordinates host and SSD compression, but PolarStore adds redo and page-read fast paths plus cluster scheduling for a cloud-native RDBMS deployment.

## My Notes

<!-- empty; left for the human reader -->

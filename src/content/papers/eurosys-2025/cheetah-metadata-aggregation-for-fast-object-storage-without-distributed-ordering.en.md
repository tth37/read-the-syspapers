---
title: "Cheetah: Metadata Aggregation for Fast Object Storage without Distributed Ordering"
oneline: "Cheetah aggregates per-object metadata into MetaX so object stores can write metadata and data in parallel, cutting small-object latency without giving up crash consistency."
authors:
  - "Yiming Zhang"
  - "Li Wang"
  - "Shengyun Liu"
  - "Shun Gai"
  - "Haonan Wang"
  - "Xin Yao"
  - "Meiling Wang"
  - "Kai Chen"
  - "Dongsheng Li"
  - "Jiwu Shu"
affiliations:
  - "Shanghai Key Laboratory of Trusted Data Circulation, Governance and Web3"
  - "NICE XLab, XMU"
  - "KylinSoft"
  - "SJTU"
  - "Huawei Theory Lab"
  - "HKUST"
  - "NUDT"
  - "Tsinghua University"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696080"
tags:
  - storage
  - crash-consistency
  - fault-tolerance
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Cheetah aggregates the per-put metadata into a single MetaX record, writes MetaX atomically on meta servers, and writes object data to raw-block data servers in parallel. For immutable objects, that removes distributed ordering from the critical path while preserving consistency.

## Problem

Directory-based object stores such as Haystack-style systems keep volume metadata on directory servers and offset metadata with the data on storage servers. For a small-object put, crash consistency then forces ordered writes across the client log, the directory metadata, and the data/offset metadata. Deletes are similarly awkward because they bounce between the directory and the data side. For immutable objects from a few KB to a few hundred KB on SSDs, those metadata waits and RPCs dominate the actual data transfer.

Hash-based placement such as Ceph scales better, but growing deployments pay with data migration during expansion. The paper therefore asks for a design that keeps directory-style migration-free growth, removes metadata ordering from the write path, and still recovers cleanly after crashes.

## Key Insight

The key insight is to treat all metadata touched by one put as one record. MetaX bundles the object-to-volume mapping, the in-volume extents, the checksum, and the request log. If MetaX is atomically persisted on meta servers, then data can be replicated in parallel to raw-block data servers; correctness no longer depends on distributed ordering across three components, only on local atomicity of MetaX, delayed visibility until both sides finish, and immutability so a failed put cannot overwrite live state.

To scale that idea, Cheetah lets metadata move but keeps data still. CRUSH maps placement groups to meta servers, while each placement group owns a volume group from which only that group's primary meta server allocates data.

## Design

Cheetah has a Raft-backed manager cluster, meta servers storing MetaX in RocksDB, object-agnostic raw-block data servers, and client proxies. MetaX is maintained through atomic KV updates such as `OBMETA_name`, `PGLOG_pgid_opseq`, and `PXLOG_pxid_reqid`.

A put hashes the object name to a placement group, finds the primary meta server with CRUSH, and asks it for a logical volume and extents. The primary allocates space, replicates and persists MetaX on the meta replicas, and returns the allocation to the proxy. At the same time, the proxy sends the object data plus `lvid/extents` to the data replicas, which write raw blocks directly. The object stays pending until both meta and data replicas acknowledge; only then does the proxy commit and notify the primary to make the object visible. This prevents one get from hitting a finished replica while another hits an unfinished one.

Hybrid PG/VG mapping is what avoids expansion-time migration. CRUSH is used to place metadata by mapping PGs to meta servers, but each PG owns a volume group from which only that PG's primary meta server allocates logical volumes. When meta servers change, PG ownership and metadata may move, but the data volumes inside the corresponding VG do not. Deletes only remove MetaX and clear bitmap bits on meta servers. Recovery uses replicated MetaX, checksums, view numbers, and leases to repair or revoke unfinished puts; the paper claims linearizability per object.

## Evaluation

The experiments use a 15-machine testbed with three client/manager machines, nine data machines, and three meta machines, with three-way replication for both metadata and data. The microbenchmarks focus on 8 KB, 64 KB, and 512 KB objects; the authors explicitly note that systems look similar once objects reach 1 MB and above.

Compared with Haystack, Cheetah cuts mean put latency by up to 2.37x and mean get latency by up to 25%. For 8 KB puts at concurrency 1000, peak throughput is still about 6% higher than Haystack. The ablations support the paper's main story: restoring ordered writes hurts much more than replacing raw-block I/O with a filesystem-backed data path. The reported filesystem penalty is only about 10% for small writes, whereas restoring distributed ordering can cost up to 40% throughput before saturation.

The richer meta service scales linearly as meta machines are added. VG-backed expansion avoids the migration penalty seen in a no-VG variant and the expansion slowdown of Ceph. Metadata recovers within a few seconds after a meta-server failure, disk recovery takes about 16.3 seconds at 24.9 GB/s, and on a three-week production trace Cheetah outperforms Haystack while keeping storage efficiency above 85%.

## Novelty & Impact

Haystack and Tectonic keep per-object write state distributed across services; Cheetah collapses that state into one atomic MetaX record. Ceph uses CRUSH to scale placement; Cheetah adapts CRUSH only for metadata placement and couples it with volume groups so data stays put during expansion. That makes the paper a likely reference for future work on crash-safe metadata paths and write-heavy object storage.

## Limitations

Cheetah's benefits depend on immutable objects and upper-layer unique naming; supporting overwrites would require unique sub-names or two-phase commit. The gains are also concentrated on small objects, since the authors say results converge once bulk data I/O dominates. Finally, synchronous replication, lease/view coordination, and recovery pauses make availability more fragile than the latency results alone suggest.

## Related Work

- _Beaver et al. (OSDI '10)_ - Haystack also uses directory-based placement for object storage, but it keeps volume metadata and offset metadata separate, so puts still require ordered distributed writes.
- _Pan et al. (FAST '21)_ - Tectonic scales metadata through layered sharded services and unifies several storage systems, whereas Cheetah collapses the per-object write path into one MetaX record to optimize small immutable object I/O.
- _Wang et al. (FAST '20)_ - MapX avoids migration for Ceph-RBD and Ceph-FS during expansion, while Cheetah targets object storage and combines migration-free growth with a faster metadata commit path.
- _Weil et al. (OSDI '06)_ - Ceph provides scalable CRUSH-based placement, but Cheetah uses CRUSH only for metadata placement and adds volume groups so expansion does not force data migration.

## My Notes

<!-- empty; left for the human reader -->

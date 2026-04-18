---
title: "DRBoost: Boosting Degraded Read Performance in MSR-Coded Storage Clusters"
oneline: "DRBoost lets MSR-coded object stores reconstruct only needed sub-chunks, using reuse-aware coding and fragmentation-free placement to avoid full-chunk degraded reads."
authors:
  - "Xiao Niu"
  - "Guangyan Zhang"
  - "Zhiyue Li"
  - "Sijie Cai"
affiliations:
  - "Tsinghua University"
conference: fast-2026
category: reliability-and-integrity
tags:
  - storage
  - fault-tolerance
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`DRBoost` argues that MSR-coded object stores lose their theoretical recovery advantage during degraded reads because production systems still reconstruct chunk-sized units for object-sized requests. It introduces partial-chunk reconstruction, a reuse-aware coding layout, and a fragmentation-free storage layout so a degraded read pulls only the sub-chunks it truly needs. In a Ceph-based prototype using `(20,16)` Clay codes, this cuts degraded-read latency by one to two orders of magnitude and often beats comparable RS and LRC deployments.

## Problem

The paper starts from an uncomfortable mismatch between coding theory and storage reality. `MSR` codes minimize repair bandwidth among `MDS` codes, which should make them appealing for reliable object storage. In practice, however, their sub-packetization grows rapidly with stripe width, and real systems choose fairly large sub-chunks to keep disks and SSDs efficient during recovery. The result is very large chunks: for `(20,16)` Clay codes with `16 KB` sub-chunks, the recommended chunk size is already `16 MB`.

That is a bad fit for modern object stores, where many objects are only kilobytes or a few megabytes. The paper cites Alibaba, IBM, and Facebook traces showing that small objects dominate both counts and accesses. Existing MSR-coded systems still treat the chunk as the basic repair unit, so reading one unavailable small object can trigger reconstruction of an entire `16 MB` chunk. Because degraded reads happen not only during permanent failures but also during temporary outages and planned maintenance, this amplification turns into visible tail latency rather than a rare corner case.

The obvious fix is "just reconstruct the needed bytes," but MSR codes make that awkward. Clay-style hop-and-couple layouts interleave objects across codewords, helper sub-chunks depend on which node failed, and naive layouts fragment healthy accesses into many small requests. The paper's problem statement is therefore stronger than "MSR chunks are large": current storage layouts and I/O semantics are fundamentally misaligned with how MSR codes want to repair data.

## Key Insight

The key claim is that degraded reads in MSR-coded storage should be optimized as a data-layout problem, not just a better decoder. `DRBoost` separates two mappings that existing systems collapse together: the `coding layout`, which determines how object bytes participate in MSR coding, and the `storage layout`, which determines how bytes are placed on devices.

Once those two views are separated, the system can make the coding layout reconstruction-friendly without forcing the storage layout to inherit its fragmentation. That enables two kinds of reuse. First, multiple missing sub-chunks can sometimes be reconstructed from the same `sub-stripe`, so one decoding step serves several losses. Second, healthy bytes from the requested object can themselves double as helper data, shrinking additional reads. The paper's deeper insight is that these reuse opportunities are only exposed when object placement is aligned with MSR structure at sub-chunk granularity, yet stored in a device-friendly order.

## Design

The first mechanism is **partial-chunk reconstruction**. DRBoost identifies `sub-stripes`, which are groups of coupled sub-chunks that can be transformed into one uncoupled MDS stripe and therefore repaired independently. During a degraded read, the algorithm first marks which requested sub-chunks are lost, then prioritizes `sub-stripe reuse`: if several lost requested sub-chunks belong to the same sub-stripe, it reconstructs them together. Only after that does it choose additional sub-stripes to maximize `request reuse`, meaning reuse of already-requested healthy data. The authors deliberately use a lightweight heuristic instead of an optimal search because exhaustive comparison across sub-stripe choices would be too expensive online.

The second mechanism is a **reconstruction-friendly coding layout**. A raw sub-stripe is not a good allocation unit because its major and minor roles are asymmetric across chunks. DRBoost therefore defines a `basic layout unit` that groups the major sub-chunks of one sub-stripe while excluding its minor ones. These units are then composed into two larger structures: `balanced layout units`, which spread data evenly across nodes for read parallelism, and `reuse-optimal layout units`, which maximize reuse so reconstruction can avoid pulling extra helper data from data chunks. An allocation sequence over these units gives objects of different sizes a better chance to land on layouts that are either balanced or reuse-optimal instead of being scattered arbitrarily.

The third mechanism is a **fragmentation-free storage layout**. The coding layout that helps degraded reads would, by itself, splinter normal reads into random I/O. DRBoost fixes this by reordering sub-chunks inside each chunk so sub-chunks from the same basic layout unit are contiguous and consecutively allocated units remain adjacent. A deterministic mapping table translates between coding-space and storage-space sub-chunks. Crucially, object metadata stores storage addresses, so normal reads bypass the translation path; only degraded reads translate from storage layout to coding layout, reconstruct, and translate back for actual device I/O.

The implementation follows that design pragmatically. The authors build a C++ prototype using `ISA-L`, integrate it with Ceph, add partial-stripe read and append interfaces, and use a two-phase write path so large-stripe parity updates do not explode write amplification. One telling detail is that partial reconstruction logic still lives largely in the prototype rather than Ceph's native EC module, which matters for deployability.

## Evaluation

The evaluation is built around a Ceph-based prototype on Alibaba Cloud: `30` storage nodes, `10` client nodes, `4 Gbps` networking, `(20,16)` Clay codes, `1024` sub-chunks per chunk, and `16 KB` sub-chunk size. The baseline is not a straw man. The authors modify Ceph's Clay implementation to reconstruct a single chunk instead of a whole stripe and to aggregate objects within a stripe, making the comparison stricter.

On synthetic workloads with object sizes from `64 KB` to `4 MB`, degraded reads are where DRBoost clearly lands its punch. Mean degraded-read latency improves by `11.7x` to `213x`, and amplification ratio falls by `16.0x` to `156.9x`. Even though degraded reads account for only about `3%` of all reads in the experiment, they dominate service quality enough that overall mean read latency still improves by `2.19x` to `60.7x`, with `P99` improving by `4.65x` to `212x`.

The real-world traces tell the same story with more nuance. Across Alibaba, IBM, Facebook photo, and Facebook video object-size distributions, DRBoost lowers mean degraded-read latency by `2.45x` to `89.2x` and mean amplification ratio by `24.6x` to `557x`. The biggest wins appear on consistently small objects, while traces containing many stripe-sized objects naturally show smaller relative gains because normal reads are already large. The component study is also persuasive: partial reconstruction gives up to `72.3x` speedup on small objects, the coding layout adds another `2.95x` to `4.90x`, and the storage layout removes the normal-read penalty that the coding layout alone would introduce.

The paper also checks the broader regime. As code width grows, both baseline and DRBoost slow down, but DRBoost degrades much more gently because chunk growth hurts full-chunk reconstruction more than partial reconstruction. Against scalar codes with the same default `(20,16)` setting, DRBoost is comparable to LRC for tiny `4 KB` Alibaba objects, but otherwise improves degraded-read latency by `1.62x` to `3.12x` over `RS` and `1.52x` to `1.80x` over `LRC`.

## Novelty & Impact

Relative to _Li et al. (FAST '23)_ on `ParaRC`, this paper is not about parallelizing full-node MSR repair; it targets object-sized degraded reads and gives them first-class semantics. Relative to _Shan et al. (SOSP '21)_ on `Geometric Partitioning`, it does not rely on geometric chunk classes for large objects, but instead introduces a general partial-chunk path plus layout control. Relative to _Ma et al. (MSST '24)_ on `G-Clay`, which improves continuity for full-chunk recovery, DRBoost attacks the more basic problem that the system should often not be reconstructing a full chunk at all.

That makes the contribution more than an implementation hack. The paper reframes MSR codes as viable not just for cold, bandwidth-efficient durability, but also for latency-sensitive warm object storage where degraded reads matter to user-facing QoS.

## Limitations

The paper's strongest limitation is scope. The design is implemented and evaluated for Clay-style coupled-layer MSR codes; the authors argue the ideas extend to many optimal-access MSR families, but direct applicability is not universal. The current implementation also reconstructs at sub-chunk granularity, which is why `4 KB` objects remain only comparable to `LRC` in one trace rather than clearly better.

There are also systems concerns that the evaluation only partially covers. The write path is more complex because DRBoost needs two-phase writes, object aggregation, and stripe recycling. The prototype integration into Ceph is incomplete in the sense that the core partial-reconstruction logic remains outside Ceph's EC module. Finally, the evaluation focuses on single-failure degraded reads and latency, not on interactions with concurrent rebuild traffic, multi-failure scenarios, or long-running operational overheads from the extra layout machinery.

## Related Work

- _Vajha et al. (FAST '18)_ — `Clay codes` supply the flexible low-field MSR construction that DRBoost builds on, while this paper contributes system-level read and layout optimizations rather than a new code.
- _Shan et al. (SOSP '21)_ — `Geometric Partitioning` reduces MSR I/O amplification by using stripes with geometrically scaled chunk sizes, whereas DRBoost keeps one coding scheme and introduces partial-chunk reconstruction plus dual layouts.
- _Li et al. (FAST '23)_ — `ParaRC` parallelizes sub-chunk repair during full-chunk recovery, while DRBoost focuses on object-sized degraded reads where reconstructing the whole chunk is already the wrong unit.
- _Ma et al. (MSST '24)_ — `G-Clay` reorganizes Clay sub-chunk positions to improve disk continuity for recovery, while DRBoost adds reuse-aware object placement and explicit coding-to-storage translation.

## My Notes

<!-- empty; left for the human reader -->

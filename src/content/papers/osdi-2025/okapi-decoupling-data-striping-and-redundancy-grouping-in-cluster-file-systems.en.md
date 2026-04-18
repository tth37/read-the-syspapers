---
title: "Okapi: Decoupling Data Striping and Redundancy Grouping in Cluster File Systems"
oneline: "Okapi lets cluster file systems choose stripe width for IO efficiency and erasure-code group width for durability independently, cutting seeks and transition IO without rewriting data."
authors:
  - "Sanjith Athlur"
  - "Timothy Kim"
  - "Saurabh Kadekodi"
  - "Francisco Maturana"
  - "Xavier Ramos"
  - "Arif Merchant"
  - "K. V. Rashmi"
  - "Gregory R. Ganger"
affiliations:
  - "Carnegie Mellon University"
  - "Google"
conference: osdi-2025
code_url: "https://github.com/Thesys-lab/okapi"
tags:
  - filesystems
  - storage
  - fault-tolerance
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Okapi separates striping from erasure-code grouping. It stripes for read behavior, groups consecutive blocks for durability, and uses inferred groups plus partial parities to make that practical. In HDFS, it raises read throughput by up to 80% and cuts transition IO roughly in half with less than 1% Namenode heap growth.

## Problem

The paper studies HDD-backed cluster file systems where cold data is erasure-coded. In systems such as HDFS, Ceph, Lustre, and Colossus, the same `k` determines both stripe width and redundancy-group width. Stripe width is about performance: narrow stripes help small and mid-sized reads, while wide stripes help huge sequential reads. Group width is about storage overhead, repair cost, and reliability.

Coupling also makes EC transitions expensive. When a file changes code as it cools or as disk failure rates change, the system must recompute parity and re-stripe the file, which means rewriting all data blocks. The paper argues this is no longer rare: large clusters perform many such transitions, and HDD IO is increasingly scarce relative to capacity.

## Key Insight

Okapi's key claim is that striping and redundancy grouping do not need to share boundaries. A file can be striped for the common-case read pattern while parity is computed over a different sequence of blocks chosen for durability goals, as long as both stripes and groups respect failure-domain placement.

The practical trick is to define redundancy groups over consecutive data blocks of the file. If blocks are logically numbered, block `x` belongs to stripe `ceil(x / stripe_width)` and group `ceil(x / group_width)`. Group membership can therefore be inferred from the existing stripe map instead of stored separately.

## Design

Okapi keeps the normal block-and-cell layout of a striped DFS: files are split into fixed-size blocks and 1 MB cells are round-robined across the blocks in a stripe. The difference is that parity is computed over every consecutive `k` data blocks of the file, even when those blocks cross stripe boundaries.

The main implementation issue is metadata. Okapi splits HDFS's striped block group into a data-stripe object and a parity-group object, then infers the mapping between them from stripe width and EC scheme. The next issue is file creation: because multiple groups may be incomplete at once, naive buffering could be large when group width exceeds stripe width. Okapi instead computes partial parities as each data block arrives, buffers those partial results, and combines them later into final parity blocks.

Degraded reads and transitions are the last challenge. A missing block may require reconstruction data that is not aligned with the requested stripe, so Okapi caches reconstruction inputs during degraded reads. For EC transitions, it recomputes parity over new consecutive groups while leaving data striping unchanged, so only parity must be rewritten unless failure-domain constraints force relocation.

## Evaluation

The prototype is implemented in HDFS and evaluated on a 20-node HDD cluster with 8 MB blocks, 1 MB cells, and 40 GbE networking. With 6-of-9 grouping fixed, choosing stripe width to match request size improves read throughput by up to 80% relative to coupled 6-wide striping and cuts seeks per second by up to 70%. For 12-of-15 codes, the paper reports up to 115% higher throughput.

On a Google-derived read-only trace, Okapi improves sustained throughput by 55%, reduces total seeks by 65%, and completes the workload 36% faster. Transition costs also drop sharply: for 1 GB files moving between 6-of-9 and wider codes, regrouping cuts disk and network IO by about half versus read-re-encode-write. The paper's Google emergency scenario shows roughly 45% less total transition IO, and a Backblaze-driven simulation shows about 38% lower mean transition IO.

The overhead numbers are modest. Okapi increases total Namenode heap by only 0.74%, keeps normal read and write throughput roughly unchanged when stripe and group widths match, and uses partial parities to keep write buffering bounded. The main downside is degraded mode: a poorly chosen stripe/group combination can make a 24 MB degraded read 33% slower than the coupled case.

## Novelty & Impact

The novelty is not a better code but a better abstraction. Okapi turns stripe width into a pure performance knob and leaves group width as the durability and capacity knob. That separation seems simple in hindsight, yet most deployed DFS designs and many redundancy-management systems still inherit the older coupling.

Its impact is operational as much as architectural. For DFS designers, the paper shows that an HDFS-like system can be retrofitted with decoupling at small metadata cost. For adaptive-redundancy work, it makes transitions cheaper by removing the need to rewrite file data.

## Limitations

Okapi is most compelling for HDFS-style workloads: sequential writes, mostly immutable files, and many later reads. The case is much weaker for mutable storage or SSD-heavy deployments where seek cost is not dominant. It also does not remove the need to benchmark stripe width; bad choices can still hurt both normal and degraded reads.

The paper's degraded-read results show the trade-off clearly: some decoupled stripe/group combinations increase tail latency enough that an operator might prefer a less throughput-optimal stripe width. Regrouping can also require block relocation to maintain failure-domain separation, and the evaluation is a prototype study rather than a production deployment report.

## Related Work

- _Shvachko et al. (MSST '10)_ - HDFS is the coupled baseline Okapi modifies and the proof that decoupling can fit into an existing DFS architecture.
- _Kadekodi et al. (FAST '19)_ - HeART motivates changing redundancy with disk reliability; Okapi reduces the read-path and transition penalties of doing so.
- _Kadekodi et al. (OSDI '22)_ - Tiger adapts redundancy without placement restrictions, while Okapi makes such group-width changes cheaper in striped DFSs.
- _Kim et al. (SOSP '24)_ - Morph reduces parity-conversion work, and Okapi complements it by eliminating the need to rewrite file data during transitions.

## My Notes

<!-- empty; left for the human reader -->

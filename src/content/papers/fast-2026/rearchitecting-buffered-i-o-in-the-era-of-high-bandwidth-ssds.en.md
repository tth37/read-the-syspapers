---
title: "Rearchitecting Buffered I/O in the Era of High-Bandwidth SSDs"
oneline: "WSBuffer replaces page-cache-all-the-way writes with a scrap buffer plus aligned direct SSD writes, removing partial-write read-before-write and scaling buffered I/O on fast SSD arrays."
authors:
  - "Yekang Zhan"
  - "Tianze Wang"
  - "Zheng Peng"
  - "Haichuan Hu"
  - "Jiahao Wu"
  - "Xiangrui Yang"
  - "Qiang Cao"
  - "Hong Jiang"
  - "Jie Yao"
affiliations:
  - "Huazhong University of Science and Technology"
  - "University of Texas at Arlington"
conference: fast-2026
category: flash-and-emerging-devices
tags:
  - storage
  - filesystems
  - kernel
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`WSBuffer` keeps the buffered-I/O interface but stops forcing every write through page cache. It buffers only small, unaligned, and partial-page fragments in a new `scrap buffer`, sends large aligned regions directly to SSDs, and flushes scraps opportunistically in the background. On eight PCIe 4.0 SSDs, that yields up to `3.91x` higher throughput and `82.80x` lower write latency than Linux file systems and `ScaleCache`.

## Problem

The paper argues that buffered I/O is no longer automatically the fastest or safest default on modern SSD arrays. Direct I/O now beats buffered I/O on large writes even though DRAM bandwidth is still higher, because page-cache management itself has become expensive: page allocation, XArray lookup and updates, dirty-state maintenance, and LRU management all sit on the write critical path. The authors show that with eight PCIe 4.0 SSDs, direct I/O scales toward the array's roughly `55 GB/s` bandwidth while buffered I/O does not.

The second problem is memory pressure. Under heavy writes, page cache must both absorb incoming data and flush it out quickly enough to make room for more. In practice, the required page-state updates and tree mutations serialize on non-scalable locks, so throughput drops sharply as available memory shrinks. The third problem is partial-page writes: if a write misses in page cache and touches only part of a page, legacy buffered I/O must first read the old page from SSD, then modify it, so partial writes become `1.51x-84.37x` slower than corresponding full-page writes.

Prior work either optimizes page cache, such as `ScaleCache`, or bypasses it with direct or hybrid I/O. The paper's criticism is that the first camp still keeps full buffering on the critical path, while the second gives up buffered I/O's transparent semantics and alignment-free programming model.

## Key Insight

The central proposition is that buffered I/O should buffer only the parts of writes that SSDs handle poorly, not every byte of every write. If small and unaligned fragments are absorbed in memory while large aligned regions go straight to SSDs, the system can exploit SSD bandwidth without exposing direct-I/O constraints to applications.

That requires one crucial invariant: dirty write data and clean read cache must be separated. In `WSBuffer`, the newest unwritten fragments live in scrap-pages, committed aligned data lives on SSDs, and ordinary page-cache pages are always clean and used only for reads. Once page cache is removed from write buffering, both the partial-write penalty and much of the write-side metadata contention become tractable.

## Design

`WSBuffer` introduces a `scrap buffer` made of `scrap-pages`. A default scrap-page has a `128 B` header and a `256 KB` data zone. The header records byte count, segment count, target SSD, page state, and up to `15` segment descriptors, so multiple small or overlapping writes can be merged into one page without first reading old data from SSD. To reduce fragmentation and copy overhead, the system allocates `32` scrap-pages at a time and stores headers separately from data zones.

The write path uses a `1 MB` threshold. Requests smaller than that go entirely into the scrap buffer. Larger requests are split into partial-scrap-page edges and a `256 KB`-aligned middle. The edges are buffered in scrap-pages, while the aligned middle is written directly to SSDs. This alignment choice is deliberate: it keeps file layout in large contiguous chunks, avoids future fragmentation, and makes later flushing of full scrap-pages straightforward. If a direct SSD write overwrites data already cached in scrap-pages or read-only memory-pages, those stale entries are reclaimed in the background.

Reads first consult the scrap buffer and then fall back to normal page-cache reads for the rest. This keeps data consistency simpler than it sounds: scrap-pages always hold the newest dirty data, page-cache pages are always clean, and SSDs hold everything already committed.

Background work is handled by `OTflush`, a two-stage flusher. Stage 1 asynchronously reads missing bytes from SSDs to fill unfilled scrap-pages created by partial writes, so read-before-write latency is moved off the foreground path. Stage 2 writes full scrap-pages back to SSDs. Both stages are SSD-load-aware: each drive maintains a `Bcount` of in-flight bytes, and `OTflush` prefers non-busy devices, using `4 MB` as the default busyness threshold. To reduce lock contention, read-only memory-pages stay in ordinary `XArray`, while scrap-pages use `SXArray`, which delays tree cleanup on deletions and uses per-scrap-page locks for state changes instead of repeatedly taking a global lock.

## Evaluation

The prototype adds about `4500` lines of code to `XFS` on Linux `6.8` and runs on a server with two Xeon Gold `6348` CPUs, `256 GB` of DRAM, and eight Samsung `990 PRO` SSDs in RAID0. The microbenchmarks strongly support the paper's core claim. For full-page writes, `WSBuffer` lowers latency by `1.03x-3.29x`. For partial-page writes, where the architecture matters most, it improves latency by `1.70x-82.80x`. Against a direct-I/O implementation plus read-modify-write and against an `AutoIO`-style hybrid policy, it is still `1.59x-231.28x` faster because it avoids synchronous partial-write repair on the critical path.

The larger benchmarks are also fairly persuasive. With sufficient memory, `WSBuffer` beats baseline file systems by `1.23x-2.51x` on Filebench `Fileserver` and `1.06x-2.84x` on `Varmail`; on read-heavy `Webproxy` it remains above most baselines but is slightly behind `XFS` when flushing is disabled, which the paper attributes to the extra scrap-buffer lookup path. Under limited memory with flushing enabled, the gains widen to `1.23x-4.48x` on `Fileserver` and `1.07x-4.37x` on `Webproxy`, suggesting that reducing write buffering really does free memory for reads.

Real applications follow the same pattern: `1.32x-2.02x` on `YCSB+LevelDB`, `1.09x-4.37x` on `GridGraph` PageRank, and `1.74x-3.09x` on `Nek5000`. CPU utilization falls by `3.2%-28.4%`, and for graph processing and `Nek5000` the fraction of foreground write data that remains in memory is only `0.34%-1.67%`. Overall, the evaluation exercises small writes, large writes, mixed workloads, limited-memory cases, and real applications, so it supports the main architectural claim well.

## Novelty & Impact

Compared with _Pham et al. (EuroSys '24)_ on `ScaleCache` and _Li and Zhang (USENIX ATC '24)_ on `StreamCache`, `WSBuffer` is not another page-cache concurrency optimization. Its novelty is architectural: page cache stops being the universal write buffer and becomes primarily a read cache again.

Compared with _Qian et al. (FAST '24)_ on `AutoIO` and _Zhan et al. (FAST '25)_ on `OrchFS`, the system keeps the buffered-I/O programming model and hides direct SSD use inside the kernel instead of asking applications to reason about alignment or alternate APIs. That makes the paper relevant to kernel file-system developers and storage researchers who want POSIX buffered I/O to remain viable as SSD bandwidth keeps rising.

## Limitations

The evidence is strongest for write-heavy local-SSD workloads on one `XFS`-based prototype. The paper argues that the design is portable to other file systems, but it does not implement those ports, and several important parameters are empirical, including the `1 MB` request threshold, the `256 KB` scrap-page size, and the `4 MB` SSD-busyness threshold.

There are also some fairness and scope caveats. `ScaleCache` is compared on Linux `5.4` while `XFS` and `WSBuffer` run on Linux `6.8`, and the `AutoIO` comparison is a userspace implementation of the principle rather than the original Lustre system. Read-heavy workloads under sufficient memory can still favor well-optimized legacy `XFS`, and durability or crash-consistency reasoning is mostly delegated to the underlying file system rather than analyzed in depth inside `WSBuffer` itself.

## Related Work

- _Pham et al. (EuroSys '24)_ — `ScaleCache` parallelizes page-cache indexing and flushing, while `WSBuffer` reduces how much data needs page-cache buffering in the first place.
- _Li and Zhang (USENIX ATC '24)_ — `StreamCache` revisits page cache for file scanning, whereas `WSBuffer` targets write-heavy buffered I/O and partial-write repair.
- _Qian et al. (FAST '24)_ — `AutoIO` mixes buffered and direct I/O at runtime, while `WSBuffer` preserves buffered-I/O semantics and internalizes the split inside the kernel.
- _Zhan et al. (FAST '25)_ — `OrchFS` uses NVM plus direct I/O to exploit SSD bandwidth, while `WSBuffer` keeps mainstream buffered I/O and changes its write path.

## My Notes

<!-- empty; left for the human reader -->

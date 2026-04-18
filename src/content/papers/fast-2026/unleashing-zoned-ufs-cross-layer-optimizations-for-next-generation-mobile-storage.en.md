---
title: "Unleashing Zoned UFS: Cross-Layer Optimizations for Next-Generation Mobile Storage"
oneline: "ZUFS makes zoned UFS practical on smartphones by combining slot-based device buffering, strict cross-layer write ordering, and proactive F2FS garbage collection."
authors:
  - "Jungae Kim"
  - "Jaegeuk Kim"
  - "Kyu-Jin Cho"
  - "Sungjin Park"
  - "Jinwoo Kim"
  - "Jieun Kim"
  - "Iksung Oh"
  - "Chul Lee"
  - "Bart Van Assche"
  - "Daeho Jeong"
  - "Konstantin Vyshetsky"
  - "Jin-Soo Kim"
affiliations:
  - "SK hynix Inc."
  - "Google"
  - "Seoul National University"
conference: fast-2026
category: flash-and-emerging-devices
tags:
  - storage
  - filesystems
  - kernel
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

This paper turns `ZUFS` from a JEDEC interface into a production mobile storage stack by redesigning the device controller, Linux I/O path, `F2FS`, and Android integration together. On a commercial `Pixel 10 Pro` smartphone, the resulting system keeps random reads stable under fragmentation, sustains more than `2x` higher write throughput than conventional `UFS` in aged conditions, and cuts a `Genshin Impact` verification-and-load phase from `35` to `30` seconds.

## Problem

Conventional `UFS` relies on page-level L2P mappings, but mobile controllers only have a few megabytes of SRAM. As capacities grow, the mapping working set no longer fits, so random reads pay repeated map-cache misses. The paper also shows that fragmentation is already a real field problem: from `10,000` shipped smartphones, about `30%` had fragmentation levels above `0.7`, and some badly fragmented devices appeared even at low utilization.

`ZUFS` looks like the obvious fix because it replaces page-granularity mapping with zone-granularity mapping and forces sequential writes. But the paper argues that simply enabling zones is not enough on phones. The stack must support at least six open zones, preserve write order despite aggressive UFS power management, and cope with `F2FS` garbage collection on very large sections. Without solving those three issues, zoned storage either wastes SRAM, violates correctness, or collapses under GC overhead.

## Key Insight

The central claim is that mobile zoned storage succeeds only when the zone abstraction is enforced as a cross-layer invariant, not as a device-local feature. A smaller mapping table helps, but the real win appears only if the controller can share scarce SRAM across open zones, the kernel and driver never reorder zoned writes, and the filesystem reclaims space before large-zone GC becomes foreground work.

That is why the design keeps the FTL inside the device but changes the contracts around it. Compared with host-heavy approaches such as `ZMS`, the paper's approach is to keep host interfaces standard and push the minimum extra machinery into the controller and the upstream storage stack.

## Design

The device architecture uses `1,056 MB` zones formed across dies and planes of TLC NAND with `16 KB` pages. Instead of a page-level table, `ZUFS` stores an `8`-byte zone mapping entry with a start address and valid-length field. The paper reports that a `1 TB` device needs only about `8 KB` for the full `ZMT`, versus nearly `1 GB` for conventional page mappings, so map metadata can stay resident in SRAM.

To support multiple open zones without reserving a full superpage buffer per zone, the controller adds `ZABM`, centered on a `Scatter-Gather Buffer Manager (SGBM)`. `SGBM` splits reserved SRAM into `4 KB` slots, keeps a slot table per open zone, and flushes as soon as data are sufficient to program either one die (`192 KB`) or a full superpage (`768 KB`). This creates logical per-zone write buffers without dedicating `7 x 768 KB` of SRAM, reduces premature flushes, and lets hotter zones borrow more slots dynamically.

The second part of the design is correctness. The authors replace UFS requeue-on-clock-gate behavior with synchronous ungating in the driver so requests preserve issue order. They also fix three Linux block-layer corner cases that could violate zoned ordering: stale `next_rq` state in `mq-deadline`, `FUA` writes bypassing the ordering path, and I/O priority policies that reorder zoned writes. Finally, they make `F2FS` background GC proactive by introducing zoned knobs such as `gc_no_zoned_gc_percent`, `gc_boost_zoned_gc_percent`, and `reserved_segments`, yielding three modes: `No-GC`, `Normal-GC`, and `Boosted-GC`.

## Evaluation

The evaluation runs on a `Google Pixel 10 Pro` with `12 GB` LPDDR5X, `512 GB` `ZUFS`, Android `16`, and Linux kernel `6.6`. On a clean device, `CUFS` and `ZUFS` deliver similar sequential and random throughput, which is important because it shows the zoned design is not buying wins by sacrificing fresh-device bandwidth.

The advantage appears when scaling or aging the workload. In wide-range random reads, `CUFS` degrades as the access range grows from `4 GB` to `256 GB`, while `ZUFS` stays stable because its zone table fits entirely in SRAM. The gap is largest below `128 KB` request sizes, where map-cache misses dominate `CUFS`. For write buffering, die-level flushing matters: `ZUFS` with a `192 KB` chunk size achieves `26%` higher write throughput than the emulated `ZMS`-style `768 KB` chunk, because it releases slots earlier and pipelines host writes with NAND programming.

Under synthetic fragmentation aging, `CUFS` collapses around the `90th` iteration: write throughput falls to roughly `100 MB/s` and read throughput drops by about `35%`. `ZUFS` still dips when background GC ramps up, but it stays above `200 MB/s` on writes and keeps reads stable because reclamation happens in the background and pauses for user reads. The application results make the storage story tangible. On an aged device, `Genshin Impact` verification plus loading takes `30` seconds on `ZUFS` versus `35` on `CUFS`, and photo-gallery scrolling reduces jank from `0.60%` to `0.26%`, with `20x` fewer fragments per file and `p99` frame time falling from `16 ms` to `11 ms`.

## Novelty & Impact

Relative to _Hwang et al. (USENIX ATC '24)_, this paper refuses to add a host-side reshaping layer or device-specific host policy; it makes zoned UFS work with mostly standard Android and Linux abstractions. Relative to _Bjørling et al. (USENIX ATC '21)_ and later ZNS work, it shows that the hard problem in mobile is not just zone semantics but surviving under UFS-class SRAM, power, and integration constraints.

The practical impact is unusually strong for a systems storage paper. The authors state that these features shipped in the `2025` `Google Pixel 10 Pro` series and describe the work as the first commercial deployment of zoned storage in flagship smartphones. That makes the paper useful both as a design argument and as a deployment report.

## Limitations

The strongest results are in fragmented or aged states; on a clean device, `ZUFS` mostly matches rather than exceeds `CUFS`. That is a reasonable outcome, but it means the value proposition depends on long-term behavior rather than short benchmark wins.

The evaluation is also narrow in some important ways. It is centered on one commercial phone platform and one zone geometry, and while the paper demonstrates throughput, jank, and fragmentation behavior, it does not provide a broad energy or endurance study. The design also requires coordinated firmware, kernel, filesystem, and Android changes, so adoption is much heavier than replacing a single device component.

## Related Work

- _Hwang et al. (USENIX ATC '24)_ - `ZMS` also targets mobile zoned flash, but relies on `IOTailor` and host-visible device policies, while this paper keeps buffering inside the device and stays within JEDEC `ZUFS` semantics.
- _Yan et al. (CCGrid '24)_ - integrates zoned namespaces into `UFS` with a host-side `FTL`, whereas this paper keeps mapping and space management inside the device controller.
- _Bjørling et al. (USENIX ATC '21)_ - introduces `ZNS` as a way to avoid the block-interface tax in server SSDs; this paper adapts the same basic idea to mobile `UFS` constraints and Android integration.
- _Han et al. (OSDI '21)_ - `ZNS+` reduces filesystem GC via in-storage zone compaction, while this paper instead redesigns `F2FS` background GC around large fixed `ZUFS` zones.

## My Notes

<!-- empty; left for the human reader -->

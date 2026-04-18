---
title: "Discard-Based Garbage Collection for Distributed Log-Structured Storage Systems in ByteDance"
oneline: "DisCoGC pairs lightweight discards with periodic compaction to reclaim long stale ranges in ByteStore and cuts ByteDance's production TCO by about 20%."
authors:
  - "Runhua Bian"
  - "Liqiang Zhang"
  - "Jinxin Liu"
  - "Jiacheng Zhang"
  - "Jianong Zhong"
  - "Jiahao Gu"
  - "Hao Guo"
  - "Zhihong Guo"
  - "Yunhao Li"
  - "Fenghao Zhang"
  - "Jiangkun Zhao"
  - "Yangming Chen"
  - "Guojun Li"
  - "Ruwen Fan"
  - "Haijia Shen"
  - "Chengyu Dong"
  - "Yao Wang"
  - "Rui Shi"
  - "Jiwu Shu"
  - "Youyou Lu"
affiliations:
  - "ByteDance"
  - "Tsinghua University"
conference: fast-2026
category: indexes-and-data-placement
tags:
  - storage
  - datacenter
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

This paper argues that compaction is the wrong default garbage-collection primitive for ByteDance's append-only storage stack when workloads create long, quickly overwritten regions. `DisCoGC` makes discard the common case and keeps compaction as a lower-frequency cleanup path, then adds boundary alignment, batching, flow control, and trim-aware filtering so the idea works across ByteDrive, ByteStore, UFS, and commodity SSDs. In production, that reduces total write amplification by `25%` and TCO by about `20%` without hurting latency.

## Problem

ByteDrive and ByteStore form a large distributed block-storage stack for ByteDance, operating at exabyte scale and serving workloads from online services to AI model download, index maintenance, and offline analytics. The storage path is append-only: random writes are converted into appends to `LogFiles`, and stale data is later reclaimed by garbage collection. The original design uses compaction, which copies still-live bytes from old `LogFiles` into new ones and then deletes the old files.

That design creates the paper's central cost problem. If compaction is conservative, stale bytes stay on SSDs and space amplification rises. If compaction is aggressive, the system rewrites more valid data, raising logical write amplification, SSD wear, and contention with foreground I/O. The authors state that this trade-off was already costing ByteDance millions of dollars per month in extra TCO.

Trace analysis shows why the authors believed a different primitive was possible. The `SAR` and offline traces contain large sequential writes and frequent overwrites: after merging adjacent writes, `65%` of `SAR` writes and `55%` of offline writes exceed `256 KiB`. Those patterns leave long contiguous stale regions in `LogFiles`. In principle, discard could reclaim those regions without moving valid data at all. The catch is that the production stack is multilayered. Alignment breaks across EC stripes, compressed blocks, and the UFS allocation unit; frequent discards create metadata churn; punched holes fragment `LogFiles`; and the underlying SSD may not have enough trim IOPS to free space promptly.

## Key Insight

The key proposition is that append-only cloud storage should treat discard, not compaction, as the first-line mechanism for reclaiming garbage whenever invalid data arrives in long contiguous runs. A discard request can reclaim an invalid range in constant time, so it lowers space amplification without paying the usual cost of rewriting live bytes. Compaction should remain in the system, but only as a secondary tool for defragmentation and boundary cleanup.

That claim only works if discard becomes a cross-layer protocol rather than a single API call. The host-visible invalid range must survive translation through `LogFiles`, chunk replicas, UFS clusters, and SSD trim semantics. The paper's real insight is therefore operational: reclaim live-space efficiently with high-frequency discard, but surround it with enough alignment repair and rate control that the multilayer stack does not collapse under metadata updates, fragmentation, or SSD trim bottlenecks.

## Design

The data path starts from ByteDrive's random-write interface and ends in ByteStore's append-only `LogFiles`. Each volume is striped into segments; each segment maps to an active `LogFile` plus sealed old ones; each `LogFile` is split into chunks replicated or EC-encoded across `ChunkServers`; and each `ChunkServer` uses a userspace filesystem whose allocation unit is a cluster of `4 * 4064 B` data sectors. `DisCoGC` inserts discard into that stack from the top down. The `BlockServer` scans the segment `LSM-tree`, finds stale `LogFile` ranges that were not discarded before, issues discard requests through the ByteStore SDK, maps them to chunk replicas, frees the corresponding UFS clusters, and records success to avoid reissuing the same discard.

Two alignment failures dominate the design. `EC loss` happens because discard requests are arbitrary ranges but EC can only discard whole stripes. `Cluster loss` happens because EC packets are aligned to `4 KiB` multiples while UFS allocates in `4 * 4064 B` clusters. The paper's two fixes are clean. First, the `BlockServer` performs boundary extension: if a new discard range touches a previously discarded one, it extends the new range by up to a few MiB so the two ranges overlap slightly and reclaim boundary garbage that would otherwise be stranded. Second, ByteStore makes EC stripes discard-friendly by choosing stripe units of `n * 4 * 4064 B`, aligning stripe boundaries with UFS clusters and eliminating cluster loss.

The next problem is metadata overhead. Every discard updates UFS `MetaPages`, so bursts of discard traffic would compete with foreground I/O. `DisCoGC` therefore batches multiple ranges from the same `LogFile` into one discard request, with up to `64` ranges per batch, and uses a parallelism-aware scheduler that picks the top-`k` segments with the largest pending discard ranges. On top of that, flow control caps discard IOPS so a burst falls back gracefully instead of destabilizing the server.

Because discard creates sparse and fragmented `LogFiles`, compaction does not disappear. The system schedules compaction independently at minute granularity. In the normal mode it picks segments with the highest garbage ratio, where garbage ratio is corrected with an explicit boundary-loss penalty. In a metadata-pressure mode, it instead compacts segments with the most `LogFiles` to reduce fragmentation. At the SSD layer, UFS adds a trim filter and trim merger. The filter avoids issuing trim for tiny ranges, while the merger coalesces adjacent small ranges into larger trims. The implementation also includes a per-segment discard WAL for crash recovery and compressed bitmaps for issued and failed discard ranges, which keeps the extra memory cost under control.

## Evaluation

The production evidence is the strongest part of the paper. On mixed ByteDance workloads, more than `90%` of invalid ranges were larger than `128 KiB`, and more than `70%` exceeded `1 MiB`, exactly the regime where discard should help. In production clusters, the baseline and `DisCoGC` ran at space amplification `1.37` and `1.23`, respectively. Under those conditions, `DisCoGC` cut logical write amplification by `32%`, reduced total write amplification by `25%`, and lowered TCO by about `20%`, while latency and per-TiB bandwidth remained essentially unchanged. Physical write amplification rose by up to `10%`, but the system still wrote fewer total NAND bytes because it avoided copying live data during GC.

The offline replay results explain where the win comes from. The `SAR` trace benefits the most, with estimated TCO reduction above `25%`, because it generates large contiguous garbage from model download and index-update bursts. The online trace benefits the least because its writes stay fragmented, yet the paper still reports `2%-5%` TCO savings even in that unfavorable regime. The authors frame this as robustness: when discard is ineffective, the design can fall back toward compaction-only behavior rather than catastrophically regressing.

The factor analysis is useful because it decomposes the final result. Enabling discard plus flow control lowers logical write amplification by `8.4%-13.9%`. Adding batching removes enough request overhead to save another `2.7%-11.7%`. Boundary extension then contributes another `5.5%-16.1%`, showing that cross-layer misalignment is not a corner case but a material source of lost capacity. The trim study also matters. On SSD model A, plain trim already reduces physical write amplification from `1.4` to `1.3`. On SSD model B, trim IOPS are too low, so the filter and merger are necessary to keep physical write amplification and delete latency within a deployable range. The evaluation therefore supports the main thesis: discard is valuable, but only after the surrounding system is engineered to absorb its secondary effects.

## Novelty & Impact

This is not a new SSD interface paper and not merely a better compaction heuristic. The novelty is a cross-layer garbage-collection scheme that turns discard into the primary reclamation mechanism inside a production distributed append-only storage stack, then makes that choice safe through boundary repair, scheduling, and trim-aware control. Relative to host-managed-flash work, the paper chooses the harder operational constraint of keeping commodity SSDs and an existing cloud stack intact.

That makes the paper likely to matter to practitioners more than to mechanism purists. Storage operators can cite it as evidence that a carefully engineered discard path can buy real TCO in production. Designers of log-structured block, object, and KV systems can reuse the broader lesson that "do less copying" only helps if the entire stack agrees on alignment and rate limits. The paper is therefore both a new mechanism and a deployment study with concrete tuning guidance.

## Limitations

The benefits are highly workload-dependent. The paper is explicit that `SAR` and offline traces are ideal because they create large sequential invalid ranges, while fragmented online workloads gain much less. In other words, `DisCoGC` is not a universal replacement for compaction; it is a better default only when overwrite locality is strong enough.

The design is also tightly coupled to ByteDrive + ByteStore. It relies on changes in the `BlockServer`, ByteStore SDK, UFS layout, EC stripe sizing, and monitoring pipeline. That makes the result more credible as systems work, but it also means the paper does not show a low-effort adoption path for generic storage stacks. Finally, the evaluation mostly compares against ByteDance's own compaction-only baseline. That is the correct operational baseline, but it leaves open how `DisCoGC` would compare with more radical alternatives such as host-managed flash or a redesigned upper-layer allocator.

## Related Work

- _Lu et al. (FAST '13)_ - studies write amplification created by filesystem behavior on flash, while `DisCoGC` pushes the problem into a distributed append-only storage stack and solves it with coordinated discard plus compaction.
- _Bjørling et al. (FAST '17)_ - `LightNVM` exposes open-channel SSD control so the host can own garbage collection directly, whereas `DisCoGC` keeps commodity SSDs and works through the existing discard/trim interface.
- _Lu et al. (ICDCS '19)_ - `OCStore` co-designs distributed object storage with open-channel SSDs, while this paper targets ByteDrive + ByteStore on standard SSDs and focuses on reclaiming stale ranges without moving valid data.
- _Kim et al. (ATC '22)_ - `IPLFS` uses discard to abandon stale space in a local log-structured filesystem, whereas `DisCoGC` handles EC alignment, fragmentation, and trim-rate limits across multiple storage layers in production cloud storage.

## My Notes

<!-- empty; left for the human reader -->

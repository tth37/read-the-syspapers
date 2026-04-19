---
title: "Overcoming the Last Mile between Log-Structured File Systems and Persistent Memory via Scatter Logging"
oneline: "SLOT replaces GC-bound contiguous PM logs with per-entry scatter logging, reclaiming invalid slots immediately while buffer-aware heuristics recover most lost locality."
authors:
  - "Yifeng Zhang"
  - "Yanqi Pan"
  - "Hao Huang"
  - "Yuchen Shan"
  - "Wen Xia"
affiliations:
  - "Harbin Institute of Technology, Shenzhen"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717488"
code_url: "https://github.com/HIT-HSSL/slotfs-eurosys"
tags:
  - filesystems
  - persistent-memory
  - crash-consistency
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SLOT removes the garbage-collection tax that PM log-structured file systems still pay for contiguous logs. It scatters metadata log entries into fixed-size slots, commits each entry by checksum instead of a tail pointer, and recovers enough locality with buffer-aware heuristics that SlotFS beats NOVA by 27%-47% on real workloads.

## Problem

LFS fits PM because ordered append gives simple persistence. But current PM LFSes such as NOVA and MadFS still keep logs contiguous at block granularity, so aging logs trigger GC to rebuild appendable space. On PM that bookkeeping becomes visible quickly because the medium itself is already fast.

The motivation numbers are clear. In NOVA, sequential-write GC time grows from 1.5% to 64.0% and bandwidth drops from 988 MiB/s to 341 MiB/s; 1-3 background writers cut foreground throughput by 10.2%-20.1%. Yet simply scattering entries seems to break the usual tail-pointer commit and sequential replay model. The paper's problem is therefore to remove contiguity without losing LFS-style crash consistency.

## Key Insight

The key claim is that PM only needs individual entries to be complete; it does not need long contiguous log segments. A fragmented no-GC NOVA variant loses only 4.5%-9.8% versus append-only, while GC-heavy NOVA loses 59.6%-79.8%, so locality should be treated as an optimization rather than a correctness invariant.

That lets SLOT redefine LFS semantics per entry: checksum for atomic commit, linked-slot traversal to find valid entries, and timestamps to recover logical append order when reused slots scramble physical order.

## Design

SLOT reserves a PM table of fixed-size slots and stores each metadata log entry in one slot. Each slot carries file-system metadata plus `next`, timestamp, and checksum. Invalid entries are either reclaimed by relinking the list and clearing their bitmap bit or reused in place from a per-inode invalid list. Because only metadata is logged, the reserved area is small: about 1%-2% of PM space.

Crash consistency follows from per-entry validation. A torn write fails checksum and is ignored; recovery walks per-inode linked lists and replays entries by timestamp. A DRAM double-linked index accelerates relinking, and a ghost-slot optimization pre-allocates the next slot so appends usually avoid rewriting the old tail.

To recover PM write-buffer efficiency, SLOT adds three heuristics: a best-effort allocator that searches for 64, then 16, then 1 contiguous free slots; a dispatcher that chooses reuse or tail append from I/O size, space utilization, and cacheline size; and an idle-time gather thread that rewrites nearby scattered entries into cacheline-sized sublists. SlotFS packages this design in a userspace PM file system with Hodor isolation and journaling for multi-inode operations.

## Evaluation

The evaluation uses a 16-core Xeon Gold 5218 with `2 x 256 GiB` Optane DCPMM and compares against NOVA, PMFS, SplitFS, ext4-DAX, and MadFS. The cleanest evidence is the 128 GiB GC stress test: for a 128 GiB sequential-write workload, NOVA issues 275.3 GiB of media I/O, including 132.1 GiB of GC traffic, and delivers 393 MiB/s; SlotFS issues 136.7 GiB, spends 0 on GC, and reaches 1845 MiB/s.

On 1 GiB single-thread FIO, SlotFS is fastest on append. At 4 KiB and 16 KiB sequential append it beats competitors by 1.33x-4.21x and 1.27x-2.12x. Overwrite is more nuanced: SlotFS beats NOVA, but in-place systems without full data atomicity can still be faster, and the paper shows that SlotFS-Relax closes that gap once it relaxes atomicity.

The rest of the evaluation is consistent with that story. SlotFS survives hundreds of random-crash recovery rounds, leads FxMark metadata tests, and beats PMFS, NOVA, and SplitFS by 41%, 41%, and 62% on single-thread Fileserver. The main claim is therefore well supported on write-heavy, GC-sensitive paths, with the NOVA comparison being the fairest apples-to-apples one.

## Novelty & Impact

The novelty is not a faster GC but a reason to avoid GC altogether for PM metadata logs. SLOT moves log management from blocks to entries and rebuilds LFS commit and replay rules around that choice. That makes it a useful paper for PM file systems, CXL-persistent tiers, and other log-structured PM systems that still inherit block-era contiguity assumptions.

## Limitations

The wins are not universal. Read-heavy workloads are often near parity, and overwrite under strong atomicity still trails some in-place designs. Part of SlotFS's end-to-end advantage also comes from userspace execution with Hodor, so not every gap to kernel systems is purely a SLOT effect.

The prototype also assumes reserved slot space, DRAM indexes, Optane-era tuning, and a modified software stack. Crash recovery still takes 1.14-1.90 seconds on the evaluated workloads, and the paper leaves heuristic retuning for future PM or CXL devices largely open.

## Related Work

- _Xu and Swanson (FAST '16)_ - NOVA adapts per-inode logging to PM, but it still manages logs at block granularity and pays GC when logs expand; SLOT moves to per-entry slot management and drops the tail-pointer commit model.
- _Kadekodi et al. (SOSP '19)_ - SplitFS cuts PM file-system software overhead with direct data access and selective kernel mediation, whereas SLOT targets the GC and crash-consistency costs inside a log-structured design.
- _Zhong et al. (FAST '23)_ - MadFS compacts and virtualizes per-file logs to reduce GC cost, but cleaning remains fundamental; SLOT argues PM metadata logging should reclaim or reuse entries immediately instead.
- _Zhou et al. (SOSP '23)_ - Trio studies secure userspace NVM file systems with kernel-enforced isolation, while SlotFS uses Hodor for intra-process isolation and contributes a new logging layout rather than a new protection architecture.

## My Notes

<!-- empty; left for the human reader -->

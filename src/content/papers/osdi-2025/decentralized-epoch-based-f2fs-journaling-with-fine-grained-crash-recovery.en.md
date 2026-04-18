---
title: "Decentralized, Epoch-based F2FS Journaling with Fine-grained Crash Recovery"
oneline: "F2FSJ replaces coarse F2FS checkpoints with per-inode metadata-change journals, epoch handoff, and fast-forward apply for lower latency and finer recovery."
authors:
  - "Yaotian Cui"
  - "Zhiqi Wang"
  - "Renhai Chen"
  - "Zili Shao"
affiliations:
  - "The Chinese University of Hong Kong, China"
  - "College of Intelligence and Computing, Tianjin University, China"
conference: osdi-2025
code_url: "https://github.com/10033908/F2FSJ"
tags:
  - filesystems
  - storage
  - crash-consistency
  - kernel
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

F2FSJ replaces F2FS's checkpoint-based crash recovery with ordered metadata-change journaling tailored to out-of-place updates. It keeps logs per inode, switches journal periods via epochs without global stalls, and fast-forwards apply by flushing the latest dirty metadata when that already subsumes older committed logs. On metadata-heavy workloads, journal time is up to 4.9x lower than F2FS checkpoint time and average latency falls by up to 35%.

## Problem

F2FS's flash-friendly layout makes steady-state writes fast, but crash recovery is coarse. A checkpoint is triggered by dirty-metadata thresholds or timeout, then flushes dirty data, inode metadata, and filesystem metadata into a checkpoint pack while blocking writes. In the paper's tests, checkpoint time accounts for roughly 17% to 47% of runtime on metadata-heavy benchmarks, and worst-case checkpoint latency reaches 247 ms, 233 ms, and 293 ms on `create-4KB`, `rmdir`, and `unlink-4KB`.

Between checkpoints, recent state can be lost. With the default 60-second interval, the paper reports up to 9.1% data or metadata loss; shortening the interval to one second reduces loss but raises execution time. F2FS's roll-forward path helps `fsync`, but the paper argues that I/O reordering can still make recovered inode state inconsistent with file data. Ext4-style journaling is also a poor fit: F2FS moves inodes out of place, so journaling only the inode misses NAT/SIT/SSA updates, while journaling full metadata pages doubles I/O and inherits centralized JBD2 locking.

## Key Insight

F2FSJ's key insight is that the right journal unit is a set of per-inode metadata changes, not whole pages. The control plane only tracks which inodes participated in a journal period; the data plane stores the actual change records inside those inodes. That removes the need for one global transaction bottleneck.

The out-of-place-update layout then becomes an advantage during apply. Because older on-disk versions remain intact, F2FSJ can often skip intermediate log records and flush the newest in-memory dirty metadata instead. The paper calls this "fast-forward-to-latest": the latest inode state can safely subsume older committed updates.

## Design

F2FSJ uses ordered journaling: data are flushed first, then only metadata changes are committed. For data-block operations it logs inode changes plus the related filesystem metadata changes, especially SIT and SSA; inode-associated NAT/SIT/SSA information is appended at commit so recovery can rebuild a consistent state without journaling whole pages.

Journal periods are represented by monotonically increasing epochs in `IDLE`, `RUNNING`, or `COMMIT`. Each inode keeps an `e2l_mapping` from epoch to a per-epoch log list. On the first modification in a `RUNNING` epoch, the inode registers once in that epoch and creates a log list; later changes append to the same list. A per-list `J_ticket` counts in-flight operations. On `fsync` or timeout, the current epoch becomes `COMMIT` and a new `RUNNING` epoch is issued immediately. The commit thread waits only for affected lists' tickets to drain, aggregates those logs, and writes a journal descriptor block, payload, and journal commit block atomically.

Apply introduces three page states: `Uptodate`, `F2FSJ_Dirty`, and `Dirty`. After data flush plus journal commit, a page becomes `Dirty`, meaning committed but not yet applied. When apply sees a `Dirty` in-memory page, it flushes that newest page and marks it `Uptodate`, collapsing older cross-epoch updates into one write. If the page is absent or already `Uptodate`, the log can be skipped; if it is `F2FSJ_Dirty`, meaning another epoch is still using it, F2FSJ falls back to applying the log record directly. Crash recovery replays remaining epochs in commit order using logged NAT/SIT/SSA metadata to locate old inodes and write new ones. One operational consequence is that journals must be applied before garbage collection, because GC can move inode and data locations.

## Evaluation

The prototype adds about 3,000 lines to Linux F2FS and uses a 256 MB contiguous journal file. On `mkdir`, `rmdir`, `create-4KB`, and `unlink-4KB`, F2FSJ's journal time is 2.4x, 1.7x, 3.6x, and 4.9x shorter than F2FS checkpoint time. Tail latency drops by roughly three orders of magnitude, and average latency improves by 23%, 35%, 13%, and 33%.

Throughput gains are strongest exactly where the design targets overhead: 1.29x/1.16x/1.27x/1.11x over checkpointed F2FS on metadata-intensive workloads, and 1.14x/1.69x/1.30x on `create-4KB`, `unlink-4KB`, and `copy-4KB`. Large sequential or random data workloads see much smaller gains because checkpoints are rare and journaling adds extra writes. On recovery, F2FSJ avoids the checkpoint-interval tradeoff and is 5.4x to 6.8x faster than F2FS roll-forward recovery in the file-count sweep; the paper also reports passing CrashMonkey rename and create/delete tests.

## Novelty & Impact

The paper's contribution is not simply "journal F2FS," but "journal F2FS in a way that respects out-of-place updates." Metadata-change logging, per-inode decentralization, epoch-based handoff, and fast-forward apply are all necessary to make ordered journaling cheaper than checkpointing. That makes the work relevant to Linux filesystem engineering and to later research on scalable journaling and flash-oriented crash recovery.

## Limitations

F2FSJ is not a universal speedup. On large data-intensive workloads it often only matches checkpointed F2FS, and some realistic workloads such as Webproxy and Varmail are still limited by F2FS metadata contention or heavy `fsync` traffic. Recovery is also still slower than ext4's page replay because F2FSJ must read old inode state and update NAT/SIT/SSA metadata in epoch order. The design requires dedicated contiguous journal space, forces journal apply before GC, and argues reduced write amplification without directly measuring SSD endurance.

## Related Work

- _Lee et al. (FAST '15)_ - F2FS introduced the out-of-place flash layout and checkpoint-plus-roll-forward recovery model that F2FSJ specifically tries to replace with finer-grained ordered journaling.
- _Xu and Swanson (FAST '16)_ - NOVA also uses per-inode logs, but it is designed for hybrid volatile/non-volatile main memory rather than flash-oriented journal aggregation and apply.
- _Kim et al. (ATC '21)_ - Z-Journal improves JBD2 scalability with per-core journaling and coherence commits, whereas F2FSJ distributes work by inode and epoch.
- _Shirwadkar et al. (ATC '24)_ - FastCommit adds compact logical metadata logging on top of periodic JBD2 commits, while F2FSJ makes metadata-change journaling the primary ordered-recovery path for F2FS.

## My Notes

<!-- empty; left for the human reader -->

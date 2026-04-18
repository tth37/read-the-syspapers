---
title: "UnICom: A Universally High-Performant I/O Completion Mechanism for Modern Computer Systems"
oneline: "UnICom moves direct-I/O completion into the kernel, using scheduler tags, a shared polling thread, and a shortcut I/O path to match polling without wasting CPUs under load."
authors:
  - "Riwei Pan"
  - "Yu Liang"
  - "Sam H. Noh"
  - "Lei Li"
  - "Nan Guan"
  - "Tei-Wei Kuo"
  - "Chun Jason Xue"
affiliations:
  - "City University of Hong Kong"
  - "ETH Zurich & Inria-Paris"
  - "Virginia Tech"
  - "Delta Electronics and National Taiwan University"
  - "Mohamed bin Zayed University of Artificial Intelligence"
conference: fast-2026
category: os-and-io-paths
code_url: "https://github.com/MIoTLab/UnICom"
tags:
  - storage
  - kernel
  - scheduling
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`UnICom` treats a kernel trap as cheap enough to keep I/O completion logic in the kernel while bypassing most of the rest of the storage stack. With `TagSched`, `TagPoll`, and `SKIP`, it reaches polling-like latency when CPUs are free and avoids polling's CPU waste when CPUs are contested.

## Problem

Fast NVMe SSDs turn software overhead into a dominant cost; the paper cites Optane-class results where software is about half of a `4 KB` read. Existing completion mechanisms force a bad choice. Polling is responsive when I/O threads own CPUs, but wastes cycles and hurts co-running compute work. Interrupts conserve CPU, but once device latency is only a few microseconds, sleep, wake-up, and interrupt delivery are themselves expensive; Table 1 attributes about `33%` of ext4's `4 KB` direct-read latency to interrupt handling.

This is most damaging in mixed workloads, which are the paper's target. Storage-intensive code often runs beside CPU-intensive threads or sibling processes, and polling hurts both. The authors also dismiss `io_uring` as a universal answer for synchronous applications because it still depends on the underlying completion path and pushes code toward an async model.

## Key Insight

The key claim is that entering the kernel is cheap enough to buy useful coordination. On the authors' machine, a syscall costs about `150 ns`, versus about `4010 ns` of device latency for a representative `4 KB` read. `UnICom` therefore traps into the kernel, reuses scheduler and permission infrastructure, and bypasses most of the rest of the I/O stack. Once completion is in the kernel, the system can keep sleeping I/O threads visible to the scheduler, wake them by lightweight state changes, and merge polling across processes.

## Design

`TagSched` changes how synchronous I/O threads sleep. Instead of dequeuing a thread on every I/O and re-enqueueing it on completion, the scheduler leaves it on the run queue and marks its PCB with `IO-WAIT`. Completion restores `IO-NORMAL`. To avoid missed-wakeup races, waiting is implemented as a decrement and wake-up as an increment, so out-of-order events cancel safely. When a completed I/O thread sits behind a compute thread, `TagSched` sends an IPI so the scheduler can run it immediately.

`TagPoll` is a shared kernel completion thread that polls NVMe queues for all I/O threads and processes. Each request carries the submitter's PCB pointer, letting the poller mark completion, restore the scheduling tag, and optionally trigger preemption. It also predicts the next completion mode: if an I/O thread is the only runnable task on its CPU, the next request can use polling; otherwise it sleeps and relies on `TagSched`.

`SKIP` makes the fast path practical. A kernel module, `UnIDrv`, manages NVMe queues and a per-file extent tree from file offsets to physical blocks. A user library, `Ulib`, intercepts direct-I/O file operations via `LD_PRELOAD` and forwards them through `user_io_submit`. Compared with `BypassD`, this avoids user-space permission machinery, static queue allocation, and the memory cost of a static fmap.

## Evaluation

Experiments run on Linux `6.5.1` with `16` E-cores and an `Intel Optane SSD P5801x`; `BypassD` gets all available NVMe queues, while `UnICom` reserves one core for its completion thread.

On I/O-only microbenchmarks, `UnICom` beats ext4 by `43.5%` on `4 KB` random reads and `34.9%` on `4 KB` random writes, and slightly exceeds `BypassD`. Under saturation it still cuts `4 KB` P99 by `31.2%` relative to ext4 while avoiding the worst `128 KB` polling tails.

Mixed workloads are the strongest evidence. With `16` compute threads, `UnICom` improves `4 KB` read IOPS by `39.4%` over ext4 and `88.8%` over `BypassD`. With `16` I/O threads and rising compute pressure, it still averages `33.2%` above ext4 and is `82.7%` above `BypassD` at `32` compute threads. In RocksDB+YCSB, it beats ext4 by `24%` and `28%` for `64 B` and `200 B` values at one thread, and by `9%` and `18%` at `32` threads.

## Novelty & Impact

Compared with `BypassD`, the novelty is not simply moving code back into the kernel, but using that move to recover scheduler coordination, cross-process sharing, and safe direct access. Compared with `Cinterrupts` and `Aeolia`, the paper changes the completion mechanism itself rather than merely making interrupts cheaper.

## Limitations

The prototype only accelerates direct I/O and depends on `LD_PRELOAD`, a custom kernel module, and file-system hooks for the extent tree. Its single completion thread is also an explicit scaling ceiling: at about `550 ns` per completion, the paper estimates a maximum of roughly `1820 KIOPS`. Cold opens pay to build the extent tree, rising to `28 us`, `57 us`, and `146 us` for files with `4`, `9`, and `186` extents, and the strongest evidence still comes from one ext4-based prototype on a very fast SSD.

## Related Work

- _Yadalam et al. (ASPLOS '24)_ — `BypassD` pushes direct file I/O and queue access into user space with polling, while `UnICom` keeps completion in the kernel to share polling across processes and reduce CPU waste under contention.
- _Tai et al. (OSDI '21)_ — `Cinterrupts` tunes interrupt coalescing for small I/Os, whereas `UnICom` changes the sleep/wake mechanism itself and can switch between poll-like and interrupt-like behavior per thread.
- _Li et al. (SOSP '25)_ — `Aeolia` uses Intel User Interrupts to accelerate userspace storage interrupts, while `UnICom` avoids special CPU requirements and instead treats an ordinary kernel trap as cheap enough to build on.
- _Joshi et al. (FAST '24)_ — `I/O Passthru` shortens the Linux NVMe path through `io_uring`, while `UnICom` adds scheduler tags, a shared completion thread, and synchronous-I/O transparency on top of a shortened path.

## My Notes

<!-- empty; left for the human reader -->

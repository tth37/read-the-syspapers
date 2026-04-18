---
title: "DPAS: A Prompt, Accurate and Safe I/O Completion Method for SSDs"
oneline: "DPAS learns per-I/O sleep timing from the last two outcomes, then switches among classic polling, PAS, and interrupts when contention or timer failures make one mode unsafe."
authors:
  - "Dongjoo Seo"
  - "Jihyeon Jung"
  - "Yeohwan Yoon"
  - "Ping-Xiang Chen"
  - "Yongsoo Joo"
  - "Sung-Soo Lim"
  - "Nikil Dutt"
affiliations:
  - "University of California, Irvine"
  - "Kookmin University"
conference: fast-2026
category: flash-and-emerging-devices
code_url: "https://github.com/DongDongJu/DPAS_FAST26"
tags:
  - storage
  - kernel
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`PAS` replaces epoch-based sleep estimation with a per-I/O controller that only asks whether the last sleeps were too short or too long. `DPAS` then switches per core among classic polling, PAS, and interrupts, so the stack keeps fast completions when CPUs are free but avoids hybrid-polling pathologies under contention.

## Problem

Modern NVMe SSDs are fast enough that interrupt cost is no longer hidden. Even when the device completes in a few microseconds, interrupt-driven I/O still pays for context switches, cache disruption, and power-state transitions. Classic polling removes those costs, but it monopolizes a CPU and breaks down once application threads or background work compete for cores.

Hybrid polling should be the compromise: sleep for part of the service time, then wake and poll near completion. The paper shows that existing Linux-style schemes fail because they estimate sleep from coarse epoch statistics. Linux Hybrid Polling uses half the previous epoch's mean latency; HyPI changes attenuation offline; EHP uses the minimum of a shorter epoch. All of them react slowly to abrupt latency shifts, and all of them confuse OS-induced late wake-ups with real device slowdown. Under contention this produces "latency shelving": one oversleep makes the next sleeps longer instead of fixing the mistake.

## Key Insight

The key claim is that hybrid polling does not need a detailed latency predictor; it needs immediate feedback. Knowing whether the last two sleeps underslept or overslept is enough to track the lower envelope of SSD latency on a per-I/O basis. Those binary outcomes arrive immediately, so the controller can react without waiting for the next sampling epoch.

The second insight is that no completion method wins everywhere. PAS still pays timer overhead, and under heavy CPU contention its requested sleep can collapse to zero, creating a timer-failure busy-wait loop. The right design is therefore a combination: use PAS when hybrid polling helps, classic polling when the core is effectively dedicated, and interrupts when contention makes sleeping unreliable.

## Design

`PAS` keeps per-bucket state using the same read/write and I/O-size buckets as Linux Hybrid Polling. Each bucket stores the previous two sleep results, a current duration, and an adjustment factor. It starts from `(OVER, UNDER)` with a `0.1 us` sleep. `(UNDER, UNDER)` increases the next sleep by `UP`; `(OVER, OVER)` decreases it by `DN`; mixed pairs mean the controller crossed the latency envelope, so it resets around `1` and makes a single corrective move. After sleeping with `hrtimer`, PAS calls a modified poll function that returns `UNDER` if the I/O is still pending and `OVER` otherwise.

PAS also tunes its own sensitivity. If the recent pair is identical, it treats that as sluggish tracking and multiplies both `UP` and `DN` by `(1 + HEATUP)`; if the pair differs, it cools sensitivity by multiplying them by `(1 - COOLDN)`. The design fixes the `UP:DN` ratio at `1:10`, bounds `UP` to `[0.001, 0.01]`, and uses `(HEATUP, COOLDN) = (0.05, 0.1)`.

Concurrency requires two more rules. PAS moves from per-device state to per-core state so different CPUs do not overwrite one another or serialize on locks. When multiple threads share a core, only the first completion using a given duration may submit a sleep result, and only the first I/O that sees a new result may update the duration. That preserves the meaning of the two-result controller.

`DPAS` adds a four-state machine: classic polling, PAS-normal, PAS-overloaded, and interrupts. In PAS-normal, it issues `NPAS = 100` I/Os to observe queue depth. If average depth is `1`, it switches to classic polling for `NCP = 1000` I/Os, then returns. If PAS observes a timer failure, meaning requested sleep has collapsed to zero, DPAS enters PAS-overloaded, rechecks queue depth, and switches to interrupts for `NINT = 10000` I/Os when depth exceeds threshold `theta` (`1` for NAND flash SSDs, `3` for 3D XPoint). This gives the system a way out when hybrid polling becomes self-defeating.

## Evaluation

The evaluation uses Linux `5.18` on a `20`-core Xeon Gold `6230` with three SSD classes: Intel Optane P5800X (`3D XPoint`), Samsung 983 ZET (`Z-NAND`), and SK hynix P41 (`TLC NAND`). The workloads include synthetic `FIO`, trace replay from `Baleen`, `Systor'17`, and `Slacker`, and `YCSB` on `RocksDB`.

The clearest PAS result is CPU efficiency. For `4 KB` random reads, PAS reduces CPU usage by `21` percentage points versus Linux Hybrid Polling while keeping the low-latency benefit of polling-based completion. Classic polling still has the highest raw upside, reaching up to `30%` higher read IOPS than interrupts on Optane, which is why DPAS keeps it as a mode.

The more important result is robustness. With simultaneous CPU contention and pulsed background I/O, DPAS improves average `YCSB` throughput over interrupts by `9%` on Optane, `7%` on ZSSD, and `5%` on P41. PAS alone helps, but DPAS is usually better because it escapes timer-failure regimes that drag PAS below interrupts at high thread counts. The trace analysis supports the diagnosis: LHP and EHP keep oversleeping after a latency spike because stale epoch statistics linger, while PAS and DPAS react immediately. The paper also shows the cost of blind polling: on ZSSD, classic polling matches interrupt latency up to the `90th` percentile, but its `99.99th` and maximum latencies rise to `17x` and `30x` of interrupts under interference.

## Novelty & Impact

Relative to Linux Hybrid Polling, `HyPI`, and `EHP`, the novelty is not another attenuation heuristic but a different control signal: per-I/O binary sleep outcomes instead of epoch summaries. Relative to prior comparisons between polling and interrupts, `DPAS` contributes an explicit runtime bridge among completion mechanisms that were usually evaluated separately.

That makes the paper relevant to Linux block-layer developers, NVMe researchers, and systems papers that benchmark ultra-low-latency storage under mixed CPU pressure. The scheduler interaction is not treated as noise around the storage path; it becomes part of the completion design itself.

## Limitations

The approach is still tightly scoped to the Linux NVMe path. The implementation sits in the multi-queue block layer, depends on a modified kernel poll path, and uses separate polled and interrupt queues per CPU. When CPU count greatly exceeds device queues, queue sharing can hurt performance. The paper also does not integrate interrupt coalescing, so interrupt mode can still create storms under very high concurrency.

The evaluation is strong for local SSDs but narrower beyond that target. Gains shrink as I/O size increases; for `128 KB` reads on P41, DPAS is about `1%` below interrupts. The paper also does not study `io_uring`, SPDK, networked storage, or deployments that would trade some IOPS for more CPU headroom. Finally, `theta` is robust, but it is still set by media class rather than derived automatically.

## Related Work

- _Lee et al. (JSA '22)_ - `EHP` replaces the mean with the minimum latency of a shorter epoch, but it still inherits epoch-boundary lag and cannot separate oversleep from real device slowdown.
- _Song and Eom (IMCOM '19)_ - `HyPI` chooses attenuation factors offline for each target system, whereas `PAS` adapts online from per-I/O sleep outcomes.
- _Hao et al. (OSDI '20)_ - `LinnOS` predicts fast versus slow flash behavior with a neural network, but it does not provide the precise wake-up timing that hybrid polling needs.
- _Yang et al. (FAST '12)_ - "When Poll is Better Than Interrupt" established the basic trade-off between polling and interrupts for storage I/O, while `DPAS` turns that static trade-off into runtime mode selection under contention.

## My Notes

<!-- empty; left for the human reader -->

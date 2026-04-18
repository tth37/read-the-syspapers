---
title: "ScaleSwap: A Scalable OS Swap System for All-Flash Swap Arrays"
oneline: "Redesigns Linux swap around per-core swap files, delegated metadata access, and per-core LRUs so all-flash SSD arrays finally scale with cores and devices."
authors:
  - "Taehwan Ahn"
  - "Chanhyeong Yu"
  - "Sangjin Lee"
  - "Yongseok Son"
affiliations:
  - "Systems and Storage Laboratory, Chung-Ang University"
conference: fast-2026
category: flash-and-emerging-devices
code_url: "https://github.com/syslab-CAU/ScaleSwap"
tags:
  - memory
  - kernel
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ScaleSwap redesigns Linux swap for many-core servers with all-flash swap arrays. Instead of letting every core contend for every swap resource, it gives each core its own swap metadata, swap cache, swap file, and LRU list, and delegates only the metadata operation when a page must cross cores. On a 128-core machine with eight NVMe SSDs, that yields up to `3.41x` higher throughput and `11.5x` lower average latency than Linux swap.

## Problem

Striping swap across multiple SSDs is not enough. Modern graph, data-processing, VM, and container workloads often need memory footprints far beyond DRAM, and SSDs are cheap enough to serve as a last memory tier. But Linux swap still follows an all-to-all model: any core may touch any swap space, and direct reclaim makes many application threads reclaim pages in parallel from shared per-node LRUs and shared swap metadata. That parallelism quickly collapses into `lru_lock` and `si_lock` contention.

The paper makes the mismatch concrete. On raw devices, mixed random read/write throughput scales from `3.4` to `5.8`, `9.4`, and `11.2 GB/s` as SSD count rises from `1` to `2`, `4`, and `8`. Linux swap, however, stays around `4 GB/s` regardless of SSD count. With `64` and `128` cores, Linux swap falls `1.5x` and `2.6x` below raw-device throughput. The bottleneck is therefore not flash bandwidth itself, but a swap subsystem whose central data structures serialize many-core access.

## Key Insight

The central claim is that swap should be mostly one-core-to-one-resource. If the core that allocates, evicts, and later faults a page can usually operate on its own swap metadata, swap cache, swap file, and LRU list, then both major lock bottlenecks shrink dramatically.

Cross-core cases still exist, such as a full local swap file, shared pages, or process migration. ScaleSwap's insight is to delegate only the metadata operation to the owner core, while the requesting thread still performs the actual page I/O directly. That preserves consistency without turning every swap-in or swap-out into a cross-core critical section.

## Design

ScaleSwap has three linked mechanisms. First, core-centric resource management gives each core its own swap metadata, swap cache, swap slot, swap file, and shared per-core LRU list. To support more than the Linux limit of `23` swap spaces, the system widens the swap-entry type field from `5` to `8` bits and reduces the offset from `50` to `47` bits, raising the usable swap-file count to `247` while still permitting up to `128 TB` per swap file. Swap allocation becomes local: a core refills its swap slot from clusters in its own swap metadata instead of round-robining over globally shared swap spaces.

Second, ScaleSwap adds opportunistic inter-core swap assistance. If a local swap file is full, or a page resides in another core's swap space because of sharing or migration, the requester enqueues a `96`-byte swap task to a per-core delegator on the owner core. That delegator is the only thread allowed to mutate that core's swap metadata, so consistency comes from ownership rather than lock sharing. Importantly, delegation covers only metadata lookup and update; the requester still reads or writes the page data directly to the chosen swap space. The paper also adds cooperative swapping: while waiting, a thread can help process tasks in its own queue instead of spinning uselessly.

Third, ScaleSwap fixes the page-reclamation path. It replaces per-node anonymous LRUs with per-core LRUs and records a page's core affinity in page flags by reusing spare bits. Swap-out therefore removes a page from the local core's LRU, and swap-in can reinsert it into the original core's LRU. This reduces interference from other cores and keeps locality aligned with the core-centric swap path.

## Evaluation

The implementation targets Linux `6.6.8` on a `128`-core server with `96 GB` of DRAM and eight `2 TB` FireCuda 530 NVMe SSDs. The main microbenchmark uses `128` threads, `128` swap files on `ext4`, and `288 GB` of touched memory, which is a reasonable stress test for the paper's target regime.

The results support the main claim. As SSD count grows from `1` to `8`, ScaleSwap achieves up to `3.41x` higher throughput than Linux swap. As core count rises to `128`, ScaleSwap scales roughly linearly while Linux swap stops improving after `32` cores. Latency gains are equally large: average latency falls by up to `11.5x`, and `99.9th`-percentile latency by up to `27.2x`. Table 5 explains why. Linux spends `53.27%` of execution time on `lru_lock`; a partial ScaleSwap variant removes that bottleneck but shifts pressure to `si_lock`; the full design removes both and reaches `14.81 GB/s` with `66.34 us` average latency, versus Linux's `4.34 GB/s` and `768.67 us`.

The broader workload set is credible. On five memory-intensive applications, ScaleSwap improves throughput by `1.70x-2.57x` at eight SSDs. On Apache Spark over `128` Common Crawl WARC files, it reaches `6.3 GB/s` and a `1.75x` speedup at the largest input size. Against prior work, it beats TMO by up to `64%` and ExtMEM by up to `5.02x`. The evaluation is strong because it directly measures SSD scaling, core scaling, lock breakdown, and delegation overhead, though it is still confined to one server platform and one filesystem configuration.

## Novelty & Impact

Compared with _Weiner et al. (ASPLOS '22)_ on TMO and _Bergman et al. (USENIX ATC '22)_ on ZNSwap, ScaleSwap is less about deciding when to offload and more about making ordinary OS swap scale on many cores and many SSDs. Compared with _Jalalian et al. (USENIX ATC '24)_ on ExtMEM, it keeps the kernel-managed swap abstraction instead of pushing memory policy into user space.

That makes the paper a systems mechanism paper, not just a measurement study. Its likely impact is on kernel memory management, SSD-backed memory extension, and future servers that treat swap as the final safety tier beneath CXL or disaggregated memory.

## Limitations

The win is strongest in the exact regime the paper targets: one server, direct reclaim, many cores, and an all-flash swap array. The paper does not evaluate slower storage media, richer multi-tenant interference, or deeper interaction with tiered and disaggregated memory systems. The hardware study is also limited to one `128`-core platform with eight SSDs.

The design itself carries explicit architectural tradeoffs. It changes swap-entry and page-flag layouts to support `247` swap files, `47`-bit offsets, and `7`-bit CPU identifiers. Those bounds are sensible for the tested machine, but they are still kernel-level assumptions rather than invisible drop-ins. Finally, delegation remains cheap because it touches only metadata, yet locality still matters: when `96` swap files are forced full, throughput falls from `14.81` to `12.48 GB/s`, so the system is robust under pressure, not free from it.

## Related Work

- _Bergman et al. (USENIX ATC '22)_ — ZNSwap redesigns swap for zoned SSDs, while ScaleSwap targets concurrency and ownership across many cores and many conventional NVMe devices.
- _Weiner et al. (ASPLOS '22)_ — TMO focuses on transparent memory offloading and pressure-aware capacity management, whereas ScaleSwap optimizes the swap fast path itself.
- _Jalalian et al. (USENIX ATC '24)_ — ExtMEM moves memory policy into user space for application-aware control; ScaleSwap keeps kernel-managed swap but makes it scale.
- _Saxena and Swift (USENIX ATC '10)_ — FlashVM uses flash-aware techniques to make swapping to flash practical, while ScaleSwap's novelty is per-core ownership and delegation on all-flash arrays.

## My Notes

<!-- empty; left for the human reader -->

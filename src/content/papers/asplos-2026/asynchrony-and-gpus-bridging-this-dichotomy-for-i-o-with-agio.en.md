---
title: "Asynchrony and GPUs: Bridging this Dichotomy for I/O with AGIO"
oneline: "AGIO lets GPU threads issue explicit asynchronous SSD I/O, decoupling issue from wait so computation and later requests can hide storage latency."
authors:
  - "Jihoon Han"
  - "Anand Sivasubramaniam"
  - "Chia-Hao Chang"
  - "Vikram Sharma Mailthody"
  - "Zaid Qureshi"
  - "Wen-Mei Hwu"
affiliations:
  - "The Pennsylvania State University, University Park, PA, USA"
  - "Nvidia, Santa Clara, CA, USA"
  - "Nvidia Research, Santa Clara, CA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790130"
code_url: "https://doi.org/10.5281/zenodo.18333270"
tags:
  - gpu
  - storage
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

AGIO adds explicit asynchronous SSD I/O to GPU threads without handing control back to the CPU. Its central move is to separate I/O initiation from completion, and even let a different GPU thread consume the result later. That separation hides microsecond-scale storage latency when there is useful overlap, and it also raises I/O parallelism in pointer-chasing code that has little compute to hide stalls.

## Problem

The paper starts from a mismatch between modern GPU workloads and the GPU execution model. Many data-intensive applications now need data that does not fit in on-card memory, so they reach into host memory and SSDs. The problem is that GPUs are still built around a mostly synchronous model: a thread issues an operation, blocks, and relies on SIMT multithreading to cover the delay. That works for cache misses and ordinary memory movement, but it is a poor fit for SSD accesses that take microseconds rather than tens or hundreds of cycles.

Prior systems only partially close that gap. CPU-orchestrated paths such as GPUfs and GPUDirect Storage can move data between SSDs and GPU memory, but the host still initiates or manages the transfer. BaM removes the CPU from the control path and lets GPU threads program NVMe queues directly, yet it still presents a blocking interface: the issuing thread waits for the transfer before making progress. On GPUs, that blocking is especially costly because warps are not independent Unix processes. Threads in the same warp often arrive at the same I/O point together, and if one thread has more I/O than its neighbors, the whole warp slows down.

So the real problem is not merely "GPU-to-SSD access is slow." It is that existing GPU-storage interfaces force a synchronous consumption model onto applications whose I/O stalls are long enough to require a fundamentally asynchronous design.

## Key Insight

The paper's main claim is that GPU-side storage I/O should be decoupled in both time and space. In time, a thread should be able to issue an I/O early and continue doing useful work before waiting. In space, the thread that consumes the data need not be the one that initiated the request.

Why does that matter? The first benefit is familiar: when future accesses are known ahead of time, asynchronous issuance acts like application-directed prefetching and can overlap storage latency with compute. The second benefit is more interesting and less obvious. Even when there is very little computation to overlap, non-blocking issuance still lets threads move ahead and create more outstanding requests, increasing I/O parallelism and using SSD bandwidth more fully. Decoupling the waiting thread also reduces the damage from SIMT imbalance, because a ready thread can consume any completed request instead of idling behind the thread that originally issued it.

## Design

AGIO exposes a small API to GPU threads: `g_aio_read`, `g_aio_write`, `g_wait`, and GPU-side dynamic allocation helpers. Each request is described by a control block containing the target buffer, offset, size, device id, an application pointer, a command id, and an optional tag. The application pointer carries per-request metadata from the issuing thread to the consuming thread.

The programming model supports three cases. In the simplest case, the same thread issues an I/O and later waits for that specific completion with `g_wait((cid,*))`; this matches regular, mostly static kernels such as dense matrix code. In dynamic graph workloads, any thread may wait for any completion with `g_wait((*,*))`, allowing the system to decouple issuance from consumption across threads. A third API variant groups correlated requests, such as the edge and weight arrays needed together in SSSP, so the runtime only releases them once the whole bundle completes.

The control path is implemented entirely on the GPU. AGIO runs a persistent runtime megakernel on dedicated runtime SMs, while application threads run on the remaining SMs. The authors reject warp specialization and instead use SM specialization via Nvidia Green Contexts, because warp-level specialization makes placement, synchronization, and cache interference harder to manage. In their default configuration, 32 of the A100's 108 SMs run runtime threads.

Communication between application threads and runtime threads uses bidirectional request and completion queues. Each channel has slotted ring buffers plus a per-slot atomic state. Instead of strict head/tail FIFO discipline, AGIO uses `nextinsert` and `nextpoll` placeholders that allow temporary holes: threads reserve slots atomically, fill or poll their own slots independently, and avoid a single doorbell-style serialization point. The runtime uses four channels per SM, which the authors argue is already far beyond SSD IOPS limits.

The data path still relies on direct GPU-NVMe interaction. NVMe queues are mapped into GPU memory, runtime threads issue commands from the GPU, and SSDs DMA data directly into GPU buffers without CPU bounce buffers. AGIO also reuses BaM's caching layer, but because AGIO is explicit I/O rather than memory-mapped access, it pays an extra copy between system buffers and application-visible data structures. GPU-side memory allocation is handled by a pool allocator with size-segregated slots and atomic state bits, which also performs GPU-virtual to DMA-address translation when needed.

## Evaluation

The implementation runs on an Nvidia A100 40GB PCIe GPU with a Micron 7450 NVMe SSD, Linux 6.8, CUDA 12.8, and Nvidia driver 570. The workload mix is intentionally split between static kernels and dynamic graph applications. Static workloads are `gemv` and `kmeans`, where access patterns are predictable enough to insert I/O early. Dynamic workloads are BFS, SSSP, PageRank, and connected components over synthetic graphs whose degree means and variances are varied to stress imbalance.

The headline result is that AGIO beats the best synchronous baseline, BaM-coalesced, by `1.65x` on average for static workloads and `1.32x` on average for dynamic workloads. The static results make the paper's "overlap" argument concrete: `gemv-1M` and `kmeans-128`, which have much more computation to cover each transfer, reach `1.54x` and `2.33x` speedups, while `gemv-4K` actually dips slightly below BaM-coalesced at `0.93x`. That is a useful honesty check: AGIO is not free, and when all threads synchronize around tiny requests with little work to hide them, the benefit narrows.

The dynamic results are more interesting because they showcase the "more outstanding I/O" claim. On low-mean, high-variance graphs such as `k16-k48`, AGIO outperforms BaM-coalesced by `1.31x` because it is much less sensitive to warp-level load imbalance. On low-mean, low-variance graphs such as `u16-u48`, it still delivers `1.87x` over BaM-coalesced and roughly matches BaM-baseline, despite not relying on hand-tuned work assignment. The NVMe queue snapshots show AGIO filling the storage pipeline sooner and finishing earlier.

The comparison against CPU-orchestrated asynchrony is also sharp. Using CUDA streams plus cuFileAsync, AGIO reaches about `3.3 GiB/s` once request size reaches `8 KiB`, whereas the stream-based approach needs `128 KiB` or larger requests to hit similar bandwidth. When the host CPU is loaded with `sysbench`, the cuFileAsync path degrades noticeably while AGIO is largely unaffected. Finally, the smaller-GPU experiment argues that AGIO is improving utilization rather than merely moving work around: with only `48` or `32` SMs, AGIO often matches or exceeds BaM-baseline and BaM-coalesced running on the full `108` SM A100, especially on high-variance graphs.

Overall, the evaluation supports the central claim well. The workloads explicitly vary the two quantities the paper says matter most, overlap and I/O parallelism, and the reported wins line up with that model.

## Novelty & Impact

Relative to _Qureshi et al. (ASPLOS '23)_, AGIO's novelty is not GPU-initiated SSD access by itself, but making that access explicitly asynchronous and exposing the programmer-visible consequences of decoupling issue and completion. Relative to CPU-managed paths such as _Silberstein et al. (ASPLOS '13)_, it removes the host from the control path entirely. Relative to general asynchronous GPU programming work such as _Wapman et al. (PMAM '23)_, it tackles a concrete storage-I/O runtime with queues, completion delivery, and application-level correlation of requests.

That makes the paper important for systems researchers working at the GPU-storage boundary and for practitioners building GPU data-processing runtimes. Its broader contribution is a reframing: once GPU threads can directly reach SSDs, blocking semantics become the next bottleneck.

## Limitations

AGIO requires applications to be rewritten with explicit control blocks, waits, and sometimes app-specific metadata handoff, so it is not transparent. The current design only supports explicit waiting with `g_wait`; the paper does not implement interrupt or callback-style completion. Its runtime is polling-based and reserves a substantial number of SMs for background threads in the default configuration, which is acceptable on an A100 but may be harder to justify on smaller GPUs.

The system also inherits some awkwardness from layering asynchronous explicit I/O over BaM's cached, memory-mapped substrate: the paper explicitly notes an extra copy between system buffers and application data structures. Finally, AGIO's gains are workload-dependent. If there is neither meaningful compute overlap nor enough imbalance to let some threads run ahead and issue more requests, the asynchronous machinery can lose to a well-coalesced synchronous design, as the `gemv-4K` result shows.

## Related Work

- _Qureshi et al. (ASPLOS '23)_ — BaM proves that GPU threads can directly drive NVMe queues, but it keeps a synchronous access model that AGIO relaxes.
- _Silberstein et al. (ASPLOS '13)_ — GPUfs integrates file access with GPU kernels, yet relies on CPU-side orchestration and multi-stage data movement that AGIO avoids.
- _Chang et al. (ASPLOS '24)_ — GMT also extends GPU access beyond on-card memory, but focuses on memory tiering policies rather than asynchronous explicit SSD I/O.
- _Wapman et al. (PMAM '23)_ — Harmonic CUDA studies asynchronous programming structure on GPUs, whereas AGIO builds a storage-specific runtime and API on top of that broader need.

## My Notes

<!-- empty; left for the human reader -->

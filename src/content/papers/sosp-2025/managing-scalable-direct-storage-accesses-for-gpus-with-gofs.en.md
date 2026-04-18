---
title: "Managing Scalable Direct Storage Accesses for GPUs with GoFS"
oneline: "GoFS moves F2FS metadata, block allocation, and NVMe queue control onto the GPU, turning GPUDirect Storage into a scalable POSIX file system for concurrent GPU I/O."
authors:
  - "Shaobo Li"
  - "Yirui Eric Zhou"
  - "Yuqi Xue"
  - "Yuan Xu"
  - "Jian Huang"
affiliations:
  - "University of Illinois Urbana-Champaign, USA"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764857"
tags:
  - storage
  - filesystems
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

GoFS turns GPUDirect Storage from a raw fast path into a real file system that the GPU can drive end to end. It keeps F2FS's on-disk format, but moves metadata management, block allocation, and NVMe queue handling into GPU memory, where GPU-oriented concurrency control lets direct storage accesses scale across thousands of threads.

## Problem

GPUDirect Storage removes an obvious inefficiency in GPU data pipelines: instead of staging data through host DRAM and then copying it to device memory, an SSD can DMA data directly into GPU memory. The problem is that today's software stack still leaves the host file system in charge. Libraries such as `cuFile` and `GPUfs` can shorten the data path, but the control path still runs through the CPU for pathname lookup, metadata traversal, permissions, and block mapping. Under highly concurrent GPU workloads, that host-side control path becomes the bottleneck.

The alternatives before GoFS are unsatisfying in different ways. `BaM` lets GPU threads issue NVMe commands directly, but only against a raw block device, so application developers must take over responsibilities that file systems normally provide. `GeminiFS` keeps metadata on the host and preloads selected metadata to the GPU, which works only when access patterns are predictable, metadata fits in GPU memory, and workloads are mostly read-only. The paper argues those assumptions do not hold for representative GPU workloads such as graph analytics, GNN training, intelligent queries, and RAG systems, where metadata can be large, accesses can be data-dependent, and intermediate writes are common.

## Key Insight

The paper's central claim is that GPUDirect Storage only becomes generally useful when the GPU owns both the data path and the filesystem control path. Once the GPU can traverse metadata, allocate blocks, issue NVMe commands, and enforce access control locally, direct storage stops being a special-purpose optimization and starts looking like a scalable POSIX file system.

That requires more than porting CPU code. GoFS works because it redesigns core file-system structures around the GPU execution model: warps and thread blocks, not independent CPU threads, are the unit of concurrency. The right abstractions are therefore batched metadata operations, per-SM allocation state, level-synchronous traversal, and zero-copy DMA into user buffers. Compatibility comes from a separate decision: preserve F2FS's on-disk layout so the host and GPU can share the same disk image instead of inventing a new storage format.

## Design

GoFS has three pieces: a host-side FUSE client, a GPU-side daemon, and `libgofs` for GPU applications. The GPU daemon is the real file-system engine. It caches dentries, inodes, and block-management state in GPU memory, maintains NVMe queue pairs in GPU memory via `libnvm`, and serves POSIX-style operations plus vector and batched APIs.

Several design choices are specifically about making file-system metadata scalable on a GPU. GoFS replaces the coarse inode mutex with a range lock implemented as a ring buffer, so disjoint accesses to one file can proceed concurrently. Conflict checks are parallelized with warp-level reductions, which is a much better fit for SIMT execution than CPU-style interval-tree logic. For directory-heavy workloads, GoFS adds a batched node (`bnode`) abstraction: one open on a directory can materialize many small files at once, amortizing inode and dentry work across a batch. For block allocation, GoFS uses per-SM bitmaps instead of a centralized allocator and coalesces all allocations from a thread block into one operation, reducing cross-thread contention.

The data-pointer traversal path gets a similar redesign. Rather than having each thread independently walk the inode's direct and indirect pointers, GoFS performs a two-stage level-synchronous traversal. First, it walks pointer blocks level by level to discover logical page addresses; then it fetches all leaf data blocks in parallel. This avoids branch divergence and straggler effects when different threads would otherwise traverse different pointer depths. On the data path, GoFS keeps multiple NVMe queues in GPU memory and issues zero-copy DMA directly between SSD and application buffers, skipping a page cache by default because the target workloads are mostly streaming or throughput-oriented. CUDA dynamic parallelism chooses how many I/O threads to launch based on request size, and GoFS offers both synchronous and asynchronous interfaces.

Host/GPU coordination is pragmatic rather than magical. GoFS keeps F2FS's on-disk format and lets the GPU act as the primary owner while the host acts as a secondary through FUSE. Read-only sharing is allowed; reopening for writes waits for the other side to release ownership. Crash consistency comes from the same log-structured, checkpoint-based machinery F2FS already uses. Protection is handled with a daemon process, GPU virtual-memory isolation, and HMAC-signed identities passed through the trusted host client, so user GPU code cannot directly forge file access rights.

## Evaluation

The evaluation uses a 16-core Xeon W5-3435X, an A100 with 40 GB of memory, and Samsung 990 Pro SSDs with GPUDirect Storage enabled. The microbenchmark results support the paper's main claim that the host control path, not the SSD, is the scaling bottleneck. GoFS reaches `5.5 GB/s` sequential read, `6.5 GB/s` sequential write, `5.1 GB/s` random read, and `6.1 GB/s` random write on one SSD, which is near raw-device throughput. The random-write result is especially telling: because GoFS is built on a log-structured layout and performs parallel log updates, random writes approach sequential speed.

The application results are broad and mostly convincing. Across intelligent queries, graph analytics, GNN training, RAG, and dataset preprocessing, GoFS reports `1.61x` average speedup over the best prior GPU storage solutions. Intelligent-query workloads benefit the most from batched metadata handling, with average speedups of `6.2x`, `7.5x`, `21.3x`, and `2.1x` over Basic, `GPUfs`, `cuFile`, and `GeminiFS`; the paper's ablation says the batch API alone contributes `1.41x` on average. For graph analytics, GoFS is `1.53x` faster than the CPU-centric baseline on average and `1.2x` faster than `GeminiFS`, matching the random-read story. In RAG, it beats Basic, `GPUfs`, and `GeminiFS` by up to `1.6x`, `1.8x`, and `1.4x`, and avoids `GeminiFS`'s KV-cache pressure from keeping `7.2 GB` of metadata resident. With four SSDs in RAID0, GoFS scales to `20.4 GB/s` sequential read and `22.1 GB/s` write. That said, nearly all evidence comes from one GPU generation, one SSD family, and an F2FS-based prototype, so the deployment envelope is still narrower than the headline suggests.

## Novelty & Impact

The novelty is not just "GPU issues NVMe commands." `BaM` already showed that. GoFS's contribution is to make the GPU a full file-system orchestrator: metadata, allocation, access control, crash consistency, and host coordination are all first-class parts of the design. Relative to `GeminiFS`, it removes the assumption that the GPU can live off preloaded metadata and read-mostly workloads; relative to `GPUfs`, it removes the CPU from the critical path instead of wrapping host file-system calls in RPC.

That makes the paper significant for data-intensive GPU systems, not only storage research. Any system that streams large datasets, does graph sampling, or mixes GPU computation with fine-grained persistent data access can treat direct SSD access as a normal file-system service rather than a bespoke I/O substrate. The paper is therefore a new mechanism, but also a change in systems framing: if accelerators are becoming first-class compute hosts, they also need first-class storage software.

## Limitations

GoFS depends on a fairly specific hardware and software stack: GPUDirect-capable GPUs and NVMe devices, CUDA, GPU virtual-memory isolation, and a host-side environment willing to run FUSE plus a trusted client. The implementation also assumes an F2FS-compatible on-disk layout; support for other file systems, remote storage, and transparent multi-GPU sharing is left to future work.

The CPU/GPU consistency model is conservative. Read-only sharing is supported, but mixed write ownership is serialized through a primary/secondary protocol, so GoFS does not make CPU and GPU symmetric peers. Some runtime costs also remain. In synchronous mode, GoFS may dedicate up to `16` of the A100's `108` SMs to polling under heavy I/O. Finally, the evaluation shows good application breadth but limited platform diversity, so it does not yet establish how robust the design is across different SSD firmware, other GPU vendors, or workloads that would genuinely benefit from a page cache.

## Related Work

- _Silberstein et al. (ASPLOS '13)_ - `GPUfs` lets GPU threads invoke host file-system APIs, but its RPC-based design keeps metadata and block management on the CPU; GoFS moves those responsibilities onto the GPU.
- _Bergman et al. (USENIX ATC '17)_ - `SPIN` demonstrated peer-to-peer SSD-GPU DMA, but it still relied on the host software stack above the data path; GoFS adds a GPU-resident file system on top of direct access.
- _Qureshi et al. (ASPLOS '23)_ - `BaM` lets the GPU issue NVMe commands to raw storage directly, whereas GoFS preserves POSIX semantics, block allocation, and crash-consistent file-system structure.
- _Qiu et al. (FAST '25)_ - `GeminiFS` offloads data I/O to the GPU while preloading metadata from the host, but it assumes predictable, mostly read-only workloads; GoFS manages metadata on demand and supports writes without host mediation.

## My Notes

<!-- empty; left for the human reader -->

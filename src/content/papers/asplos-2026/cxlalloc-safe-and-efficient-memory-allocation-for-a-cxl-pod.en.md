---
title: "Cxlalloc: Safe and Efficient Memory Allocation for a CXL Pod"
oneline: "cxlalloc splits allocator metadata by coherence domain, preserves cross-process pointer consistency, and adds recoverable CAS/mCAS protocols for shared CXL pods."
authors:
  - "Newton Ni"
  - "Yan Sun"
  - "Zhiting Zhu"
  - "Emmett Witchel"
affiliations:
  - "The University of Texas at Austin, Austin, Texas, USA"
  - "University of Illinois Urbana-Champaign, Champaign, Illinois, USA"
  - "NVIDIA, Santa Clara, California, USA"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790149"
code_url: "https://github.com/nwtnni/cxlalloc"
tags:
  - memory
  - disaggregation
  - fault-tolerance
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

cxlalloc is a user-space allocator for a shared CXL pod. It splits metadata by coherence domain, coordinates mappings across processes, and makes allocator operations recoverable. The result is near-mimalloc performance while still handling limited or absent inter-host coherence.

## Problem

The paper studies a small CXL pod where 8-16 hosts share memory. In that setting, an allocator must solve three problems at once.

First, inter-host hardware cache coherence may be partial or absent, so allocator metadata cannot assume `CAS` works everywhere. Second, memory is shared across processes, not only threads, so the allocator must preserve pointer consistency: the same pointer must name the same physical memory in every process, and newly allocated memory must become dereferenceable across processes. Third, partial failures are common: one thread or process may crash while others keep running, so locks and stop-the-world recovery are poor fits.

The authors argue that prior designs each cover only part of this space: fast volatile allocators lack cross-process sharing and recovery; persistent-memory allocators assume total failure and a quiet recovery window; and prior CXL memory managers often rely on fixed heaps, only small allocations, or per-object metadata that burns too much coherent memory.

## Key Insight

The key claim is that a CXL-pod allocator should be organized around coherence domains. Only a tiny fraction of metadata truly needs cross-host atomicity; mapping placement and visibility must be allocator-managed; and recovery should log just enough state to replay interrupted operations, not scan the whole heap.

cxlalloc therefore splits metadata into HWcc and SWcc regions, reserves virtual-address ranges so every process can map heap pieces at the same offsets, lazily installs missing mappings with a `SIGSEGV` handler, and records only 8 bytes of per-thread recovery state. If HWcc is unavailable, the same narrow atomic interface can be implemented with near-memory `mCAS`.

## Design

cxlalloc has three heaps: small (`8B-1KiB`), large (`1KiB-512KiB`), and huge (`512KiB+`). Small and large allocations use slabs. Each slab has an owner thread, an SWcc descriptor with size class and free-bit state, and a tiny HWcc descriptor that stores only a remote-free counter.

This layout separates the fast path from the shared path. Local allocation and free remain mostly thread-local. Remote frees do not mutate another thread's bitmap; they only decrement the shared counter with `CAS` or `mCAS`. cxlalloc adds `detached` and `disowned` slab states so slabs with remote frees can still be safely stolen back and reused.

Cross-process pointer consistency comes from reserved virtual-address ranges plus lazy mapping. The small heap grows monotonically at fixed offsets in every process. Huge allocations use a reservation array and a hazard-offset protocol, so freed mappings are reclaimed only after no process still has that offset published. Recovery relies on lock-free shared structures, detectable `CAS` for global-list updates, and 8 bytes of per-thread state that let a restarted thread finish an interrupted allocator action idempotently.

## Evaluation

The evaluation measures performance, coherent-memory usage, and recovery overhead. On an 80-core Intel Ice Lake machine, using YCSB and Twitter memcached traces, cxlalloc reaches `93.9%` of mimalloc's throughput on average; ralloc reaches `90.9%`.

The metadata split clearly pays off. Across the macrobenchmarks, cxlalloc uses only `0.02%` HWcc memory on average, and only `7.1%` of ralloc's HWcc footprint. Recovery overhead is also low: a nonrecoverable ablation is just `0.3%` faster overall, while Memento-based experiments show that ralloc must either block for recovery GC or leak memory, whereas cxlalloc does neither.

On real CXL hardware with an Intel Agilex 7 Type-2 device and an FPGA `mCAS` prototype, the platform itself is substantially slower than local DRAM: `357ns` read latency versus `112ns`, and `19.9 GB/s` bandwidth versus `114 GB/s`. Even so, `cxlalloc-mcas` reaches `80%` of `cxlalloc-hwcc` throughput on the small-heap `threadtest`. The caveat is the remote-free-heavy `xmalloc-small` benchmark, where `cxlalloc-mcas` falls to `1%` of the HWcc configuration because every remote free requires an `mCAS`.

## Novelty & Impact

Relative to _Leijen et al. (ISMM '19)_, cxlalloc extends fast owner-centric slab allocation into a cross-process, cross-host setting. Relative to _Cai et al. (ISMM '20)_, it keeps recoverability without assuming total failure or blocking recovery. Relative to _Zhang et al. (SOSP '23)_, it avoids per-allocation reference counts and fixed-size heaps. The contribution is therefore a full allocator design for shared CXL memory, not just a faster synchronization trick.

## Limitations

The design assumes a reliable CXL device that survives process crashes and OS reboots, and it assumes threads are pinned to cores. On platforms without HWcc, the uncachable device-biased `mCAS` path becomes a bottleneck for remote-free-heavy workloads.

The small heap also grows monotonically and never unmaps its mappings, huge allocations depend on `SIGSEGV`-driven lazy mapping plus `MAP_FIXED` reservations, and the remote-free protocol still has pathological fragmentation cases. The paper argues these cases are rare, but they remain deployment constraints.

## Related Work

- _Leijen et al. (ISMM '19)_ — mimalloc provides the fast owner-centric slab discipline that cxlalloc builds on, but it does not handle cross-process pointers, CXL coherence limits, or crash recovery.
- _Cai et al. (ISMM '20)_ — ralloc is a recoverable persistent-memory allocator, whereas cxlalloc targets volatile shared CXL memory with live surviving processes instead of a blocking post-crash recovery phase.
- _Zhang et al. (SOSP '23)_ — cxl-shm also targets partial failures in CXL shared memory, but relies on per-allocation reference counts, fixed-size heaps, and no huge allocations, all of which cxlalloc is designed to avoid.
- _Zhu et al. (DIMES '24)_ — Lupin motivates why partial failures matter in a CXL pod; cxlalloc supplies the allocator substrate needed to make such systems practical.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Scalable Address Spaces using Concurrent Interval Skiplist"
oneline: "The paper replaces coarse address-space locking with a concurrent interval skiplist, per-core arenas, and hybrid global/local locking so `mmap()` and `munmap()` scale on many cores."
authors:
  - "Tae Woo Kim"
  - "Youngjin Kwon"
  - "Jeehoon Kang"
affiliations:
  - "KAIST"
  - "KAIST / FuriosaAI"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764807"
code_url: "https://github.com/kaist-cp/interval-vm.git"
tags:
  - kernel
  - memory
  - filesystems
category: memory-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

This paper argues that the real bottleneck in modern kernel address spaces is no longer page-fault lookup, but the coarse serialization of `mmap()`-style allocation and `munmap()`/`mprotect()`-style modification. Its solution is a concurrent interval skiplist that merges interval mapping with interval locking, plus a Linux redesign around hybrid global/local locking, per-core arenas, and scalable counters. On Linux 6.8, that combination yields up to `13.1x` higher `mmap()` microbenchmark throughput and clear wins on Apache, LevelDB, Metis, and Psearchy.

## Problem

The paper starts from a familiar systems pain point: kernels still manage each process address space behind a coarse read-write lock, such as Linux's `mmap_lock`. That design lets many page faults run in parallel, but it serializes the operations that matter most to modern multicore software: creating mappings for allocator arenas and file-backed regions, and modifying or removing mappings once work completes. On a dual-socket 48-core machine, the authors measure that Linux 6.8 can spend up to about `90%` of Apache's time, `60%` of Metis's, `41%` of Psearchy's, and `40%` of LevelDB's waiting on `mmap_lock`.

The obvious fix, "replace one big lock with smaller ones," is not enough. Address-space operations touch intervals whose true synchronization footprint depends on the current map state: a `munmap()` may need to lock neighboring gaps so page tables can be safely freed, and a modification may span several mappings that do not align with metadata boundaries. At the same time, lookup must remain RCU-safe so faults can keep traversing without blocking, global operations such as `fork()` and `exit()` still need whole-space coordination, and `mmap()` allocation itself becomes contended if every thread scans from the same starting point. The paper's claim is that scalability fails unless all of those constraints are solved together.

## Key Insight

The core proposition is that address-space metadata and address-space locking should live in the same interval data structure. If traversal first discovers which interval to lock and only then acquires locks, concurrent updates can invalidate the decision and force retries or coarse fallback. If the map itself can perform "find the overlapping interval set and lock it" as one operation, the kernel can parallelize non-overlapping work without losing correctness.

That observation leads to a broader design rule: once the coarse lock is removed, the remaining bottlenecks become visible and must also be redesigned. The paper therefore does not present the concurrent interval skiplist as a standalone data structure. It pairs it with a hybrid global/local lock for whole-address-space operations, a per-core arena layout and separator hierarchy for scalable `mmap()` placement, and an adaptive per-core counter scheme that preserves resource limits without turning accounting into the new serialized hotspot.

## Design

The concurrent interval skiplist exposes `Query`, `Lock`, `Unlock`, and `Swap` primitives over an interval map. At the base level it behaves like a concurrent linked list, but it adds skip links for logarithmic search. The key mechanism is node-granular interval locking: the structure locks not just nodes whose intervals overlap the target range, but also the predecessor node and relevant gaps, because those determine whether another thread could insert, split, or repopulate the region during an update. Updates are committed in read-copy-update style. New nodes are prepared off to the side, the predecessor pointer is atomically redirected to them, and only then are the old nodes invalidated. That preserves lock-free lookup for `Query` while allowing atomic multi-node interval replacement.

The Linux design built on top of this structure uses two levels of locking. Each core has a lock that can be held in global-read, global-write, local-read, or local-write mode. Local operations pair the running core's lock with an interval lock inside the skiplist; global operations acquire all per-core locks, which is cheaper than locking every mapping in a large address space. Fault handling proceeds in escalating stages: first try without address-space locking, then retry under local-read locking when page-table allocation or VMA updates require synchronization, and finally fall back to global-read mode for rare unadapted file-backed cases. Modify operations similarly run under local-write plus interval locking, with global-write only as a fallback.

`mmap()` scalability needs two additional ideas. First, the address space is partially partitioned into 64 GiB per-core arenas so concurrent allocators do not all race for the same first free hole. Second, the skiplist is organized with separator nodes whose higher levels route between arenas while lower levels mostly stay within one arena, reducing cross-arena interference during insertion. Each arena also maintains a hint toward the last successful placement and moves it backward after `munmap()` to encourage reuse. Finally, resource accounting uses adaptive per-core counters: updates stay buffered locally until the remaining margin to a hard limit becomes too small, at which point cores switch to direct global updates so enforcement remains exact.

## Evaluation

The evaluation is strong because it measures both the data structure in isolation and the full Linux implementation on the workloads that previously suffered from `mmap_lock`. In user space, the interval skiplist loses on pure lookup, with `35%` higher Query latency and only `0.77x` peak Query throughput versus Linux's maple tree. That tradeoff is real: the maple tree's high branching factor makes read traversal cheaper. But the skiplist wins exactly where the paper says the bottleneck moved. It improves peak throughput by `22.9x` for `Alloc` and `5.28x` for `Map`, and cuts single-threaded `Map` latency by `49%`.

On the kernel side, LMbench shows modest regressions where whole-space traversal or lookup dominates: `fork+exit` latency rises by `21.6%`, page-fault latency by `3.2%`, and `mmap+fault+munmap` by `3.22%`. The multithreaded results are the main point. Peak throughput improves by `13.1x` on an `mmap()` microbenchmark and `10.4x` on a sequence of alloc-fault-modify operations. The macrobenchmarks line up with that story: Apache improves by `4.53x` in a single-process configuration and `3.19x` in its default multi-process configuration, LevelDB by `4.49x`, Metis by `1.47x`, and Psearchy by `1.27x`. The paper also breaks down Fault, Alloc, and Modify support separately and shows that disabling any of them substantially weakens scaling, which supports the paper's "solve the whole stack, not one lock" thesis.

## Novelty & Impact

Relative to prior address-space work, the novelty is not just "use finer-grained locks." The paper combines three pieces that earlier systems only solved partially: dynamic interval locking, RCU-safe multi-interval updates, and compatibility with a production kernel's full address-space semantics. RCUVM showed how to let faults proceed concurrently with updates, but it did not parallelize Alloc and Modify and only targeted anonymous memory. RadixVM parallelized non-overlapping operations, but it paid for page-granular metadata, weak RCU fit, and an allocation heuristic that the authors argue is impractical in a real kernel.

That makes this paper more than a Linux patch set. It is a reusable design pattern for interval-heavy kernel subsystems: integrate synchronization into the interval map itself, then add explicit support for whole-structure operations and allocator placement. The immediate audience is kernel VM researchers and Linux MM developers, but the authors also make a plausible case that similar issues appear in file systems, device-memory interval maps, and other kernel subsystems whose updates span dynamic ranges.

## Limitations

The design is not free. Lookups are slower than the maple tree, and that shows up as modest page-fault and `fork()` overhead. The paper's own data therefore supports a narrower claim than "the skiplist is a better map in general": it is better when update scalability dominates, not when the workload is mostly single-threaded lookup. Likewise, the Linux implementation still contains fallback paths. File-backed memory is only enabled for file systems the authors trust (`ramfs`, `tmpfs`, and `ext4`), and some less common operations still revert to global locking.

There are also engineering assumptions that may matter in deployment. The per-core arena layout spends virtual address space to gain parallel allocation; the paper notes that even 128 arenas consume less than `4%` of x86-64's 256 TiB space, but that argument is architecture-specific. The evaluation is thorough on throughput, yet lighter on memory overhead, long-term fragmentation behavior, and worst-case fairness when many threads exhaust private arenas and spill into shared space. The result is convincing as a systems mechanism, but not the last word on every workload or platform.

## Related Work

- _Clements et al. (ASPLOS '12)_ - RCUVM lets faults run concurrently with updates via an RCU-safe tree, whereas this paper targets the harder problem of parallelizing `mmap()` and `munmap()`-style updates in a production kernel.
- _Clements et al. (EuroSys '13)_ - RadixVM also parallelizes non-overlapping address-space operations, but does so with page-granular radix-tree metadata that the SOSP paper argues is too costly and awkward for RCU in real kernels.
- _Kogan et al. (EuroSys '20)_ - Scalable range locks address some dynamic interval-locking cases, while the concurrent interval skiplist folds locking and interval updates into one structure and avoids speculative global fallback for the common case.
- _Boyd-Wickizer et al. (OSDI '10)_ - The Linux scalability study identified `mmap_lock` contention as a serious many-core bottleneck; this paper is a direct attempt to remove that bottleneck without changing applications.

## My Notes

<!-- empty; left for the human reader -->

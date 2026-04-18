---
title: "uCache: A Customizable Unikernel-based IO Cache"
oneline: "uCache makes `mmap`-style IO caching application-customizable in a unikernel, using shared VMA state, policy hooks, and pluggable backends to approach `SPDK`-class performance."
authors:
  - "Ilya Meignan--Masson"
  - "Masanori Misono"
  - "Viktor Leis"
  - "Pramod Bhatotia"
affiliations:
  - "Technical University of Munich"
conference: fast-2026
category: os-and-io-paths
code_url: "https://github.com/TUM-DSE/uCache"
tags:
  - caching
  - kernel
  - virtualization
  - storage
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`uCache` is an OS-level IO cache for unikernels that keeps the memory surface of `mmap` but lets applications choose buffer size, backend, and replacement behavior. It shares VMA metadata between application and OS, runs policy callbacks in the same address space, and separates caching from storage access through `uVFS` and `uStore`. In the worst-case out-of-memory benchmark, it beats `mmap` by up to `55x`, and its NVMe backend stays within `3.5%` of `SPDK` on average.

## Problem

Modern cloud applications need caches over fast local NVMe and, increasingly, non-filesystem backends. The kernel page cache via `mmap` is easy to use, but on fast devices its generic implementation becomes visible: page faults are expensive, the memory-management path uses contended shared structures, asynchronous IO is awkward, and TLB shootdowns hurt scalability. At the same time, POSIX hints such as `madvise` are too weak to express application semantics like transaction-protected pages, workload-specific prefetching, or logical buffer sizes such as `8 KiB` and `16 KiB`.

The other extreme is to build a userspace cache with explicit `pin`/`unpin`-style control. That gives full control over replacement and backend choice, but it pushes cache-management complexity back into each application. The paper is trying to remove that dilemma: developers can have simplicity or performance and flexibility, but not both.

## Key Insight

The paper argues that this trade-off comes from OS/application isolation, not from memory mapping itself. In a unikernel, the cache can expose internal control points directly to the application. `uCache` therefore makes each mapped region a shared VMA object carrying buffer size, backend choice, resident-set type, and policy hooks. The OS still resolves faults transparently, but the rules for eviction, prefetch, and safety can come from application logic instead of generic POSIX advice.

## Design

`uCache` is implemented as a library inside `OSv`. Its main API remains `mmap`-like, but each mapping becomes one shared VMA composed of fixed-size `Buffer` objects with application-chosen size. The API also exposes explicit primitives such as `evict`, `prefetch`, `writeback`, `msync`, and `ensureCached`, so an application can bypass page-fault-driven behavior when it wants tighter control.

Policy customization is split across global hooks (`needToEvict`, `chooseEvictionVMAs`), VMA hooks (`chooseEvictionBuffers`, `choosePrefetchBuffers`), buffer hooks (`isEvictable()`), and optional bookkeeping hooks. Because callbacks are compiled into the same unikernel image, they can inspect application state directly; the paper uses this to keep locked database pages non-evictable and to reuse DuckDB's Parquet prefetch logic.

The cache manager itself uses optimistic lock-free page-table operations. On insert, a thread allocates physical memory, claims the PTE with `CAS`, fetches the data, and only then marks the mapping present; losing threads wait. Eviction clears present bits, triggers TLB invalidation, and `CAS`-removes physical addresses, aborting if another core raced in and touched the page. The same mechanism extends to multi-page buffers, which is important because one goal is to support `8 KiB` or `16 KiB` application units instead of only `4 KiB` pages.

Storage access is abstracted by `uVFS` and `uStore`. `uVFS` generalizes VFS to files, blocks, or objects, and applications may register their own backends. The prototype also provides an NVMe `uStore` that borrows zero-copy and per-core queue pairs from kernel-bypass designs while keeping filesystem compatibility through a lightweight `MiniFS` layer that translates file offsets to LBAs.

## Evaluation

Experiments run in VMs on an AMD `EPYC 9654P` with `768 GiB` RAM and a passthrough Kioxia `CM-7` NVMe SSD. In a `1 TiB`-file / `100 GiB`-cache microbenchmark where accesses eventually fault and evict, `uCache` beats `mmap` by up to `55x` at `64` threads and scales nearly linearly. The NVMe backend stays within `3.5%` of `SPDK` on average and beats `libaio` by `50%` on average, up to `150%` at larger batches. As a direct `mmap` replacement, random lookup throughput improves by `46x` to `78x` as cache memory shrinks from `128 GiB` to `16 GiB`.

The application studies are smaller but useful. Porting `vmcache` yields about `118k` TPC-C transactions per second, only `3%` below the specialized `exmap` path and clearly above the `madvise` version. Porting DuckDB's Parquet caching improves TPC-H execution time by `1.98x` on average, with best cases of `4.89x` on Q4 and `6.59x` on Q6. These results support the claim that cache-management overhead is no longer dominant, though almost all evidence comes from local NVMe.

## Novelty & Impact

`uCache` is novel because it combines an application-visible cache abstraction, lock-free page-table-driven cache operations, and a pluggable storage layer in one design. It sits between `Tricache`-style userspace control and eBPF-style Linux customization, and argues that once the OS is specialized to one cloud application, cache policy itself should become part of application design.

## Limitations

The design depends on unikernels and the prototype is tied to `OSv`, so it is not a drop-in improvement for ordinary Linux processes. The paper also notes portability issues around missing `fork`. The prototype's `ext4` path caches file-offset-to-LBA mappings in memory, does not support sparse files, and disallows concurrent structural file changes while open. Crash consistency is still the application's responsibility, and object-store flexibility is argued more than evaluated.

## Related Work

- _Feng et al. (OSDI '22)_ — `TriCache` keeps cache control in userspace and hides `pin`/`unpin` logic behind compiler support, whereas `uCache` tries to recover similar control inside an OS-level memory-mapped cache.
- _Papagiannis et al. (EuroSys '21)_ — `Aquila` specializes memory-mapped IO through virtualization while retaining Linux, whereas `uCache` moves to a unikernel and exposes cache policy as an application-visible interface.
- _Cao et al. (USENIX ATC '24)_ — `FetchBPF` customizes Linux prefetching with eBPF hookpoints, but `uCache` offers broader cache-policy control because callbacks can access full application state.
- _Zussman et al. (SOSP '25)_ — `cache_ext` makes the Linux page cache customizable with eBPF, while `uCache` argues for deeper OS-application co-design and non-filesystem backend flexibility.

## My Notes

<!-- empty; left for the human reader -->

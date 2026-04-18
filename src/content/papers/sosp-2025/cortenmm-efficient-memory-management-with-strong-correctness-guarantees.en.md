---
title: "CortenMM: Efficient Memory Management with Strong Correctness Guarantees"
oneline: "CortenMM removes the VMA layer, programs page tables through range transactions, and verifies the locking core so memory management scales without giving up Linux-like semantics."
authors:
  - "Junyang Zhang"
  - "Xiangcan Xu"
  - "Yonghao Zou"
  - "Zhe Tang"
  - "Xinyi Wan"
  - "Kang Hu"
  - "Siyuan Wang"
  - "Wenbo Xu"
  - "Di Wang"
  - "Hao Chen"
  - "Lin Huang"
  - "Shoumeng Yan"
  - "Yuval Tamir"
  - "Yingwei Luo"
  - "Xiaolin Wang"
  - "Huashan Yu"
  - "Zhenlin Wang"
  - "Hongliang Tian"
  - "Diyu Zhou"
affiliations:
  - "Peking University"
  - "Zhongguancun Laboratory"
  - "Ant Group"
  - "CertiK"
  - "UCLA"
  - "Michigan Tech"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764836"
code_url: "https://github.com/TELOS-syslab/CortenMM-Artifact"
tags:
  - memory
  - kernel
  - verification
  - pl-systems
category: memory-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CortenMM argues that modern kernels no longer need a separate VMA-style software abstraction above page tables. It keeps only a page-table-centric representation, exposes a transactional range interface, and verifies the concurrent MMU core in Verus, yielding both higher multicore scalability and stronger correctness guarantees.

## Problem

The paper starts from a concrete complaint about contemporary kernels: memory management is both too slow and too fragile. Linux and similar systems maintain two views of an address space, a software-level structure such as VMAs and the hardware-level MMU state in page tables. That split historically helped portability and advanced semantics, but every real operation must now keep two very different data structures synchronized under concurrency. The result is both performance loss and correctness risk: even recent Linux fine-grained locking still leaves multicore contention in metadata unrelated to the final MMU operation, and the paper points to recent CVEs caused by subtle memory-management races. Existing research systems improve parts of the problem, but often by dropping features or paying large memory overheads. CortenMM targets the harder combination of Linux-like semantics, high multicore performance, and stronger-than-testing correctness.

## Key Insight

The core claim is that, on mainstream ISAs, the software-level abstraction is now mostly legacy complexity. x86, ARM, and RISC-V all use closely related multi-level radix-tree page tables, and kernels already hide most ISA differences with language-level abstractions. If swapping, copy-on-write, or file-backed mappings need extra state, that state can live beside the page table rather than in a second address-space tree. Once there is only one abstraction, concurrency control can also be simplified: callers lock a virtual-address range, obtain a cursor, and then perform `query`, `map`, `mark`, or `unmap` atomically. Overlapping ranges serialize; disjoint ranges run in parallel.

## Design

CortenMM associates every page-table page with a page descriptor indexed by physical page number. Each descriptor stores the page lock and an on-demand per-PTE metadata array. That array records the minimal extra state the MMU cannot encode directly: whether a virtual page is invalid, reserved for anonymous allocation, mapped, file-backed, swapped out, and so on, together with permission bits and auxiliary metadata. This is how the system preserves Linux-style semantics without rebuilding a VMA layer.

Programming the MMU goes through a transactional interface. `AddrSpace::lock(range)` finds a covering page-table page for the range and returns an `RCursor`; the caller then composes `query`, `map`, `mark`, and `unmap`, and the whole sequence is atomic. The paper presents two locking protocols. `CortenMMrw` walks from the root with reader locks and then write-locks the covering page-table page. `CortenMMadv` traverses without locks under RCU, locks the covering page, then DFS-locks descendants; when concurrent `unmap` removes page-table pages, they are detached, marked stale, and freed only after an RCU grace period. On top of this interface, CortenMM implements `mmap`, `munmap`, `mprotect`, page faults, demand paging, copy-on-write, reverse mapping, file-backed mappings, swapping, and huge pages. The implementation is 8,028 lines of Rust, only 122 of them unsafe, and the verified transactional core is 829 lines.

## Evaluation

The evaluation runs on a 2-socket AMD EPYC 9965 machine with 384 cores and 1 TB DRAM, comparing against Linux 6.13.8, RadixVM, and NrOS. Single-thread results are already favorable: `CortenMMadv` beats Linux on four of five microbenchmarks, improving `mmap-PF` by 46.8%, page faults by 53.6%, `unmap-virt` by 76.9%, and `unmap` by 7.8%, while losing only 3.1% on plain `mmap` because it allocates page-table pages eagerly. The multicore results are much stronger. On low-contention microbenchmarks at 384 cores, `CortenMMadv` outperforms Linux by 33x on page faults and by 2270x on `unmap-virt`; even in high-contention settings it still leads by 3x to 1489x. Real applications show the same pattern when memory management is the bottleneck: JVM thread creation latency falls by 32% at 384 cores, Metis improves by 26x, dedup reaches 2.69x higher throughput than Linux at 64 threads, and psearchy is about 2x faster. By contrast, workloads that do not stress memory management, such as most PARSEC benchmarks, show little change but no regression.

The paper also measures engineering cost. The verified transactional interface has a 5.2:1 proof-to-code ratio, required roughly eight person-months, and verifies in under 20 seconds. Memory overhead remains close to Linux; even a worst-case fully populated metadata array would keep total overhead below 2%. The evidence supports the central claim, though some of the largest wins come from microbenchmarks intentionally stressing the memory-management fast path.

## Novelty & Impact

Relative to prior scalable-memory work, CortenMM's novelty is not a faster tree, a better range lock, or a more replicated page table. Its main move is to delete the software-level abstraction entirely and rebuild memory management around a transactional MMU interface whose concurrency semantics are simple enough to verify. That makes the paper both a concrete mechanism and a broader design argument: if two internal representations dominate a subsystem's synchronization cost, deleting one of them may improve both performance and proof tractability.

## Limitations

CortenMM is intentionally scoped to mainstream MMUs that look like multi-level radix-tree page tables, so it does not transfer cleanly to architectures with very different MMU organizations. It also currently lacks NUMA placement policy support. The proof boundary is narrower than the headline might suggest: what is formally verified is the concurrent MMU-manipulation core, namely the two locking protocols, the `RCursor` operations, and page-table well-formedness. The proof assumes a sequential memory model and trusts Verus, the SMT solver, the hardware, the rest of the OS, and the implementations of locks, RCU, and allocators. The verified code also lives in a separate Verus artifact rather than being linked directly into the shipping kernel. Performance is not universally better either: address-space-enumeration-heavy operations such as `fork` are 17.7% slower than Linux, and `CortenMMadv` stops scaling past about 64 threads under high contention on the same last-level page-table page.

## Related Work

- _Clements et al. (ASPLOS '12)_ — Scalable Address Spaces Using RCU Balanced Trees keeps the software-level address-space tree and makes it more concurrent, while CortenMM argues that deleting that layer is the cleaner solution.
- _Clements et al. (EuroSys '13)_ — RadixVM also pursues scalable address spaces with page-table-centric ideas, but it relies on private per-core page tables, omits several Linux-style semantics, and pays much higher memory overhead.
- _Bhardwaj et al. (OSDI '21)_ — NrOS applies node replication to OS state, including memory management, whereas CortenMM builds a memory-specific transactional interface that retains copy-on-write, swapping, reverse mapping, and file-backed mappings.
- _Klein et al. (SOSP '09)_ — seL4 proves a kernel at a much broader scope, while CortenMM verifies a narrower but highly concurrent memory-management core and spends its simplicity budget on performance.

## My Notes

<!-- empty; left for the human reader -->

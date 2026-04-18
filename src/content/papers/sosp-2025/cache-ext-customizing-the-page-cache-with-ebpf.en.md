---
title: "cache_ext: Customizing the Page Cache with eBPF"
oneline: "cache_ext turns Linux page-cache eviction into an in-kernel eBPF interface, so each cgroup can run workload-specific policies instead of one fixed LRU-style policy."
authors:
  - "Tal Zussman"
  - "Ioannis Zarkadas"
  - "Jeremy Carin"
  - "Andrew Cheng"
  - "Hubertus Franke"
  - "Jonas Pfefferle"
  - "Asaf Cidon"
affiliations:
  - "Columbia University"
  - "IBM Research"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764820"
code_url: "https://github.com/cache-ext/cache_ext"
tags:
  - caching
  - memory
  - kernel
  - ebpf
category: memory-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

cache_ext lets Linux run custom page-cache eviction policies as eBPF programs inside the kernel. Its per-cgroup, list-based interface can express policies from LFU and S3-FIFO to application-specific GET/SCAN prioritization, and those policies beat the stock page cache on the right workloads.

## Problem

Linux's page cache is still centered on an LRU approximation over active and inactive lists. The paper argues that this is a bad fit for scan-heavy workloads, mixed-priority database traffic, and workloads where frequency or request class matters more than recency; `madvise()`, `fadvise()`, and MGLRU still leave applications trapped inside kernel-defined policy structure.

Userspace delegation is not cheap enough either. A best-case design that only forwards cache events through eBPF ring buffers already loses 16.6%-20.6% on YCSB and 4.7% on file search, so the real task is to make eviction programmable while keeping the hot path in-kernel, preserving tenant isolation, and preventing unsafe folio references.

## Key Insight

cache_ext works because it exposes policy rather than kernel internals. Applications get five callbacks, kernel-managed eviction lists, and a batched candidate-selection interface: enough to express real algorithms, but small enough for the kernel to keep performance, sharing, and safety under control.

The other key choice is scope. Policies attach per cgroup rather than globally, so different workloads can run different eviction rules while still sharing cached pages.

## Design

cache_ext keeps policy execution in-kernel via `struct_ops` callbacks and kfuncs. The framework exposes five events: initialization, folio admission, folio access, folio removal, and eviction requests. Policies only nominate victims; the kernel still verifies that a folio is evictable and can fall back to its default path if a policy returns too few candidates.

The main abstraction is the eviction-list API. Policies can create one or more variable-sized linked lists, add or move folios, delete folios, and iterate with a callback. `list_iterate()` has a simple mode that walks until enough victims are found and a batch-scoring mode that scores a window before selecting the lowest-scoring folios. That is enough for FIFO and MRU, multi-list policies such as S3-FIFO and MGLRU, and score-based policies such as LFU and LHD; extra metadata such as frequencies or scan-thread IDs lives in eBPF maps.

The examples show the interface is broad enough to matter: S3-FIFO uses two lists plus a ghost queue, MGLRU uses generation lists and a PID controller, and GET-SCAN uses two LFU-like lists keyed by thread identity. LHD needs periodic reconfiguration and fixed-point arithmetic because eBPF lacks floating point, so the authors use a `BPF_PROG_TYPE_SYSCALL` path for that work. Isolation is per cgroup, safety comes from a valid-folios registry that validates every candidate before eviction, and the full prototype adds about 2,000 kernel lines, about 210 of them in the core page-cache path.

## Evaluation

The experiments run on CloudLab machines with a 16-core AMD Rome CPU, 128 GB of memory, a 480 GB SSD, and Linux 6.6.8. The workload mix includes YCSB and Twitter cache traces on LevelDB, scan-heavy file search, mixed GET/SCAN traffic, multi-cgroup isolation, and overhead microbenchmarks.

On a 100 GiB LevelDB database in a 10 GiB cgroup, cache_ext's LFU beats the default Linux policy by up to 37% throughput and cuts P99 read latency by up to 55%; LHD is usually close behind. On Twitter cache traces, however, no single policy dominates: LHD wins on cluster 34, LFU on cluster 52, and MGLRU wins on clusters 17 and 18. That negative result supports the paper's thesis that the win is programmability, not a universally better algorithm.

The strongest workload-specific result is file search over the Linux source tree: cache_ext's MRU is almost 2x faster than both the default policy and MGLRU because recency is the wrong signal for repeated scans. The GET-SCAN policy is also convincing: separating point-query pages from scan pages improves GET throughput by 70% and lowers GET P99 latency by 57%, though SCAN throughput drops by 18%. A compaction admission filter for RocksDB lowers P99 latency by 17%.

Overhead is low enough to make the design credible. The valid-folios registry costs 0.4%-1.2% of cgroup memory, a no-op policy adds at most 1.7% CPU overhead in `fio`, and a cache_ext reimplementation of MGLRU is within 1% of native-kernel MGLRU on YCSB. The isolation experiment also shows why per-cgroup policy matters: a tailored LFU+MRU setup improves YCSB by 49.8% and file search by 79.4% over the all-default baseline. The main caveat is that most evidence centers on file-backed, `pread()`-oriented workloads rather than `mmap()`-heavy ones.

## Novelty & Impact

The paper's novelty is not a new eviction algorithm. It is a kernel interface design that makes modern cache-policy research deployable inside Linux without a custom kernel fork for every idea. Compared with prior page-cache customization efforts, cache_ext is more expressive than single-queue eBPF proposals, avoids the hot-path cost of userspace delegation, and explicitly addresses multi-tenant isolation and safety.

That matters for both researchers and operators: ideas such as LHD, S3-FIFO, or application-specific rules become testable against the real Linux page cache with a few hundred lines of policy code rather than a deep kernel patch.

## Limitations

cache_ext is not evidence that one better default exists; the Twitter-trace results show the opposite. Users still need to choose or build policies that match their workloads, and some choices can be actively harmful, as MRU on YCSB demonstrates.

There are also technical limits. Some policies are only approximate because eBPF still lacks mature general-purpose data structures and floating-point support; LHD needs a special reconfiguration path and fixed-point arithmetic. Isolation is imperfect when cgroups share files, loading policies requires root privileges, and the evaluation focuses mostly on file-backed access with LevelDB often forced to use `pread()` instead of `mmap()`.

## Related Work

- _Yelam et al. (USENIX ATC '25)_ — PageFlex also uses eBPF for Linux paging customization, but it delegates policy work to userspace and focuses on paging and prefetching rather than in-kernel file-cache eviction.
- _Cao et al. (USENIX ATC '24)_ — FetchBPF makes Linux prefetching programmable with eBPF, whereas cache_ext tackles the harder problem of eviction policies, richer data structures, and per-cgroup isolation.
- _Beckmann et al. (NSDI '18)_ — LHD shows that sophisticated probability-based eviction can outperform simple recency heuristics, and cache_ext turns that kind of algorithm into something the Linux page cache can actually host.

## My Notes

<!-- empty; left for the human reader -->

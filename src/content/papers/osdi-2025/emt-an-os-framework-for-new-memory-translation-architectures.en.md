---
title: "EMT: An OS Framework for New Memory Translation Architectures"
oneline: "EMT refactors Linux translation around MMU drivers so schemes like ECPT and FPT plug in with near-zero overhead, while exposing OS bottlenecks hardware-only studies miss."
authors:
  - "Siyuan Chai"
  - "Jiyuan Zhang"
  - "Jongyul Kim"
  - "Alan Wang"
  - "Fan Chung"
  - "Jovan Stojkovic"
  - "Weiwei Jia"
  - "Dimitrios Skarlatos"
  - "Josep Torrellas"
  - "Tianyin Xu"
affiliations:
  - "University of Illinois Urbana-Champaign"
  - "University of Rhode Island"
  - "Carnegie Mellon University"
conference: osdi-2025
code_url: "https://github.com/xlab-uiuc/emt"
tags:
  - kernel
  - memory
  - hardware
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

EMT is a Linux framework that replaces hardwired page-table assumptions with an MMU-driver interface built around translation objects, translation databases, and translation services. That lets the authors support radix, ECPT, and FPT on one kernel with negligible interface cost, while also revealing OS-level correctness and performance issues that architecture-only evaluations miss.

## Problem

Memory translation is becoming a first-order bottleneck because memory capacity keeps growing while TLB reach does not, and newer workloads such as ML, graph analytics, and bioinformatics have poor locality. On x86-64, a TLB miss already triggers a multi-level radix-tree walk; with nested translation in virtualized settings, the walk can require up to 24 sequential memory accesses on four-level tables. Hardware researchers have responded with faster MMU designs such as hashed, flattened, and hybrid page tables.

The paper argues that commodity OS support has not kept up. Linux memory management is full of architecture-independent code that still assumes a radix tree: adjacent entries can be reached by pointer arithmetic, a PMD either names a huge page or a lower-level directory, and range queries can infer emptiness from intermediate tree nodes. As a result, evaluating a new translation architecture usually means simulating hardware while assuming OS overhead stays constant. EMT's starting point is that this assumption is wrong: the translation architecture changes what the kernel must do on page faults, range scans, locking, swapping, and huge-page management.

## Key Insight

The key claim is that the OS should abstract the function of translation, not the hardware-shaped data structure that happens to implement it. Linux does not need to know whether a mapping lives in a radix tree, a hashed table, or a flattened structure; it needs a way to query and update one virtual-to-physical mapping plus its metadata, to manage an address space as a collection of such mappings, and to switch MMU state across contexts.

EMT therefore splits the interface into a small architecture-neutral core and optimization hooks. The core is strong enough to let a new MMU scheme plug into Linux without rewriting generic memory-management code, while the hooks preserve the low-level fast paths that make Linux competitive in the first place. That combination is the paper's real contribution: extensibility without forcing Linux into a high-level, optimization-hostile abstraction.

## Design

EMT organizes translation around three primitives. A translation object represents one mapping and its metadata, such as physical address, size, permissions, presence, dirty state, swap encoding, or architecture-specific attributes like protection keys. A translation database represents the address space that stores those objects; it may be a radix tree, multiple ECPT hash tables, or another hardware-defined structure. A translation service manages MMU state such as creating, destroying, and switching translation databases on context switches.

The API is divided into 15 basic functions and 35 customizable functions. Every MMU driver must implement the basic operations, such as finding a translation object, updating it, or switching an address space. Customizable functions have architecture-neutral defaults but may be overridden when a scheme has a better fast path. The paper's representative example is iteration over a range of translations: the default version repeatedly calls `tdb_find_tobj`, while the x86 radix driver exploits spatial locality and advances a pointer directly. Similar hooks exist for range locking, huge-page eligibility, swap handling, and address-range emptiness checks.

The Linux port is substantial but disciplined. EMT-Linux on Linux 5.15 rewrites 196 kernel functions in `mm/`, moving translation-specific logic into MMU drivers while preserving existing features and optimizations such as split page-table locks, huge pages, swapping, DAX, and MPK. The x86-64 radix driver provides the baseline. The FPT driver reuses much of that code and adds support in 664 lines without changing architecture-neutral modules. The ECPT case is more demanding: the authors build a 7.4 KLOC MMU driver plus a QEMU-based emulated MMU toolchain so the OS can run on hardware that does not yet exist.

## Evaluation

The first result is that EMT itself is cheap. EMT-Linux with Radix, ECPT, and FPT drivers passes all 1,208 applicable Linux Test Project tests, covering 376 system calls. Against vanilla Linux on a dual-socket Xeon server, EMT-Linux reaches 99.9% normalized performance on average across 41 LEBench microbenchmarks, with the worst case being a 4.2% slowdown on `epoll big`; on the paper's macro benchmarks the overhead stays below 0.1%, and Redis, Memcached, and PostgreSQL differ from vanilla Linux by at most about 0.1% in throughput and average latency.

The more interesting result is what EMT reveals about ECPT from the OS side. In hardware simulation, ECPT speeds up page-table walks by 23.1% on average and raises IPC by 7.0% relative to x86-64 radix translation. But once the real Linux kernel is in the loop, those hardware gains are diluted by extra kernel work: ECPT causes 1.74x more page-fault-handling instructions on average with 4 KB pages and 2.59x more with THP enabled, largely because sparse range checks that are cheap in a tree become expensive in an independent-entry hash structure. As a result, total cycles improve by only 2.3% on average across workloads, although GUPS and Memcached still improve by 11.5% and 12.9%.

EMT also exposes optimization opportunities. A customized ECPT iterator that exploits locality inside entry clusters cuts total kernel work by 49.0% and page-fault-handling work by 52.5% on GraphBIG BFS with THP. The paper's broader point is that hardware metrics alone are insufficient: faster walks and higher IPC do not automatically translate into faster applications when the translation architecture changes the kernel's control path.

## Novelty & Impact

Compared with _Rashid et al. (ASPLOS '87)_, EMT is not a classic `pmap`-style separation that hides the machine under a narrow mapping API; it intentionally keeps room for Linux's low-level optimization patterns. Compared with _Skarlatos et al. (ASPLOS '20)_ and _Park et al. (ASPLOS '22)_, it is not another translation architecture but the missing OS substrate that makes ECPT- or FPT-like proposals runnable on a commodity kernel. Compared with _Tabatabai et al. (USENIX ATC '24)_, which makes memory-management policy more extensible, EMT targets the translation architecture itself.

That makes EMT important for both hardware and systems researchers. The framework provides an open platform for implementing new MMUs on real Linux, and the ECPT case study shows why that matters: once the OS is involved, new issues appear, including kernel-page-table self-reference, atomic switching of kernel translation state, sparse-range management, and locking tradeoffs that architecture-only simulators would miss.

## Limitations

EMT's scope is narrower than "all memory management." It focuses on CPU virtual-to-physical translation, not IOMMU translation, physical-page operations, or designs that expose physical addresses directly to software. Virtualization support is planned rather than implemented, and the paper argues for generality mainly through three schemes: x86 radix, FPT, and ECPT.

The ECPT experience also shows that EMT does not make hard OS problems disappear. Kernel-page-table management required extra hardware support for atomic switching between kernel ECPT states, and the implementation still uses coarse-grained locking while the authors explore better multicore locking. The evaluation is strong, but part of it still depends on emulation and trace-driven hardware simulation rather than manufactured MMU hardware.

## Related Work

- _Rashid et al. (ASPLOS '87)_ - Mach's `pmap` separates machine-independent memory management from hardware mapping, while EMT argues Linux needs lower-level hooks to preserve performance-critical optimizations.
- _Skarlatos et al. (ASPLOS '20)_ - ECPT proposes elastic cuckoo page tables; EMT provides the Linux substrate needed to implement and evaluate that idea as a real OS stack.
- _Park et al. (ASPLOS '22)_ - FPT shortens radix-tree walks by flattening levels, and EMT shows such a design can live behind an MMU driver rather than a cross-cutting kernel rewrite.
- _Tabatabai et al. (USENIX ATC '24)_ - FBMM makes memory-management policy extensible via filesystem-style interfaces, whereas EMT specifically targets extensibility across hardware translation architectures.

## My Notes

<!-- empty; left for the human reader -->

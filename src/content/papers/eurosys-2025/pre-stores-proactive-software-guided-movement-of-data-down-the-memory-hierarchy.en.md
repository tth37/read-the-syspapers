---
title: "Pre-Stores: Proactive Software-guided Movement of Data Down the Memory Hierarchy"
oneline: "Pre-Stores treats downward movement of dirty data as a software hint, using DirtBuster to place clean, demote, or cache-skipping where writes actually hurt."
authors:
  - "Xiaoxiang Wu"
  - "Baptiste Lepers"
  - "Willy Zwaenepoel"
affiliations:
  - "University of Sydney, Sydney, Australia"
  - "Inria, Grenoble, France"
  - "University of Neuchâtel, Neuchâtel, Switzerland"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696097"
tags:
  - memory
  - persistent-memory
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pre-Stores argues that software should initiate dirty-data movement downward just as prefetch initiates movement upward. It reuses existing cache-control instructions plus an offline analysis tool, DirtBuster, to decide where `clean`, `demote`, or cache-skipping help. On heterogeneous memory systems, the paper reports up to 47% higher TensorFlow throughput, up to 40% lower NAS runtime, and up to 62% lower X9 message latency.

## Problem

CPU caches were designed assuming the medium below them looks like DRAM. The paper argues that this assumption breaks on emerging memory hierarchies such as Optane PMEM, CXL-style attached memory, and cache-coherent accelerator memory. The first failure mode is write amplification: software may write data sequentially, but the cache evicts dirty lines in pseudo-random order. On the paper's Intel-plus-Optane machine, the CPU writes back 64 B cache lines while PMEM internally writes 256 B units, so random eviction turns a sequential stream into 180% write amplification with one thread and about 330% with two or more.

The second failure mode is delayed visibility. On weaker-memory systems, CPUs may keep recent writes private until a fence or atomic instruction forces them outward. If the next visible level is high-latency coherent memory, that "last minute" propagation stalls the pipeline. On the paper's Arm-plus-FPGA machine, a simple benchmark improves by up to 65% when the write propagation is started early instead of waiting for the fence. Existing software hints help reads via prefetch; the paper's point is that the write side lacks an equivalent abstraction.

## Key Insight

The central claim is that downward movement of dirty data should be treated as an explicit, software-guided optimization problem. A pre-store is the write-side analogue of a prefetch: software asks hardware to move data to a more public cache level or toward memory before the architecture is forced to do so. `clean` is useful when the goal is to make writeback more sequential; `demote` is useful when a later fence or atomic would otherwise pay the visibility cost synchronously.

The important qualifier is that the right hint depends on observed reuse. Data that will be reread should stay cached after an early writeback; data that will be rewritten should not be flushed away; data that will never be touched again is better skipped past the cache entirely with non-temporal stores. DirtBuster therefore turns pre-storing into a profile-guided decision over binaries and libraries rather than a manual guess.

## Design

The paper exposes a simple abstraction, `prestore(location, size, op)`, with two operations. `clean` starts a non-blocking writeback from cache to memory but keeps the line cached. `demote` pushes data downward within the hierarchy, for example from a private buffer or L1 toward a more globally visible level. On x86, these map to instructions such as `clwb` and `cldemote`; on Arm, the paper uses cache-maintenance instructions such as `dc cvau`. If data will neither be reread nor rewritten, the paper treats non-temporal stores as the third option: bypass the cache entirely.

DirtBuster has three stages. First, it uses `perf` sampling to find write-intensive functions and call chains with under 1% overhead. Second, it uses Intel PIN to log all reads, writes, and fence-like instructions in those regions, then reconstructs sequential-write contexts and the distance from a write to the next fence or atomic. Third, it computes re-read and re-write distances per cache line. The recommendation rule is the paper's real contribution: use `demote` when data is rewritten and must become visible before a fence, use `clean` when data will be reread, and prefer non-temporal stores when the data will be neither reread nor rewritten. The tradeoff is that this stage is offline and intrusive: the instrumentation phase can slow execution by up to 25x, and developers still patch the code manually.

## Evaluation

The evaluation is organized around two platforms chosen to match the two motivating pathologies. Machine A is a Xeon Gold 6230 with 128 GB DRAM and 8 x 128 GB Optane PMEM, where the key problem is 64 B cache lines feeding a 256 B PMEM write unit. Machine B is an Enzian system with a 48-core Arm ThunderX-1 and a cache-coherent FPGA configured either as a 60-cycle, 10 GB/s device or a 200-cycle, 1.5 GB/s device, where the key problem is expensive visibility across a coherent path.

The strongest TensorFlow result comes from a single Eigen loop: adding one `clean` pre-store improves training throughput by up to 47% and reduces measured write amplification from 3.7x to 2.7x. In the NAS suite, patching MG, FT, SP, UA, and BT reduces runtime by up to 40%. On YCSB-A, the biggest gains come when DirtBuster recommends cache-skipping: CLHT reaches up to 2.9x the baseline and Masstree up to 2.5x. The smaller one-line `clean` patch still matters, reaching up to 2.3x on CLHT and 1.9x on Masstree. On Machine B, where the benefit is overlapping visibility rather than improving sequentiality, `clean` improves CLHT by 52% and Masstree by 25% for 1 KB values, and adding a `demote` in X9 cuts message-send latency by 62% on the fast FPGA configuration and 40% on the slow one.

The evaluation supports the paper's core claim reasonably well. The workloads exercise exactly the proposed bottlenecks, and the negative cases are informative: read-mostly YCSB workloads are not patched, pre-stores on Machine B give no benefit to the TensorFlow and NAS cases that lack the relevant pathology, and DirtBuster-approved insertions on architectures with no expected benefit add at most 0.3% overhead. This is not a broad systems bake-off, but it is a convincing mechanism study.

## Novelty & Impact

The novelty is not a new ISA feature. The paper's contribution is to reframe existing cache-control instructions as a general performance primitive for heterogeneous memory systems and to pair that framing with a concrete analysis workflow. Prior PMEM work largely used `clwb`-like instructions for correctness and persistence ordering; Pre-Stores argues they are also useful as ordinary performance hints for write-heavy code. That should make the paper relevant to systems work on PMEM-like tiers, coherent accelerators, and future CXL-attached memory, as well as to compiler and binary-optimization work that wants a principled way to reason about write propagation.

## Limitations

The win condition is narrow. Workloads must be write-heavy, and those writes must either form sufficiently long sequential streams or sit close enough to fences and atomics that early propagation can be overlapped. Read-heavy workloads do not benefit. Misuse can be severe: a microbenchmark that repeatedly rewrites the same cache line becomes 75x slower with unnecessary cleaning, and a manual pre-store in NAS FT causes a 3x slowdown.

DirtBuster is also explicitly offline, intrusive, and architecture-aware. The best optimization sometimes requires non-temporal stores rather than a one-line pre-store, which means more invasive, ISA-specific changes. The evaluation covers only two hardware families and a selected set of write-heavy applications, so the paper proves the idea is real but does not show that pre-store placement can be made universal or fully automatic.

## Related Work

- _Shin et al. (ISCA '17)_ - hides PMEM persist-barrier latency with speculation, whereas Pre-Stores uses the same class of instructions as general write-side performance hints.
- _Wu et al. (PACT '20)_ - Ribbon accelerates cache-line flushing for persistent memory, while Pre-Stores broadens the goal to write amplification and fence-visible latency on heterogeneous memories.
- _Khan et al. (HPCA '14)_ - read/write cache partitioning changes cache-space allocation, whereas Pre-Stores changes when dirty data is pushed downward.
- _Lepers and Zwaenepoel (OSDI '23)_ - Johnny Cache redesigns data placement for tiered memory sequentiality, while Pre-Stores leaves the data structure intact and patches specific write sites.

## My Notes

<!-- empty; left for the human reader -->

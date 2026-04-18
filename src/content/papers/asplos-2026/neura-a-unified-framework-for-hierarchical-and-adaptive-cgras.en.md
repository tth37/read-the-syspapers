---
title: "Neura: A Unified Framework for Hierarchical and Adaptive CGRAs"
oneline: "Builds a hierarchical spatial-temporal CGRA plus migration-aware mapping so kernels can expand, split, and reclaim idle sub-CGRAs at runtime."
authors:
  - "Cheng Tan"
  - "Miaomiao Jiang"
  - "Yuqi Sun"
  - "Ruihong Yin"
  - "Yanghui Ou"
  - "Qing Zhong"
  - "Lei Ju"
  - "Jeff Zhang"
affiliations:
  - "Google, Mountain View, CA, USA"
  - "Arizona State University, Tempe, AZ, USA"
  - "Shandong University, Qingdao, Shandong, China"
  - "Independent Researcher, Qingdao, Shandong, China"
  - "University of Minnesota Twin Cities, Minneapolis, MN, USA"
  - "Cornell University, Ithaca, NY, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790193"
code_url: "https://github.com/tancheng/CGRA-Flow/tree/neura-asplos-ae"
tags:
  - hardware
  - compilers
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Neura argues that scalable spatial-temporal CGRAs need the compiler's mapping granularity to be decoupled from the hardware's runtime acceleration granularity. It therefore builds a hierarchical multi-CGRA fabric, a migration-aware mapper, and a simple runtime that can fuse kernels onto one sub-CGRA, later split them apart, or expand a running kernel across more sub-CGRAs without recompilation. On periodic multi-kernel workloads, that combination yields `1.64x-3.85x` throughput speedups over a same-scale monolithic baseline.

## Problem

The paper starts from a familiar CGRA scaling failure. If a spatial-temporal CGRA is made larger, mapping gets harder because the search space grows combinatorially, but utilization does not improve automatically. Small kernels leave most tiles idle; large kernels often end up with worse initiation intervals because the mapper cannot find good placements quickly enough. In conventional designs, the compiler maps onto one monolithic fabric at compile time, and that mapping effectively fixes the runtime acceleration granularity too.

That coupling becomes especially painful for dynamic multi-kernel execution. Real systems launch kernels at different times and with different lifetimes, so idle capacity appears and disappears during execution. Existing CGRAs either run one kernel at a time or statically partition the array, which means they cannot react well when one kernel finishes and another could use the newly freed resources. The paper's thesis is that mapping scalability, architectural flexibility, and multi-kernel runtime support are not separate annoyances; together they block CGRAs from scaling as a general platform.

## Key Insight

Neura's key claim is that a scalable spatial-temporal CGRA should compile for a manageable unit, then let the runtime decide how many such units a kernel actually occupies. In other words, mapping granularity and acceleration granularity should be different knobs. If a kernel is small, several kernels can share one CGRA. If a kernel later deserves more resources, the runtime can migrate part of its mapping onto neighboring CGRAs instead of accepting the original allocation forever.

That only works if the architecture tolerates variable communication latency. Once a kernel spans multiple sub-CGRAs and may fetch remote SRAM data, the old clock-driven assumption of fixed per-operation latency breaks. Neura therefore combines hierarchical hardware with data-driven execution and a migration-aware mapper that keeps critical-path operations anchored while treating non-critical operations as movable slack. The paper's synthetic example makes the point clearly: by moving only non-critical operations, a kernel's II drops from `3` to `2` during execution.

## Design

Neura organizes the fabric as a mesh of CGRAs, with each sub-CGRA containing `4x4` tiles and eight SRAM banks. Adjacent CGRAs are not isolated islands: boundary tiles remain connected through crossbars, and all SRAM banks share a global address space reachable through the inter-CGRA NoC. Each CGRA also has its own controller that delivers control signals over a separate lightweight ring, so control delivery does not fight with datapath traffic. At the tile level, Neura includes scalar FUs plus four-lane vector FUs.

On top of that hardware, the paper defines several execution modes. A large kernel can be mapped across multiple CGRAs from the start. Several small kernels can instead be fused into one DFG and packed onto a single CGRA, then later redistributed if more resources become available. Scalar kernels can expand by migrating non-critical operations in a mirrored way onto a neighboring CGRA; vector kernels can expand when the compile-time vectorization factor exceeds the lanes available in one sub-CGRA. All of these modes can coexist on the same fabric.

The compiler is responsible for preserving that flexibility. Built on LLVM, it performs vectorization and unrolling, constructs DFGs, optionally fuses multiple kernels, and then emits migratable mappings. The important policy is to place the critical path first so the mapping gets as close as possible to `criticalII`, then schedule non-critical operations into later slack slots so they become migration candidates. The runtime itself is intentionally simple: it runs on the host CPU, tracks kernel completion, uses `FCFS` with priority boosting, never revokes already assigned CGRAs, and lets an under-provisioned head-of-line kernel absorb newly freed CGRAs. The paper says the reconfiguration overhead is usually only dozens of cycles.

## Evaluation

The evaluation uses ten kernels from embedded, ML, and HPC workloads, then builds six periodic execution cases that range from dense arrivals to sparse arrivals. Neura's main comparison is against a same-scale monolithic `12x12` spatial-temporal CGRA with `144` tiles and no multi-kernel support; the evaluated Neura prototype is a `3x3` grid of `4x4` sub-CGRAs, also totaling `144` tiles. The ablation from `Neura-L0` through full `Neura` is useful because it isolates how much benefit comes from hierarchy alone versus scalar migration, multi-kernel migration, and vector expansion.

The headline numbers support the paper's central claim. Compared with the baseline, total execution time improves by `1.44x-2.17x` in cases 2-6, while workload throughput improves by `1.64x-3.85x` across cases 1-6. The gains get larger as arrivals become sparser, which matches the design intuition: more temporal slack means more opportunities to reallocate idle sub-CGRAs. The paper also reports that the hierarchical `Neura-L0` design alone gives up to `2.3x` throughput speedup in the sparsest case, while the full dynamic mechanisms add up to another `1.67x` on top. Utilization reaches nearly `99%` in dense cases and stays above `56.66%` even in the sparsest one.

The scaling experiment is also strong. On a synthetic high-density workload, overall throughput speedup rises from `5.3x` to `25.8x` as the fabric grows from `2x2` to `5x5` Neura CGRAs, while utilization stays above `86%`. Physical-design results are more modest but still informative: the `3x3` Neura layout at ASAP7, `0.7V`, and `400MHz` consumes `489.7 mW` and incurs about `10%` area and `10.2%` power overhead over a `12x12` monolithic baseline. I found the ablations convincing, but the broader comparison to prior platforms is necessarily weaker because the authors themselves note the technology stacks and hardware assumptions are not directly matched.

## Novelty & Impact

Relative to HierCGRA and other hierarchical CGRA proposals, Neura's real novelty is not hierarchy alone but hierarchy plus runtime migration and mappings deliberately structured to make that migration safe. Relative to vector-CGRA work such as FLEX or VecPAC, its contribution is not merely adding vector lanes, but allowing vectorized kernels to consume more sub-CGRAs dynamically when one sub-CGRA's lanes are insufficient. Relative to multi-kernel runtime systems such as DRIPS or ICED, Neura tries to unify architecture, compiler, runtime, RTL generation, and physical-design exploration in one open-source framework.

That makes the paper likely to matter to three groups: researchers building scalable CGRA architectures, compiler authors working on placement and scheduling under dynamic hardware availability, and practitioners who want an end-to-end open-source platform rather than a point solution. The work reads as a new systems mechanism packaged as a full-stack research artifact, not just a benchmark win.

## Limitations

Neura's migration story is deliberately constrained. Dynamic allocation happens at per-CGRA granularity, scalar migration only moves non-critical operations, and the paper's mirrored migration pattern is much simpler than fully general remapping. The runtime policy is also intentionally basic: `FCFS` with priority boosting on the host CPU, no revocation of granted resources, and future work left for richer schedulers or dedicated hardware support.

The evaluation is broad inside the paper's chosen world, but that world is still mostly periodic kernel mixes on a cycle-accurate simulator. The physical-design results cover the proposed architecture, yet the cross-platform power/performance comparison in Figure 13 is explicitly not apples-to-apples. I would also treat the paper as strongest on concurrent multi-kernel throughput and utilization, not as a definitive answer on how to schedule arbitrary real applications with unpredictable memory behavior.

## Related Work

- _Prabhakar et al. (MICRO '24)_ — SN40L shows how hierarchical dataflow hardware can scale out, whereas Neura keeps a spatial-temporal CGRA model and adds migration-aware runtime expansion.
- _Bandara et al. (ICCAD '23)_ — FLEX enables vector execution on CGRAs, while Neura folds vector support into a hierarchical fabric that can spread one vectorized kernel across multiple sub-CGRAs.
- _Gobieski et al. (MICRO '22)_ — RipTide is a spatial-only, ultra-low-power dataflow design; Neura instead keeps temporal reconfiguration to better support large irregular kernels and runtime migration.
- _Tan et al. (HPCA '22)_ — DRIPS dynamically rebalances pipelined streaming applications on CGRAs, whereas Neura targets a more general hierarchical multi-kernel execution model.

## My Notes

<!-- empty; left for the human reader -->

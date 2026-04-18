---
title: "LithOS: An Operating System for Efficient Machine Learning on GPUs"
oneline: "LithOS turns the CUDA driver boundary into a GPU OS layer that atomizes kernels, schedules them at TPC granularity, and trades small latency slips for higher utilization and lower energy."
authors:
  - "Patrick H. Coppock"
  - "Brian Zhang"
  - "Eliot H. Solomon"
  - "Vasilis Kypriotis"
  - "Leon Yang"
  - "Bikash Sharma"
  - "Dan Schatzberg"
  - "Todd C. Mowry"
  - "Dimitrios Skarlatos"
affiliations:
  - "Carnegie Mellon University"
  - "Meta"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764818"
tags:
  - scheduling
  - gpu
  - ml-systems
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

LithOS inserts an OS-like control layer under CUDA, schedules work at NVIDIA TPC granularity, and transparently splits long kernels into smaller atoms so latency-sensitive and best-effort ML jobs can share one GPU without coarse partitioning. On an A100, this cuts inference tail latency by up to 13x versus MPS while also enabling about 26% mean capacity savings from right-sizing and 26% mean energy savings from DVFS.

## Problem

The paper starts from a practical datacenter problem rather than a microbenchmark curiosity. Meta's study shows GPU device utilization often between under 25% and above 60%, while SM utilization can drop below 15%. Small serving batches, bursty demand, and large differences in model size and popularity leave expensive GPUs partially idle even as power and supply constraints tighten.

Existing transparent sharing mechanisms force a bad tradeoff. Temporal schemes such as time slicing and TGS preserve compatibility but leave concurrency on the table; spatial schemes such as MPS and MIG allow overlap but either cause interference or waste capacity through coarse GPC partitions and slow reconfiguration. Once a kernel has entered the driver and hardware queues, software also cannot cheaply reorder it, resize it, or power-manage it. LithOS therefore argues that GPU sharing needs an OS-style control point below frameworks and above the vendor driver.

## Key Insight

LithOS's central claim is that the right scheduling units are the TPC for space and the atom for time. TPCs are much finer than MIG partitions yet still coarse enough to preserve compiler and intra-SM optimizations. Atoms are runtime-created subsets of thread blocks that let software regain scheduling opportunities between pieces of a long kernel even without hardware preemption.

With per-stream launch queues beneath the CUDA Driver API, LithOS can delay dispatch and use one control point for TPC stealing, right-sizing, and DVFS. The core insight is therefore not just finer scheduling, but that a driver-level OS layer becomes powerful once kernels are decomposed into schedulable atoms.

## Design

LithOS is a Rust library that interposes on the CUDA Driver API. Each stream gets a launch queue, applications receive TPC quotas, and CPU-side dispatcher and tracker threads decide when work enters hardware queues and when completed work frees resources. The TPC scheduler can lend idle TPCs to other jobs, but it uses online latency prediction, low hardware stream priority, and caps on outstanding stolen work to bound priority inversion.

The key enabler is the Kernel Atomizer. LithOS patches launch metadata so execution starts in a small Prelude kernel that checks each thread block's global block index and jumps to the original kernel only for a chosen range. By relaunching the same kernel with non-overlapping ranges, LithOS turns one kernel into multiple atoms without source, PTX, compiler, or framework changes. Atom size is chosen from predicted runtime and a target atom duration of about 250 to 500 microseconds, which cuts head-of-line blocking and allows TPC reallocations at atom boundaries.

On top of that control plane, LithOS adds right-sizing and DVFS. Right-sizing fits a simple `l = m / t + b` model from one-TPC and full-TPC measurements plus an occupancy filter for outliers, then chooses the smallest TPC count that stays within a user-selected latency-slip budget. DVFS computes a weighted frequency sensitivity across a kernel sequence and picks a conservative device frequency that stays within the same budget. Both mechanisms depend on an online predictor keyed by launch queue and the kernel's ordinal position within a batch.

## Evaluation

The prototype is evaluated mainly on a single A100 server against NVIDIA time slicing, MPS, priority scheduling, MIG, and prior systems TGS, REEF, and Orion. In inference-only stacking with two high-priority services and one best-effort job, LithOS is the only system that simultaneously reaches 100% SLO attainment and normalized throughput 1.0. MPS reaches 1.11 throughput, but only 45% SLO attainment; MIG and thread limits protect latency by leaving slack stranded.

Tail latency numbers explain the difference. Across model combinations, LithOS improves high-priority tail latency by up to 13x over MPS, about 4x over Orion, and about 1.2x over TGS. In inference-plus-training stacking, it reduces service tail latency by 4.7x over MPS and by 1.18x over the best prior system while improving aggregate throughput by 1.35x. The ablation study shows that TPC scheduling throttles interference, but atomization delivers the extra gain by breaking up long best-effort kernels.

The efficiency results are also meaningful. With a latency slip of 1.1, right-sizing saves up to 51% of GPU capacity and 26% on average, while mean P99 increase and throughput loss are both about 4%. DVFS saves up to 46% of GPU energy and 26% on average with about 7% mean P99 increase. These numbers support the paper's main claim that transparent, compute-centric GPU OS control can improve both utilization and efficiency.

## Novelty & Impact

Relative to TGS, LithOS adds true TPC-granular spatial control instead of mostly temporal sharing. Relative to REEF and Orion, it does not depend on framework changes or heavy offline profiling, because it learns online at the driver boundary. The real contribution is therefore a substrate: atomization, TPC scheduling, right-sizing, and DVFS are unified as OS functions rather than presented as isolated serving tricks.

That framing matters to both systems researchers and GPU architects. LithOS offers a concrete model for a GPU OS and also identifies missing hardware support, including explicit kernel-to-SM placement, finer-grained preemption, and faster DVFS.

## Limitations

The prototype depends on reverse-engineered NVIDIA internals such as QMD patching and TPC mappings, and concurrent contexts still ride on MPS. LithOS also does not offer true preemption: atomization only helps at atom boundaries, so already running work can still delay urgent requests.

The evaluation is mostly single-A100, so generality across GPU generations is argued more than measured. Bandwidth isolation is largely out of scope, and the authors estimate another 4% to 13% could be gained in contention-heavy cases. DVFS is device-wide and slow to switch, around 50 ms, which forces conservative policies. Finally, REEF and Orion are reimplemented rather than run from original artifacts, so the comparison is careful but not perfectly artifact-identical.

## Related Work

- _Wu et al. (NSDI '23)_ — TGS transparently shares GPUs across containers, but it remains primarily temporal, whereas LithOS combines temporal control with TPC-granular spatial scheduling and atomization.
- _Han et al. (OSDI '22)_ — REEF delivers microsecond-scale GPU preemption for DNN inference, while LithOS generalizes the goal into a driver-level OS substrate for unmodified applications.
- _Strati et al. (EuroSys '24)_ — Orion uses interference-aware GPU sharing with offline profiling and application cooperation, whereas LithOS emphasizes online learning and transparency below the framework layer.
- _Ng et al. (SOSP '23)_ — Paella is a software-defined scheduler for low-latency model serving, while LithOS broadens the scope to an OS-like resource manager that also right-sizes hardware and manages power.

## My Notes

<!-- empty; left for the human reader -->

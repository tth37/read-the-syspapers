---
title: "CRAVE: Analyzing Cross-Resource Interaction to Improve Energy Efficiency in Systems-on-Chip"
oneline: "CRAVE learns CPU-GPU-memory DVFS coupling offline, then uses a runtime dominant-resource utility to apply coordinated frequencies that improve mobile-SoC performance and energy."
authors:
  - "Dipayan Mukherjee"
  - "Sam Hachem"
  - "Jeremy Bao"
  - "Curtis Madsen"
  - "Tian Ma"
  - "Saugata Ghose"
  - "Gul Agha"
affiliations:
  - "Univ. of Illinois Urbana-Champaign"
  - "Sandia National Labs"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717498"
code_url: "https://github.com/dipayan2/CRAVE_Artifact_EuroSys"
tags:
  - energy
  - hardware
  - memory
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CRAVE argues that DVFS decisions on mobile SoCs should not be driven only by the currently busy component. Because CPU cores, the GPU, and memory interfere through shared memory, the right frequency for one resource depends on the others. CRAVE learns those platform-specific interactions once, then uses a runtime dominant-resource metric to pick a coordinated CPU/GPU/memory setting, improving both latency and energy on ODROID-XU4 and Jetson TX2.

## Problem

Mobile SoCs expose DVFS controls for several components, but mainstream governors still act mostly locally. Built-in Linux governors look at per-resource utilization, while prior cooperative schemes often depend on workload-specific training or QoS feedback such as frame rate. The paper argues that both approaches miss a structural fact of SoC design: CPU, GPU, and DRAM share a tightly coupled memory system, so changing one frequency can change the performance and power of the others.

The authors show this is not a small effect. On real boards, memory frequency scaling substantially changes CPU and GPU benchmark performance, and can also change their power draw. A governor that reacts only to CPU or GPU utilization can therefore scale the wrong resource, wasting energy while leaving the true bottleneck untouched, especially for heterogeneous workloads whose dominant resource changes over time.

## Key Insight

The central claim is that cross-resource coupling is a property of the platform, not just of a particular application, so a governor can learn it once offline and reuse it across workloads. CRAVE therefore separates platform characterization from runtime control. It measures how CPU, GPU, and memory frequencies affect one another's performance and power, distills that into small tables, and then uses those tables online. This framing also makes memory a first-class dominant resource: because CPU-GPU cooperation flows through shared DRAM, the right fix is often to raise memory rather than the resource that merely looks busy.

## Design

CRAVE has a one-time training phase and a lightweight runtime phase. During training, it sweeps all `⟨fCPU, fMem, fGPU⟩` configurations and runs resource-specific microbenchmarks from AnTuTu, PassMark, and Mixbench. From those measurements it computes a resource-interaction matrix `RI`, where each entry is a Spearman correlation between the frequency of one resource and the observed performance of another.

It then builds two objects. The first is a power-performance ratio, `PPR`, for every frequency tuple, with a tunable weight `ν`; for a fixed value of one resource's frequency, CRAVE stores the globally best full-system tuple in a lookup table `πν`. The second is a runtime utility metric `U_r(t)`, which sums the current costs of all resources weighted by `RI`. The dominant resource is the resource with the largest utility.

At runtime, the governor polls utilization and current frequencies, identifies the dominant resource, sets that resource using a standard policy such as `ondemand` or a cost-based policy, and then looks up the best full-system tuple for the resulting dominant-resource frequency. Non-dominant resources below a 20% utilization threshold are scaled down. On big.LITTLE systems, CRAVE manages one CPU domain at a time: usually big cores, but little cores when big cores are already at minimum frequency and below 5% utilization.

## Evaluation

The evaluation uses two real platforms: ODROID-XU4 and NVIDIA Jetson TX2. Training uses microbenchmarks; end-to-end evaluation uses Chai, Rodinia, and glmark2 workloads. The main baselines are the default Linux governors (`schedutil` plus `simple_ondemand`), Co-Cap, and GearDVFS. The runtime polling interval is 250 ms.

The paper first validates the premise. The learned `RI` matrices show that memory frequency has the strongest cross-resource effect on both platforms. The optimal `PPR` regions also often favor higher memory settings, though the best point differs between XU4's LPDDR3 and TX2's LPDDR4 because newer memory can consume a larger share of total system power.

The end-to-end gains are meaningful. On Jetson TX2 individual workloads, CRAVE improves performance by an average of 20% over the default governors while reducing energy by 16%. Against Co-Cap and GearDVFS, it improves performance by 16% and 17%, while reducing energy by 10% and 6%, respectively. On ODROID-XU4 heterogeneous workloads, it improves performance by 19% on average while cutting energy by 24% versus the default governors. For concurrent workloads, CRAVE holds performance roughly steady while saving 17% energy on TX2, and improves performance by 21% while reducing energy by 10% on XU4.

This supports the core thesis reasonably well: the workloads exercise CPU-GPU-memory cooperation, and the comparisons include both built-in and prior cooperative governors. The main caveat is breadth, since two development boards and benchmark suites do not guarantee identical gains on every commercial SoC.

## Novelty & Impact

Relative to Co-Cap, CRAVE does not merely add another heuristic on top of CPU/GPU dominance; it makes memory a first-class participant in both dominant-resource detection and coordinated DVFS. Relative to GearDVFS and similar workload-trained policies, it shifts learning from application traces to platform-level cross-resource behavior. The contribution is therefore both a new framing and a new mechanism, and it should matter to OS, firmware, and mobile-platform designers who need energy savings without per-application retraining.

## Limitations

CRAVE is not free. Its offline training phase is expensive: 12 hours to explore 980 configurations on ODROID-XU4 and 15 hours for 1716 configurations on Jetson TX2. The approach also scales combinatorially as more DVFS-capable domains are added, so broader deployment will need sampling or interpolation rather than exhaustive sweeps. The runtime policy is reactive, not predictive, and the implementation simplifies heterogeneous CPUs by controlling only one CPU domain at a time. The paper also stops at development-board benchmarks rather than real mobile applications with user-facing QoS targets.

## Related Work

- _Deng et al. (MICRO '12)_ - CoScale coordinates CPU and memory DVFS in servers, whereas CRAVE targets mobile SoCs and adds GPU-aware, platform-specific cross-resource modeling.
- _Hsieh et al. (ESTIMedia '15)_ - MemCop also considers CPU, GPU, and memory together, but it is tuned to mobile gaming workloads, while CRAVE is explicitly application-agnostic.
- _Park et al. (SAC '16)_ - Co-Cap uses dominant-resource classification for CPU-GPU capping; CRAVE extends the idea by making memory dominant when shared-memory interaction warrants it.
- _Lin et al. (MobiCom '23)_ - GearDVFS learns from workload traces to predict multi-resource settings, whereas CRAVE learns the hardware coupling once and reuses it across arbitrary workload mixes.

## My Notes

<!-- empty; left for the human reader -->

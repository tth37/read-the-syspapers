---
title: "Performance Predictability in Heterogeneous Memory"
oneline: "Camp predicts CXL and DRAM-CXL interleaving slowdown from a DRAM run by modeling demand reads, prefetch delays, and store-buffer backpressure."
authors:
  - "Jinshu Liu"
  - "Hanchen Xu"
  - "Daniel S. Berger"
  - "Marcos K. Aguilera"
  - "Huaicheng Li"
affiliations:
  - "Virginia Tech, Blacksburg, USA"
  - "Microsoft and University of Washington, Redmond, USA"
  - "NVIDIA, Santa Clara, USA"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790201"
code_url: "https://github.com/MoatLab/CAMP"
tags:
  - memory
  - disaggregation
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Camp argues that heterogeneous-memory slowdown is predictable before deployment, not just measurable after the fact. A DRAM profiling run exposes the microarchitectural pressure points that CXL latency will amplify, and Camp turns those signals into both pure-CXL slowdown forecasts and DRAM/CXL interleaving curves.

## Problem

In a DRAM+CXL machine, operators want to know before placement how much slowdown a workload will suffer if some of its footprint lands on the slow tier. That is hard because the usual signals are incomplete. MPKI captures access frequency but not latency tolerance. Average latency and bandwidth describe the memory system but not how CPU pipelines convert those effects into lost execution time. Stall counters are closer, yet they are reactive and mix several causes together. Even Melody still requires both DRAM and CXL runs. Camp aims to predict slowdown from workload structure already visible on DRAM.

## Key Insight

The key claim is that CXL slowdown is not an opaque device property. It is the result of CPU-side pressure points that are already visible during DRAM execution. Camp, short for Causal Analytical Memory Prediction, models three additive slowdown sources: demand-read stalls, cache/prefetch inefficiency, and store-buffer backpressure. Demand-read slowdown depends on how baseline latency interacts with memory-level parallelism, because only the latency that MLP cannot hide becomes extra stall time. Cache slowdown shows up through reliance on line-fill buffers and memory-sourced prefetches, which become less timely as latency rises. Store slowdown appears when the store buffer is already close to saturation and longer read-for-ownership completions delay draining. Once those components are predicted separately, Camp can forecast both full-CXL execution and mixed DRAM/CXL interleaving.

## Design

Camp profiles a workload on DRAM using at most 12 PMU counters. For non-bandwidth-bound workloads, that run is enough. For bandwidth-bound workloads, Camp adds one CXL endpoint run so it can synthesize the full weighted-interleaving curve.

The demand-read model starts from memory-active cycles and Little's Law. The authors argue that the number of memory requests stays roughly stable across DRAM and CXL, so the key variable is how latency growth compares with MLP growth. That yields a hyperbolic predictor in baseline `L/MLP`: workloads with poor baseline latency tolerance suffer most when memory gets slower. The cache model asks how dependent the workload is on line-fill-buffer hits and memory-sourced prefetches, because higher latency makes those fills late and turns hidden cache activity into visible stalls. The store model is simpler: if DRAM execution already spends cycles blocked by a full store buffer, then CXL's longer RFO latency will amplify that blockage roughly linearly.

For interleaving, the paper's simplifying observation is that MLP changes only weakly across DRAM/CXL ratios. That lets Camp reduce the problem to a latency-curve model: each tier's latency is an unloaded baseline plus a quadratic contention term, and endpoint stall components are scaled into a closed-form slowdown curve for any weighted-interleaving ratio. The same machinery drives "Best-shot" ratio selection and workload colocation.

## Evaluation

The evaluation is broad for the paper's target domain. The authors test 265 workloads spanning SPEC CPU 2017, PARSEC, GAPBS, PBBS, Redis, Spark, VoltDB, MLPerf, GPT-2, DLRM, and Llama-style inference. They use three Intel generations, a NUMA slow tier, and three ASIC CXL 2.0 expanders with 214-271 ns latency and 22-52 GB/s bandwidth.

Prediction accuracy is the headline result. Camp reaches 0.97 Pearson correlation on NUMA and 0.91-0.96 across the three CXL devices. Depending on the device, 77.8-92.4% of workloads fall within 5% absolute slowdown error, and 90.7-97.3% fall within 10%. The component-wise plots matter because they show that demand-read, cache, and store slowdowns are each predicted accurately on their own. Best-shot beats Caption, NBT, Colloid, Alto, Soar, first-touch, and Linux's default 1:1 interleave on eight bandwidth-bound workloads, with gains up to 21%, while Camp-guided colocated placement beats MPKI-guided placement by up to 12% and improves performance by up to 23% over conventional choices. The main boundary is that interleaving is modeled only for weighted interleaving, and bandwidth-bound cases still need the second endpoint run.

## Novelty & Impact

Relative to _Liu et al. (ASPLOS '25)_, Camp moves from post-hoc decomposition to predictive modeling: Melody explains where slowdown came from, while Camp predicts it before deployment. Relative to _Liu et al. (OSDI '25)_, it is broader than SoarAlto's demand-read-centric AOL heuristic because it also models prefetch-induced cache stalls and store-buffer backpressure. Relative to _Vuppalapati and Agarwal (SOSP '24)_, it rejects latency equalization as the optimization target and instead predicts end-to-end slowdown directly. That makes the paper useful to both CXL researchers and operators building tiered-memory placement policies.

## Limitations

Camp depends on platform-specific calibration, and some constants come from microbenchmarks rather than a fully portable derivation. The paper also acknowledges that device tail latency can create outliers, especially on noisier CXL expanders, and that very high-concurrency workloads can break the average-MLP assumption. The scope is narrower than the title might suggest: the full-CXL predictor is meant for regimes where bandwidth is not already saturated, while the interleaving model is tied to weighted interleaving rather than first-touch or migration-based policies.

## Related Work

- _Liu et al. (ASPLOS '25)_ — Melody provides the additive decomposition Camp builds on, but it needs both DRAM and CXL executions and is therefore an attribution framework rather than a predictor.
- _Liu et al. (OSDI '25)_ — SoarAlto uses AOL-style reactivity to guide tiering, whereas Camp derives a causal `L/MLP` model and extends it to cache and store effects.
- _Vuppalapati and Agarwal (SOSP '24)_ — Colloid optimizes for latency equalization across tiers; Camp argues that equalized latency can still be the wrong answer if stall cycles are not minimized.
- _Sun et al. (MICRO '23)_ — Caption characterizes genuine CXL systems and explores coarse interleaving choices, while Camp contributes the predictive model that analytically picks the ratio.

## My Notes

<!-- empty; left for the human reader -->

---
title: "TierX: A Simulation Framework for Multi-tier BCI System Design Evaluation and Exploration"
oneline: "TierX co-explores kernel partitioning and implant/body/external hardware choices to find BCI designs that hit throughput, latency, and operating-time targets."
authors:
  - "Seunghyun Song"
  - "Yeongwoo Jang"
  - "Daye Jung"
  - "Kyungsoo Park"
  - "Donghan Kim"
  - "Gwangjin Kim"
  - "Hunjun Lee"
  - "Jerald Yoo"
  - "Jangwoo Kim"
affiliations:
  - "Seoul National University, Seoul, Republic of Korea"
  - "Hanyang University, Seoul, Republic of Korea"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790234"
code_url: "https://github.com/SNU-HPCS/TierX"
tags:
  - hardware
  - networking
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

TierX argues that invasive BCI design should be treated as a joint optimization problem over computation placement, wireless links, and power delivery rather than as a processor-only choice. It models implant, near-body, and external tiers; searches both workload partitioning and hardware configuration; and predicts performance with `96.2%` average accuracy against measurements. In the studied workloads, the resulting multi-tier designs beat single-tier baselines by up to `21.6x` in throughput and `5.83x` in latency.

## Problem

The paper starts from a practical mismatch in invasive BCI systems. Real applications such as seizure detection, movement decoding, spike sorting, and speech decoding have very different kernel pipelines, latency targets, and energy budgets, yet deployed designs usually commit to one processing location: either do everything inside the implant SoC or stream everything outward. Neither extreme is robust. Implant-only execution saves communication but quickly runs into thermal and power limits inside brain tissue. Offloading to a wearable or external machine relaxes compute pressure, but some kernels produce so much intermediate data that wireless transmission dominates latency and energy.

This already makes architecture selection hard, but the authors' broader point is that BCI system design is not only about choosing a processor. The quality of a design also depends on which communication method is used between tiers, which power-transfer and storage mechanisms are available, and where each node can be placed on or around the body. Those choices interact with one another. A body-coupled link may enable more offloading than RF, but at different power cost; a supercapacitor may improve charging efficiency but reduce stored energy; a neck-to-arm path and a neck-to-external path have different loss profiles. Existing BCI development frameworks help with signal-processing software, and prior BCI hardware papers characterize specific integrated processors, but the paper argues that none of them provide an end-to-end tool for jointly exploring workload partitioning and full-system configuration under BCI-specific constraints.

## Key Insight

The central claim is that multi-tier BCI design becomes tractable once the tiers are modeled as coupled compute, communication, and power domains rather than as isolated processors. In other words, the right partition is not "run the heavy kernels outside the implant" in the abstract; it is "place each kernel at the tier where its compute cost, output size, stride, link quality, and energy implications jointly make sense for the target objective." Because BCI pipelines are periodic and their kernels expose explicit output dimensions and strides, TierX can estimate those cross-tier tradeoffs systematically instead of relying on ad hoc intuition.

That framing matters because the best design point changes with the workload and the optimization goal. A throughput-optimal partition may be different from a latency-optimal one, and both may change again if the user swaps RF for BCC, a battery for a supercapacitor, or an arm-mounted wearable for an external processor. The paper's memorable insight is therefore not a new decoding algorithm or wireless protocol; it is that BCI architects need a search-and-simulate framework that treats partitioning and hardware choice as one problem.

## Design

TierX has two major parts. `TierX-frontend` is the interface and search engine. Users specify available system configurations, including inter-tier transceivers, ECC, wireless power transfer units, storage devices, and node placements; define the application pipeline by listing kernels, output dimensions, and strides; and select an objective such as throughput, latency, or operating time together with constraints such as BER, SAR, power budget, and recharge interval. The optimizer then searches over both workload partitions and feasible hardware configurations. It supports exhaustive search with pruning and a genetic algorithm for faster approximate exploration. The pruning rules are simple but sensible: if a design already violates safety or power at a given on-implant load, larger versions of the same pattern can be skipped.

`TierX-model` is the simulator underneath. Its compute model uses per-kernel static power, dynamic power, and latency, assuming fully pipelined execution as in prior BCI processors such as HALO and SCALO. Its communication model turns user-provided PHY parameters into `SNR`, then into `BER`, packet overhead, retransmission count, latency, and TX/RX energy. Its power model estimates both harvested and consumed wireless-power energy, accounting for path loss, rectification efficiency, and storage round-trip efficiency. A scheduler integrates those component models into a timeline that captures overlap, dependencies, contention, and opportunistic charging. It checks latency-window violations, peak-power violations, and `SAR` limits, and then estimates operating time from depth-of-discharge over a sampling window.

Two details make the design stronger than a toy simulator. First, the whole model is modular: users can swap in more detailed compute models, including parameters extracted from RTL frameworks such as ESP, or supply their own path-loss measurements for a deployment. Second, the simulator is built around the periodic structure of BCI pipelines, so it can extrapolate steady-state behavior from a short sample window rather than simulating an arbitrarily long trace.

## Evaluation

The evaluation is reasonably convincing for a framework paper because it validates both fidelity and usefulness. For fidelity, the authors build real RF, BCC, RF-power, and body-coupled-power setups, vary posture and node placement, and compare measured versus estimated `SNR` and received power. Across all representative configurations, TierX reports `96.2%` average accuracy versus measurements, with RF estimates generally above `97%` and BCC/BCP in the mid-`90%` range. That does not prove the model is universal, but it does show the simulator is anchored in hardware rather than only in synthetic assumptions.

For usefulness, the authors evaluate four representative workloads and many combinations of communication module, storage, node placement, and optimization goal. The search engine is not free: exhaustive search with pruning takes `6379 s` on their server, while the genetic algorithm takes `707 s`, a `9.0x` reduction, and lands within `9.93%` of exhaustive-search optima on average. More importantly, the workload studies show that "best partition" is genuinely workload-dependent. Movement decoding, seizure detection, and speech decoding are often constrained by implant power, while spike sorting is bottlenecked by the first kernel's processing latency and therefore benefits more from offloading.

The strongest systems result is the comparison against single-tier baselines. Relative to the best single-tier offloading choice, the optimal multi-tier partition reduces implant power and end-to-end latency by `7.73x` and `2.02x`. Across applications, a multi-tier design with optimal partitioning and default hardware improves average throughput by `2.94x` and speed by `2.02x` over the single-tier baseline; once TierX also optimizes the hardware configuration, the total gains rise to `5.36x` throughput and `2.55x` speed, while sustaining about `23` hours of operation with one hour of pre-charging. The evaluation supports the paper's central claim well: the workloads exercise exactly the compute-versus-communication-versus-power bottlenecks TierX is meant to reason about. The evidence is narrower at the deployment boundary, however, because the validation environment is mostly a stationary indoor wearable setup and the single-tier baseline is itself simulated as the best of on-, near-, and off-implant execution rather than a separate implemented system.

## Novelty & Impact

Relative to _Karageorgos et al. (ISCA '20)_, TierX's novelty is not a new integrated BCI processor but a framework that decides when integrated processing is the wrong answer. Relative to _Sriram et al. (ISCA '23)_, which presents accelerator-rich distributed BCI hardware, TierX contributes a search procedure and a unified performance model across computation, communication, and power rather than a fixed architecture. Relative to _Yadav et al. (EMBC '25)_, Foresee focuses on processor-level exploration, while TierX extends the design surface to inter-tier links, powering, node placement, and end-to-end operating time. The closest systems analogy is _Kang et al. (ASPLOS '17)_ on mobile/cloud DNN partitioning, but TierX adapts that general idea to a much harsher domain where BER, SAR, and implant energy dominate the feasible region.

That makes the paper valuable less as a final BCI architecture than as an enabling tool. It should be useful to architects deciding where to place future BCI kernels, to circuit and wireless researchers who want their modules evaluated in a larger system context, and to follow-on papers that need an openly released baseline for multi-tier BCI tradeoffs.

## Limitations

TierX is only as good as the component parameters the user provides. The compute model depends on per-kernel latency and power numbers from prior hardware or external tools, so errors in those inputs propagate directly into the search results. The communication model also leans on `AWGN`-style BER estimation and measured path-loss libraries; that is a practical starting point, but it may miss richer channel dynamics in real mobile or long-term deployments.

The safety story is similarly conservative but incomplete. TierX checks peak power and `SAR`, and the authors explicitly note that more realistic thermal models would cost more simulation time. That means the current framework is better at pruning obviously unsafe points than at certifying medical safety. Finally, the evaluation is broad in design-space terms but narrow in workload diversity: it covers four representative pipelines and mostly stationary use conditions, so the paper shows that multi-tier exploration is promising, not that TierX has already solved patient-specific deployment in the wild.

## Related Work

- _Karageorgos et al. (ISCA '20)_ — HALO shows hardware-software co-design for integrated BCI processing; TierX reuses that style of kernel-level characterization but generalizes beyond implant-only architectures.
- _Sriram et al. (ISCA '23)_ — SCALO studies accelerator-rich distributed BCI hardware, while TierX asks how to partition workloads and choose communication and power modules across tiers.
- _Kang et al. (ASPLOS '17)_ — Neurosurgeon is the closest generic tier-partitioning framework, but it does not model implant-specific BER, SAR, and wireless-power constraints.
- _Yadav et al. (EMBC '25)_ — Foresee offers modular RTL-based exploration of integrated BCI compute units; TierX can consume such models while adding end-to-end multi-tier communication and power tradeoffs.

## My Notes

<!-- empty; left for the human reader -->

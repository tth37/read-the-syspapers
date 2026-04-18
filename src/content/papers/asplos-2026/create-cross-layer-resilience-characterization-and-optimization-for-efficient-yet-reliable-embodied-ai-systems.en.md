---
title: "CREATE: Cross-Layer Resilience Characterization and Optimization for Efficient yet Reliable Embodied AI Systems"
oneline: "CREATE co-optimizes undervolted embodied AI stacks by clamping circuit outliers, rotating planner weights, and scaling controller voltage from task criticality."
authors:
  - "Tong Xie"
  - "Yijiahao Qi"
  - "Jinqi Wen"
  - "Zishen Wan"
  - "Yanchi Dong"
  - "Zihao Wang"
  - "Shaofei Cai"
  - "Yitao Liang"
  - "Tianyu Jia"
  - "Yuan Wang"
  - "Runsheng Wang"
  - "Meng Li"
affiliations:
  - "School of Integrated Circuits, Peking University, Beijing, China"
  - "School of EECS, Peking University, Beijing, China"
  - "Georgia Institute of Technology, Atlanta, GA, USA"
  - "Institute for Artificial Intelligence, Peking University, Beijing, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790147"
tags:
  - hardware
  - energy
  - fault-tolerance
  - ml-systems
  - llm-inference
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CREATE shows that undervolted embodied agents are not uniformly fragile: the LLM planner is much more sensitive than the low-level controller, and the controller is only brittle at certain steps. It turns that into a cross-layer design that clamps large timing-error outliers in hardware, rotates planner weights offline, and adapts controller voltage from a learned entropy signal. On the authors' modeled accelerator, that preserves task quality while cutting computational energy by `40.6%` on average over nominal voltage.

## Problem

Modern embodied agents combine expensive high-level reasoning with thousands of low-level control decisions, so compute energy quickly becomes a deployment bottleneck on battery-powered robots. Undervolting is attractive because dynamic power falls roughly quadratically with supply voltage, but it induces timing errors. In embodied AI those errors show up as failed missions or many extra execution steps, not just mild accuracy loss: one bad planner output or one bad controller action can erase the saved energy. Existing resilience techniques are a poor fit because redundancy and timing-borrowing add hardware cost, ABFT-style recovery can break real-time constraints, and retraining-heavy fixes usually target single models rather than a planner/controller stack.

## Key Insight

The paper's main insight is that embodied AI has structured resilience. The planner is fragile because LLM activation outliers interact badly with normalization; even a modest injected error can skew the normalization statistics enough to corrupt the subtask plan. The controller is much more tolerant because it is invoked repeatedly and has more uniform activations, but even it is not equally safe at all times: exploratory phases with diffuse action logits can absorb noise, while critical phases with sharp logits cannot. CREATE therefore spends protection where failures are catastrophic and spends energy savings where the current model or timestep can tolerate noise.

## Design

CREATE has three parts. At the circuit level, anomaly detection and clearance (AD) sits after GEMM accumulation in the systolic array. Because valid INT8 outputs rarely use the highest bits, high-bit timing faults often push values outside the legal quantized range; AD detects those out-of-range results and clamps them to zero. At the model level, weight-rotation-enhanced planning (WR) uses Hadamard-style rotations, merged into weights offline, to redistribute planner activation outliers around vulnerable Transformer components and make normalization less fragile. At the application level, autonomy-adaptive voltage scaling (VS) targets the controller: a small predictor, run at nominal voltage from the current image and subtask embedding, estimates action-logit entropy and drives an LDO-based controller-voltage policy, with updates every five steps.

The implementation is a `128 x 128` systolic-array accelerator with anomaly-detection units on outputs and distributed digital LDOs that scale PE-array voltage from `0.6V` to `0.9V` in `10mV` steps. AD and WR reshape the planner/controller error surface, while the entropy predictor plus LDO policy decides when controller voltage can safely fall.

## Evaluation

The evaluation centers on JARVIS-1 in Minecraft because it exposes both an LLM planner and a Transformer controller over long, multi-stage tasks. The modeled hardware uses a commercial `22nm` PDK and post-layout estimates; the full system reports `11.2 ms` planner latency, `942 us` controller latency, and `8.57 us` entropy-predictor latency. The added hardware is genuinely small: anomaly detection costs `0.08%` area and `0.10%` power, while distributed LDOs cost `0.13%` area and `0.14%` power.

The component studies are concrete. For the planner, AD raises success from `0%` to `85%` on `wooden` and from `0%` to `83%` on `stone` at `BER = 1 x 10^-5`; WR then improves success by `43%` and `40%` on those tasks at `BER = 2 x 10^-5` while reducing average steps by `33%` and `49%`. On the controller side, the entropy predictor reaches `R^2 = 0.92`, and the chosen adaptive policy lowers effective voltage by `7.3%` relative to a constant-voltage policy without sacrificing success rate. AD+WR preserves planner task quality even at `BER = 1 x 10^-2`, and across eight JARVIS-1 tasks at `0.75V`, AD alone recovers `71%` of the error-free success rate on average while AD+WR lifts that to `97%`.

The top-line numbers are strong. Relative to nominal voltage, the full stack saves `40.6%` computational energy on average, or `35.0%` relative to the strongest existing baselines. The paper estimates `29.5%` to `37.3%` chip-level energy savings and roughly `15%` to `30%` battery-life improvement. Cross-platform tests also help: AD+WR reduces planner energy by `50.7%` on average across JARVIS-1, OpenVLA, and RoboFlamingo workloads, while AD+VS reduces controller energy by `39.3%` on average across JARVIS-1, Octo, and RT-1. The evaluation supports the central claim for modeled edge accelerators, but it remains a simulation-plus-injection study rather than a deployed robot experiment.

## Novelty & Impact

Relative to _Agarwal et al. (ISSRE '23)_, which studies transient faults in standalone LLMs, CREATE's novelty is that it treats the planner and controller as one embodied system with different failure modes. Relative to _Wan et al. (DAC '21)_, it addresses a more heterogeneous agent architecture and ties resilience directly to voltage scaling. Relative to _Xie et al. (DAC '25)_, it avoids recovery-heavy protection and instead composes circuit, model, and application-level levers. That makes the paper useful both to embodied-AI systems builders and to architecture researchers looking for a concrete example of cross-layer characterization turned into deployable mechanisms.

## Limitations

The biggest limitation is realism. The paper synthesizes the accelerator and performs extensive fault injection, but it does not demonstrate CREATE on fabricated silicon or on a physical robot with measured battery discharge, so the battery-life gains are still model-based estimates. The scope of faults is also narrower than the title suggests: the work focuses on transient computational timing errors, mostly sets aside memory faults, and gets its strongest evidence from the JARVIS-1 style planner/controller stack. WR specifically relies on large-Transformer outlier-plus-normalization behavior, and the controller policy needs both a trained entropy predictor and a searched entropy-to-voltage mapping. Cross-platform generality is shown by transplanting planner and controller techniques separately, not by evaluating a full end-to-end stack beyond JARVIS-1.

## Related Work

- _Agarwal et al. (ISSRE '23)_ — studies resilience of standalone large language models under transient hardware faults, whereas CREATE focuses on an embodied planner/controller pipeline and uses that heterogeneity to choose mitigations.
- _Wan et al. (DAC '21)_ — analyzes and improves fault tolerance for learning-based navigation systems, but CREATE broadens the target to modern embodied agents with an LLM planner plus low-level controller.
- _Mahmoud et al. (ISSRE '21)_ — explores selective protection for CNN resilience; CREATE instead changes the planner's activation statistics and the controller's voltage policy rather than selectively hardening one network block.
- _Xie et al. (DAC '25)_ — REALM improves standalone LLM reliability with statistical ABFT, while CREATE emphasizes recovery-free cross-layer co-optimization for energy-constrained embodied deployment.

## My Notes

<!-- empty; left for the human reader -->

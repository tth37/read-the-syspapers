---
title: "SimAI: Unifying Architecture Design and Performance Tuning for Large-Scale Large Language Model Training with Scalability and Precision"
oneline: "SimAI reuses real training frameworks and NCCL to unify LLM-training capacity planning and packet-level tuning, matching real runs with 98.1% average alignment."
authors:
  - "Xizheng Wang"
  - "Qingxu Li"
  - "Yichi Xu"
  - "Gang Lu"
  - "Dan Li"
  - "Li Chen"
  - "Heyang Zhou"
  - "Linkang Zheng"
  - "Sen Zhang"
  - "Yikai Zhu"
  - "Yang Liu"
  - "Pengcheng Zhang"
  - "Kun Qian"
  - "Kunling He"
  - "Jiaqi Gao"
  - "Ennan Zhai"
  - "Dennis Cai"
  - "Binzhang Fu"
affiliations:
  - "Alibaba Cloud"
  - "Tsinghua University"
  - "Zhongguancun Laboratory"
  - "South China University of Technology"
conference: nsdi-2025
category: llm-and-ml-training-serving
code_url: "https://github.com/aliyun/SimAI"
tags:
  - llm-training
  - gpu
  - networking
  - datacenter
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SimAI is a unified LLM-training simulator that reuses real frameworks and NCCL instead of approximating them from coarse traces. `SimAI-WG` mocks Megatron and DeepSpeed to emit workloads, `SimAI-CP` models computation at submodule and kernel granularity, and `SimAI-CM` reconstructs NCCL's point-to-point traffic. Across the paper's test scenarios, SimAI averages 1.9% deviation from real runs and is used to guide host-bandwidth and TP decisions.

## Problem

Existing practice uses coarse simulators for capacity planning and packet-level simulators for performance tuning. That split makes predictions inconsistent and forces teams to choose between realism and speed. For LLM training, operators want to compare host layouts, network bandwidth, and TP/DP/PP settings before building hardware, but current tools either ignore real framework and collective behavior or are too slow to support iterative exploration. The paper therefore asks for one simulator that can generate realistic workloads without a full target cluster, model both GPU computation and collective communication accurately, and still scale to thousand-GPU studies.

## Key Insight

SimAI's key claim is that a unified simulator is only credible if it treats the training framework and the communication library as executable specifications. It does not infer workloads from FLOP counts or approximate collectives as idealized flows. Instead, it tricks Megatron and DeepSpeed into running as if they were on the target cluster, skips the real transfers, and records the actual submodules, collectives, and overlap dependencies; it then intercepts NCCL's own initialization and collective-selection logic to reconstruct the peer-to-peer flows a real job would generate.

The broader idea is selective fidelity. Computation gets a finer-grained model than most training simulators expose, communication stays packet-level and NCCL-aware, and simulator speed comes from systems engineering rather than from coarsening the model.

## Design

SimAI has three modeling pieces plus an execution engine. `SimAI-WG` runs a mocked framework on one host, pretends that the requested world size exists, suppresses real communication, and emits a workload description file with computation submodules, collective and peer-to-peer operations, and their dependency graph.

`SimAI-CP` handles computation. For existing GPUs it uses a measured operation database for common LLM submodules and, when needed, finer kernels such as attention and MLP pieces. For unreleased GPUs it falls back to a two-formula Roofline-style model: compute-bound kernels scale with effective FLOPS and memory-bound kernels with memory bandwidth.

`SimAI-CM` handles communication via `SimCCL`, a lightly modified NCCL. It creates virtual communicators, reads a user-provided topology file instead of probing hardware, reconstructs channels, and intercepts collectives to emit the underlying point-to-point flow list. This preserves effects from algorithm selection, PXN routing, and many NCCL environment variables.

Those events are then executed in an NS-3-based simulator. To make that practical, SimAI adopts multithreading and reorganizes shared metadata into node-indexed tables so threads can avoid global locks. The paper reports that this lock-free redesign makes SimAI 23x faster than the original single-thread version and 15% faster than an earlier multithreaded implementation.

## Evaluation

The evaluation uses two 128-host RoCEv2 clusters with fat-tree, multi-rail topologies: one A100 cluster and one H100 cluster. Benchmarks come from a GPT-3 and LLaMA suite under Megatron and DeepSpeed, and ASTRA-sim is the main comparison point.

Communication accuracy is the clearest result. For intra-host collectives, SimAI's average deviation is 3.9% on A100 and 2.3% on H100, versus 74.8% and 51.7% for ASTRA-sim. Inter-host results show the same pattern, especially on small messages and larger scales: the paper highlights an 8 MB `AllGather` on 512 A100 GPUs where ASTRA-sim is off by 530.2%.

Computation accuracy is also strong for the measured path. `SimAI-CP` stays within 0.5%-3.1% of ground truth across A100, H100, and H20, while the fallback `SimAI-CP-Model` is looser at 13%-15% error. End to end, iteration time stays within 4% of real clusters up to 1,024 GPUs, and the paper summarizes overall alignment as 98.1%. The production studies show the simulator is actionable: on the H100 case study, raising per-GPU network bandwidth from 200 Gbps to 400 Gbps still improves performance by 19%, and the TP study argues that once a layer fits, adding more TP can hurt throughput.

## Novelty & Impact

The novelty is not any single model but the composition: workload generation from real frameworks, NCCL-aware communication reconstruction, kernel-aware compute modeling, and an execution path fast enough for repeated design exploration. Compared with ASTRA-sim-style work, SimAI is less a simulator component and more a full-stack method for answering hardware and tuning questions with one consistent abstraction. That is why the impact claim is plausible: the authors say Alibaba teams used it for host-bandwidth and training-parameter decisions, not just offline analysis.

## Limitations

The scope is still narrow. Support is centered on Megatron and DeepSpeed, NCCL, and NVIDIA-plus-RoCE deployments, and workloads outside the paper's benchmark suite require additional GPU-side measurements to populate the operation database. Small-message behavior can still diverge because SimAI does not model all runtime and NIC-pipeline effects. For unreleased GPUs, the fallback compute model is materially less accurate than the measured-kernel database, and different NCCL versions or other CCLs would require re-adapting the `SimCCL` layer. The simulator also skips real payload semantics, so expert parallelism is simplified as balanced token routing, and some NCCL features such as adaptive routing and InfiniBand SHARP-related behavior remain future work.

## Related Work

- _Rashidi et al. (ISPASS '20)_ - `ASTRA-sim` models distributed DNN training stacks, while `SimAI` tries to make the same simulator usable for both LLM capacity planning and packet-level tuning.
- _Won et al. (ISPASS '23)_ - `ASTRA-sim 2.0` extends training-system simulation to hierarchical networks and disaggregated settings, whereas `SimAI` focuses on higher-fidelity workload, computation, and NCCL-aware communication modeling.
- _Gao et al. (SIGCOMM '23)_ - `DONS` shows how data-oriented network simulation improves cache behavior and parallelism, and `SimAI` adopts a related scalability mindset for its own multithreaded execution engine.
- _Khairy et al. (ISCA '20)_ - `Accel-Sim` provides much finer GPU modeling, but `SimAI` trades away instruction-level detail to remain fast enough for large end-to-end LLM-cluster studies.

## My Notes

<!-- empty; left for the human reader -->

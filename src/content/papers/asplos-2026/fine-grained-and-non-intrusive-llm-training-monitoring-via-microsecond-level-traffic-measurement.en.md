---
title: "Fine-grained and Non-intrusive LLM Training Monitoring via Microsecond-level Traffic Measurement"
oneline: "Measures per-flow RDMA traffic on SmartNICs, maps it back to NCCL operators, and localizes LLM-training faults without instrumenting user code."
authors:
  - "Yibo Xiao"
  - "Hao Zheng"
  - "Haifeng Sun"
  - "Qingkai Meng"
  - "Jiong Duan"
  - "Xiaohe Hu"
  - "Rong Gu"
  - "Guihai Chen"
  - "Chen Tian"
affiliations:
  - "State Key Laboratory of Novel Software Technology, Nanjing University, Nanjing, China"
  - "National University of Singapore, Singapore, Singapore"
  - "Infrawaves, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790163"
tags:
  - llm-training
  - observability
  - rdma
  - smartnic
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Pulse monitors LLM training by measuring RDMA traffic directly on SmartNICs instead of instrumenting user code. It reconstructs NCCL operators from per-flow traces and uses gap-aware metrics such as actual communication time to separate computation faults from communication stragglers. On a 64-H200 testbed, it localizes 10 of 12 representative failures at machine level, versus 4 for operator-level baselines.

## Problem

The paper targets managed LLM-training clusters, where long-running, tightly synchronized jobs make one slow node look like a cluster-wide slowdown. Providers need fast localization, but usually cannot require users to patch training frameworks or communication libraries.

Prior tools miss the target in different ways. Offline benchmarks may not reproduce the failure. Online monitors such as Aegis, Holmes, and GreyHound mostly observe operator-level timing and average throughput. That is too coarse when collectives synchronize at slice granularity: one straggling rank creates gaps on the others, so the whole group can show similar durations even though only one machine is slow. Operator-level timing also mixes GPU work, CPU proxy-thread delays, and NIC transmission, so a computation bottleneck can look like a network anomaly.

## Key Insight

Pulse’s key claim is that RDMA traffic itself is the right signal for fine-grained diagnosis, provided the system can map low-level flows back to communication operators. Measuring each QP directly on the RNIC reveals the true progression of communication instead of only a software-recorded interval, so the monitor can see the gaps that operator-level systems miss.

Pulse also avoids sending every microsecond trace to the analyzer. It compresses fine-grained traffic into a few gap-aware metrics: for built-in collectives, actual communication time and communication volume; for custom collectives, rank-level actual rate and completion status.

## Design

Pulse has three components: a NIC Agent, a Host Agent, and an Analyzer. The NIC Agent splits measurement into aggregation in the NIC pipeline, measurement on NIC-embedded microprocessors, and collection on the host. An event fires every 4 KB of transmitted data, the measurement layer records per-QP traffic into 32 us epochs, and host polling reclaims inactive flows. The design uses a direct-address table keyed by the 24-bit QPN plus an epoch pool for active flows.

The Host Agent turns flow measurements into operator measurements. During initialization it hooks `ibv_modify_qp`, NCCL setup, and GPU usage to recover QP-to-GPU mappings and communication-group membership. During execution it intercepts NCCL operators and infers expected peers and traffic volume. P2P operators expose this directly; built-in collectives do not, so Pulse infers whether NCCL chose ring or tree from the active-peer pattern.

Because real traffic includes headers, synchronization messages, and retransmissions, expected volume is only a lower bound. Pulse therefore segments operators using both transmitted bytes and a time-gap threshold. The same idea extends to custom collectives by grouping P2P calls between `ncclGroupStart` and `ncclGroupEnd`.

The Analyzer then localizes faults from compact summaries. Built-in communication fail-slow shows up as larger actual communication time; fail-stop as the node that sent the least data. For custom collectives, Pulse uses rank-level actual rate to smooth per-P2P jitter and incomplete P2P operators to identify fail-stop. Computation anomalies are inferred from delayed or missing later operators, plus the case where duration stretches while actual communication time stays normal.

## Evaluation

Pulse runs on eight rented servers with 64 H200 GPUs and BlueField-3 SuperNICs over 400 Gbps RoCEv2, and injects 57 failures across GPT-2 70B, Mixtral 8x7B, and a small neighbor-exchange workload.

Pulse exceeds 90% precision and reaches 100% recall overall, localizing 10 of 12 representative failures at machine level and shrinking the other two to group level. The operator-level baselines localize only 4 cases at machine level and misdiagnose 2 others. The case studies explain the gain: 32 us monitoring exposes congestion stragglers that 64 us already starts to blur; actual communication time prevents false network diagnoses in CPU-contention cases; and rank-level actual rate suppresses false positives in MoE expert-parallel traffic.

Overhead is low. Monitoring up to 2000 concurrent flows per RNIC does not reduce throughput and changes average RDMA latency only from 1.52 us to 1.53 us. Training iteration time is nearly unchanged across GPT-2 32B, GPT-2 70B, and Llama-70B, while host-NIC PCIe overhead peaks at about 0.3 MB/s. The main cost is diagnosis latency: Pulse is about 0.7 s slower because it polls RNIC data every second and still has to perform flow-operator association.

## Novelty & Impact

Relative to Aegis and Holmes, Pulse’s novelty is not a better operator-level monitor but a different observability substrate: NIC-visible traffic first, operator reconstruction second. Relative to GreyHound, it preserves non-intrusive deployment while adding sub-operator visibility. Relative to host or switch measurement work, its contribution is the three-layer RNIC design that makes lossless microsecond RDMA measurement practical on deployed SmartNICs.

That makes the paper directly relevant to cloud training operators and, more broadly, to observability for communication-heavy ML systems.

## Limitations

Pulse only monitors inter-node RDMA traffic. It does not observe NVLink, does not support CollNet or NVLS, and therefore cannot provide full scale-up visibility. That also limits some computation diagnoses to machine level when the ambiguity stays inside one node.

The system also assumes programmable RNICs such as BlueField-3 or ConnectX-6 Dx, periodic host polling, and a parallelism-identification heuristic that matches frameworks such as Megatron or DeepSpeed. Those assumptions narrow portability. The one-second polling period is another explicit tradeoff: it keeps overhead low, but caps reactivity.

## Related Work

- _Dong et al. (NSDI '25)_ — Aegis gathers operator-level data from training logs and CCLs, while Pulse moves down to per-flow RDMA traffic.
- _Yao et al. (NSDI '25)_ — Holmes localizes LLM-training irregularities online from operator timelines rather than NIC-visible traffic.
- _Wu et al. (USENIX ATC '25)_ — GREYHOUND is non-intrusive through function hooking and CUDA events; Pulse keeps that model but adds microsecond traffic measurement.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Mycroft: Tracing Dependencies in Collective Communication Towards Reliable LLM Training"
oneline: "Mycroft records Coll-level progress inside NCCL, samples a few ranks, and reconstructs communication dependencies to localize LLM-training hangs and fail-slows in seconds."
authors:
  - "Yangtao Deng"
  - "Lei Zhang"
  - "Qinlong Wang"
  - "Xiaoyun Zhi"
  - "Xinlei Zhang"
  - "Zhuo Jiang"
  - "Haohan Xu"
  - "Lei Wang"
  - "Zuquan Song"
  - "Gaohong Liu"
  - "Yang Bai"
  - "Shuguang Wang"
  - "Wencong Xiao"
  - "Jianxi Ye"
  - "Minlan Yu"
  - "Hong Xu"
affiliations:
  - "The Chinese University of Hong Kong"
  - "ByteDance"
  - "ByteDance Seed"
  - "Harvard University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764848"
tags:
  - llm-training
  - observability
  - rdma
  - gpu
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mycroft adds Coll-level tracing to NCCL so live LLM jobs can be debugged before NCCL timeout. It samples a few ranks, records flow- and chunk-level progress, and uses dependency violations to narrow a hang or fail-slow to the likely rank, GPU, NIC path, or flow.

## Problem

Hybrid-parallel LLM training turns one slow collective into cluster-wide idle time. A gray failure can stall a job without obvious logs; a fail-slow can keep it running while wasting throughput. Because DP, PP, and TP groups are nested, the first bad rank is quickly hidden behind downstream waiters.

Existing tools observe the wrong layer. Op-level profilers show that a collective was late but not why. Kernel-level tracing is detailed but expensive and still detached from communication semantics. RDMA counters help with the network, but not with sender-GPU readiness or receiver blocking. Operators therefore often wait for NCCL timeout and restart blindly. The paper's claim is that diagnosis needs observability inside the collective library itself.

## Key Insight

Mycroft's key idea is Coll-level tracing: record the progress states that reveal dependency violations instead of recording every CUDA event. At flow level it tracks individual network paths. At chunk level it records how much data is GPU-ready, transmitted by RDMA, and marked done.

Those counters are enough to separate several cases. `GPU_ready > RDMA_transmitted` points to sender-side RDMA lag; `RDMA_transmitted > RDMA_done` points to network or receiver-side blocking; consistently later starts or finishes point to GPU or host-side compute delay. Because anomalies propagate within hundreds of milliseconds, always-on triggering only needs a few sampled ranks.

## Design

Mycroft instruments NCCL 2.21.5 at the proxy-thread critical path. It adds fewer than ten tracepoints and emits two log types: a completion log for each finished collective and a real-time state log every 100 ms while a collective is in flight. Logs include operation metadata plus `GPU_ready`, `RDMA_transmitted`, `RDMA_done`, GPU/channel/QP identifiers, and communication-group IDs. Each host writes to a 512 MB shared-memory ring; a read-only agent ships the data asynchronously through Kafka to a cloud database.

The online pipeline has two stages. The trigger samples at least one rank per DP group, capped at ten ranks total, and fires when sampled ranks stop completing collectives, throughput halves, or operation intervals double. Root-cause analysis then reconstructs a short global state machine from the recent window, finds the affected communication group, and checks which rank or flow made the least progress or started and ended abnormally late. Mycroft also integrates with `py-spy` and PyTorch Flight Recorder so dataloader stalls, missing CollOp launches, and process-group deadlocks can be ruled out quickly.

## Evaluation

The controlled evaluation uses 32 A100-80GB GPUs across four machines with NVLink, PCIe, and four ConnectX-6 RNICs per host, running Megatron-LM GPT with TP=8, PP=2, and DP=2. The authors inject seven faults: NIC shutdown, NIC bandwidth limiting, PCIe downgrading, GPU power limiting, background GPU computation, background network traffic, and NCCL proxy delay. Mycroft localizes all seven. The signatures match the design: NIC shutdown is the first rank to stop logging, bandwidth limiting produces `GPU_ready > RDMA_transmitted`, and background traffic leaves `GPU_ready = RDMA_transmitted` but delays `RDMA_done`. Across all injections, end-to-end diagnosis stays within 13 seconds.

Overhead is low. On NCCL tests, Mycroft tracks baseline bandwidth closely, while NPKit drops bus bandwidth to about one third. In Megatron training, iteration time rises only from 1116 ms to 1119 ms, and trace volume is about 46.8 KB per iteration per machine, versus roughly 15 MB for Nsight's CUDA tracing. In production, after deployment in October 2024, Mycroft monitored ByteDance jobs above 128 GPUs, detected 13,221 interruptions over November and December 2024, ran root-cause analysis 1,253 times, and isolated a single problematic flow in 705 cases. The paper also reports 90% anomaly detection within 15 seconds and all root-cause analyses within one minute, though it does not provide a fully labeled production dataset for precision and recall.

## Novelty & Impact

Relative to GREYHOUND, Mycroft analyzes dependency propagation inside a collective instead of only late collective timestamps. Relative to Evolution of Aegis, it combines RDMA-visible progress with GPU-side communication state. Relative to Nsight- or NPKit-style tracing, it trades full kernel timelines for a representation aligned with communication semantics.

The contribution is therefore not a new collective algorithm but a new observability boundary. Coll-level tracing gives operators a middle ground between coarse logs and prohibitively detailed traces, and the same idea could guide future reliability tooling in collective libraries.

## Limitations

Mycroft only sees the communication layer. It cannot directly encode benign compute-communication overlap, legitimate load imbalance, or deeper application intent, so its thresholds are heuristic; the paper uses rules such as throughput dropping by 50% and ranks starting or ending more than one second late.

The current implementation is also NCCL-specific and often narrows the search space rather than proving the final hardware fault. The case studies still rely on `py-spy`, Flight Recorder, or offline checks for final confirmation. The backend is centralized as well, and the paper notes that 10,000 GPUs already generate about 3 TB of trace data per day, so larger deployments may need decentralization.

## Related Work

- _Dong et al. (NSDI '25)_ — Evolution of Aegis diagnoses AI-training failures from RDMA-level and runtime signals, whereas Mycroft adds internal collective-library state to explain how one stalled transmission propagates.
- _Wu et al. (ATC '25)_ — GREYHOUND detects fail-slows from collective-operation timing, while Mycroft pushes analysis down to flow- and chunk-level dependencies for localization.
- _Deng et al. (NSDI '25)_ — Minder detects faulty machines for distributed model training from out-of-band machine signals, whereas Mycroft instruments the communication path itself.
- _Xiong et al. (ATC '24)_ — SuperBench proactively validates GPU nodes with benchmarks, while Mycroft targets failures and slowdowns that appear during the real training job.

## My Notes

<!-- empty; left for the human reader -->

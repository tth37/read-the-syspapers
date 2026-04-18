---
title: "Robust LLM Training Infrastructure at ByteDance"
oneline: "ByteRobust keeps 10k-GPU LLM training moving with isolation-first fault handling, stack-trace-driven over-eviction, warm standbys, and recovery-aware checkpoints."
authors:
  - "Borui Wan"
  - "Gaohong Liu"
  - "Zuquan Song"
  - "Jun Wang"
  - "Yun Zhang"
  - "Guangming Sheng"
  - "Shuguang Wang"
  - "Houmin Wei"
  - "Chenyuan Wang"
  - "Weiqiang Lou"
  - "Xi Yang"
  - "Mofan Zhang"
  - "Kaihua Jiang"
  - "Cheng Ren"
  - "Xiaoyun Zhi"
  - "Menghan Yu"
  - "Zhe Nan"
  - "Zhuolin Zheng"
  - "Baoquan Zhong"
  - "Qinlong Wang"
  - "Huan Yu"
  - "Jinxin Chi"
  - "Wang Zhang"
  - "Yuhan Li"
  - "Zixian Du"
  - "Sida Zhao"
  - "Yongqiang Zhang"
  - "Jingzhe Tang"
  - "Zherui Liu"
  - "Chuan Wu"
  - "Yanghua Peng"
  - "Haibin Lin"
  - "Wencong Xiao"
  - "Xin Liu"
  - "Liang Xiang"
affiliations:
  - "The University of Hong Kong"
  - "ByteDance Seed"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764838"
tags:
  - llm-training
  - fault-tolerance
  - observability
  - gpu
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ByteRobust treats large-scale LLM training as a continuously failing production service rather than a batch job that occasionally crashes. It combines real-time inspection, hierarchical stop-time diagnostics, stack-trace-driven over-eviction, hot updates, warm standbys, and over-eviction-aware checkpointing so training can resume quickly without waiting for perfect root-cause proofs. On 9,600-GPU production jobs, the system sustains up to 97% ETTR, while its recovery mechanisms improve restart speed by more than 10x over conventional requeue.

## Problem

The paper starts from an operational reality: once LLM pretraining spans thousands of GPUs for months, failures stop being exceptional. Over a three-month window on ByteDance's production platform, the authors record 38,236 explicit failures, 5,948 implicit failures, and 9,582 manual restarts across 778,135 LLM training jobs. Existing practice is still mostly fail-stop: wait for logs or timeouts, run stress tests, reschedule resources, and reload terabyte-scale checkpoints from remote storage. That workflow can cost hours or even days, which directly harms the effective training time ratio (ETTR).

The difficulty is not just frequency, but ambiguity. Large LLM training mixes TP, PP, DP, ZeRO, long-context stages, and continuously evolving optimization code. The same symptom, such as a hang, NaN loss, or illegal memory access, may come from user code, networking, storage, GPU hardware, or silent data corruption. Implicit failures are especially costly because they often leave no decisive log signal, so naive timeout-based handling wastes large numbers of GPUs while engineers try to localize the fault precisely.

## Key Insight

ByteRobust's central claim is that, at 10k-GPU scale, fast isolation is usually more valuable than exact localization. A robustness system should reason in the same units as the training job itself: machines, parallel groups, code versions, and checkpoint domains. If runtime signals can quickly separate "healthy enough to continue" from "suspect and evict," then the job spends less time idle even when the system cannot yet explain the exact root cause.

The companion insight is that recovery must minimize environmental drift. If code changes are applied in place, replacement machines come from a prevalidated standby pool, and checkpoints are already backed up outside likely failure domains, then restarts stop looking like full job resubmissions. They become bounded repair operations that preserve as much of the original runtime context as possible, which both shortens downtime and reduces new sources of variance during debugging.

## Design

ByteRobust has a control plane and a data plane. The control plane contains the Robust Controller, which orchestrates detection, eviction, rollback, and recovery, and the Runtime Analyzer, which handles silent hangs and MFU drops. Each training pod runs a Robust Agent with four modules: a Monitor for system and workload metrics, a Diagnoser for stop-time tests such as EUD and NCCL checks, an On-Demand Tracer for capturing process stacks, and a CKPT Manager for asynchronous checkpointing and backup.

Its automated fault-tolerance loop is hierarchical. High-confidence explicit faults such as GPU unavailability or disk faults trigger direct machine eviction. Otherwise ByteRobust suspends the job and runs stop-time diagnostics. If the failure looks transient, it simply reattempts. If a recent code update is suspect, it rolls the code back using in-place hot update instead of rebuilding the pod. For harder cases such as SDC, it uses dual-phase replay: keep TP and PP fixed, vary only DP grouping, and identify a suspect machine from the intersection of faulty horizontal and vertical groups.

Implicit failures are handled differently. For hangs and MFU decline, ByteRobust captures stack traces from training, data-loading, and checkpoint subprocesses, clusters dominant stacks versus outliers, and then evicts the shared PP, DP, or TP group behind the outliers. This is deliberately over-conservative: the system accepts some false positives to recover sooner. Recovery then relies on warm standby machines sized to the P99 failure count and on checkpoint backups placed outside a rank's 3D parallel groups so that over-evicting one group does not destroy the only usable checkpoint.

## Evaluation

The evaluation is convincing for the target environment. ByteRobust has run for more than a year on production clusters with over 200,000 GPUs. On two 9,600-GPU production pretraining jobs, one dense 70B+ model and one 200B+ MoE model, cumulative ETTR stays as high as 97%, and the sliding-window unproductive period remains within roughly 50 minutes even in later stages. Relative MFU still improves by 1.25x for the dense job and 1.58x for the MoE job because hot updates let engineers ship optimization changes without paying the cost of full requeue.

The component results explain those gains. Real-time inspection detects NIC crashes in 30 seconds instead of waiting for the roughly 10-minute distributed timeout, and detects GPU lost or memory errors in 10 seconds. In production, automatic eviction-and-restart resolves most explicit failures, while the analyzer automatically handles 24 implicit incidents through machine over-eviction. In the recovery microbenchmarks, hot update is 11.04x faster than requeue, warm standby reduces weighted restart time by 10.87x versus requeue and stays within 5.19% of an oracle with unlimited ready spares, and every-step checkpointing cuts blocking time by 99.69% versus Megatron save while limiting MFU loss to 0.71%. The evidence is mostly internal, but it does align with the paper's claim that tightly integrated detection and recovery matter more than any single diagnostic trick.

## Novelty & Impact

Relative to MegaScale, ByteRobust is not just a monitoring and stop-time-diagnosis system; it closes the loop from detection to automatic isolation, rollback, and recovery. Relative to Gemini and related checkpointing work, it makes backup placement recovery-policy-aware by assuming whole parallel groups may be over-evicted. Relative to SuperBench-style stress testing, it preserves the job's actual TP/PP/DP structure and uses runtime stack aggregation when silent failures would not reproduce under synthetic tests.

That makes the paper more of a systems blueprint than a single mechanism paper. Its contribution is the framing that robust LLM training requires coordinated decisions about diagnosis, code evolution, restart policy, standby capacity, and checkpoint placement. Anyone building production LLM training infrastructure or GPU-cluster SRE tooling is the obvious downstream audience.

## Limitations

The system is deeply shaped by ByteDance's environment. It assumes Kubernetes-style control, custom agents in every pod, spare warm-standby capacity, and access to NVIDIA-specific diagnostics and runtime metrics. Many design choices are deliberately coarse. Over-evicting a full PP group can create 6-7 false positives in a 9,600-GPU job, which is acceptable at that scale but would look expensive in smaller clusters.

The hardest failure mode also remains partly unsolved. The paper notes that NVIDIA EUD reaches only about 70% recall for SDC in production, and the fallback MiniGPT validation plus dual-phase replay still has high overhead. External generality is therefore limited: most deployment evidence comes from ByteDance's own jobs and infrastructure, and many comparisons are against prior practice or simplified baselines rather than artifact-identical competing systems.

## Related Work

- _Jiang et al. (NSDI '24)_ — MegaScale monitors heartbeats and RDMA metrics for LLM training, whereas ByteRobust adds automatic isolation, rollback, and recovery-aware checkpoint placement.
- _Wang et al. (SOSP '23)_ — Gemini uses in-memory checkpoints for fast recovery, while ByteRobust overlaps backup with training and places replicas outside likely over-eviction domains.
- _Xiong et al. (ATC '24)_ — SuperBench proactively stress-tests GPU nodes, but ByteRobust argues that preserving the original training topology is more faithful for diagnosing silent failures.
- _Dong et al. (NSDI '25)_ — Evolution of Aegis improves AI-training fault diagnosis from logs and heuristics, whereas ByteRobust leans on runtime metrics and in-job process-state aggregation to handle hangs and gray failures.

## My Notes

<!-- empty; left for the human reader -->

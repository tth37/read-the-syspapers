---
title: "Minder: Faulty Machine Detection for Large-scale Distributed Model Training"
oneline: "Minder flags the machine whose denoised metrics stay persistently dissimilar from peers, turning multi-team training fault triage into 3.6-second runtime alerts."
authors:
  - "Yangtao Deng"
  - "Xiang Shi"
  - "Zhuo Jiang"
  - "Xingjian Zhang"
  - "Lei Zhang"
  - "Zhang Zhang"
  - "Bo Li"
  - "Zuquan Song"
  - "Hang Zhu"
  - "Gaohong Liu"
  - "Fuliang Li"
  - "Shuguang Wang"
  - "Haibin Lin"
  - "Jianxi Ye"
  - "Minlan Yu"
affiliations:
  - "Tsinghua University"
  - "ByteDance"
  - "Northeastern University"
  - "Harvard University"
conference: nsdi-2025
tags:
  - llm-training
  - observability
  - gpu
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Minder detects faulty machines in large distributed training jobs by treating healthy machines as near-synchronous peers and looking for the one whose denoised monitoring trace stays persistently different. It trains one unsupervised LSTM-VAE per metric, prioritizes the most fault-sensitive metrics, and alerts only when the same outlier persists across consecutive windows. In ByteDance's production deployment, the system reacts in 3.6 seconds on average and reaches 0.904 precision and 0.893 F1 on real fault cases.

## Problem

The paper studies a painful operational gap in large-scale model training: faults usually begin as a problem on one host, but the first practical signal often arrives only after the whole job has slowed down or halted. In the authors' environment, training jobs run on up to thousands of machines and unexpected faults happen about twice per day on average. Because modern training relies on tightly synchronized data, pipeline, and tensor parallelism, one bad machine can trigger NCCL timeouts, disconnected communication, or long idle periods on many other machines.

The default response is manual diagnosis. That means multiple teams inspect logs, counters, and offline tests for training software, networking, storage, and hardware until someone finds the culprit. The paper argues this is slow for structural reasons. Notification is late because engineers are usually paged only after a stop, not when performance first degrades. Logs are incomplete because they omit many useful counters such as GPU power or PFC packet rates. The workflow is also labor-intensive because a fault can originate in GPU memory, PCIe, NVLink, NICs, software libraries such as CUDA or NCCL, or supporting services such as HDFS and SSH.

The harder technical problem is that there is no universal metric or label. CPU, GPU, memory, throughput, and PFC counters all correlate with some faults, but none covers all of them. Even the same metric can be normal for one training job and abnormal for another depending on workload and scale. So the paper is not solving generic anomaly detection; it is solving runtime blame assignment under task-dependent baselines.

## Key Insight

Minder's core proposition is that large distributed training already gives you the right reference set: other machines in the same job. Under 3D parallel training, healthy machines should show similar second-level patterns in compute, communication, and storage counters. A faulty machine therefore need not match a precomputed notion of "normal"; it only needs to remain an outlier relative to its peers.

That observation leads to two further design choices. First, Minder denoises each metric separately instead of building one monolithic detector across all metrics, because different faults surface through different counters and combining them can blur the useful signal. Second, it requires continuity: faults usually create degraded behavior that lasts for minutes, whereas sensor jitters and transient bursts are short. The combination turns the problem from "classify this machine state" into "find the machine that stays most dissimilar for long enough."

## Design

Minder runs as a backend watcher. For each task, it periodically pulls recent per-second monitoring data for all machines, aligns timestamps across hosts, fills missing samples with the nearest timestamp, and min-max normalizes each metric. It then slices each metric into sliding windows and feeds those windows into per-metric denoising models.

The denoiser is an LSTM-VAE. The paper's rationale is pragmatic: a VAE trained mostly on normal runtime traces learns the dominant temporal structure and reconstructs noisy inputs into cleaner embeddings, while true outliers stay distinctive after reconstruction. Minder trains a separate model for each metric, such as CPU usage, PFC packet rate, or GPU duty cycle. This matters because the paper's fault study shows an "or" relationship between faults and metrics: ECC errors may show up in CPU or GPU metrics, PCIe faults are more visible in network counters, and no single feature is authoritative.

The system also learns a metric priority order. For each time window, Minder computes the per-metric maximum Z-score across machines, then trains a decision tree over those window-level features. Metrics near the tree root are treated as more fault-sensitive. The learned order favors PFC, CPU, GPU, and NVLink-related signals, which matches the authors' case study that most real failures disturb process state or communication first.

At runtime, Minder walks that priority order. For one metric at a time, it reconstructs each machine's window with the corresponding LSTM-VAE, computes pairwise Euclidean distances between machine embeddings, sums each machine's distance to all others, and normalizes that score to account for cluster size. The machine with the largest normalized dissimilarity becomes the candidate if it exceeds a similarity threshold. Minder then shifts the window by one step and repeats the check. Only if the same machine remains the candidate for longer than a continuity threshold, set to four minutes, does Minder raise an alert. In production, that alert feeds a driver that blocks the machine and lets Kubernetes replace it so the job can recover from checkpoints.

## Evaluation

The evaluation combines a year-long deployment description with a labeled dataset of 150 runtime fault instances collected over nine months. The tasks span 4 to more than 1,500 machines, up to 10,000 NVIDIA Ampere GPUs, and cover the major fault types from the paper's taxonomy, including ECC errors, CUDA failures, GPU execution errors, PCIe downgrading, and machine-unreachable cases.

The first headline result is latency. One Minder invocation takes 3.6 seconds on average, including both data fetching and analysis. The paper compares that with a manual diagnosis process that takes over half an hour on average and sometimes days, so the authors reasonably frame Minder as removing more than 99% of the response time in the common path.

The second result is detection quality. Minder reaches 0.904 precision, 0.883 recall, and 0.893 F1. The baseline Mahalanobis-distance detector reaches 0.788 precision, 0.767 recall, and 0.777 F1. That gap supports the paper's claim that denoising and per-metric modeling matter; simple statistical outlier detection is more easily misled by jitter.

The ablations are also useful. Using fewer metrics hurts recall because it drops informative counters; using more metrics hurts precision because heterogeneous signals interfere with each other. Replacing the model with raw distances or an all-metrics integrated model lowers recall and F1, and removing continuity drops precision sharply to 0.757 by turning short jitters into false alarms. The evaluation is weaker on rare concurrent failures: PCIe downgrading and GPU execution errors are harder when faults propagate quickly across 3D parallel groups, and switch-related AOC failures are under-observed because the current monitoring stack lacks the right cable counters. The paper is candid that second-level monitoring is the limiting factor here.

## Novelty & Impact

The novelty is not a new deep model in isolation. Minder's contribution is the systems recipe: exploit peer similarity within one training job, denoise each metric separately, prioritize metrics by fault sensitivity, and gate alerts on temporal continuity. That package is more specific than generic KPI anomaly detection and more deployable than heavyweight root-cause analysis that depends on service dependency graphs.

This paper should matter to operators of large training clusters and to researchers working on AI infrastructure reliability. It shows that machine-level fault detection can be fast enough to sit directly on the recovery path, and that the right abstraction for these jobs is comparative observability across homogeneous workers rather than a universal anomaly label. It is therefore a new mechanism for training operations, not just a measurement study.

## Limitations

Minder detects the machine, not the root cause. Once it alerts, engineers may still need extra tooling to decide whether the real issue is ECC, PCIe, NVLink, a software stack failure, or a transient network event. The paper explicitly leaves fine-grained causal diagnosis to future work.

The method also depends on workload structure. It assumes machines within a job should look broadly similar, which is true for the authors' 3D-parallel training workloads but may be weaker for more heterogeneous inference or mixed-service environments. The authors argue the idea should transfer where inter-machine similarity holds, but they do not evaluate that claim.

Finally, the current deployment uses second-level counters and mostly single-fault cases. That misses very fast propagation patterns and makes concurrent failures hard to localize unless finer-grained telemetry is available. The paper's own multi-fault injection experiment succeeds only after moving to millisecond-level monitoring.

## Related Work

- _Xiong et al. (USENIX ATC '24)_ - SuperBench proactively runs benchmarks to catch unreliable AI hardware, while Minder passively watches live jobs and focuses on runtime fault detection, including software-originated failures.
- _Liu et al. (NSDI '23)_ - HostPing diagnoses intra-host RDMA bottlenecks with offline tests, whereas Minder aims to identify the bad machine during ongoing distributed training.
- _Liu et al. (ISSRE '19)_ - FluxRank localizes root-cause machines for service failures using service-level contextual signals; Minder instead relies on the homogeneous peer behavior of distributed training workers.
- _Xu et al. (WWW '18)_ - This VAE-based KPI anomaly detector motivates Minder's denoising choice, but Minder adds per-metric modeling, peer-wise distance comparison, and continuity checks tailored to machine blame assignment.

## My Notes

<!-- empty; left for the human reader -->

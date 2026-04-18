---
title: "Holmes: Localizing Irregularities in LLM Training with Mega-scale GPU Clusters"
oneline: "Holmes uses communication-operator logs, an auto-tuned random forest, and graph search over training parallelism to localize silent LLM-training irregularities in seconds."
authors:
  - "Zhiyi Yao"
  - "Pengbo Hu"
  - "Congcong Miao"
  - "Xuya Jia"
  - "Zuning Liang"
  - "Yuedong Xu"
  - "Chunzhi He"
  - "Hao Lu"
  - "Mingzhuo Chen"
  - "Xiang Li"
  - "Zekun He"
  - "Yachen Wang"
  - "Xianneng Zou"
  - "Juncheng Jiang"
affiliations:
  - "Fudan University"
  - "Tencent"
  - "University of Chicago"
conference: nsdi-2025
category: llm-and-ml-training-serving
tags:
  - llm-training
  - gpu
  - observability
  - networking
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Holmes targets a failure mode that does not crash LLM training: iterations that silently run much slower than expected and accumulate more wasted time than explicit failures. It logs only communication operators, detects abnormal operators with an auto-tuned random-forest model, and then walks a communication-operator graph plus cross-iteration evidence to localize the most likely bad GPU or network component. On production traces and a production-style testbed, Holmes reports up to 97.21% localization accuracy and 30.3-second end-to-end localization time.

## Problem

The paper starts from an operational fact that prior LLM-systems work largely ignores. Large training jobs on 352-8192 GPUs do not just fail occasionally; they also enter "irregular" iterations where training continues, but a step runs noticeably longer than its local reference. These irregularities are frequent, silent, and expensive. In the authors' traces from a production cluster with more than 10,000 H800 GPUs, irregularities happen orders of magnitude more often than hard failures. At 8192 GPUs, the wasted time attributed to irregularities reaches 32.38 hours over a month, and manual localization takes more than 4 hours in 86.2% of cases.

Why is this hard to diagnose? Traditional failure tooling expects error logs or explicit job interruption. Irregularities generate neither. At the same time, a single slow GPU, bad NIC, flaky link, or unstable switch can delay collective operations and make many healthy GPUs look slow because they must wait at synchronization points. The diagnosis target is therefore not "which GPU observed a long step," but "which device actually caused the slowdown," and a false positive is costly because isolating a healthy node wastes scarce training capacity.

## Key Insight

The core insight is that communication operators are the right observational boundary for this problem. They are sparse enough to log cheaply, but rich enough to expose both compute-side and network-side irregularities. If a GPU computes slowly before an `All-Reduce`, the communication operator's start time shifts; if the network is the problem, the operator's elapsed time and peer behavior reflect that too. Holmes therefore does not need full operator tracing or generic hardware telemetry to localize the issue.

The second insight is structural. Abnormal operators should not be judged independently. Their meaning depends on the communication pattern induced by data, tensor, expert, and pipeline parallelism. Holmes encodes that structure as a communication-operator graph and searches it differently for collective communication and point-to-point communication, then aggregates evidence across many iterations with a Bayesian-style device ranking. The result is a domain-specific localization algorithm rather than a generic anomaly detector.

## Design

Holmes has four stages. First, a lightweight `CommOps` logger records only communication operators such as `All-Reduce`, `All-Gather`, `All-to-All`, `Send`, and `Recv`. Each log entry stores fields like communication pattern, elapsed time, timestamps, communicator, rank, and data size. The paper's argument is that this is the minimum logging granularity that still preserves propagation structure while avoiding the overhead of tracing every compute operator.

Second, Holmes detects abnormal operators once an iteration monitor flags a `delta`-irregular step. The detector is a random forest over per-operator features and global context, including mean and standard deviation of execution time, z-score, quartiles, IQR, rank, message size, communication pattern, iteration time, and window-level average operator latency. Because long-running training jobs drift over time, Holmes auto-tunes the trained forest by shifting threshold values for features whose distributions have moved, rather than retraining from newly labeled data every time.

Third, Holmes localizes the root cause with a communication-operator graph. Naively connecting every operator to every participating GPU would explode in size, so the system compresses the graph using communication groups induced by parallel training structure. For collective communication, Holmes performs BFS over the group. If all copies of a collective operator are abnormal, the communication itself is the likely cause; if one GPU's copy is normal, Holmes backtracks on that GPU to earlier operators, inferring that the others are waiting on a slower predecessor. For point-to-point pipeline communication, Holmes performs DFS along peer operators and backtracks across pipeline stages until it finds the earlier abnormal operator or confirms the network path itself is the cause.

Finally, Holmes performs cross-iteration analysis. It computes an irregularity rate from the correlation between abnormal-operator duration and end-to-end iteration time, then accumulates that evidence onto candidate GPUs, links, NICs, and switches. A MAP estimator and a topology-aware decay factor prevent central network devices from being overblamed simply because many paths cross them. Holmes then ranks devices and returns the top candidates.

## Evaluation

The evaluation uses three months of traces from a production training environment with more than 10,000 GPUs, H800 accelerators, ConnectX-7 Dx NICs, Megatron-LM, DeepSpeed, and NCCL. On abnormal-operator detection alone, Holmes's random forest reaches F1 above 0.89 across scales and 0.93 at 4096 GPUs, outperforming 3-sigma, KNN, and the paper's SVM baseline. Its auto-tuning also matters: over a month-long 3072-GPU run, the tuned detector stays above 0.917 F1 while an untuned RF drops from 0.922 to 0.906.

End to end, Holmes is strongest as a localization system rather than only a detector. At 2048 GPUs it achieves 97.2% localization accuracy, and even at 8192 GPUs it still reports 88.2%, versus 78.0% for the random-walk baseline and 80.7% for the Seer-style neural baseline. The system remains usable across more complex hybrid parallel jobs as well, with median localization accuracy of 94.6% for 3D parallelism, 89.6% for 4D, and 86.0% for 6D.

The production-style prototype supports the real-time claim. Detection latency on one GPU log stays below 400 ms even for a 15-minute window with 9-10K operators. Progressive fetching cuts transferred data from 24.36 GB to 0.84 GB per localization, a 96.6% reduction over analyzing every GPU's logs. End-to-end localization ranges from 15.5 seconds at 2048 GPUs to 30.3 seconds at 8192 GPUs, with 21.2 seconds on a 3072-GPU setup. The case study is also convincing: Holmes inspects only 106 of 3072 GPUs, finds GPU 2574 as the straggler, and after isolating its node the average training throughput rises from 85.43 to 90.62 samples/s.

## Novelty & Impact

The novelty is not the use of machine learning alone, nor graph search alone, but their combination at the communication-operator boundary of LLM training. Holmes turns "silent slow steps" into a structured diagnosis problem whose graph edges are defined by parallel-training semantics rather than by generic system calls or service dependencies. The cross-iteration MAP layer is also important: it converts many noisy per-iteration suspicions into a ranked device list that operations engineers can act on.

This paper is likely to matter to practitioners running large training clusters and to researchers working on LLM-training reliability. It expands the reliability agenda beyond crash recovery and checkpointing toward continuous performance stability, which is arguably the more frequent source of waste in very large clusters.

## Limitations

Holmes depends on a per-training random-forest model trained from manually labeled `CommOps` logs collected over a few hours. The paper's auto-tuning reduces retraining pressure, but it does not eliminate the need for an initial labeled model, and the paper does not show how well a model transfers across clusters, frameworks, or communication-library versions.

The prototype evidence is also mixed in scope. The paper uses real production traces, but its low-latency prototype evaluation is run on a simulation framework with CPU-based log writers emulating GPU processes. That is reasonable for evaluating analytics latency, yet it is weaker than a fully in-situ deployment result. Accuracy also degrades as GPU count and parallelism dimensionality rise, and Holmes cannot meaningfully separate irregular from normal iterations when `delta` is too small; below about 1.04, normal step-time fluctuation dominates the signal. Finally, the discussion section admits that richer telemetry, such as implementation-specific collective behavior or hardware resource metrics, might improve localization but would raise logging overhead sharply.

## Related Work

- _Jiang et al. (NSDI '24)_ - `MegaScale` studies how to scale and debug more than 10,000-GPU LLM training, but its focus is explicit failures, whereas `Holmes` targets silent irregular iterations that never produce failure logs.
- _Hu et al. (NSDI '24)_ - `Characterization of Large Language Model Development in the Datacenter` characterizes LLM development behavior at cluster scale, while `Holmes` turns one overlooked symptom, step-time irregularity, into an online localization problem.
- _Gan et al. (ASPLOS '19)_ - `Seer` uses neural models to localize QoS issues in cloud microservices, whereas `Holmes` relies on communication-operator structure and training-parallelism semantics to remain interpretable and effective at GPU-cluster scale.
- _Liu et al. (ICSE-SEIP '21)_ - `MicroHECL` localizes faults with application graphs in microservices; `Holmes` adopts the graph-localization idea but rebuilds it around collective and P2P communication groups in hybrid-parallel training.

## My Notes

<!-- empty; left for the human reader -->

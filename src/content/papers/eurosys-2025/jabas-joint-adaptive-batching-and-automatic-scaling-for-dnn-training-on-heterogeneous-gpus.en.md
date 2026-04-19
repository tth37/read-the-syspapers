---
title: "JABAS: Joint Adaptive Batching and Automatic Scaling for DNN Training on Heterogeneous GPUs"
oneline: "JABAS keeps adaptive batching statistically sound on heterogeneous GPU clusters by using equal-sized virtual workers and forecasting when to scale the GPU set."
authors:
  - "Gyeongchan Yun"
  - "Junesoo Kang"
  - "Hyunjoon Jeong"
  - "Sanghyeon Eom"
  - "Minsung Jang"
  - "Young-ri Choi"
affiliations:
  - "UNIST"
  - "Samsung SDS"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696078"
code_url: "https://github.com/unist-ssl/JABAS"
tags:
  - ml-systems
  - gpu
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

JABAS tackles a failure mode that prior adaptive-batch trainers mostly sidestep: on heterogeneous GPU clusters, the common fix of assigning larger local batches to faster GPUs breaks the i.i.d. minibatch assumption and can damage convergence. It introduces IIDP, which keeps every worker's local batch size identical by running multiple virtual stream workers and optional gradient accumulation steps per GPU, then couples iteration-level batch adaptation with epoch-level GPU auto-scaling. Across three heterogeneous clusters and seven models, the paper reports 33.3% shorter training time and 54.2% lower training cost than prior adaptive-training baselines without accuracy loss.

## Problem

Adaptive batching is attractive because large global batches reduce synchronization overhead, yet using a large batch too early can hurt model quality. Prior systems therefore try to grow the global batch during training. The paper argues that this is not enough in practice: if resources stay fixed, early training often wastes GPUs because the job is communication-bound, while later training leaves performance on the table if the cluster is not enlarged as the batch grows. In the paper's GNMT example, 4 GPUs are 10.13% faster than 16 GPUs during the first two epochs, but 16 GPUs become 51% faster later and finish 70% sooner overall, at 2.34x the cost. A good system has to choose batch size and resource count together.

Heterogeneous GPUs make the problem worse. Real production clusters already mix several GPU types, but the obvious heterogeneous fix, weighted data parallelism with different local batch sizes per GPU, changes the gradient-noise distribution seen by each worker. That violates the theoretical assumption that minibatches are i.i.d., and the paper shows the damage is real: with WDP or WDP plus SimiGrad, training quality drops by up to 7.5% or diverges outright on some models. The stakes are therefore twofold: use faster GPUs well, and do so without quietly corrupting convergence semantics.

## Key Insight

The paper's core claim is that heterogeneity should be absorbed by changing how many same-sized workers each GPU runs, not by changing the local batch size of those workers. If every worker still processes the same local batch size, then gradient aggregation keeps the same semantics as ordinary data parallelism even though faster GPUs may host more work through extra virtual workers or gradient-accumulation steps.

Once that invariant holds, adaptive batching and scaling become one configuration problem. For any target global batch size and candidate GPU allocation, JABAS can search over a common local batch size plus per-GPU choices of virtual stream workers and accumulation steps, then pick the highest-throughput configuration. The system's broader insight is that convergence preservation and hardware utilization are not competing goals here; they can be reconciled if the runtime decouples workers from physical GPUs without changing per-worker sample counts.

## Design

JABAS is built around IIDP, a training runtime that executes multiple virtual stream workers (VSWs) on one GPU via CUDA streams. Each GPU has one main VSW and optional sibling VSWs. Sibling VSWs compute gradients for their local minibatches; the main VSW locally aggregates those gradients, participates in inter-GPU All-reduce, and then applies the optimizer once before copying updated weights one-way to the sibling VSWs. This avoids running a full optimizer per worker. The paper implements two weight-synchronization modes: sequential one-way synchronization (SWS) and overlapping one-way synchronization (OWS), where OWS overlaps shard-wise weight updates and copies with later All-reduce operations unless large gradient buffers would cause interference.

The configuration solver is the second pillar. JABAS profiles each model and GPU type to learn the maximum local batch size, the maximum number of VSWs, and the compute, communication, and optimizer costs needed for a performance model. It then uses dynamic programming to choose a common local batch size and per-GPU `(n_vsw, n_GA)` pair that maximize throughput for a given global batch size. Because JABAS reuses SimiGrad's gradient-similarity test, it divides the allocated GPUs into two identical groups and configures the total number of decoupled workers per group accordingly.

Control happens at two timescales. Every `p=100` iterations, the adaptive batching manager computes gradient similarity for the two groups, increases or decreases the global batch size by `alpha=0.1` within configured bounds, updates the learning rate, and asks IIDP to reconfigure VSW threads and accumulation counts without restarting GPU processes. At epoch boundaries, a global-batch forecaster predicts the next epoch's batch trajectory using an ensemble of Gaussian Process Regression and exponential smoothing. The auto-scaling manager enumerates candidate GPU allocations, estimates each one's epoch time by repeatedly calling the configuration solver over the predicted trajectory, and checkpoints plus restarts only if a different allocation is worth using.

## Evaluation

The evaluation spans three heterogeneous clusters and seven models: ResNet-50, ViT, Faster-R-CNN, GNMT, BERT-large, GPT3-XL, and LLaMA2-7B. Cluster A mixes V100, P100, TITAN RTX, and RTX 3090; cluster B mixes RTX 2060, Quadro P4000, TITAN V, and TITAN RTX; cluster C uses RTX A6000s with power limits to emulate heterogeneous compute capability for large language models. The main baselines are SimiGrad, Pollux, and Pollux-AS. WDP-style methods are discussed, but excluded from the main comparison because the paper first shows that they can degrade convergence badly on heterogeneous GPUs.

The headline result is that JABAS is both faster and cheaper while reaching the same target quality. Averaged across the paper's heterogeneous-cluster experiments, it cuts training time by 33.3% and training cost by 54.2% relative to the state of the art. Compared with SimiGrad specifically, average training time falls by 24.7% on cluster A, 31.3% on cluster B, and 43.8% on cluster C. Compared with the second-cheapest method for each workload, cost drops by 31.4%, 90%, and 41.1% on those clusters. For communication-heavy GNMT on cluster B, the cost reduction reaches 5.1x because JABAS often avoids the weakest GPUs instead of insisting on the full cluster.

The mechanism-level evidence is also useful. Dynamic VSW configuration and other JABAS control logic add less than 10% overhead for all models, iteration-time prediction error averages 5.9%, and the global-batch trajectory forecaster averages 15.8% error. Those numbers support the paper's central claim that the joint controller is practical, not just conceptually neat. The main external-validity caveat is that cluster C simulates heterogeneity by power-capping identical GPUs, and the cost model is derived from AWS p3.8xlarge pricing rather than a direct cloud bill.

## Novelty & Impact

The closest prior systems each solve only part of the problem. SimiGrad gives fine-grained batch adaptation, but not heterogeneous-GPU scaling. Pollux co-adapts batch size and resource count, but it assumes homogeneous workers and optimizes a goodput metric that the paper shows can overvalue throughput gains even when statistical efficiency collapses. VirtualFlow and EasyScale decouple workers from GPUs, but they do not combine that runtime idea with convergence-preserving adaptive batching and per-epoch scaling.

That makes JABAS interesting as both a mechanism paper and a control paper. IIDP is a concrete runtime contribution: same-sized workers, local aggregation, and one-way weight synchronization let heterogeneous GPUs behave like a better-balanced DP job. On top of that, the paper shows a clean way to share one configuration solver across batch adaptation and auto-scaling. Future work on heterogeneous ML clusters, especially systems that need to reason about training quality and resource efficiency together, is likely to cite it for that formulation even if they replace the specific predictor or solver.

## Limitations

JABAS assumes a fairly structured environment. Each node must contain homogeneous GPUs, the number of GPUs per node is assumed even, and GPU allocation is built from identical pairs so the adaptive-batching metric can compare two matched groups. The system also depends on profiling each model and GPU type to estimate maximum local batch size, maximum VSW count, and time-model parameters; bringing up a new hardware type or operator mix is therefore not free.

The scaling mechanism is deliberately coarse-grained. GPU reallocations happen only at epoch boundaries because the job must be checkpointed and restarted on a new allocation. That is reasonable for long training runs, but it does not address bursty multi-tenant interference or sudden cluster churn within an epoch. The authors also note that the dynamic-programming solver is quadratic in the number of decoupled workers per group, which was acceptable in their experiments but may need further optimization at larger scales.

Finally, the evaluation scope is narrower than the title suggests. The paper covers several model families, including LLMs, but the LLM results run on power-limited A6000s rather than a naturally mixed cluster, and the paper does not study mixed-vendor accelerators, failures, or background contention from other tenants. Those gaps do not invalidate the core idea, but they matter for production deployment.

## Related Work

- _Qiao et al. (OSDI '21)_ - Pollux co-adapts batch size and cluster resources using goodput, while JABAS targets heterogeneous GPUs and argues that preserving i.i.d. minibatches matters more than chasing raw throughput.
- _Qin et al. (NeurIPS '21)_ - SimiGrad adjusts global batch size from gradient similarity, and JABAS reuses that signal inside a heterogeneous-GPU runtime with automatic scaling.
- _Or et al. (MLSys '22)_ - VirtualFlow decouples workers from hardware with virtual nodes, whereas JABAS keeps equal local batch sizes and focuses on preserving convergence under heterogeneity.
- _Li et al. (SC '23)_ - EasyScale elastically trains with same-sized workers on GPUs, but JABAS adds adaptive batching, epoch-level GPU reallocation, and a throughput-optimizing configuration solver.

## My Notes

<!-- empty; left for the human reader -->

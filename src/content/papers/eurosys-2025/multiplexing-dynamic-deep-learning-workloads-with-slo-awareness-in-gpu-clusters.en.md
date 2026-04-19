---
title: "Multiplexing Dynamic Deep Learning Workloads with SLO-awareness in GPU Clusters"
oneline: "Mudi models inference latency as a piecewise-linear function of GPU share, predicts interference from training-model structure, and packs training beside inference without breaking SLOs."
authors:
  - "Wenyan Chen"
  - "Chengzhi Lu"
  - "Huanle Xu"
  - "Kejiang Ye"
  - "Chengzhong Xu"
affiliations:
  - "University of Macau"
  - "Shenzhen Institute of Advanced Technology, CAS"
  - "Univ. of CAS"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696074"
tags:
  - gpu
  - ml-systems
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mudi multiplexes latency-sensitive inference with lower-priority training on the same GPU cluster by turning each inference service's latency into a piecewise-linear function of GPU share and batch size. It predicts how a new training model will change that function from the model's layer structure, then combines cluster-level placement with device-level tuning. On a 12-A100 cluster and a 1000-GPU simulator, the paper reports 42% higher GPU utilization and up to 2.27x better training efficiency while keeping inference SLO violations below prior baselines.

## Problem

The paper starts from a familiar imbalance in production DL clusters. Online inference services get whole GPUs because their SLOs are in the tens to hundreds of milliseconds, but their actual utilization is poor: the authors' Alibaba traces show average inference utilization of only 37%, with average SM utilization below 37% and every service staying below 52% GPU utilization. Training jobs are not much better. Alibaba and Shanghai AI Lab traces show that about 30% of training-device time is near idle, while queueing delays can exceed 1,000 minutes.

Multiplexing is the obvious fix, but naive sharing is unsafe. The paper measures that inference colocated with other inference services can see 3.19x end-to-end interference for GPT2 and 2.40x for ResNet50 because tokenization, preprocessing, PCIe transfers, and kernel execution all contend. Inference plus training is milder, at 1.67x and 1.21x on average, which creates an opportunity, but only if the system can predict and control that interference quickly.

Prior work mostly splits the problem in the wrong place. Cluster-level schedulers choose colocations, while device-level systems tune SM partitioning, batching, or kernel launches after the fact. Mudi argues those decisions are tightly coupled: changing GPU partition size or inference batch size changes both the service latency curve and the amount of GPU left for training, so optimizing them independently wastes capacity or violates SLOs. Dynamic arrivals make this harder because inference QPS changes rapidly and many training jobs are previously unseen.

## Key Insight

Mudi's core claim is that inference latency under spatial GPU sharing is simple enough to optimize if the system models the right object: not a generic interference score, but a piecewise-linear latency curve over GPU share. For a fixed inference batch size, latency drops sharply until a cutoff point and then flattens; when a training job is colocated, the curve keeps the same shape, and the change in its slopes captures the interference introduced by that training model.

That representation creates a bridge between cluster-wide and local control. If Mudi can predict those slopes and cutoff points from the training model's architecture, it can estimate which GPU placement will hurt inference the least before the job runs. Then, on the chosen device, it only needs to search a much smaller space to find the inference batch size and minimum GPU partition that still satisfies the SLO. The paper's broader message is that explicit latency modeling is more useful here than opaque end-to-end heuristics.

## Design

Mudi has three main components. The offline profiler first samples each inference service under batching sizes from 16 to 512 and GPU shares from 10% to 90%, while colocated with representative training tasks. It records P99 latency and fits a two-segment piecewise-linear function with two slopes and one cutoff point. The authors deliberately use a low-sample model: with only six samples, piecewise fitting beats polynomial and MLP fits because it keeps profiling overhead small while retaining good accuracy.

Next, the interference modeler learns to predict those function parameters from the incoming training job's architecture. Its features are counts of common layer types such as convolution, linear, embedding, encoder, decoder, batch norm, pooling, and a catch-all bucket for other layers. Different inference services can use different lightweight regressors for each predicted parameter. This is how Mudi handles unseen training jobs: it does not need prior execution traces for the exact model, only its layer structure.

At runtime, the online multiplexer extracts the new training job's architecture and predicts the latency curves it would induce on each inference service. The cluster-level selector assigns the training job to the GPU whose colocated inference services have the smallest average predicted slope across candidate batch sizes, using low slope as a proxy for both low interference and more remaining GPU budget for training.

On the chosen device, the local tuner does two things. First, it uses Gaussian-process Bayesian optimization with an LCB acquisition function to search inference batch size online, because training throughput is not monotonic in batch size once PCIe transfer and control-flow effects are included. Second, it solves for the minimum GPU share that still keeps `W_i / b_i * P_i(b_i, Δ_i, Ψ_j) <= SLO_i`, then gives the rest to training. Because changing MPS GPU share requires restarting the service, Mudi hides that with a shadow inference instance and switches over when the new instance is ready. A memory manager built on CUDA Unified Memory can swap training memory to host RAM when larger inference batches would otherwise cause OOM.

## Evaluation

The evaluation uses a physical 12-A100 cluster and a simulator scaled to 1,000 GPUs. The physical run executes 300 training jobs; the simulator runs 5,000. Inference workloads include ResNet50, Inception, GPT2, BERT, RoBERTa, and YOLOS with service-specific SLOs. Training workloads span CNNs, recommender models, LSTMs, GNNs, BERT, YOLOv5, and ResNet18. Baselines are GSLICE, gpulets, and MuxFlow, with the first two extended with training-side tuning for fairness.

The headline result is that Mudi keeps inference latency under control while improving training progress. Average SLO violation rate drops to 0.5% in the physical cluster and 1.2% in the simulator. Depending on the service, the reduction versus baselines reaches 5.5x for ResNet50, 2.2x for Inception, 4.2x for GPT2, 2.3x for BERT, 3.8x for RoBERTa, and 6x for YOLOS. On the training side, completion time falls by up to 2.27x, waiting time by up to 1.63x, and makespan by up to 2.25x.

The mechanism-level numbers line up with that story. Average SM utilization reaches 60% and memory utilization 35%, which the paper reports as 42% and 19% above baselines. Maximum throughput while meeting SLOs improves by 67%-103% across the six inference services. The tuner usually converges within 25 iterations, and cluster-level placement overhead stays below 18 ms in the physical cluster. The strongest caveat is scale realism: the 1,000-GPU evidence comes from a fitted simulator rather than a live deployment, so the large-cluster gains are suggestive rather than fully closed.

## Novelty & Impact

The paper's main novelty is not GPU partitioning alone, and not interference prediction alone, but the way it fuses cluster-wide placement with device-level batch and resource tuning around a shared latency model. gpulets and GSLICE largely operate at the device level for inference serving; MuxFlow reasons about cluster-wide GPU sharing, but Mudi adds explicit SLO-aware inference modeling and a path for unseen training workloads. That makes the contribution a systems control formulation more than a single scheduling heuristic.

This is useful for operators running mixed DL clusters where inference must stay fast and training should opportunistically consume slack. The paper also makes a narrower point that is easy to miss: inference-plus-training is often a better sharing target than inference-plus-inference because CPU-side interference is lower. That design lesson is likely to influence later GPU-cluster schedulers even if Mudi itself is not adopted verbatim.

## Limitations

Mudi is specialized to a particular workload shape: online inference with strict latency SLOs plus training jobs that can absorb delay. The paper explicitly says it cannot handle cases where model weights and intermediates already exceed GPU memory, and it calls out LLM serving with large KV caches as outside scope. The architecture-feature predictor is also only as good as its chosen layer vocabulary; workloads dominated by unusual operators may not match the trained models well.

The evaluation is convincing on its physical cluster, but the large-scale claims depend on simulation, and some baselines had to be adapted because they were not built for mixed inference-training multiplexing. There is also operational complexity hidden in the control loop. MPS GPU-share changes require process replacement, memory swapping can delay training, and the paper eventually recommends no more than one inference plus three training tasks per GPU, with one-plus-one giving the best tradeoff.

## Related Work

- _Dhakal et al. (SoCC '20)_ - GSLICE dynamically partitions GPU resources for inference services, while Mudi adds cluster-wide placement and training-aware control.
- _Choi et al. (ATC '22)_ - gpulet profiles inference workloads to support spatio-temporal sharing on multi-GPU servers, but it does not jointly optimize inference-training colocations for dynamic cluster arrivals.
- _Xiao et al. (OSDI '20)_ - AntMan scales and schedules GPU jobs in clusters using priority-aware kernel control, whereas Mudi centers the problem on preserving inference SLOs under spatial sharing with training.
- _Zhao et al. (arXiv '23)_ - MuxFlow also targets large-scale DL clusters, but Mudi argues that explicit latency curves and architecture-based prediction handle unseen training jobs and SLO-sensitive inference more effectively.

## My Notes

<!-- empty; left for the human reader -->

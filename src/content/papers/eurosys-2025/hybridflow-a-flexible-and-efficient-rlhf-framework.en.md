---
title: "HybridFlow: A Flexible and Efficient RLHF Framework"
oneline: "HybridFlow separates inter-model orchestration from intra-model execution and reshards actor weights between generation and training without redundant copies."
authors:
  - "Guangming Sheng"
  - "Chi Zhang"
  - "Zilingfeng Ye"
  - "Xibin Wu"
  - "Wang Zhang"
  - "Ru Zhang"
  - "Yanghua Peng"
  - "Haibin Lin"
  - "Chuan Wu"
affiliations:
  - "The University of Hong Kong"
  - "ByteDance"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696075"
code_url: "https://github.com/volcengine/verl"
tags:
  - llm-training
  - gpu
  - datacenter
  - scheduling
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HybridFlow splits RLHF into a single-controller dataflow across models and multi-controller execution inside each model. Its actor-side 3D-HybridEngine switches between generation and training parallelisms on the same GPU set without redundant weight copies, yielding 1.53x-20.57x higher throughput than prior RLHF systems.

## Problem

RLHF turns a small RL DAG into a pipeline of heavyweight distributed LLM programs. In PPO-style alignment, actor, critic, reference, and reward models all run with different computation patterns and sharding choices, and the edges between them are many-to-many resharding steps rather than simple tensor handoffs.

A fully single-controller design makes intra-model dispatch too expensive, because LLM training and generation contain enormous operator graphs. A fully multi-controller design keeps local execution fast but hard-wires data transfers, model placement, and algorithm logic into per-device programs. The paper argues that this makes RLHF variants like Safe-RLHF and ReMax awkward to implement and makes actor train/generate transitions costly, because the two stages prefer different parallelisms.

## Key Insight

The right abstraction boundary is between models. There are only a few inter-model dependencies per RLHF iteration, so a single controller can cheaply coordinate execution order, placement, and data transfer. Inside each model, the system should continue using the standard multi-controller engines from LLM training and serving.

That split also reframes actor switching. If training and generation stay on the same GPU set, the system can change 3D parallel layouts between stages and optimize only the reshaping step, instead of maintaining separate actor copies or forcing both stages to share one suboptimal partition.

## Design

HybridFlow provides model classes like `ActorWorker`, `CriticWorker`, and `RewardWorker` on top of execution backends such as `3DParallelWorker`, `FSDPWorker`, and `ZeROWorker`. The controller script is then just a sequence of primitives like `generate_sequences`, `compute_values`, and model updates. The paper uses this to demonstrate flexibility: PPO takes eight lines, Safe-RLHF adds five more, and ReMax mainly changes which primitives are called.

Inter-model movement is handled by transfer protocols, each defined by a collect function and a distribute function, so models with different sharding schemes can exchange data without being rewritten for one another. `ResourcePool` defines which GPU set a model lives on; models on different pools can run asynchronously once their inputs are ready, while colocated models time-share the same devices.

The actor-specific `3D-HybridEngine` is the main optimization. Training and generation share one GPU set but use different 3D layouts. Generation shrinks tensor parallelism and increases effective data parallelism by splitting each training DP replica into several micro-DP replicas. During stage switches, the engine gathers only the parameters needed within each micro-DP group, runs generation, all-gathers responses, and repartitions the model for training. A custom grouping scheme makes training and generation partitions overlap on each GPU, which is how HybridFlow achieves zero memory redundancy during actor resharding.

Above that, an auto-mapper enumerates placement plans and GPU allocations, simulates candidate parallelisms for each model, and picks the lowest end-to-end latency configuration for the RLHF DAG.

## Evaluation

The evaluation runs PPO, ReMax, and Safe-RLHF on `Dahoas/ful-hh-rlhf` with 7B-70B Llama-family models on up to 128 A100-80GB GPUs across 16 machines. Prompts and responses are both fixed at 1024 tokens so the comparison stays fair to baselines that lack continuous batching.

The headline result is consistent: HybridFlow improves throughput by 1.53x-20.57x over DeepSpeed-Chat, OpenRLHF, and NeMo-Aligner. For PPO alone, it averages 3.67x over DeepSpeed-Chat, 3.25x over OpenRLHF, and 12.52x over NeMo-Aligner, with the largest reported gain at 20.57x. On 70B models, the paper reports an average 9.64x speedup.

The paper also validates the actor-side story directly. HybridFlow cuts training-to-generation transition time by 55.2% on average, or 11.7 seconds, and by up to 89.1% or 78.2 seconds on 70B models. On 16 GPUs, reducing generation tensor parallelism to 2 for 7B and 4 for 13B lowers generation latency by 60.3% and 36.4% relative to reusing the training partition. The placement study shows the mapping algorithm is useful as well: colocating all models wins on smaller clusters, while split or standalone placements win as scale grows. The main limitation of the evaluation is that it is mostly throughput-oriented and based on fixed-length workloads.

## Novelty & Impact

HybridFlow is not a new RLHF objective; it is a systems architecture. Its novelty is the combination of a hierarchical control model, reusable transfer protocols across sharding boundaries, zero-redundancy actor resharding, and automatic device mapping in one framework. That makes it relevant to RLHF infrastructure builders who want to swap algorithms, engines, or placements without rewriting the full distributed stack.

## Limitations

The search algorithm assumes homogeneous GPUs and is only evaluated on A100 clusters. Colocated models are mostly run sequentially to avoid contention instead of using finer-grained GPU multiplexing. The paper also studies system throughput far more than downstream alignment quality, convergence, or irregular real-world traces.

## Related Work

- _Liang et al. (NeurIPS '21)_ - RLlib Flow also treats RL as a dataflow problem, but its nodes are much lighter than the distributed LLM programs HybridFlow targets in RLHF.
- _Barham et al. (MLSys '22)_ - Pathways provides asynchronous distributed dataflow for large ML programs, whereas HybridFlow specializes that idea to a multi-model RLHF pipeline with explicit inter-model transfer protocols.
- _Yao et al. (arXiv '23)_ - DeepSpeed-Chat is the closest systems baseline; it hard-wires one RLHF execution pattern, while HybridFlow makes placement and train/generate parallelism first-class choices.
- _Rajbhandari et al. (SC '20)_ - ZeRO solves memory pressure for data-parallel training, but HybridFlow uses it only as a building block and focuses on orchestrating multiple RLHF models plus actor-stage resharding.

## My Notes

<!-- empty; left for the human reader -->

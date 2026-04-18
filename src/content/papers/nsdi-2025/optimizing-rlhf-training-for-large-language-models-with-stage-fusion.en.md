---
title: "Optimizing RLHF Training for Large Language Models with Stage Fusion"
oneline: "RLHFuse splits RLHF into sample- and micro-batch-level subtasks, then fuses generation/inference and Actor/Critic training to raise throughput by up to 3.7x."
authors:
  - "Yinmin Zhong"
  - "Zili Zhang"
  - "Bingyang Wu"
  - "Shengyu Liu"
  - "Yukun Chen"
  - "Changyi Wan"
  - "Hanpeng Hu"
  - "Lei Xia"
  - "Ranchen Ming"
  - "Yibo Zhu"
  - "Xin Jin"
affiliations:
  - "School of Computer Science, Peking University"
  - "StepFun"
conference: nsdi-2025
category: llm-and-ml-training-serving
code_url: "https://github.com/FlexFusion/FlexFusion"
tags:
  - llm-training
  - gpu
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

RLHFuse argues that RLHF inefficiency comes from drawing synchronization boundaries at the wrong granularity. It splits generation and inference into sample-level subtasks, splits Actor and Critic training into micro-batch subtasks, and then fuses those subtasks across stages so long-tail generation no longer stalls inference and one model's pipeline bubbles are filled by the other. On a 256-GPU Hopper cluster, that raises end-to-end RLHF throughput by up to 3.7x over prior systems.

## Problem

The paper studies the PPO stage of RLHF, where one iteration contains Actor generation, Reference/Reward/Critic inference, and then Actor/Critic training. Existing RLHF systems already optimize this workflow at the task level: they choose different 3D-parallel configurations for different tasks and reduce task-switching overhead. RLHFuse's complaint is that this is still too coarse, because the main waste happens inside those tasks.

The first waste source is generation skew. Generated response lengths are long-tailed, so near the end of decoding only a handful of very long samples remain. GPU utilization collapses because decoding is memory-bandwidth-bound and wants large batches, yet the inference stage still cannot start because the workflow waits for the slowest sample. The paper shows that on real RLHF runs this tail can consume more than half of generation time, and the problem worsens as maximum output length grows.

The second waste source is pipeline bubbles during training. RLHF trains two large models, Actor and Critic, and large models require high pipeline parallelism. Under the common 1F1B schedule, bubble fraction is `(N-1)/(N-1+M)` for `N` pipeline stages and `M` micro-batches. In RLHF, `M` is already constrained because the batch has been divided into mini-batches and then across data-parallel groups, so increasing `M` is not free. When `N` becomes large, a substantial fraction of GPUs sit idle. The paper's central claim is that RLHF's multi-model structure creates inefficiency that task-level optimization cannot remove.

## Key Insight

The key insight is that RLHF's real dependency boundaries are finer than the stage graph suggests. Generation and inference depend on each other at sample granularity, not only at whole-stage granularity. Once most samples have finished generation, the remaining long-tail samples can be consolidated onto a few generators while the released GPUs begin inference immediately, without violating synchronous semantics.

The same perspective applies to training. Pipeline bubbles are dependencies within one model's micro-batch schedule, but Actor and Critic are independent models in the RLHF training stage. If their micro-batches are scheduled jointly, one model can execute when the other would otherwise be idle. So the paper's lasting idea is not a new RL algorithm or a better single-task parallel strategy. It is a change in execution unit: optimize RLHF at the subtask level, where the workflow exposes exploitable overlap.

## Design

RLHFuse still begins with per-task parallel-strategy selection in the style of ReaLHF and HybridFlow. Given a model, cluster, and workload, it chooses tailored DP/TP/PP settings for each task. Its contributions start after that choice, with two fusion mechanisms.

For generation plus inference, RLHFuse monitors the generation instances and triggers migration when the number of unfinished samples drops below a threshold `Rt`. It then keeps only `m` generation instances alive for the tail. `m` is chosen to satisfy two constraints at once: enough aggregate batch capacity so decoding latency does not worsen, and enough memory to hold the surviving samples' KV cache. Among the instances, RLHFuse keeps the `m` ones with the largest remaining workloads to minimize migration volume. In the authors' cluster, migration transfers KV cache over RDMA, which lets the destination resume decoding immediately. The GPUs released by the other generation instances are then reused for Reference, Reward, and Critic inference, so inference overlaps with long-tail generation instead of waiting behind it. The paper explicitly says the same trick cannot be applied between inference and training because PPO needs mini-batches to be sampled from the full generated set.

For training, RLHFuse adapts bidirectional pipeline execution to heterogeneous models. Actor and Critic may differ in model size and in TP/PP choices, so the symmetric Chimera schedule does not apply directly. RLHFuse first normalizes the two models into compatible pipeline groups using fusion factors `K1` and `K2`, then searches for a valid fused schedule over all stages and micro-batches. A valid schedule must preserve inter-stage data dependencies, intra-stage order, deadlock freedom, and activation-memory limits. Rather than relying on a greedy heuristic, RLHFuse uses simulated annealing: initialize from a greedy schedule, generate neighbors by swapping adjacent subtasks within a stage, compute latency via a memoized dependency recurrence, and then run a second pass that reduces peak activation memory without degrading latency. Around these core ideas, the implementation also adds a tuned generation engine, balanced mini-batch partitioning across DP groups, cheaper weight redistribution, and CPU residency for frozen Reference/Reward weights.

## Evaluation

The evaluation runs on a production RLHF cluster with 32 nodes and 256 Hopper GPUs, with NVLINK inside each node and 8x200 Gbps RoCEv2 between nodes. The workloads use LLaMA 13B, 33B, and 65B models on HH-RLHF, with global batch size 512 and mini-batch size 64. The paper evaluates four Actor/Critic pairs, from 13B/33B up to 65B/33B, varies maximum generation length from 512 to 2048 tokens, and reports average sample throughput over 20 post-warm-up iterations.

End to end, RLHFuse improves sample throughput by 2.5-3.7x over DeepSpeed-Chat, 1.4-2.4x over ReaLHF, and 1.2-1.4x over RLHFuse-Base, which contains the same low-level optimizations but no stage fusion. The baseline setup is not obviously stacked in RLHFuse's favor: the paper says DeepSpeed-Chat could not run with the original mini-batch size on this testbed, so the authors increased its mini-batch size to 256 while keeping the global batch size fixed, a change they explicitly call more favorable to DeepSpeed-Chat's throughput. The breakdown explains where RLHFuse still wins. When generation length is large enough, inter-stage fusion fully hides most or all of the inference stage behind long-tail generation and reduces the combined generation-plus-inference time by 1.2-1.6x. Intra-stage fusion reduces training time by 1.2-1.3x by filling pipeline bubbles across the two models. The remaining overheads, such as data movement and weight redistribution, stay below 3% of total iteration time.

The paper also validates the two tuning components directly. For inter-stage fusion, the best migration point is around 20% of the batch remaining: smaller values leave overlap untapped, while larger values overload the surviving generation instances. For intra-stage fusion, the simulated-annealing scheduler consistently beats the greedy scheduler, reaches the paper's lower-bound latency in all but one configuration, and keeps activation memory close to the serial 1F1B lower bound. The most persuasive example is a 65B Actor plus a 33B Critic, where the fused schedule completely overlaps the smaller model's training under the chosen configuration.

## Novelty & Impact

Relative to ReaLHF and HybridFlow, RLHFuse is novel because it optimizes execution after per-task parallel strategies have already been chosen, rather than only improving those strategies or the stage-transition machinery. Relative to Chimera, it handles the harder RLHF case of two different models with different parallel layouts instead of two replicas of the same model. That makes the paper important to teams building large RLHF clusters, especially for long-output workloads where generation tails and large PP degrees are unavoidable. The contribution is a new execution mechanism for RLHF workflows, not a new alignment objective.

## Limitations

RLHFuse depends on profiling and workload predictability. The migration threshold `Rt` is derived from offline simulation of output-length distributions and must be updated as those distributions change during training. Its migration mechanism also benefits from a fast RDMA fabric; on slower networks, moving KV cache may no longer be negligible.

The fused-pipeline formulation has structural assumptions as well. Tensor-parallel degrees are assumed to be powers of two, and one model's PP configuration must be divisible into the normalized fused-stage layout. The evaluation is also mostly about throughput, not learning quality: the paper argues that synchronous semantics are preserved, but it does not separately measure convergence behavior or alignment quality, and it only studies LLaMA-family models on the authors' production cluster. Finally, the paper explicitly releases the intra-stage fusion component, but it does not specify a public release path for the full RLHFuse system.

## Related Work

- _Lei et al. (USENIX ATC '24)_ - PUZZLE reduces RLHF task-switching overhead, while RLHFuse targets underutilization inside generation and training themselves.
- _Li and Hoefler (SC '21)_ - Chimera uses bidirectional pipelines for replicated copies of one model; RLHFuse extends the idea to heterogeneous Actor and Critic models with different parallel strategies.
- _Narayanan et al. (SOSP '19)_ - PipeDream popularized 1F1B pipeline scheduling, which RLHFuse treats as the baseline whose bubbles remain expensive at large pipeline widths.
- _Jiang et al. (NSDI '24)_ - MegaScale focuses on large-scale LLM training infrastructure, whereas RLHFuse focuses on the multi-model PPO stage that is specific to RLHF.

## My Notes

<!-- empty; left for the human reader -->

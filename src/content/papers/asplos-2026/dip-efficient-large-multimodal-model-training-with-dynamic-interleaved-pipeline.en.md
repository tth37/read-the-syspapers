---
title: "DIP: Efficient Large Multimodal Model Training with Dynamic Interleaved Pipeline"
oneline: "DIP speeds multimodal training by separating modalities into pipeline segments, splitting batches into modality-specific sub-microbatches, and searching schedules online."
authors:
  - "Zhenliang Xue"
  - "Hanpeng Hu"
  - "Xing Chen"
  - "Yimin Jiang"
  - "Yixin Song"
  - "Zeyu Mi"
  - "Yibo Zhu"
  - "Daxin Jiang"
  - "Yubin Xia"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University, Shanghai, China"
  - "StepFun, Shanghai, China"
conference: asplos-2026
category: llm-training
doi_url: "https://doi.org/10.1145/3779212.3790154"
tags:
  - llm-training
  - ml-systems
  - scheduling
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

DIP separates modalities into dedicated pipeline segments, splits each batch into modality-specific sub-microbatches, and asynchronously searches a schedule. Across five 12B-94B models, the paper reports up to 97.3% higher throughput than prior systems.

## Problem

The bottleneck comes from heterogeneous modules and heterogeneous batches. An LMM may contain image encoders, language backbones, diffusion decoders, and adapters with very different costs. In the paper's 37B vision-language example, exhaustive layer splitting still leaves a 16.7% stage-latency spread and 22.8% extra bubble overhead under Megatron-LM's `1F1B` schedule.

Dynamic data amplifies that mismatch. Packing by sequence length cannot equalize work because more images mainly stress the vision path while more text mainly stress the language path. The paper reports a 4.15x gap between the lightest and heaviest packed text-to-video batches, and 40.3% overhead for a 7B VLM with dynamic data relative to a fixed-budget unimodal baseline. Variable-length LLM techniques mostly assume every layer stretches together; multimodal training breaks that assumption.

## Key Insight

The paper's main claim is that imbalance should be attacked before scheduling. If stages from very different modalities share one pipeline segment, their mismatch is structural and reordering alone cannot fix it. DIP therefore gives each modality dedicated pipeline segments, making each segment's cost behavior more predictable.

It then splits a microbatch into modality-specific sub-microbatches, so a slow image or video module can execute several shorter stages whose latency better matches a backbone stage. Because every batch has a different modality mix, schedules must be generated online, but the search runs asynchronously on idle CPU cores so it stays off the GPU critical path.

## Design

DIP combines offline partitioning with online planning. Offline, it profiles candidate sub-microbatch sizes for each modality, picks the smallest size that still preserves at least 95% of peak GPU efficiency, then assigns pipeline-segment counts roughly in proportion to measured latency and places layers across `P * K_i` model chunks.

At runtime, the planner prefetches metadata for the next batch and splits each modality's work into `M_i = ceil(N_i / B_i)` sub-microbatches. The searcher then does three things: MCTS over segment orderings, greedy dual-queue interleaving that follows `1F1B` when possible and otherwise fills bubbles with the earliest feasible stage, and per-rank memory optimization through a small approximate ILP over precomputed candidates.

An operator-level simulator provides latency and memory estimates, and the Megatron-LM runtime is extended to execute the resulting action list with explicit compute, P2P communication, and synchronization steps. Search is parallelized across CPU cores and limited to half the machine's cores.

## Evaluation

The evaluation covers five 12B-94B models on a 64-GPU H800 cluster, plus a 16-GPU H20 cluster for FSDP comparison. Baselines include Megatron-LM, `nnScaler*`, and Optimus where applicable.

On real datasets averaged over 100 iterations, DIP improves throughput by 15.6%-76.2% over baselines on VLM workloads and by 36.6%-97.3% on T2V workloads. On the H20 cluster, it is 27% faster than Megatron-LM for VLM-S, while FSDP is only about 3% slower than Megatron-LM, which suggests the gain comes from DIP's planning rather than a framework change. The ablation is also clean: on VLM-S, iteration time falls from 26.13 s in vanilla Megatron-LM to 16.05 s with all DIP components, a 62.8% improvement.

The dynamic-workload experiment best validates the paper's thesis. At high image counts, Megatron-LM becomes 52.9% slower than DIP and `nnScaler*` plus Optimus still trail by 10.4%. The sub-microbatch study shows the intended tradeoff: smaller chunks reduce schedule sensitivity, but chunks below 8 waste GPU efficiency, with size 12 working best in their setup. The planner also appears practical: DIP stays under 10 seconds of search time, while Z3 and Gurobi exceed 30 minutes once the problem grows beyond about 10 microbatches. The main caveat is that the largest 3k-16k GPU H100 results are simulated rather than executed.

## Novelty & Impact

Relative to _Jiang et al. (EuroSys '24)_, DIP is not just dynamic packing for variable-length inputs; it explicitly models modality-specific imbalance and rebuilds the pipeline around it. Relative to _Feng et al. (ATC '25)_ and _Wang et al. (ASPLOS '25)_, it aims at per-batch online adaptation to changing input mix rather than a fixed task set.

That makes DIP especially relevant to teams training frontier multimodal models on expensive GPU clusters. Its contribution is both a new scheduling mechanism and a useful reframing: the right unit of balancing is per-modality work segments, not whole multimodal microbatches.

## Limitations

DIP depends on profiling quality and simulator accuracy. Calibration improves the simulator to 97.6% average accuracy, but the system still inherits modeling error and the cost of re-profiling for new hardware or kernels. It also assumes next-batch metadata is available early enough and that model chunks remain statically placed.

The evaluation is broad across model types but narrower in deployment scope. Most real executions are on clusters up to 64 GPUs, while the 3k-16k GPU results are simulated. Some baselines are also reproduced inside Megatron-LM rather than run as their original systems. Finally, DIP optimizes scheduling inside a fixed DP/TP/PP plan instead of jointly searching the full parallelization space.

## Related Work

- _Jiang et al. (EuroSys '24)_ - DynaPipe adapts pipeline plans for variable-length multi-task training, but DIP targets modality-specific imbalance that does not hit all layers uniformly.
- _Feng et al. (ATC '25)_ - Optimus exploits bubbles in multimodal LLM training, whereas DIP adds modality-separated partitioning and per-batch online schedule generation.
- _Wang et al. (ASPLOS '25)_ - Spindle targets predefined multi-task training, while DIP focuses on dynamic input mixtures inside one multimodal pipeline.
- _Jeon et al. (ASPLOS '25)_ - GraphPipe generalizes pipeline execution to DAG schedules; DIP is more specialized around multimodal transformers and online search.

## My Notes

<!-- empty; left for the human reader -->

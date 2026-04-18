---
title: "WLB-LLM: Workload-Balanced 4D Parallelism for Large Language Model Training"
oneline: "WLB-LLM replaces token-balanced 4D training with workload-balanced variable-length packing and adaptive context sharding, delivering 1.23x average speedup."
authors:
  - "Zheng Wang"
  - "Anna Cai"
  - "Xinfeng Xie"
  - "Zaifeng Pan"
  - "Yue Guan"
  - "Weiwei Chu"
  - "Jie Wang"
  - "Shikai Li"
  - "Jianyu Huang"
  - "Chris Cai"
  - "Yuchen Hao"
  - "Yufei Ding"
affiliations:
  - "University of California, San Diego"
  - "Meta"
conference: osdi-2025
code_url: "https://github.com/Ash-Zheng/WLB-LLM-CP"
tags:
  - llm-training
  - gpu
  - scheduling
category: llm-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

WLB-LLM balances long-context LLM training by predicted latency rather than token count. It pairs variable-length packing plus delayed outlier documents at the PP level with padding-free per-document sharding plus adaptive CP selection, delivering 1.23x average end-to-end speedup.

## Problem

The paper studies a mismatch between how 4D training frameworks divide work and how long-context transformers actually spend time. Existing systems equalize token counts, but packed documents have very different per-token attention costs because a token near the tail of a long document attends to much more history than a token from a short one. Equal token counts therefore do not imply equal latency.

The authors show this on an internal 405B run over 8K H100 GPUs at 128K context: the slowest GPU has 1.44x the computation latency of the fastest. Fixed-length packing makes some pipeline micro-batches much heavier than others, and context parallelism shards packed sequences by position, so workers that receive document tails do more attention work than workers with the same token count. Naively repacking across more global batches helps only partly: it still cannot fix intra-document imbalance after sequence sharding, and in the 550M convergence study it raises training loss by reducing data-loader randomness.

## Key Insight

The paper's core idea is to balance work at the same granularity where skew is created. At the pipeline level, that means balancing predicted micro-batch latency rather than token count. At the context-parallel level, it means balancing each document's attention triangle rather than arbitrary equal-length shards of the packed sequence. The practical consequence is a runtime that can use variable-length micro-batches, delay only a few outlier documents, and choose between per-document and per-sequence sharding based on which one is actually faster for the current input.

## Design

WLB-LLM treats imbalance as a propagation problem: TP, CP, and DP all wait for their slowest worker, and PP amplifies that skew further. The paper therefore fixes PP and CP separately.

At the PP level, WLB-LLM replaces fixed-length packing with workload-aware variable-length packing. It minimizes the maximum total micro-batch latency, where latency includes both the quadratic attention term and the roughly linear cost of GEMM, collectives, and element-wise work. An online ILP solver is too expensive, so the implementation uses a greedy packer plus multi-level outlier queues. Documents above threshold `L_i` wait until a queue has one heavy document per micro-batch, then are released together; the remaining documents are greedily assigned to the least-loaded feasible micro-batch.

At the CP level, WLB-LLM adds padding-free per-document sharding. Instead of slicing the packed sequence into `2 x CP_size` equal chunks, it splits each document itself into `2 x CP_size` chunks and gives symmetric chunk pairs to workers so attention work stays balanced. If lengths are not divisible by `2 x CP_size`, the divisible part is sharded symmetrically and the remainder is round-robined. Because shorter query lengths can waste tile-level work while larger chunks benefit more from Hopper TMA multicast, WLB-LLM profiles achieved TFLOPS offline for different `Q_len` and `KV_len`, predicts attention latency for per-sequence and per-document sharding, and picks the cheaper option per micro-batch.

## Evaluation

The evaluation uses 32 nodes with 8 H100 SXM 80GB GPUs each, connected by NVLink and RoCE. Models range from 550M to 70B, with 64K and 128K contexts. The baselines are `Plain-4D`, the authors' unoptimized internal stack, and `Fixed-4D`, which adds greedy fixed-length packing within one global batch plus a static CP sharding policy.

Across all settings, WLB-LLM improves end-to-end speed by 1.23x over Plain-4D and 1.19x over Fixed-4D. On 7B-128K, always-on per-document sharding gives only 1.02x, adaptive CP sharding raises that to 1.05x, PP-side variable-length packing plus outlier delay gives 1.28x, and the full system reaches 1.33x. Longer contexts help more: on 7B the gain rises from 1.03x at 32K to 1.40x at 160K.

The optimization analysis compares balance, overhead, and convergence together. A fixed-length ILP solver can reduce imbalance, but with four global batches it costs more than 25 seconds per batch. WLB-LLM with two outlier queues reaches imbalance degree 1.05 with only 20 ms packing overhead, under 0.65% of step time. In the 550M convergence study, packing across eight global batches raises training loss by 1.6%, while WLB-LLM stays close to the single-batch baseline because it delays only a small fraction of tokens, averaging 0.5 iterations per token.

## Novelty & Impact

Relative to _Narayanan et al. (SC '21)_, WLB-LLM does not introduce a new parallel dimension; it makes existing 4D parallelism input-aware. Relative to _Jiang et al. (EuroSys '24)_, it is not a new pipeline scheduler for multi-task jobs, but a way to keep one long document from poisoning a synchronized LLM training step. That makes it a practical contribution for long-context training stacks, where the paper identifies a source of wasted GPU time that grows with context length.

## Limitations

The main limitation is scope. The evaluation is inside one internal training stack on internal LLaMA-like models, and the open-source artifact covers only the CP optimization rather than the full system. The gains also taper on larger models because communication dominates more of the step. Algorithmically, WLB-LLM still depends on offline latency profiles and heuristic queue thresholds, and its CP selector chooses one sharding mode for a whole sequence. The PP optimization also perturbs execution order by delaying outliers; the paper shows this is small, but it is still a tradeoff.

## Related Work

- _Narayanan et al. (SOSP '19)_ — PipeDream optimizes pipeline execution itself, whereas WLB-LLM focuses on balancing the variable-cost micro-batches flowing through an already chosen pipeline.
- _Narayanan et al. (SC '21)_ — Megatron-LM established large-scale tensor, pipeline, and data parallel training, but it assumes token-balanced batches rather than workload-balanced ones.
- _Jiang et al. (EuroSys '24)_ — DynaPipe dynamically optimizes pipeline schedules for multi-task training, while WLB-LLM addresses input-dependent imbalance inside one long-context LLM workload.

## My Notes

<!-- empty; left for the human reader -->

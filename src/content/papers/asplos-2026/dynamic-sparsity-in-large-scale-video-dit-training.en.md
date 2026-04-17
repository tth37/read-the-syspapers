---
title: "Dynamic Sparsity in Large-Scale Video DiT Training"
oneline: "Learns low-rank attention predictors to keep only dynamic critical KV pairs, then couples sparse kernels with hybrid context parallelism for faster video DiT training."
authors:
  - "Xin Tan"
  - "Yuetao Chen"
  - "Yimin Jiang"
  - "Xing Chen"
  - "Kun Yan"
  - "Nan Duan"
  - "Yibo Zhu"
  - "Daxin Jiang"
  - "Hong Xu"
affiliations:
  - "Computer Science and Engineering, The Chinese University of Hong Kong, Shatin, Hong Kong"
  - "Independent, Beijing, China"
  - "StepFun, Shanghai, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762216"
code_url: "https://github.com/NetX-lab/DSV"
tags:
  - ml-systems
  - gpu
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

DSV speeds up video Diffusion Transformer training by exploiting a property the authors measure directly: most attention mass is carried by a small, changing set of key-value pairs. It learns low-rank predictors to identify those KV pairs, implements sparse attention with custom kernels, and changes context parallelism to match per-head sparsity. On up to `128` H800 GPUs and `520k` tokens, the paper reports up to `3.02x` higher training throughput without clear quality loss relative to full attention.

## Problem

The paper targets a bottleneck that is especially acute for modern video generation. Video DiTs increasingly use 3D full attention because simpler spatial-temporal factorizations lose detail, but at long sequence lengths that choice becomes extremely expensive. For 1.3B and 3B models at `200k` tokens, the authors show self-attention consuming `92%` and `93%` of forward/backward time. Those long sequences also force context parallelism, so the bottleneck is tied to inter-GPU communication as well as local compute.

Static sparse patterns are not an easy fix. The paper shows that video-DiT attention is sparse, but not locally predictable: critical KV pairs do not concentrate in windows, sparsity varies across blocks and heads, and it grows during training. In the case study, the top `10%` of KV pairs explain over `90%` of the attention score for `95.2%` of queries in one block and `86.8%` in another, yet only `15.1%` of critical pairs lie within five tokens of the query. The challenge is therefore to exploit sparsity without first paying the full dense-attention cost, then carry that benefit through kernels and multi-GPU parallelism.

## Key Insight

The central claim is that video-DiT attention is sparse enough to prune aggressively, but only if sparsity is treated as a runtime property rather than a fixed mask. DSV therefore learns a cheap low-rank approximation of attention scores and uses it only to rank likely critical KV pairs before the expensive dense path runs.

That works because the important KV pairs are easy to separate from the long tail, and because neighboring queries often want similar KV sets even though those keys are not spatially local. The paper reports over `92.4%` overlap within a `2x2x2` token cube and about `80.1%` overlap on average across blocks. That combination lets DSV estimate sparse structure once, reuse it across nearby queries, and turn sparsity into real kernel-level speedup instead of losing the gain to irregular memory access.

## Design

DSV has three components: a sparsity predictor, sparse kernels, and sparsity-aware context parallelism. A profiler periodically samples full attention to track per-head sparsity. For each attention block, DSV trains low-rank query/key projections so that `Q_lr K_lr^T` approximates `QK^T`; the loss emphasizes preserving score ordering rather than exact values. The default low-rank dimension is `16`, and the extra predictor state stays below `10M` parameters for a 3B model.

Training runs in two stages. Stage 1 keeps attention dense while training the predictor until average approximation loss falls below `0.01`, usually within about `5k` iterations. Stage 2 keeps finetuning the predictor, but an operation dispatcher enables sparse attention only when measured sparsity and memory headroom justify it; otherwise the block falls back to full attention.

The kernel work is essential. A naive sparse path would materialize a `[H, S, S]` score tensor and then run `top-k`, which would require about `320 GB` at `H=16` and `S=100k`. DSV instead fuses low-rank matrix multiplication and `top-k` selection into one kernel, keeping only running top candidates and reducing storage from `O(S^2)` to `O(SK)`. It also uses query grouping, where nearby queries share the central query's predicted KV set, to recover memory coalescing and tensor-core utilization.

The last piece is parallelism. Standard head-wise CP becomes imbalanced when some heads are much sparser than others, while standard sequence-wise CP still gathers all remote KV tensors. DSV adds sparse HCP, which reallocates heads to minimize the slowest GPU's compute burden, and sparse SCP, which exchanges only predicted critical KV tensors. A small optimizer chooses the best hybrid split per block.

## Evaluation

The authors evaluate 0.8B, 2.7B, and 30B video DiTs on UCF-101, WebVid-10M, VideoGen, and OpenVid, using up to `128` H800 GPUs. Against dense full attention and window-based attention, DSV improves training throughput by `2.1x-3.02x` over full attention on the 2.7B VideoGen setup as length scales to `520k` tokens, and by `2.06x-2.53x` over full attention on the 30B OpenVid setup. The kernel study reports `2.2x-5.7x` forward speedup and `3.3x-4.0x` backward speedup at `90%` sparsity.

Model quality stays close to full attention. On UCF-101, FVD is `438.02` for DSV versus `440.32` for full attention; on OpenVid it is `782.22` versus `838.52`; on WebVid the two are nearly tied. VBench shows similarly small gaps, and a 30-person blind user study gives DSV the best normalized score, `4.57`, above full attention's `4.25`. I take that as evidence that DSV is quality-preserving in the measured regimes, not just a fast approximation. That last sentence is an inference from the reported metrics rather than the paper's own wording.

## Novelty & Impact

Relative to _Dao et al. (NeurIPS '22)_, DSV is not another dense-attention kernel optimization; it tries to avoid much of the quadratic work once sparsity becomes predictable. Relative to fixed-window video attention, its key move is to reject the assumption that useful sparsity must be local or static. Relative to existing context-parallel training schemes, it lets sparsity directly reshape communication volume and head assignment.

That makes the paper useful beyond one model family. Its reusable idea is to measure emergent sparsity in training, learn a cheap predictor for it, and then co-design kernels plus parallelism around that structure.

## Limitations

DSV adds real complexity. It depends on offline profiling for query-group size, sparsity thresholds, and compute/communication models, and some of that tuning is hardware-specific. The system also needs predictor warm-up, continued sparsity profiling, random spot-checks against dense attention, and CPU offload of critical-KV indices. The paper further shows that aggressive pruning is unsafe: keeping only `40%` of attention mass hurts convergence.

Its scope is also bounded. The largest evaluated model is `30B`, so the work does not yet address pipeline-parallel load balancing for bigger DiTs. Query-specific sparsity is left to future work, and the distributed gains are validated much more thoroughly for training than for inference.

## Related Work

- _Peebles and Xie (ICCV '23)_ — DiT establishes diffusion transformers as a scalable generative backbone; DSV focuses on making their long-video training path affordable.
- _Dao et al. (NeurIPS '22)_ — FlashAttention makes dense exact attention IO-aware, whereas DSV uses learned sparsity to skip much of the score and value work itself.
- _Esser et al. (ICML '24)_ — scaling rectified-flow transformers shows the push toward larger generative transformers, and DSV addresses the systems bottleneck once video token counts become extreme.

## My Notes

<!-- empty; left for the human reader -->

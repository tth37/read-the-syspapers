---
title: "DeltaZip: Efficient Serving of Multiple Full-Model-Tuned LLMs"
oneline: "DeltaZip compresses full-model-tuning deltas into sparse low-bit updates, keeps the base model resident, and batches requests across fine-tuned variants efficiently."
authors:
  - "Xiaozhe Yao"
  - "Qinghao Hu"
  - "Ana Klimovic"
affiliations:
  - "ETH Zurich"
  - "MIT"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717468"
code_url: "https://github.com/eth-easl/deltazip"
tags:
  - llm-inference
  - gpu
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

DeltaZip treats each full-model-tuned variant as a base model plus a compressed delta. It prunes and quantizes that delta, keeps the base model resident, and executes base-model and delta matmuls separately so requests for different variants of the same base can batch together. On their serving traces, the authors report 2x-12x higher throughput than a swapping-based vLLM baseline while keeping quality close to FP16.

## Problem

Hosted LLM platforms increasingly need to serve many fine-tuned variants with bursty, long-tail demand. Dedicating GPUs to each variant wastes capacity because most variants are idle most of the time. Swapping full checkpoints across a smaller GPU pool is cheaper, but requests then pay model-load latency and still batch poorly because every variant is treated as a separate model.

Adapter-based systems help only when PEFT quality is acceptable. The paper's motivating evidence is that LoRA can match FMT on easier tasks yet still trails on harder code and math workloads. For providers that want FMT-level quality, the real systems problem is how to make those full-model-tuned variants cheap enough to host together.

## Key Insight

The paper's central claim is that a full-model-tuned checkpoint is better represented as a small perturbation of the base model than as a brand-new model. Even though FMT updates all parameters, the delta usually has much smaller magnitude and many more near-zero values than the original weight matrix, so it is much easier to prune and quantize aggressively.

That observation changes both compression and serving. At runtime, the system can compute `W_base X` once for all variants that share a base and add a cheap sparse low-precision `ΔX` per variant. During compression, however, each layer must be calibrated against the reconstructed weight `W_base + compressed_delta`; otherwise later-layer activations shrink and calibration quality collapses.

## Design

DeltaZip has an offline compressor and an online serving path. ΔCompress subtracts the base model from the fine-tuned model, applies 2:4 structured pruning, quantizes the remaining values to 4-bit or 2-bit, and can optionally add lossless compression. The 2:4 choice is hardware-aware: modern GPUs accelerate exactly that sparse pattern. The compressor works layer by layer on a small calibration set, reconstructing `W_base + Q ⊙ M` after every layer so the next layer sees realistic activations. The paper says 256 calibration samples are enough and that compressing a 7B model takes about 30 minutes on one RTX 3090.

At serving time, the base model stays on GPU, while compressed deltas live across disk, CPU memory, and GPU memory. Every linear layer is evaluated as a shared FP16 base GEMM plus a sparse low-precision delta matmul, and the outputs are merged before nonlinearities. DeltaZip extends tensor parallelism by partitioning base weights and deltas in the same way.

The main runtime optimization is Selective Batched Matrix Multiplication (SBMM). The scheduler groups requests by delta and reduces random accesses, then one GPU kernel processes multiple deltas in parallel instead of launching many tiny kernels. Continuous batching admits at most `N` resident deltas per iteration, and a simple preemption rule limits starvation when hot deltas keep attracting new requests.

## Evaluation

The evaluation makes two points. First, delta compression preserves quality far better than compressing full model weights directly. On Llama 13B, DeltaZip's 2-bit and 50%-sparse delta reaches 11.83x compression while keeping BoolQ/TruthfulQA/LogiQA at 84.95/42.54/27.65 versus 85.29/43.00/27.04 for FP16. On Llama 70B, the same recipe reaches 13.96x compression with similarly small changes. SparseGPT-style compression on full weights degrades accuracy much more at roughly similar compression ratios.

Second, the serving path pays off when demand is long-tail. On 4-way tensor-parallel A800 nodes with 32 model variants and LMSys-derived traces, DeltaZip improves throughput by 2x-12x and average end-to-end latency by 1.6x-16x over a vLLM-SCB baseline that swaps full models and batches by model. TTFT improves even more, because the shared-base batching reduces queueing. The gain narrows under high-load uniform demand, where prompt processing dominates. The paper also shows why compressed FMT matters: on Llama-7B GSM8K, full FMT scores 34.79, LoRA 29.49, and DeltaZip-compressed FMT 34.95.

## Novelty & Impact

The novelty is the end-to-end co-design. Punica and S-LoRA show how to share a base model across adapter variants, while SparseGPT and AWQ compress whole models. DeltaZip applies compression to FMT deltas instead, calibrates those deltas correctly, and serves them natively without reconstructing a full checkpoint on the request path. That makes full-parameter tuning far more practical for providers that host many low-volume variants on top of a few base models.

## Limitations

DeltaZip is least compelling when only a few variants exist and all of them fit in GPU memory, because direct full-checkpoint serving can then be faster. It also does not reduce prefill cost, so high-load uniform workloads remain bounded by prompt processing. On the systems side, the scheduler trades strict per-model fairness for batching efficiency, and LoRA/FMT co-serving is still coarse-grained: both are supported, but not in the same mixed batch.

## Related Work

- _Chen et al. (MLSys '24)_ - Punica shows how to batch many LoRA adapters on a shared base model, while DeltaZip extends that multi-tenant serving logic to full-model-tuned variants.
- _Sheng et al. (arXiv '23)_ - S-LoRA improves adapter serving with unified paging and large-scale batching, but it still assumes PEFT-style adapters rather than compressed full-model deltas.
- _Frantar and Alistarh (arXiv '23)_ - SparseGPT compresses full model weights directly; DeltaZip instead compresses deltas and reconstructs each layer during calibration to avoid large quality loss.
- _Fu et al. (arXiv '24)_ - ServerlessLLM speeds model loading in a black-box serving setting, whereas DeltaZip exploits shared lineage between variants so different fine-tuned models can batch through the same base-model path.

## My Notes

<!-- empty; left for the human reader -->

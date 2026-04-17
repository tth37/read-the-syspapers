---
title: "SuperOffload: Unleashing the Power of Large-Scale LLM Training on Superchips"
oneline: "Redesigns LLM training offload for superchips with adaptive weight placement, bucket repartitioning, and speculative CPU optimizer overlap to train larger and longer models on fewer GPUs."
authors:
  - "Xinyu Lian"
  - "Masahiro Tanaka"
  - "Olatunji Ruwase"
  - "Minjia Zhang"
affiliations:
  - "University of Illinois, Urbana, IL, USA"
  - "Microsoft, Redmond, WA, USA"
  - "Snowflake, Bellevue, WA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762217"
tags:
  - llm-training
  - memory
  - gpu
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

SuperOffload redesigns LLM-training offload for GH200-style superchips instead of reusing PCIe-era rules. It keeps Hopper, Grace, and NVLink-C2C busy together through adaptive weight placement, bucket repartitioning, and speculative optimizer overlap, enabling up to 25B training on one superchip and 1M-token 13B training on 8 superchips.

## Problem

The paper targets the common case where teams want to train or post-train LLMs with far fewer GPUs than pretraining runs use. CPU offloading is attractive because CPU memory can absorb optimizer states, gradients, and sometimes parameters.

But those systems assume a PCIe-connected accelerator, so they optimize mostly for minimizing transfer volume. GH200 changes the tradeoff: Grace and Hopper are tightly coupled on one package, linked by high-bandwidth NVLink-C2C, and the CPU is strong enough to execute real optimizer work. In that setting, PCIe-era heuristics can underuse the CPU, waste C2C bandwidth, and still leave synchronization gaps on the critical path. The challenge is therefore to redesign offloading around tightly coupled heterogeneous hardware, not just offload more tensors.

## Key Insight

The core claim is that on superchips, minimizing bytes moved is the wrong objective; maximizing simultaneous use of GPU compute, CPU compute, and C2C transfer is the right one. That means tensor placement, casting, and optimizer scheduling must all be revisited together.

SuperOffload therefore treats training as a Superchip-aware dataflow graph, chooses between keeping weights on GPU or flowing them through CPU memory depending on the regime, and overlaps CPU optimizer work with GPU backward propagation. Offloading becomes a throughput optimization as well as a capacity optimization.

## Design

SuperOffload has five main pieces. First, it switches between weight-stationary and weight-flow offloading. The former looks like classic optimizer-state offload and works when micro-batches are small enough that repeated weight movement would not pay off. The latter becomes useful when long sequences make activations dominate memory, so moving more weights to CPU frees GPU space for larger contexts.

Second, it redoes bucketization around GH200's bandwidth curve. Transfers are grouped into about `64 MB` buckets, where C2C bandwidth is near saturation, and the last few buckets' optimizer states stay on the GPU so the next iteration does not wait on CPU-produced updates. This is a direct fix for the exposed tail latency that remains in earlier bucketized designs.

Third, it introduces Speculation-then-Validation (STV). The CPU starts optimizer steps before global gradient clipping and NaN/Inf checks finish, while validation runs in parallel. If validation later fails, the system rolls back and replays the update. Fourth, Superchip-Aware Casting chooses to cast on the GPU and move FP32 tensors when that is faster than casting on CPU and moving FP16. Fifth, GraceAdam uses ARM SVE, prefetching, tiling, and OpenMP to make Grace CPU optimizer execution fast enough to matter.

The system also extends to multi-superchip training by combining with ZeRO-3-style partitioning and with Ulysses sequence parallelism, plus NUMA-aware placement so each process stays close to its local Grace-Hopper pair.

## Evaluation

The evaluation directly tests the paper's claim on GH200 hardware. The authors use 1x GH200 and multi-node GH200 NVL2 clusters, GPT/LLaMA-style models, and the Pile. Baselines include PyTorch DDP, Megatron, ZeRO-2/3, ZeRO-Offload, ZeRO-Infinity, FSDP-CPU Offload, and Ulysses.

The main numbers are strong. On one superchip, SuperOffload achieves up to `67%` higher throughput than PyTorch DDP and around `2x` average throughput over ZeRO-Offload, peaking at `2.5x`. On 4 and 16 GH200s, it reports up to `83%`, `46%`, and `37%` higher throughput than Megatron, ZeRO-2, and ZeRO-3, while still averaging `2.5x` over ZeRO-Offload. Scale also improves sharply: one superchip can train up to `25B` parameters versus `15B` for ZeRO-Offload and `3.5B` for DDP.

The long-sequence story is similarly compelling. SuperOffload-Ulysses supports sequences up to `8x` longer than vanilla Ulysses and trains a `13B` model at `1 million` tokens on `8` superchips with `55%` MFU. The breakdown study also supports the mechanism-level claims: GraceAdam adds `10.4%`, Superchip-Aware Casting `12.7%`, STV `45%`, and bucket repartitioning `14.1%`, for `2.06x` total gain over the baseline. I found the evidence convincing for GH200-class training, though much less informative about portability to other integrated CPU-GPU platforms.

## Novelty & Impact

Relative to _Ren et al. (ATC '21)_, this is not merely a better ZeRO-Offload implementation; it changes the objective from "minimize PCIe traffic" to "maximize whole-superchip utilization." Its novelty is the combination of adaptive weight placement, exact speculative overlap, casting-policy inversion, and an ARM-tuned optimizer inside one runtime.

## Limitations

The paper is tightly bound to GH200. The `64 MB` bucket choice, the casting tradeoff, GraceAdam's SVE path, and the NUMA assumptions all depend on Grace-Hopper characteristics, so generalization to MI300A or future GB200-like systems is not demonstrated. STV also relies on rollback events being rare; the 175B run supports that assumption, with only `93` rollbacks from step `1000` to `80000` (`0.12%`), but the paper does not explore regimes with much more frequent clipping or instability. Finally, the long-sequence evaluation centers on 13B and 30B GPT-style models, not a wider range of post-training pipelines or optimizers.

## Related Work

- _Ren et al. (ATC '21)_ — ZeRO-Offload established CPU offloading for large-model training, but it was tuned for PCIe-era systems and mostly optimizer-state offload rather than superchip-wide co-design.
- _Huang et al. (ASPLOS '20)_ — SwapAdvisor studies tensor movement across heterogeneous memory, while SuperOffload specializes that idea to mixed-precision LLM training with exact optimizer overlap.
- _Rhu et al. (MICRO '16)_ — vDNN pioneered memory virtualization for DNN training, whereas SuperOffload targets transformer-scale training and treats CPU execution, not just memory capacity, as a first-class resource.
- _Rasley et al. (KDD '20)_ — DeepSpeed made extreme-scale training practical as a software stack; SuperOffload fits into that ecosystem but focuses specifically on exploiting tightly coupled CPU-GPU superchips.

## My Notes

<!-- empty; left for the human reader -->

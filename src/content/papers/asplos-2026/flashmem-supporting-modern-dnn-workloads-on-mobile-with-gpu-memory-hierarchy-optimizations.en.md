---
title: "FlashMem: Supporting Modern DNN Workloads on Mobile with GPU Memory Hierarchy Optimizations"
oneline: "FlashMem replaces full weight preloading with offline-planned streaming, texture-aware layouts, and pipelined kernels to run larger mobile DNN workloads in less memory."
authors:
  - "Zhihao Shu"
  - "Md Musfiqur Rahman Sanim"
  - "Hangyu Zheng"
  - "Kunxiong Zhu"
  - "Miao Yin"
  - "Gagan Agrawal"
  - "Wei Niu"
affiliations:
  - "University of Georgia"
  - "University of Texas at Arlington"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790164"
tags:
  - ml-systems
  - gpu
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

FlashMem replaces "load the whole model first" with an offline-generated streaming plan for weight chunks. Combined with texture-aware layouts and branch-free pipelined kernels, that lets phone GPUs run larger single-model and multi-model workloads with lower memory use and lower end-to-end latency.

## Problem

The paper starts from a mismatch between modern mobile AI workloads and existing runtimes. Phones increasingly run several models back-to-back, or a single model large enough to stress memory on its own, yet mainstream mobile frameworks still preload all weights before inference. On a OnePlus 12, the authors report peak memory of 4,077 MB for Whisper-Medium and 4,858 MB for SD-UNet under MNN. They also show that loading and weight-transformation overhead can dominate actual compute time.

Naive streaming is not enough either. Mobile GPUs move weights through disk, unified memory, and texture memory, and operators tolerate overlapped loading very differently. Softmax and LayerNorm slow down quickly, while MatMul can hide much more transfer work. The real problem is deciding which weight chunks to stream at which layers.

## Key Insight

FlashMem's core claim is that mobile DNN execution becomes tractable once weight residency is planned jointly with operator load capacity. Because the lowered graph order is known, the runtime can decide which weights must be preloaded, how early others should enter unified memory, and how many chunks can be transformed into texture memory at each layer. If those decisions respect per-layer overlap capacity, the system can keep only part of a model resident and still avoid stalling compute.

That is why FlashMem uses offline planning instead of online heuristics: memory layout, operator fusion, and kernel scheduling all change how much overlap is actually usable.

## Design

FlashMem has three main mechanisms. First, it formulates Overlap Plan Generation (`OPG`) on the lowered graph. The plan chooses a preload set `W`, an earliest load layer `z_w` for each weight, and chunk allocations `x_{w,l}` for texture-memory transformation. The objective penalizes both large upfront preloads and long residency times. The implementation uses CP-SAT plus a custom load-capacity-aware solver, `LC-OPG`, with fallback strategies when exact solving gets stuck.

Second, FlashMem estimates how much overlap each layer can sustain. It profiles operators, classifies them as elemental, reusable, or hierarchical, and uses an XGBoost model to derive a per-layer capacity budget `C_l`. Those budgets constrain the solver. If fusion removes too many scheduling boundaries, FlashMem selectively splits fused kernels again; here, more fusion can hurt because it leaves fewer places to hide loading.

Third, FlashMem makes the plan executable. It reorganizes weights into 2.5D texture-oriented layouts to reduce reshapes and transposes, then rewrites kernels into a branch-free pipeline where each iteration prefetches the next tile while computing on the current one. That reduces SIMT divergence and helps hide texture-memory latency.

## Evaluation

The evaluation covers 11 models across six task types on a OnePlus 12 plus three additional phones. Compared with product-style baselines, FlashMem reports geometric-mean end-to-end speedups of `6.1x` over MNN, `6.2x` over TVM, `1.7x` over LiteRT, and `75x` over ExecuTorch. Against SmartMem, the closest research baseline, the geomean speedup is `8.6x`. On memory, FlashMem cuts average usage by `3.5x` relative to SmartMem and by up to `8.4x` relative to TVM. A representative large-model result is GPT-Neo-1.3B, which drops from 2,667 MB average memory in SmartMem to 554 MB in FlashMem while integrated latency falls from 48,610 ms to 3,086 ms.

Two results matter most for the thesis. First, FlashMem is the only evaluated framework that can run GPT-Neo-2.7B on the tested mobile GPU. Second, in sequential multi-model experiments it stays under a manually set 1.5 GB memory budget while MNN repeatedly spikes during initialization. The ablation supports the design story: `OPG` alone gives `5.3x-8.1x` speedups and `2.1x-3.8x` memory reductions over SmartMem, with adaptive fusion and kernel rewriting adding smaller gains. The main caveat is scope: FlashMem measures integrated initialization-plus-execution latency, so its biggest wins are in cold-start and model-switching regimes.

## Novelty & Impact

Relative to _Niu et al. (ASPLOS '24)_, FlashMem's novelty is treating weight residency as a first-class optimization variable instead of focusing only on layout transformation. Relative to _Li et al. (MobiCom '24)_, it is much more explicitly about mobile GPU hierarchy and texture memory. Relative to _Han et al. (MobiSys '24)_, it attacks loading and transformation overhead rather than preemption policy.

This reads as a mechanism paper rather than a measurement paper: the planner, capacity model, and kernel rewriting path form one coherent system.

## Limitations

FlashMem depends on substantial offline work: the solver is run before deployment on a workstation with 512 GB DRAM, and the paper allows up to 150 seconds of solve time. It also assumes mostly static graphs; dynamic neural networks are left to future work. The experiments use batch size 1 and FP16/FP32 only, so interaction with quantized models or burstier workloads is unresolved.

The multi-model story is also narrower than the title suggests. FlashMem mainly targets sequential or FIFO-like model execution, not richer preemptive settings, and its gains are smaller for convolution-heavy networks whose weight transformations are harder to overlap.

## Related Work

- _Niu et al. (ASPLOS '24)_ — SmartMem removes many texture-layout transformations, while FlashMem extends that line with offline overlap planning, selective defusion, and pipelined kernel-level streaming.
- _Li et al. (MobiCom '24)_ — FlexNN also targets memory-constrained edge inference, but focuses on adaptive slicing/loading on mobile CPUs rather than texture-memory-aware execution on mobile GPUs.
- _Han et al. (MobiSys '24)_ — Pantheon addresses preemptible multi-DNN inference on mobile edge GPUs; FlashMem instead optimizes the FIFO-style model-switching path and the memory hierarchy beneath it.
- _Kwon et al. (SOSP '23)_ — vLLM shows how paging can reduce memory pressure for datacenter LLM serving, whereas FlashMem adapts the broader idea of non-resident weights to mobile GPUs with very different hierarchy and kernel constraints.

## My Notes

<!-- empty; left for the human reader -->

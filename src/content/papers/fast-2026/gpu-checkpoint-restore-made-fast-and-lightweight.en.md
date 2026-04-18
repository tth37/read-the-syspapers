---
title: "GPU Checkpoint/Restore Made Fast and Lightweight"
oneline: "GCR lets the driver handle GPU control state, copies data buffers separately, and uses CPU shadow execution to make incremental checkpoints fast with under 1% runtime overhead."
authors:
  - "Shaoxun Zeng"
  - "Tingxu Ren"
  - "Jiwu Shu"
  - "Youyou Lu"
affiliations:
  - "Tsinghua University"
conference: fast-2026
category: ai-era-storage
tags:
  - gpu
  - fault-tolerance
  - serverless
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`GCR` splits GPU checkpoint/restore into driver-managed control state and separately copied data buffers. It preserves virtual addresses through page-table restore and uses CPU shadow execution with dirty templates for incremental checkpoints, cutting checkpoint latency by `72.1%` versus `cuda-ckpt` while keeping runtime overhead below `1%`.

## Problem

The paper targets elastic GPU serverless scaling, rapid task switching, and fault-tolerant GPU computation. The common requirement is a system primitive that works across inference, training, and HPC workloads without framework-specific checkpoint logic.

The two existing design families fail in opposite ways. Driver-integrated checkpointing such as `cuda-ckpt` adds almost no runtime overhead and handles opaque GPU control state well, but it copies GPU data buffers slowly, reaching only `3.0 GB/s` on checkpoint and `7.2 GB/s` on restore. Interception-based systems such as `PhOS` can use asynchronous copies, but they must intercept and serialize much of the GPU API surface, so control-state handling becomes expensive and normal execution slows by `8.7%` on average, peaking at `49.6%`.

Neither path supports practical incremental checkpointing. In the paper's `Llama2-7B` inference example, the ideal incremental checkpoint is `4.1 GB`, yet both baselines still write about `30 GB`, a `7.2x` amplification.

## Key Insight

The central claim is that GPU control state and GPU data buffers should not be checkpointed by the same mechanism. Control state is driver-private and small enough to leave to the driver's opaque machinery; data buffers are bulk bytes and should move through a direct high-bandwidth copy path. Once those paths are separated, the main correctness invariant is preserving GPU virtual addresses across restore.

The same logic drives incremental checkpointing. Fine-grained dirty tracking matters, but doing it on the GPU critical path is too expensive. `GCR` instead identifies writes on the CPU via shadow execution of templates that compute only dirty addresses and lengths.

## Design

`GCR` is a library plus a checkpoint backend. During normal execution it intercepts only GPU memory allocation and deallocation through `LD_PRELOAD`, recording each buffer's address and length; the metadata is tiny, and the reported overhead is under `1%`.

Checkpointing is hybrid. `GCR` first copies intercepted GPU data buffers into CPU memory with asynchronous copies, then deallocates only their physical memory so the later driver-integrated checkpoint will not capture them again. It then invokes driver-integrated checkpointing for the remaining GPU control state, including the GPU page table. During restore, the driver recreates control state and the saved page table, while `GCR` allocates fresh physical memory with `cuMemCreate`, remaps it onto the preserved virtual addresses with `cuMemMap`, and copies the buffer contents back. The paper reports less than `0.1%` extra control-state overhead from page-table preservation, and only `432 us` to remap `27.3 GB` in one example.

For incremental checkpoints, `GCR` generates dirty templates offline from PTX. Each template reduces a kernel to the store instructions that determine dirty addresses and lengths as functions of kernel arguments and launch dimensions. At runtime, `GCR` intercepts kernel launches, feeds those arguments into the template, and shadow-executes the result on the CPU in parallel with the real GPU kernel. For supported kernels, this takes microseconds and under `1 MB` of CPU memory; for opaque kernels, the system falls back to conservative marking or disables incremental checkpointing.

## Evaluation

The evaluation uses two `A100-40GB` GPUs with `NVLink` and `PCIe 4.0`, running `CUDA 12.6`, `PyTorch 2.7.1`, `Transformers`, `vLLM`, and `DeepSpeed`. The workload mix covers LLM inference for serverless cold start, LLM and DNN training for switching and fault tolerance, and one HPC molecular-dynamics workload.

For elastic GPU serverless scaling, `GCR` reduces cold-start latency by `54.2%` on average versus `cuda-ckpt` and `87.1%` versus `PhOS`. Its restore bandwidth reaches `23.0 GB/s`, about `92%` of the PCIe limit, or `3.4x` and `11.5x` higher than the two baselines. For rapid task switching, total switch latency drops by `71.6%` versus `cuda-ckpt` and `74.1%` versus `PhOS`. For full checkpointing, latency falls by `72.1%` versus `cuda-ckpt` and `63.6%` versus `PhOS`, with `20.5 GB/s` checkpoint bandwidth. Incremental checkpointing then cuts checkpoint size by `86.6%` and checkpoint latency by `43.8%` relative to the first checkpoint, while normal execution stays above `99.9%` of baseline throughput on average.

## Novelty & Impact

The paper's novelty is the combination, not any one ingredient: driver-integrated checkpointing for control state, interception only for data buffers, and symbolic dirty templates for low-overhead incremental checkpoints. That makes it a useful reference point for GPU serverless systems, multi-tenant schedulers, and fault-tolerant training infrastructure.

## Limitations

`GCR` depends on vendor support for driver-integrated checkpoint/restore, low-level GPU virtual-memory APIs, and enough kernel visibility to generate dirty templates. For closed-source or poorly documented kernels, incremental checkpointing may need to be disabled or fall back to coarse marking. The prototype also stores checkpoints only in CPU memory, synchronizes kernels before checkpointing, and leaves concurrent checkpoint/restore as future work. Portability beyond NVIDIA `A100` is argued, not demonstrated.

## Related Work

- _Wei et al. (SOSP '25)_ — `PhoenixOS` / `PhOS` intercepts the full GPU API surface and uses validated speculation, while `GCR` narrows interception to memory management and delegates control state back to the driver.
- _Yang et al. (SoCC '24)_ — on-demand and parallel GPU checkpoint/restore improves C/R with modified-driver support, whereas `GCR` targets commodity drivers and adds incremental dirty-buffer tracking.
- _Fu et al. (OSDI '24)_ — `ServerlessLLM` performs application-level restoration for serverless LLM inference; `GCR` provides framework-transparent system-level GPU state C/R.
- _Lee et al. (ICS '19)_ — `GPU Snapshot` offloads checkpointing in GPU-dense systems with stronger hardware assumptions, while `GCR` is designed for current production GPUs.

## My Notes

<!-- empty; left for the human reader -->

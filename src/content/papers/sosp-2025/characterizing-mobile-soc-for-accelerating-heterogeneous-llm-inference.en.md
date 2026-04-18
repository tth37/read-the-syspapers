---
title: "Characterizing Mobile SoC for Accelerating Heterogeneous LLM Inference"
oneline: "HeteroInfer profiles mobile GPU/NPU quirks, then partitions LLM work across both engines so prefill uses more compute and decoding uses more DRAM bandwidth."
authors:
  - "Le Chen"
  - "Dahu Feng"
  - "Erhu Feng"
  - "Yingrui Wang"
  - "Rong Zhao"
  - "Yubin Xia"
  - "Pinjie Xu"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "Tsinghua University"
  - "SenseTime Research"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764808"
tags:
  - llm-inference
  - gpu
  - hardware
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HeteroInfer shows that mobile LLM inference should use GPU and NPU together, but only after profiling their real bottlenecks instead of trusting peak TFLOPs. It exploits NPU stage/order/shape sensitivity, unified memory, and phase-specific partitioning so prefill gets more usable compute and decoding gets more usable memory bandwidth. On Snapdragon 8 Gen 3 and 8 Elite, the paper reports 1.34x-6.02x end-to-end speedups over prior mobile engines without relying on activation quantization or sparsity.

## Problem

On-device LLMs need low latency and local data handling, and modern phone SoCs already ship GPUs plus NPUs. Existing engines still mostly choose one backend: GPU-only stacks such as MLC/MNN or NPU-only stacks such as llm.npu and PowerInfer-2. That wastes hardware because prefill is compute-bound while decoding is memory-bound.

Naively running both processors in parallel also fails. The paper measures three obstacles on Snapdragon 8 Gen 3: NPU FLOAT performance changes sharply with tensor size, operand order, and aspect ratio; GPU-NPU synchronization costs about 400 microseconds, which is comparable to decoding kernel time; and one processor alone reaches only about 40-45 GB/s during decoding, below the platform's roughly 61.9 GB/s attainable bandwidth. So the hard problem is not just offloading work to the NPU, but coordinating two mismatched accelerators without losing the gain to shape pathologies and sync overhead.

## Key Insight

The paper's key insight is that GPU and NPU should cover each other's failure modes. In prefill, the NPU remains the main engine, while the GPU absorbs tensor shapes and operators the NPU handles poorly. In decoding, the goal is not more FLOPs but more simultaneous memory traffic: concurrent GPU+NPU execution can pull bandwidth close to the SoC ceiling. That requires hardware-driven partitioning plus microsecond-scale synchronization over unified memory.

## Design

HeteroInfer uses the CPU only as a control plane. At layer level, it places most matmuls on the NPU and operators such as RMSNorm and SwiGLU on the GPU, and it rewrites some matmuls as `([K, N] x [N, M])^T` to fit the NPU's weight-stationary datapath better.

The core mechanism is tensor-level parallelism. Weight-centric partitioning splits weight matrices by rows across GPU and NPU and merges partial outputs; this helps both prefill and decoding. Activation-centric partitioning handles dynamic prompt lengths by keeping standard-size chunks on the static-graph NPU and sending only the irregular remainder to the GPU, avoiding online graph generation or heavy padding. A hybrid partition combines padding with weight-centric splitting so neither device sits idle on awkward shapes.

An offline profiler measures per-operator latency, bandwidth, and sync cost across tensor shapes. A solver then chooses among GPU-only, NPU-only, weight-centric, activation-centric, and hybrid execution. To make these plans practical, HeteroInfer keeps a small shared buffer pool mapped into CPU, GPU, and NPU address spaces and replaces heavy fence-based synchronization with predicted sleeping followed by brief polling on a shared-memory completion flag.

## Evaluation

The implementation uses OpenCL GPU kernels, Qualcomm QNN on the NPU, and W4A16 so accuracy matches the original model better than activation-quantized baselines. The measurements support the design: GPU throughput grows roughly linearly with tensor size until saturation, the NPU shows pronounced stage/order/shape sensitivity, and concurrent GPU+NPU decoding raises bandwidth from about 43 GB/s with GPU alone to 59.5 GB/s, close to the measured 61.9 GB/s maximum.

End to end, the results are strong for the stated setting. Across multi-turn dialogue, GSM8K, and LongBench, HeteroInfer reports 1.34x-6.02x lower latency than prior mobile engines. Prefill exceeds 1000 tokens/s, including 1092 tokens/s on InternLM-1.8B, while decoding reaches 51.12 tokens/s. At dynamic sequence length 525, the heterogeneous partitioner beats online NPU graph generation by 2.24x and simple padding by 2.21x. Fast synchronization matters as well, adding 24.3% average prefill speedup for tensor-level execution and up to 4.01x decoding speedup. The paper also reports stable game FPS under concurrent execution, only 2.2% prefill slowdown, 17.7% decoding slowdown, and 55% lower end-to-end energy than GPU-only execution. The main caveat is that most experiments are batch-1 and Qualcomm-specific.

## Novelty & Impact

The contribution is not a new quantization scheme or kernel library. It is a systems recipe for mobile SoCs: characterize the hardware honestly, optimize prefill and decoding as different phases, and use a profiler-solver loop to map ordinary LLM operators onto GPU and NPU together. That should matter both to mobile runtime builders and to SoC designers thinking about cross-accelerator scheduling, shared memory, and synchronization support for future edge-AI chips.

## Limitations

HeteroInfer depends heavily on current mobile NPU properties: static graphs, systolic arrays, and strong tensor-shape pathologies. Porting it to a new SoC or model family still requires fresh profiling and solving. The workload model is also narrow: all experiments use batch size 1, and the paper does not report long-session thermal behavior or richer multi-session contention. Finally, some baselines trade accuracy or model structure for speed, so the comparisons are informative but not perfectly apples-to-apples. Decoding is already close to the DRAM ceiling, so further software-only gains may be limited.

## Related Work

- _Wang et al. (MMAsia Workshops '24)_ — MNN-LLM focuses on GPU-only mobile inference, while HeteroInfer argues that the missing speedup is cross-accelerator cooperation.
- _Xu et al. (arXiv '24)_ — llm.npu pushes the NPU aggressively, but HeteroInfer shows that NPU-only execution leaves both compute flexibility and DRAM bandwidth unused.
- _Xue et al. (arXiv '24)_ — PowerInfer-2 targets smartphones with NPU-heavy execution and model-specific changes, whereas HeteroInfer keeps the standard model and partitions ordinary operators across GPU and NPU.
- _Song et al. (HPCA '20)_ — AccPar studies tensor partitioning for heterogeneous accelerators, while HeteroInfer adapts that idea to unified-memory mobile SoCs with static NPU graphs and microsecond-scale synchronization.

## My Notes

<!-- empty; left for the human reader -->

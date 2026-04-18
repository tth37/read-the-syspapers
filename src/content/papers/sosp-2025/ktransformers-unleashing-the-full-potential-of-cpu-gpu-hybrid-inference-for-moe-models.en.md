---
title: "KTransformers: Unleashing the Full Potential of CPU/GPU Hybrid Inference for MoE Models"
oneline: "KTransformers combines AMX/AVX-512 MoE kernels, CUDA-graph orchestration, and expert deferral so one GPU plus CPUs can run huge MoE models much faster locally."
authors:
  - "Hongtao Chen"
  - "Weiyu Xie"
  - "Boxin Zhang"
  - "Jingqi Tang"
  - "Jiahao Wang"
  - "Jianwei Dong"
  - "Shaoyuan Chen"
  - "Ziwei Yuan"
  - "Chen Lin"
  - "Chengyu Qiu"
  - "Yuening Zhu"
  - "Qingliang Ou"
  - "Jiaqi Liao"
  - "Xianglin Chen"
  - "Zhiyuan Ai"
  - "Yongwei Wu"
  - "Mingxing Zhang"
affiliations:
  - "Tsinghua University"
  - "Approaching.AI"
  - "Hangzhou Dianzi University"
  - "University of Electronic Science and Technology of China"
  - "Beijing University of Posts and Telecommunications"
  - "Beijing Institute of Technology"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764843"
code_url: "https://github.com/kvcache-ai/ktransformers"
tags:
  - llm-inference
  - gpu
  - scheduling
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

KTransformers makes local hybrid MoE inference practical by co-designing CPU kernels, CPU/GPU scheduling, and one small model-level relaxation called Expert Deferral. Across DeepSeek-V3, DeepSeek-V2.5, and Qwen2-57B-A14B, it delivers 4.62x-19.74x faster prefill and 1.66x-4.90x faster decode than prior hybrid baselines.

## Problem

MoE models are appealing for local hybrid inference because attention and shared experts can stay on the GPU while routed experts live in DRAM and execute on CPUs. The paper argues that prior systems still underperform for two reasons. In prefill, long prompts activate many experts, so the CPU spends most of its time inside expert GEMMs, but existing AVX-512 or vendor AMX kernels are not tuned for MoE layout or cache reuse. In decode, the arithmetic per token is small enough that launch and synchronization overheads dominate: the runtime repeatedly crosses the host boundary, launches tiny GPU kernels, and pays extra cost for CPU-GPU and cross-NUMA coordination. On DeepSeek-V3, the authors report 70.02 tokens/s in prefill, 4.68 tokens/s in decode, and GPU utilization below 30%.

## Key Insight

The paper's core insight is that local MoE inference is limited by a pipeline, not a single operator. CPU expert kernels must be faster in prefill, the CPU/GPU boundary must stop fragmenting decode, and the model's own dependency chain must be loosened enough to expose overlap. KTransformers therefore combines three mutually reinforcing moves: AMX-oriented kernels and layouts for high-arithmetic-intensity expert work, AVX-512 for low-intensity decode work, CUDA-graph-friendly coordination that hides submit/sync points inside the graph, and Expert Deferral, which delays some routed experts by one layer because residual connections make that approximation tolerable.

## Design

KTransformers is implemented as a HuggingFace-compatible injection framework: a YAML file matches modules by name or class and swaps in optimized operators. For MoE blocks, the key replacement is a fused CPU operator backed by specialized AMX and AVX-512 kernels. Expert weights are rearranged into AMX-tile-friendly submatrices, aligned to cache lines, and scheduled around the CPU cache hierarchy; MoE sub-operators are fused where dependencies allow, and prefill uses dynamic task scheduling to smooth expert imbalance. The runtime uses AMX for high-arithmetic-intensity expert work, especially prefill, and switches to a compatible AVX-512 kernel in low-intensity decode regimes where lower overhead matters more.

For coordination, shared experts stay on the GPU while routed experts run on the CPU. A control thread pushes routed-expert work to background workers and launches GPU kernels for shared experts. Instead of synchronizing in the host at every submit/sync boundary, KTransformers wraps those boundaries in `cudaLaunchHostFunc`, which lets the whole decode path stay inside one CUDA Graph. On dual-socket machines it also uses NUMA-aware tensor parallelism: each expert's weights are sharded across sockets so most memory traffic stays local and only a lightweight reduction crosses sockets.

Expert Deferral is the paper's most distinctive mechanism. Standard MoE execution requires every routed expert in layer `k` to finish before layer `k+1` attention can proceed. KTransformers splits routed experts into immediate and deferred groups; deferred experts contribute at layer `k+2` instead. That breaks the strict dependency enough to overlap CPU expert work with the GPU's next-layer computation. On DeepSeek-V3, the paper finds that deferring three experts in the BF16 configuration saturates CPU utilization, cuts single-layer time by 26%, and raises end-to-end decode throughput by 33%.

## Evaluation

The evaluation is explicitly about local deployment. The hardware is a dual-socket Xeon 8452Y server with either an A100 40 GB or RTX 4080 16 GB, and the workloads use Wikitext at batch size 1. The paper evaluates DeepSeek-V3, DeepSeek-V2.5, and Qwen2-57B-A14B against Fiddler and Llama.cpp, with Llama.cpp extended so it can offload experts at comparable granularity.

The headline results are large and reasonably well supported. In prefill, KTransformers beats both baselines across prompt lengths, with 4.62x-19.74x speedups. In decode without Expert Deferral, it is already 2.42x-4.09x faster than Fiddler and 1.25x-1.76x faster than Llama.cpp on full-precision models; on quantized models the gain over Llama.cpp rises to 1.77x-1.93x. Expert Deferral adds up to 45% more decode throughput, producing total decode speedups of 1.66x-4.90x. The breakdown experiments also fit the story: AMX matters most in prefill, AVX-512 and CUDA Graph matter most in decode, and NUMA-aware tensor parallelism helps decode more than prefill. The quality cost of Expert Deferral is small but nonzero: on the main benchmark table the shifts stay within about two points, and on DS-3's LiveBench the default six-deferred-expert setting loses only 0.5% on average, much less than simply skipping those experts.

## Novelty & Impact

The novelty is architectural rather than model-level. Relative to Fiddler, KTransformers pushes much harder on CPU kernels, NUMA locality, and decode-time synchronization. Relative to algorithmic MoE acceleration work, it keeps the model mostly intact and changes the runtime instead. That makes the paper useful both to practitioners who want private local serving of very large MoE models and to systems researchers interested in how far controlled execution-order relaxation can go before quality breaks.

## Limitations

The paper is narrower than the headline speedups suggest. Almost all experiments target batch size 1 local serving, so it does not establish whether the same design remains best for higher-concurrency or cloud-style workloads. The CPU-side gains are also tied closely to Intel AMX and a large dual-socket NUMA machine, so portability to weaker CPUs or other ISAs is unclear. Expert Deferral itself is an approximation, not a free win: the reported accuracy loss is small, but the best defer count is model-dependent and the safety of this semantic change on long-tail tasks remains uncertain. The evaluation also stops at single-node hybrid serving, leaving distributed deployment and operational complexity largely unexamined.

## Related Work

- _Kamahori et al. (arXiv '24)_ - Fiddler establishes CPU/GPU orchestration for MoE inference, while KTransformers pushes much harder on CPU kernels, NUMA locality, and decode-time synchronization.
- _Kwon et al. (SOSP '23)_ - vLLM/PagedAttention makes GPU-resident LLM serving efficient, but KTransformers tackles the different regime where sparse MoE models spill into CPU memory and compute there.
- _Song et al. (SOSP '24)_ - PowerInfer accelerates dense-model local inference through selective offloading, whereas KTransformers exploits MoE sparsity and routed-expert execution on CPUs.
- _Hwang et al. (ISCA '24)_ - Pre-gated MoE reduces active experts algorithmically, while KTransformers keeps the original expert set and optimizes the heterogeneous runtime that executes it.

## My Notes

<!-- empty; left for the human reader -->

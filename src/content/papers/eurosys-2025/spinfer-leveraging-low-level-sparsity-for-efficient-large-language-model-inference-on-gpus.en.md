---
title: "SpInfer: Leveraging Low-Level Sparsity for Efficient Large Language Model Inference on GPUs"
oneline: "SpInfer makes 30%-70% unstructured LLM sparsity pay off on GPUs by replacing heavy indices with tensor-core-aligned bitmaps and decoding them cheaply inside shared memory."
authors:
  - "Ruibo Fan"
  - "Xiangrui Yu"
  - "Peijie Dong"
  - "Zeyu Li"
  - "Gu Gong"
  - "Qiang Wang"
  - "Wei Wang"
  - "Xiaowen Chu"
affiliations:
  - "The Hong Kong University of Science and Technology (Guangzhou), China"
  - "Harbin Institute of Technology, Shenzhen, China"
  - "The Hong Kong University of Science and Technology, Hong Kong SAR"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717481"
code_url: "https://github.com/HPMLL/SpInfer_EuroSys25.git"
tags:
  - llm-inference
  - gpu
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SpInfer argues that 30%-70% unstructured sparsity fails on GPUs mostly because indices destroy both compression and compute intensity. Its tensor-core-aligned bitmap format and shared-memory decoding let pruned LLM weights beat dense cuBLAS and cut OPT inference latency by up to 1.58x.

## Problem

On OPT-13B running on 2 RTX4090s, model weights occupy 87.6% of memory and GEMM takes 61.6% of execution time, so linear layers are the obvious target. But LLMs cannot usually be pruned to the 70%-90% sparsity that makes classic sparse kernels attractive; current unstructured methods typically stop around 50% before accuracy loss becomes unacceptable.

That is exactly where existing sparse formats break down. CSR and Flash-LLM's Tiled-CSL still spend enough bytes on location metadata that compression can fall below 1 under 50% sparsity, and the extra index traffic keeps GPU kernels memory-bound. Systems such as Flash-LLM and SparTA therefore often barely beat, or fail to beat, dense cuBLAS in the regime practitioners can actually deploy.

## Key Insight

SpInfer's key claim is that low-sparsity sparse inference should be organized around Tensor Core fragments, not individual nonzeros. If metadata is amortized over a fragment that already matches `mma` execution units, storage shrinks and compute intensity rises together.

The concrete move is to replace explicit coordinates with a 64-bit bitmap over an 8x8 tile. Then the kernel reconstructs Tensor Core fragments inside shared memory with popcount-style operations instead of dragging 16-bit or 32-bit indices through global memory, cache, and registers. That is why the bitmap helps both memory footprint and throughput.

## Design

SpInfer combines a tensor-core-aware storage format with a kernel built specifically for it. In TCA-BME, an 8x8 `BitmapTile` stores a 64-bit mask plus packed FP16 nonzeros; four of them form a 16x16 `TCTile` aligned with `mma.m16n8k16`; multiple `TCTile`s form a `GroupTile` processed by one thread block. The matrix is stored in `GTileOffset`, `Bitmap`, and `Values` arrays, and the column-major arrangement inside `TCTile`s is chosen so decoded values already match Tensor Core register layout.

The kernel preserves that layout end to end. Each iteration loads one sparse `GroupTile` and one dense `XTile`, decodes the sparse tile into registers, moves the dense tile into Tensor Core layout, and issues the multiply. `LDGSTS.128` lets both sparse weights and dense activations go directly from global memory to shared memory, avoiding the register round-trip that Flash-LLM still pays.

The most distinctive optimization is Shared Memory Bitmap Decoding (SMBD). A warp uses `__popcll` and masked popcount to compute offsets for packed nonzeros on the fly, then fills the two FP16 lanes of each register in two phases. A double-buffered asynchronous pipeline overlaps the next sparse and dense loads with current Tensor Core work, and separate `cp.async` groups let SMBD on CUDA cores overlap with Tensor Core instructions.

## Evaluation

Kernel benchmarks use weight shapes from OPT, Llama 2/3, Qwen2, and Mixtral on RTX4090 and A6000, against cuSPARSE, Sputnik, SparTA, Flash-LLM, dense cuBLAS, and SMaT. The results land exactly where the paper claims they should: on RTX4090, SpInfer averages 1.79x over cuBLAS and 1.56x over Flash-LLM; on A6000, 1.51x over cuBLAS. At 40% sparsity it is the only method that consistently beats cuBLAS, at 1.46x average speedup and 94.44% win rate. At 50% sparsity it reaches 1.66x and wins on 96.30% of tested matrices; at 70%, 1.90x and 100% win rate. It is also 2.12x faster than SMaT at 50% sparsity.

The end-to-end study uses Wanda-pruned OPT-13B/30B/66B at 60% sparsity against Flash-LLM, FasterTransformer, and DeepSpeed. Average speedups are 1.35x/1.42x/1.49x on RTX4090 and 1.29x/1.36x/1.55x on A6000. The best case is 1.58x over Flash-LLM on 1 GPU at batch size 32, 1817.02 versus 1183.58 tokens/s. Memory savings are just as important: OPT-13B at batch size 16 and sequence length 256 uses 14.4 GB instead of 27.4 GB, a 47.5% reduction, and SpInfer can run several configurations where Flash-LLM OOMs. End-to-end runs are still limited to OPT models and largely inherit accuracy guarantees from the pruning pipeline.

## Novelty & Impact

The novelty is a format-and-kernel co-design for the awkward 30%-70% sparsity band. Flash-LLM still pays too much per-value indexing cost, SparTA depends on mixing structured and residual sparsity, and extreme-sparsity kernels optimize a different regime. SpInfer shows that low-sparsity unstructured pruning can be a practical deployment technique rather than just a theoretical FLOP reduction, and one that composes with pruning, quantization, and serving-layer optimizations.

## Limitations

SpInfer is strongest in decode-like, memory-bound workloads. When batch size and sequence length are both large in prefill, the operation becomes more compute-bound and SpInfer can be up to 11.8% slower than dense cuBLAS. It also only supports static weight sparsity, not dynamic activation sparsity.

The evaluation is narrower than the kernel story suggests: end-to-end results cover OPT only, portability to non-NVIDIA hardware is argued rather than demonstrated, and bitmap indexing is the wrong choice once sparsity climbs above 90%, where CSR-like kernels can win again.

## Related Work

- _Xia et al. (VLDB '23)_ - Flash-LLM also targets sparse LLM inference on Tensor Cores, but SpInfer argues that Tiled-CSL and register-heavy unpacking still waste too much index bandwidth at 50%-ish sparsity.
- _Zheng et al. (OSDI '22)_ - SparTA mixes 2:4-structured sparsity with residual unstructured storage, whereas SpInfer stays fully unstructured and attacks the index-overhead problem directly with bitmaps.
- _Gale et al. (SC '20)_ - Sputnik is an important CUDA-core sparse kernel baseline, but SpInfer shifts the design target to Tensor Core fragment alignment and low-sparsity LLM shapes.
- _Fan et al. (ASPLOS '24)_ - DTC-SpMM shows how to use Tensor Cores for general sparse matrix multiplication, while SpInfer specializes that line of work to the decode-heavy, low-to-moderate sparsity regime of pruned LLM inference.

## My Notes

<!-- empty; left for the human reader -->

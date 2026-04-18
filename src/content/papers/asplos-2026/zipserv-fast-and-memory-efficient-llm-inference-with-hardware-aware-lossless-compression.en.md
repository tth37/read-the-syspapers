---
title: "ZipServ: Fast and Memory-Efficient LLM Inference with Hardware-Aware Lossless Compression"
oneline: "Compresses BF16 LLM weights into a Tensor-Core-aligned fixed-length format and fuses decompression with GEMM so lossless serving saves memory while speeding decode."
authors:
  - "Ruibo Fan"
  - "Xiangrui Yu"
  - "Xinglin Pan"
  - "Zeyu Li"
  - "Weile Luo"
  - "Qiang Wang"
  - "Wei Wang"
  - "Xiaowen Chu"
affiliations:
  - "The Hong Kong University of Science and Technology (Guangzhou), Guangzhou, China"
  - "Harbin Institute of Technology, Shenzhen, Shenzhen, China"
  - "The Hong Kong University of Science and Technology, Hong Kong, Hong Kong SAR"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790250"
code_url: "https://github.com/HPMLL/ZipServ_ASPLOS26.git"
tags:
  - llm-inference
  - gpu
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ZipServ argues that lossless compression helps LLM serving only if the compression format matches GPU execution. It replaces variable-length entropy coding with a fixed-length BF16 weight format, `TCA-TBE`, and uses a fused `ZipGEMM` kernel that reconstructs weights directly into Tensor Core registers during decode. The paper reports up to `30%` model-size reduction, up to `2.21x` kernel speedup over cuBLAS, and `1.22x` average end-to-end throughput over vLLM.

## Problem

The paper starts from a tension that has made lossless compression unattractive for inference. Operators want bit-exact weights because aggressive lossy compression can damage model behavior, especially on long-context or safety-sensitive workloads. But previous lossless systems mostly help storage, training checkpoints, or communication rather than online serving. Once they are inserted into an inference pipeline, the decompression cost often dominates the benefit of reading fewer bytes.

ZipServ says this is not because lossless compression is inherently too expensive, but because the usual codecs fight the GPU. Huffman- or ANS-style encodings produce variable-length bitstreams, which means each warp lane decodes a different number of bits and takes a different control path. That creates divergence, stalls, and poor memory behavior. The paper measures this mismatch directly: on L40S, DietGPU and DFloat11 reach only `43.7%` and `76.5%` of peak memory bandwidth, respectively. A second problem appears at the system level. Most pipelines fully decompress weights into global memory before launching GEMM, so the system pays for both compressed reads and decompressed writes. Their roofline analysis says this decoupled path cuts compute intensity by about `62%` versus standard GEMM for a representative `4096 x 4096` weight matrix. In other words, prior work saves capacity but gives back too much performance.

## Key Insight

The paper's key observation is that BF16 LLM weights are structured enough to support a GPU-friendly lossless format. Across several LLM families, the exponent field is highly skewed: the top-7 exponents cover over `95%` of weights, and in `99.6%` of matrices those top exponents form a numerically contiguous window. That means ZipServ does not need a general entropy coder. It can encode most weights as "base exponent plus a tiny offset," reserve one fallback state for outliers, and keep decoding regular across the warp.

That statistical fact matters only because the system spends it in the right place. ZipServ's proposition is that storage savings turn into serving speed only when decompression is fused into the decode-stage GEMM data path. If weights are fetched in compressed form and reconstructed only when a Tensor Core warp actually needs them, the system eliminates the intermediate buffer that sinks prior designs. The paper therefore treats compression format and kernel structure as one joint design problem rather than two separable steps.

## Design

ZipServ has an offline compressor and an online inference engine. Offline, it profiles each weight matrix's exponent histogram, chooses the best contiguous 7-exponent window, and stores `BaseExp = min(window) - 1`. It then partitions the matrix into `8 x 8` tiles and encodes each tile with `TCA-TBE` (Tensor-Core-Aware Triple Bitmap Encoding). Every element receives a 3-bit state: `001` to `111` represent one of the seven frequent exponents, while `000` means fallback full-precision BF16. For frequent elements, ZipServ stores only sign and mantissa in a compact buffer; outliers go to a full-value buffer.

The important layout choice is not just "3 bits," but how those bits are stored. Instead of packing them into a dense bitstream, ZipServ splits each tile into three separate 64-bit bitmaps, one per bit-plane. That makes accesses naturally aligned and lets all lanes execute the same branch-free decode logic. The tiling hierarchy is also matched to Tensor Core execution: `8 x 8` `FragTile`s compose `16 x 16` `TensorCoreTile`s, which then compose `64 x 64` block tiles. Because the compressed layout already mirrors the register layout expected by `mma.sync`, the kernel avoids runtime reshuffling.

The decode-stage kernel, `ZipGEMM`, fuses four steps into one pipeline: loading compressed weight tiles and activations into shared memory, warp-local decompression, register transfer of activations, and Tensor Core matrix multiply. The decompressor itself has three neat pieces. First, it ORs the three bitmaps to build a spatial indicator telling each lane whether its two assigned elements come from the high-frequency buffer or the fallback buffer. Second, it uses `popc`-style prefix counts to compute addresses on the fly, so it does not need explicit per-element indices. Third, it reconstructs the exponent arithmetically as `BaseExp + code`, avoiding lookup tables. The final BF16 values are packed directly into the `bf16x2` registers consumed by Tensor Cores.

ZipServ is deliberately stage-aware. During decode, where GEMM is memory-bound, `ZipGEMM` uses the "load-compressed, compute-decompressed" path. During prefill, where larger `N` makes GEMM compute-bound, the system falls back to a decoupled path: decompress first, then call cuBLAS. The paper reports that this prefill choice adds only about `4%` and `2%` of GEMM time at `N = 8192` and `16384`, respectively. The prototype is about `3.5K` lines of code and integrates into vLLM through a custom CUDA/C++ backend plus Python glue.

## Evaluation

The evaluation is strongest on the regime the paper cares about most: consumer-grade and inference-optimized GPUs serving BF16 models. Kernel experiments cover representative layers from LLaMA3.1, Qwen2.5, Gemma3, and Mistral on RTX4090 and L40S, with additional forward-compatibility tests on RTX5090. Against cuBLAS Tensor Core GEMM, `ZipGEMM` achieves `1.31x` average speedup on RTX4090 and `1.36x` on L40S, with peaks of `1.71x` and `2.21x`. The alternative lossless pipelines are nowhere close: DietGPU, nvCOMP, and DFloat11 all slow down relative to the plain cuBLAS baseline.

The micro-analysis explains why the fused design wins. On one RTX4090 case, ZipServ trades extra integer instructions for a `29.3%` drop in DRAM reads, while still keeping Tensor Core utilization at `71.6%` of the cuBLAS baseline. The standalone decompressor is also competitive on its own, beating DietGPU, nvCOMP, and DFloat11 by `2.14x`, `1.83x`, and `1.10x` on average for full transformer-block decompression. I found this useful because it shows the format itself is SIMT-friendly, not just the fused kernel around it.

End-to-end results are solid and are the most important evidence for the paper's claim. On LLaMA3.1-8B, Mistral-24B, and LLaMA3.1-70B, ZipServ cuts average latency by `17.60%` versus vLLM and raises average throughput by `1.22x`; at batch size `32` with `2048` output tokens on LLaMA3.1-8B, throughput reaches `1105` tokens/s, or `1.66x` over vLLM. Weight storage drops from `14.96/43.92/131.56 GB` to `10.83/31.30/93.52 GB`, which in turn expands the available KV cache. The breakdown on LLaMA3.1-8B is especially persuasive: linear-layer time falls from `24.99 ms` to `14.76 ms`, and KV-cache capacity rises from `5.07 GB` to `8.60 GB`.

## Novelty & Impact

Relative to _Yubeaton et al. (arXiv '25)_, ZipServ's main contribution is not "another lossless codec," but a codec whose fixed-length structure is explicitly chosen to suit GPU warps and Tensor Core tiling. Relative to _Dao et al. (NeurIPS '22)_, it applies the same broader systems idea as FlashAttention, namely fusing work to avoid unnecessary trips through memory, but in a very different part of the LLM stack: decompression plus GEMM rather than attention. Relative to _Kwon et al. (SOSP '23)_, which makes serving practical through PagedAttention and KV-cache management, ZipServ is a lower-level backend change that shrinks weight footprint and speeds the decode kernels those runtimes depend on.

That makes the paper likely to matter to two groups. Serving-system builders can view it as a new backend for bit-exact deployments on bandwidth-limited GPUs. Systems and architecture researchers can view it as evidence that lossless compression becomes interesting again when the codec, memory layout, and accelerator kernel are co-designed instead of optimized in isolation.

## Limitations

The gains are not universal. The paper is explicit that ZipServ is aimed at consumer-grade and inference-optimized GPUs; on training-oriented A100 and H800, the fused kernel may not always beat cuBLAS because memory bandwidth is less of a bottleneck and the ALU-heavy decompression work is harder to hide. The compression ratio is also modest by design, roughly `30%` rather than the multi-bit savings promised by lossy quantization.

There are also narrower technical limits. Some small layers do not tune well, and the paper reports only `0.79x` of cuBLAS on one `O_proj` case. Prefill is still handled by a separate decompression-plus-GEMM path, so the fully fused story applies mainly to decode. Finally, one baseline comparison is less satisfying than the others: because DFloat11's compression code was unavailable, the authors estimate some shapes by scaling from full-block measurements. That does not invalidate the overall trend, but it makes that particular head-to-head less airtight than the cuBLAS or vLLM comparisons.

## Related Work

- _Kwon et al. (SOSP '23)_ — PagedAttention/vLLM solves continuous serving and KV-cache memory management, while ZipServ targets the weight-representation and GEMM path underneath that runtime.
- _Dao et al. (NeurIPS '22)_ — FlashAttention reduces attention IO through fusion and on-chip tiling; ZipServ brings the same memory-traffic mindset to lossless weight decompression plus GEMM.
- _Frantar et al. (PPoPP '25)_ — MARLIN shows how hardware-aware kernels can hide low-bit inference overhead, but it is a lossy quantized design, whereas ZipServ keeps BF16 weights bit-exact.

## My Notes

<!-- empty; left for the human reader -->

---
title: "T-MAC: CPU Renaissance via Table Lookup for Low-Bit LLM Deployment on Edge"
oneline: "T-MAC rewrites W1-W4 LLM matmuls as bit-pattern table lookups, letting CPUs run low-bit models without dequantization and making edge inference faster and cheaper."
authors:
  - "Jianyu Wei"
  - "Shijie Cao"
  - "Ting Cao"
  - "Lingxiao Ma"
  - "Lei Wang"
  - "Yanyong Zhang"
  - "Mao Yang"
affiliations:
  - "USTC / Microsoft Research"
  - "Microsoft Research"
  - "UCAS / Microsoft Research"
  - "USTC"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696099"
code_url: "https://github.com/microsoft/T-MAC"
tags:
  - llm-inference
  - compilers
  - energy
  - hardware
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

T-MAC argues that low-bit edge LLMs are executed inefficiently today: current systems dequantize weights back into hardware-friendly types, so lower bit-width does not cleanly reduce latency. It decomposes W1-W4 weights into one-bit planes, precomputes tiny activation tables, and replaces mixed-precision GEMV/GEMM with table lookups plus additions. On real devices, that yields up to 6.6x kernel speedup over llama.cpp and up to 2.8x end-to-end throughput gain.

## Problem

Edge LLM inference wants low memory footprint and energy, so weight-only quantization is already essential. But once weights are 4-bit, 3-bit, 2-bit, or 1-bit while activations stay in `int8` or `fp16`, inference becomes a mixed-precision GEMV/GEMM problem that commodity CPUs and GPUs do not natively expose. Existing systems such as `llama.cpp` therefore decode or dequantize weights back into a supported type and then run a conventional kernel. The paper shows that this destroys the expected scaling: dropping from 4-bit to 3-bit or 2-bit often fails to speed up, and can even get slower because decode overhead dominates. The problem statement is simple: execute low-bit mixed-precision kernels directly, without dequantization, and still improve as weight precision drops.

## Key Insight

The central claim is that low-bit mixed-precision matmul should be expressed in bits. If an `n`-bit weight matrix is decomposed into `n` one-bit matrices, `A × W` becomes a weighted sum of `A × Wi` products. For a group of `g` one-bit weights there are only `2^g` patterns, so T-MAC precomputes the activation-side results for all of them once, stores them in a tiny table, and replaces multiply-accumulate with indexed lookup plus accumulation. This makes the kernel bit-width-agnostic and roughly linear in the number of weight bits. The systems insight is that CPUs can keep those tables on-chip and make lookup cheaper than dequantize-then-multiply.

## Design

T-MAC has an offline and an online path. Offline, it bit-serializes the quantized weight matrix into one-bit planes and packs each group of `g` bits into an index. Online, for each activation chunk, it builds a table containing the signed sums for all `2^g` patterns. The paper uses `g = 4`, small enough that the whole table fits in one NEON or AVX2 register. Each packed weight group then becomes a lookup index, and the partial sums from different bit-planes are recombined with bit-serial scaling and bias correction.

Most of the engineering is about keeping lookup tables cheap. T-MAC reorders loops to traverse `K` first and tiles to maximize reuse of one precomputed table across many output columns. It keeps tables in registers and uses `TBL` on ARM or `PSHUF` on x86 for the lookup. Weight permutation makes DRAM accesses sequential, weight interleaving removes unpacking reorder overhead, mirror consolidation stores only half the table because of sign symmetry, and table quantization shrinks the table to `int8`. The implementation is generated with TVM/LLVM but embedded into `llama.cpp` as C++ so it can reuse `llama.cpp`'s threadpool.

## Evaluation

The evaluation covers kernel shapes from Llama-2-7B and Llama-2-13B across four edge devices, then integrates T-MAC into `llama.cpp` for end-to-end tests on low-bit Llama and BitNet models. The baseline is strong: optimized `llama.cpp` kernels on each platform, plus BLAS for mpGEMM.

The evidence matches the thesis. `llama.cpp` stops benefiting when weight precision drops because decode overhead offsets arithmetic savings, while T-MAC improves almost linearly with the number of bits. For single-threaded mpGEMV, the maximum speedups over `llama.cpp` are 11.2x, 5.8x, 4.7x, and 3.1x for 1-, 2-, 3-, and 4-bit kernels, and the paper summarizes overall kernel gains up to 6.6x. End to end, T-MAC delivers up to 2.8x higher token-generation throughput for Llama-2-7B-2bit. BitNet-b1.58-3B reaches 30 tokens/s on one M2 Ultra core, 71 tokens/s on eight cores, and 11 tokens/s on Raspberry Pi 5. On M2 Ultra, energy drops by 20.6%-61.2% depending on the model. On some 2-bit models, CPU plus T-MAC is also competitive with same-device GPUs and NPUs because decode-phase inference is memory-bound and T-MAC removes the dequantization path. The main caveat is that the stack is still `llama.cpp`, so non-matmul code paths limit how much of the kernel win reaches the application.

## Novelty & Impact

T-MAC's novelty is not quantization itself but direct execution of already-quantized weights. Relative to GPTQ, AWQ, BitDistiller, or BitNet, it solves the missing systems problem: how to make W1-W4 weights actually run faster on commodity edge CPUs. Relative to earlier LUT-based inference work such as DeepGEMM, it specializes lookup execution to asymmetric LLM mixed precision and co-designs layout, compression, and register-level execution around CPU byte-shuffle instructions. That makes CPUs a much more credible edge LLM target and hints that low-bit LLM accelerators may need fast LUT access alongside fast multiply-accumulate units.

## Limitations

T-MAC is strongest in decode-style, memory-bound inference. The multithreaded gains are smaller than the single-threaded ones because memory bandwidth quickly becomes the bottleneck, and on M2 Ultra the AMX coprocessor narrows the mpGEMM advantage. The method also depends on ISA-specific properties: fast byte-shuffle instructions, enough registers to keep tables resident, and offline tuning of tiling, permutation, and interleaving. Lookup-table size still grows exponentially with group size, which is why the paper settles on `g = 4`. Finally, fast aggregation is not a free win: table quantization is essentially harmless, but fast aggregation measurably increases perplexity and lowers downstream accuracy.

## Related Work

- _Dettmers et al. (NeurIPS '22)_ - LLM.int8() makes transformer inference practical at 8-bit by isolating outlier channels, while T-MAC focuses on much lower weight bits and removes dequantization from the execution path.
- _Ganji et al. (CVPR '23)_ - DeepGEMM also replaces low-precision multiplies with LUTs, but for quantized CNN-style workloads; T-MAC adapts LUT execution to asymmetric `WnA16`/`WnA8` LLM kernels.
- _Du et al. (arXiv '24)_ - BitDistiller shows that 2-bit Llama models can preserve quality, and T-MAC provides the CPU kernel path that turns such models into practical edge deployments.

## My Notes

<!-- empty; left for the human reader -->

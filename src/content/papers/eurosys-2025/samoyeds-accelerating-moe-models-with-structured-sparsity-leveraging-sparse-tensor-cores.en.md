---
title: "Samoyeds: Accelerating MoE Models with Structured Sparsity Leveraging Sparse Tensor Cores"
oneline: "Samoyeds prunes MoE weights and routed activations together, maps both to a Sparse-Tensor-Core-friendly format, and speeds MoE inference while raising batch limits."
authors:
  - "Chenpeng Wu"
  - "Qiqi Gu"
  - "Heng Shi"
  - "Jianguo Yao"
  - "Haibing Guan"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Shanghai Enflame Technology Co. Ltd., Shanghai, China"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717455"
code_url: "https://github.com/guqiqi/Samoyeds.git"
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

Samoyeds treats MoE inference as a sparse-sparse problem: expert weights are pruned with structured sparsity, and routed activations are already sparse. Its custom format and Sparse-Tensor-Core kernel skip both kinds of redundancy, reaching up to 1.99x over VENOM at kernel level and up to 1.30x over vLLM-DS, while raising maximum batch size by 4.41x on average.

## Problem

Once attention is accelerated with FlashAttention-style techniques, the MoE layer becomes the dominant bottleneck; the paper reports it taking over 80% of transformer-block time in several models. Existing MoE systems such as MegaBlocks and vLLM-DS reduce padding or permutation costs, but still compute dense expert weights. Structured-sparsity kernels such as cuSPARSELt and VENOM exploit sparse weights on Sparse Tensor Cores (SpTCs), but assume dense activations.

That assumption is exactly wrong for MoE. Routing already makes activations sparse because each token is sent to only a few experts. But naively making both operands sparse either causes I/O amplification or destroys coalesced access. The paper therefore targets a format and execution scheme built specifically for MoE's dual-side sparsity.

## Key Insight

Samoyeds' central claim is that MoE routing-induced activation sparsity is structured enough to exploit in hardware if it is encoded explicitly. On the weight side, the system combines 2:4 element-wise sparsity with vector-wise sparsity, so it both matches `mma.sp` and supports sparse ratios beyond 50% without the inflexibility of pure 2:4 pruning. On the input side, it records exactly which routed token-expert pairs survive.

Because routing already defines the exact sparse activation pattern, the resulting sparse-sparse execution is mathematically identical to the original MoE computation. The gain comes from skipping redundant loads and multiplies, not from approximation.

## Design

The weight matrix is partitioned into `M x V` blocks. Each block keeps only `N` sub-rows, and the surviving sub-rows are further pruned into 2:4 groups. The encoded form contains compressed nonzero data, an indices array telling the kernel which sub-rows remain, and a 2-bit metadata array for SpTC. The input side uses a selection array (`SEL`) plus vector-wise sparse columns to describe which routed tokens actually participate in each expert computation.

The kernel pipelines `cp.async` fetches into shared memory with `mma.sp` computation from registers. The rest of the design is about making that fast enough to matter: three-level tiling across the memory hierarchy, a data-stationary scheme that keeps outputs in registers even when sub-row mappings shift during reduction, custom packing of data and 2-bit metadata so accesses stay coalesced and `ldmatrix`-friendly, and layout optimizations that pre-transpose weights offline, fuse input transposition into the global-to-shared path, and keep intermediate expert outputs compressed. Samoyeds also fuses activation and weighted accumulation with matrix multiplication to avoid extra memory round trips.

## Evaluation

Most measurements run on an RTX 4070 Super and compare against cuBLAS, Sputnik, cuSPARSELt, VENOM, Transformers, MegaBlocks, and vLLM-DS. On 238 synthetic kernel cases, Samoyeds reaches up to 1.99x over VENOM, 5.44x over cuBLAS, 3.18x over cuSPARSELt, and 18.76x over Sputnik. On realistic shapes extracted from Qwen2-MoE, DeepSeek-MoE, MiniCPM-MoE, OpenMoE-34B, and Mixtral models, it averages 2.33x over VENOM and 3.95x over cuBLAS.

At MoE-layer level, Samoyeds averages 1.46x over Transformers with shared experts and 1.45x without; versus MegaBlocks and vLLM-DS, the best gains reach 1.66x and 1.53x. Using a single decoder layer as an end-to-end proxy, the paper reports up to 2.36x over Transformers and up to 1.31x / 1.30x over MegaBlocks / vLLM-DS. Maximum supported batch size increases by 4.41x on average over Transformers, with OpenMoE-34B moving from 3 to 56.

At 75% sparsity, BERT retains over 99.3% of its dense SQuAD 1.1 accuracy on average, while Tiny-LLaMA-1B and Qwen2-1.5B see only 0.06 and 0.05 perplexity increases on GSM8K. The main weakness is shape sensitivity: models with many small experts or heavily skewed dimensions, such as Mixtral-8x22B, leave less parallelism and more padding overhead, so gains narrow.

## Novelty & Impact

The paper's novelty is joining three threads that were previously separate: structured sparse SpTC kernels, MoE-specific execution optimization, and activation-sparsity exploitation. VENOM is sparse-dense, MegaBlocks is MoE-aware but dense on weights, and PIT exploits activation sparsity without SpTC. Samoyeds combines them into one MoE-specific format and execution scheme, showing that routing sparsity can be promoted from an algorithmic side effect to a systems primitive.

## Limitations

The end-to-end evaluation is still a proxy measurement: one decoder layer rather than a full serving stack, so framework overhead, scheduling, and memory fragmentation are not fully exercised. Most performance results also come from one NVIDIA family. The paper studies direct porting across several NVIDIA GPUs and shows Samoyeds degrades less than VENOM, but AMD support is argued more than demonstrated. The accuracy study is indirect as well, because it evaluates smaller dense or non-MoE models rather than the large MoE models used for the speed tests.

## Related Work

- _Castro et al. (SC '23)_ - VENOM also targets Sparse Tensor Cores with a flexible structured format, but it assumes sparse weights and dense inputs rather than MoE's dual-side sparsity.
- _Gale et al. (PMLSys '23)_ - MegaBlocks accelerates MoE execution with block-sparse kernels and less padding, while Samoyeds additionally prunes expert weights and maps them onto SpTC hardware.
- _Zheng et al. (SOSP '23)_ - PIT exploits dynamic activation sparsity through compiler transformations, whereas Samoyeds couples activation sparsity with structured weight sparsity and a hand-tuned sparse kernel.
- _Chen et al. (PPoPP '23)_ - DFSS shows how dynamic N:M structured sparsity can match hardware constraints in attention workloads, and Samoyeds adapts that hardware-aware mindset to MoE linear layers.

## My Notes

<!-- empty; left for the human reader -->

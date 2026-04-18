---
title: "Cheddar: A Swift Fully Homomorphic Encryption Library Designed for GPU Architectures"
oneline: "Redesigns CKKS around a 25-30-prime 32-bit RNS and aggressive kernel fusion so GPUs run FHE much faster without exploding key size or memory traffic."
authors:
  - "Wonseok Choi"
  - "Jongmin Kim"
  - "Jung Ho Ahn"
affiliations:
  - "Seoul National University, Seoul, Republic of Korea"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3760250.3762223"
tags:
  - security
  - gpu
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Cheddar is a GPU-oriented CKKS library that rebuilds the residue-number-system stack around 32-bit primes instead of inheriting CPU-style 64-bit assumptions. Its main move is to combine a new 25-30-prime RNS design with low-level modular arithmetic and aggressive kernel fusion, which cuts both compute overhead and memory traffic enough to beat prior GPU FHE systems by `2.18-4.45x` on representative workloads.

## Problem

The paper starts from the basic promise of fully homomorphic encryption: cloud servers should be able to compute on ciphertexts without ever seeing plaintext. In practice, that promise is still expensive. CKKS workloads are dominated by very large modular polynomial operations, repeated rescaling, basis conversion, automorphisms, and bootstrapping. Even after years of acceleration work, encrypted inference and training remain orders of magnitude slower than unencrypted execution.

GPUs look like the natural target because CKKS exposes large amounts of limb-level and coefficient-level parallelism. But the authors argue that earlier GPU libraries still leave performance on the table for two separate reasons. First, mainstream FHE software is built around 64-bit RNS primes, while NVIDIA GPUs execute integer arithmetic through 32-bit datapaths; emulating 64-bit integer work makes the compute cost grow badly. Second, simply switching to 32-bit RNS is not enough: prior 32-bit constructions either require many level-specific evaluation keys, which bloats memory capacity, or rely on layouts that introduce awkward control flow and poor GPU utilization.

There is also a bandwidth problem. Once BConv and NTT get faster, the remaining automorphism and element-wise kernels are mostly constrained by DRAM traffic, and conventional FHE operation sequences bounce data between kernels while repeatedly converting to and from Montgomery form. The paper therefore targets a broader systems question than "how do we speed up one kernel": how should an end-to-end CKKS library be reorganized so that both the arithmetic format and the execution schedule match GPU hardware?

## Key Insight

The central claim is that GPU-friendly FHE requires co-design across number representation, memory layout, and operation sequencing. A 32-bit RNS scheme only helps if it preserves evaluation-key compatibility across levels, keeps data contiguous in memory, and does not force expensive special cases into kernels. Likewise, faster modular arithmetic only matters if the library removes the memory traffic that would otherwise replace compute as the bottleneck.

Cheddar's answer is to treat 32-bit execution as a whole-stack design problem. The 25-30 prime system uses a fixed cycle of primes near `2^25` and `2^30` so rational rescaling keeps the CKKS scale near `2^40` while still allowing a single top-level evaluation-key layout. An inverted-terminal layout then orders limbs so level changes still map to contiguous storage. On top of that representation, the library uses signed Montgomery reduction, architecture-tuned BConv/NTT kernels, and fusion rules that precompute away Montgomery conversions and collapse multi-kernel sequences into fewer passes over memory. The lasting lesson is that the win comes from making the representation schedulable on a GPU, not merely from swapping 64-bit math for 32-bit math.

## Design

The first design piece is the new RNS construction. For non-bootstrapping levels, Cheddar uses a rational-rescaling cycle that discards three `Pr~30` primes and adds two `Pr~25` primes, repeats that once, then discards four `Pr~25` primes and adds two `Pr~30` primes. This keeps the scale around `2^40` while using only a small fixed set of terminal primes. Because the primes come from fixed ordered lists rather than being greedily chosen per level, a single evaluation key prepared at the top level remains compatible after truncation. For bootstrapping levels, where larger scales around `2^55-2^58` are acceptable, the library switches to double-rescaling-style choices so the final top-level modulus still includes all primes and does not waste modulus budget.

The second piece is data layout. Rational rescaling normally makes the same logical prime appear at different physical positions across levels, which complicates indexing and memory allocation. Cheddar's inverted-terminal layout stores the terminal `Pr~25` limbs first in reverse order and the `Pr~30` limbs after them. Because prime introduction and removal follow the fixed cycle above, every level can still occupy contiguous aligned memory, which simplifies cross-level operations like rescaling and ModDown.

The third piece is kernel engineering. Cheddar implements signed Montgomery reduction because it uses fewer instructions than Barrett or classic Montgomery reduction on recent GPUs while needing only one precomputed constant per prime. BConv matrix multiplication uses lazy reduction aggressively enough to cut many modular reductions without overflowing signed 64-bit accumulators. For NTT, the library extends prior on-the-fly twiddle-factor generation so an entire phase can regenerate twiddles instead of loading most of them from memory. The kernels are parameterized and then architecture-specifically tuned for each GPU.

The fourth piece is operational-sequence optimization. Sequential fusion folds constant multiplications into adjacent INTT and BConv kernels, eliminating the explicit cost of entering or leaving Montgomery form and simplifying rescaling and ModDown. The paper also splits and reorders some steps to expose more fusion opportunities. Parallel fusion then merges repeated accumulations and automorphisms, including the linear-transform patterns common in bootstrapping and encrypted neural-network layers, so shared inputs are loaded once instead of many times.

Implementation-wise, Cheddar is not just a benchmark prototype. The paper presents it as a full library with high-level interfaces, bootstrapping and DNN modules, a GPU memory-pool allocator, and an architecture-specific fine-tuner. The main codebase is described as more than `11,000` lines of C++/CUDA.

## Evaluation

The default setup uses `128-bit` secure parameters with `N = 2^16`, `PQ < 2^1776`, default `Delta = 2^40`, and `dnum = 4`. The workloads are full-slot bootstrapping, homomorphic logistic-regression training (HELR), ResNet-20 inference on CIFAR-10, and a sorting network. This is a good mix because it exercises both the cryptographic core and end-to-end application pipelines rather than only microkernels.

The headline comparison is against prior GPU systems. On the same `A100 80GB`, Cheddar reduces bootstrapping latency from WarpDrive's `121.0 ms` to `40.0 ms` (`3.03x`), HELR iteration time from `113.0 ms` to `51.9 ms` (`2.18x`), and ResNet inference time from `5.88 s` to `1.32 s` (`4.45x`). The paper also reports broader speedups of `2.18-19.6x` over representative GPU implementations and shows that Cheddar can outperform recent FPGA designs while running on commodity GPUs. On an `RTX 5090`, the reported times drop further to `22.1 ms` for bootstrapping, `25.9 ms/it` for HELR, and `0.72 s` for encrypted ResNet inference.

The evaluation does a nice job of tying the macro results back to the mechanism choices. Rational rescaling with the 25-30 prime system increases effective level by up to five compared with a hand-tuned double-rescaling configuration, which cuts bootstrapping frequency and yields another `1.07-1.41x` workload speedup. The basic-mechanism study against open-source libraries shows that even when the prime-system advantage is factored out, Cheddar is still about `1.5-1.8x` faster on HMult, HRot, and rescaling. The ablation study is also informative: kernel-level BConv/NTT optimizations alone improve workload time only `5-7%`, while sequential fusion adds `18-22%` and parallel fusion adds `12-23%`. That supports the paper's main point that memory movement, not just arithmetic throughput, is the limiting factor in a mature GPU FHE stack.

The evaluation is convincing for single-node GPU acceleration, though narrower for other deployment models. Some workloads hit out-of-memory limits on smaller GPUs, and the paper does not try to solve multi-GPU distribution or CPU/GPU heterogeneity. That is not a flaw in scope, but it does bound how far the conclusions travel.

## Novelty & Impact

Relative to _Samardzic and Sanchez (ASPLOS '24)_, Cheddar's novelty is not merely using rational rescaling, but turning it into a fixed 25-30-prime schedule that preserves evaluation-key compatibility and fits GPU execution. Relative to _Jung et al. (TCHES '21)_, the contribution is broader than a faster bootstrapping pipeline: the paper extends fusion and dataflow optimization across an entire CKKS library. Relative to _Fan et al. (HPCA '25)_, which also pushes GPU FHE hard, Cheddar's distinguishing move is the combined representation-plus-execution redesign rather than only faster math kernels.

That makes the paper useful to two communities. Systems researchers can cite it as evidence that FHE performance now depends on whole-library dataflow design rather than isolated cryptographic kernels. Practitioners building private ML or encrypted analytics stacks can read it as a concrete recipe for when a single modern GPU is enough to make CKKS workloads usable.

## Limitations

Cheddar is still a specialized implementation. The evaluation targets CKKS, not FHE schemes in general, and the software requirements remain NVIDIA-centric even though the paper compares against an AMD-based accelerator. The library also needs substantial GPU memory; some workloads fail on `16-24 GB` devices because evaluation keys and temporary polynomials are large.

Its best results depend on careful parameter selection and architecture-specific tuning. Lower scales such as `Delta = 2^35` improve speed further, but the paper shows that pushing to `Delta = 2^30` breaks HELR and ResNet quality, so the performance gains are not free. More broadly, the paper focuses on single-query and single-node execution. It does not study how these kernels interact with multi-tenant scheduling, distributed bootstrapping, or networked services that may dominate in practical cloud deployments.

## Related Work

- _Samardzic and Sanchez (ASPLOS '24)_ — BitPacker shows how rational rescaling can enable high arithmetic efficiency, while Cheddar redesigns that idea to avoid evaluation-key blowup and GPU-unfriendly control flow.
- _Jung et al. (TCHES '21)_ — 100x Faster Bootstrapping identifies memory-centric bottlenecks and uses early fusion, and Cheddar generalizes that style of optimization across more CKKS mechanisms and library layers.
- _Fan et al. (HPCA '25)_ — WarpDrive also accelerates GPU FHE aggressively, but Cheddar reports better end-to-end workload times by co-designing the RNS construction, data layout, and fusion strategy.
- _Kim et al. (ISCA '23)_ — SHARP is a custom accelerator for practical FHE, whereas Cheddar argues that commodity GPUs can recover much of that performance through software and representation choices alone.

## My Notes

<!-- empty; left for the human reader -->

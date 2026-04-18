---
title: "A Framework for Developing and Optimizing Fully Homomorphic Encryption Programs on GPUs"
oneline: "Builds a PyTorch-like GPU FHE framework that lowers homomorphic primitives through staged passes to cut key memory, runtime allocation overhead, and redundant polynomial work."
authors:
  - "Jianyu Zhao"
  - "Xueyu Wu"
  - "Guang Fan"
  - "Mingzhe Zhang"
  - "Shoumeng Yan"
  - "Lei Ju"
  - "Zhuoran Ji"
affiliations:
  - "Shandong University, Qingdao, China"
  - "The University of Hong Kong, Hong Kong, China"
  - "Ant Group, Hangzhou, China"
  - "State Key Laboratory of Cryptography and Digital Economy Security, Jinan, China"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790120"
code_url: "https://github.com/jizhuoran/EasyFHE"
tags:
  - security
  - gpu
  - compilers
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

EasyFHE is a GPU runtime framework for fully homomorphic encryption that sits after frontend compilation and before GPU kernels. Its layered lowering pipeline applies FHE-specific passes for memory reduction, allocation reuse, and redundancy elimination, delivering up to `4.39x` speedup over open-source GPU baselines.

## Problem

The paper starts from a mismatch between primitive-level acceleration and application-level usability. Prior GPU FHE work has made CKKS operations such as homomorphic multiplication much faster, but building a whole encrypted program still forces developers to manage ciphertext state, evaluation keys, and GPU memory details by hand. That is a poor fit for users who want to program at the level of homomorphic primitives.

Performance also remains weak for reasons that single-kernel papers do not solve. Rotation keys and encoded constants often dominate memory, short-lived intermediates make allocation overhead visible, and the lowered polynomial arithmetic still contains repeated modulus changes, rotation setup, and constant encoding. EasyFHE is motivated by the idea that end-to-end GPU FHE needs a runtime backend, not only faster kernels.

## Key Insight

The central claim is that backend structure matters as much as primitive throughput. Because FHE programs avoid data-dependent control flow, EasyFHE can rewrite them into a plain SSA-style primitive sequence and optimize across primitive boundaries instead of treating each call independently.

That representation is what unlocks the wins. EasyFHE can reason about memory at the level of polynomial sets, choose rotation keys under an explicit memory budget, and merge auxiliary operations such as modulus-up and rescaling when the algebra allows it. The lasting insight is that efficient GPU FHE needs a compiler-like runtime backend, not just faster cryptographic kernels.

## Design

EasyFHE has four layers: homomorphic primitives, primitive-specific implementations, polynomial arithmetic, and reusable GPU kernels such as NTT and automorphism. This keeps the programming interface stable while allowing new FHE techniques to be integrated in the middle layers.

Its memory model is central. EasyFHE uses polynomial sets as the management unit, which avoids both heavy fragmentation and gross over-allocation. The framework also tracks metadata such as scale, noise degree, slot count, and active polynomial count, and offers a plaintext-twin mode for debugging.

The optimization framework has three main pass families. Memory-usage passes select rotation offsets under a memory budget and use hybrid constant encoding so some vectors stay on device while others are fetched or generated on demand. Memory-management passes preallocate storage for live intermediates, reuse symbolic destinations, and prefetch host data to overlap transfer with computation. Redundancy-elimination passes exploit FHE structure: additive chains can share one key-switch/rescale sequence, multi-offset rotations can hoist shared modulus-up work, and encoded constants can be cached after first use.

## Evaluation

The experiments span `RTX4090`, `RTX A6000`, and `H100 PCIe`, and use both basic and application-scale workloads: dot product, bootstrapping, sorting, encrypted logistic-regression training, and encrypted ResNet-20 and ResNet-110 inference.

Against Troy and HEonGPU, EasyFHE reports `2.88x` average end-to-end speedup and up to `4.39x`. The gains are larger on complex workloads, which fits the paper's claim that application-level FHE exposes cross-layer optimization opportunities that primitive benchmarks miss. The memory experiments are also persuasive: ResNet workloads exceed the capacity of smaller GPUs under the baselines, but EasyFHE still runs them, and under an H100 memory cap it is `2.18x` faster than an "optimal replacement" strategy at `10 GB`.

The ablations line up with the mechanism. Memory-management optimization contributes `1.48x` average speedup, redundancy elimination contributes `1.44x`, and both help more on lower-end GPUs. Importantly, the implementation reuses kernels from over100x and follows OpenFHE-style algorithms, so the gains mostly come from framework organization rather than from unusually strong primitive kernels.

## Novelty & Impact

Relative to _Ebel et al. (ASPLOS '25)_, which compiles ML programs into FHE code, EasyFHE covers the next stage: efficient GPU execution of the resulting primitive sequence. Relative to _Jung et al. (TCHES '21)_, its contribution is broader than memory-centric bootstrapping kernels because it targets whole-program runtime support. Relative to _Fan et al. (HPCA '25)_, the distinctive move is to treat FHE execution as a layered backend problem rather than only a kernel-throughput problem.

That makes the paper useful to both practitioners and systems researchers. It lowers the barrier to writing complete GPU FHE applications, and it argues convincingly that end-to-end FHE performance is now constrained by memory and lowering decisions as much as by arithmetic speed.

## Limitations

The framework is evaluated only on CKKS-style workloads, even though the authors argue the structure should generalize to RLWE-based schemes more broadly. Its kernel layer is also intentionally conservative: EasyFHE uses 64-bit arithmetic, omits on-the-fly rotation-key generation, and does not incorporate the most aggressive fusion or rescaling techniques from the fastest recent libraries. That preserves compatibility with OpenFHE-like algorithms but leaves performance on the table.

Its memory optimizations also trade space for time. Coarse-grained polynomial-set allocation reduces churn but wastes some memory by design. And the scope stays within a single-node GPU setting, so the paper does not answer multi-GPU, distributed key-management, or service-deployment questions.

## Related Work

- _Ebel et al. (ASPLOS '25)_ — Orion is a frontend compiler that turns ML programs into FHE primitives, while EasyFHE starts from those primitives and optimizes the GPU backend.
- _Jung et al. (TCHES '21)_ — over100x accelerates bootstrapping kernels on GPUs, whereas EasyFHE generalizes memory- and redundancy-aware optimization to full FHE applications.
- _Fan et al. (HPCA '25)_ — WarpDrive pushes GPU FHE kernels harder, but EasyFHE argues that application-level wins require automatic memory management and cross-operation optimization as well.

## My Notes

<!-- empty; left for the human reader -->

---
title: "CLM: Removing the GPU Memory Barrier for 3D Gaussian Splatting"
oneline: "CLM keeps only frustum-critical Gaussian attributes on the GPU, offloads the rest to CPU memory, and pipelines transfer, caching, and Adam updates on one consumer GPU."
authors:
  - "Hexu Zhao"
  - "Xiwen Min"
  - "Xiaoteng Liu"
  - "Moonjun Gong"
  - "Yiming Li"
  - "Ang Li"
  - "Saining Xie"
  - "Jinyang Li"
  - "Aurojit Panda"
affiliations:
  - "New York University, New York, NY, USA"
  - "Pacific Northwest National Laboratory, Richland, WA, USA"
  - "University of Washington, Seattle, WA, USA"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790140"
code_url: "https://github.com/nyu-systems/CLM-GS"
tags:
  - gpu
  - memory
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CLM makes large-scene 3D Gaussian Splatting trainable on one consumer GPU by keeping only frustum-selection attributes resident and hiding the rest of the offload cost with pipelining, caching, and view reordering.

## Problem

The main bottleneck in 3DGS is memory, not arithmetic. Each Gaussian has 59 trainable parameters, and training stores parameters, gradients, and Adam state, so the model state alone costs `N x 59 x 4 x 4` bytes. The authors estimate that a 24 GB RTX 4090 can hold only about 26 million Gaussians before activations and temporary buffers.

That is far below realistic large scenes: their examples range from Rubble at 40 million Gaussians and roughly 50 GB to MatrixCity BigCity at 100 million and 110 GB. Existing fixes all compromise something important: multi-GPU training raises cost, pruning can hurt fidelity, and partitioning can create boundary artifacts. Naive CPU offload is also insufficient because loading all Gaussians every step still needs too much GPU memory and adds transfer and CPU Adam overhead that is hard to hide.

## Key Insight

CLM's central insight is that 3DGS training is sparse enough that the GPU never needs the whole scene at once. Each view touches only the Gaussians inside its frustum, and for large scenes that working set is tiny relative to the full model. On MatrixCity BigCity, the average view accesses only `0.39%` of Gaussians and the maximum is `1.06%`.

The sparsity also has structure. Nearby views reuse many of the same Gaussians, and the final microbatch that touches a Gaussian in the current batch can often be known in advance. CLM uses those facts to cache reused Gaussians across adjacent microbatches and to run CPU-side Adam as soon as a Gaussian's gradients are final.

## Design

CLM splits Gaussian attributes into two classes. Selection-critical attributes, namely position, scale, and rotation, are needed for frustum culling and account for 10 of the 59 floats in each Gaussian, so CLM keeps them resident on the GPU for all Gaussians. Non-critical attributes, including color coefficients and opacity, stay in CPU pinned memory and are loaded only for in-frustum Gaussians. This lets frustum culling run without materializing the full model on the GPU.

Training is reorganized into one-image microbatches. CLM performs pre-rendering frustum culling, explicitly stores each in-frustum set `S_i`, and feeds only those Gaussians to rasterization through a selective-loading kernel; a matching kernel stores gradients back to CPU memory. Three optimizations make the pipeline effective: precise Gaussian caching reuses `S_i ∩ S_{i+1}` directly on the GPU, overlapped CPU Adam updates any Gaussian as soon as its last microbatch in the current batch finishes, and pipeline order optimization reorders views to maximize overlap between successive working sets using a TSP-style objective over symmetric-difference distance. Communication and compute run on separate CUDA streams with double buffering.

## Evaluation

The evaluation matches the claim well. The authors test five scenes on an `RTX 4090` over PCIe 4.0 and an `RTX 2080 Ti` over PCIe 3.0. The baseline setup is careful: the GPU-only baseline is single-GPU Grendel with gsplat kernels, the enhanced baseline additionally adopts CLM's pre-rendering frustum culling, and the naive-offload baseline shares pinned memory, CPU Adam, and gradient accumulation so the comparison isolates CLM's offloading strategy.

The headline result is scale. On the RTX 4090, the enhanced GPU-only baseline tops out at about `18.4M` Gaussians on BigCity, naive offloading reaches `46.0M`, and CLM reaches `102.2M`; on the RTX 2080 Ti, CLM reaches `47.0M` versus `7.7M` for the enhanced baseline. That extra capacity improves quality directly: on BigCity, PSNR rises from `23.93` at the GPU-only limit of `15.3M` Gaussians to `25.15` at `102.2M`. CLM is also `1.38x-1.92x` faster than naive offloading while retaining `86%-97%` of the enhanced baseline throughput on the 2080 Ti and `55%-90%` on the 4090. The ablations are consistent with the design story: CLM reduces communication volume by `37%-82%`, and TSP-based ordering gives the lowest transfer volume among the tested schedules.

## Novelty & Impact

Relative to _Zhao et al. (ICLR '25)_, which scales 3DGS training across multiple GPUs, CLM offers a single-GPU design that converts CPU memory into model capacity without changing the representation. Relative to pruning or hierarchical approaches such as _Kerbl et al. (TOG '24)_, CLM does not shrink the scene to fit memory; it preserves fidelity and instead changes placement, overlap, and ordering. Relative to partitioning systems such as _Lin et al. (CVPR '24)_, it avoids cross-partition stitching artifacts by keeping one global scene representation.

The impact is straightforward: practitioners get a path to train much larger 3DGS scenes on commodity hardware, and systems researchers get a clean example of workload-specific offloading built around frustum sparsity and spatial locality.

## Limitations

CLM is not a free-memory abstraction. It still keeps selection-critical attributes of all Gaussians on the GPU, so the system remains bounded by GPU memory, just with a much smaller resident set. It also depends on substantial host memory and pinned-memory allocation; even BigCity uses tens of GB of pinned RAM. The current implementation is CUDA-based, and the ordering step is only demonstrated at the tested batch sizes. Finally, the evaluation centers on training throughput and reconstruction quality rather than end-to-end interactive inference latency; that last point is an inference from the experiments rather than an author-stated limitation.

## Related Work

- _Kerbl et al. (TOG '23)_ — introduced 3D Gaussian Splatting and its densification-based training loop; CLM keeps that learning pipeline but changes where Gaussian state resides.
- _Zhao et al. (ICLR '25)_ — Grendel scales 3DGS with multiple GPUs, whereas CLM targets the same memory wall by offloading onto CPU memory on a single GPU.
- _Lin et al. (CVPR '24)_ — VastGaussian partitions large scenes into subregions, while CLM keeps one global scene and avoids partition-boundary inconsistency.
- _Kerbl et al. (TOG '24)_ — hierarchical 3D Gaussians reduce memory by changing the representation itself; CLM instead preserves the representation and optimizes placement and transfer.

## My Notes

<!-- empty; left for the human reader -->

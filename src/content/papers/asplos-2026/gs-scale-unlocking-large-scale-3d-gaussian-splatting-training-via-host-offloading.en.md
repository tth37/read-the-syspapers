---
title: "GS-Scale: Unlocking Large-Scale 3D Gaussian Splatting Training via Host Offloading"
oneline: "Offloads most 3DGS state to host memory, keeps geometry resident for culling, and pipelines forwarded updates so commodity GPUs can train much larger scenes."
authors:
  - "Donghyun Lee"
  - "Dawoon Jeong"
  - "Jae W. Lee"
  - "Hongil Yoon"
affiliations:
  - "Seoul National University, Seoul, Republic of Korea"
  - "Google, Mountain View, CA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790167"
code_url: "https://github.com/SNU-ARC/GS-Scale.git"
tags:
  - gpu
  - memory
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

GS-Scale asks whether large-scene 3D Gaussian Splatting training can fit on commodity GPUs by treating GPU memory as a cache rather than the system of record. Its answer is to keep all Gaussian parameters and Adam states in host memory, fetch only the visible subset each iteration, and then recover the lost performance with GPU-resident geometry, pipelined parameter forwarding, and deferred optimizer updates. The result is 3.3-5.6x lower peak GPU memory with throughput close to GPU-only training.

## Problem

The paper starts from a blunt scaling failure in 3DGS training: better scene quality usually means more Gaussians, but explicit Gaussian representations are memory-hungry even before training state is counted. Each Gaussian carries 59 trainable parameters, and training multiplies that footprint because gradients, optimizer state, and activations also have to be stored. The authors measure that Gaussian-related state accounts for about 90% of GPU memory, while activations are only around 10% at common 1K-4K image resolutions. On large scenes such as Rubble, reaching the highest visual quality needs roughly 40 million Gaussians and about 53 GB of GPU memory, which is far beyond a single consumer GPU.

The obvious response is multi-GPU training, and the paper explicitly cites recent distributed 3DGS work in that direction. But the authors argue that this is the wrong default for hobbyists, creators, and small professional users who want to reconstruct large scenes from their own images on a laptop or desktop. Host offloading looks attractive because only Gaussians inside the current viewing frustum participate in rendering and backpropagation. Their profiling shows that only 8.28% of total Gaussians are active on average across large scenes. The catch is that the two remaining whole-model operations, frustum culling and Adam updates, become CPU bottlenecks if everything lives in host memory.

## Key Insight

The central claim is that host offloading can work for 3DGS only if the system preserves the sparsity benefit while avoiding CPU execution on the full model in the critical path. The paper’s insight is therefore not merely “offload inactive Gaussians,” but “split the training state by access pattern.” Geometry is special because every iteration needs it for culling; many non-geometric parameters are special in the opposite way because they often receive zero gradient and can be updated lazily without changing the final optimization result.

That perspective lets GS-Scale turn a naive CPU-assisted design into a pipelined CPU-GPU training system. GPU memory is reserved for the pieces that must stay hot: geometric attributes for all Gaussians and the currently visible subset of the rest. CPU memory holds the cold majority. Once the paper frames 3DGS training as a sparse, iteration-by-iteration working set problem, the rest of the design follows naturally.

## Design

The baseline design is straightforward: all parameters and optimizer state live in host memory; CPU frustum culling finds visible Gaussian IDs; those parameters are copied over PCIe; GPU runs forward and backward; gradients return to CPU; and CPU runs Adam. That saves memory, but the paper shows it is about 4x slower than GPU-only training on an RTX 4070 Mobile laptop because CPU culling and optimizer updates dominate and the GPU sits idle waiting for them.

GS-Scale adds three main optimizations. First, selective offloading keeps only the geometric attributes, mean, scale, and quaternion, on the GPU for all Gaussians. Those are the only fields needed for frustum culling, so the system moves that expensive operation back onto the GPU. This costs only 10 of 59 parameters per Gaussian, about a 17% GPU-memory overhead, while still offloading the other 83% of per-Gaussian attributes and their host-side optimizer state.

Second, parameter forwarding breaks the dependency between CPU optimizer updates and the next GPU iteration. After culling identifies the next iteration’s visible IDs, the CPU eagerly updates only those needed non-geometric parameters using the previous iteration’s gradients and forwards them to the GPU in 32 MB chunks. The remaining parameters are updated lazily on the CPU in parallel with GPU forward/backward execution. Meanwhile, geometry and its optimizer states stay on the GPU and can be updated immediately after each pass. This turns the training loop into a pipeline rather than a strict sequence.

Third, deferred optimizer update exploits Adam’s deterministic behavior under zero gradients. For Gaussians that were not active, GS-Scale does not immediately touch their weights or optimizer states. Instead it increments a 4-bit defer counter and later reconstructs the momentum, variance, and weight using precomputed scaling factors when the Gaussian becomes active again or the counter saturates at 15. The paper reports that on Rubble only 2.29% of Gaussians hit the maximum deferral count, with an average deferral count of 5.03, so most unnecessary CPU memory traffic disappears.

To handle the separate issue that one especially wide-view image can still set the peak memory requirement, GS-Scale also adds balance-aware image splitting. If the active-to-total Gaussian ratio exceeds a threshold, the image is split into two subregions, each rendered separately, with gradients aggregated on the CPU before a single optimizer update. A one-time binary search over the split point keeps the two halves roughly balanced.

## Evaluation

The evaluation is convincing on the paper’s main claim: host offloading can cut memory sharply without making training unusably slow. Built on `gsplat`, GS-Scale reduces peak GPU memory by a 3.98x geomean over GPU-only training across six large scenes, with reductions ranging from 3.3x to 5.6x. The Aerial scene is the clearest stress test: it needs over 50 GB without offloading, but GS-Scale cuts that by 5.5x and makes training possible on an RTX 4080 Super.

Throughput results are more nuanced but still strong. Relative to the naive host-offloaded baseline, the full system improves throughput by 4.47x on the laptop and 4.57x on the desktop. Compared with GPU-only training, GS-Scale reaches a geomean of 1.22x on the laptop and 0.84x on the desktop, excluding OOM cases. That is a fair presentation because GPU-only simply cannot run many of the larger configurations. The paper also checks training quality directly: across six scenes, PSNR, SSIM, and LPIPS are essentially unchanged versus the original training recipe, supporting the claim that deferred updates are a systems optimization rather than an algorithmic approximation with visible quality loss.

The practical payoff is scale. On an RTX 4070 Mobile GPU, GS-Scale raises the trainable Gaussian count from 4 million to 18 million; on an RTX 4080 Super, from 9 million to 40 million. Those larger models translate into visibly better reconstructions, including a 28.7% geomean LPIPS reduction on the laptop and 30.5% on the desktop.

## Novelty & Impact

Relative to _Zhao et al. (ICLR '25)_ on Grendel, GS-Scale tackles the same “keep original 3DGS training semantics while scaling up” goal but does so on a single GPU through CPU host offloading instead of distributed multi-GPU execution. Relative to _Liu et al. (ECCV '24)_ on CityGaussian and other divide-and-conquer methods, its novelty is preserving end-to-end 3DGS training rather than partitioning the scene and paying boundary-quality penalties. Relative to _Ren et al. (USENIX ATC '21)_ on ZeRO-Offload, the new move is workload-specific: exploit per-iteration visibility sparsity and zero-gradient structure instead of generic layerwise prefetching.

This is a systems paper in the strongest sense: the key contribution is not a new rendering model but a memory hierarchy and scheduling strategy tailored to 3DGS training. Anyone building practical 3DGS tooling on commodity hardware, or thinking about sparse working sets in other graphics/ML pipelines, will likely cite it.

## Limitations

GS-Scale depends heavily on the paper’s measured sparsity pattern. If a workload activates a large fraction of Gaussians most iterations, the memory savings and deferred-update win both shrink. The system also assumes enough host memory and decent CPU memory bandwidth; the paper shows performance depends on the GPU-to-CPU bandwidth ratio and even notes weaker results on NUMA servers because deferred updates suffer from low locality.

The image-splitting mechanism is a pragmatic patch rather than a universal solution. It only splits into two regions, uses a threshold chosen by the authors (`mem_limit = 0.3` in experiments), and computes the split point once before training even though densification changes the Gaussian distribution later. Evaluation is otherwise careful, but several throughput comparisons rely on downscaled scenes because the unmodified GPU-only baseline would hit OOM too early. That supports the paper’s practical thesis, but it also means the cleanest apples-to-apples speed comparisons happen below the most extreme scale regime.

## Related Work

- _Kerbl et al. (SIGGRAPH '23)_ — The original 3D Gaussian Splatting paper establishes the explicit Gaussian training pipeline that GS-Scale accelerates and memory-scales without changing its optimization semantics.
- _Zhao et al. (ICLR '25)_ — Grendel keeps the original 3DGS recipe but scales it with multi-GPU distributed training, whereas GS-Scale trades distributed complexity for single-GPU host offloading.
- _Liu et al. (ECCV '24)_ — CityGaussian represents the divide-and-conquer family that reduces memory by partitioning scenes, which GS-Scale argues hurts both efficiency and final quality.
- _Ren et al. (USENIX ATC '21)_ — ZeRO-Offload is the closest host-offloading analogue from LLM training, but GS-Scale contributes a 3DGS-specific design centered on visibility sparsity and deferred updates.

## My Notes

<!-- empty; left for the human reader -->

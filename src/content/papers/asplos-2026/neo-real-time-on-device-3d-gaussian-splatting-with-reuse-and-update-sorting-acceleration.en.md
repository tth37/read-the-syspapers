---
title: "Neo: Real-Time On-Device 3D Gaussian Splatting with Reuse-and-Update Sorting Acceleration"
oneline: "Reuses prior-frame per-tile Gaussian order and incrementally repairs it with dedicated sorting hardware to make high-resolution on-device 3DGS real-time."
authors:
  - "Changhun Oh"
  - "Seongryong Oh"
  - "Jinwoo Hwang"
  - "Yoonsung Kim"
  - "Hardik Sharma"
  - "Jongse Park"
affiliations:
  - "KAIST, Daejeon, Republic of Korea"
  - "Meta, Sunnyvale, CA, USA"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790192"
code_url: "https://github.com/casys-kaist/Neo.git"
tags:
  - hardware
  - gpu
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Neo argues that on-device 3D Gaussian Splatting is no longer primarily blocked by rasterization, but by repeatedly re-sorting per-tile Gaussian lists from scratch. It carries the previous frame's sorted table forward, repairs it incrementally with Dynamic Partial Sorting, and pairs that algorithm with a sorting-focused accelerator. On the evaluated scenes, that is enough to cut DRAM traffic sharply and push QHD rendering into real-time territory.

## Problem

The paper starts from an AR/VR constraint that is hard to satisfy on edge hardware: view synthesis has to run locally, but wearable-class devices have tight bandwidth budgets. Prior 3DGS work, especially GSCore, already improved rasterization substantially, yet the authors show that this mostly exposes a new bottleneck. Under a 51.2 GB/s memory system, GSCore still reaches only `31.1 FPS` at FHD and `15.8 FPS` at QHD.

The diagnosis is that memory traffic, not raw compute, is now limiting performance. Scaling GSCore from 4 to 16 cores under the same bandwidth improves throughput by only about `1.12x`, while a `4x` bandwidth increase yields `3.83x`. Sorting alone consumes up to `90.8%` of GPU traffic and `69.3%` of GSCore traffic.

## Key Insight

Neo's core proposition is that 3DGS sorting should be treated as an incremental repair problem rather than a fresh global sort. Across six scenes, over `90%` of tiles retain more than `78%` of their Gaussians from the previous frame, and even the `99th` percentile ordering change moves a Gaussian by only `31` positions. That means the prior frame's sorted table is already close to correct.

Neo therefore reuses that table, repairs only the parts invalidated by viewpoint change, inserts newly visible Gaussians, deletes outgoing ones, and refreshes depths during rasterization. The central win is algorithmic: the system replaces a bandwidth-heavy global sort with local corrections that fit on chip and need only one off-chip pass.

## Design

The software algorithm has four steps per frame: reordering, insertion, deletion, and depth update. Reordering uses Dynamic Partial Sorting. Instead of globally sorting each tile's Gaussian table, Neo loads a `256`-entry chunk into on-chip memory, sorts it locally, writes it back once, and moves on. To let Gaussians cross chunk boundaries, the system shifts boundaries by half a chunk every other iteration. The authors keep only a single off-chip pass and report less than `0.1 dB` degradation from this choice.

Insertion and deletion handle visibility changes. Incoming Gaussians are identified in preprocessing, while outgoing ones are marked invalid and physically removed during merge. Depth refresh is folded into rasterization: instead of rereading Gaussian depths afterward, Neo writes updated depths back while the features are already in flight. Removing this optimization would increase traffic by `33.2%`.

The hardware mirrors this dataflow. Neo combines a Preprocessing Engine, a Sorting Engine with `16` sorting cores built around Bitonic Sorting Units and Merge Sorting Units+, and a Rasterization Engine with `4` rasterization cores containing Intersection Test Units and Subtile Compute Units. The point is not a generic faster sorter, but a pipeline built specifically for reuse-and-update ordering.

## Evaluation

The evaluation uses six Tanks and Temples scenes at HD, FHD, and QHD. The main baselines are NVIDIA Orin AGX 64GB and GSCore, with GSCore scaled to `16` cores for fair comparison against Neo's `16` sorting units. Neo's advantage grows with resolution: averaged across scenes, it is `5.0x`, `8.7x`, and `12.4x` faster than Orin AGX at HD, FHD, and QHD, and `1.7x`, `3.2x`, and `5.5x` faster than GSCore. At QHD it reaches an average of `97.7 FPS`.

The traffic numbers match the story. Rendering 60 QHD frames averages `360.8 GB` on Orin AGX, `104.6 GB` on GSCore, and `19.5 GB` on Neo, a `94.6%` and `81.4%` reduction relative to the two baselines. Quality holds up: the maximum PSNR drop stays below `1.0 dB`, and several scenes show no measurable change. On Building and Rubble from Mill 19, Neo still averages `72.9 FPS`, and under faster camera motion it remains above `60 FPS` in the tested setup. That is good evidence for the central claim because the workloads directly exercise the bandwidth-limited, temporally correlated regime the design targets.

## Novelty & Impact

Relative to _Lee et al. (ASPLOS '24)_, Neo's novelty is not another rasterization-centric 3DGS accelerator, but the claim that sorting becomes the next dominant bottleneck once rasterization is optimized. Relative to _Feng et al. (ISCA '25)_, it avoids background sorting's steady bandwidth drain by incrementally correcting the current frame's table. Relative to _Wu et al. (MICRO '24)_ and _Ye et al. (HPCA '25)_, it is complementary: those systems optimize other parts of the stack, while Neo specializes in bandwidth-efficient ordering.

## Limitations

Neo depends on temporal coherence. When viewpoint changes become abrupt, the reused ordering is less accurate and the algorithm may need several frames to reconverge. The evaluation is also bounded in scope: it covers six main scenes plus stress cases, and the hardware numbers come from simulation plus RTL synthesis rather than fabricated silicon. More broadly, Neo reduces sorting traffic; it does not solve model compression, stereo rendering integration, or full headset deployment.

## Related Work

- _Lee et al. (ASPLOS '24)_ — GSCore accelerates 3DGS with hierarchical sorting and subtile rasterization, while Neo identifies sorting traffic as the next bottleneck and replaces full per-frame re-sorts with temporal reuse.
- _Feng et al. (ISCA '25)_ — Lumina also exploits temporal redundancy in neural rendering, but it does so with background sorting; Neo instead uses incremental in-place repair to avoid sustained bandwidth contention.
- _Wu et al. (MICRO '24)_ — GauSPU targets SLAM-oriented 3DGS acceleration with a sparsity-adaptive rasterizer, whereas Neo focuses on view-synthesis sorting overhead.
- _Ye et al. (HPCA '25)_ — Gaussian Blending Unit reuses rasterization work on edge GPUs, making it complementary to Neo's reuse of Gaussian ordering.

## My Notes

<!-- empty; left for the human reader -->

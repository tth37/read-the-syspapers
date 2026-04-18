---
title: "AGS: Accelerating 3D Gaussian Splatting SLAM via CODEC-Assisted Frame Covisibility Detection"
oneline: "Uses video-CODEC SAD signals to detect frame covisibility, skip most tracking refinements and non-contributory Gaussians, and pipeline 3DGS-SLAM on dedicated hardware."
authors:
  - "Houshu He"
  - "Naifeng Jing"
  - "Li Jiang"
  - "Xiaoyao Liang"
  - "Zhuoran Song"
affiliations:
  - "School of Computer Science, Shanghai Jiao Tong University, Shanghai, China"
  - "Department of Micro-Nano Electronics, Shanghai Jiao Tong University, Shanghai, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3760250.3762229"
tags:
  - hardware
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

AGS accelerates 3DGS-SLAM by treating video-CODEC motion-estimation output as a cheap signal for frame covisibility. High-covisibility frames use a coarse neural pose estimate and selective mapping that skips previously non-contributory Gaussians, while low-covisibility frames still trigger limited 3DGS refinement and full mapping. A matching accelerator pipeline turns those algorithmic shortcuts into `6.71x` speedup over A100, `17.12x` over AGX Xavier, and `5.41x` over GSCore with small quality loss.

## Problem

The paper starts from a mismatch between reconstruction quality and runtime. Systems such as SplaTAM produce much better scene quality than traditional SLAM, but the authors report that running SplaTAM on fewer than 600 frames still takes more than 20 minutes on an A100. That is too slow for robots that must map and act within minutes.

Their profiling identifies three bottlenecks. Tracking dominates runtime, consuming `83%` of time because it needs about `200` 3DGS iterations per frame while mapping needs about `30`. Mapping is also wasteful: `85.1%` of Gaussians in one Gaussian table do not affect final pixel color. Finally, early termination causes some pixel engines to go idle while others remain busy. Existing accelerators such as GSCore and Cicero help rendering or NeRF inference, but not the full training-heavy 3DGS-SLAM loop.

## Key Insight

The central claim is that adjacent SLAM frames are similar enough that a cheap frame-covisibility signal can drive both algorithmic pruning and hardware scheduling. AGS extracts that signal from the video CODEC's motion-estimation path: the minimum SAD values already computed for compression become a proxy for how much the camera moved.

That proxy supports two decisions. For tracking, high covisibility means a lightweight neural pose estimator is usually enough, and only low-covisibility frames need extra 3DGS refinement. For mapping, high covisibility means many Gaussians that were non-contributory in the last key frame are likely still non-contributory now; at the highest covisibility level, more than `80%` persist across frames. Separately, alpha computation is independent of later recursive color accumulation, so hardware can split rendering and redistribute work from busy engines to idle ones.

## Design

AGS has three logical pieces. First, CODEC-assisted FC detection accumulates the minimum SAD values from motion estimation; larger totals mean lower covisibility. That score is then fed to both tracking and mapping.

Second, movement-adaptive tracking replaces "always run many 3DGS iterations" with a coarse-then-fine policy. Every frame first goes through a Droid-SLAM-style feature extractor and ConvGRU updater. If covisibility is above `ThreshT`, AGS accepts the coarse pose. Otherwise it performs only `IterT` extra 3DGS refinement iterations. The tuned setting uses `ThreshT = 90%` and `IterT = 20`.

Third, Gaussian contribution-aware mapping divides frames into key and non-key frames. Key frames run full mapping and record which Gaussians were effectively useless. Non-key frames reuse that information to skip likely useless Gaussians. A Gaussian is marked non-contributory for a pixel when its alpha value falls below `Threshα = 1/255`; its per-frame non-contributory count is then compared with `ThreshN`. Key versus non-key status is decided by a separate threshold `ThreshM`, with final tuned values `ThreshM = 50%` and `ThreshN = 450`.

The hardware mirrors the algorithm: an FC detection engine piggybacks on the CODEC, a pose tracking engine combines `32 x 32` systolic arrays with a lightweight GS array, and a mapping engine adds GS logging/skipping tables plus update and comparison units. A GPE scheduler splits rendering into alpha computation and color accumulation, letting idle GPEs precompute alpha values for busy ones through an alpha buffer.

## Evaluation

The authors evaluate AGS on TUM-RGBD, Replica, and ScanNet++, and compare against SplaTAM, Orb-SLAM2, GPUs, and GSCore-based configurations. Hardware results come from a cycle-level simulator tied to Ramulator plus a Verilog implementation synthesized at 28nm and `500MHz`, so the evidence is solid for architecture research but still simulation-based.

The main accuracy result is that AGS improves geometric-mean ATE RMSE on TUM-RGBD from `5.54 cm` for SplaTAM to `2.81 cm`, a `1.97x` improvement, while incurring only `2.36%` average PSNR loss. Its selective-mapping predictor has a `5.7%` false-positive rate for wrongly skipped contributory Gaussians. On performance, AGS-Server achieves `6.71x` speedup over A100 and `5.41x` over GSCore-Server, while AGS-Edge reaches `17.12x` over AGX Xavier and `14.63x` over GSCore-Edge. Energy efficiency improves by `22.58x` over A100 and `42.28x` over AGX Xavier, and AGS also delivers `5.11x` speedup when applied to Gaussian-SLAM. The paper's own analysis shows `63.8%` of adjacent TUM-RGBD frames fall into the high-covisibility regime, which helps explain why the design works.

## Novelty & Impact

Relative to _Keetha et al. (CVPR '24)_, AGS is a co-designed system that turns temporal redundancy into both tracking reduction and mapping pruning. Relative to _Lee et al. (ASPLOS '24)_, it covers the whole 3DGS-SLAM training loop rather than only accelerating rendering. Relative to _Teed and Deng (NeurIPS '21)_, it uses a Droid-SLAM-style tracker only as a coarse front-end and keeps selective 3DGS refinement because pure tracker substitution hurts map quality. Its impact is strongest for researchers working on temporal reuse, AI accelerators, and real-time 3DGS-SLAM.

## Limitations

AGS depends heavily on workload structure. If adjacent frames are not highly covisible, both the tracking shortcut and the mapping reuse weaken. Its threshold choices are empirical, with `IterT`, `ThreshM`, and `ThreshN` selected from a Desk-scene sensitivity study, so portability is not free. The hardware evidence comes from traced execution and cycle simulation rather than fabricated silicon, and the GSCore comparison necessarily mixes GSCore rendering with GPU-side training because GSCore does not support the whole loop. Finally, AGS still trails classical SLAM on pure trajectory error: Orb-SLAM2 reaches `1.98 cm` geometric-mean ATE RMSE, so AGS improves the 3DGS-SLAM tradeoff rather than dominating all SLAM regimes.

## Related Work

- _Keetha et al. (CVPR '24)_ — SplaTAM is the baseline 3DGS-SLAM pipeline; AGS keeps its reconstruction style but removes many tracking iterations and mapping computations.
- _Teed and Deng (NeurIPS '21)_ — Droid-SLAM supplies the neural-tracking backbone for AGS's coarse pose estimate, but AGS adds selective 3DGS refinement to stay compatible with 3DGS mapping.
- _Lee et al. (ASPLOS '24)_ — GSCore accelerates 3DGS inference by skipping useless rendering work, whereas AGS targets the training-heavy SLAM loop and adds temporal reuse across frames.
- _Yan et al. (CVPR '24)_ — GS-SLAM is another 3DGS-SLAM design, but AGS focuses on architecture-level acceleration and covisibility-guided pruning rather than scene-representation policy.

## My Notes

<!-- empty; left for the human reader -->

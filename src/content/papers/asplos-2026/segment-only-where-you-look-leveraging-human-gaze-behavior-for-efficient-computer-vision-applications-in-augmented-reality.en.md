---
title: "Segment Only Where You Look: Leveraging Human Gaze Behavior for Efficient Computer Vision Applications in Augmented Reality"
oneline: "Couples gaze-conditioned saliency sampling, frame reuse, and an AR SoC plug-in so segmentation runs only on the object the wearer is looking at."
authors:
  - "Tianhua Xia"
  - "Haiyu Wang"
  - "Sai Qian Zhang"
affiliations:
  - "Tandon School of Engineering, New York University, New York City, NY, USA"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790216"
tags:
  - hardware
  - energy
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

SOLO argues that AR segmentation should follow human attention instead of re-segmenting every full-resolution frame. It combines gaze-conditioned downsampling, cross-frame reuse, saliency-based sensing, and a small SoC accelerator so the system spends work only on the object the user is looking at. The paper reports up to `12x` end-to-end latency reduction, plus `8.6x` average speedup and `9.1x` average energy savings over full-resolution GPU baselines.

## Problem

The paper starts from a direct mismatch between AR sensors and AR compute. Multi-megapixel outer-camera frames are common, but full-resolution segmentation on mobile-class hardware is far too slow for interactive use. On a Jetson Orin NX stand-in, the paper measures `3347 ms` for HRNet and `3942 ms` for ViT-Base at `2880 x 2880`, versus a roughly `50-70 ms` budget for visually fluid AR. Uniformly shrinking every frame is not acceptable either, because the object the user cares about becomes too small to segment well.

AR use is also highly structured. Users usually fixate on one object, then saccade to another, and many adjacent frames remain visually similar while the head pose is stable. Full-frame segmentation therefore wastes work on peripheral regions and often recomputes answers that could have been reused. The paper's systems question is how to turn that behavioral structure into savings in sensing, bandwidth, and inference at the same time.

## Key Insight

The central claim is that, in AR, the instance worth segmenting is usually the one near the user's gaze, and human vision gives the system room to exploit that fact. During fixation, quality matters mostly near the attended object; during saccades, temporary visual suppression means some work can be skipped; across short view-stable segments, old masks can often be reused. If the system can cheaply predict gaze from the eye camera and turn it into a saliency map over the outer frame, then it can spend pixels and compute only where they matter.

That is stronger than ordinary learn-to-downsample work because the saliency map is conditioned on user intent, not only on scene content. The hardware corollary is equally important: once the interesting pixels are known, the camera should avoid reading out the rest instead of sensing the whole frame and compressing later.

## Design

The software path centers on `SOLONet`. It first evenly subsamples the frame to get a coarse image `I_fd`, then feeds `I_fd` plus the eye image `I_e` into `ESNet`. `ESNet` uses an eight-block gaze-tracking ViT, attention-based token pruning, `int8` quantization, and a one-layer RNN for saccade detection. Its output is a saliency score map, which drives nonuniform sampling of the original frame into a much smaller image `I_fs` that preserves resolution near the attended instance.

The downstream segmentation network is simplified to the actual task. Instead of segmenting every object in the scene, it predicts only a binary mask for the instance of interest plus its class label, then upsamples the result back to the original scale. Training is end-to-end with Dice loss plus a regularizer that encourages the saliency map to align with the ground-truth instance region.

The runtime policy is `SSA`, the SOLO Streaming Algorithm. It reruns segmentation only when reuse is unsafe: the view changed beyond threshold `alpha`, gaze moved beyond threshold `beta`, or a new frame segment began. If a saccade is detected, the previous result can also be reused because visual sensitivity is reduced.

The hardware path carries the same idea into the sensor and SoC. Saliency-based sensing (`SBS`) lets the outer camera read out only selected pixel sub-arrays, cutting ADC/readout and MIPI cost directly. A `4.7 mm^2` SOLO accelerator plugs into the AR SoC to run `ESNet`; it uses a `16 x 16` systolic array plus control logic for token pruning, reuse checks, and index-map generation.

## Evaluation

The evaluation covers both algorithmic accuracy and hardware effect. On LVIS, ADE20K, and Aria Everyday, SOLO is compared against average downsampling (`AD`), saliency-only learn-to-downsample (`LTD`), and full-resolution segmentation (`FR`) using HRNet, SegFormer, and DeepLabV3 backbones. The cleanest result is that gaze-conditioning improves accuracy even under similar FLOP budgets: with HRNet on LVIS, SOLO reaches `0.66/0.56` b-IoU/c-IoU, versus `0.56/0.49` for `LTD` and `0.53/0.45` for `FR`.

The reuse study also looks credible rather than cosmetic. When SSA skips about `60%` of frames on Aria Everyday, c-IoU drops by only `0.05`. On the hardware side, compared with `FR+GPU`, SOLO delivers `8.6x` speedup and `9.1x` energy savings on average. Representative end-to-end latency drops from `598.2 ms` to `49.4 ms` for HR on Aria. The sensor-only study supports the co-design story too: under high light, `SBS` cuts sensing latency by `4.3x` on average and reduces sensing energy by `8.9x`.

The user studies matter because latency is part of perceived correctness. In a Quest Pro A/B test on static scenes, participants preferred the SOLO-based presentation in `96% +/- 6%` of trials; in a DAVIS 2016 dynamic-scene study, SOLO was chosen in `122/128` trials while maintaining `28.7 ms` average per-frame latency with SSA enabled. That supports the paper's central claim well: the win is not only fewer FLOPs, but a better latency-accuracy tradeoff at the human-perception level.

## Novelty & Impact

Relative to saliency-based downsampling papers such as _Recasens et al. (ECCV '18)_ and _Thavamani et al. (ICCV '21)_, SOLO's novelty is to replace generic scene saliency with user gaze and then push that signal all the way into the sensor and SoC. Relative to ordinary segmentation systems such as _Cheng et al. (CVPR '22)_, it narrows the task from "segment the whole scene" to "segment the attended instance," then exploits that narrower contract aggressively. That makes the paper likely to matter to AR system builders, mobile-vision researchers, and hardware/software co-design work around perceptual computing.

## Limitations

The approach is tightly coupled to tasks where one gazed-at instance dominates. Applications that require whole-scene understanding, multi-object reasoning, or peripheral anomaly detection will not fit naturally, and the method depends on reasonably accurate gaze estimation. Several of the strongest hardware results also come from RTL synthesis and sensor modeling rather than fabricated silicon. Reuse depends on view stability too: on the more dynamic DAVIS dataset, SSA still helps, but only skips `13%` of frames. Finally, the user studies are encouraging but small, with seven participants for the static-scene study and four for the dynamic A/B test.

## Related Work

- _Recasens et al. (ECCV '18)_ — Learning to Zoom introduced saliency-based learnable resampling, but SOLO replaces generic saliency with gaze-conditioned sampling for AR segmentation.
- _Thavamani et al. (ICCV '21)_ — Fovea also uses nonuniform sampling, yet targets autonomous navigation rather than user-attended instance segmentation on AR devices.
- _Cheng et al. (CVPR '22)_ — Mask2Former is a strong full-scene segmentation baseline; SOLO trades that generality for a narrower but much lower-latency attended-object task.
- _Liu et al. (TVCG '25)_ — FovealNet focuses on efficient gaze tracking itself, whereas SOLO uses gaze as the control signal for sensing and segmentation co-design.

## My Notes

<!-- empty; left for the human reader -->

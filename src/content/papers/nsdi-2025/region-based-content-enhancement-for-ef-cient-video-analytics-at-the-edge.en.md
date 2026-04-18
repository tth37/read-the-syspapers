---
title: "Region-based Content Enhancement for Efficient Video Analytics at the Edge"
oneline: "RegenHance predicts accuracy-critical macroblocks, packs them across streams, and co-plans enhancement with inference to gain 10-19% accuracy at 2-3x frame-based throughput."
authors:
  - "Weijun Wang"
  - "Liang Mi"
  - "Shaowei Cen"
  - "Haipeng Dai"
  - "Yuanchun Li"
  - "Xiaoming Fu"
  - "Yunxin Liu"
affiliations:
  - "Institute for AI Industry Research (AIR), Tsinghua University"
  - "State Key Laboratory for Novel Software Technology, Nanjing University"
  - "University of Göttingen"
conference: nsdi-2025
category: llm-and-ml-training-serving
code_url: "https://github.com/mi150/RegenHance"
tags:
  - ml-systems
  - scheduling
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

The paper argues that edge video analytics should not enhance whole frames when only a small subset of pixels actually changes downstream accuracy. RegenHance predicts important macroblocks, packs those regions densely across streams, and jointly plans decoding, prediction, enhancement, and inference. On five heterogeneous devices, it improves accuracy by 10-19% over direct inference while delivering 2-3x throughput over frame-based enhancement baselines.

## Problem

Edge video analytics lives in an awkward regime. Cameras are cheap, uplinks are constrained, and downstream DNNs are sensitive to blur, compression artifacts, and low resolution. Content enhancement helps, because a super-resolution or restoration model can recover details before inference, but the straightforward version is too expensive: enhancing every frame adds large latency and competes directly with the analytics model for GPU time.

The paper's motivation study shows why prior selective frame enhancement is still unsatisfying for analytics. Per-frame super-resolution improves accuracy by more than 10%, but cuts end-to-end throughput by more than 76% relative to running inference directly on the original frames. Anchor-frame methods such as selective SR recover some throughput, but they reuse enhanced content across nearby frames. That reuse is acceptable for human viewing, yet it is much less acceptable for DNN inference, where small distortions can flip predictions. To satisfy a 90% target accuracy, the selective method still has to enhance 27-61 frames in a 120-frame chunk on average, which is far too much work for an edge server.

## Key Insight

The paper's key claim is that the expensive unit of enhancement is wrong. What matters for analytics is not whether a frame as a whole was enhanced, but whether the regions whose quality affects inference were enhanced. The authors call those regions Eregions. In more than 75% of object-detection frames, Eregions occupy only 10-25% of the image area; for semantic segmentation, 70% of frames need only 10-15% of the area enhanced. At the same time, enhancement latency scales with input size rather than with pixel values, so blacking out the rest of the frame does not save time.

That leads to a concrete proposition: if the system can identify the macroblocks whose enhancement would most improve downstream accuracy, then it should enhance only those macroblocks, batch them densely across streams, and allocate resources so that no pipeline stage becomes the bottleneck. The system therefore needs a fast importance predictor, a packing algorithm that converts sparse regions into dense enhancement inputs, and a scheduler that reasons globally across heterogeneous streams and devices.

## Design

RegenHance has three components. The first is MB-based region importance prediction. Instead of working at pixel granularity, the system uses codec macroblocks such as H.264's 16x16 MBs as the basic unit. That is precise enough to capture small objects but much cheaper than per-pixel reasoning. The paper defines an importance metric from two signals: how sensitive downstream analytical accuracy is to a pixel change, and how much enhancement would change that pixel relative to bilinear interpolation. Ground truth labels are produced offline by enhancing frames, running one forward and backward pass of the analytical model, and then assigning importance to each MB.

At runtime, RegenHance approximates MB importance prediction as a lightweight segmentation task with 10 importance levels. It retrains several candidate models and chooses MobileSeg because it matches heavyweight models' accuracy while running 4-18x faster. To avoid predicting every frame in a chunk, it also reuses MB-importance outputs over time. A lightweight operator over Y-channel residual changes in the compressed stream selects representative frames, predicts those frames' MB importance, and reuses the results for nearby frames. The paper reports that this predictor alone can run at 30 fps on one i7-8700 CPU core and 973 fps on a GPU.

The second component is region-aware enhancement. RegenHance aggregates MBs from all streams into a global queue sorted by importance, then selects the top N MBs that fit the current enhancement budget. Because enhancement models require rectangular tensors while the chosen MBs are sparse and irregular, the system groups connected MBs into regions, bounds them with rectangles, partitions oversized boxes, and sorts candidate boxes by importance density rather than raw area. It then packs them into fixed-size bins with rotation when useful, stitches the real pixels into dense tensors on the GPU, runs super-resolution, and pastes the enhanced content back into bilinearly upscaled frames. The importance-density ordering is essential because classic large-item-first packing wastes budget on big boxes that contain too many unimportant pixels.

The third component is profile-based execution planning. RegenHance models the pipeline as a DAG of decoder, importance predictor, enhancer, and analytical model. On a given edge device, it profiles each component on each accessible processor and searches for hardware assignments and batch sizes that maximize throughput under latency and accuracy targets. The paper uses dynamic programming over the DAG. In practice, this matters because naive round-robin or sequential scheduling leaves substantial CPU and GPU time idle and may spend enhancement budget on the wrong streams.

## Evaluation

The evaluation covers two downstream tasks, object detection and semantic segmentation, on five heterogeneous devices: RTX4090, A100, RTX3090Ti, Tesla T4, and Jetson AGX Orin. The baselines are `only infer`, NeuroScaler, Nemo, and several strawman variants of the paper's own pipeline. This setup is strong because it tests both a heavyweight and a lightweight analytical model and varies device class, task, resolution, stream count, and target accuracy.

The main result is consistent with the paper's thesis. Across devices, RegenHance improves accuracy by 10-19% over direct inference while delivering 2-3x throughput relative to state-of-the-art frame-based enhancement. Averaged over the experiments, its throughput exceeds Nemo by 12x for object detection and 11x for semantic segmentation, and exceeds NeuroScaler by 2.1x and 1.9x respectively. On RTX4090 or A100, it can serve ten object-detection streams, 300 fps total, at about 91% accuracy under a one-second latency target, or six streams at 95% accuracy.

The component analysis is also persuasive. Execution planning alone lifts throughput from 95 fps to 111 fps over per-frame SR. Adding MB prediction without region-aware packing does not help, because zeroing unimportant pixels leaves enhancement latency unchanged. Once the region-aware enhancer is enabled, throughput jumps to 179 fps, and the full system reaches 300 fps. The predictor outperforms DDS-style RoI selection by more than 60x on CPU and more than 12x on GPU, while temporal reuse doubles its throughput. The packing policy achieves a 75% occupy ratio and beats alternative packing schemes by up to 13%. Cross-stream MB selection improves accuracy by 8-12% over uniform allocation and by 2-3% over a fixed-threshold policy. The evidence supports the central claim that fine-grained selection plus global scheduling, not just "less enhancement," is what makes the design work.

## Novelty & Impact

Compared with _Yeo et al. (SIGCOMM '22)_ on NeuroScaler and _Yeo et al. (MobiCom '20)_ on Nemo, the novelty is that RegenHance changes the unit of optimization from sampled frames to importance-ranked macroblocks. Compared with _Du et al. (SIGCOMM '20)_ on DDS, it is not merely doing RoI selection, but estimating which regions most affect analytical accuracy after enhancement and making that estimate cheap enough for online use.

That makes the paper a useful systems contribution for edge video analytics platforms that let users bring their own models. It combines a task-aware metric, a packing mechanism aligned with enhancement-model behavior, and a runtime planner that reasons across the whole pipeline. It gives later work on smart cameras, edge GPU schedulers, and analytics-specific video preprocessing a concrete result to build on: the right granularity of enhancement is neither the whole frame nor a generic perception-oriented RoI.

## Limitations

The system is not plug-and-play. Each downstream analytical task needs its own offline-generated importance labels and its own fine-tuned MobileSeg predictor because the importance metric depends on the downstream model. The paper says that fine-tuning takes only about four minutes on eight RTX3090 GPUs, but that is still an operational cost that a production platform must absorb.

The win also depends on sparsity. If most of the frame matters, or if the enhancement model's gains are spread broadly rather than concentrated in small regions, the advantage of region-based packing shrinks. The evaluation is limited to object detection and semantic segmentation with one super-resolution model family, so the evidence for other vision tasks is indirect. Finally, the runtime still needs per-device profiling and a nontrivial amount of systems integration, including residual extraction and GPU-side stitching, and the paper reports 1-3 minutes of planning on a new device plus 0.6-2 seconds of initialization when stream sets change.

## Related Work

- _Du et al. (SIGCOMM '20)_ - DDS selects regions of interest to reduce offloading cost, while RegenHance predicts the macroblocks whose enhancement most improves analytical accuracy and keeps the selector lightweight enough for real-time use.
- _Yeo et al. (MobiCom '20)_ - Nemo selectively enhances anchor frames and reuses their gains, whereas RegenHance argues that reusing enhanced content hurts inference and instead reuses only importance predictions.
- _Yeo et al. (SIGCOMM '22)_ - NeuroScaler scales neural video enhancement at the frame level; RegenHance moves the optimization target to cross-stream MB regions and couples it with resource planning.
- _Lu et al. (SenSys '22)_ - Turbo exploits idle GPU slots for enhancement, while RegenHance redesigns the enhancement granularity and explicitly balances decoder, selector, enhancer, and inference stages.

## My Notes

<!-- empty; left for the human reader -->

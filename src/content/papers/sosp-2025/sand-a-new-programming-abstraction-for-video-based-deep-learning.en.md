---
title: "SAND: A New Programming Abstraction for Video-based Deep Learning"
oneline: "SAND turns video preprocessing into filesystem-backed views and plans reusable materializations across tasks and epochs to avoid repeated decoding and keep training GPUs busy."
authors:
  - "Juncheol Ye"
  - "Seungkook Lee"
  - "Hwijoon Lim"
  - "Jihyuk Lee"
  - "Uitaek Hong"
  - "Youngjin Kwon"
  - "Dongsu Han"
affiliations:
  - "KAIST"
  - "Chung-Ang University"
  - "Maum.AI"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764847"
tags:
  - ml-systems
  - filesystems
  - caching
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SAND argues that video training bottlenecks are fundamentally an object-management problem, not just a faster-decoder problem. It exposes videos, frames, augmented frames, and training batches as filesystem-backed views, then plans which intermediate objects to materialize, cache, and reuse across epochs and concurrent jobs. That combination cuts repeated decoding enough to deliver up to 10.2x faster hyperparameter search than CPU preprocessing and up to 2.8x over a GPU/DALI baseline.

## Problem

The paper starts from an uncomfortable fact about video-based deep learning: preprocessing is both hard to write and often slower than the model itself. A typical pipeline must decode compressed video, choose sparse frame subsets, apply random spatial transforms, assemble clips into batches, and do all of that again for every epoch. In SlowFast, the authors report more than 2.2k lines of preprocessing code, over twice the code used for model training. Existing frameworks mostly leave this pipeline in user code, so developers must manually manage objects, dependencies, and storage.

The performance consequences are equally serious. On the paper's benchmark applications, CPU preprocessing takes 2.2x to 6.5x longer than GPU training, which causes 65-88% lower GPU utilization relative to an ideal stall-free pipeline. Moving preprocessing onto the GPU with DALI and hardware decode helps, but not enough: preprocessing still exceeds training time by 1.3x to 2.7x, shrinks usable batch size on 1080p video from 24 to 16 on an A100, and consumes 2.6x more energy than CPU decoding. The deeper problem is repeated decoding. Videos are sampled differently each epoch, frames are discarded after use, and independent jobs such as hyperparameter search decode the same source videos again with no system-level sharing. Caching everything is not realistic either; the paper estimates Kinetics-400 would need about 83.5 TB if fully decoded, far beyond the 85 GB memory and 3 TB local SSD on the cloud instances they target.

## Key Insight

SAND's core claim is that preprocessing should be expressed as reusable storage objects with system-managed lifetimes. Instead of treating each job's preprocessing pipeline as private application logic, SAND turns intermediate results into first-class views and lets the system coordinate when they are generated, cached, evicted, and shared.

What makes that idea work is coordinated randomness. Video training needs random frame sampling and random crops for statistical correctness, so naive reuse would bias the workload. SAND therefore does not remove randomness; it aligns random choices across tasks just enough to create overlap. It uses a shared frame pool for temporal sampling and a shared window mechanism for stochastic spatial transforms, so tasks can still see random inputs while the system gains common sub-objects worth reusing. The result is a storage abstraction that preserves training semantics while exposing enough structure for caching and scheduling to matter.

## Design

The user-facing abstraction is the view. A view is a virtual object representing a stage in the pipeline, such as a decoded frame set, an augmented frame, or the final training batch. Users describe video handling and augmentation in a configuration file, and then access the desired object through a stable path such as `/{task_name}/{epoch}/{iteration}/view`. SAND serves these paths through the Linux VFS and standard POSIX calls like `open()`, `read()`, and `getxattr()`, so an ordinary PyTorch `Dataset` can fetch a batch without knowing how it was produced.

Internally, SAND builds two graphs. For each task, it first creates an abstract view dependency graph that records view types and operations. It then compiles those into a concrete object dependency graph for the next `k` epochs, where videos, frames, augmentations, and batches become actual cacheable objects. Reuse comes from merging identical subpaths across tasks and epochs. To preserve temporal randomness, SAND computes a common sampling grid using the GCD of requested strides, samples frames on that grid, and lets tasks draw from a shared frame pool. To preserve spatial randomness, it separates deterministic transforms from stochastic ones and uses one randomly chosen large crop window that smaller task-specific crops can reuse as subregions.

After planning comes selective materialization. SAND begins from the ideal-but-impossible case of caching all leaves, then greedily prunes the object graph upward when a parent object saves storage without too much recomputation. Objects are chosen based on reuse frequency, regeneration cost, and footprint. At runtime, demand-feeding threads have highest priority because they satisfy current `read()` calls, while pre-materialization threads work ahead on future epochs. Priorities are deadline-based under normal conditions and switch toward shortest-job-first when memory pressure exceeds a threshold. The prototype is implemented as a FUSE filesystem, uses libvpx and openh264 for decode, libtorch-cpu and OpenCV for augmentations, and caches frames with lossless libpng compression.

## Evaluation

The evaluation covers four representative settings on GCP A2 instances with A100 GPUs, 12 vCPUs per GPU, and 3 TB local NVMe: single-task training, Ray Tune hyperparameter search, concurrent heterogeneous training, and two-node distributed training against remote Filestore. The workloads are SlowFast, MAE, HD-VILA, and BasicVSR++, with on-demand CPU preprocessing via PyAV/Decord-style libraries, on-demand GPU preprocessing via DALI, and an ideal no-stall upper bound.

The central claim is well supported. In single-task training, SAND cuts end-to-end time by 2.4x to 5.6x versus CPU preprocessing and still beats the GPU baseline by 1.4x to 1.7x, while raising GPU utilization by 2.5x to 5.7x versus CPU and 1.4x to 1.7x versus GPU. The bigger wins appear when reuse opportunities multiply. In hyperparameter search, SAND speeds search by 2.9x to 10.2x over CPU and 1.4x to 2.8x over GPU, with GPU utilization up to 12.3x higher than CPU and 2.9x higher than GPU. In concurrent SlowFast+MAE training, it delivers 5.3x and 6.2x faster training than CPU baselines. In remote-storage distributed training, it gives SlowFast a 5.2x speedup and reduces network bandwidth demand to 3% of baseline by caching materialized batches locally.

The component studies are also useful. Materialization planning cuts decoding operations by 50.3% and random-crop work by 33.1%, and the resulting reuse lifts GPU utilization by 2.64x to 2.78x. Graph pruning lowers recomputation overhead by 10% with 3 TB storage and 25% with 1.5 TB. Priority-based scheduling reduces average iteration time enough that disabling it makes SAND 42.6% slower. The paper also shows that its coordinated randomness does not visibly distort training loss curves.

## Novelty & Impact

SAND is novel because it reframes video preprocessing as a system-managed storage problem. Libraries such as PyTorchVideo and Decord provide useful loaders and codec interfaces, but they leave each job to rebuild the same pipeline independently. Scanner also models video processing as a higher-level graph, yet its focus is video analytics throughput rather than repeated reuse across iterative training epochs and concurrent deep-learning jobs. Image-oriented preprocessing accelerators such as FusionFlow or Goldminer attack input-pipeline overhead, but SAND's distinctive move is to make video-training intermediates explicit objects whose reuse can be planned across time and across jobs.

That makes the paper likely to matter beyond video ML. The view abstraction, pruning policy, and scheduling strategy are concrete enough to be cited by ML systems work on pretraining pipelines, AutoML, and multimodal training, but the deeper contribution is a reusable design pattern: expose expensive intermediate data as virtual objects, then let the system coordinate correctness-preserving reuse.

## Limitations

SAND's benefits are strongest when tasks share datasets and preprocessing structure. The paper's own numbers show that single-task gains are smaller than hyperparameter-search or multi-task gains, which means the abstraction is not magic; it wins by manufacturing and exploiting overlap. If workloads have highly task-specific augmentations, little repeated access, or extremely tight local storage budgets, the reuse opportunity shrinks and more recomputation leaks back in.

The evaluation scope is also narrower than the ambition of the abstraction. The prototype is tested on a handful of open-source training stacks, mostly on GCP A100 instances, and the remote-storage experiment reports one model in one WAN-backed setup. Because the system sits in user space through FUSE and keeps preprocessing on CPUs, it still trails the ideal no-stall case by 5-14% in hyperparameter search. Finally, custom augmentations require conforming to SAND's interface or running through its RPC path, so the operational cost of adopting it in messy production pipelines is only partially explored.

## Related Work

- _Poms et al. (TOG '18)_ - Scanner represents video processing as computation graphs for scalable analytics, but it does not target iterative DNN training where the same videos are repeatedly reprocessed across epochs and jobs.
- _Cheng et al. (TPDS '21)_ - This work co-designs preprocessing and scheduling for deep learning workflows, whereas SAND focuses specifically on compressed-video pipelines and cross-task reuse of decoded and augmented intermediates.
- _Kim et al. (VLDB '23)_ - FusionFlow accelerates preprocessing through CPU-GPU cooperation, but SAND's contribution is to make reusable video-training objects explicit and system-managed rather than merely faster to produce.
- _Zhao et al. (Proc. ACM Manag. Data '23)_ - Goldminer elastically scales training-data preprocessing pipelines, while SAND attacks the separate problem of repeated decoding and reuse under iterative video training.

## My Notes

<!-- empty; left for the human reader -->

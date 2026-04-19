---
title: "Heimdall: Optimizing Storage I/O Admission with Extensive Machine Learning Pipeline"
oneline: "Heimdall predicts SSD busy periods rather than isolated slow I/Os, then turns that model into a 28 KB admission controller for replicated flash storage."
authors:
  - "Daniar H. Kurniawan"
  - "Rani Ayu Putri"
  - "Peiran Qin"
  - "Kahfi S. Zulkifli"
  - "Ray A. O. Sinurat"
  - "Janki Bhimani"
  - "Sandeep Madireddy"
  - "Achmad Imam Kistijantoro"
  - "Haryadi S. Gunawi"
affiliations:
  - "University of Chicago"
  - "MangoBoost Inc."
  - "Bandung Institute of Technology"
  - "Florida International University"
  - "Argonne National Laboratory"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717496"
code_url: "https://github.com/ucare-uchicago/Heimdall"
tags:
  - storage
  - kernel
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Heimdall is an ML-based I/O admission controller for replicated flash storage. Its main move is to predict SSD busy periods, not isolated slow I/Os, and to engineer the whole pipeline so that a tiny per-I/O neural network stays accurate enough to matter in practice. That raises accuracy from LinnOS' current 67% to 93%, cuts average latency by 15-35% in 500 trace-driven experiments, and runs with 28 KB of model state at 0.05-0.08 µs inference latency.

## Problem

The paper studies replicated flash storage, where a front-end can send a read to one backend replica and that replica can either admit the request locally or decline it so the front-end reroutes to another copy. This is valuable because SSDs are black boxes whose internal garbage collection, buffer flushing, wear leveling, and burst interactions can create long tail-latency episodes. Prior work already showed that a slow replica is sometimes worse than reconstructing or redirecting the request elsewhere.

The hard part is making the admit-or-reroute decision accurately. Heuristic systems such as C3, AMS, and Heron depend on hand-tuned rules. LinnOS moved to ML, but it predicts at a fixed 4 KB granularity and labels individual requests with a latency cutoff. On modern traces from Microsoft, Alibaba, and Tencent, the authors find that this older design now averages only 67% accuracy. In this setting, both kinds of mistakes hurt: false admits send a read into a busy device, while false reroutes overload the alternate replica and raise average latency. A useful solution therefore has to improve prediction quality without adding enough CPU or memory overhead to make kernel or distributed deployment unrealistic.

## Key Insight

Heimdall's key claim is that admission control should learn device state over periods, not ask whether one completed I/O happened to be slow. SSD background work manifests as intervals where latency rises while throughput drops, and those intervals are what matter operationally. A large request can look slow even on an otherwise healthy device, so per-request latency cutoffs create bad labels; by contrast, labeling busy periods makes the target align with the real decision the system needs to make: is this replica in a bad phase right now?

That shift also explains why the authors spend so much effort on data cleaning. If the model is supposed to detect prolonged contention, then lucky cache hits inside a slow period, transient ECC or retry events inside a fast period, and very short slow bursts are all label noise rather than signal. Once the labels reflect sustained busyness, a compact model can use recent queue depth, recent latency, recent throughput, and I/O size to infer whether the next request should be admitted.

## Design

Heimdall is best understood as an end-to-end ML pipeline rather than just a classifier. Its period-based labeling first marks candidate busy I/Os when latency is high and throughput is low, with thresholds chosen by a gradient-descent search that balances sensitivity and accuracy. It then extends those labels to whole tail periods. A three-stage noise filter removes fast outliers inside slow periods, slow outliers inside fast periods, and short slow bursts of three I/Os or fewer. On top of that cleaned data, the authors do feature engineering and settle on five main features: queue length, historical queue length, historical latency, historical throughput, and I/O size, with a historical depth of three and min-max normalization.

For the model itself, Heimdall keeps the architecture simple. After exploring several learners, the authors choose a neural network because it gives the best accuracy-stability tradeoff. The final network predicts at per-I/O granularity, uses two hidden layers with 128 and 16 neurons, keeps ReLU in the hidden layers, and uses a single-neuron sigmoid output. That is already a major simplification over LinnOS because Heimdall does not split a large I/O into many 4 KB inferences.

Deployment is treated as part of the design, not an afterthought. The authors manually convert the inference path from Python to C++, compile with `-O3`, and quantize the weights by scaling them by 1,024. The result is sub-microsecond inference latency and a 28 KB model footprint. They also add joint inference: one inference can cover up to `P` I/Os, while still only carrying recent history from the last few I/Os so the model does not explode in size. This gives operators a throughput-versus-accuracy knob without changing the basic architecture.

## Evaluation

The evaluation is unusually broad for a paper in this space. Heimdall is trained and tested on 2 TB of raw traces from Microsoft, Alibaba, and Tencent, generating 11 TB of intermediate data, and the main user-level study draws 500 random three-minute traces spanning different read/write ratios, request sizes, IOPS, and randomness levels. In the main setup, the authors emulate a 2-way replicated environment with two Samsung 970 PRO SSDs and compare against baseline, random routing, C3, LinnOS, and hedging. They first justify C3 as the strongest heuristic representative among AMS, C3, and Heron, then show Heimdall has the best percentile and average latency overall. The headline number is 15-35% lower average latency than the state of the art and up to 2x faster than the baseline.

The ablations do a good job supporting the central claim. Starting from LinnOS at 67% ROC-AUC, replacing digitization with min-max scaling brings accuracy to 67.5%, period-based labeling lifts it to 73%, richer features lift it to 77%, and the three-stage noise filter supplies the final jump to 93%. The deployment-cost numbers are also strong: compared with LinnOS, Heimdall cuts model memory from 68 KB to 28 KB, reduces CPU overhead by 2.5x, and executes inference in 0.05-0.08 µs depending on CPU. Joint inference extends the sustainable workload from 0.5 mIOPS to 4 mIOPS at a 2 µs latency target when the joint size is 9, but median accuracy falls from 88% to 81%, which is why the authors recommend a joint size of 3 as a better operating point.

The paper also checks whether the method survives more realistic deployment settings. In the Linux-kernel prototype, on heterogeneous Intel DC-S3610 and Samsung PM961 SSDs, Heimdall still achieves the lowest average latency and is 38-48% faster than the non-baseline methods. In Ceph, across 10 machines and 20 OSDs, it beats baseline and random routing across different scale factors. That said, the Ceph experiment uses FEMU-emulated SSDs because of hardware availability, so I read that result more as evidence that the policy generalizes to distributed control paths than as proof of absolute flash-device behavior at cluster scale.

## Novelty & Impact

The paper's novelty is not a fancy new learning model. The real contribution is a storage-specific formulation of admission control, plus the discipline to optimize the whole ML pipeline and deployment path together. Compared with LinnOS, Heimdall changes the prediction target from per-page slowdown to busy periods, makes variable-sized I/O first-class, and shrinks the runtime model enough for practical kernel and Ceph integration. Compared with LAKE, which helps kernels offload ML inference to GPUs, Heimdall tries to make CPU-side inference cheap enough that offload is optional rather than required.

That makes the paper likely to matter to two groups. Storage researchers can cite it as evidence that admission control accuracy depends more on domain-specific labeling and preprocessing than on exotic model families. Systems researchers building deployable ML components can cite it as a case where careful feature design, quantization, and language-level optimization matter more than raw benchmark accuracy. The paper therefore feels like a strong new framing of an existing problem, backed by a practical mechanism that is ready to be reused.

## Limitations

Heimdall is still a trained model, which means its usefulness depends on collecting representative traces and retraining when workloads drift. The long-run experiment shows accuracy varying between 63% and 82% over eight hours if the model is trained only once, and the paper's preliminary retraining policy assumes access to recent per-request logs even though the authors acknowledge that such logging is expensive and often disabled by default. That makes the retraining story interesting but incomplete.

There are other limits as well. The whole system is optimized for read-latency control in replicated flash arrays, not general storage scheduling. Joint inference buys throughput only by giving up some accuracy. The Ceph evaluation relies on FEMU rather than physical SSDs. And although the paper calls the system black-box, the solution still depends on storage-specific feature engineering, threshold searches, and hand-designed filters, so it is not an automatic recipe one can drop into arbitrary devices or workloads without care.

## Related Work

- _Hao et al. (OSDI '20)_ - LinnOS is the direct predecessor: it uses a light neural network for flash admission control, but its per-4 KB cutoff-based labeling makes it less accurate and less natural for variable-sized I/O than Heimdall.
- _Fingler et al. (ASPLOS '23)_ - LAKE focuses on making kernel-space ML more deployable through GPU-assisted batching, whereas Heimdall instead simplifies the model and adds joint inference so storage admission can stay efficient on CPUs.
- _Suresh et al. (NSDI '15)_ - C3 cuts tail latency through heuristic replica selection in cloud data stores; Heimdall tackles a similar admit-versus-reroute decision, but learns SSD-specific busy periods rather than relying on adaptive heuristics.
- _Wong et al. (FAST '24)_ - Baleen also uses ML for storage admission, but its target is flash-cache admission and prefetching, while Heimdall focuses on block-level I/O admission across replicated flash devices.

## My Notes

<!-- empty; left for the human reader -->

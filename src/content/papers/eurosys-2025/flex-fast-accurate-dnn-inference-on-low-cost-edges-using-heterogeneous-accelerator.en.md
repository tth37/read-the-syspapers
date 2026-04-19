---
title: "Flex: Fast, Accurate DNN Inference on Low-Cost Edges Using Heterogeneous Accelerator Execution"
oneline: "Flex learns how each input behaves on the CPU and low-cost accelerator, then dynamically splits DNN layers to better satisfy latency, accuracy, and energy goals on edge devices."
authors:
  - "Tanmoy Sen"
  - "Haiying Shen"
  - "Anand Padmanabha Iyer"
affiliations:
  - "University of Virginia"
  - "Georgia Institute of Technology"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696067"
tags:
  - ml-systems
  - hardware
  - energy
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Low-cost accelerators speed up DNN inference, but their lower precision can change the answer, and the best CPU/LCA split depends on the input. Flex profiles time, accuracy, and output matching offline, then uses heuristics or SAC-based RL to pick a per-input layer placement or a single split point. Across several models on three Android phones, the paper reports up to 39% lower average inference time, up to 22% higher accuracy, and up to 61% lower energy than prior approaches, while Flex-RL+ stays within about 4.2% of Oracle on inference time.

## Problem

The paper targets budget edge devices with GPUs, TPUs, DSPs, or NPUs that save energy by running at lower precision. That creates a bad default choice: all-LCA execution is fast but can lose accuracy, while CPU-only execution preserves fidelity but gives up latency and energy gains. In the authors' measurements, all-LCA execution can lose up to 7.3% accuracy relative to all-CPU execution.

The closest prior system, MLMP, fixes one partition offline. Flex shows that this is inadequate: the Oracle assignment varies with the input even when the input distribution still resembles the training data, and different ImageNet, HAR, and SQuAD classes prefer different CPU/LCA splits. The search is hard because layers affect time and accuracy unevenly, and CPU/LCA communication can cost more than nearby computation. The real task is therefore per-input partitioning under accuracy, deadline, and memory constraints.

## Key Insight

Per-input heterogeneous execution is feasible if the runtime predicts a few cheap signals instead of exhaustively evaluating schedules online. Flex learns three: the time cost of an assignment, the accuracy cost of an assignment, and whether CPU and LCA execution are likely to match at the single-layer or whole-model level.

Those signals support a simple policy. Layers predicted to match are safer to move, later heavy layers usually buy the most latency reduction, and because CPU/LCA crossings are expensive, one communication-aware split often beats arbitrary interleavings. Flex therefore replaces exponential online search with learned scoring plus a few empirical rules about where the useful layers usually are.

## Design

Flex starts with offline profiling. It samples random layer assignments, measures time and accuracy, and trains two random-forest regressors: `RF-T` for inference time and `RF-A` for accuracy. Their inputs include model structural features, the proposed assignment, and the input sample; the measured time already includes CPU/LCA communication. It also trains two classifiers: `layer-classifier` predicts whether moving one layer to the LCA preserves the CPU result, and `model-classifier` predicts whether full-model CPU and LCA executions match.

The heuristic path has three variants. `Flex-L` greedily moves layers predicted to match, favoring those that save more time and lose less accuracy under `RF-T` and `RF-A`; if needed, it can move unmatched layers too. `Flex-D` chooses a single division point to avoid repeated CPU/LCA crossings: in accuracy-first mode it moves shallow layers first, while in latency-first mode it starts from the heavy suffix and searches for the split that saves the most time while meeting accuracy and memory constraints. `Flex-B` speeds this up by grouping layers, binary-searching groups, then linearly searching inside the best group.

`Flex-RL` and `Flex-RL+` replace the heuristic with soft actor-critic. State consists of deadline, accuracy target, and available memory; action is a layer assignment; violating constraints gets a large negative reward. `Flex-RL` trains on estimated time and accuracy, while `Flex-RL+` uses actual values during training. Curriculum learning transfers across related model families, and all layers stay resident in both CPU and LCA memory so scheduling changes execution location rather than moving model weights.

## Evaluation

The evaluation uses eight models across vision, NLP, and time-series tasks and three Android phones: a Snapdragon 778G device with GPU and Hexagon 770, a Pixel 6 TPU phone, and a Snapdragon 888G device. Inputs range from 100 to 500 per model, with deadlines from 0.5 to 5 seconds and accuracy requirements from 80% to 95%.

The main result is that input-aware partitioning beats static partitioning and model-selection-style baselines. Relative to ALERT-T, Mistify, AMPT, ALERT-A, MLMP-T, MLMP-A, and a simple suffix-moving strawman, `Flex-D` improves timeliness guarantee ratio by 11-35% and lowers inference time by 11-34%, depending on the baseline. `Flex-L` and `Flex-RL` gain another 2-3% timeliness over `Flex-D`, while `Flex-B` improves `Flex-D` by 2% timeliness and 3% inference time with lower search cost.

The best overall variant is `Flex-RL+`. Compared with `Flex-RL` and `Flex-L`, it improves timeliness by 2.5% and 2.8% and reduces inference time by 3% and 4%, because it trains on actual rather than estimated metrics. The paper also reports that `Flex-RL+` is only about 2.5% below Oracle on accuracy and accuracy guarantee and about 4.2% behind Oracle on inference time. Decision overhead drops 48% from `Flex-L` to `Flex-D`, another 41% from `Flex-D` to `Flex-B`, and about 90% from `Flex-B` to `Flex-RL+`. Energy follows inference time, with the abstract reporting up to 61% lower energy than prior work.

## Novelty & Impact

Flex's novelty is not partitioning by itself but making partitioning input-aware and accuracy-aware under low-cost-accelerator behavior. MLMP statically partitions CPU/NPU execution, ALERT and Mistify mostly choose among models, and CPU/GPU cooperative execution systems such as `μLayer` mainly optimize latency. Flex combines output-fidelity prediction, communication-aware split selection, and a low-overhead learned controller in one runtime.

That makes the paper relevant to mobile ML runtimes and embedded AI deployments where deadline and accuracy both matter. The broader lesson is that low-precision accelerators are not just faster coprocessors; they change the model's behavior, so the scheduler has to reason about semantic fidelity as well as throughput.

## Limitations

Flex is not cheap to prepare. Offline training takes roughly 5-6 hours for the regressors, 2.45 hours for the layer-classifier, 4.2 hours for the model-classifier, and about 7 hours for RL, so deployment is per-device and per-model-family work rather than instant portability.

The system also depends on estimator quality. RF-T and RF-A have 7.14% and 9.56% MAPE, the layer-classifier reaches 87-93% accuracy, and the model-classifier 84-92%. The authors tie part of the gap to Oracle to those errors, and note that wrong model-classifier predictions can make Flex-RL+ 9% slower and 4.6% less accurate than Oracle. The RL policy is also best-effort rather than a hard guarantee.

Finally, the cleanest baseline is MLMP. Several other comparisons adapt model-selection systems by randomly splitting layers across CPU and LCA, so those deltas are less apples-to-apples. The paper also stays within three Android devices, leaving broader portability open.

## Related Work

- _Tan and Cao (IPSN '21)_ - MLMP also partitions DNN execution across CPU and NPU, but it uses static schedules and limited search, whereas Flex makes the assignment input-aware and communication-aware.
- _Wan et al. (ATC '20)_ - ALERT selects among multiple models to satisfy latency, accuracy, and energy goals, while Flex keeps one model and changes its execution plan across CPU and LCA.
- _Guo et al. (NSDI '21)_ - Mistify picks compressed model variants for resource-constrained devices; Flex instead tries to recover better latency/accuracy tradeoffs from one model by changing where layers run.
- _Kim et al. (EuroSys '19)_ - `μLayer` cooperatively executes on-device inference across CPU and GPU, but Flex adds explicit modeling of accelerator-induced accuracy loss and per-input scheduling under user-specified constraints.

## My Notes

<!-- empty; left for the human reader -->

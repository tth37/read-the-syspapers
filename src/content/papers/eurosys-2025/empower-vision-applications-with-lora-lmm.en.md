---
title: "Empower Vision Applications with LoRA LMM"
oneline: "VaLoRA packs domain knowledge into a small set of LoRA adapters, batches them with adaptive tiling, and switches modes in under 10 ms to serve vision tasks on one LMM."
authors:
  - "Liang Mi"
  - "Weijun Wang"
  - "Wenming Tu"
  - "Qingfeng He"
  - "Rui Kong"
  - "Xinyu Fang"
  - "Yazhu Dong"
  - "Yikang Zhang"
  - "Yuanchun Li"
  - "Meng Li"
  - "Haipeng Dai"
  - "Guihai Chen"
  - "Yunxin Liu"
affiliations:
  - "State Key Laboratory for Novel Software Technology, Nanjing University"
  - "Institute for AI Industry Research (AIR), Tsinghua University"
  - "Shanghai AI Laboratory"
  - "Beijing Academy of Artificial Intelligence (BAAI)"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717472"
code_url: "https://github.com/mi150/VaLoRA"
tags:
  - llm-inference
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

VaLoRA makes one LMM practical for several vision tasks by generating only as many LoRA adapters as accuracy constraints require, batching heterogeneous adapters with an adaptive GPU kernel, and switching execution modes in under 10 ms. Across five tasks on three LMMs, it reports 24-62% accuracy gains over the untuned base model and 20-89% lower latency than prior LoRA-serving systems.

## Problem

Vision applications still rely on many narrow models for detection, QA, captioning, and video understanding. LMMs offer a better language interface and broader reasoning, but on domain-specific workloads they often lag those specialized models, so external knowledge has to be injected with LoRA.

That creates three coupled systems issues. One adapter per task wastes capacity and makes runtime management messy, but fusing too many domains into one adapter hurts accuracy. Serving multiple applications also means running heterogeneous adapters together; the paper measures 27-140 ms of extra latency for prior unmerged systems. And because video analytics prefers low latency while visual retrieval prefers throughput, mode switching matters, yet dLoRA-style switching can cost more than 53 ms per transition.

## Key Insight

The paper's key idea is to treat LoRA generation and LoRA serving as one end-to-end optimization. Offline, the system should pack as much external knowledge as possible into each adapter without crossing task-specific accuracy floors. Online, it should stay in merged mode whenever possible, but use a much cheaper kernel and scheduling path when heterogeneous adapters or starving requests force a change.

A second insight is that many vision tasks do not need autoregressive text generation at all. If the output is a bounded label set, the adapter can carry a small task head and skip multiple decode rounds entirely.

## Design

VaLoRA has three main components. The offline generator collects labels from domain datasets or from existing small models and greedily fuses them into one adapter until some task drops below its accuracy target; then it rolls back that last step and starts a new adapter. The ideal problem is a constrained bin-packing problem, but the implementation uses this heuristic because the exact version is impractical. For fixed-output tasks, the same adapter can also include a trainable vision task head.

Its runtime path centers on ATMM, an adaptive-tiling matrix multiplication kernel for unmerged inference. Instead of using one static tiling like Punica or S-LoRA, VaLoRA profiles input-shape/tiling pairs offline, stores the best configuration in a hash table, and dispatches the matching precompiled kernel at runtime. Double buffering overlaps data movement and compute, which reduces both padding waste and SM underutilization.

The orchestrator then chooses among merged, unmerged, and a mixed mode called deLoRA. The fast switcher keeps only the LoRA factors `A` and `B` resident, uses contiguous memory, and computes all-layer `ΔW` in one shot, cutting switch time below 10 ms. deLoRA keeps one hot adapter merged into the base model while other requests run through a correction branch that subtracts the merged adapter and adds the requested one, so cold requests do not wait for a full switch.

## Evaluation

Experiments use Qwen-VL-7B, LLaVA-1.5-7B, and LLaVA-1.5-13B on an A100-80GB server. Workloads cover visual retrieval on ShareGPT-4V and RefCOCO, plus video analytics on YODA, Cityscapes, and UCF101; baselines are Punica, S-LoRA, and dLoRA.

The main latency results are strong: for visual retrieval, VaLoRA reduces average token latency by 72%, 50%, and 20% versus dLoRA, Punica, and S-LoRA; for video analytics the reductions are 89%, 83%, and 71%, mostly because the task head removes autoregressive decoding. On accuracy, LoRA-adapted Qwen-VL improves the untuned base model by 24.5-62.2% on domain-heavy tasks, and the paper reports 4.3-5% gains over specialized small models on visual QA and image captioning. The component studies also match the mechanism: the task head cuts latency by 41-63%, ATMM is 2.3-3.4x faster than competing operators, and throughput scales from 6.07 req/s on one A100 to 23.97 req/s on four.

## Novelty & Impact

VaLoRA's novelty is the combination: adapter generation, adaptive GPU batching, fast mode switching, and mixed-mode scheduling in one vision-oriented serving stack. Earlier LoRA-serving systems mostly targeted text LLMs or optimized only one part of the path.

The paper should matter to multimodal serving engines and multi-tenant LoRA systems. Its most practical lesson is that the cheapest way to serve many vision tasks is often to remove language generation when the task does not need it.

## Limitations

The paper's own caveats are important. Vision task heads only fit tasks with bounded outputs, so natural-language retrieval still uses the original LM head. Adapter generation is heuristic, and the authors explicitly note that fusion order and knowledge pre-clustering can change quality.

The evaluation is also narrower than the claim might suggest: most results are single-GPU, and the system comparison is against other LoRA-serving stacks rather than full production pipelines built from specialized vision models. Prefix caching is implemented but contributes less than 4% throughput.

## Related Work

- _Chen et al. (MLSys '24)_ - Punica batches heterogeneous LoRA adapters in unmerged mode, while VaLoRA argues that vision workloads need adaptive tiling and fast switching rather than always paying unmerged overhead.
- _Sheng et al. (MLSys '24)_ - S-LoRA also serves many concurrent adapters, but it stays in unmerged mode; VaLoRA adds ATMM, sub-10 ms switching, and a mixed execution mode.
- _Wu et al. (OSDI '24)_ - dLoRA introduces dynamic orchestration between merged and unmerged inference, and VaLoRA keeps that intuition but makes the switch much cheaper and adds deLoRA to reduce starvation.
- _Zhou et al. (ATC '22)_ - PetS serves parameter-efficient DNN variants, but not autoregressive multimodal LMMs, so it misses the batching, tiling, and scheduling issues VaLoRA targets.

## My Notes

<!-- empty; left for the human reader -->

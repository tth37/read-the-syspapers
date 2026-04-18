---
title: "Efficient Temporal Graph Network Training via Unified Redundancy Elimination"
oneline: "PULSE speeds TGN training by deduplicating batch inputs, reconstructing raw messages on demand, and recycling GPU buffers around temporal reuse."
authors:
  - "Yiqing Wang"
  - "Hailong Yang"
  - "Kejie Ma"
  - "Enze Yu"
  - "Pengbo Wang"
  - "Xin You"
  - "Qingxiao Sun"
  - "Chenhao Xie"
  - "Zhongzhi Luan"
  - "Yi Liu"
  - "Depei Qian"
affiliations:
  - "Beihang University, State Key Laboratory of Complex & Critical Software Environment, Beijing, China"
  - "Beihang University, Beijing, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790157"
code_url: "https://doi.org/10.5281/zenodo.17945819"
tags:
  - graph-processing
  - ml-systems
  - gpu
  - memory
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PULSE treats TGN training as one redundancy problem spanning computation, message storage, and data loading. It keeps only minimal inputs, minimal stored state, and minimal reusable GPU blocks, then reconstructs everything else exactly by indexing rather than recomputation. On four datasets and two TGN-style models, that unified design improves throughput by up to `6.67x` with no accuracy loss.

## Problem

The paper studies continuous-time TGNs, where each batch samples timestamped neighborhoods, loads node memory and raw messages, runs memory update plus temporal attention, and writes state back. That pipeline repeats the same logical information in multiple forms. Sampled rows often share node IDs, edge IDs, or timestamps, raw messages duplicate recoverable state, and cross-batch feature reuse is real but irregular.

Prior systems tackle only pieces of this. ETC and TGLite reduce some access or loading redundancy, and TGOpt focuses on inference-time attention. The authors argue that this is too local: redundant raw-message storage steals GPU space from caching, and redundant computation increases data movement. On `wiki-talk`, they measure component-level intra-batch redundancy between `0.5147` and `0.9789`, raw-message-store redundancy averaging `0.8682`, and inter-batch node/edge reuse commonly around `0.3-0.4`. The end-to-end question is how to remove that repeated work without changing TGN semantics.

## Key Insight

The key claim is that redundancy should be removed at the smallest semantically necessary unit in each stage: Minimal Input Units (MIUs) for computation, Minimal Storage Units (MSUs) for persisted messages, and Minimal Reuse Units (MRUs) for GPU memory. Once the pipeline is expressed in those units, most eliminated data can be reconstructed exactly with inverse maps, dependency counters, and buffer indirection.

This matters because row-wise deduplication is too coarse. PULSE splits the path into reusable components, lets redundancy propagate through row-wise operators, and stops only when aggregation truly couples rows.

## Design

PULSE's computation path starts with a hybrid offline/online deduplication scheme. Positive targets are stable across epochs, so they are deduplicated once offline; negative targets are deduplicated online and merged into the same unique set. That MIU then feeds Operator-Level Reconstruction: row-wise sub-operators are deduplicated independently, and full temporal-attention `Q/K/V` rows are materialized only when later multiplies require them.

For storage, PULSE keeps only the MSU: outdated node-memory entries that are still needed because some raw messages reference them and cannot yet be refreshed. Instead of tracking every dependency explicitly, it maintains lightweight reference counters for updated and outdated entries. On each batch, it spills only still-referenced old states into freed slots and reconstructs the rest on demand.

For loading, PULSE reserves a software-managed GPU buffer and partitions it into fixed-size MRUs chosen to reduce fragmentation across node features, edge features, time encodings, and memory states. A BlockPool allocator manages the space. The reuse policy is bipartite: node-indexed data stay resident when memory permits, while much larger edge features are cached in a sliding temporal window. The paper finds stride `10` gives the best miss-rate versus replacement-cost tradeoff.

## Evaluation

The evaluation uses one server with an Intel Xeon Gold 6336Y CPU and one `A100 40GB` GPU. The models are TGN and TGAT under four configurations that vary batch size (`2000` or `6000`) and layer count (`1` or `2`). The datasets are `lastfm`, `wiki-talk`, `stackoverflow`, and `gdelt`; baselines are ETC and TGLite.

PULSE wins everywhere: average speedups are `2.37x` over ETC and `3.28x` over TGLite, with a maximum of `6.67x` over ETC on `wiki-talk` under `C4`. ETC also runs out of memory in the 2-layer settings `C2` and `C4`, while PULSE continues training because it lowers both persistent storage and peak attention memory. Mechanistically, PULSE cuts host-to-device traffic by `64.23%` and the number of processed temporal-operator elements by `68.91%` on average. The largest end-to-end gains come from memory-state management (`+134.3%`) and edge-feature management (`+106.4%`). Accuracy is unchanged across all datasets and configurations, with matching AP/AUC to the baselines. That makes the evaluation convincing for single-GPU TGN training, even if it does not yet prove portability beyond that regime.

## Novelty & Impact

Relative to _Gao et al. (VLDB '24)_, PULSE does not stop at access scheduling; it joins computation, storage, and loading under one exact-reconstruction framework. Relative to _Wang and Mendis (ASPLOS '24)_, it is a deeper runtime redesign than TGLite. Relative to _Wang and Mendis (PPoPP '23)_, it shifts the redundancy idea from TGAT inference to full training-time state management.

The paper will likely matter to future GPU-based graph-learning systems because its main contribution is a reusable systems principle: organize TGN training around irreducible state and recover everything else just in time.

## Limitations

The paper evaluates only TGN and TGAT on a single `A100 40GB` server, so portability to newer accelerators or distributed multi-GPU training is still open. Its offline positive-target preprocessing costs about `1.5x` one epoch and is excluded from end-to-end timing, which is fair for long runs but less so for short jobs. The cache policy also depends on workload-sensitive choices such as stride and reserved buffer size, and richer future TGN variants may make exact reconstruction harder than in the current message format.

## Related Work

- _Gao et al. (VLDB '24)_ — ETC reduces redundant accesses and overlaps some pipeline stages, but it does not remove component-wise computation redundancy or raw-message duplication across the whole training stack.
- _Wang and Mendis (ASPLOS '24)_ — TGLite provides a lightweight framework for continuous-time temporal GNNs, whereas PULSE is a deeper runtime redesign with exact reconstruction and custom GPU memory management.
- _Wang and Mendis (PPoPP '23)_ — TGOpt studies redundancy-aware optimization for temporal graph attention inference; PULSE borrows the redundancy theme but extends it to training-time storage and loading.
- _Dai et al. (ASPLOS '25)_ — Cascade improves large-batch TGN training via dependency-aware handling of scattered events, while PULSE focuses on eliminating redundant work inside the standard training pipeline itself.

## My Notes

<!-- empty; left for the human reader -->

---
title: "AdaCheck: An Adaptive Checkpointing System for Efficient LLM Training with Redundancy Utilization"
oneline: "AdaCheck models tensor-level redundancy across parallelisms and iterations, then checkpoints only irreducible state and gradient deltas to make per-step LLM checkpoints practical."
authors:
  - "Weijie Liu"
  - "Shengwei Li"
  - "Zhiquan Lai"
  - "Keshi Ge"
  - "Qiaoling Chen"
  - "Peng Sun"
  - "Dongsheng Li"
  - "Kai Lu"
affiliations:
  - "National Key Laboratory of Parallel and Distributed Computing, College of Computer Science and Technology, National University of Defense Technology"
  - "Nanyang Technological University"
  - "Shanghai AI Laboratory"
conference: fast-2026
category: ai-era-storage
code_url: "https://github.com/HPDL-Group/Merak"
tags:
  - llm-training
  - fault-tolerance
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

AdaCheck treats checkpoint minimization as a redundancy-analysis problem rather than an I/O scheduling problem. It identifies the irreducible parameter and optimizer states across arbitrary LLM parallel plans, then replaces many full saves with gradient deltas. Across dense and sparse models, it cuts checkpoint size by `6.00–896×`, enables per-iteration checkpointing, and adds almost no training-throughput overhead.

## Problem

Long LLM training runs fail often, so rollback cost matters. The authors cite the `54`-day training of `LLaMA 3.1` on `16K` GPUs, which saw `419` failures and roughly `2M` GPU hours of wasted work. Existing systems optimize the wrong boundary: `CheckFreq` reduces stalls but still assumes a complete model replica must reach persistent storage, while `GEMINI` uses the training network but still saves local state without asking whether those tensors are duplicated elsewhere.

That is especially wasteful when training mixes `DP`, `ZeRO`, model parallelism, expert parallelism, and irregular auto-generated plans. Naive replica counting is also unsafe, because recovery depends on replica placement and a parameter can be redundant while its optimizer state is not. The real problem is therefore to shrink checkpoints without baking in a specific parallelism and without losing resumability.

## Key Insight

AdaCheck's core claim is that checkpoint necessity is a tensor-distribution property, not a whole-model property. It defines `tensor redundancy` as the worker and tensor-index locations that hold a tensor's replicas, derives full, partial, and no redundancy from that representation, and then intersects parameter redundancy with optimizer-state redundancy. The second insight is temporal: in mixed-precision training, adjacent checkpoints often differ mainly by the half-precision gradient, so once the system knows which states must survive, it can often store gradients instead of full states.

## Design

AdaCheck has offline and online stages. Offline, it classifies state as full, partial, or non-redundant, intersects parameter and optimizer-state redundancy, and uses a failure-tolerance factor `k` to decide when partially replicated state is still safe to omit. To compute this cheaply, a startup detector hashes local tensors, compares only within the communication groups that already synchronize replicas, removes overlapping subgroup work, and uses a ring-style algorithm so communication and comparison overlap. By intersecting results from two iterations, it filters both hash collisions and transient equalities; the detector finishes within `3` minutes on `128` workers.

Online checkpointing exploits cross-iteration redundancy. In mixed-precision Adam training, parameters occupy `2M` bytes and optimizer states `12M`, so a full checkpoint is `14M`. AdaCheck saves parameters directly when only parameters matter, but otherwise saves associated gradients, reducing the cost to `1/6` when only optimizer state must be preserved and to `1/7` when both parameter and optimizer state are represented by the gradient. These reduced checkpoints go to remote CPU memory inside groups aligned with model parallel structure so transfer can overlap with training. A modified remote CPU optimizer applies gradients as they arrive, and non-blocking full checkpoints remain as a catastrophe fallback.

## Evaluation

The evaluation uses two clusters: `32` `A800 80G` GPUs with `800 Gbps` training bandwidth, and `128` `RTX 3090` GPUs with `100 Gbps` training bandwidth. It spans `LLaMA-7B`, `LLaMA-30B`, `DeepSeek-V2-Lite`, `GPT-1.4B`, `GPT-7B`, and `GPT-MoE`, plus `ZeRO`, `MiCS`, `EP`, and auto-generated plans from `nnScaler`, which is broad enough to test the paper's adaptability claim.

Relative to `CheckFreq` and `GEMINI`, AdaCheck reduces checkpoint size by `6.00–896×`. The ablation shows that offline redundancy elimination alone gives `1.30–240×` smaller checkpoints than `GEMINI`, and the online method adds up to another `7.09×` reduction. More importantly, AdaCheck enables checkpointing every iteration and raises checkpoint frequency by `36.2–111×` over `CheckFreq` and `1.46–3.64×` over `GEMINI`. On sparse models, average wasted time per failure drops by `12.1–88.93×` relative to `CheckFreq` and `1.73–4.51×` relative to `GEMINI`. Iteration-time overhead is almost negligible, and at higher simulated failure rates effective throughput improves by up to `1.12×` over `GEMINI`. The main caveat is that `GEMINI` is reimplemented because the original system is closed-source.

## Novelty & Impact

AdaCheck combines two forms of redundancy exploitation that earlier systems separate or ignore. Compared with `CheckFreq`, it changes what must be checkpointed rather than only when bytes move. Compared with `GEMINI`, it adds replica-aware state elimination and gradient-based cross-iteration checkpoints on top of remote-memory transport. That makes it relevant to LLM training frameworks and auto-parallel systems that need one checkpoint mechanism across many layouts. The `Merak` integration supports the claim that the design is meant as reusable infrastructure.

## Limitations

AdaCheck detects redundancy only at startup, so dynamic re-planning or elastic worker membership would likely require rerunning the detector. Fast recovery is also probabilistic once simultaneous failures exceed the configured group size `k`, which is why the system still needs full checkpoints as a fallback. Finally, the evaluation reaches `128` GPUs rather than the `1K–16K` scales used as motivation, and one key baseline (`GEMINI`) is reimplemented instead of run from an original artifact.

## Related Work

- _Mohan et al. (FAST '21)_ — `CheckFreq` overlaps checkpoint I/O with training, but still assumes at least one complete model must be saved to persistent storage.
- _Wang et al. (SOSP '23)_ — `GEMINI` moves checkpoints to remote CPU memory over the training network, while AdaCheck additionally removes redundant state and uses gradient-based incremental checkpoints.
- _Gupta et al. (EuroSys '24)_ — Just-in-time checkpointing creates checkpoints only after failures using existing replicas, whereas AdaCheck preserves non-redundant state proactively and remains usable beyond pure replica-based recovery.
- _Jiang et al. (NSDI '25)_ — `ByteCheckpoint` optimizes the checkpointing pipeline for foundation models, while AdaCheck focuses on minimizing the checkpoint contents themselves across parallelisms and iterations.

## My Notes

<!-- empty; left for the human reader -->

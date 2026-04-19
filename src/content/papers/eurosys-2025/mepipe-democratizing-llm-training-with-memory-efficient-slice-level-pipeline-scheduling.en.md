---
title: "MEPipe: Democratizing LLM Training with Memory-Efficient Slice-Level Pipeline Scheduling on Cost-Effective Accelerators"
oneline: "MEPipe trains LLMs on 24 GB RTX 4090s by slicing each sequence and interleaving slice-level pipeline work to cut activation memory without extra communication."
authors:
  - "Zhenbo Sun"
  - "Shengqi Chen"
  - "Yuanwei Wang"
  - "Jian Sha"
  - "Guanyu Feng"
  - "Wenguang Chen"
affiliations:
  - "Tsinghua University"
  - "Zhipu AI"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717469"
project_url: "https://zenodo.org/records/14942680"
tags:
  - llm-training
  - gpu
  - memory
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

MEPipe targets an awkward hardware tier for LLM training: cheap GPUs such as RTX 4090 that have strong raw FLOPS but only 24 GB of memory and much weaker interconnects than A100-class systems. Its core move is Sequence Virtual Pipeline Parallelism (SVPP), which schedules pipeline work at slice granularity so the system preserves activations for a few slices rather than whole micro-batches, then fills remaining bubbles with fine-grained weight-gradient GEMMs. On 64 RTX 4090s, the paper reports up to 1.68x speedup over prior approaches, 35% MFU on Llama 13B, and comparable iteration time to a 32-A100 cluster at 2.5x better cost effectiveness.

## Problem

The paper starts from a real economic constraint. A server with 8 A100s and NVLink cost roughly 5x as much as a server with 8 RTX 4090s in the authors' October 2024 pricing snapshot, yet the 4090 has similar FP16 peak FLOPS. The catch is that the cheaper card loses on exactly the resources LLM training usually depends on: memory capacity and communication bandwidth. That makes the standard recipe for large-model training a poor fit.

Tensor parallelism and context parallelism both reduce per-device memory by slicing model state or sequence state, but they pay for that with per-layer communication during forward and backward passes. On PCIe-connected 4090s, that communication is expensive enough to erase much of the benefit. Pipeline parallelism is more attractive because it communicates only between stages, but the classic schedules still require the early stages to hold activations for many forward passes before the first backward pass can start. That activation footprint is exactly what a 24 GB card cannot afford.

The closest apparent fix, TeraPipe-style sequence pipeline parallelism, also falls short. It slices each sample into smaller sequence fragments, which reduces bubble ratio and shrinks per-slice activations, but its schedule still runs all forward passes before the first backward pass. The result is that workers keep too many activations live at once. MEPipe therefore asks for something stricter than lower communication or lower bubble ratio in isolation: can a pipeline schedule reduce activation memory enough for commodity accelerators without introducing new communication overhead?

## Key Insight

The main insight is that the right scheduling unit is not the micro-batch but the sequence slice, and the right optimization target is not just bubble ratio but the number of live slices before the first backward pass. If the runtime interleaves forward and backward computation as soon as slice dependencies permit, the activation footprint can scale with a small number of slices rather than a long prefix of full samples.

That is not enough by itself, because sequence slicing introduces two new complications. First, later slices are computationally heavier than earlier ones in decoder-only models because their attention layers depend on more preceding keys and values. Second, once the model is also partitioned into virtual pipeline chunks, the dependency structure becomes nontrivial. MEPipe's second insight is that these problems can be handled separately: use SVPP to construct a legal, low-memory slice schedule, then use fine-grained weight-gradient scheduling to absorb the remaining imbalance and tail bubbles.

## Design

MEPipe is built on Megatron-LM and has three components: a profiler, an SVPP scheduler, and an execution engine. The profiler measures forward and backward time plus memory consumption for the target model and hardware. The scheduler then chooses a schedule from five parameters: pipeline stages `p`, virtual pipeline size `v`, sequence pipeline size `s`, number of micro-batches `n`, and how many forward passes happen before the first backward pass.

SVPP generalizes ordinary pipeline scheduling in two directions at once. Like sequence pipeline parallelism, it partitions each sample into slices. Like virtual pipeline parallelism, it can split the model into finer chunks and assign multiple chunks to a worker. The scheduler then interleaves slice-level forward and backward passes while respecting causal-attention dependencies: a later slice in one stage depends on both the earlier slice in the same stage and the matching slice from the preceding stage.

The paper's key practical contribution is that it generates several legal SVPP variants with different memory and bubble tradeoffs, then picks the cheapest one that fits the device memory budget. Its memory model combines static memory for parameters, gradients, and optimizer state; temporary operator workspace; and live activation memory. This matters because the best schedule is hardware-dependent. A memory-rich device can start more forward passes early to reduce bubbles, while a 4090-class device may need to delay some forward work until after the first backward pass.

MEPipe then attacks the second bottleneck, slice imbalance. In decoder models, later slices spend more time in attention-score computation. Borrowing the zero-bubble idea of separating activation-gradient and weight-gradient work, MEPipe goes one step finer and decomposes weight-gradient computation into individual GEMMs. During backpropagation those GEMMs are enqueued, then opportunistically executed when a stage would otherwise wait for tensors from neighboring stages. That both smooths cross-slice imbalance and turns communication gaps into useful work.

## Evaluation

The evaluation runs on 8 servers with 8 RTX 4090 24 GB GPUs each, PCIe 4.0 within a node, and 100 Gbps InfiniBand across nodes. The workloads are Llama 2 models with 7B, 13B, and 34B parameters. The baselines are strong and were tuned seriously: DAPPLE, VPP, Zero Bubble, and ZBV, with exhaustive search over PP, CP, VP, and recomputation settings where applicable.

The headline result is that MEPipe wins specifically in the low-memory, low-bandwidth regime it targets. Across the evaluated Llama settings, it reports up to 1.68x speedup and 1.35x average speedup over prior approaches on 64 RTX 4090s. On Llama 13B, it reaches 35% MFU and 116 TFLOPS peak performance. The paper also shows why the improvement appears: compared with prior schedules, SVPP cuts peak activation memory by more than 70% at sequence-pipeline size 4 and more than 80% at size 8 in the motivating analysis.

The comparisons are also fairly informative. DAPPLE often needs context parallelism or recomputation to fit memory, which raises communication or compute cost. VPP and ZBV reduce warmup and drain bubbles, but extra chunks increase static memory and can cap feasible pipeline depth. MEPipe avoids both penalties by reducing activation memory through scheduling itself. The fine-grained weight-gradient mechanism adds another 9.4% performance improvement over the same schedule without that mechanism.

The paper's A100 comparison is less about absolute speed than economics. A 64-RTX-4090 cluster achieves iteration times comparable to a 32-A100 cluster on the same Llama models, despite each 4090 delivering only about half an A100's realized throughput in their implementation. Because the server price ratio is roughly 1:5, the authors argue the resulting setup is still 2.5x more cost effective.

## Novelty & Impact

The novelty is not just "use cheaper GPUs" or "slice the sequence." Prior work already offered low-bubble pipeline schedules, virtual chunks, recomputation, and sequence slicing. MEPipe's contribution is to combine those ideas around a sharper objective: minimize activation residency on bandwidth-poor accelerators without paying the communication tax of TP or CP. SVPP is the centerpiece because it makes slice-level scheduling memory-aware instead of treating lower bubble ratio as the only goal.

That makes the paper relevant beyond RTX 4090 clusters. Anyone designing LLM training systems for constrained accelerators, PCIe-only servers, or future low-cost training hardware can reuse the formulation: first model memory precisely enough to choose a legal slice schedule, then use deferred gradient work to reclaim the bubbles left by dependency and imbalance. The result is a systems paper with a real deployment thesis, not just a scheduling curiosity.

## Limitations

MEPipe is specialized. Its scheduling logic assumes decoder-style causal attention, where later slices depend on earlier ones in a structured way; the paper does not explore encoder-decoder or more irregular architectures. Its evaluation is also throughput-centric: the experiments run for 100 iterations and focus on iteration time, MFU, and memory fit, so the paper does not present a full end-to-end pretraining study showing final model quality under the new schedule.

The design also trades on careful tuning. The authors rely on profiling and grid search to find the best PP, CP/SPP, VP, and schedule variant, and they explicitly call out the search cost as a limitation. In addition, very large SPP sizes eventually hurt GEMM and FlashAttention efficiency, so the schedule cannot reduce bubbles arbitrarily without paying an operator-level penalty.

Finally, the hardware story is not free. The paper itself notes reliability concerns for thousand-GPU 4090 clusters, FP16 overflow and underflow issues, and higher power draw than A100 clusters with similar aggregate compute. MEPipe makes cheap accelerators more plausible for LLM training, but it does not eliminate the operational challenges of building large clusters from them.

## Related Work

- _Fan et al. (PPoPP '21)_ - DAPPLE popularized 1F1B pipeline scheduling, while MEPipe goes further by reducing the number of live activations through slice-level rather than micro-batch-level scheduling.
- _Li et al. (arXiv '21)_ - TeraPipe introduced sequence pipeline parallelism, but MEPipe argues TeraPipe's all-forward-then-backward schedule still keeps too many activations resident on memory-limited GPUs.
- _Qi et al. (ICLR '24)_ - Zero Bubble pipeline parallelism defers weight-gradient work to fill tail bubbles, and MEPipe extends that idea to individual GEMMs so it can also smooth slice-level imbalance.
- _Sun et al. (ASPLOS '24)_ - AdaPipe uses adaptive recomputation and repartitioning to survive stage-wise memory imbalance, whereas MEPipe tries to avoid recomputation overhead by choosing a lower-memory schedule in the first place.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Mercury: Unlocking Multi-GPU Operator Optimization for LLMs via Remote Memory Scheduling"
oneline: "Mercury treats remote GPU memory as schedulable storage, then auto-searches shift, shard, and collective schedules for faster multi-GPU LLM operators."
authors:
  - "Yue Guan"
  - "Xinwei Qiang"
  - "Zaifeng Pan"
  - "Daniels Johnson"
  - "Yuanwei Fang"
  - "Keren Zhou"
  - "Yuke Wang"
  - "Wanlu Li"
  - "Yufei Ding"
  - "Adnan Aziz"
affiliations:
  - "University of California, San Diego"
  - "Meta"
  - "George Mason University"
  - "OpenAI"
  - "Rice University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764798"
code_url: "https://github.com/ChandlerGuan/mercury_artifact"
tags:
  - gpu
  - compilers
  - memory
  - llm-training
  - llm-inference
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mercury is a multi-GPU operator compiler for LLM attention and GEMM that treats remote GPU memory as an explicitly scheduled storage tier rather than as a side effect of communication. Its CommIR intermediate representation lets the compiler search over shifts, sharding, replication, and collectives in one space, allowing it to match or beat manual designs such as RingAttention, Ulysses, and USP.

## Problem

The paper starts from a practical scaling failure: important LLM operators no longer fit cleanly on one GPU. Long-context attention can require hundreds of gigabytes of memory, and even the KV cache for Llama-3 70B is cited at 282 GB, well beyond one H100's 80 GB HBM. Multi-GPU execution is therefore mandatory, but the best known implementations are mostly handcrafted and tightly coupled to specific model shapes, GPU counts, and interconnects.

Existing compilers fall short because they assume a local-memory-centric execution model. In that model, every GPU first gathers the needed input into its own HBM, then executes a largely synchronous schedule. Shared inputs are duplicated, communication is treated mainly as a way to exchange intermediate results, and the compiler has little room to explore more aggressive overlap or lower-memory layouts. That is why recent long-context systems have resorted to ad hoc asynchronous designs such as ring or multi-level shifts: the useful schedules exist, but current compiler abstractions cannot express them as first-class choices.

## Key Insight

Mercury's central claim is that remote GPU memory should be modeled as part of the memory hierarchy, not as an external transport service. Once the compiler can treat another GPU's memory as schedulable storage, it can intentionally stagger when each worker accesses shared data, keep less state in local HBM, and trade communication against storage and locality in a principled way.

That shift in viewpoint matters because it unifies several decisions that prior systems split apart. A loop schedule now determines not only who computes what, but also which buffers are sharded or replicated, whether accesses should be synchronous or shifted in time, and whether the resulting data movement should lower to point-to-point communication or to collectives. The paper's thesis is that a compiler needs one representation spanning compute, memory, and communication if it wants to recover known expert schedules and discover new ones.

## Design

Mercury introduces CommIR, a loop-based IR built around standard computation transformations such as `tile`, `join`, `reorder`, and `patch`, plus four communication-aware primitives: `parallelize`, `shift`, `shard`, and `replicate`. `parallelize` maps a loop to a level of the hardware mesh and gives the compiler a default placement rule: buffers indexed by that loop are sharded, while unrelated buffers are replicated. `shift` offsets a local loop by a parallel loop, turning synchronous access into staggered remote-memory access. Multi-level shifts let the same operator distinguish intra-node from inter-node communication. `shard` and `replicate` annotate buffer layouts explicitly so the lowering pass can infer whether a given schedule should become `AllGather`, `Broadcast`, `AllReduce`, `ReduceScatter`, or fall back to point-to-point sends and receives.

The pipeline is DSL to CommIR to search to lowering. Users describe an operator in a Python-like DSL; Mercury parses it into CommIR; transformation passes generate candidate computation schedules first and communication schedules second; then the backend lowers local compute to TorchInductor and optionally patches subgraphs with optimized kernels such as FlashAttention. The tuner prunes candidates whose inferred memory footprint exceeds device capacity and profiles the rest on real hardware. In the paper's experiments, this search takes about 10 minutes per operator. Mercury also adds graph-level search across an operator DAG so it can choose per-operator schedules jointly with resharding costs instead of optimizing each operator in isolation.

## Evaluation

The evaluation uses H100, A100, and L4 clusters, with NVLink or PCIe inside nodes and RoCE between nodes. Mercury is implemented with CUDA 12.6, NCCL 2.26.2, TorchInductor from PyTorch 2.8, and is tested on Llama-3-style attention and GEMM operators under batch sizes 1 to 16 and sequence lengths from 4K to 2M tokens. The baselines are strong and relevant: RingAttention, DeepSpeed-Ulysses, USP, AsyncTP, cuBLAS collectives, and TorchInductor's own multi-GPU templates.

The headline result is consistency. Mercury is the fastest system in every operator benchmark the paper reports. For attention, it reaches up to 4x speedup on H100 MHA at batch size 16 and beats both Ulysses and USP across MHA and GQA, especially when topology or head structure makes fixed templates brittle. For GEMM, where the design space is more regular, the gains are smaller but still meaningful: Mercury reaches up to 1.9x speedup on AllGather-GEMM on A100 at batch size 16 by breaking collectives into finer-grained overlapped schedules.

The paper also tests the thesis that topology-aware search matters. Across varied 4 GPU, 8 GPU, and 16 GPU layouts, Mercury reports an average 2.91x speedup and is strongest on mixed hierarchical topologies such as 2x4 or 4x2, where single-pattern manual methods struggle. On long-context attention, Mercury remains ahead as sequence length scales to 2M tokens and is the only evaluated approach that still finds a feasible schedule at 2M; the baselines run out of memory there. At the model level, Mercury's graph-aware operator choices improve one Llama-3 transformer layer by up to 1.62x over the best 3D-parallel baseline by reducing both operator latency and inter-operator resharding overhead. Overall, the experiments support the main claim: remote-memory-aware schedules matter most when memory pressure and topology complexity are high.

## Novelty & Impact

Mercury's novelty is not merely broader autotuning. It gives multi-GPU operator compilation a representation in which asynchronous remote-memory access, collective synthesis, and local tensor scheduling live in the same search space. That makes the paper a real systems contribution rather than a collection of templates. For people building distributed LLM runtimes, the practical message is that future performance gains will come from compiler support for hybrid memory-and-communication schedules, not only from hand-writing another specialized attention kernel for the next topology.

## Limitations

The paper's search strategy is empirical and hardware-in-the-loop, so compile time is not trivial. Ten minutes per operator is acceptable for the evaluated workloads, but the paper itself notes that search cost may rise with more complex operators and larger device meshes. The system also focuses on static operators; ragged tensors, MoE routing, and fused compute-communication kernels are left as future work.

There is also a deployment boundary. Mercury uses its own DSL and lowers mainly through TorchInductor plus selected patched kernels, so integrating the approach into other compiler stacks would require engineering work. Finally, the model-level study evaluates one transformer layer rather than full end-to-end serving or training runs, which is enough to show the resharding benefit but leaves some full-system questions open.

## Related Work

- _Liu et al. (ICLR '24)_ - RingAttention introduces shift-based long-context attention, but it hard-codes a universal ring rather than searching topology-aware multi-level shift schedules.
- _Jangda et al. (ASPLOS '22)_ - CoCoNet breaks the usual barrier between computation and communication, yet its search space remains centered on synchronous collective patterns instead of Mercury's asynchronous remote-memory schedules.
- _Zheng et al. (OSDI '22)_ - Alpa automates inter- and intra-operator parallelism with template-driven decompositions, whereas Mercury searches lower-level operator schedules and remote-memory placement inside each operator.
- _Chen et al. (ASPLOS '24)_ - Centauri improves communication-computation overlap for large-model training, while Mercury contributes a general loop IR that can synthesize both collective and point-to-point schedules for attention and GEMM.

## My Notes

<!-- empty; left for the human reader -->

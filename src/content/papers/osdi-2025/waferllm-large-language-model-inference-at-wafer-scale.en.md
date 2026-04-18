---
title: "WaferLLM: Large Language Model Inference at Wafer Scale"
oneline: "WaferLLM maps prefill, decode, and KV-cache management onto wafer-scale mesh accelerators with PLMR-aware parallelism, MeshGEMM, and MeshGEMV."
authors:
  - "Congjie He"
  - "Yeqi Huang"
  - "Pei Mu"
  - "Ziming Miao"
  - "Jilong Xue"
  - "Lingxiao Ma"
  - "Fan Yang"
  - "Luo Mai"
affiliations:
  - "University of Edinburgh"
  - "Microsoft Research"
conference: osdi-2025
code_url: "https://github.com/MeshInfra/WaferLLM"
tags:
  - llm-inference
  - hardware
  - memory
  - caching
category: llm-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

WaferLLM argues that a wafer-scale accelerator is not just a bigger GPU. It models the device as a mesh of tiny local-memory cores with extreme non-uniform access costs, then rebuilds LLM prefill, decode, GEMM/GEMV, and KV-cache management around that fact. On Cerebras WSE-2, the result is up to 10-20x higher end-to-end throughput than the best reported SGLang A100 cluster setup and 606x faster GEMV than a single A100.

## Problem

The paper targets the core bottleneck of LLM inference: decode is dominated by GEMV, so every generated token repeatedly pulls model weights through memory, making throughput fundamentally bandwidth-bound. Wafer-scale accelerators look like an ideal answer because they pack hundreds of thousands of cores, tens of GB of on-chip SRAM, and tens of PB/s of on-chip bandwidth onto one chip. But existing inference systems were built for shared-memory GPUs or TPU-style pods, where software can mostly ignore where data sits. On a wafer-scale mesh, that assumption breaks badly. Remote accesses can vary by up to 1,000x in latency, each core has only tens of KB to a few MB of local memory, and routing tables are tiny. A direct port of today’s LLM runtimes therefore wastes most of the hardware: it creates long-distance traffic, overuses routing resources, performs expensive transposes on the mesh, and skews KV-cache placement so a few cores become hotspots.

## Key Insight

The central claim is that wafer-scale inference should be designed around the hardware’s four first-order constraints, not hidden behind a fake shared-memory abstraction. The paper packages those constraints into the PLMR model: massive parallelism, highly non-uniform latency, constrained per-core memory, and limited routing resources.

Once inference is framed that way, the design direction becomes clear. Prefill should use much finer-grained partitioning than GPU tensor parallelism; decode should introduce replication where dimensions are too small to partition; communication primitives should minimize hop distance and routing fan-out rather than emulate allgather-heavy GPU algorithms; and KV cache placement must stay balanced across the mesh. That is what makes full single-chip inference practical.

## Design

WaferLLM splits the problem into prefill parallelism, decode parallelism, and KV-cache management. In prefill, it partitions both activations and weights across the X and Y axes of the wafer so attention and feed-forward GEMMs can exploit far more parallelism than GPU-style schemes that mostly shard only the embedding dimension. It then replaces standard distributed GEMM with MeshGEMM. MeshGEMM logically arranges tiles in a cycle, uses cyclic shifting for correctness, and applies an interleaving mapping so each step communicates only with two-hop neighbors. That keeps the critical path constant in hop count, bounds local memory usage, and respects the small routing budget. For the `QK^T` step, WaferLLM uses a transposed distributed GEMM so it avoids an explicit matrix transpose across the mesh.

Decode has the opposite problem: the sequence dimension is tiny, so naive sharding leaves too little work per core. WaferLLM therefore replicates the sequence dimension and repartitions weights for decode, then uses MeshGEMV instead of the usual pipelined or ring allreduce structure. MeshGEMV performs local GEMV on each core and aggregates partial sums with a K-tree allreduce; the implementation uses `K=2`, trading a few extra routing paths at tree roots for much lower critical-path latency than sequential reduce chains.

The KV cache design follows the same logic. Concatenate-style cache growth, which is natural on GPUs, causes one row of cores to absorb the newly generated vectors and quickly become the bottleneck. WaferLLM replaces that with shift-based management: rows push older KV entries upward to adjacent rows so storage and compute stay balanced. The runtime also pre-places weights differently for prefill and decode to eliminate repeated transposes, and it uses the wafer NoC to reshuffle between phases.

## Evaluation

The evaluation runs on Cerebras WSE-2, a wafer-scale chip with 850,000 cores, 40 GB of aggregate SRAM, 48 KB per core, and a 1.1 GHz compute engine. The paper compares WaferLLM against two adapted compiler baselines on the same hardware, T10 and Ladder, and against SGLang on up to 16 NVIDIA A100 GPUs.

The headline result is that the end-to-end system advantage is real, not just a microbenchmark artifact. For full LLaMA3-8B and LLaMA2-13B inference, WaferLLM is about 160x faster than T10 on average and hundreds of times faster than Ladder; against the best reported multi-GPU SGLang setting, it is 10-20x faster end to end and about 2-2.5x more energy efficient. The microbenchmarks explain why. MeshGEMM beats SUMMA and Cannon and keeps more than 70% computational efficiency near 720x720 cores, while the baselines fall below 50%. MeshGEMV is about 4.6x faster than Cerebras’s own pipeline-allreduce GEMV and 280-606x faster than a single A100 tensor-parallel GEMV. The KV-cache result is also striking: on the paper’s setup, shift-based placement supports 137,548 decode tokens for LLaMA3-8B versus 382 with concatenate-style management.

The evidence supports the paper’s thesis most strongly for decode, where bandwidth and communication dominate. The main caveat is that CodeLLaMA-34B and QWen2-72B are evaluated via scaled subsets of layers on one WSE-2 rather than full end-to-end runs.

## Novelty & Impact

Relative to _Liu et al. (SOSP '24)_, which introduced T10 for inter-core connected accelerators, WaferLLM treats mesh distance as a first-class constraint rather than assuming effectively uniform on-chip access. Relative to _Wang et al. (OSDI '24)_, which optimizes low-precision tensor programs for shared-memory devices, it argues that wafer-scale inference needs new parallel algorithms rather than a better compiler pass over GPU-like assumptions. Relative to _Luczynski et al. (HPDC '24)_, which studies wafer-scale reduce as a primitive, WaferLLM builds a full inference stack with phase-specific placement, GEMM, GEMV, and KV-cache management.

That combination makes the paper important beyond Cerebras specifically. Its real contribution is a systems argument: if wafer-scale accelerators matter, the software stack must expose topology, local memory, and routing limits instead of pretending the chip is monolithic. Future wafer- and mesh-scale inference systems will likely cite the PLMR framing even if they change the concrete kernels.

## Limitations

The paper is careful not to claim that the current WSE-2 reaches the hardware ideal. It identifies three reasons the measured gains are below the theoretical memory-bandwidth advantage: second-generation cores cannot fully overlap memory and compute, edge cores are underutilized, and long-range NoC communication still costs enough to matter. The 48 KB per-core SRAM is also a real constraint: it forces pipeline parallelism in places where a larger local memory could have enabled cleaner tensor parallelism, and the paper says this can cause up to 5x underutilization.

There are evaluation limits as well. Full end-to-end numbers are only for 8B and 13B models on a single wafer; larger models are extrapolated from subsets of layers. T10 and Ladder are author-implemented adaptations to WSE-2 rather than vendor-supported production systems, so the multi-GPU SGLang comparison is the cleaner external validation. Finally, WaferLLM is tuned to dense-transformer inference; MoE and other variants are discussed mostly as future work.

## Related Work

- _Liu et al. (SOSP '24)_ — T10 scales deep learning over inter-core connected processors, but it assumes on-chip communication is closer to a crossbar than to a huge mesh, so it misses wafer-scale locality as a design constraint.
- _Wang et al. (OSDI '24)_ — Ladder optimizes tensor programs for shared-memory accelerators, whereas WaferLLM shows that those assumptions break once remote SRAM access and routing pressure dominate execution.
- _Kwon et al. (SOSP '23)_ — PagedAttention improves GPU KV-cache efficiency through concatenation and paging, while WaferLLM argues that concatenate-style growth creates severe skew on wafer-scale meshes and replaces it with shifting.
- _Luczynski et al. (HPDC '24)_ — Near-optimal wafer-scale reduce studies allreduce on the same class of hardware; WaferLLM generalizes that idea into MeshGEMV and integrates it into a complete LLM inference runtime.

## My Notes

<!-- empty; left for the human reader -->

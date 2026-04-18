---
title: "MSCCL++: Rethinking GPU Communication Abstractions for AI Inference"
oneline: "Builds GPU collectives from hardware-near channels plus a DSL, so AI inference gets near-custom communication performance without vendor-specific hand-written stacks."
authors:
  - "Changho Hwang"
  - "Peng Cheng"
  - "Roshan Dathathri"
  - "Abhinav Jangda"
  - "Saeed Maleki"
  - "Madan Musuvathi"
  - "Olli Saarikivi"
  - "Aashaka Shah"
  - "Ziyue Yang"
  - "Binyang Li"
  - "Caio Rocha"
  - "Qinghua Zhou"
  - "Mahdieh Ghazimirsaeed"
  - "Sreevatsa Anantharamu"
  - "Jithin Jose"
affiliations:
  - "Microsoft Research, Vancouver, BC, Canada"
  - "Microsoft Research, Redmond, WA, USA"
  - "Microsoft Research, Beijing, China"
  - "Microsoft Azure, Redmond, WA, USA"
  - "Microsoft Azure, Cambridge, MA, USA"
  - "Microsoft Azure, Minneapolis, MN, USA"
  - "Microsoft Azure, Austin, TX, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790188"
code_url: "https://github.com/microsoft/mscclpp"
tags:
  - gpu
  - networking
  - llm-inference
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

MSCCL++ argues that GPU communication libraries should not force users to choose between hand-written, hardware-specific kernels and slow, rigid collectives. It exposes three hardware-near channel abstractions, layers a DSL and drop-in collective library on top, and shows that this stack preserves near-peak communication performance while speeding up real LLM inference.

## Problem

The paper starts from a practical frustration in modern AI systems: communication is now often a first-order bottleneck, especially for LLM inference, where the authors cite `10%-40%` of end-to-end time in real workloads. Yet the mainstream answer, NCCL-style collectives, is intentionally generic. It hides many low-level details behind synchronous `send/recv`-style primitives, chooses algorithms internally, and exposes only a narrow control surface. That is convenient for average workloads, but it is exactly why high-performance users keep bypassing it with custom kernels.

Those custom kernels exist for several reasons. Different workloads care about different points on the latency-versus-bandwidth curve; inference decode wants very small-message latency, while prefill and training-style cases want throughput. Collectives also mix data movement with computation, so an implementation that is optimal for pure transfer is not necessarily optimal once reductions and overlap matter. Finally, GPU interconnects evolve quickly: a production team may want to use a new transfer mode or switch feature long before a general-purpose library has wrapped it cleanly.

The cost of this status quo is engineering complexity. A team that writes its own communication path must reason about GPU, CPU, and NIC orchestration; data consistency under weak memory models; and link-specific mechanisms such as DMA, peer memory access, and switch-level multicast. The paper's target problem is therefore broader than "make AllReduce faster." It is how to give experts enough control to exploit hardware-specific features without forcing every inference system to maintain a fragile, vendor-specific communication stack.

## Key Insight

The central claim is that portability and performance are not in conflict if the abstraction boundary is drawn at the right place. MSCCL++ therefore does not begin from collectives like AllReduce and then try to tune them. Instead, it begins from the small set of transfer modes that real interconnects expose: port-mapped I/O, memory-mapped I/O, and switch-mapped I/O. If those mechanisms are surfaced directly, with explicit synchronization semantics and no forced intermediate buffers, higher layers can still specialize aggressively.

That leads to a layered design. The Primitive API is for experts who want exact control and near-zero abstraction cost. The DSL keeps the one-sided, asynchronous properties of those primitives, but lets developers describe communication algorithms at the level of thread blocks, chunks, and ranks instead of raw CUDA/HIP code. The Collective API then packages the resulting algorithms behind an NCCL-compatible surface for users who just want a faster library. The memorable proposition is that the same communication stack can support progressive refinement: generic users get a drop-in collective library, while power users can peel back layers only when they need the last bit of performance.

## Design

The Primitive API revolves around three channel types. `PortChannel` handles port-mapped transfers such as intra-node DMA copies or RDMA sends. Its `put` is zero-copy, one-sided, and asynchronous; `signal`, `wait`, and `flush` define when receivers may read data and when senders may safely reuse buffers. Today, because RDMA or DMA initiation still requires host involvement, each port channel owns a CPU thread and a request queue. That is a deliberate design trade: the API preserves asynchronous GPU-visible semantics even when the underlying hardware path still needs CPU help.

`MemoryChannel` targets peer-memory access with two protocols. The `HB` protocol amortizes synchronization over large chunks for bandwidth, while the `LL` protocol synchronizes at much finer granularity to reduce latency. `SwitchChannel` captures hardware such as NVLink SHARP, where a switch can perform multicast or reduction directly using multimem instructions. The important invariant across all three is that synchronization and transfer are decoupled, so kernels can overlap computation with communication instead of blocking on a two-sided rendezvous.

Above that, the DSL gives a global view of all ranks and thread blocks. Users write algorithms in Python using channels, buffers, and chunk slices; MSCCL++ lowers that program into an execution plan, inserts the needed synchronizations automatically, and fuses operations such as local reduction plus remote put into a single action when dependencies allow. The paper's overlapped ring `ReduceScatter` example makes the benefit concrete: by splitting each chunk in half, one half can be reduced while the other is still being transferred. The executor then interprets the lowered plan inside a generic execution kernel. Finally, the collective library reuses these mechanisms to provide tuned `1PA`, `2PA`, `2PR`, and hierarchical collectives behind an NCCL-compatible API.

## Evaluation

The first question is whether the abstractions leak performance. Table 1 suggests they mostly do not. On the paper's H100 setup, MSCCL++ reaches the same measured NVLink throughput as the best achievable number (`397.5 GB/s`), nearly the same NVLink latency (`829 ns` versus `822 ns`), the same InfiniBand throughput (`48.94 GB/s`), and somewhat higher InfiniBand latency (`4.89 us` versus `3.76 us`). That is a strong sign that the primitive layer is close enough to hardware for serious use.

The collective results are then consistently strong. On A100-40G, MSCCL++ improves AllReduce by up to `4.2x` over NCCL and `3.1x` over MSCCL for small messages, and by up to `1.8x` for large messages. For AllGather, the small-message gain reaches `5.4x` over NCCL. On H100, the `SwitchChannel` implementation is especially important: it yields up to `56%` higher bandwidth than an equivalent `MemoryChannel` version and drives overall AllReduce wins of up to `2.8x` for small messages and `2.4x` for large ones over NCCL. On MI300x, the same abstractions also adapt well to a very different topology, beating RCCL by up to `3.8x` on small messages and `2.2x` on large ones. I found the cross-hardware story persuasive because the paper does not claim a single magic algorithm; it claims that the abstraction stack makes topology-specific algorithms easier to express.

The end-to-end inference numbers matter more than the microbenchmarks. Replacing NCCL with MSCCL++ in vLLM for `Llama3-70B` on `8x A100-80G` reduces decode latency by `1.11x` on average and improves prefills by up to `1.06x`. In SGLang on `16x H100`, DeepSeek-V3 decode throughput rises by `1.31x` on average. The DeepEP result is also important qualitatively: by swapping an NVIDIA-specific IBGDA path for `PortChannel`, the authors match NVSHMEM-based performance without a noticeable loss while making the code more portable. The main caveat is that many collective results come from offline-picked best configurations rather than online autotuning, so the paper proves that the abstractions can express high-performance kernels more directly than it proves they can choose them automatically.

## Novelty & Impact

Relative to _Cowan et al. (ASPLOS '23)_, the key novelty is not merely "another DSL for collectives," but a DSL built on one-sided, asynchronous primitives rather than NCCL's synchronous send/recv substrate. Relative to NCCL and RCCL, the paper's contribution is not a single faster AllReduce schedule, but a communication stack that keeps low-level transfer modes visible enough to exploit DMA-copy, multimem, or topology-specific pipelining. Relative to custom inference kernels such as those in TensorRT-LLM or DeepEP, the pitch is that these optimizations should live in a reusable library instead of being repeatedly reimplemented inside each serving stack.

That makes the paper likely to matter to two audiences. Systems researchers can cite it as a case study in where to place the abstraction boundary for accelerator I/O. Practitioners building LLM serving stacks can cite it because it shows a path away from permanently maintaining bespoke communication kernels. The RCCL and SGLang adoptions strengthen that impact claim substantially.

## Limitations

The paper is honest that portability is not automatic. MSCCL++ still needs hardware-specific primitive implementations, and the best collective kernels are chosen by offline profiling over message sizes and platforms rather than by sophisticated online autotuning. The DSL also has a measurable runtime cost: its executor is `3%` slower on average than direct Primitive API implementations, and up to `18%` slower in one corner case.

There are also architectural constraints. `PortChannel` currently depends on a CPU thread to initiate some transfers, so it does not eliminate host involvement when the hardware itself cannot. `SwitchChannel` requires specialized support such as NVLink SHARP-style multimem operations. Finally, although the title says "AI inference," the evaluation mostly demonstrates faster collectives and then substitutes them into a few inference frameworks. That is enough to validate the communication thesis, but it does not show that MSCCL++ by itself solves broader serving problems such as admission control, batching, or multi-model routing.

## Related Work

- _Cowan et al. (ASPLOS '23)_ — MSCCLang synthesizes collective algorithms over NCCL/RCCL-style primitives, while MSCCL++ changes the primitive substrate itself to keep one-sided asynchronous communication visible.
- _Cai et al. (PPoPP '21)_ — SCCL generates efficient collective schedules, but still assumes conventional collective primitives; MSCCL++ argues that schedule synthesis benefits from a richer communication interface underneath.
- _Shah et al. (NSDI '23)_ — TACCL guides topology-aware collective synthesis, whereas MSCCL++ focuses on exposing transfer modes and synchronization semantics that such synthesized algorithms can exploit.
- _Hwang et al. (NSDI '23)_ — ARK also moves distributed ML control toward the GPU, but it is a monolithic end-to-end system; MSCCL++ extracts reusable communication abstractions into a standalone library stack.

## My Notes

<!-- empty; left for the human reader -->

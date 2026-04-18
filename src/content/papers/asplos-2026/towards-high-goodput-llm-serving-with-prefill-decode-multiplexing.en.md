---
title: "Towards High-Goodput LLM Serving with Prefill-decode Multiplexing"
oneline: "MuxWise multiplexes prefill and decode within the same GPUs, preserving one KV-cache pool while repartitioning SMs online to raise strict-SLO goodput."
authors:
  - "Yukang Chen"
  - "Weihao Cui"
  - "Han Zhao"
  - "Ziyi Xu"
  - "Xiaoze Fan"
  - "Xusheng Chen"
  - "Yangjie Zhou"
  - "Shixuan Sun"
  - "Bingsheng He"
  - "Quan Chen"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "National University of Singapore, Singapore"
  - "Researcher, Shanghai, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790236"
code_url: "https://github.com/ykcombat/sglang/tree/slo_config"
project_url: "https://zenodo.org/records/18062118"
tags:
  - llm-inference
  - scheduling
  - gpu
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

MuxWise argues that the right unit for LLM serving is not "one GPU for prefill" or "one GPU for decode," but "some SMs for prefill and the rest for decode on the same GPU." It uses layer-wise prefill execution, worst-case contention guards, and an SLO-aware dispatcher to keep decode within target while reclaiming idle compute for prefill. Across the paper's workloads, that raises peak goodput by `2.20x` on average and up to `3.06x` over prior systems.

## Problem

The paper starts from a gap between how production LLM services behave and how existing schedulers allocate hardware. Real workloads mix short chats, long-context analysis, reasoning traces, and multi-turn agents, so the ratio between input length, output length, and reused context changes dramatically across requests. At the same time, services want tight `TTFT` and `TBT` targets, especially for decode.

The two mainstream fixes both leave performance on the floor. Disaggregated systems such as Splitwise and LoongServe separate prefill and decode onto different instances to protect decode latency, but then they either strand GPUs when the phase mix changes or shrink the effective KV-cache pool. The paper's motivating example is blunt: splitting the same four GPUs into two pairs can cut cache hit rate from `36.6%` to `4.2%`, which turns reuse into recomputation. Chunked-prefill systems avoid full disaggregation, but they fuse prefill chunks with decode iterations under one token budget. That budget then becomes a hard compromise between SLO compliance and GPU saturation. For Llama-70B on 8 A100s, the authors show that saturating the GPU needs a budget around `4K`, while a `100 ms` `TBT` target permits only about `256`; at `4K`, `TBT` reaches `505 ms`.

The deeper issue is that prior designs still couple compute placement and memory placement too tightly. If prefill and decode cannot independently borrow compute while sharing the same KV state, the system either wastes throughput or breaks latency targets.

## Key Insight

The central claim is that prefill and decode should be spatially multiplexed inside each GPU, not merely time-interleaved or split across instances. Decode needs only enough SMs to satisfy its SLO; the rest can be reassigned to prefill, and both phases can still read and write one shared KV-cache pool. That single move removes the false choice between dynamic compute allocation and KV-cache reuse.

But the paper also shows that naive intra-GPU multiplexing is not enough. Prefill launches are slower, prefill runtimes are more variable, and bandwidth contention is unpredictable, so a straightforward "launch decode first, then launch prefill" scheme creates bubbles and can still miss deadlines. MuxWise's real insight is therefore twofold: make prefill interruptible at layer granularity, and reason about contention with conservative worst-case bounds rather than exact online prediction.

## Design

MuxWise is built from three pieces. The bubble-less multiplex engine uses NVIDIA GreenContext to bind different CUDA streams to different SM subsets while keeping both phases in one process and one memory space. That gives MuxWise low-overhead repartitioning and preserves cross-phase, cross-request KV reuse. The engine then splits prefill into transformer-layer-sized prefill layers (`PLs`). Because a layer launch is much shorter than an entire prefill, the scheduler can insert enough layers to cover decode time, stop after a decode finishes, or preempt a very long prefill so a shorter request can run first.

Layer granularity solves only part of the problem, because inflight batching still requires synchronization when a completed prefill joins the decode batch. MuxWise therefore adds query-based synchronization: it keeps launching decode iterations and prefill layers asynchronously, polls CUDA events, and merges a finished prefill into the current decode batch immediately instead of stalling for a coarse barrier. The authors report that fully layer-wise launching adds at most `1.5%` runtime overhead.

The contention-tolerant estimator handles the harder question: how many SMs can decode safely surrender? MuxWise first trains separate solo-run latency predictors for prefill and decode from offline profiling, using reused length, new-token length, output length, batch size, and partition configuration as features. It then applies a contention guard that stores worst-case decode slowdown factors for coarse grid cells over prefill/decode sizes and SM partitions. The paper emphasizes that SLO guarantees do not require perfect prediction, only an upper bound good enough to keep decode under target. Coarse profiling is enough because observed contention inflation stays within roughly `20%` on A100 and `30%` on H100.

The dispatcher runs after every decode iteration and every completed prefill batch. It chooses a best-fit SM split that satisfies decode first, then uses the remaining SMs for prefill. If a new short prefill batch arrives while a long prefill is running, MuxWise may preempt the long batch, but only if doing so will not cause the victim to miss its own `TTFT` target; recursive preemption is forbidden. The design deliberately gives decode hard priority and treats prefill SLO attainment as opportunistic once decode has been protected.

## Evaluation

The evaluation is strong for the paper's target regime: strict-SLO serving inside a single instance. The main platform is 8 `A100-80GB` GPUs running SGLang, with additional experiments on 8 H100s and 8 H200s. The authors test Llama-8B, Llama-70B, and Qwen3-235B-22B-activated against chunked-prefill in SGLang, NanoFlow, LoongServe, and SGLang-PD. Workloads include real multi-turn Conversation and Tool&Agent traces, plus synthetic ShareGPT, OpenThoughts, and LooGLE mixes.

The headline number is peak goodput: averaged across the paper's settings, MuxWise improves goodput by `2.20x`, with a maximum of `3.06x`. Under rising Tool&Agent load while enforcing 99th-percentile SLOs, it delivers `2.6x`, `5.2x`, `2.0x`, and `1.3x` more goodput than chunked-prefill, NanoFlow, LoongServe, and SGLang-PD respectively for Llama-8B; for Llama-70B, the gains are `3.06x`, `2.62x`, and `1.62x` over chunked-prefill, LoongServe, and SGLang-PD. On real traces, chunked-prefill and NanoFlow often fail `TBT`, while MuxWise and the disaggregated baselines keep it under control. The tradeoff is that SGLang-PD can achieve slightly lower `TBT` by statically reserving more decode compute, but MuxWise consistently wins on `TTFT` because it gives decode only the SMs it actually needs.

The cross-platform results matter too. On H100 and H200 systems, MuxWise still beats chunked-prefill by `2.28x` on average for 99th-percentile `TTFT` and `1.81x` for 99th-percentile `TBT`. That supports the core claim that the benefit comes from the serving paradigm rather than from one narrow implementation trick. My main caveat is scope: the experiments focus on one serving instance, one model family per run, and strict online SLOs. They do not answer cluster-level routing, autoscaling, or multi-model interference.

## Novelty & Impact

Relative to _Patel et al. (ISCA '24)_ and _Zhong et al. (OSDI '24)_, MuxWise's main novelty is refusing to pay the standard disaggregation tax in KV-cache capacity and recomputation. Relative to _Agrawal et al. (OSDI '24)_, it rejects token-budget fusion as the main abstraction and instead makes phase separation explicit inside the GPU. Relative to _Feng et al. (ISCA '25)_, it adds explicit bubble control and contention-aware scheduling rather than relying on ordinary stream overlap.

That makes the paper important for two audiences. Systems researchers get a new serving abstraction, intra-GPU PD multiplexing, plus a concrete scheduler that shows how to make it practical. Practitioners get a clear message that goodput losses in current LLM stacks are often caused less by raw model cost than by the way prefill and decode are mapped onto hardware.

## Limitations

MuxWise depends on hardware support for low-overhead intra-process SM partitioning such as GreenContext, so it is not instantly portable to every inference stack. It also needs per-model, per-machine offline profiling for both the solo-run predictor and the contention guard. The paper argues that this is acceptable, but it still adds operational work compared with fixed-policy schedulers.

The design is also intentionally biased toward protecting decode. The contention guard is only built for decode, while prefill SLOs are handled indirectly; when inference load exceeds peak capacity, the paper largely accepts that some prefills will miss. More broadly, MuxWise is a single-instance optimization. The discussion section says it can complement disaggregated fleets, but also admits it helps less when SLOs are loose, when workloads are effectively offline, or when prefill instances are already dominated by long requests that leave little room for decode multiplexing. Finally, the implementation adds about `6.2%` memory overhead from GreenContext plus CUDA Graph integration.

## Related Work

- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve uses chunked prefills to overlap prefill with decode, while MuxWise keeps full phases distinct and multiplexes them spatially inside each GPU.
- _Patel et al. (ISCA '24)_ — Splitwise disaggregates prefill and decode across instances for latency isolation; MuxWise keeps them co-located to preserve one KV-cache pool and adapt compute online.
- _Zhong et al. (OSDI '24)_ — DistServe also pursues goodput under SLOs through disaggregation, whereas MuxWise attacks the same objective with intra-GPU phase sharing.
- _Wu et al. (SOSP '24)_ — LoongServe adds dynamic long-context disaggregation, but MuxWise argues that releasing original KV placement still sacrifices cross-request reuse.

## My Notes

<!-- empty; left for the human reader -->

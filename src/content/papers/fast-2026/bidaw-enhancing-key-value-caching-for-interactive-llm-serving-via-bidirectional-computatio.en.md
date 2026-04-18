---
title: "Bidaw: Enhancing Key-Value Caching for Interactive LLM Serving via Bidirectional Computation–Storage Awareness"
oneline: "Bidaw separates fast and slow KV loads at the scheduler and uses answer length to predict future reuse, bringing host-memory/SSD LLM caching closer to the all-memory ideal."
authors:
  - "Shipeng Hu"
  - "Guangyan Zhang"
  - "Yuqi Zhou"
  - "Yaya Wei"
  - "Ziyan Zhong"
  - "Jike Chen"
affiliations:
  - "Tsinghua University"
  - "China University of Geosciences Beijing"
  - "China Telecom Omni-channel Operation Center"
conference: fast-2026
category: ai-era-storage
tags:
  - llm-inference
  - caching
  - scheduling
  - memory
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Bidaw is a two-tier KV-caching system for interactive LLM serving, where history state lives across host memory and SSD instead of a large DRAM pool. Its central move is to make compute and storage exchange predictive signals: the scheduler should know where each request's KV resides and how large it is, while eviction should use the previous model answer to predict when that KV will be needed again. On the authors' interactive workload, Bidaw reduces response latency by up to `3.58x` and improves throughput by up to `1.83x`, getting much closer to the all-host-memory upper bound than prior systems.

## Problem

The paper targets multi-round interactive serving, not offline batch inference. In this setting, each new user turn depends on the KVs from all previous turns in that conversation, but GPU memory is too small to keep those histories resident indefinitely. Recomputing the entire conversation prefix every round is prohibitive: on the authors' production-style workload, users average `22.4` rounds per conversation, and redundant recomputation accounts for as much as `93.1%` of total compute.

The obvious alternative is to cache history KVs in a two-tier store with host memory as the performance layer and SSD as the capacity layer. Prior systems such as CachedAttention and FlashGen already do this, but the paper shows a large remaining gap. Against a simulated ideal where all KVs are always served from host memory, existing two-tier approaches suffer up to `3.8x` higher latency and `2.0x` lower throughput. The problem is not that SSDs are inherently unusable; it is that prior designs treat compute scheduling and storage management as separate subsystems.

That separation hurts in two ways. First, KV-loading times vary sharply because requests have different history lengths and because host memory and SSD have very different bandwidth. An unlucky request whose KV sits on SSD can stall the GPU while later requests with memory-resident KVs wait behind it. Second, eviction policies that look only at past access order see poor temporal locality. On the authors' trace, `80%` of weighted reuse distances exceed the `200 GB` host-memory capacity, and even when the performance tier holds about `40.1%` of KVs on average, common policies achieve only around `20%` hit rate. The paper's question is therefore how to make two-tier KV caching behave more like an all-memory system without requiring RDMA disaggregated memory or lossy compression.

## Key Insight

The central proposition is that interactive serving exposes useful future hints on both sides of the compute-storage boundary, and a good system should exploit them in both directions. On the compute side, the scheduler can tell whether a request is cheap to start by looking at KV placement and KV size before it ever reaches the GPU. On the storage side, the serving engine knows something that a conventional cache does not: the length of the model answer it just produced, which strongly influences when the same user will send the next turn.

That second claim is the more interesting one. Bidaw observes that the lower bound of a KV's future weighted reuse distance rises with the previous answer length, because longer answers keep the human user busy reading, listening, and composing the next query while other users' requests arrive in between. Across twelve time windows and multiple arrival rates, the paper reports Spearman correlations of `0.94-0.98` between answer length and the smallest future weighted reuse distance. The broader idea is that interactive LLM serving is not just a cache-replacement problem; it is a human-in-the-loop access-pattern problem, and the model's own output helps predict the next access.

## Design

Bidaw's control path begins when a request arrives. The compute engine inspects where that request's history tensor currently lives and splits requests into two queues. Requests whose KVs are already in the performance layer go to a `ready queue`; requests whose KVs are only in SSD go to a `preparing queue`, where they wait for promotion after being loaded into host memory. GPU execution pulls only from the ready queue, so a slow SSD read no longer blocks unrelated requests whose KVs are already warm. Within the ready queue, Bidaw keeps FCFS-like fairness by ordering promoted requests by original arrival time rather than promotion time.

The preparing queue uses a different policy because SSD-bound requests have highly variable service times. Bidaw introduces `disk-HRRN`, a storage-aware variant of Highest Response Ratio Next, and assigns priority `1 + waiting_time / KV_size`. This intentionally favors smaller KVs, which can be promoted quickly and reduce overall queueing delay, while the waiting-time term prevents large-KV requests from starving. The result is a hybrid scheduler: FCFS semantics once KVs are ready, and size-aware promotion while requests are still storage-bound.

The eviction path is equally cross-layer. Bidaw maintains per-user statistics on past weighted reuse distances and also tracks the latest answer length coming from the model. It first uses the answer length to estimate a lower bound on the next access's reuse distance. It then maintains a background ghost cache that simulates an optimal policy on past traces to estimate hit rates for reuse-distance buckets: a guaranteed-hit small bucket, several "promising" buckets beyond raw memory capacity, and an extreme bucket whose hit rate is effectively zero. For each user's next access, Bidaw combines the per-user probability distribution over buckets with the answer-length-derived lower bound, producing an overall hit potential. When host memory is tight, it evicts the KV with the lowest predicted hit potential.

The data path adds several implementation details that matter in practice. Bidaw uses inclusive caching so SSD always retains a copy, which makes eviction cheap. It adopts continuous batching, then pairs it with a mix-grained GPU allocator: `256`-token blocks for history and input tokens, `16`-token blocks for generated tokens, with split-and-merge support to limit fragmentation while still making CPU-GPU transfers coarse enough to use bandwidth well. Finally, the paper notices that for MHA-based models the literal KV tensor is not always the best object to cache. Among intermediate tensors, the "normalized activation" (`tensor 6`) offers the highest saved-compute-per-byte ratio, so Bidaw stores that tensor and reconstructs KV later on a low-priority CUDA stream. The authors note that this optimization is attractive for MHA models such as OPT, Qwen, Llama, and Bloom, but not for GQA models, where caching KV directly remains preferable.

## Evaluation

The evaluation uses both a large private trace and a public one. The main workload comes from an industry partner and spans more than one million conversation rounds, with average query length `36`, average response length `45`, and average round count `22.4`. Experiments run on one `80 GB` A800 GPU, `200 GB` of host memory, and a `1.5 GB/s` SATA-SSD RAID-5 array over PCIe 4.0. Models include `OPT-6.7B`, `Qwen-7B`, `OPT-13B`, `Qwen-14B`, and `OPT-30B`. The baselines are `vLLM`, `CachedAttention`, and `FlashGen`, plus a simulated upper bound where all KVs come from host memory.

The headline numbers support the paper's claim. Across models, Bidaw supports `1.43x-1.83x` higher user arrival rate than the state of the art at similar latency, and on `OPT-13B` it cuts average response latency by up to `3.58x`. The supporting diagnostics also line up with the mechanism: the new eviction policy lowers miss rate by up to `57.6%` relative to the queue-enhanced policy from CachedAttention and by up to `69.9%` relative to common general-purpose policies; the I/O-aware scheduler reduces average queueing time from `5.76 s` to `2.45 s`, a `57.5%` drop. Tail latency improves too: on `OPT-30B`, Bidaw cuts P99 latency by `47.03%` versus CachedAttention and `56.81%` versus FlashGen.

The evaluation is mostly convincing because it stresses exactly the regime the paper claims to optimize: low-concurrency, human-paced, multi-turn serving on a single machine. A useful sanity check is that the benefit does not disappear even when the SSD is made faster in simulation: with a `5 GB/s` SSD, the FlashGen baseline improves from `15.18` to `20.23` users per minute on `OPT-13B`, but still remains far below Bidaw's `27.81` to `30.35`. The main caveat is that CachedAttention and FlashGen are reimplemented on top of vLLM because the original systems are closed-source, so the comparisons are informative but not perfectly apples-to-apples.

## Novelty & Impact

Relative to _Gao et al. (ATC '24)_ and _Jeong and Ahn (ASPLOS '25)_, Bidaw's novelty is not merely "another KV cache." Its main contribution is to show that the scheduler and the eviction policy should both consume signals produced by the other side of the stack: storage latency should shape request order, and model answers should shape replacement decisions. Relative to _Qin et al. (FAST '25)_, it targets a cheaper deployment point than RDMA-based disaggregated-memory KV serving. Relative to _Gao et al. (EuroSys '25)_, it goes beyond activation caching as a restoration trick and turns tensor choice into a compute-versus-footprint optimization.

That makes the paper important for local or private interactive serving, especially in vertical domains that cannot justify a specialized memory pool. The likely impact is practical rather than conceptual: people building chatbot appliances or on-prem deployment stacks can borrow Bidaw's cross-layer scheduling and answer-informed eviction immediately, even if they never adopt its exact implementation.

## Limitations

Bidaw's strongest assumption is that the workload is genuinely human-paced and interactive. Its answer-length predictor works because longer answers delay the next turn; if requests come from automated agents, scripted load generators, or bursty pipelines, that correlation may weaken. The paper itself hints at this in the ShareGPT study: because timestamps are synthetically generated with a Poisson process, the previous-answer-based eviction strategy contributes much less there than on the real interactive trace.

There are also systems-level limits. The evaluation is single-node and single-GPU, so the paper says little about multi-GPU serving, tenant interference, or datacenter-scale schedulers. The storage-efficient tensor trick is not universal, since GQA models should cache KV directly. And the implementation keeps a background ghost cache plus per-user reuse statistics, which are cheap in the reported setup but may become more involved under much larger user populations or different memory budgets. Finally, the reliance on reimplemented baselines means some residual uncertainty remains about how much of the win is algorithmic versus implementation quality.

## Related Work

- _Gao et al. (ATC '24)_ — CachedAttention adds queue-aware eviction and proactive loading for multi-turn serving, while Bidaw argues queue state alone misses both SSD-service asymmetry and answer-driven user think time.
- _Jeong and Ahn (ASPLOS '25)_ — FlashGen reduces recomputation with resource-aware multi-turn serving, whereas Bidaw adds explicit storage-latency-aware scheduling and a cross-layer eviction predictor.
- _Qin et al. (FAST '25)_ — Mooncake uses an RDMA-backed disaggregated memory pool for KV reuse, while Bidaw targets lower-cost local host-memory/SSD hierarchies.
- _Gao et al. (EuroSys '25)_ — HCache restores serving state from intermediate activations, and Bidaw extends that line by asking which history tensor is most storage-efficient to cache under two-tier I/O constraints.

## My Notes

<!-- empty; left for the human reader -->

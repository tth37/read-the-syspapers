---
title: "Shift Parallelism: Low-Latency, High-Throughput LLM Inference for Dynamic Workloads"
oneline: "Switches between sequence and tensor parallelism at runtime by preserving KV-cache layout, cutting low-traffic latency without giving up batch efficiency."
authors:
  - "Mert Hidayetoglu"
  - "Aurick Qiao"
  - "Michael Wyatt"
  - "Jeff Rasley"
  - "Yuxiong He"
  - "Samyam Rajbhandari"
affiliations:
  - "Snowflake, Menlo Park, California, USA"
  - "Snowflake, Bellevue, Washington, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790219"
code_url: "https://github.com/snowflakedb/ArcticInference"
tags:
  - llm-inference
  - gpu
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Shift Parallelism starts from a practical serving problem: tensor parallelism gives low per-request latency, while data parallelism gives higher throughput, and production traffic swings between those two regimes. The paper adapts sequence parallelism to inference, makes its KV-cache layout compatible with tensor parallelism, and switches between an SP-heavy base mode and a full-TP shift mode according to batch size. The result is a serving stack that keeps TTFT and TPOT low under light traffic while recovering much of the throughput that TP normally gives up under bursts.

## Problem

The paper argues that LLM inference traffic is fundamentally dynamic. Interactive workloads such as coding agents and chatbots arrive in small numbers and care about TTFT and TPOT. Batch-style workloads arrive in large bursts and mostly care about aggregate tokens per second. A single production deployment often sees both patterns, sometimes alternating within minutes.

Existing multi-GPU parallelisms force an unpleasant choice. Tensor parallelism partitions weights and computation inside each layer, which accelerates a single request but pays repeated all-reduce costs; it is therefore latency-oriented but throughput-poor. Data parallelism does the opposite: it replicates the model, gets high throughput across many requests, but does not speed up any single request. Operators can deploy separate TP and DP fleets, but that duplicates capacity and operational complexity. Worse, the paper argues that one cannot cheaply switch between TP and DP online because their attention and KV-cache layouts differ, so switching would require expensive data movement or re-materialization.

## Key Insight

The paper's core claim is that Sequence Parallelism, specifically Ulysses-style SP, has the right structural property for inference-time switching. Like DP, SP can deliver high throughput on large batches because it avoids TP's costly all-reduce pattern in attention. But unlike DP, SP can share the same KV-cache layout as TP. If the implementation preserves not just head placement but also head ordering, a system can move between SP and TP without rewriting the cache.

That turns traffic adaptation into a simple runtime policy. When batches are large, use SP or a mixed `(SP, TP)` configuration to reduce TTFT and sustain throughput. When batches are small, especially in decode-heavy low-traffic periods where SP suffers load imbalance, shift to full TP to minimize TPOT. The important proposition is not merely "switch when the load changes," but "choose two parallelisms whose caches are invariant enough that switching is cheap."

## Design

The design has two layers. First, the authors generalize SP itself for inference. Training-time SP is not enough because inference models commonly use grouped-query attention, can have fewer KV heads than GPUs, and operate under small, fluctuating batch sizes. The implementation therefore adds GQA support, replicates KV cache when the number of KV heads is too small for the chosen SP degree, and pads small batches so sequence slices remain balanced across GPUs. That padding keeps SP workable, but it also explains why SP is not ideal for low-traffic decoding: redundant padded tokens inflate TPOT.

Second, Shift Parallelism defines two concrete runtime modes. The base configuration is either pure SP or a mixed `(SP, TP)` factorization over the node, chosen so the model fits and enough KV-cache memory remains for concurrency. The shift configuration is always full TP across the same GPUs. The runtime then compares the current batch size against a threshold: above the threshold it runs the base configuration, below it it runs the shift configuration.

The nontrivial part is KV-cache invariance. For arbitrary mixed `(SP, TP)` layouts, attention heads become interleaved after SP's all-to-all exchange, so naive full TP would observe a different head order and therefore a different cache interpretation. The paper fixes this with a general process-to-data mapping that loads the shift configuration's QKV shards in the same logical head order as the base configuration. That is the technical step that makes "switching" a real implementation strategy rather than a conceptual sketch.

The authors also examine two ways to manage weights across the two modes. On-the-fly slicing avoids extra memory but requires transpositions that perform poorly on Hopper FP8 tensor cores. Their implementation instead keeps separate base and shift models while sharing the attention mechanism and KV cache. The paper gives the extra weight-memory cost as `1/SP`; with `SP = 8`, the shift model adds `12.5%` overhead. Finally, the whole design is integrated into vLLM through the ArcticInference plug-in, with separate compilation and CUDA-graph capture for both modes.

## Evaluation

The evaluation is fairly complete for the paper's target setting: single-node, multi-GPU LLM serving under changing traffic. The main testbed is an `8xH200` node with NVSwitch. The core dense-model results use Llama-70B and Qwen-32B in FP8, and the workloads include a synthetic bursty mix, the Azure LLM code trace, the Mooncake conversation trace, and parameterized synthetic requests.

The bursty synthetic experiment makes the main systems point clearly. Compared with vLLM configured for throughput-optimized DP and latency-optimized TP, Shift Parallelism achieves the best median latency while keeping near-DP throughput: median TTFT drops to `148 ms`, versus `1,355 ms` for DP and `3.93 s` for TP; median TPOT is `51 ms`, versus `83-85 ms` for the baselines; peak throughput reaches `69,147 tok/s`, which is much closer to DP's `75,535 tok/s` than TP's `51,162 tok/s`. On the Azure code trace, the paper reports that Shift Parallelism consistently attains the lowest TTFT, TPOT, and completion time distributions, especially around burst points where TP's queueing grows quickly.

The controlled benchmark with `4k` input and `250` output tokens shows the same pattern in a cleaner form. On Llama-70B, Shift Parallelism reaches `102 ms` TTFT versus `159 ms` for TP and `614 ms` for DP, while combined throughput rises to `37.4k tok/s` from TP's `24.7k tok/s`. Across context sizes from `2k` to `128k`, the authors summarize the headline wins as up to `6.97x` faster response than DP, `1.56x` faster response than TP, up to `2.45x` faster generation than DP, and up to `1.51x` higher peak throughput than TP. The arrival-rate sweep is also persuasive: DP and TP cross over at a few requests per second, but Shift Parallelism stays on the best side of that tradeoff and yields the lowest completion time across the whole range.

I found the evaluation convincing for the stated claim, but only within its scope. The paper does not beat DP on absolute peak throughput at sustained high traffic; Table 3 states that explicitly. Its win is that it dominates TP on throughput while preserving TP-like latency when traffic lightens. That is a more realistic systems claim, and the experiments support it well.

## Novelty & Impact

Relative to _Agrawal et al. (OSDI '24)_, the paper is not about chunked-prefill scheduling; it is about choosing and switching the underlying multi-GPU parallelism itself. Relative to _Patel et al. (ISCA '24)_, which separates prefill and decode across different resources, Shift Parallelism stays within one deployment and avoids stage-to-stage KV transfer by preserving cache layout across modes. The most novel contribution is therefore not SP alone, but the end-to-end argument that inference can exploit SP as a throughput-oriented companion to TP and can switch between them cheaply because of KV-cache invariance.

That matters to teams building shared LLM fleets where traffic oscillates between interactive and batch behavior. It also gives future serving papers a new design axis: instead of optimizing only scheduling above a fixed execution substrate, they can treat the substrate's parallelism mode as another runtime control knob.

## Limitations

The paper is clear that Shift Parallelism is not a universal optimum. DP still wins the highest-throughput corner in sustained high-traffic settings because it avoids attention communication entirely. Long-context throughput remains heavily bounded by attention cost, which the authors explicitly leave to sparse-attention-style techniques. The implementation also inherits nontrivial overhead from vLLM itself on smaller models, so not every remaining gap is explained by parallelism choice. Finally, the MoE discussion is promising but incomplete: the paper shows gains on two sparse models, yet leaves expert parallelism and broader sparse-model design space for future work.

## Related Work

- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve improves prefill/decode overlap with chunked prefill, while Shift Parallelism changes the underlying GPU parallelism mode itself and is designed to compose with chunked-prefill systems.
- _Kwon et al. (SOSP '23)_ — PagedAttention makes continuous LLM serving practical by stabilizing KV-cache memory management; Shift Parallelism assumes that serving substrate and focuses on multi-GPU execution strategy.
- _Patel et al. (ISCA '24)_ — Splitwise separates prefill and decode onto different workers, whereas Shift Parallelism keeps one node and changes between SP and TP to match traffic without moving KV state across stages.
- _Qin et al. (FAST '25)_ — Mooncake treats KV cache as a disaggregated storage problem, while Shift Parallelism targets the in-node latency/throughput tradeoff of how inference work is parallelized over GPUs.

## My Notes

<!-- empty; left for the human reader -->

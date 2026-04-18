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

Shift Parallelism treats multi-GPU parallelism itself as a runtime control knob for LLM serving. The paper adapts Sequence Parallelism to inference, preserves KV-cache invariance between SP and TP, and switches between an SP-based base mode and a full-TP shift mode according to batch size. That lets one deployment keep low-latency behavior under light traffic while recovering much of the throughput that TP usually gives up during bursts.

## Problem

The paper starts from a deployment reality that many serving papers flatten away: one LLM fleet often sees both interactive traffic and batch-like bursts. Coding agents and chatbots send a few requests at a time and care about `TTFT` and `TPOT`; summarization, post-training, and similar jobs arrive in large waves and mainly care about combined tokens per second. Traffic oscillates between those regimes, so a single fixed parallelism leaves money or latency on the table for part of the day.

The bad news is that the standard choices split the tradeoff in awkward ways. Tensor parallelism accelerates per-layer computation and is especially good for decode latency, but its repeated all-reduce traffic cuts combined throughput. Data parallelism is the mirror image: excellent throughput, but no acceleration for a single request. The paper also argues that simply switching between TP and DP online is impractical because their attention and KV-cache layouts differ, so switching would require costly cache movement or recomputation. That means operators either pick one compromise mode or overprovision separate fleets.

## Key Insight

The core claim is that Ulysses-style Sequence Parallelism is the missing throughput-oriented companion to TP for inference. SP avoids TP's attention all-reduce pattern, so it gives better `TTFT` and higher throughput on larger batches. At the same time, unlike DP, SP can be made KV-cache-invariant with TP. If the system preserves both head placement and head ordering, the same cached keys and values remain meaningful after a switch.

That changes the problem from "how do we migrate between incompatible serving modes?" to "when should we flip between two compatible ones?" The paper's answer is simple and practical: keep SP, or a mixed `(SP, TP)` layout, as the base configuration for large batches, then shift to full TP when the batch is small and decode-heavy. The reason is not that TP is universally lower latency; it is that SP wins on prefill and throughput, while TP wins on `TPOT` when SP's small-batch load imbalance and padding overhead become dominant.

## Design

The first part of the design is a generalized SP implementation for inference rather than training. The paper extends SP to support `GQA`, which matters because inference models often have fewer KV heads than query heads. When the chosen SP degree exceeds the available KV-head parallelism, the system replicates KV cache through the all-to-all communication path instead of relying on TP-style recomputation. It also pads small batches up to a multiple of the SP degree so work can be evenly distributed. That padding is important: it keeps SP correct and balanced, but it is also exactly why SP is a poor low-traffic decode mode and why Shift Parallelism needs TP as its fallback.

The second part is the switching structure. The base configuration is either full SP or a mixed `(SP, TP)` factorization, with `SP x TP = P` across the node, chosen so the model fits while preserving enough KV-cache memory for concurrency. The shift configuration is always full TP over the same GPUs. At runtime, the system uses a batch-size threshold: large batches run in the base configuration, while small batches switch to full TP.

The hardest technical issue is generalized KV-cache invariance. For mixed `(SP, TP)` layouts, SP's all-to-all turns the logical head order into an interleaved order. A naive full-TP shift would therefore interpret the cache incorrectly even if the head counts matched. The paper fixes this with a process-to-data mapping that loads the shift configuration's Q weights and QKV shards in the base configuration's logical head order. In other words, switching is cheap only because the authors preserve the cache's meaning, not just its shape.

The memory-management story is also concrete. The paper considers on-the-fly slicing and separate-model replication for the shift path. On-the-fly slicing avoids extra storage but requires transpositions that interact poorly with Hopper FP8 tensor cores. The implementation therefore chooses two separately loaded models that share the attention mechanism and KV cache. The added weight footprint is `1/SP`; with `SP = 8`, that means `12.5%` extra weight memory. The system is integrated into vLLM through the ArcticInference plug-in, with separate compilation and CUDA-graph capture for base and shift modes.

## Evaluation

The evaluation is broad enough for the paper's actual claim: one-node, multi-GPU serving under dynamic traffic. The main hardware target is an `8xH200` node with `NVSwitch`; the software base is vLLM plus the ArcticInference plug-in. The main dense-model experiments use FP8 Llama-70B and Qwen-32B, and the workloads include a synthetic burst trace, the Azure LLM code trace, the Mooncake conversation trace, and controlled synthetic request streams. The paper also adds two MoE models later to stress the generalized SP path.

The bursty synthetic trace is the cleanest headline result. Compared with throughput-optimized DP and latency-optimized TP in vLLM, Shift Parallelism delivers median `TTFT` of `148 ms` versus `1,355 ms` for DP and `3.93 s` for TP, median `TPOT` of `51 ms` versus `83-85 ms`, and peak throughput of `69,147 tok/s` versus `75,535 tok/s` for DP and `51,162 tok/s` for TP. That is exactly the paper's point in one table: keep near-DP throughput while avoiding the queueing collapse that TP sees under bursts.

The real traces support the same story. On the 15-minute Azure code trace, the paper reports the lowest `TTFT`, `TPOT`, and completion-time distributions across the whole replay, with the most visible advantage around burst points. On the Mooncake conversation trace, DP and TP cannot sustain the arrival rate on a single node and their wait times grow because the KV cache fills up, whereas SP and Shift Parallelism maintain finite completion times. That is a useful stress case because it shows the benefit is not just nicer p50 numbers, but staying on the right side of queue stability.

The controlled `4k` input, `250` output benchmark makes the tradeoff easier to compare numerically. On Llama-70B, Shift Parallelism reaches `102 ms` `TTFT`, `10.1 ms` `TPOT`, and `37.4k tok/s` combined throughput; TP gets `159 ms`, `9.34 ms`, and `24.7k tok/s`; DP gets `614 ms`, `22.5 ms`, and `45.9k tok/s`. On Qwen-32B, Shift hits `86.41 ms` `TTFT`, `9.48 ms` `TPOT`, and `53.8k tok/s`, versus TP's `113 ms`, `8.68 ms`, and `38.3k tok/s`, and DP's `385 ms`, `18.8 ms`, and `70.1k tok/s`. Across context sizes from `2k` to `128k`, the paper summarizes the best-case gains as up to `6.97x` faster response than DP, `1.56x` faster response than TP, up to `2.45x` faster generation than DP, and up to `1.51x` higher peak throughput than TP. The arrival-rate sweep is equally strong: TP and DP cross over at only a few requests per second, while Shift Parallelism stays below both in completion time across the whole range.

I found the evaluation convincing for the stated scope, with two caveats. First, the paper is explicit that DP still wins the absolute highest-throughput corner under sustained high traffic, because attention parallelization always carries communication cost. Second, the whole study is single-node and `NVSwitch`-centric, so the results say more about dynamic parallelism inside one box than about multi-node serving fleets.

## Novelty & Impact

Relative to _Agrawal et al. (OSDI '24)_, this paper is not another scheduler over a fixed serving substrate; it changes the substrate itself by making the parallelism mode dynamic. Relative to _Patel et al. (ISCA '24)_, which separates prefill and decode across resources, Shift Parallelism keeps one deployment and avoids stage-to-stage KV transfer by preserving cache semantics across SP and TP. The novelty is therefore not merely "SP for inference," but the end-to-end argument that SP can serve as TP's high-throughput companion and that KV-cache invariance makes runtime switching practical.

That is a meaningful contribution for production LLM systems. It gives operators a way to collapse what might otherwise be separate latency-oriented and throughput-oriented configurations into one deployment, and it suggests a broader research direction: parallelism choice itself can be part of the serving control plane, not just a static compile-time decision.

## Limitations

The paper is refreshingly direct that Shift Parallelism is not a universal optimum. DP still owns the absolute peak-throughput corner in sustained high traffic because it avoids attention communication altogether. Long-context serving also remains attention-bound, so throughput drops as context grows even when Shift Parallelism makes the better tradeoff than TP. The paper treats sparse attention and similar long-context techniques as orthogonal future work rather than solving that bottleneck here.

There are also deployment constraints behind the clean story. The threshold policy is driven by batch size and depends on offline profiling for the chosen model, hardware, and quantization setup. The implementation duplicates model weights for the shift path, which is cheap enough at `1/SP` overhead but still not free. And because the evaluation is concentrated on single-node `H200` systems with `NVSwitch`, the paper does not tell us how well the same mechanism survives multi-node communication, expert parallelism, or a truly heterogeneous fleet.

## Related Work

- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve improves prefill/decode overlap with chunked prefill, while Shift Parallelism changes the underlying GPU parallelism mode itself and is designed to compose with chunked-prefill systems.
- _Kwon et al. (SOSP '23)_ — PagedAttention makes continuous LLM serving practical by stabilizing KV-cache memory management; Shift Parallelism assumes that serving substrate and focuses on multi-GPU execution strategy.
- _Patel et al. (ISCA '24)_ — Splitwise separates prefill and decode onto different workers, whereas Shift Parallelism keeps one node and changes between SP and TP to match traffic without moving KV state across stages.
- _Qin et al. (FAST '25)_ — Mooncake treats KV cache as a disaggregated storage problem, while Shift Parallelism targets the in-node latency/throughput tradeoff of how inference work is parallelized over GPUs.

## My Notes

<!-- empty; left for the human reader -->

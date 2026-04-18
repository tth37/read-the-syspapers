---
title: "Shift Parallelism: Low-Latency, High-Throughput LLM Inference for Dynamic Workloads"
oneline: "Switches between sequence parallelism and full tensor parallelism without moving KV cache, so one LLM-serving deployment stays fast at both low and high load."
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
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Shift Parallelism starts from an uncomfortable serving fact: tensor parallelism gives the best per-request latency, while data parallelism gives the best pure throughput, and existing systems usually pick one or deploy both separately. The paper's answer is to adapt sequence parallelism to inference, make its KV-cache layout compatible with tensor parallelism, and switch between the two online based on batch size. That gives one deployment that is much closer to the latency of TP at low load and much closer to the throughput of SP or DP at high load.

## Problem

The paper targets production LLM inference workloads that do not stay in one regime. Interactive chatbot or agent loops arrive at low concurrency and care about `TTFT` and `TPOT`, while batch jobs such as summarization or translation arrive in bursts and care much more about aggregate tokens per second. A single model deployment may see both patterns in the same day, and sometimes in the same minute.

Existing multi-GPU inference parallelisms force an unpleasant choice. Tensor parallelism (TP) shards each layer and reduces latency for a single request, but every layer pays all-reduce overhead, so combined throughput drops. Data parallelism (DP) is embarrassingly parallel across requests and therefore cheap per token at high traffic, but it cannot speed up one request and is poor for interactive latency. The obvious operational workaround is to run separate TP and DP fleets and route requests by class, but that duplicates capacity and complicates production management.

The more interesting question is why one deployment cannot simply switch between TP and DP as traffic changes. The paper's answer is that the attention state does not line up: their KV-cache layouts are incompatible, so a mid-flight switch would require expensive data movement and coordination. That makes the core problem more specific than "choose the best parallelism." The challenge is to find a pair of inference parallelisms with complementary performance and a shared KV-cache layout, so a running system can move between them without rebuilding the request state.

## Key Insight

The central insight is that sequence parallelism (SP), originally developed as Ulysses for training, has the right structural properties for this role. Like DP, it improves throughput relative to TP by avoiding TP's all-reduce-heavy attention path. Unlike DP, it still parallelizes work within a request, which helps `TTFT` on long prompts. Most importantly, its KV-cache layout can be made invariant with TP, so the same request state can survive a switch between the two.

That does not mean SP is always best. In low-traffic decoding, SP suffers from small-batch load imbalance and sometimes must pad tokens so all GPUs stay busy; that hurts `TPOT`. TP remains the right mode when the batch is small and per-token generation latency matters most. The paper's proposition is therefore not "replace TP with SP," but "treat SP as the high-batch base mode and TP as the low-batch shift mode, then switch by batch size." The enabling trick is KV-cache invariance: if the cache and head ordering remain consistent across modes, the system can respond to traffic changes without costly cache transformation.

## Design

The design has two layers. The first is a generalized inference-time SP implementation. The authors extend training-style Ulysses so it works for inference models with Grouped Query Attention (GQA), can replicate KV cache when the SP degree exceeds the number of KV heads, and can tolerate low-traffic imbalance. They also support mixed `(SP, TP)` base configurations for models that do not fit comfortably on one GPU. In that mixed mode, TP keeps the model resident while SP uses the remaining GPUs to enlarge effective KV-cache capacity and raise throughput.

The second layer is Shift Parallelism itself. The runtime keeps two configurations: a base configuration that uses either full SP or mixed `(SP, TP)`, and a shift configuration that uses full-node TP. At each forward pass, the system compares the current batch size to a threshold. If the batch is large, it runs the base configuration to optimize `TTFT` and combined throughput; if the batch is small, it shifts to TP to minimize `TPOT`.

Making that switch cheap requires careful data layout control. The paper shows that arbitrary `(SP, TP)` and full-TP combinations do not automatically preserve attention-head ordering, even if they nominally shard the same heads. To restore invariance, the shift configuration loads its QKV shards in the SP-aware order of the base configuration. That keeps the KV-cache coherent across modes. For weights, the implementation chooses explicit weight replication instead of slicing on the fly: it loads separate base and shift models that share the same KV cache. The extra memory cost of the shift model is `1/SP` of the base model's weight footprint, so high-SP base modes make the duplication cheaper.

The system is integrated into vLLM through a plug-in path rather than a new runtime. Both models are separately compiled and CUDA-graph captured, then replayed according to the active mode. That is a practical design choice: the paper is trying to make dynamic parallelism deployable inside an existing serving stack, not just demonstrate a new algorithm in isolation.

## Evaluation

The evaluation centers on single-node `8xH200` deployments using vLLM plus the authors' implementation, mostly with FP8 `Llama-70B` and `Qwen-32B`, and then extends to two sparse MoE-style models. The cleanest latency-throughput comparison is Figure 12. On `Llama-70B`, Shift Parallelism achieves `102 ms` TTFT, versus `159 ms` for TP and `614 ms` for DP. Its TPOT is `10.1 ms`, nearly matching TP's `9.34 ms` and far ahead of DP's `22.5 ms`. For combined throughput, it reaches `37.4k tok/s`, which is much higher than TP's `24.7k tok/s` though still below DP's `45.9k tok/s`. That pattern is exactly the paper's claim: not global dominance over DP, but a far better single-deployment tradeoff than TP or DP alone.

The synthetic bursty-trace experiment makes the operational value clearer. There, median TTFT is `148 ms` with Shift Parallelism, compared with `1,355 ms` for throughput-optimized DP and `3,930 ms` for latency-optimized TP, while peak throughput still reaches `69,147 tok/s` versus DP's `75,535 tok/s` and TP's `51,162 tok/s`. In other words, the system gives up some pure-batch peak throughput relative to DP in exchange for avoiding catastrophic latency spikes when bursts and interactive traffic mix.

The real-trace studies reinforce that story. On the Azure code trace, Shift Parallelism achieves the lowest TTFT, TPOT, and completion-time distributions among the tested modes. On the Mooncake conversation trace, TP and DP cannot keep up on one node and accumulate unbounded queueing delay, while SP and Shift can sustain the workload once FP8 KV cache is enabled. I found the evaluation supportive of the central claim for node-local serving, especially because the comparisons are implemented inside the same vLLM-based stack. The main caveat is that the paper itself finds substantial framework overhead in vLLM, so part of the remaining gap to DP at high throughput is system overhead rather than the core parallelism idea.

## Novelty & Impact

Relative to prior serving work that separates prefill and decode across workers, Shift Parallelism makes a different bet: keep one deployment, keep the KV cache local, and change the intra-node parallelism instead of changing where phases run. Relative to Ulysses itself, the paper's novelty is not merely "SP for inference"; it is the claim that inference-time SP can be generalized enough to share KV state with TP and therefore serve as half of a dynamic switching pair.

That makes the paper most relevant to practitioners running production multi-GPU LLM serving and to systems researchers studying how to smooth the latency-cost tradeoff under dynamic demand. It is a mechanism paper, but one with a strong deployment message: dynamic traffic should not force operators into permanently separate TP and DP fleets.

## Limitations

The paper is clear that Shift Parallelism does not beat every baseline on every metric. Pure high-traffic throughput is still best with DP, because Shift still performs parallel attention and therefore still pays communication costs. The design also carries memory and implementation overhead: the shift model replicates `1/SP` of the weights, two configurations must be compiled and graph-captured, and a threshold must be chosen to decide when to switch.

The experiments are also mostly single-node and mostly dense-model centric. The sparse-model section is promising, but the authors explicitly say expert parallelism remains future work. Likewise, the strongest results are on `8xH200` with the authors' vLLM plug-in stack. The paper does not really study multi-node serving, fleet-level routing, or how a threshold should adapt online as traffic distributions drift. The paper also does not show a controller that learns the threshold automatically.

## Related Work

- _Patel et al. (ISCA '24)_ — Splitwise separates prefill and decode across workers to optimize each phase independently, whereas Shift Parallelism keeps one node-local serving stack and switches multi-GPU parallelism instead of phase placement.
- _Qin et al. (FAST '25)_ — Mooncake uses a KV-cache-centric disaggregated architecture, while Shift Parallelism specifically avoids remote KV movement by exploiting a shared local KV layout between SP and TP.

## My Notes

<!-- empty; left for the human reader -->

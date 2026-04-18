---
title: "PrefillOnly: An Inference Engine for Prefill-only Workloads in Large Language Model Applications"
oneline: "PrefillOnly uses hybrid prefilling to shrink active inference memory for single-token LLM requests, then schedules them with continuously updated prefill-time estimates."
authors:
  - "Kuntai Du"
  - "Bowen Wang"
  - "Chen Zhang"
  - "Yiming Cheng"
  - "Qing Lan"
  - "Hejian Sang"
  - "Yihua Cheng"
  - "Jiayi Yao"
  - "Xiaoxuan Liu"
  - "Yifan Qiao"
  - "Ion Stoica"
  - "Junchen Jiang"
affiliations:
  - "University of Chicago"
  - "TensorMesh, Inc."
  - "Tsinghua University"
  - "LinkedIn"
  - "UC Berkeley"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764834"
tags:
  - llm-inference
  - memory
  - caching
  - scheduling
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PrefillOnly argues that recommendation, verification, embedding, and disaggregated-prefill requests are not small variants of chat serving; they form a distinct prefill-only regime. It uses hybrid prefilling to reduce active inference memory, discards or offloads suffix KV state while preserving prefix caches, and schedules by shortest estimated prefill time with continuous re-estimation. Across four 2-GPU setups, the paper reports 1.4x-4.0x higher QPS than generic baselines without worse mean or P99 latency.

## Problem

LLM inference engines are designed for arbitrary-length generation. That design bakes in two assumptions: the engine must keep all-layer KV caches because many decode steps may follow, and the scheduler cannot rely much on job completion time because output length is unknown. In prefill-only workloads, both assumptions are wrong.

The paper's motivating applications are long-input discriminative tasks such as post recommendation, credit verification, and data labeling, plus embedding generation and prefill nodes in prefill/decode disaggregation. These requests still have large contexts: the evaluation's simulated recommendation traces use 11k-17k-token user profiles, and credit histories run 40k-60k tokens. But the model only needs the probability of one next token, or the hidden state at one position. Existing engines therefore pay for future decode reuse that never arrives.

The obvious alternatives are unsatisfying. Chunked prefilling admits longer inputs but slows attention kernels. Tensor or pipeline parallelism spreads KV state across GPUs, but brings all-reduce overhead or pipeline bubbles. Meanwhile, the fixed one-token output makes service time much more predictable, yet generic engines still mostly use JCT-agnostic queueing and miss opportunities to reduce latency and increase prefix-cache locality.

## Key Insight

A prefill-only engine should optimize for active inference state, not for long-lived decode reuse. Once the system knows a request ends after one token, most KV data generated during prefill need not remain resident, and the queue can be ordered by a good proxy for prefill time.

The non-obvious part is where memory really goes. PrefillOnly shows that simply keeping only the current layer's KV cache yields limited gains, because MLP intermediates dominate peak memory: in Llama-3.1-8B, the main temporary tensors are 28,672 and 14,336 floats per token, versus 2,048 for one layer of KV cache. So the right proposition is: shrink linear-layer intermediates aggressively, keep attention fast and unchunked, and then exploit the deterministic service time of one-token requests in the scheduler.

## Design

PrefillOnly begins with a profiling run. Given a configured maximum input length, it forwards a synthetic request through the model, measures peak GPU memory, and reserves the remainder for prefix KV caches. At runtime, an OpenAI-compatible front end sends requests to a scheduler, which chooses one request per step and dispatches it to executors built on top of vLLM.

The first mechanism is hybrid prefilling. PrefillOnly processes non-attention layers chunk by chunk but keeps attention layers unchunked. Implemented via `torch.compile`, it groups consecutive linear operators into a virtual layer, forwards each chunk through that layer, and then materializes the full output. Two details matter: preallocating the full output tensor avoids doubling memory during concatenation, and in-place reuse writes output chunks back into input buffers when shapes match. Because prefilling still completes in one forward pass, the engine can discard or offload KV state without having to regenerate it for later chunks.

The second mechanism is suffix KV discarding/offloading. PrefillOnly preserves as much prefix KV as fits in GPU memory so future requests can hit prefix cache, then discards or offloads suffix KV when the request exceeds that budget. Unlike vLLM-style suffix eviction after request completion, this happens during the request itself. The paper's prototype only discards suffix KV, but explicitly notes that systems such as LMCache or Mooncake could supply the offload path.

The third mechanism is shortest-prefill-first scheduling with continuous re-estimation. PrefillOnly treats requests as sequential, not batched, because its target regime is usually compute-bound until contexts become extremely long. Before each scheduling step it recomputes every waiting request's score as estimated prefill time minus `lambda * queue_time`, where the estimate is driven by cache-miss tokens rather than raw input length. Continuous re-estimation matters because prefix-cache hits appear and disappear over time; without recalibration, a shortest-job policy can miss the requests that just became cheap.

## Evaluation

The implementation adds about 4.6k lines of Python on top of vLLM and is tested on 2x L4, 2x A100, 2x H100 PCIe, and 2x H100 NVLink, with Llama-3.1-8B, Qwen-32B FP8, and Llama-3.3-70B FP8. The workloads are simulated rather than production traces, which is a real caveat, but they are aligned with the paper's target cases: one workload stresses prefix reuse in recommendation, and the other stresses extremely long inputs in credit verification.

The results support the paper's central claim. Across hardware and workloads, PrefillOnly reports 1.4x-4.0x higher sustainable QPS than PagedAttention, chunked prefilling, tensor parallelism, and pipeline parallelism, without inflating mean or P99 latency. In recommendation, the gain mostly comes from scheduling: continuous prefill-time re-estimation prevents prefix-cache thrashing that hurts FIFO and naive shortest-job policies. In credit verification, the gain comes from avoiding inference-parallel communication and pipeline bubbles for very long inputs.

The maximum-input-length numbers are equally important. PrefillOnly reaches 130k/87k/97k tokens on L4/A100/H100, versus 24k/11k/15k for PagedAttention and 46k/17k/25k for chunked prefilling. Tensor and pipeline parallelism can sometimes support even longer contexts, but only by paying the throughput costs the paper is trying to avoid. The paper also validates its scheduling proxy: cache-miss tokens correlate with measured prefill time at 0.987 Pearson correlation on Qwen-32B FP8.

## Novelty & Impact

The paper's novelty is mostly at the systems-framing level. It identifies prefill-only serving as a first-class workload rather than a corner case of generative serving, then redesigns memory management and queueing around that framing. Hybrid prefilling is the strongest concrete mechanism, because it explains how to lower active memory without paying the usual chunked-attention penalty. The work should matter to builders of recommendation, verification, embedding, and disaggregated serving systems that currently inherit chat-oriented assumptions from mainstream LLM runtimes.

## Limitations

The biggest limitation is external validity. Both datasets are simulated, so the paper does not show production request traces, real tenant mixes, or long-duration operational effects. The design also has clear losing regimes. If prefix-cache capacity, rather than per-request active memory, is the bottleneck, tensor or pipeline parallelism may be preferable because each GPU stores only a slice of KV state. The prototype discards suffix KV instead of offloading it, so future reuse is lost. And its scheduling policy is local to one engine instance; the paper itself notes that a global shortest-prefill-first router could do better in large deployments. Low-QPS latency can also favor parallelized baselines because PrefillOnly deliberately avoids splitting one request across GPUs.

## Related Work

- _Kwon et al. (SOSP '23)_ — PagedAttention/vLLM improves generic LLM memory management, but still assumes all-layer KV retention and mostly JCT-agnostic scheduling.
- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve uses chunked prefilling for generative serving, while PrefillOnly keeps attention unchunked and chunks only the linear parts.
- _Zhong et al. (OSDI '24)_ — DistServe disaggregates prefill and decode for generative workloads; PrefillOnly studies the extreme where prefill itself is the whole workload.
- _Yu et al. (OSDI '22)_ — Orca raises generative-serving throughput with continuous batching, whereas PrefillOnly argues batching is often the wrong abstraction for compute-bound prefill-only jobs.

## My Notes

<!-- empty; left for the human reader -->

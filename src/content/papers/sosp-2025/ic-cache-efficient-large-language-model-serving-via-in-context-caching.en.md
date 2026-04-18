---
title: "IC-Cache: Efficient Large Language Model Serving via In-context Caching"
oneline: "IC-Cache turns past request-response pairs into in-context demonstrations, then routes each query across small and large LLMs by predicted quality and load."
authors:
  - "Yifan Yu"
  - "Yu Gan"
  - "Nikhil Sarda"
  - "Lillian Tsai"
  - "Jiaming Shen"
  - "Yanqi Zhou"
  - "Arvind Krishnamurthy"
  - "Fan Lai"
  - "Henry M. Levy"
  - "David E. Culler"
affiliations:
  - "University of Illinois Urbana-Champaign"
  - "Google"
  - "Google & University of Washington"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764829"
tags:
  - llm-inference
  - caching
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

IC-Cache argues that historical LLM interactions are more valuable as demonstrations than as cached answers. It retrieves a few high-utility request-response pairs, prepends them to a new prompt so a smaller model can imitate a larger one, and routes requests across models with a load-aware bandit. On realistic traces, the paper reports 1.4x-5.9x higher throughput and 28-71% lower latency without hurting judged response quality.

## Problem

LLM serving is squeezed between quality, latency, and cost. Larger models answer better, but they are slower and much more expensive, and the paper shows with Microsoft's Azure trace that minute-scale peaks can reach 25x off-peak load. Operators therefore need a way to preserve quality without routing everything to the most expensive model.

Historical requests look like the obvious lever: across MS MARCO, Natural Questions, and LMSys-Chat, over 70% of requests have another request with cosine similarity above 0.8. But semantic caching is not enough. Exact matches are rare, and directly returning the nearest cached answer drops win rate from 50% to 18% because semantically similar questions often still need different responses. The systems problem is turning recurring traffic into useful guidance without replaying stale or off-topic answers.

## Key Insight

The paper's key claim is that old request-response pairs are better reused as demonstrations than as answers. If a cached pair came from a stronger model, prepending it to a new prompt can help a smaller model imitate the larger model's structure, reasoning style, and level of detail. On recurring workloads, that turns historical traffic into live capability augmentation.

Utility, however, is not the same as relevance. A semantically similar example may still be low value if its answer is weak, redundant with other examples, or teaches a skill the smaller model already has. IC-Cache therefore couples three decisions: choose examples by predicted helpfulness, route the request according to both quality and load, and keep refining the cache as traffic changes.

## Design

IC-Cache sits in front of existing backends such as vLLM, HuggingFace Runtime, and LangChain. For each request it retrieves examples, chooses a model, then updates the example pool.

The Example Selector is two-stage. It first uses dense embeddings to retrieve semantically related candidates, with offline clustering sized at about `sqrt(N)` to keep matching scalable. It then runs a lightweight proxy model, trained from preference feedback or sampled quality checks, to estimate true helpfulness for the current request and target model. Instead of blindly taking the top-k most similar items, IC-Cache selects a combination of examples and tunes a global utility threshold online so that extra demonstrations are kept only when they pay for their prompt-length cost.

The Request Router is a contextual multi-armed bandit whose context includes the request and chosen examples, and whose arms are candidate models. It updates online from sparse feedback rather than requiring labels for every model on every query. To survive bursty traffic, it tracks an exponential moving average of load and applies a tanh-based bias against expensive models only after load crosses a threshold.

The Example Manager handles long-run cache quality. It can replay old examples offline and keep a better response when the expected gain justifies the replay cost, and it bounds cache size with a one-dimensional knapsack over example size versus offloading value. The paper also adds privacy controls such as domain-scoped admission, client-side PII stripping, and an optional differentially private synthetic cache.

## Evaluation

The prototype is about 3 KLOC and uses FAISS retrieval, a JAX router, and gRPC-connected components. The evaluation runs on a 16 A100 cluster with Microsoft-inspired arrival traces, millions of requests across conversation, search QA, translation, code generation, and math reasoning, and both proprietary and open models including Gemini, DeepSeek-R1, Qwen2.5, Gemma-2, and Phi-3.

End to end, IC-Cache improves throughput by 1.4x-5.9x and lowers latency by 28-71% without hurting judged quality. On online traces it delivers 9% higher response quality than RouteLLM at comparable throughput and latency. On Natural Questions it reaches 2.3x higher throughput than RouteLLM at the same 50% win rate, and on MS MARCO the routed Gemma-2-2B plus IC-Cache setup pushes win rate above 50% against Gemma-2-27B.

The mechanisms themselves also look plausible. The two-stage selector adds under 1% overhead. In contention-free tests, Gemma-2-2B plus IC-Cache is 71% faster than Gemma-2-27B and delivers 5.1x more throughput under the same resource budget. In some translation and code-generation settings, tens of thousands of plaintext examples, under 20 MB total, are enough to approach saturated quality.

## Novelty & Impact

IC-Cache's novelty is the systems framing: it turns historical traffic into an online distillation signal and co-designs example retrieval, model routing, and cache maintenance around that idea. That distinguishes it from semantic caching, which reuses old answers, and from pure model routers, which choose a model but do not change what the smaller model sees at inference time.

The result is relevant to operators of multi-model LLM fleets, edge/cloud assistants, and serving systems that already collect request history or preference feedback.

## Limitations

IC-Cache works best when workloads recur. If traffic is highly novel or similar requests still need materially different outputs, the example pool becomes less useful. It also increases prefill time because every offloaded request carries extra demonstrations.

The design depends on feedback quality and background resources. The proxy model and bandit need preference or judged-quality signals, replay assumes spare off-peak capacity, and the default plaintext cache raises privacy concerns. The paper offers sanitization and DP synthesis, but the DP cache loses some quality. Most experiments also map public datasets onto realistic traces rather than studying a full production deployment.

## Related Work

- _Kwon et al. (SOSP '23)_ - vLLM/PagedAttention makes one model's KV-cache efficient, whereas IC-Cache changes which model can serve a query by reusing historical request-response pairs as demonstrations.
- _Ong et al. (arXiv '24)_ - RouteLLM learns to route between small and large models, but it neither augments the small model with in-context examples nor biases decisions explicitly for overload.
- _Zhao et al. (EMNLP '24)_ - LongRAG retrieves external documents for long-context QA; IC-Cache instead retrieves prior model interactions, which transfer answer structure and reasoning style rather than static text alone.
- _Yu et al. (OSDI '22)_ - Orca increases serving throughput with continuous batching, and IC-Cache is complementary because it expands the set of requests that a cheaper model can handle in the first place.

## My Notes

<!-- empty; left for the human reader -->

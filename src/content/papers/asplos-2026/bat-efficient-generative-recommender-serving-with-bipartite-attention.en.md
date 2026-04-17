---
title: "Bat: Efficient Generative Recommender Serving with Bipartite Attention"
oneline: "Bat reorders generative recommender prompts so either users or items become reusable KV-cache prefixes, then schedules and places caches by hotness to raise throughput."
authors:
  - "Jie Sun"
  - "Shaohang Wang"
  - "Zimo Zhang"
  - "Zhengyu Liu"
  - "Yunlong Xu"
  - "Peng Sun"
  - "Bo Zhao"
  - "Bingsheng He"
  - "Fei Wu"
  - "Zeke Wang"
affiliations:
  - "Zhejiang University, Hangzhou, China"
  - "Taobao & Tmall Group of Alibaba, Beijing, China"
  - "The University of Hong Kong, Hong Kong, China"
  - "Aalto University, Espoo, Finland"
  - "National University of Singapore, Singapore, Singapore"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790131"
tags:
  - ml-systems
  - caching
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Bat argues that generative recommender prompts do not have to treat the user profile as the only reusable prefix. Its Bipartite Attention mechanism makes user tokens and item tokens interchangeable at the prefix boundary, then Bat uses hotness-aware scheduling plus hot-replicated cold-sharded item placement to decide which prefix to cache and where to place it. Across four datasets, Bat reports up to `2.3x` higher throughput than recomputation and up to `1.6x` over the conventional user-as-prefix design.

## Problem

The paper starts from a deployment shift in recommender systems. Generative recommenders replace relatively small DLRM-style rankers with Transformer models that encode the user profile, about `100` candidate items, and instruction tokens in one long causal-attention prompt. That improves modeling capacity, but it also makes ranking look like LLM prefill: for `1B-7B` models with inputs up to `8K` tokens, even a single request can exceed a `100-200 ms` SLO.

Prefix caching is the obvious systems response, but the default organization wastes most of the opportunity. In the usual user-as-prefix layout, only the user profile can be reused, and only across repeated requests from the same user. Cross-user reuse is blocked by personalization, while item reuse is poor because retrieval produces different candidate sets from turn to turn. On the authors' advertising workload, this drops cache hit rate to `18%` and limits total computation savings to less than `11%` versus recomputation. The memory story is also bad: with Qwen2-1.5B, `1000` user tokens already consume about `29 MB` of KV cache, so storing `10^8` users would require more than `2.9 PB`.

So the real problem is not just "cache GR prefixes." It is "find a cache unit that can be reused across many users, fit it into practical cluster memory, and decide per request whether user-side or item-side reuse saves more work."

## Key Insight

Bat's key claim is that recommendation prompts have a permutation-invariant structure at the user-versus-item level. Swapping which side comes first does not materially change the recommendation task as long as each user and each item preserves its own token order and the mask prevents different items from interacting. If that proposition holds, then the system can sometimes turn the item set into the reusable prefix instead of the user profile.

That matters because item popularity is much more skewed and much more shared than user identity. The traces show that about `90%` of accesses concentrate on the hottest `10%` of items, while many users are inactive and appear only once or twice per hour. Bat therefore treats prefix choice as a resource-allocation decision: if items are the reusable boundary, the system can amortize item KV caches across many users; if a user has a very long history and high short-term frequency, it can still fall back to the traditional user prefix.

## Design

The first piece is Bipartite Attention itself. Bat supports two prompt organizations: `User-as-prefix`, where the cached prefix is `[U]` and the suffix is `[I1, ..., IN, Instr]`, and `Item-as-prefix`, where the cached prefix is `[I1, ..., IN]` and the suffix is `[U, Instr]`. To make item KV caches independently reusable, Bat changes both the attention mask and the position encoding. Different candidate items cannot attend to each other, and each item's first token shares the same starting position ID. This removes the positional bias that would otherwise tie an item's KV cache to one exact slot in the candidate list.

The second piece is Bat's disaggregated serving architecture. A centralized prompt scheduler receives requests from retrieval, queries cache metadata for user and item entries, chooses a prefix order, and dispatches batches to GPU inference workers. Separate KV cache workers hold paged user and item entries in CPU or GPU memory and transfer them through DMA or RDMA, while a metadata service tracks indexes and hotness. The key point is not the split itself, but the policy: Bat proactively decides which prefix to reuse before execution rather than passively accepting the application's prompt order.

The third piece is cache placement. Because item caching consumes memory that could otherwise hold user entries, Bat pools memory across nodes and uses a hot-replicated cold-sharded design. It profiles network bandwidth and prefill time to derive a communication budget, fully replicates only the hottest items up to that budget, and shards the tail across workers. That keeps hot items local while avoiding full replication of the entire corpus.

The fourth piece is hotness-aware prompt scheduling. Bat observes that user history length alone is a poor rule because long-profile users may still be cold and cause compulsory misses. It therefore maintains a sliding-window estimate of user request frequency and chooses user-as-prefix only when the user's token count exceeds item-token count and the user's predicted frequency beats the lowest-frequency user entry already occupying cache. Otherwise, the request uses item-as-prefix. In short, Bat spends scarce user-cache space only on users likely to reuse it soon.

## Evaluation

The evaluation is broader than a toy serving study. The authors use a `4`-node A100 cluster for most experiments, a `16`-node H20 production cluster for scalability, three open datasets from Amazon (`Games`, `Beauty`, `Books`), and a synthetic `Industry` dataset derived from real advertising traces. They test Qwen2-1.5B, Qwen2-7B, and Llama3-1B on the same vLLM plus FlashInfer base with CPU-memory KV caching for baselines.

The headline result is that Bat consistently beats recomputation and usually beats fixed prefix policies. Across datasets and models, it reaches up to `58%` cache hit rate and up to `2.3x` higher throughput than recomputation, while improving throughput by up to `1.6x` over the conventional user-as-prefix policy. The comparison between fixed policies is itself informative: item-as-prefix outperforms user-as-prefix on `Beauty`, `Books`, and `Industry`, but loses on `Games`, where user access frequency is high. That is exactly the regime split Bat is designed to exploit, so the results support the paper's central claim that one fixed prefix policy is not enough.

The quality study is also important because the whole system depends on semantic invariance rather than pure systems engineering. Table 3 shows that item-as-prefix usually preserves Recall, MRR, and NDCG relative to user-as-prefix, and sometimes even improves them, but not always: Qwen2-1.5B on `Books` degrades slightly, and Llama3-1B is less robust in some settings. The authors attribute this to base-model sensitivity and suggest position-independent caching techniques such as PIC/CacheBlend to narrow the gap.

The component studies are useful rather than perfunctory. Hot-replicated cold-sharded placement improves throughput by `10%` at `10 Gbps` and `16%` at `100 Gbps` over full replication on the `Books` workload, while avoiding the heavy network penalty of pure hashing. Hotness-aware scheduling materially outperforms a cache-agnostic "pick the longer side" policy when user cache is tight. On latency, Bat sustains about `1.47x` the request rate of user-as-prefix and `1.57x` of recomputation under a `200 ms` P99 target. On scalability, throughput grows near-linearly from `1` to `16` nodes and Bat remains effective up to an `Industry-100M` item corpus.

## Novelty & Impact

Relative to prior generative recommender work such as _Zhai et al. (ICML '24)_, Bat's novelty is not a stronger ranking model but a new serving abstraction: it treats prompt order as a controllable systems lever and uses recommendation semantics to justify it. Relative to general LLM prefix-caching systems such as _Kwon et al. (SOSP '23)_ and later KV-cache stores, Bat's main distinction is that it does not passively cache fixed prompts; it changes the prompt structure, then co-designs placement and admission policies around that choice. Relative to position-independent caching papers such as _Hu et al. (ICML '25)_, Bat creates a recommender-specific reason to exploit position independence.

That makes the paper likely to matter to two communities. Recommender-systems engineers get a concrete recipe for making GR serving less cost-prohibitive, and systems researchers get a clean example of workload semantics informing cache design.

## Limitations

The largest limitation is model dependence. Bat works only if the base GR model tolerates the item-as-prefix reordering with little or no ranking loss, and the paper itself shows that this is not uniformly true across models and datasets. In practice that means the deployment recipe is partly "pick or fine-tune a model that behaves well under reordered positions."

The design also assumes relatively stable item descriptions and strong popularity skew. Precomputing item KV caches offline, replicating the hot head, and updating the rest in the background is sensible for e-commerce and ads, but it may work less cleanly when item metadata changes frequently or popularity shifts faster than the hotness estimator can track.

Finally, the evaluation stays within the ranking stage and mostly within `100`-candidate workloads. The paper says the retrieval stage can have more than `10K` candidates and suggests Bat may help even more there, but does not evaluate that regime. It also does not study multi-model serving or end-to-end recommender pipelines.

## Related Work

- _Zhai et al. (ICML '24)_ — HSTU shows that large generative recommenders can improve ranking quality at industrial scale; Bat tackles the serving-cost side of that same shift.
- _Kwon et al. (SOSP '23)_ — PagedAttention provides the paged KV-cache substrate Bat builds on, but it does not exploit recommender-specific prompt reorderings or shared item prefixes.
- _Hu et al. (ICML '25)_ — EPIC studies position-independent caching for LLM serving; Bat uses a related idea in a narrower but more workload-specific form to make item prefixes reusable.
- _Yao et al. (EuroSys '25)_ — CacheBlend recomputes selected tokens to recover accuracy under cache reuse, which is directly relevant to Bat's item-as-prefix accuracy gap on some base models.

## My Notes

<!-- empty; left for the human reader -->

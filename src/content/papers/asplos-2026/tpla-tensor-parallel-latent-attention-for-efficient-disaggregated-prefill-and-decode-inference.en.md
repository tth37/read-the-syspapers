---
title: "TPLA: Tensor Parallel Latent Attention for Efficient Disaggregated Prefill & Decode Inference"
oneline: "Reparameterizes MLA into a tensor-parallel decode path that shards latent KV cache across GPUs, while keeping MLA-style prefill to preserve accuracy and TTFT."
authors:
  - "Xiaojuan Tang"
  - "Fanxu Meng"
  - "Pingzhi Tang"
  - "Yuxuan Wang"
  - "Di Yin"
  - "Xing Sun"
  - "Muhan Zhang"
affiliations:
  - "Institute for Artificial Intelligence, Peking University, Beijing, China"
  - "Tencent Youtu Lab, Shanghai, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790237"
tags:
  - llm-inference
  - gpu
  - caching
  - disaggregation
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

TPLA starts from a specific weakness of `MLA`: once inference uses tensor parallelism, every GPU still has to hold the full latent KV cache, so MLA's memory advantage erodes exactly where large-model serving needs it most. The paper's answer is to shard the latent space across devices while letting every attention head still see the full latent information, then to keep MLA during compute-bound prefill and switch to TPLA only for memory-bound decode. On DeepSeek-V3-0324 and Kimi-K2-Base, that yields `1.79x` and `1.93x` decoding speedups at `32K` context on two H800s with modest accuracy loss.

## Problem

The paper is about a deployment mismatch between model architecture and systems reality. `MLA`, introduced by DeepSeek-V2, compresses each token's KV state into a low-rank latent vector, which is excellent for single-device decoding because the cache is smaller than standard multi-head attention or `GQA`. But under tensor parallelism, the attention computation for different heads is spread across GPUs, and each GPU still needs the full latent vector `cKV`. That means per-device KV-cache footprint no longer shrinks with the tensor-parallel degree. The authors give a concrete example: with `TP=4`, LLaMA-3-70B's GQA cache becomes `512` dimensions per device, while DeepSeek-V3's MLA cache stays replicated at `576` dimensions per device.

The obvious fix is `GLA`, which partitions the latent KV cache itself. But the paper argues that GLA pays for that systems win by weakening the model. Once heads are divided into groups and each group sees only its own latent slice, cross-group query-latent interactions disappear. In other words, GLA reduces per-device cache, but it also reduces each head's representational capacity and requires retraining from scratch. The target problem is therefore narrower and more practical than "make latent attention fast": preserve MLA-style model quality, reduce per-device KV traffic under tensor parallel inference, and do it in a way that can load existing MLA checkpoints.

## Key Insight

The key claim is that the bad tradeoff in GLA is not fundamental. A latent KV cache can be sharded across devices without hiding part of the latent space from each head, as long as the system shards each head's input dimension instead of permanently assigning disjoint head subsets to disjoint latent subsets. Each device can compute attention over its local latent shard, project the partial output locally, and then combine the final result with an all-reduce. That keeps the per-device KV cache small while preserving the logical "full view" seen by each attention head.

The remaining obstacle is that `RMSNorm` and `softmax` are global operations over the whole latent vector. If the model is naively sliced, those operators see only a shard and introduce approximation error. TPLA's second insight is to absorb an orthogonal transform into the MLA weights before slicing so that local shards approximate the full-vector statistics better. Hadamard balancing works well for `RMSNorm`; `PCA` works better for `softmax`, where keeping high-variance information concentrated in early dimensions matters more than simple numerical balance. The third insight is phase separation: use reparameterized MLA during prefill, where compute dominates and slicing is unnecessary, and switch to TPLA only during decode, where memory bandwidth is the bottleneck.

## Design

The design starts from the absorbed form of MLA, where the up-projection into keys is folded into the query activations and the value projection is folded into the output projection. TPLA then splits the latent KV vector across devices, but unlike GLA, it does not give each device only a disjoint subset of heads. Instead, every original attention head is represented on every latent shard, so each shard computes a partial attention result for all heads. The system sums those partial outputs with an all-reduce. The paper also shows that this is algebraically equivalent to a special case of GLA with duplicated heads, which is important because it makes TPLA compatible with `FlashAttention-3` rather than requiring a completely new attention kernel stack.

Two reparameterization steps make this practical for pretrained checkpoints. For `RMSNorm`, the authors introduce an orthogonal matrix `U` such that after transforming the latent vector, the norm computed on each shard is a good approximation of the full-vector norm. A Hadamard transform is attractive here because it spreads magnitude evenly and keeps the local RMS estimates close to the global one. For `softmax`, the goal is different: the dot-product score on each shard should approximate the global score. Plain Hadamard balancing is not enough, so the paper uses `PCA` over calibration data to rotate the latent space such that the first half of dimensions captures most of the variance. The resulting coefficients are then absorbed into the model weights, giving a training-free conversion path from MLA to TPLA.

The prefilling/decode split is the systems-level piece that makes the mechanism useful. Decode is memory-bandwidth-bound, so reducing per-device KV-cache traffic matters a lot. Prefill is compute-bound, so TPLA's replicated head structure is less attractive there. The paper therefore proposes `TPLA (pd sep.)`: keep the reparameterized MLA form during prefill, without slicing `RMSNorm` or `softmax`, then partially reuse that KV cache and switch to TPLA for decode. This avoids approximation error on the vast majority of prompt tokens and also lowers `TTFT`.

## Evaluation

The evaluation covers both model-quality preservation and inference speed. On short commonsense tasks, the contrast with GLA is stark. For DeepSeek-V2-Lite, plain MLA has WikiText-2 perplexity `6.31`; direct MLA-to-GLA conversion explodes it to `2212`, while training-free TPLA conversion reaches `7.24`. The same pattern holds across MMLU, ARC, PIQA, HellaSwag, OpenBookQA, and WinoGrande: TPLA loses accuracy relative to MLA, but far less than GLA, and lightweight alignment or prefill/decode separation nearly closes the gap. On DeepSeek-V3, average commonsense accuracy falls from `72.10` to `68.00` for direct TPLA conversion; on Kimi-K2-Base it falls from `73.52` to `70.49`.

Long-context results are more mixed, which makes the paper more credible. On LongBench, direct TPLA conversion accumulates slicing error over long sequences. But `TPLA (pd sep.)` narrows the gap substantially: DeepSeek-V3 drops from `58.19` average to `56.04`, which the authors describe as only a `2.15%` average loss, and Kimi-K2-Base drops from `54.78` to `52.39`. The paper is honest that lightweight alignment on concatenated short-text corpora helps less on these long-generation tasks than on short multiple-choice benchmarks.

For performance, the setup is reasonably fair to the central claim. The authors remove `MoE` routing from DeepSeek-V3-0324 and Kimi-K2-Base to isolate attention effects, convert both models to `BF16`, and use `FlashAttention-3` in both MLA and TPLA runs. On two H800 GPUs, decoding throughput improves steadily with context length, reaching `1.79x` at `32K` context for DeepSeek-V3-0324 and `1.93x` for Kimi-K2-Base. Prefill latency tells the complementary story: because prefill is compute-bound, plain TPLA is not ideal, but `TPLA (pd sep.)` is about `1.4x` faster than TPLA at `1K` prompt length. Taken together, the experiments support the paper's central systems claim well: sharding latent KV for decode is genuinely valuable, but only if prefill and decode are treated as different regimes.

## Novelty & Impact

Relative to _Zadouri et al. (arXiv '25)_, TPLA's novelty is not merely "make MLA more hardware-friendly," but preserve full-head access to the latent space while still reducing per-device KV cache. Relative to _DeepSeek-AI (arXiv '24)_, it turns MLA from a mostly single-device-efficient mechanism into one that survives tensor-parallel deployment. Relative to _Zhong et al. (OSDI '24)_, it is complementary rather than competitive: DistServe separates prefill and decode across serving resources, while TPLA changes the attention formulation itself so the decode side consumes less memory bandwidth.

The paper is likely to matter to two groups. LLM-serving researchers can cite it as a concrete recipe for reconciling latent attention with tensor parallel inference, especially for disaggregated prefill/decode pipelines. Model architects may also care because the work exposes a cleaner interface between pretrained attention formats and deployment-time parallelization. That makes the contribution feel like a real mechanism plus a practical conversion path, not just a benchmark paper.

## Limitations

The paper's main limitation is that its cleanest results are for `g=2` sharding. The authors explicitly note that `PCA` loses effectiveness as the number of groups grows, because later principal components carry much less useful information; this raises doubts about how well the exact recipe scales to more aggressive partitioning. Long-generation accuracy is also still fragile: Appendix results on `RULER` show that even the aligned variant drops sharply at longer contexts, suggesting that decode-time approximation errors can compound over many generated tokens.

There are also evaluation-scope limits. The speed experiments remove `MoE` routing, run on only two H800s, and focus on the attention path rather than full production serving. The paper argues that compatibility with `FlashAttention-3` makes deployment practical, but it does not evaluate a real disaggregated cluster manager or a heterogeneous multi-node setup. Finally, although the authors argue that TPLA could be trained from scratch, they do not actually show that training recipe, and they acknowledge that TPLA's duplicated-head structure would increase training cost.

## Related Work

- _DeepSeek-AI (arXiv '24)_ — DeepSeek-V2 introduces `MLA`, and TPLA can be read as a deployment-oriented extension that preserves MLA's checkpoint format while fixing its tensor-parallel KV-cache replication problem.
- _Zadouri et al. (arXiv '25)_ — `GLA` also shards latent attention for faster decoding, but it reduces each head's visible latent capacity and therefore serves as TPLA's main negative reference point.
- _Zhong et al. (OSDI '24)_ — DistServe separates prefill and decode into different serving stages; TPLA borrows the same phase distinction but changes the attention computation so decode itself is lighter.
- _Meng et al. (arXiv '25)_ — TransMLA shows how to convert non-MLA checkpoints into MLA, and this paper uses that bridge to argue that TPLA can eventually apply beyond models that were originally trained with MLA.

## My Notes

<!-- empty; left for the human reader -->

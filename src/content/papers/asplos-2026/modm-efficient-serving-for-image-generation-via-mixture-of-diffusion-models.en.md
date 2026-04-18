---
title: "MoDM: Efficient Serving for Image Generation via Mixture-of-Diffusion Models"
oneline: "MoDM caches final images, refines cache hits with a cheaper diffusion model, and reallocates GPUs online to raise throughput without giving up large-model quality."
authors:
  - "Yuchen Xia"
  - "Divyam Sharma"
  - "Yichao Yuan"
  - "Souvik Kundu"
  - "Nishil Talati"
affiliations:
  - "University of Michigan, Ann Arbor, MI, USA"
  - "Intel Labs, Los Angeles, CA, USA"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3760250.3762220"
code_url: "https://github.com/stsxxx/MoDM"
tags:
  - ml-systems
  - caching
  - gpu
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

MoDM argues that the right cache unit for diffusion serving is the final image, not a model-specific latent. On a cache hit, it retrieves a visually aligned image with CLIP, adds noise to jump back to an intermediate timestep, and finishes only the remaining denoising steps on a smaller model. A global monitor then shifts GPUs between large and small models as load changes, giving the system much better throughput and SLO behavior than single-model serving while keeping image quality much closer to the large model than naive small-model baselines.

## Problem

The paper starts from a familiar deployment problem for text-to-image APIs: good images come from large diffusion models, but those models are slow because inference still requires dozens of denoising steps. Smaller models and distilled variants cut latency, but they also lose fidelity. A provider therefore faces a bad choice between quality and responsiveness, especially when request rates spike.

Prior caching systems help, but not enough. Nirvana-style latent caching reuses intermediate representations from earlier prompts, which saves some work, yet the cache entries are tied to one model family. That means the system cannot freely mix a high-quality model for misses with a cheaper model for hits. The paper also points out the storage cost: with their Stable Diffusion-3.5-Large example, multiple latent snapshots take about 2.5 MB per image, versus 1.4 MB for the final image alone. Even with a very high hit rate, the reported compute reduction of prior work is limited, so bursty workloads still trigger long queues and SLO misses.

The deeper systems problem is therefore not just "make one diffusion model faster." It is "build a serving stack that can adapt online between latency and quality, without locking the cache to one model and without collapsing under changing request rates."

## Key Insight

MoDM's key claim is that final-image caching exposes a reusable boundary between models. If the cache stores only completed images plus their embeddings, the retrieved artifact can seed generation for any compatible diffusion model family. That makes cross-model serving possible in a way latent caching cannot.

The second part of the insight comes from diffusion dynamics. Early denoising steps decide most of the coarse structure, while later steps refine details. So if a cached image is already visually close to the new prompt, the system can add calibrated noise, skip the first `k` steps, and let a smaller model do only the tail of the denoising trajectory. In other words, cached images preserve the expensive global structure, and the cheap model only edits the remaining details.

This only pays off if model allocation follows the same logic. Cache misses should keep going to a large model, because they need full generation from scratch. Cache hits are a different workload, and they can be moved to smaller models when the quality loss stays within a chosen bound. MoDM's contribution is to turn that observation into a concrete serving policy.

## Design

The design has two main control points: a request scheduler and a global monitor. The request scheduler embeds each prompt with CLIP, searches a cache of prior generated images, and treats the request as a hit only when cosine similarity exceeds a threshold. Unlike prior work, retrieval is text-to-image rather than text-to-text, because the authors show that visual alignment matters more than prompt-string similarity. Their figures compare CLIPScore and PickScore distributions and show that text-to-image retrieval gives better matches.

Once the scheduler finds a hit, it does not return the cached image directly. Instead, it injects noise according to the diffusion schedule and resumes generation from an intermediate timestep. MoDM restricts the skipped-step count `k` to `{5, 10, 15, 20, 25, 30}` and chooses among them with an empirical heuristic based on retrieval similarity. The paper sets a quality-retention target of at least `alpha = 0.95` relative to full large-model generation; on a held-out check, the heuristic reaches 99.7% of the baseline CLIP score while cutting denoising work.

Resource management is the second half of the system. Large-model workers prioritize cache misses, because those requests need all `T = 50` denoising steps. Small-model workers focus on refining hits. The global monitor records request rate, hit rate, and the distribution of chosen `k` values, then computes how many GPUs should host large versus small models. In quality-optimized mode it maximizes the number of large models while still meeting hit and miss workloads; in throughput-optimized mode it sends all hits to the small model and allocates GPUs in proportion to the weighted hit and miss demand. A PID controller smooths the reallocation so the system does not thrash under load changes.

The cache policy is deliberately simple. MoDM uses a FIFO-style sliding window rather than a more complicated utility policy, motivated by the observation that over 90% of cache-hit requests in DiffusionDB retrieve an image generated within the previous four hours. The paper also treats "cache only large-model outputs" versus "cache outputs from both large and small models" as a tunable design choice: caching everything raises hit rate and throughput, but slightly worsens FID.

## Evaluation

The implementation is in Python and PyTorch, with the scheduler, monitor, and workers in separate processes and PyTorch RPC for node communication. The experiments use four models: two large backbones, Stable Diffusion-3.5-Large and FLUX.1-dev, plus two smaller models, SDXL and SANA-1.6B. The main workloads are DiffusionDB, which carries real temporal locality, and MJHQ-30k, which is less production-like.

The headline throughput numbers are strong. On DiffusionDB with Stable Diffusion-3.5-Large as the baseline large model, MoDM reaches `2.5x` normalized throughput with SDXL and `3.2x` with SANA; on MJHQ the gains are smaller but still material at `2.1x` and `2.4x`. With FLUX as the large model, MoDM still reaches `2.4x-2.9x`, which supports the paper's portability claim across model families.

The SLO results are the most convincing systems evidence. Under a latency threshold of `2x` the large-model inference time, vanilla serving and Nirvana begin to violate SLOs once load passes roughly 5 requests per minute on 4x A40s or 14 requests per minute on 16x MI210s. MoDM keeps operating up to 10 requests per minute on A40s and 22 on MI210s under the same threshold, and up to 26 requests per minute on MI210s under the looser `4x` threshold. The appendix tail-latency plots tell the same story: baseline p99 latency climbs past 1000 seconds as load rises, while MoDM remains stable over a much wider region.

Quality is more nuanced, which is exactly what a reader should want to know. MoDM-SDXL keeps CLIPScore essentially on par with the large-model baseline on DiffusionDB (`28.70` versus `28.55`) and far better FID than running SDXL alone (`11.85` versus `16.29`). But it does not fully match the large model or Nirvana on FID (`6.29` and `9.01`, respectively). So the evaluation supports the central claim that MoDM improves the quality-performance frontier, not that it makes the trade-off disappear. The energy results reinforce the serving argument: `46.7%` savings with SDXL and `66.3%` with SANA relative to vanilla Stable Diffusion-3.5-Large.

## Novelty & Impact

Relative to _Agarwal et al. (NSDI '24)_, MoDM's main novelty is replacing latent caching with final-image caching so the cache can be reused across model families and paired with a different refinement model. Relative to _Ma et al. (CVPR '24)_, which accelerates diffusion through intermediate-feature caching, MoDM is more of a serving-system paper: the novelty is not just faster sampling, but the combination of retrieval, adaptive `k` selection, online GPU allocation, and mixed-model execution. Relative to _Ahmad et al. (MLSys '25)_, which studies query-aware model scaling, MoDM contributes a cache-centered way to decide when a small model is safe.

That makes the paper relevant to operators of hosted image-generation APIs and to systems researchers interested in multi-model AI serving. It is one of the clearer attempts to treat diffusion inference as a dynamic resource-management problem instead of a fixed-model optimization problem.

## Limitations

MoDM depends heavily on temporal locality. The FIFO cache works because DiffusionDB shows that most useful reuse happens within four hours; on MJHQ, where that locality is weaker, the gains drop. The system also assumes offline profiling for each model pair and uses an empirical CLIP-based heuristic for cache-hit thresholds and `k` selection, so portability is not automatic even if the cache format is model-agnostic.

The quality story also remains a real trade-off. MoDM clearly beats standalone small models, but its FID is still noticeably worse than the large-model baseline, and sometimes worse than Nirvana. That matters if a deployment values distribution fidelity more than throughput. Finally, the paper does not isolate the operational cost of dynamic model switching, cache warm-up, or embedding maintenance; those costs may be acceptable, but the evaluation mostly treats them as backgrounded system plumbing rather than first-class bottlenecks.

## Related Work

- _Agarwal et al. (NSDI '24)_ — Nirvana accelerates diffusion serving with latent caching, whereas MoDM changes the cache object itself to enable cross-model reuse and smaller-model refinement.
- _Ma et al. (CVPR '24)_ — DeepCache reuses intermediate features inside a single diffusion model; MoDM instead caches final images and builds a full serving policy around model mixing and request routing.
- _Lu et al. (ECCV '24)_ — RECON retrieves concept prompt trajectories to speed text-to-image synthesis, while MoDM focuses on production serving with explicit cache management and SLO-aware GPU allocation.
- _Ahmad et al. (MLSys '25)_ — DiffServe chooses model scale based on the query, and MoDM is complementary in using cached visual context to decide when cheaper refinement is sufficient.

## My Notes

<!-- empty; left for the human reader -->

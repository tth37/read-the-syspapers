---
title: "Bayesian Code Diffusion for Efficient Automatic Deep Learning Program Optimization"
oneline: "Bayesian Code Diffusion clusters similar subgraphs, reuses a strong prior schedule, and diffuses its parameters to cut auto-tuning time by up to 3.31x."
authors:
  - "Isu Jeong"
  - "Seulki Lee"
affiliations:
  - "Ulsan National Institute of Science and Technology (UNIST)"
conference: osdi-2025
code_url: "https://github.com/eai-lab/BayesianCodeDiffusion"
tags:
  - compilers
  - gpu
  - ml-systems
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Bayesian Code Diffusion speeds up tensor-program auto-tuning by treating a well-optimized schedule for one subgraph as a prior for similar subgraphs, then searching nearby instead of restarting from random schedules. Implemented inside Ansor, it cuts compilation time by up to 3.31x while usually matching and sometimes slightly improving the final program latency.

## Problem

The paper targets a practical bottleneck in deep learning compilers such as TVM and Ansor. Auto-tuners can find fast tensor-program schedules, but the search is expensive because each subgraph is treated almost independently, candidate schedules are often initialized randomly, and the cost model learns online from whatever measurements the current search happens to collect. For models with repeated operators, the compiler ends up paying for similar searches many times.

The authors isolate three missed opportunities: similar subgraphs do not reuse tuned schedules, fine-tuning begins from weak random starting points, and the cost model sees overly broad and redundant data early. Prior work improves parts of this pipeline, but usually with one-shot transfer, restricted operator coverage, or CPU-only or GPU-only applicability.

## Key Insight

The core claim is that schedule search should reuse optimized schedules as priors. If one subgraph has already found a good parameter setting, that schedule is evidence about where good schedules for similar subgraphs are likely to lie.

This works because similar subgraphs often share the same Ansor sketch and have nearby optimal parameters. Instead of restarting from the full search space, Bayesian Code Diffusion begins from the prior schedule and diffuses its parameters outward. The same logic is applied to learning: pre-train the cost model on diverse priors, then fine-tune it on each cluster's posteriors.

## Design

The implementation has three stages. First, it clusters subgraphs by sketch rather than only by operator type, because identical operators can still induce different optimization rules and different search spaces. Second, it chooses one prior subgraph per cluster using cosine similarity over tensor-dimension vectors, then gives that prior a larger optimization budget. This is also the cost model's pre-training phase, since priors from different clusters produce diverse measurements.

Third, it tunes the remaining posterior subgraphs by code diffusion. The Bayesian story is that good posterior parameters should both lower latency and stay near the prior distribution; the implementation approximates that inside Ansor's schedule rules. For `InitFillTileSize`, the paper gives three diffusion modes: directly reuse split factors when loop extents match, map the prior factors to the nearest valid divisors when extents differ, or rescale them according to the extent ratio. A randomized path is kept for diversity, and all diffused candidates are still fine-tuned afterward.

The cost model itself is unchanged: the system keeps Ansor's XGBoost predictor. The gain comes from changing the training order so that diverse priors broaden the model first and cluster-specific posteriors refine it later.

## Evaluation

The prototype is implemented on top of Ansor in TVM and evaluated on an Intel Core i9-11900K CPU and an NVIDIA A6000 GPU across ten models, including ResNet-18, MobileNet, BERT, VGG, and EfficientNet. The main metric is how long each method takes to reach Ansor's best program latency.

Bayesian Code Diffusion is consistently faster on that metric: average compilation speedup over Ansor is 2.52x on CPU and 2.00x on GPU, with maxima of 3.31x and 2.79x. Program quality is preserved. The paper reports final execution latencies up to 1.13x faster than prior methods, and the first diffused programs are already strong, reaching up to 1.65x speedup on MXNet and 1.47x on BERT on GPU.

The ablations help support the mechanism. Subgraph-cluster experiments show an average 2.11x optimization speedup over Ansor. A separate experiment changes only the cost-model training order and still reaches good latencies faster than Ansor's default training order. The sparsity analysis is also informative: CPU gains correlate more with sketch sparsity, while GPU gains correlate more with operator sparsity, which matches the paper's claim that prior propagation matters more on CPU and cost-model learning strategy matters more on GPU.

## Novelty & Impact

Compared with _Zheng et al. (OSDI '20)_, the paper changes the unit of reuse: tuned schedules and measurements become priors for other subgraphs rather than isolated artifacts. Compared with _Gibson and Cano (PACT '22)_, it performs reuse online within the current model instead of requiring a separately precompiled donor model. Compared with _Li et al. (ICPP '23)_, it transfers schedule parameters, not just cost-model specialization.

The lasting idea is simple and useful: repeated subgraphs should induce connected search spaces, not independent ones. That is the kind of mechanism later auto-tuners and tensor compilers can plausibly inherit.

## Limitations

The paper is explicit that the Bayesian framing is only partly realized. The true prior distribution over optimal schedule parameters is unknown, so the implementation uses hand-designed diffusion rules inside Ansor, and those rules may not transfer cleanly to other compilers.

Prior selection is also heuristic: tensor-shape similarity is useful but not always best. Gains depend on repetition, so models with high sketch sparsity or tiny clusters offer fewer reuse opportunities. The cost model also remains Ansor's unchanged XGBoost model, leaving additional headroom outside the paper's current design.

## Related Work

- _Zheng et al. (OSDI '20)_ - Ansor automatically generates sketches and tunes them well, but each subgraph still pays for an essentially separate search.
- _Gibson and Cano (PACT '22)_ - Transfer-Tuning reuses schedules from a different precompiled model, whereas Bayesian Code Diffusion reuses priors online inside the current model and supports both CPU and GPU.
- _Zheng et al. (MLSys '22)_ - DietCode reduces dynamic tensor-program search cost with a unified GPU-oriented search space, but it supports a narrower operator set than this paper targets.
- _Li et al. (ICPP '23)_ - FamilySeer groups similar subgraphs for cost-model training, while Bayesian Code Diffusion also diffuses schedule parameters across those subgraphs.

## My Notes

<!-- empty; left for the human reader -->

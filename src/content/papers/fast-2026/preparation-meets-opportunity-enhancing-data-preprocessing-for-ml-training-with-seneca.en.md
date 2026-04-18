---
title: "Preparation Meets Opportunity: Enhancing Data Preprocessing for ML Training With Seneca"
oneline: "Seneca models the ML input pipeline to split cache across encoded, decoded, and augmented data, then rewrites random batches to favor cache hits across concurrent jobs."
authors:
  - "Omkar Desai"
  - "Ziyang Jiao"
  - "Shuyi Pei"
  - "Janki Bhimani"
  - "Bryan S. Kim"
affiliations:
  - "Syracuse University"
  - "Huaibei Normal University"
  - "Samsung Semiconductor"
  - "Florida International University"
conference: fast-2026
category: ai-era-storage
code_url: "https://github.com/swiftomkar/seneca-fast26-pytorch"
tags:
  - ml-systems
  - caching
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Seneca treats ML input preprocessing as a joint cache-allocation and sampling problem. Its Model-Driven Partitioning (MDP) chooses how much memory to devote to encoded, decoded, and augmented data, and its Opportunistic Data Sampling (ODS) rewrites random minibatches to prefer cache hits without violating epoch semantics. Across concurrent jobs, it cuts makespan by `45.23%` versus PyTorch and improves DSI throughput by up to `3.45×` over the next-best dataloader.

## Problem

The paper targets the data storage and ingestion (DSI) pipeline for multimedia and recommendation training, where CPUs fetch, decode, transform, augment, and collate data before GPUs can consume it. The authors argue that this stage is becoming a worse bottleneck over time because GPU throughput has grown faster than CPU preprocessing throughput. On the systems they measure, the gap between preprocessing throughput and training throughput for SwinT widens from `4.63×` on an RTX 5000 server to `7.66×` on an A100 server, so faster accelerators expose DSI stalls more sharply.

Two specific failures make prior caching insufficient. First, data appears in three materially different forms: encoded data is compact but expensive to decode, decoded data saves decode work but is inflated, and augmented data is most training-ready but least reusable across epochs. The right answer changes with cache size and hardware. With `450 GB` of cache, storing preprocessed data cuts preprocessing time by `69.91%` while fetch time rises only `34.85%`; with `250 GB`, the same choice yields only `11.36%` preprocessing relief but raises fetch time by `87.2%`. Second, concurrent jobs over the same dataset do not naturally help one another because random sampling ignores what is already cached. On OpenImages, four PyTorch jobs perform `7.16` million preprocessing operations for `1.7` million samples, and simply adding a shared cache improves aggregate throughput by only `11.81%`.

## Key Insight

The paper's core claim is that the preprocessing bottleneck should be optimized at two levels at once: cache space must be partitioned across data forms using a performance model, and random sampling must be relaxed from "follow this fixed pseudo-random order" to "consume each sample once per epoch in an order that still appears random." That combination matters because the value of caching a sample depends on whether the bottleneck is storage, CPU decode, CPU augmentation, network, PCIe, or GPU ingestion, while the value of sharing cache across jobs depends on whether the sampler can capitalize on hits created by other jobs. If the system reasons explicitly about both questions, concurrent training becomes cooperative instead of redundant.

## Design

MDP models four mutually exclusive access cases: the requested sample is already cached in augmented form, decoded form, encoded form, or only in storage. For each case, Seneca estimates DSI throughput as the minimum of the relevant service bandwidths and hardware rates, including remote cache or storage bandwidth, CPU decode or augmentation throughput, GPU ingestion, and network and PCIe transfer costs; it also incorporates gradient communication overhead in distributed training. The model then computes how many samples fit in each tier under a cache split `xE`, `xD`, and `xA`, weighted by data inflation `M`, and combines the four cases into one predicted overall throughput. Seneca searches the partition space at `1%` granularity with a brute-force sweep, which the authors say takes less than `1` second and is typically done once per dataset.

ODS is the runtime policy that makes shared caching useful. For each job, it keeps a seen-bit vector recording which samples have already been consumed in the current epoch. For each dataset, it stores per-sample state and a reference count describing whether the sample is cached as augmented, decoded, encoded, or only in storage. When a batch request arrives, ODS finds the misses, replaces them with cached hits that the requesting job has not yet seen, increments reference counts, and returns the modified batch. When a cached sample's reference count reaches the configured threshold, a background thread evicts it and fills the space with new random samples from storage. With the threshold set to the number of concurrent jobs, augmented samples are not reused across epochs, while each job still sees each sample once per epoch.

The implementation is pragmatic rather than exotic. Seneca modifies PyTorch `v1.12.0` by about `4200` lines and uses Redis as the cache backend, but the design is meant to be a drop-in dataloader replacement rather than a new training framework.

## Evaluation

The paper first validates the MDP model itself on four configurations: one and two in-house servers, AWS `p3.8xlarge`, and Azure `NC96ads_v4`. Across `24` modeled-versus-measured combinations, the Pearson correlation is at least `0.90`, which matters because the rest of the design depends on using that model to choose cache partitions. The evaluation then spans seven models from `3.4` million to `633.4` million parameters, three datasets from `142 GB` to `1.4 TB`, and five hardware configurations.

The most convincing end-to-end result is that the design improves training time without changing accuracy trends. On ImageNet-1K over `250` epochs on Azure, Seneca reaches the same convergence pattern as PyTorch and DALI with less than `2.83%` final-accuracy error, while reducing training time by `48.51%` for ResNet-18, `38.09%` for ResNet-50, `49.16%` for VGG-19, and `47.83%` for DenseNet-169 relative to PyTorch. In a scheduler-driven AWS experiment with `12` jobs arriving over time and at most two concurrent jobs, Seneca reduces total makespan to `45.23%` of PyTorch by sharing preprocessing work instead of repeating it independently.

The concurrency and scaling data support the paper's central argument. On two Azure nodes, Seneca scales to `1.89×` the throughput of one node and still beats MINIO by `42.39%`. On a single Azure server with up to four concurrent jobs, it outperforms Quiver by `1.81×` at four jobs, and Table 8 shows why: Seneca drives GPU utilization to `98%` while PyTorch, DALI, MINIO, and Quiver remain limited by I/O and CPU preprocessing. ODS also improves cache efficiency materially, reaching a `54%` hit rate with only `20%` of ImageNet-1K cached and `66%` with `40%` cached. The regime where Seneca wins is therefore not narrow; it extends across small and large datasets, single-node and distributed runs, and both cold and warm epochs.

## Novelty & Impact

Relative to _Graur et al. (ATC '24)_ and _Graur et al. (ATC '22)_, Seneca is not mainly about where to run transforms or how to expose preprocessing as a service. Its novelty is that it treats the cache as a three-form resource-allocation problem and then couples that choice with a sampler that exploits inter-job reuse. Relative to _Khan et al. (FAST '23)_ and _Kumar and Sivathanu (FAST '20)_, Seneca is built for concurrent jobs that share a dataset: it keeps Quiver's intuition that substitution can raise hit rate, but avoids oversampling by operating within epoch semantics, and it avoids SHADE's dependence on job-specific importance. That makes the paper relevant to ML systems researchers working on dataloaders, remote caches, and multi-tenant training infrastructure. The main contribution is a new mechanism plus a clearer framing of preprocessing as a systems bottleneck that must be modeled and scheduled, not merely cached.

## Limitations

Seneca's benefits depend on assumptions that are reasonable but not universal. MDP needs profiled system parameters such as CPU throughput, cache bandwidth, storage bandwidth, and sample inflation; the paper does not show how robust the chosen partition is when those values drift during a long run or when multiple datasets compete for the same cache. ODS is strongest when concurrent jobs share a dataset and similar preprocessing pipelines. If workloads are heterogeneous, or if a training job has little preprocessing work to amortize, the substitution opportunity shrinks.

The empirical coverage is also narrower than the paper's ambition. Most end-to-end results are on image models, even though the paper claims applicability to audio, recommendation, and other preprocessing-heavy jobs. The cache backend is Redis, so the paper does not explore whether a slower or more failure-prone cache service would change the tradeoff. Finally, the paper shows that accuracy is not visibly harmed, but it does not provide a deeper theoretical argument about when ODS's relaxed pseudo-random ordering is equivalent to the original sampling distribution.

## Related Work

- _Graur et al. (ATC '24)_ — Pecan optimizes transformation ordering and placement, while Seneca explicitly partitions cache across encoded, decoded, and augmented forms and then changes sampling to exploit that partition.
- _Lee et al. (ATC '21)_ — Revamper reuses partially augmented samples, whereas Seneca reasons across three cache tiers and uses per-epoch reference thresholds to avoid reusing augmented data across epochs.
- _Khan et al. (FAST '23)_ — SHADE improves cacheability through importance sampling, but Seneca is aimed at shared-cache concurrency rather than per-job importance and performs well with multiple simultaneous jobs.
- _Kumar and Sivathanu (FAST '20)_ — Quiver also substitutes cached samples for misses, but Seneca couples substitution with model-based cache partitioning and avoids Quiver's `10×` oversampling overhead.

## My Notes

<!-- empty; left for the human reader -->

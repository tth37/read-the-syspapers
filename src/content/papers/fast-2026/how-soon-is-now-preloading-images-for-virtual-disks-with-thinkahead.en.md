---
title: "How Soon is Now? Preloading Images for Virtual Disks with ThinkAhead"
oneline: "ThinkAhead learns per-image boot traces and runtime bandwidth bins to preload VD blocks before first access, sharply reducing lazy-loading slow I/Os in EBS."
authors:
  - "Xinqi Chen"
  - "Yu Zhang"
  - "Erci Xu"
  - "Changhong Wang"
  - "Jifei Yi"
  - "Qiuping Wang"
  - "Shizhuo Sun"
  - "Zhongyu Wang"
  - "Haonan Wu"
  - "Junping Wu"
  - "Hailin Peng"
  - "Rong Liu"
  - "Yinhu Wang"
  - "Jiaji Zhu"
  - "Jiesheng Wu"
  - "Guangtao Xue"
  - "Patrick P. C. Lee"
affiliations:
  - "Shanghai Jiao Tong University, China"
  - "Alibaba Group, China"
  - "Shanghai Key Laboratory of Trusted Data Circulation, Governance and Web3, China"
  - "The Chinese University of Hong Kong, China"
conference: fast-2026
category: cloud-and-distributed-storage
code_url: "https://github.com/Master-Chen-Xin-Qi/FAST26_AE"
tags:
  - storage
  - virtualization
  - caching
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ThinkAhead preloads snapshot blocks for virtual disks before the guest touches them. It learns per-image boot access patterns from production traces, reorders blocks by access density and time under current bandwidth, and falls back to metadata-based zero-shot selection when history is sparse. In Alibaba EBS, this raises the hit rate by up to `7.27x` over lazy loading and cuts P99 wait latency by up to `98.7%`.

## Problem

Cloud EBS services keep VM images in remote object storage and materialize them into block volumes on demand. Full eager loading is too slow: the paper says a `40 GiB` image at `20 MB/s` would take about `34 minutes`, so production systems use lazy loading to let a VM start almost immediately. The catch is that the first miss to an unloaded block now waits for an OSS pull, turning cold-start cost into long-tail I/O stalls during boot.

Alibaba's field data shows this is not a niche issue. Across a year of production diagnosis, lazy loading explains `39.35%` of all slow I/Os in the EBS software stack, with P99 lazy-load latency up to `7 s`. The first six minutes after VD creation are the danger zone: more than `95%` of slow I/Os happen there. Existing mitigations are misaligned with this setting. Regional caches and peer-to-peer distribution struggle because image popularity and placement vary sharply across clusters and time, and new image abstractions such as FlacIO require I/O-path and format changes that do not fit a large EBS deployment.

## Key Insight

The paper's key claim is that boot-time access patterns are predictable enough to preload the right blocks, but only if the scheduler ranks blocks by both value and timeliness rather than replaying a historical trace literally. VDs created from the same image have strong intra-image similarity, and only a small fraction of LBAs are touched in the first minutes of boot. That means preloading can eliminate most lazy-load stalls if it pulls the small set of high-value blocks early enough.

The non-obvious part is that exact access order is not the right target. Under constrained bandwidth, blocks that are accessed frequently and early should outrank blocks that merely appear first once. ThinkAhead therefore treats preloading as an optimization problem over access count, average access time, minimum access time, and current bandwidth, rather than as pure trace replay.

## Design

ThinkAhead has three pieces. First, dataset preprocessing cleans the per-VD trace sequences collected from the first six minutes of boot. For each image, it looks at the distribution of unique accessed block counts, trims the top and bottom `2.5%` of outliers, partitions traces into categories around local maxima, and then clusters traces within a category using Pearson correlation. Each cluster yields a centroid trace that represents one stable boot pattern while tolerating reordering and dropped requests.

Second, score-based block selection turns a centroid into an actual preload order. Each block gets a score that combines normalized access count, average access time, and minimum access time. The weights are trained offline with a genetic algorithm separately for bandwidth bins, because the best ordering at `5 MB/s` is not the best ordering at `80 MB/s`. At runtime, ThinkAhead picks the current bin, generates a preload sequence, and can switch to another centroid if incoming accesses look more like a different group. The central system then downloads blocks through three priority queues: missed blocks first, predicted near-future blocks second, and the remaining blocks last.

Third, zero-shot prediction covers images with little or no history. ThinkAhead chooses donor traces hierarchically: same image family first, then same user, then the closest metadata match such as ISO version and performance level. If that still leaves too few traces, it relaxes the filter. The design explicitly trades some precision for deployability: training takes hours offline, but inference stays within milliseconds and the learned parameters are reused across clusters.

## Evaluation

The evaluation is broad enough to support the main claim. The simulator replays traces from about `160,000` VDs created from about `2,500` images, split `80/20` into train and test, and explores both public and user-defined images across bandwidths from a few MB/s to `80 MB/s`. ThinkAhead achieves up to `7.27x` higher hit rate than lazy loading on public images and up to `2.64x` on user-defined images. Under low bandwidth, it also drives P99 wait latency down by up to `79.8%` versus lazy loading, and in zero-shot cases it improves P99 wait latency by up to `98.7%` while staying within `1%` of the oracle-like History-based baseline.

The paper also compares against stronger alternatives than lazy loading: Leap, DADI+, count/time heuristics, and a History-based policy that replays the test trace's exact order. ThinkAhead usually beats the heuristic baselines because it adapts to bandwidth and does not overcommit to sequential order. More interestingly, it can outperform History-based on hit rate and median latency because replaying order alone ignores access density and causes queueing when bandwidth is tight. In the production-cluster end-to-end experiment, ThinkAhead improves Snapshot Worker wait latency by `3.20x` at P50, `1.35x` at P99, and `1.26x` at the maximum, reduces cold-start latency by `1.46x`, and cuts slow-I/O count by `5.35x`.

## Novelty & Impact

Relative to _Li et al. (USENIX ATC '20)_, ThinkAhead is not just block-trace replay for image service; it adds trace cleaning, bandwidth-aware scoring, and a zero-shot path for sparse-history images in a production EBS setting. Relative to _Liu et al. (FAST '25)_, it avoids changing the image abstraction or I/O path, which is a meaningful systems contribution when the target is an existing commercial block store. Relative to _Cao et al. (USENIX ATC '24)_, the novelty is not a generic prefetching hook but a workload-specific preloading policy tuned to VD boot behavior.

The likely impact is practical. Cloud storage teams that already collect VD boot traces can deploy it without GPUs or special hardware, and the paper contributes a rare production-scale dataset and diagnosis of why lazy loading fails in EBS. The work is mostly a new mechanism built on a strong measurement study rather than a new theoretical model.

## Limitations

The strongest caveat is dependence on history. The paper handles zero-shot images better than the baselines, but the entire approach still assumes that image family, user, and metadata predict future boot behavior well enough. If boot behavior changes because the image is heavily mutated, or if traffic comes from workloads that do not resemble OS boot, ThinkAhead will lose accuracy and can fall back toward lazy-loading behavior.

A second limitation is operational scope. Training is the most expensive part, taking more than two hours offline, and the paper does not fully quantify how often retraining is needed as images evolve. The production evaluation is also narrower than the trace-driven simulation: it confirms end-to-end benefit, but it does not deeply study multi-tenant interference, fairness across simultaneous image pulls, or the impact of wrong bandwidth-bin choices under sudden congestion. Finally, because all fetched blocks will eventually be used, the paper optimizes hit rate more than bandwidth waste; that assumption is reasonable for image booting but not for general-purpose prefetching.

## Related Work

- _Li et al. (USENIX ATC '20)_ — DADI preloads overlay-based block images from prior traces, but ThinkAhead targets remote snapshot loading in production EBS and explicitly adapts to bandwidth variation and sparse history.
- _Liu et al. (FAST '25)_ — FlacIO redesigns container image service around a new runtime image abstraction, whereas ThinkAhead keeps standard VD images and optimizes only block arrival order.
- _Cao et al. (USENIX ATC '24)_ — FetchBPF provides customizable kernel prefetching mechanisms; ThinkAhead contributes the learned policy and trace-processing pipeline for EBS image boot.
- _Chang et al. (USENIX ATC '25)_ — Poby accelerates container image provisioning with SmartNIC assistance, while ThinkAhead works at block level for VM and system-disk images without assuming special network hardware.

## My Notes

<!-- empty; left for the human reader -->

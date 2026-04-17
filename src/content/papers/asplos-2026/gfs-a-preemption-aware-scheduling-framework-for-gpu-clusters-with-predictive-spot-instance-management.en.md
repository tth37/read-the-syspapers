---
title: "GFS: A Preemption-aware Scheduling Framework for GPU Clusters with Predictive Spot Instance Management"
oneline: "Forecasts per-tenant HP GPU demand, derives dynamic spot quotas, and preempts with checkpoint-aware cost to cut evictions and queueing in GPU clusters."
authors:
  - "Jiaang Duan"
  - "Shenglin Xu"
  - "Shiyou Qian"
  - "Dingyu Yang"
  - "Kangjin Wang"
  - "Chenzhi Liao"
  - "Yinghao Yu"
  - "Qin Hua"
  - "Hanwen Hu"
  - "Qi Wang"
  - "Wenchao Wu"
  - "Dongqing Bao"
  - "Tianyu Lu"
  - "Jian Cao"
  - "Guangtao Xue"
  - "Guodong Yang"
  - "Liping Zhang"
  - "Gang Chen"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "The State Key Laboratory of Blockchain and Data Security, Zhejiang University, Hangzhou, China"
  - "Alibaba Group, Hangzhou, China"
  - "Zhejiang University, Hangzhou, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762231"
code_url: "https://github.com/Sjtucitlab/Spot"
tags:
  - scheduling
  - gpu
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

GFS targets a practical GPU-cluster problem: cloud operators want to sell spare GPUs as spot capacity, but static quotas and reactive scheduling make spot jobs unstable and still leave expensive GPUs under-allocated. The paper's answer is a closed loop that forecasts high-priority demand, turns that forecast into a time-varying spot quota, and only preempts spot jobs when a checkpoint-aware cost model says the damage is minimal.

## Problem

The paper is motivated by a shift in production GPU clusters after the rise of LLMs. Compared with 2020 traces, the 2024 cluster the authors study sees far more full-card and full-node requests, much longer task runtimes, and substantial queuing for 8-GPU gang-scheduled jobs. In that environment, the old arrangement of "reserve enough GPUs for high-priority jobs and sell the rest as spot" stops working well because demand spikes are sharp, long-lived, and organization-specific.

The failure mode is two-sided. If the provider keeps static spot quotas large, high-priority jobs arrive and evict spot jobs aggressively; the paper reports week-level average spot eviction around 49.5%, with peaks above 93% during busy hours. If the provider is conservative instead, large A100/A800/H800 pools still show allocation rates below 80%, so the cluster leaves money on the table. First-fit placement makes this worse by fragmenting nodes and mixing job types in ways that later force more disruptive preemptions. The core question is therefore not merely how to schedule one queue faster, but how to jointly manage prediction, quota setting, and placement so that HP jobs meet SLOs while spot jobs still get usable guaranteed windows.

## Key Insight

The paper's main claim is that spot instability in GPU clusters is largely a control-loop problem rather than just a local placement problem. If the scheduler can estimate future HP demand as a distribution instead of a single point, it can reserve capacity at a chosen guarantee rate, expose only the remaining inventory to spot jobs, and then make preemption decisions with explicit awareness of checkpoint waste and node eviction history.

That matters because each layer corrects a different source of loss. Forecasting addresses overcommitment during demand surges. Dynamic quotas prevent a conservative forecast from freezing too much capacity when real eviction is low but spot queues are growing. Preemption-aware placement then converts the quota into concrete node choices that preserve packing for future HP jobs while avoiding repeated damage to the same spot jobs. The paper's contribution is the coupling of those three layers into one operational system.

## Design

GFS has three modules. `GDE` forecasts per-organization HP GPU demand over a future horizon. Its model, OrgLinear, decomposes each organization's history into trend and cyclical components, adds temporal features such as hour, weekday, and holiday, and adds business-context features such as cluster and GPU model. Instead of outputting only a mean forecast, it predicts both mean and variance, so GFS can choose an upper quantile as a safe demand bound for quota planning.

`SQA` converts those forecasts into spot quotas. It first computes a cluster-level guaranteed inventory by summing organization-level high-quantile demand bounds and subtracting that from cluster capacity. It then multiplies the result by a safety coefficient `eta`, but `eta` is not fixed. If recent spot eviction exceeds the target by a wide margin, GFS shrinks `eta`; if eviction is low but maximum spot queuing is high, GFS grows `eta`. This gives the system a feedback path between long-horizon forecasts and current operating conditions.

`PTS` is the runtime scheduler. For non-preemptive placement it scores candidate nodes along three dimensions: GPU packing, homogeneous co-location of HP with HP and spot with spot, and eviction awareness from short- and long-term node histories. If an HP task still cannot be placed, GFS considers preemption. The key heuristic is to sort candidate spot victims by wasted work since the last checkpoint and to choose the node with minimum combined cost from eviction impact and wasted GPU time. Spot jobs themselves are never scheduled preemptively; only HP jobs can trigger preemption.

## Evaluation

The evaluation uses both production deployment and trace-driven simulation, which is important because the forecasting and quota logic are only meaningful with realistic cluster dynamics. In production, after deployment on the largest cluster, spot eviction drops below 10% across GPU models, with A100 eviction improving by 67.81%. Allocation rate also rises materially: A800 improves by 22.79%, A100 by 14.03%, and the paper estimates about $459,715 in monthly gains.

In simulation on a 2,296-A100 cluster, GFS is compared against YARN-CS, Chronus, Lyra, and FGD under low, medium, and high spot loads. For HP jobs, the most robust result is queuing time: GFS cuts average HP JQT by 60.17%-70.81% while keeping p99 JCT unchanged at 29,304.5 seconds. For spot jobs, average improvements are 14.24% lower JCT, 44.10% lower JQT, and 33.01% lower eviction rate. Under the medium workload, for example, GFS reduces spot JQT to 575.4 seconds, far below the 1,211.7-5,450.5 second range of the baselines.

The ablations are especially useful because they show each module matters. Replacing OrgLinear with a naive previous-week-peak estimator raises spot JQT from 575.4 to 10,502.4 seconds and eviction from 1.21% to 8.08%. Disabling SQA's feedback path raises spot JQT to 2,174.3 seconds. Simplifying the scheduler's non-preemptive and preemptive logic also hurts spot performance materially. That evidence supports the paper's central thesis better than the topline comparisons alone.

## Novelty & Impact

Relative to _Gao et al. (SoCC '21)_, GFS is not just another deadline-aware scheduler; it adds demand-distribution forecasting and quota adaptation specifically for the provider-side spot market in GPU clusters. Relative to _Bai et al. (OSDI '20)_, its novelty is not faster context switching, but deciding when and where preemption should happen in the first place. Relative to application-side spot systems such as _Athlur et al. (EuroSys '22)_, GFS moves the optimization target from one training job to whole-cluster efficiency.

That makes the paper useful to both researchers and practitioners working on multi-tenant GPU clouds. It is a systems paper about operational control: predicting the right reservation, exposing the right amount of spot capacity, and paying the smallest possible price when HP jobs reclaim GPUs.

## Limitations

GFS depends on reasonably accurate demand forecasts and on metadata such as organization, cluster, and GPU type, so its quality may drop if those signals are noisy or if workload regimes change abruptly. Its preemption model also assumes checkpointed jobs, which means the benefit is smaller for workloads that checkpoint rarely or carry large restart costs not captured by elapsed time since checkpoint.

The evaluation is strong for the authors' environment but narrower than the paper's title may suggest. The detailed simulations center on one 2,296-A100 cluster, and the main efficiency metric is GPU allocation rate rather than direct SM utilization. The paper also does not specify how well the approach generalizes to multi-cluster routing or cross-cluster quota coordination, so that part remains an open deployment question.

## Related Work

- _Gao et al. (SoCC '21)_ — Chronus is deadline-aware and lease-based for DL training, whereas GFS adds probabilistic demand forecasting, dynamic spot quota control, and checkpoint-waste-aware preemption.
- _Bai et al. (OSDI '20)_ — PipeSwitch reduces runtime context-switch cost during preemption, while GFS focuses on cluster-level decisions about whether preemption should occur and which jobs should absorb it.
- _Athlur et al. (EuroSys '22)_ — Varuna adapts distributed training to spot instances from the application side; GFS instead manages spot reliability from the cloud provider's scheduling layer.

## My Notes

<!-- empty; left for the human reader -->

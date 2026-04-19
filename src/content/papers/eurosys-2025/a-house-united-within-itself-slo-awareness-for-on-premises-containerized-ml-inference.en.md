---
title: "A House United Within Itself: SLO-Awareness for On-Premises Containerized ML Inference Clusters via Faro"
oneline: "Faro relaxes latency SLOs into utilities, adds probabilistic forecasts, and reallocates replicas across a fixed Ray/Kubernetes inference cluster fast enough to cut violations."
authors:
  - "Beomyeol Jeon"
  - "Chen Wang"
  - "Diana Arroyo"
  - "Alaa Youssef"
  - "Indranil Gupta"
affiliations:
  - "University of Illinois Urbana-Champaign"
  - "IBM Research"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696071"
code_url: "https://dprg.cs.uiuc.edu/traces/go.php?id=40"
tags:
  - ml-systems
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Faro targets the hard case that most prior ML autoscalers dodge: many inference jobs sharing one fixed on-prem cluster, each with a latency SLO and bursty demand. It turns each SLO into a relaxed utility, predicts future load as a distribution rather than a point estimate, and solves a cluster-wide optimization quickly enough to rebalance replicas every few minutes. On Ray Serve over Kubernetes, the paper reports 2.3x-12.3x fewer SLO violations than prior baselines in right-sized clusters, and still 1.1x-1.5x fewer in heavily oversubscribed ones.

## Problem

The paper starts from an operational reality: enterprises often run ML inference on containerized on-prem clusters because they want portability, isolation, and internal control, but the usual deployment pattern is still one siloed cluster per team or per model. That wastes machines because inference traffic is highly time-varying and developers over-request capacity. Consolidating these jobs into a shared cluster is economically attractive, but then someone has to decide which model gets replicas when the total CPU and memory budget is fixed.

Existing autoscalers do not solve that problem cleanly. Ray Serve and Kubernetes HPA react to low-level signals such as CPU utilization or queue length, not developer-facing latency SLOs. Systems such as Barista, MArk, Cocktail, and INFaaS are mostly designed around a single job or around cloud cost minimization, where more capacity can often be bought. Swayam handles ML SLOs, but not a fixed shared cluster. Cilantro is multi-tenant and utility-based, yet the authors show it reacts too slowly for this workload mix: on their 32-replica setup with a 720 ms SLO, Cilantro sees an average 83.4% SLO violation rate versus 6.9% for Faro.

The timing mismatch is the real systems bottleneck. ML inference SLOs are sub-second, while replica cold starts are tens of seconds to minutes, and workloads can spike faster than a slow optimizer can react. A controller that computes the exact best allocation too slowly is operationally worse than a slightly approximate controller that can adapt before the spike passes.

## Key Insight

The key insight is that SLO-aware multi-tenant autoscaling should optimize a deliberately relaxed surrogate, not the exact SLO objective. Faro treats exactness itself as the enemy: step-function utilities, high-fidelity queue models, and point forecasts all create plateaus or brittle predictions that make optimization too slow. By softening each component just enough, Faro preserves the ordering that matters for allocation decisions while making the optimization solvable in under a second. That is why the paper emphasizes `sloppification` across the whole stack rather than a single heuristic: smooth utilities lower-bound SLO satisfaction, probabilistic forecasts expose likely spikes, and unstable queues become penalties instead of flat infinities.

## Design

Faro has four main pieces. First, each job exposes only a latency SLO: a target latency `s_i` and percentile. Faro distills that into an original step utility and then a relaxed utility `U(l_i, s_i) = min((s_i / l_i)^alpha, 1)`. For overload cases where requests must be dropped, it multiplies that utility by an AWS-style penalty derived from achieved availability, producing an effective utility. At cluster scope, the administrator can choose objective families such as total utility, fairness, or hybrids like Faro-FairSum and Faro-PenaltyFairSum.

Second, Faro estimates how many replicas each job needs. It uses either a pessimistic upper bound or an `M/D/c` queueing model, with an engineering approximation to speed percentile-latency estimation. The paper's example shows why this matters: with per-request time `p = 150 ms`, arrival rate `lambda = 40 req/s`, and SLO `s = 600 ms`, the upper-bound model asks for 10 replicas, whereas the `M/D/c` model needs only 8 at the 99.99th percentile. Faro then relaxes unstable queues using a utilization threshold `rho_max = 0.95`, avoiding the optimization plateaus created by infinite latency.

Third, Faro predicts workload probabilistically. Its predictor is based on N-HiTS, augmented with a Gaussian output model. Instead of choosing one future load trace, Faro samples 100 predictions and optimizes over the resulting window, which better captures bursts that RMSE-trained point predictors miss.

Finally, the autoscaler runs in three stages. Stage 1 formulates a per-job objective over the predicted 7-minute load window while accounting for replica cold start, which reached up to 70 seconds in the authors' runs. Stage 2 solves the multi-tenant constrained optimization under total vCPU and memory limits using COBYLA; hierarchical grouping with `G = 10` keeps solving scalable as job count rises. Stage 3 shrinks jobs that already have predicted utility 1 until cluster utility would change, reclaiming slack. Faro pairs this 5-minute predictive loop with a 10-second reactive loop that only scales up additively when observed SLO violations reveal forecast error. In implementation, Faro runs as a separate Kubernetes pod over Ray Serve v2.0.0, with one Ray subcluster per inference job and router-side metrics plus tail-drop at queue length 50.

## Evaluation

The deployment evaluation runs on IBM Cloud VPC with two `cx2-32x64` VMs, using ResNet34 inference jobs on PyTorch, one Ray Serve replica per worker pod, and cluster sizes varied through Kubernetes quotas. Workloads come from nine Azure Functions traces plus one Twitter trace, rescaled to 1-1600 requests per minute, with day 11 used for evaluation after ten days of predictor training. Baselines are FairShare, Oneshot, AIAD, and a combined MArk/Cocktail/Barista policy.

The strongest result is that Faro wins across both sufficient and insufficient cluster sizes. In the right-sized 36-replica cluster, it reduces cluster SLO violation rate by 2.3x-12.3x and lost cluster utility by 1.7x-9x versus baselines. When the cluster is slightly oversubscribed at 32 replicas, it still improves SLO violations by 2.8x-8.4x and lost utility by 2.5x-6.1x. Even in the heavily oversubscribed 16-replica case, it remains better by 1.1x-1.5x on SLO violations and 1.2x-1.5x on lost utility.

The evaluation also supports the paper's mechanism claim. The timeline plots show Faro holding maximum cluster utility for longer periods and recovering faster from transient spikes because the short-term autoscaler catches forecast misses. Mixed workloads with 50% ResNet18 and 50% ResNet34 still show 4x-23x lower SLO violation rates and 2.3x-13.1x lower lost utility. The ablation study is especially convincing: relaxation alone lowers lost cluster utility by 2.1x-3.7x, the hybrid autoscaler contributes up to 1.42x, and probabilistic prediction up to 1.36x. That is exactly the story the paper is trying to tell: the win comes from the whole relaxed control loop, not from any one queueing formula.

## Novelty & Impact

Faro's novelty is not a new autoscaling metric or a new serving engine by itself. The contribution is a complete control formulation for fixed-size multi-tenant inference clusters: convert human-facing SLOs into utilities, relax those utilities so local solvers can move quickly, combine probabilistic forecasting with queue-based capacity estimation, and then apply the result centrally across jobs that compete for the same resource budget. For systems researchers, that is a concrete argument that inference control should be posed as cluster-wide utility optimization rather than independent per-job scaling. For practitioners, it offers a design that can sit around existing Ray Serve and Kubernetes deployments instead of replacing them.

## Limitations

The paper is honest that Faro only autoscales replica counts; it does not solve placement, scheduling, or admission control. It relies on Kubernetes for pod placement and on router-side dropping when overload becomes unavoidable. The evaluation is also narrower than the paper's broader ambition: real deployments use homogeneous CPU-backed inference with ResNet models on IBM Cloud, and the largest scale result beyond 20 deployed jobs comes from a matched simulator rather than a live cluster. The authors explicitly call CPU/GPU mixes and heterogeneity an open challenge. More generally, Faro's queueing assumptions are inference-specific: Poisson arrivals, low-variance service times, and a utility formulation tailored to latency SLOs.

There is also a tradeoff inside Faro's own objective family. In heavily oversubscribed clusters, the fairness-oriented variants lose to Faro-Sum and Faro-PenaltySum because equitable sharing lowers aggregate utility when there simply are not enough replicas to satisfy everyone. That is not a bug, but it means operators still need to choose which global objective they actually want.

## Related Work

- _Gujarati et al. (Middleware '17)_ - Swayam proactively scales single ML inference jobs to meet SLAs efficiently, while Faro optimizes across multiple jobs that must share a fixed cluster budget.
- _Gunasekaran et al. (NSDI '22)_ - Cocktail performs proactive model-serving optimization for a single service and only scales up, whereas Faro adds multi-tenant downscaling and cross-job reallocation under hard cluster limits.
- _Zhang et al. (USENIX ATC '19)_ - MArk chooses cost-efficient cloud resources for one inference service under effectively elastic supply; Faro instead redistributes a fixed on-prem replica pool among competing jobs.
- _Bhardwaj et al. (OSDI '23)_ - Cilantro also uses utilities for cluster-level objectives, but Faro argues that its relaxed objectives and faster prediction loop are necessary for sub-second ML inference SLOs.

## My Notes

<!-- empty; left for the human reader -->

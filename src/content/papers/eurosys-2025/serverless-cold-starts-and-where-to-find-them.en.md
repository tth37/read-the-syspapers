---
title: "Serverless Cold Starts and Where to Find Them"
oneline: "A five-region production trace shows serverless cold starts come from mismatches between trigger patterns, resource pools, runtimes, and regional bottlenecks, not one universal delay."
authors:
  - "Artjom Joosen"
  - "Ahmed Hassan"
  - "Martin Asenov"
  - "Rajkarn Singh"
  - "Luke Darlow"
  - "Jianfeng Wang"
  - "Qiwen Deng"
  - "Adam Barker"
affiliations:
  - "Central Software Institute, Huawei"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3696073"
project_url: "https://github.com/sir-lab/data-release"
tags:
  - serverless
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

This paper is a production measurement study, not a new cold-start mechanism. Using 31 days of Huawei YuanRong traces across five regions, it shows that cold starts are driven by different bottlenecks in different settings, and that many of the worst offenders are policy mismatches between trigger patterns, keep-alive time, runtime choice, and resource-pool design.

## Problem

Cold starts are a known problem in serverless systems, but most public evidence is thin. Prior provider-side studies mostly publish aggregate statistics, while black-box measurements from outside the platform can observe latency but not the internal step that caused it. That leaves operators and researchers with a vague target: they know cold starts hurt, but not whether to fix pod allocation, scheduling, dependency deployment, keep-alive policy, or regional placement.

That ambiguity matters because a public cloud is not a single homogeneous queue. Regions see different request rates, runtimes, peak shapes, and resource mixes. A one-minute keep-alive might be sensible for one workload and obviously wasteful for another. The paper therefore asks a provider-view question: across real traffic, which functions cause cold starts, which component dominates the delay, and how much of that pain is actually amortized by later pod use?

## Key Insight

The key proposition is that a cold start is not one latency tax with one fix. The same symptom can arise from very different causes. Some functions cold start frequently because timer periods sit just outside the one-minute keep-alive window, so nearly every invocation recreates the pod. Others cold start because bursty traffic forces autoscaling and stresses scheduling or pool allocation. Even long cold starts are not always equally harmful if the resulting pod stays alive and serves many later requests.

That is why the paper decomposes cold starts rather than treating them as a single scalar. It separates pod allocation, code deployment, dependency deployment, and scheduling, and adds a new metric, pod utility ratio, defined as useful pod lifetime divided by cold-start time after subtracting the one-minute keep-alive. The central claim is that both optimization and diagnosis need this finer view.

## Design

The study uses three telemetry streams from Huawei's YuanRong platform over 31 days: request-level records, pod-level cold-start records, and function metadata. The trace spans five regions and 20 clusters, covering 85 billion requests, more than 12 million pods, and 11.9 million cold starts. For each cold start, the authors log total cold-start time plus four components: pod allocation, code deployment, dependency deployment, and scheduling.

The analysis starts at region level and then drills deeper into Region 2 for trigger, runtime, and resource-allocation breakdowns. That choice lets the paper connect macro behavior, such as peak-time lags and holiday effects, with micro causes inside the startup path. The authors also model cold-start times with a LogNormal fit and cold-start inter-arrival times with a Weibull fit, mainly to give later systems work realistic distributions for simulation.

Two design moves make the paper more useful than a plain trace release. First, it treats multi-region behavior as a first-class object: regions have different peak hours, different median request rates per function, and different dominant cold-start components. Second, pod utility ratio asks whether a slow startup was followed by enough useful work to justify the cost.

## Evaluation

The strongest result is heterogeneity. Across regions, median cold-start times range from about 0.1 seconds to 2 seconds, with long tails everywhere. Region 1 sees cold starts up to 7 seconds and Region 2 up to 3 seconds. The dominant component also changes by region: Region 1 is largely driven by dependency deployment and scheduling, whereas Region 2 is dominated by pod allocation. Cold-start time is positively correlated with the number of cold starts in all regions, and the first workday after the holiday creates a visible catch-up spike in both count and duration.

The Region 2 breakdown turns those measurements into operational guidance. Timers account for almost 60% of functions and 30% of cold starts, but only 5% of running pods, which means many timer-driven functions cold start almost every time and then do little useful work. Python3 accounts for almost 50% of cold starts. Small CPU-memory configurations account for more than 60% of cold starts, but larger allocations are slower when they do cold start: median startup time for larger pools is about 1x to 5x that of smaller pools depending on region, largely because pod search, code deployment, and dependency deployment all get worse.

Runtime and trigger type matter in different ways. In Region 2, most runtimes have sub-second medians with long tails, but Custom and HTTP have medians above 10 seconds. For Custom, the main reason is pod allocation: there is no reserved pool, so pods are created from scratch. OBS-triggered functions also have slow cold starts, but the paper is careful not to overclaim because OBS is heavily entangled with Custom runtimes. Finally, pod utility ratio changes the story: 20% of pods have utility ratio below 1, while the median is about 4:1, so a short cold start can still be wasteful if the pod dies almost immediately afterward.

The evaluation supports the main claim well because it covers a large production trace and exposes component timings, not just end-to-end latency. Its causal conclusions are necessarily weaker than its descriptive ones, but as a diagnosis of where cold starts come from in practice, it is unusually concrete.

## Novelty & Impact

The novelty here is explanatory rather than algorithmic. The paper does not introduce a new runtime, prewarming policy, or scheduler. Instead, it gives a provider-side decomposition of cold starts across regions, trigger types, runtimes, and resource sizes, then reframes their cost with pod utility ratio. That is new enough to matter because many cold-start papers optimize one mechanism without first proving that the same mechanism is dominant in production.

The impact is that it points away from one-size-fits-all fixes. The paper argues for region-aware load balancing, trigger-aware keep-alive policies, predictive resource-pool sizing, and workflow-aware prewarming. Even if a reader never uses YuanRong, the study is a strong reminder that cold-start work should target the actual dominant component and the actual workload class.

## Limitations

This is still an observational study from one provider and one platform. The trace spans only 31 days and only five regions, not Huawei's full deployment footprint. The deeper trigger/runtime/resource analysis is centered on Region 2 rather than repeated across all regions. That is enough to reveal structure, but not enough to claim universal percentages for every public cloud.

Some explanations are also confounded. The paper explicitly notes that slow OBS cold starts are strongly mixed with Custom runtimes, so trigger type is not a clean causal variable there. More broadly, provider telemetry can localize the slow stage of a cold start better than it can prove the exact architectural root cause. The paper is best read as a high-quality measurement study that narrows the search space for optimizations, not as the final word on why every cold start happens.

## Related Work

- _Wang et al. (USENIX ATC '18)_ - Peeking Behind the Curtains measures cold starts from the user side; this paper adds the provider's internal component breakdown.
- _Shahrad et al. (USENIX ATC '20)_ - Serverless in the Wild characterizes provider workloads at a high level, while this paper focuses specifically on cold-start causes across regions.
- _Oakes et al. (USENIX ATC '18)_ - SOCK proposes faster serverless provisioning; this paper explains which parts of provisioning dominate in production.
- _Joosen et al. (SoCC '23)_ - How Does It Function? studies long-term serverless workload trends, and this paper narrows in on cold starts with richer per-event telemetry.

## My Notes

<!-- empty; left for the human reader -->

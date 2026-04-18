---
title: "GREEN: Carbon-efficient Resource Scheduling for Machine Learning Clusters"
oneline: "GREEN uses progress-per-energy scaling in an upper queue and carbon-intensity-aware load shifting in a lower queue to cut ML-cluster emissions with small JCT impact."
authors:
  - "Kaiqiang Xu"
  - "Decang Sun"
  - "Han Tian"
  - "Junxue Zhang"
  - "Kai Chen"
affiliations:
  - "iSING Lab, Hong Kong University of Science and Technology"
  - "USTC"
conference: nsdi-2025
category: llm-and-ml-training-serving
tags:
  - scheduling
  - ml-systems
  - gpu
  - datacenter
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

GREEN is a Slurm-based scheduler for shared GPU training clusters that splits the problem into two decisions: how many GPUs a job should get based on marginal training progress per unit energy, and when high-power jobs should run based on grid carbon intensity. Its two-level queue cuts cluster-wide carbon footprint by up to 41.2% and peak power by 12% on real ML workloads, with 3.6%-5.9% higher average JCT than the best time-oriented baseline.

## Problem

The paper argues that existing ML cluster schedulers optimize the wrong objective for carbon-aware operation. Systems such as Tiresias, Optimus, and Pollux focus on JCT, goodput, or fairness, so they scale jobs according to time efficiency rather than environmental impact. Zeus adds energy awareness, but only at the single-job level; it does not decide how a shared cluster should divide GPUs across jobs with different power profiles. Carbon-aware cloud schedulers are also an imperfect fit, because many of them assume on-demand elasticity, user-supplied deadlines, or the ability to leave capacity idle during dirty hours.

That mismatch matters in multi-tenant MLaaS clusters. Different jobs consume very different amounts of power when scaled out, so a scheduler that only looks at throughput can waste both energy and carbon. At the same time, many training jobs run for hours, days, or weeks and are already paused and resumed in practice, which means they have some temporal flexibility. A cluster scheduler should exploit both forms of flexibility without changing model hyperparameters or requiring users to rewrite their training code.

The hard part is doing this under fixed cluster capacity. Simply throttling jobs during high-carbon hours lowers utilization and hurts JCT. Simply delaying jobs to greener hours can starve long jobs or leave GPUs idle. GREEN is designed to reduce carbon footprint while staying inside the realities of a shared production GPU cluster.

## Key Insight

The key insight is that carbon-efficient scheduling in ML clusters has both a spatial and a temporal component, and the scheduler should treat them separately. Spatially, each extra GPU should be given to the job that converts energy into training progress most efficiently, not merely the job with the best raw speedup. Temporally, long-running high-power jobs should be pulled toward greener hours with lower carbon intensity, while lower-power jobs fill dirtier hours, as long as the scheduler preserves overall resource fairness over time.

This decomposition lets GREEN avoid intrusive job-level control. It does not tune batch size, learning rate, or model internals. Instead, it measures how efficiently a running job turns energy into progress, keeps those scaling decisions, and then applies a second policy that reorders jobs in time according to accumulated carbon footprint and the current carbon-intensity curve. The paper's claim is that a two-level queue is enough to co-optimize both goals with modest impact on JCT.

## Design

GREEN has three main pieces: a carbon tracker, two optimizers, and an MLFQ-style scheduler that composes them. The carbon tracker estimates each job's power draw as GPU power from NVML plus modeled CPU power plus a static term for the rest of the node. It samples every 30 seconds and integrates power against a Carbon Intensity Curve (CIC), built from historical grid data, to estimate each job's cumulative carbon footprint. The same tracker also gathers the runtime signals used for scheduling.

The Energy Efficiency Optimizer answers the question "should this job get one more GPU?" GREEN defines energy efficiency as training progress divided by accumulated energy, approximated either from explicit progress updates or from throughput over the interval since the last scaling event. Every job starts at one GPU, or the minimum it needs, and GREEN computes a degradation factor relative to that initial efficiency. If adding GPUs does not degrade efficiency too much, the job stays in the upper queue and can scale out again. Once the job stops looking energy-efficient to scale further, it moves to the lower queue with its current GPU allocation. A capacity cap on the upper queue keeps online profiling from consuming the whole cluster and starving established jobs.

The Carbon Footprint Optimizer decides when lower-queue jobs should run. Its score combines three signals: accumulated carbon footprint, the same efficiency degradation factor, and a shifting factor that depends on current carbon intensity and job power draw. The shifting factor is intentionally heuristic: jobs above the current median power draw are treated as high-power jobs, hours below the daily average CIC are treated as greener hours, and a parameter `mu` controls how aggressively GREEN pushes high-power jobs into those greener windows. The effect is to keep low-power jobs running during dirty hours while reserving greener hours for more carbon-expensive work.

The scheduler itself resembles MLFQ. The upper queue performs online profiling and scaling. The lower queue keeps the scaling decision fixed and reorders jobs for peak-load shifting. Active scheduling runs every 30 minutes and may preempt low-priority jobs; passive scheduling fills newly freed GPUs between active rounds without recalculating everything. The paper also adds starvation mitigation: short jobs benefit from the upper queue's implicit short-job bias, while a 30% upper-queue capacity cap protects long-running jobs that already reached the lower queue.

## Evaluation

The evaluation uses a 32-node GPU cluster, each node with 2 RTX 3090s, 20 CPU cores, 64 GB RAM, and ConnectX5 NICs. The main workload is a replay of 791 real user jobs collected over 24 hours from a university production cluster, including image, speech, and NLP training jobs ranging from 1 minute to 37 hours. GREEN is compared against Tiresias, GAIA's Carbon-Time policy, EcoVisor, and, on a 150-job compatible subset, Pollux and Zeus plus Tiresias.

Across four regional carbon traces, GREEN reduces cluster-wide carbon footprint by up to 41.2%, and by 32.2% on average, relative to the compared schedulers. Even when temporal shifting is disabled, the energy-efficiency scaling logic alone still yields an average 21% carbon reduction. Under the UK carbon trace, GREEN lowers peak cluster power from 28 kW to 24.5 kW and total energy use from 966 kWh to 725 kWh, which matters because physical clusters are provisioned and billed around peak demand as well as total energy.

The time-efficiency cost is real but controlled. Compared to Tiresias, the best JCT baseline, GREEN increases average JCT by 3.6%-5.9% and tail JCT by 5.1%-7.1%. The per-job breakdown is reasonable: extra-small jobs improve slightly, while the worst category, jobs longer than 10 hours, sees a 6.9% average JCT increase. On the smaller subset needed for non-model-agnostic baselines, GREEN still cuts carbon footprint by 23.9% relative to Pollux and by 12.7% relative to Zeus plus Tiresias. The evidence supports the paper's central claim: the design wins broadly across realistic workloads, but the biggest gains appear in regions whose carbon intensity changes substantially over the day.

## Novelty & Impact

The novelty is not merely "carbon-aware scheduling for ML." Prior schedulers usually optimize one axis at a time: Tiresias for fairness and JCT, Pollux for goodput-oriented scaling, Zeus for per-job energy efficiency, and GAIA-style systems for carbon-aware timing in elastic clouds. GREEN's contribution is to combine energy-efficient scale-out and carbon-intensity-aware time shifting inside one shared-cluster scheduler that stays model-agnostic and respects fixed capacity constraints.

That makes the paper useful to operators of campus and enterprise GPU clusters, not just to cloud researchers. It gives a practical recipe for adding carbon awareness to a conventional batch scheduler such as Slurm without requiring job deadlines or invasive control over training code. The work is therefore best understood as a new scheduling mechanism, backed by a realistic deployment-style evaluation, rather than a pure measurement study.

## Limitations

GREEN assumes preemptible training jobs and does not promise per-job SLOs or deadline guarantees. The paper explicitly notes that some real deployments may need to override its policy to protect jobs with strict execution requirements. That is a meaningful limitation because many production ML platforms mix flexible batch jobs with less flexible work.

Its carbon model is also incomplete by design. GREEN does not account for embodied carbon or data-center PUE, and it relies on historical or forecast carbon-intensity data. If those forecasts are wrong, the time-shifting policy can make worse decisions. The benefit of shifting also shrinks in regions where carbon intensity is already very low or nearly flat over time, so extra preemptions may add overhead for little absolute gain.

Finally, the mechanism is aimed at training workloads, not latency-sensitive inference. The paper also acknowledges that long jobs can still be delayed in highly congested clusters despite the starvation controls. GREEN is therefore a good fit for shared training clusters, but not a universal carbon scheduler for every GPU workload.

## Related Work

- _Gu et al. (NSDI '19)_ - `Tiresias` optimizes fairness and JCT in GPU clusters, whereas `GREEN` keeps a similar multi-queue flavor but adds energy-efficiency scaling and carbon-aware temporal shifting.
- _Qiao et al. (OSDI '21)_ - `Pollux` scales jobs for goodput, while `GREEN` scales them for marginal training progress per unit energy and then reorders them using carbon intensity.
- _You et al. (NSDI '23)_ - `Zeus` optimizes the energy-time tradeoff of individual DNN jobs, whereas `GREEN` allocates a shared cluster across many jobs and reasons about grid carbon intensity.
- _Hanafy et al. (ASPLOS '24)_ - `GAIA` assumes elastic cloud resources and deadline-aware control, while `GREEN` targets a static shared ML cluster with fixed capacity and no user-provided deadlines.

## My Notes

<!-- empty; left for the human reader -->

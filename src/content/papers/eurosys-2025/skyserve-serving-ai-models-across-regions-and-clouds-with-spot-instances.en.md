---
title: "SkyServe: Serving AI Models across Regions and Clouds with Spot Instances"
oneline: "SkyServe makes spot GPUs viable for AI serving by spreading replicas across regions and clouds, buffering with extra spot capacity, and falling back to on-demand only when needed."
authors:
  - "Ziming Mao"
  - "Tian Xia"
  - "Zhanghao Wu"
  - "Wei-Lin Chiang"
  - "Tyler Griggs"
  - "Romil Bhardwaj"
  - "Zongheng Yang"
  - "Scott Shenker"
  - "Ion Stoica"
affiliations:
  - "UC Berkeley"
  - "ICSI"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717459"
code_url: "https://github.com/skypilot-org/skypilot"
tags:
  - llm-inference
  - datacenter
  - gpu
  - fault-tolerance
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SkyServe argues that spot GPUs are not too unreliable for serving; the real problem is treating them as a single-region pool with static fallback. Its `SpotHedge` policy spreads replicas across regions and clouds, keeps a small buffer of extra spot replicas, and launches on-demand replicas only when spot capacity disappears. On real cloud runs and replayed spot traces, that cuts serving cost by roughly 43% versus all on-demand while preserving high availability and lowering latency relative to prior spot-serving baselines.

## Problem

Serving modern AI models is expensive because each replica sits on costly GPU instances and real traffic is bursty enough that operators overprovision for spikes. Spot instances look like the obvious fix: the paper reports spot GPUs at only 8%-50% of on-demand price. But existing serving systems mostly treat spot as a single-region resource, and that assumption breaks badly for GPU-backed inference.

The paper identifies three failure modes. First, spot GPUs are often simply unavailable within one region; in one AWS trace, spot GPUs were unavailable across all zones in a region 33.1% of the time. Second, preemptions are correlated inside a region, so spreading replicas across zones is not enough: if one zone starts losing capacity, nearby zones often follow within minutes. Third, preemption warnings are too short to save large-model serving. The authors measure 183 seconds just to provision an instance with a pre-installed image and deploy a Llama-2-7B endpoint on vLLM, already longer than AWS's 2-minute warning and far longer than GCP or Azure warnings.

That combination makes prior designs brittle. Pure-spot deployments lose capacity or go down entirely. Static spot-plus-on-demand node pools waste money when spot is healthy and still fail when the fixed spot pool cannot be replenished. The paper's claim is that spot GPUs are feasible for serving only if placement, overprovisioning, and fallback are all treated as one control problem.

## Key Insight

The core insight is that the system should hedge against spot volatility with cheap spot diversity first and expensive on-demand capacity second. If replicas are placed across wider failure domains, preemptions become less correlated and the search space for replacement instances gets much larger. Once that broader placement exists, only a small amount of extra spot capacity is needed to absorb most preemptions during cold start, and on-demand replicas can be launched as a temporary backstop instead of being kept alive all the time.

In other words, the right abstraction is not "what fixed fraction should be on-demand?" but "how many ready replicas do I need, how many extra spot replicas should buffer preemptions, and where should those spot replicas live right now?" That reframes spot serving from a static fleet-composition problem into an online control policy over failure domains.

## Design

`SpotHedge` has two coupled pieces. The first is dynamic placement. It tracks enabled zones in two sets: available zones and highly preempting zones. When a zone preempts a replica, that zone is moved out of the active set; when a launch succeeds there again, it returns to the available set. New spot replicas are launched from currently available zones, preferring cheaper zones and avoiding zones already hosting the current service when possible. If fewer than two zones remain in the available set, the system rebalances by reopening all zones rather than concentrating the entire service in one surviving zone.

The second piece is dynamic fallback. Let `N_tar(t)` be the target number of ready replicas from the autoscaler and `N_extra(t)` the number of extra spot replicas provisioned as a buffer. SkyServe tries to keep `N_tar + N_extra` spot replicas in flight. If some spot replicas are preempted, it launches on-demand replicas to cover the missing ready capacity while still trying to restore the full spot fleet. Once enough spot replicas become ready again, those on-demand replicas are terminated. This gives the service a dynamic mixture of spot and on-demand replicas rather than a static node pool split.

SkyServe implements this policy as a serving stack with a service controller, autoscaler, and load balancer. The controller manages provisioning, readiness checks, and termination; the autoscaler converts load into `N_tar`; and the load balancer routes only to ready replicas. The system is designed to sit under existing inference engines such as vLLM, TGI, and Triton rather than replace model-serving internals.

## Evaluation

The evaluation combines real cloud experiments with trace-driven simulation. The live deployment runs for about 22 hours, serves 133k requests, and costs about $4.1k total. The main end-to-end setup serves Llama-2-70B with vLLM on 8x A10G `g5.48xlarge` instances; a second setup runs OPT-6.7B with SpotServe on 4x T4 instances. Workloads come from Chatbot Arena traces, so the system sees bursty arrivals and variable output lengths rather than synthetic steady load.

The main result is that SkyServe achieves the service quality that cheaper spot-only baselines cannot. Against production-style and research baselines, it improves P50, P90, and P99 latency by 2.3x, 2.1x, and 2.1x on average while reducing cost by 43% on average relative to all on-demand deployment. In the Llama-2-70B experiments, SkyServe keeps request failure rates at 0.34%-0.62%, while ASG reaches 36% under volatile spot conditions, AWSSpot reaches 49%-94%, and MArk reaches 6.8%-79%. The paper is careful about interpreting cost: AWSSpot and MArk can be cheaper in some volatile periods only because they fail to keep enough ready replicas.

The trace-driven results support the same mechanism more cleanly. Across AWS and GCP spot traces, SpotHedge reaches 99%-100% availability, reduces average latency by 1.1-3.0x versus Even Spread and 1.0-1.8x versus Round Robin, and comes within 5%-20% relative cost of an omniscient offline optimum while still costing only 42%-55% of an all-on-demand fleet. That evaluation matches the paper's thesis: the win comes from combining broader placement, a small spot buffer, and temporary on-demand fallback.

## Novelty & Impact

The novelty is not a new inference engine or a new autoscaler in isolation. The contribution is a serving policy that treats spot preemption correlation, cold start delay, and fleet composition as one problem and then realizes it in a multi-region, multi-cloud serving system. Relative to SpotServe, which focuses on intra-replica parallelism under preemption, SkyServe works one layer up at provisioning and placement time.

This makes the paper useful to two audiences. Systems researchers get a concrete argument that spot GPU serving is viable if failure domains are widened and fallback is dynamic. Practitioners get an operational recipe they can plausibly adopt without rewriting model-serving code, because SkyServe sits around existing engines and uses standard cloud instances rather than specialized hardware.

## Limitations

The paper's strongest results come from workloads where request processing takes seconds, so inter-region round-trip latency is small compared with model execution time. For highly interactive applications with very tight TTFT targets, remote-region routing could be a less favorable tradeoff than the paper suggests. The authors discuss this but do not fully evaluate it.

The policy is also heuristic rather than learned or proven optimal online. Thresholds such as the extra spot count, zone rebalancing trigger, and autoscaling windows are measurement-driven. Finally, the deployment evidence is persuasive but still limited: a few clouds and regions, two model setups, and the assumption that on-demand GPUs remain obtainable across regions. If that fallback capacity also becomes scarce, the paper does not provide a deeper remedy.

## Related Work

- _Miao et al. (arXiv '23)_ - SpotServe makes model parallelism tolerate preemption inside a replica, while SkyServe tackles where replicas should be provisioned and how spot and on-demand capacity should be mixed across failure domains.
- _Zhang et al. (ATC '19)_ - MArk serves ML inference with a mixture of spot and on-demand instances, but its assumptions are CPU-oriented and single-region; SkyServe shows those assumptions fail for GPU-backed AI serving.
- _Yang et al. (ASPLOS '23)_ - Snape uses cloud-internal signals to predict spot obtainability for inference serving, whereas SpotHedge relies on online placement and fallback decisions that do not assume provider-side capacity visibility.
- _Harlap et al. (ATC '18)_ - Tributary uses spot instances for elastic services with latency SLOs, but SkyServe focuses on long-cold-start GPU model replicas and correlated preemptions across cloud failure domains.

## My Notes

<!-- empty; left for the human reader -->

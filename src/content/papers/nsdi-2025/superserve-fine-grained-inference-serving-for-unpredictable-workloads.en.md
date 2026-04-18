---
title: "SuperServe: Fine-Grained Inference Serving for Unpredictable Workloads"
oneline: "SuperServe keeps one weight-shared SuperNet resident, actuates SubNets in place, and uses per-query slack to trade accuracy for throughput under bursty inference traffic."
authors:
  - "Alind Khare"
  - "Dhruv Garg"
  - "Sukrit Kalra"
  - "Snigdha Grandhi"
  - "Ion Stoica"
  - "Alexey Tumanov"
affiliations:
  - "Georgia Tech"
  - "UC Berkeley"
  - "Adobe"
conference: nsdi-2025
tags:
  - ml-systems
  - scheduling
  - datacenter
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SuperServe replaces model switching with in-place subnetwork actuation inside one weight-shared SuperNet. Its `SubNetAct` operators let the system pick a depth/width configuration in under 1 ms, and `SlackFit` uses the earliest query slack to choose both subnetwork accuracy and batch size online. That combination cuts the memory cost of serving a broad accuracy range by up to 2.6x and, on Azure-style traces, improves mean accuracy by up to 4.67% at the same SLO attainment or SLO attainment by 2.85x at the same accuracy.

## Problem

The paper studies inference serving for production applications whose request rates are both bursty and hard to predict at sub-second granularity. The target setting is not offline batch inference but latency-critical services, such as web applications and autonomous systems, where requests must meet SLOs in the 10-100 ms range while still returning the most accurate prediction possible. At the same time, GPU memory is scarce, so keeping a large menu of models resident is expensive.

The authors frame the serving problem as a three-way tension: latency, accuracy, and resource efficiency. Older serving systems choose one fixed model and therefore either miss SLOs during bursts or leave accuracy on the table during normal load. Newer automated systems can switch among multiple models, but that reintroduces a different bottleneck: the model-loading delay on the critical path. Figure 1a shows that loading a model into GPU memory is often much slower than the inference itself, with the gap widening for larger networks. In their simulation over the Microsoft Azure Functions trace, a 100 ms actuation delay leads to up to 75x more SLO misses than an idealized zero-delay policy.

SuperNets appear to offer the missing flexibility, because one trained SuperNet contains many SubNets spanning a latency-accuracy frontier. But prior NAS-based work still extracts those SubNets as separate deployable models. That puts serving systems back in the same bind: keep many models in memory and waste resources, or page them in and out and violate SLOs. The paper's starting point is therefore that the bottleneck is not only policy quality; it is the representation of model choices as separately loadable artifacts.

## Key Insight

The central claim is that inference serving should treat model choice as control flow inside one deployed network, not as a decision to load one model binary instead of another. If the trained SuperNet already subsumes all feasible SubNets, the serving system can keep the SuperNet resident and dynamically route each request through the subset of layers and weights corresponding to the desired latency-accuracy point.

That reframing matters because it removes actuation delay from the critical path. Once switching is reduced to selecting a depth/width tuple instead of copying weights into GPU memory, the scheduler can respond to the current queue rather than predicting future bursts. The paper goes further and argues that query slack is an adequate online signal: when slack shrinks, the system should pick lower-latency SubNets and usually larger batches; when slack is abundant, it should opportunistically raise accuracy. This works because pareto-optimal SubNets have a useful structure: lower-accuracy choices can often serve larger batches at roughly the latency where higher-accuracy choices serve smaller ones.

## Design

The mechanism is `SubNetAct`, which modifies a trained SuperNet by inserting three control-flow operators. `LayerSelect` chooses which blocks execute, effectively controlling network depth. For CNN-based SuperNets it selects per-stage depth; for transformer-based SuperNets it selects layers using the paper's "every-other" strategy. `WeightSlice` selects only a prefix of channels or attention heads inside a layer, which gives width scaling without duplicating full weights. Together, those two operators let the serving system identify a SubNet by a control tuple `(D, W)` and activate it in place.

The third operator, `SubnetNorm`, handles a correctness issue specific to convolutional SuperNets. Naively sharing BatchNorm state across many SubNets hurts accuracy because each SubNet needs its own running mean and variance. `SubnetNorm` therefore stores precomputed normalization statistics per SubNet and per normalization layer, while still sharing the main weights. The paper reports that these non-shared statistics are about 500x smaller than the shared layers, so the bookkeeping cost is small relative to the memory saved by not materializing many independent models.

On top of `SubNetAct`, the paper builds `SlackFit`, an online scheduler. Offline, it uses NAS outputs to restrict attention to pareto-optimal SubNets, shrinking the search space from roughly 10^19 architectures to about 10^3 candidates. It then profiles each candidate by batch size and groups `(SubNet, batch-size)` choices into latency buckets. Online, SuperServe keeps incoming requests in a global EDF queue. Whenever a worker is free, `SlackFit` looks at the remaining slack of the earliest-deadline query, picks the fastest bucket that still fits under that slack, forms the corresponding batch, and dispatches it. The implementation is a router plus scheduler plus GPU workers, with `SubNetAct` encoded in TorchScript IR; the full system is about 17.5k lines of C++ and uses gRPC between clients, router, and workers.

## Evaluation

The evaluation mixes mechanism-level and end-to-end results. At the mechanism level, `SubNetAct` is the core enabler: compared with serving sampled standalone ResNets or extracted SubNets, it reduces memory usage by up to 2.6x while exposing hundreds of fine-grained operating points. More importantly, actuation is effectively instantaneous: Figure 5b reports sub-millisecond SubNet activation, versus hundreds of milliseconds for model loading. That creates a throughput range of roughly 2,000-8,000 QPS within a relatively narrow accuracy band.

The end-to-end experiments use a ResNet-based SuperNet trained on ImageNet and a transformer-based SuperNet trained on MNLI, running on 8 RTX2080Ti GPUs and 24 CPU cores. The real-world test replays 32,700 workloads from the Microsoft Azure Functions trace, compressed from 24 hours to 120 seconds. Against `Clipper+` and `INFaaS`, SuperServe is strongest on the CNN case: it reaches 0.99999 SLO attainment, is 4.65% more accurate at the same SLO attainment, and achieves 2.85x higher SLO attainment at the same mean serving accuracy. For transformers, it reports a 1.2x SLO-attainment improvement at equal accuracy or 1.72% higher accuracy at equal SLO attainment.

The synthetic traces support the same story under more controlled burstiness. Across bursty workloads with varying mean arrival rate and CV^2, the paper reports that SuperServe stays above 0.999 SLO attainment and is up to 4.33% more accurate than the baselines at 0.9999 SLO attainment, or 2.06x better in SLO attainment at the same accuracy. Under time-varying arrival acceleration, it maintains 0.991-1.0 SLO attainment even at 5,000 QPS^2 acceleration. The microbenchmarks also matter: after killing one worker every 12 seconds, the system still holds about 0.999 SLO attainment down to 50% capacity by switching to lower-accuracy SubNets; and when scaling workers, it reaches about 33,000 QPS at 0.999 SLO attainment. Overall, the evaluation supports the central mechanism claim, though it is still limited to modest GPU scale and relatively small models.

## Novelty & Impact

The paper's novelty is the combination of a new serving abstraction and a scheduler designed around it. Prior automated serving systems such as `INFaaS` and `Proteus` still reason over discrete models whose activation is coarse and expensive. SuperServe instead turns "model choice" into fast control inside one resident SuperNet, which is what makes a genuinely reactive policy practical. `SlackFit` is intentionally simple, but it only works because the representation removes switching cost.

This is likely to matter to ML-systems researchers and operators who serve many latency-accuracy points for one task. The work sits between NAS and serving: it does not propose a better SuperNet training algorithm, but it provides the systems support needed to make SuperNets operationally useful in bursty online inference.

## Limitations

The system depends on having a trained SuperNet and a reliable offline profiling phase. If the hardware environment changes materially, or if the latency profiles drift, the scheduler's bucketization may need to be regenerated. The paper also assumes predictable inference latency and homogeneous workers; heterogeneous accelerators are discussed only as future work.

The evaluation scope is narrower than the paper's broad motivation. The experiments use image and text classification SuperNets on 8 RTX2080Ti GPUs, not large generative models or very large clusters. The fault-tolerance result is useful, but it is really graceful degradation through faster subnetwork switching, not a full recovery protocol. Finally, one baseline choice is structurally constrained: `INFaaS` is run without per-query accuracy thresholds because the paper's workload model does not provide them, so that comparison mainly demonstrates SuperServe's ability to optimize accuracy online rather than a head-to-head match of identical objectives.

## Related Work

- _Cai et al. (ICLR '20)_ - `Once-for-All` trains one SuperNet for many deployment points, while `SuperServe` adds runtime serving support so those SubNets can be actuated online instead of statically extracted.
- _Gujarati et al. (OSDI '20)_ - `Clockwork` makes DNN inference predictable for fixed deployed models, whereas `SuperServe` focuses on dynamically choosing among many latency-accuracy points under bursty traffic.
- _Romero et al. (USENIX ATC '21)_ - `INFaaS` automates model selection under accuracy constraints, but it still switches among discrete models; `SuperServe` avoids that loading delay by activating weight-shared SubNets in place.
- _Ahmad et al. (ASPLOS '24)_ - `Proteus` performs accuracy scaling with a coarse-grained MILP every 30 seconds, while `SuperServe` targets sub-second reactive control by making actuation essentially free.

## My Notes

<!-- empty; left for the human reader -->

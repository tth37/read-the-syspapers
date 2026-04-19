---
title: "Improving GPU Sharing Performance through Adaptive Bubbleless Spatial-Temporal Sharing"
oneline: "Bless squeezes idle GPU bubbles by scheduling short kernel squads and switching among MPS contexts, cutting latency while still honoring each application's quota."
authors:
  - "Shulai Zhang"
  - "Quan Chen"
  - "Weihao Cui"
  - "Han Zhao"
  - "Chunyu Xue"
  - "Zhen Zheng"
  - "Wei Lin"
  - "Minyi Guo"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Microsoft"
  - "Alibaba Group"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696070"
tags:
  - gpu
  - scheduling
  - datacenter
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Bless argues that GPU sharing fails largely because existing schedulers leave short idle bubbles between heterogeneous kernels. It schedules requests as small kernel squads, predicts which spatial or spatial-temporal split will finish fastest, and switches among pre-created MPS contexts so active requests can borrow idle SMs without losing their promised quota. On an A100, the paper reports 21.1%-37.3% lower inference latency than prior sharing schemes while keeping quota deviation near zero.

## Problem

Cloud operators increasingly want several lightweight AI jobs to share one GPU, but the standard choices each waste performance in a different way. Temporal sharing gives applications time slices, yet unpreemptable kernels and variable kernel lengths mean a request rarely occupies exactly its promised fraction of the device. Spatial sharing fixes SM partitions, which improves predictability, but any idle SMs inside one tenant's partition become unusable bubbles even if another tenant is waiting. Unbounded sharing fills the device more aggressively, but once kernels from multiple applications interleave freely, latency becomes hard to predict and quota guarantees become weak.

The paper's motivating example pairs VGG11 at 1/3 GPU and ResNet50 at 2/3 GPU on an A100. The same marked request takes 17.1 ms under temporal sharing and 11.5 ms under spatial sharing, while an ideal bubble-free schedule would finish in 10.1 ms without slowing the other application. The paper therefore targets a stricter goal than high utilization: lower latency without violating the isolated-latency target implied by each application's quota.

## Key Insight

Bless's core claim is that fairness should be enforced at the level of request progress, not fixed per-request partitions. If the runtime repeatedly asks which request is furthest behind its isolated execution curve, forms a short kernel squad from the lagging requests, and then chooses the fastest resource split for that squad, it can keep every request close to its quota target while still reclaiming idle SMs.

This only works if concurrent kernel behavior is predictable enough to search quickly online. Bless relies on offline profiles rather than full hardware introspection or kernel preemption. Once it knows how each kernel behaves under several SM budgets, it can estimate squad duration well enough to decide when strict spatial isolation is better and when later kernels should be released to run bubble-free on the full GPU.

## Design

Bless has an offline profiling stage and an online runtime. During profiling, it measures each application's isolated latency under quota `n%`, each kernel's duration under different SM allocations, cumulative progress through the request, and peak SM demand. On A100 it samples 18 partitions, which the paper says keeps the search space manageable; profiling finishes in 1.9 seconds on average and must run on the same GPU model used in deployment.

At runtime, each application gets its own FIFO queue, and Bless serves at most one active request per application. The multi-task scheduler tracks each active request's real progress and expected progress, then repeatedly selects kernels from the request with the smallest relative progress `Pr/Pe` until it fills a bounded-size kernel squad or hits a request boundary. This is the quota-preserving part of the design: if one request falls behind because of interference, it contributes more kernels to the next squad.

For each squad, the execution configuration determiner searches a compact space of options: no spatial restriction, strict spatial splits, and a semi-spatial mode where only the front part of each request stays restricted. Two estimators make this practical. The interference-free predictor handles strict isolation with 6.7% average error, and the workload-equivalence predictor handles non-isolated overlap with 7.1% average error; across 2,260 kernel groups, the predicted-optimal split matches the real optimum 96.2% of the time.

The concurrent kernel manager realizes these choices with Nvidia MPS. Bless pre-creates contexts with different SM affinities using `cuCtxCreate_v3`, launches the early kernels of a request into restricted contexts, then switches later kernels into an unrestricted context so they can consume leftover bubbles. The implementation is about 5,000 lines of C++ with a gRPC interface.

## Evaluation

The evaluation runs on a server with one Nvidia A100 (108 SMs, 40 GB) and an AMD EPYC 7302 CPU. Workloads cover inference and training for VGG11, ResNet50, ResNet101, NasNet, and BERT, with kernel durations ranging from 3 us to 3 ms. Bless is compared against Temporal sharing, MIG, GSlice, Unbound sharing, Reef+ for inference, and Zico for training; ISO, the isolated MPS latency at a given quota, is the fairness target.

Across inference workloads, Bless lowers average latency by 37.3%, 34.2%, 21.1%, 16.5%, and 13.5% versus Temporal, MIG, GSlice, Unbound, and Reef+ respectively. Across training workloads, it cuts epoch latency by 26.5%, 7.5%, 12.5%, and 9.9% versus Temporal, MIG, Unbound, and Zico. The gains are largest at medium and low load, where bubbles are abundant; under continuous saturation Bless stays within 3% of GSlice, which fits the paper's premise that there is little slack left to exploit.

Bless is also better at honoring uneven quotas. Across nine pairwise deployments, average latency deviation from ISO is 0.6 ms, versus 14.3 ms for Temporal and 2.1 ms for GSlice. On a Twitter-derived trace, it cuts latency by 18.4%, 20.5%, and 7.3% versus Temporal, MIG, and GSlice at equal quotas, and by 14% versus GSlice at a 1/3-2/3 split with no extra deviation from ISO. On an Azure serverless trace, the reductions are 49.3%, 41.2%, and 32.1%. Under explicit QoS targets, Bless has only 0.6% violations on average, while Unbound and GSlice violate 38.8% and 50.1% of requests.

## Novelty & Impact

The closest prior systems each solve only one side of the problem. GSlice gives controlled spatial partitions but wastes idle capacity inside them. Reef gives tight control for prioritized inference, but it is fundamentally biased and sacrifices co-runners. Orion profiles interference carefully, but Bless goes further by turning bubbles into an explicit scheduling target. Its novelty is the combination of progress-based fair scheduling, lightweight online search over kernel-squad configurations, and MPS-based context switching that converts static spatial sharing into adaptive spatial-temporal sharing.

That makes the paper relevant to datacenter operators and GPU-scheduling researchers. It shows that quota-aware sharing does not have to choose cleanly between predictability and utilization, at least for stationary inference and training jobs whose kernels can be profiled ahead of time.

## Limitations

Bless is not a general scheduler for arbitrary GPU workloads. It assumes stationary applications with deterministic DAGs and requires offline profiling on the same GPU model used in production. The deployment logic also avoids pairing applications with extremely short kernels and extremely long kernels, because the short ones can otherwise be starved inside each squad. Dynamic applications such as autoregressive LLM serving would need a different progress model or much more aggressive profiling.

The mechanism also pays visible overheads and leaves some resources unmanaged. Each MPS context consumes about 230 MB of GPU memory, kernel-squad switches cost about 20 us, context switches create about 50 us of vacuum, and Bless only controls SM allocation, not registers or shared memory. Its lazy wait for squad boundaries can slightly hurt a lightly loaded high-quota tenant under an extremely biased workload: the paper reports about 9% latency inflation for that tenant, although the busy co-runner gets 2.2x higher throughput.

## Related Work

- _Dhakal et al. (SoCC '20)_ - GSlice adaptively spatially partitions inference workloads, while Bless reconfigures resources within a request so idle SMs inside a partition can be reclaimed mid-request.
- _Han et al. (OSDI '22)_ - Reef uses microsecond-scale preemption and controlled concurrency for prioritized DNN inference, whereas Bless targets unbiased quota-based sharing across all co-located applications.
- _Strati et al. (EuroSys '24)_ - Orion profiles interference for fine-grained GPU sharing, but Bless adds kernel-squad scheduling and explicit online search over spatial-temporal execution configurations.
- _Lim et al. (ATC '21)_ - Zico overlaps DNN training iterations to save memory and improve sharing, while Bless works at kernel granularity and tracks per-application progress against quota targets.

## My Notes

<!-- empty; left for the human reader -->

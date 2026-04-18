---
title: "BlitzScale: Fast and Live Large Model Autoscaling with O(1) Host Caching"
oneline: "BlitzScale multicasts LLM weights over the compute network and lets partially loaded instances execute ready layers, so autoscaling needs only one host-cached copy per model."
authors:
  - "Dingyan Zhang"
  - "Haotian Wang"
  - "Yang Liu"
  - "Xingda Wei"
  - "Yizhou Shan"
  - "Rong Chen"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "Huawei Cloud"
conference: osdi-2025
code_url: "https://github.com/blitz-serving/blitzscale"
tags:
  - llm-inference
  - gpu
  - networking
  - datacenter
  - caching
category: llm-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

BlitzScale speeds model autoscaling by treating deployed GPUs and one cluster-wide host copy as parameter sources, then multicasting weights over RDMA and NVLink instead of waiting on SSD loads or per-host cache hits. It also breaks scaling from "add a fully loaded instance" into "add layers as they arrive": a partially loaded instance can execute the layers it already has and hand activations back to the old instance. On real traces, that gives substantially lower TTFT than ServerlessLLM while cutting GPU time versus over-provisioned serving.

## Problem

The paper targets model-as-a-service platforms that host many large models at once and must absorb bursty demand without permanently reserving peak GPU capacity. The difficult case is short bursts, not slow diurnal change: the authors cite workloads whose request rate jumps 5x within two seconds, while LLM memory demand also swings because KV cache occupancy depends on unpredictable decode length. In that setting, providers want to keep only the average number of instances online and scale up when bursts arrive, but user-facing latency budgets are tight enough that even sub-second delays matter.

Prior autoscaling mechanisms fail for two separate reasons. First, the data plane is too slow. SSD bandwidth on GPU servers is only 2-10 Gbps per GPU in the surveyed setups, so even an 8B model can take 12.8 seconds to load from a 10 Gbps SSD. Second, faster host-memory loading depends on local cache hits that are hard to sustain when a platform serves hundreds or thousands of models. ServerlessLLM reports 40%-75% host-cache hit rates; BlitzScale's own characterization shows miss rates of 20%-46% on BurstGPT, with misses becoming more common when scaling to multiple hosts. Worse, all of these paths are stop-the-world: the new instance stays idle until every weight is present. For a 72B model, the paper argues that keeping SLO violations below 60% already needs about 220 Gbps per GPU, and holding stop time under 500 ms would require 576 Gbps per GPU, beyond typical deployments.

## Key Insight

The core claim is that autoscaling should reuse two things the serving cluster already has: an underutilized compute network for moving parameters, and the model's layer structure for doing useful work before loading is complete. The first part works because RDMA and NVLink are much faster than SSD and, in the authors' measurements, remain lightly used even in network-heavy PD-disaggregated serving. If a model is already deployed somewhere, its parameters can be multicast directly from those running instances. If it is not currently deployed, one host-cached copy anywhere in the cluster is enough, because the network can fan that copy out to all new instances.

The second part works because inference is naturally layer by layer. A scaled instance does not need the whole model to help; it only needs enough layers to compute a prefix and return activations to the overloaded instance that still owns the rest. This turns loading time into partial throughput rather than dead time. The important conceptual shift is therefore not just "faster loading" but "finer-grained scaling": the unit of progress becomes loaded layers, not fully initialized instances.

## Design

BlitzScale adds four main control components to a serving stack: a load monitor, a global parameter pool, a scale planner, and a live-execution scheduler. The parameter pool tracks where each model currently resides across deployed GPUs and host DRAM. During initialization, the system spreads one copy of each model across cluster hosts so at least one host-backed source always exists. When load exceeds a threshold, the monitor requests more instances, the planner selects sources and targets, and the scheduler coordinates serving during the transition.

The network side is built around a simplified topology model. GPUs linked by NVLink are treated as a scale-up group because intra-group broadcast is extremely fast; inter-host traffic is modeled as a leaf-spine RDMA fabric with per-GPU bandwidth and leaf identifiers. The planner first prunes sources that would interfere with serving traffic, then greedily forms serial forwarding chains. That chain structure is attractive because once an intermediate target receives the first layer, it can immediately forward it while the source starts sending the next layer, so bandwidth-heavy broadcast overlaps naturally. The planner uses multiple chains when necessary to avoid slow inter-leaf links and, in PD disaggregation, to avoid colliding parameter traffic with KV-cache traffic. If source and target nodes each have duplicated shards, BlitzScale further parallelizes a transfer by having each GPU send only its shard and then reconstructing the full weights via NVLink AllGather on the receiver.

Live scaling is the other half of the design. BlitzScale pairs an overloaded old instance with a new instance that is still loading. It immediately redirects queued and incoming requests to the new instance; once the first layer arrives, the new instance executes that layer and sends activations back to the old one for the remaining layers. A naive "best effort" policy still leaves the old instance as the bottleneck, so the paper introduces ZigZag scheduling. ZigZag deliberately delays some work on the old instance so the new one can accumulate more loaded layers and execute a larger prefix, improving pipeline balance. The authors present both an ILP formulation and a cheaper queue-based approximation. For LLM-specific PD disaggregation, BlitzScale also pre-scales decode instances when prefill demand rises and handles decode scaling by temporarily mutating some prefill instances into decode instances when direct live decode scaling would interfere with KV-cache transfers.

## Evaluation

The implementation is a 24 KLOC Rust and C++ system using FlashInfer kernels. The evaluation covers two GPU clusters, three real traces, and three model sizes. Cluster A uses A800 GPUs with NVLink and 100 Gbps RDMA, which is needed for 72B tensor-parallel instances; Cluster B uses A100 PCIe servers. Workloads come from BurstGPT, AzureCode, and AzureConv, and the compared systems are ServerlessLLM, an AllCache variant that always hits host memory, DistServe, and vLLM. The paper also applies the same scaling policy to BlitzScale and ServerlessLLM variants, and it calibrates DistServe to match BlitzScale when autoscaling is disabled, which makes the comparisons more credible.

The strongest evidence is that BlitzScale consistently lowers latency on bursty traces where scaling actually matters. On BurstGPT with a 72B model, TTFT is 75.5% shorter than ServerlessLLM and 21.1% shorter than AllCache; TBT is 7.4% and 5.1% shorter, respectively. A detailed micro-timeline for scaling a 24B model to six prefill instances shows why: BlitzScale begins emitting tokens around 500 ms because the live path is already useful, and it finishes scaling in about 1.2 seconds, versus roughly 2.0 seconds for AllCache. The ablation study also isolates the pieces cleanly: faster network loading helps everywhere, multicast matters most when several instances scale together, and ZigZag helps most on the slower-network cluster where live overlap has time to pay off.

The resource-usage story also supports the central claim. Against DistServe with full over-provisioning, BlitzScale reaches the same 5x-SLO target while using about half the GPU time; against the average-provisioned DistServe setup, it cuts TTFT by 95.8% and TBT by 1%. Compared with ServerlessLLM, it uses 19.46% less GPU time and less host cache because it does not need per-host replicas. That evidence matches the paper's thesis: faster, cluster-wide parameter movement and live cooperative execution jointly improve both latency and utilization.

## Novelty & Impact

Relative to ServerlessLLM, BlitzScale is not merely a more aggressive cache. Its main move is to replace per-host cache dependence with a cluster-wide parameter pool and network multicast, then to turn loading time into execution time through cooperative layer-wise serving. Relative to PipeSwitch-style loading overlap, the novelty is that the scaled instance contributes throughput before it can independently finish a request. That is a qualitatively different autoscaling abstraction.

The impact is practical for systems that already run modern LLM-serving clusters with fast GPU interconnects but do not want permanent peak provisioning. The paper is likely to matter to MAAS operators, LLM-serving researchers, and future work on elastic disaggregated inference, because it couples cluster resource management with the actual structure of inference execution instead of treating instance startup as an opaque cold start.

## Limitations

The design depends on assumptions that are plausible but not universal. Its planner assumes a simplified leaf-spine model and exploits the claim that opposite-direction network flows do not interfere in the targeted fabrics; if a deployment has different topology behavior, the interference-free plan may be less reliable. The benefits also depend on having spare GPUs and an underutilized compute network, which may not hold in tightly packed clusters.

Some limits are more specific to LLM serving. The paper acknowledges that direct live scaling of decode instances in PD disaggregation is impossible without interference, so it uses a workaround that mutates prefill instances into decode instances while replenishing prefill capacity elsewhere. The autoscaling policy itself is also mostly out of scope: thresholds come from prior work and offline profiling, and the authors explicitly leave better policy design to future work. Finally, the multicast gains are narrower when only one large instance can be added at a time; the 72B evaluation, for example, cannot fully exercise the "many simultaneous receivers" case because the cluster can scale only a small number of such instances.

## Related Work

- _Bai et al. (OSDI '20)_ - PipeSwitch overlaps parameter loading with execution, but the new instance still cannot complete requests until the full model is loaded; BlitzScale adds cooperative live execution during loading.
- _Jeong et al. (EuroSys '23)_ - Direct-host-access speeds host-to-GPU loading, whereas BlitzScale mostly avoids repeated host traffic by sourcing weights from deployed GPUs or one cluster-wide host copy via multicast.
- _Sun et al. (OSDI '24)_ - Llumnix dynamically schedules and migrates LLM workloads across existing instances, while BlitzScale focuses on bringing new instances online fast enough that bursts do not require over-provisioning.
- _Zhong et al. (OSDI '24)_ - DistServe demonstrates PD-disaggregated serving and the heavy KV-cache traffic it creates; BlitzScale is designed to autoscale in that setting without letting scaling traffic interfere with serving traffic.

## My Notes

<!-- empty; left for the human reader -->

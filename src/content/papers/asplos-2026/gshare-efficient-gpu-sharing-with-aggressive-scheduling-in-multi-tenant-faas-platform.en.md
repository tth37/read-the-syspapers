---
title: "gShare: Efficient GPU Sharing with Aggressive Scheduling in Multi-tenant FaaS platform"
oneline: "Decouples GPUs from FaaS keep-alive state, remaps fine-grained vGPUs across microVMs, and schedules by deadline slack to cut GPU cost with bounded latency."
authors:
  - "Yanan Yang"
  - "Zhengxiong Jiang"
  - "Meiqi Zhu"
  - "Hongqiang Xu"
  - "Yujun Wang"
  - "Liang Li"
  - "Jiansong Zhang"
  - "Jie Wu"
affiliations:
  - "China Telecom Cloud Computing Research Institute, Beijing, China"
  - "China Telecom Cloud Technology Co. Ltd., Chengdu, China"
  - "China Telecom Cloud Technology Co. Ltd., Guangzhou, China"
  - "Temple University, Philadelphia, United States"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790168"
tags:
  - serverless
  - gpu
  - virtualization
  - scheduling
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

gShare treats GPUs in a FaaS platform as reclaimable, fine-grained vGPU slices rather than resources permanently tied to a warm function instance. It combines kernel-level vGPU remapping, checkpoint-based model save/restore, and a slack-aware scheduler that delays sharing decisions until necessary. The paper reports `43%-63%` lower GPU usage than keep-alive baselines while still meeting more than `95%` of latency targets.

## Problem

The paper starts from a mismatch between current FaaS abstractions and GPU-backed inference. CPU functions can be allocated and reclaimed finely, but GPU functions are usually coarse-grained and stay attached for the entire warm lifetime of the function. That is especially wasteful for small models: among 3,000 popular models from TensorFlow Hub and Hugging Face, `66.4%` fit under `1GB` and `78.1%` fit under `4GB`, so provisioning GPUs in `1GB` chunks can waste up to `85%` of memory.

Keep-alive policies magnify the problem. GPU cold starts are slower, so providers keep idle GPU functions warm, but the paper measures roughly `10x` higher idling cost than CPU keep-alive. Prior serverless sharing systems try to recover that waste with model swapping, yet their proxy-based control plane adds overhead and uses heuristics like popularity rather than actual request deadlines. The core question is therefore how a VM-isolated FaaS platform can share GPUs aggressively enough to save money without converting reuse into queueing delay and SLO misses.

## Key Insight

The central claim is that serverless GPU efficiency improves once GPU ownership is decoupled from function liveness. If a function can keep its memory image while surrendering its GPU slice, the platform can recycle the device across tenants instead of paying to keep every warm instance fully provisioned. Sharing decisions should then be driven by deadline slack, not popularity: requests whose swap time plus execution time already threaten the SLO keep a private cached slice, while the rest can be scheduled lazily and only dispatched once their slack is nearly exhausted.

## Design

gShare has three main pieces. First, it builds a fine-grained vGPU layer for microVM-based FaaS workers. GPU slices can be as small as `128MB`, with proportional compute quotas, and the virtualization lives in kernel space using `vfio-mdev`, direct I/O, and per-vGPU channels. That lets tenant images keep standard ML frameworks while the host enforces memory and compute limits.

Second, it separates function memory management from GPU attachment. A "pseudo offloading" hot-plug path keeps vGPU connection metadata while releasing only the hardware resource, cutting hot-plug latency from about `0.7s` to under `1ms`. Model state is saved with CUDA checkpoint/restore into a shared host-memory pool, and the fast path often avoids a full swap-out plus swap-in pair by reusing cached snapshots and overwriting device memory directly.

Third, the request scheduler co-designs sharing with SLO enforcement. The ideal problem is a mixed-integer nonlinear program, but the implementation uses an online heuristic called Dual-Queue Lazy Scheduling. Requests whose predicted swap time plus execution time already make them risky go into a `cacheQueue`, where locality dominates. The rest go into a `shareQueue`, ordered by deadline slack `theta - I - D_hat`. The scheduler waits until slack reaches zero, then either reuses the best feasible shared slice or allocates a new one.

## Evaluation

The evaluation uses a 20-server testbed with 64 NVIDIA A100 GPUs (`40GB` each), split into nine vGPU pool types from `128MB` to `40GB`. Workloads come from three week-long production traces, and the default latency target is `1.5x` each function's `p90` execution time. The baselines are Keepalive, FaasCache, FaaSwap, NoCache, and a FIFO variant of gShare that allocates early rather than lazily.

The headline result is that gShare reduces GPU usage by `63%`, `47%`, and `43%` across the three traces while keeping function performance close to Keepalive and still satisfying more than `95%` of latency targets. Relative to FaaSwap, the introduction claims `24%-58%` lower cloud cost and `1.8x-2.7x` better combined cost/performance. gShare raises `p95` latency for bad requests by about `15%`, but has negligible effect on `p50`, which supports the claim that lazy scheduling mostly changes the tail rather than the common case.

The deeper breakdown explains why misses happen. Table 2 shows that in gShare, swap and scheduling wait account for less than `1%` of the requests that still meet their targets, while model swap time is the dominant reason violated requests miss across nearly all methods. The engineering results are also solid: a full-quota vGPU performs about the same as a physical GPU, throughput scales nearly linearly with vGPU quota, and the scheduler reaches about `75%` of the offline optimum while making decisions `10x-100x` faster than the MINLP solver. The paper translates those savings into about `$330,000` per year per cluster under AWS-style pricing, or up to `$400,000` under the Aliyun model.

## Novelty & Impact

Relative to _Yu et al. (ATC '25)_, which archives the FaaSwap line of work, gShare's key move is to replace proxy-centric sharing with kernel-level vGPU remapping plus slack-aware scheduling. Relative to _Yang et al. (ASPLOS '22)_, which shows serverless inference can be fast, gShare is about making GPU-backed serverless inference economically dense under VM isolation rather than merely low-latency. Its impact is therefore both mechanistic and operational: new GPU-sharing machinery, but also a clearer path to lower serverless GPU cost.

## Limitations

The paper's scheduling model assumes requests already have a pre-launched function instance, so it does not fully solve the interaction between GPU sharing and true cold-start-heavy workloads. Its implementation is also tightly bound to NVIDIA GPUs and a large amount of kernel engineering: rewriting `57` `ioctl` interfaces and roughly `60,000` lines of control-path code is a real deployment barrier, and AMD support is still in progress.

There are algorithmic limits too. gShare's vGPU time slicing is non-preemptive within a kernel, so long kernels can still create underutilization and queueing interference. The scheduler is server-local rather than cluster-global, and the comparison to FaaSwap depends on the authors' re-implementation rather than a released artifact.

## Related Work

- _Yu et al. (ATC '25)_ — Torpor/FaaSwap also uses model swapping for serverless GPU sharing, but gShare replaces its proxy-based control plane with direct vGPU remapping and deadline-slack scheduling.
- _Yang et al. (ASPLOS '22)_ — INFless shows that serverless inference can hit low latency, whereas gShare focuses on reclaimable GPU allocation and cross-tenant sharing under microVM isolation.
- _Crankshaw et al. (NSDI '17)_ — Clipper studies low-latency model serving and deadline-aware dispatch in a serverful setting, without the VM-level GPU virtualization and keep-alive cost model that dominate gShare.
- _Agache et al. (NSDI '20)_ — Firecracker provides the microVM substrate that makes VM-isolated serverless practical, but it does not address accelerator virtualization or GPU sharing.

## My Notes

<!-- empty; left for the human reader -->

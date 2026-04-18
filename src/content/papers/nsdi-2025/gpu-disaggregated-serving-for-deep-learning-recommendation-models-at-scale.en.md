---
title: "GPU-Disaggregated Serving for Deep Learning Recommendation Models at Scale"
oneline: "Prism splits DLRMs into CPU-heavy and GPU-heavy subgraphs, serves them across RDMA-linked CN and HN pools, and turns stranded training GPUs into elastic recommender capacity."
authors:
  - "Lingyun Yang"
  - "Yongchen Wang"
  - "Yinghao Yu"
  - "Qizhen Weng"
  - "Jianbo Dong"
  - "Kan Liu"
  - "Chi Zhang"
  - "Yanyi Zi"
  - "Hao Li"
  - "Zechao Zhang"
  - "Nan Wang"
  - "Yu Dong"
  - "Menglei Zheng"
  - "Lanlan Xi"
  - "Xiaowei Lu"
  - "Liang Ye"
  - "Guodong Yang"
  - "Binzhang Fu"
  - "Tao Lan"
  - "Liping Zhang"
  - "Lin Qu"
  - "Wei Wang"
affiliations:
  - "Hong Kong University of Science and Technology"
  - "Alibaba Group"
conference: nsdi-2025
tags:
  - ml-systems
  - gpu
  - disaggregation
  - rdma
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`Prism` is a production DLRM serving system that splits a recommendation model into CPU-heavy and GPU-heavy subgraphs and executes them on RDMA-linked CPU nodes (`CNs`) and GPU nodes (`HNs`). The key result is not just that remote execution is possible, but that the system can use otherwise stranded GPUs in training servers without blowing up latency: in production deployment it cuts CPU fragmentation by 53%, GPU fragmentation by 27%, and saves over 90% of GPUs during peak promotional events.

## Problem

The paper starts from a mismatch between how datacenters are built and how deep learning recommendation models actually consume resources. DLRMs are not uniformly GPU-bound. Their sparse embedding lookups need large memory footprints and many CPU cores, while only the dense MLP or transformer-style layers are strongly GPU-efficient. In Alibaba's production clusters, a typical DLRM instance requests 48 CPUs and 1 GPU, whereas a training server commonly has 96 CPUs and 8 GPUs. Two DLRM instances can therefore consume all CPUs on a server while leaving 6 GPUs idle and unusable for other jobs.

That mismatch gets worse under elastic demand. Recommendation traffic has strong diurnal variation, with peak-to-valley ratios above 6x, and seasonal shopping events push demand about 1.3x above normal daily peaks. Provisioning a dedicated inference fleet for the worst case is too expensive, so operators want to borrow capacity from training clusters during spikes. But that also fails on monolithic servers: training nodes have low CPU-to-GPU ratios, while more than 90% of the production DLRMs in the trace need CPU-to-GPU ratios above 20. In other words, the extra GPUs exist, but the surrounding server shape makes them hard to use.

The paper's target is therefore broader than accelerating one model. It wants a serving system that can separate CPU and GPU provisioning, scale both independently, and still hit tens-of-milliseconds latency SLOs under bursty traffic. The hard part is that disaggregation introduces extra network hops and scheduling complexity exactly on the critical path of online inference.

## Key Insight

The core insight is that DLRMs have an unusually clean operator-level split, so the right place to disaggregate is the computation graph itself. Embedding-related operators dominate CPU time, while matrix multiplications and attention dominate GPU time. Because online DLRM graphs stay structurally stable after deployment even as parameters update, Prism can partition the graph once, keep the cut stable, and then scale the two halves independently.

That is a more practical choice than API-level GPU remoting or hardware-level GPU pooling. API remoting treats all CUDA calls alike and leaves little room for DLRM-specific optimization; hardware disaggregation needs infrastructure changes and often stays rack-local. Prism instead uses graph-level disaggregation: run CPU- and memory-intensive operators on `CNs`, offload the GPU-efficient suffix to `HNs`, and rely on fast RDMA plus careful placement and traffic control to keep the added latency within SLO.

## Design

Prism is inserted at the end of the existing production optimization pipeline rather than replacing it. Model owners still use the usual framework optimizations; only after those passes finish does Prism rewrite the graph for disaggregated serving. Its partitioner begins from GPU-efficient seed operators, then runs a DFS-style coloring pass upstream and downstream to collect as much GPU-friendly work as possible, stopping at CPU-intensive operators such as embedding lookups. The result is a `CN` subgraph that receives the original request and an `HN` subgraph that receives intermediate tensors.

The partitioner also applies two communication-aware optimizations. First, it preserves constant subgraphs on the `HN` side so constant expressions are computed once and cached instead of being repeatedly transferred. Second, when several transmitted tensors are derived from the same ancestor, Prism may send only the ancestor tensor if that is cheaper than sending the derived tensors individually. The runtime packages the remote section as a unified `FusedGraphOp`, uses a shared memory pool, and leverages GPUDirect RDMA so data written for transmission already lands in the RPC subsystem's buffer. For small tensors it uses RDMA send/recv, and for larger ones RDMA write. The paper reports 19-181% improvement from these transfer optimizations, and observes that 80% of production services transfer under 10 MiB per request to the `HN`.

The second major component is topology-aware resource management. Prism constrains all instances of one service to the same pod because cross-pod RDMA costs more than 50% performance. Within a pod it prefers placing instances under the same access switch, and inside a node it scores allocations by GPU-to-RNIC or CPU-to-RNIC path length, favoring GPUs and RNICs on the same PCIe switch. This matters because the paper measures 21-36% GPUDirect RDMA throughput loss from worse GPU-RNIC topology.

The third component is the SLO-aware communication scheduler. The system explicitly manages incast when many `CNs` send tensors to a smaller set of `HNs`. Prism uses a window-based admission scheme, adapts the window using congestion-notification packets from RNICs and switches, and orders delayed requests by earliest deadline first rather than FCFS. The scheduling objective is simple: maximize the number of requests whose transmission starts early enough to still satisfy their end-to-end SLO.

## Evaluation

The evaluation is unusually production-oriented. The authors test five real Alibaba recommendation models with embedding tables from 100 GiB to 700 GiB. The default `HN` has 128 CPU cores, 8 A100 GPUs with 80 GiB each, and four 200 Gbps RNICs; the `CN` has 128 CPU cores and one 200 Gbps RNIC. Baselines are the existing optimized monolithic serving stack, plus a local-disaggregation ablation where the split graph stays on one physical host.

For sequential single-request execution, remote disaggregation adds overhead, increasing average latency by 10-38%. That is the pessimistic regime. Under sustained load, Prism is more interesting: it often lowers latency and increases goodput relative to the monolithic baseline because `FusedGraphOp` avoids GPU queue interleaving and turns host-to-device transfers into device-to-device RDMA transfers. The paper highlights one challenging model, `Model-XL`, where communication exceeds 9 MiB per request and GPU compute is under 1 ms; even there Prism loses at most 6%.

Resource efficiency is the stronger result. Total CPU consumption stays close to the baseline for the same goodput, but CPU usage on GPU nodes drops by 15-84x, which is exactly the resource that previously stranded GPUs. On one multi-GPU node, Prism improves throughput by 5-9x because it can pack many more serving instances than the monolithic baseline. With MIG enabled, `Model-XS` scales to 24 `HN` instances on one server and reaches 9x the baseline throughput.

The cluster-level numbers are the paper's best evidence. In a production GPU cluster with about 90% allocation, Prism reduces fragmented CPU resources by 53% (18k cores) and fragmented GPUs by 27% (60 GPUs). During seasonal promotions, three online services together need only 6 borrowed A100 nodes instead of up to 70 A100 nodes under the old monolithic deployment pattern, which is where the claimed 90%+ GPU savings comes from. Given that there is no prior production GPU-disaggregated DLRM system to compare against, the baseline choice is reasonable, though it does leave the paper stronger on before/after operational evidence than on broad cross-system comparisons.

## Novelty & Impact

The paper's main novelty is not merely "serve DLRMs over RDMA." It combines graph-level model partitioning, topology-aware placement, and SLO-aware network scheduling into a full production path that makes heterogeneous training clusters usable for recommendation serving. That distinguishes it from generic GPU remoting systems, which do not exploit DLRM structure, and from recommender-serving papers that still assume monolithic servers.

This work will matter to operators of large recommendation systems, but it should also be cited more broadly in datacenter and ML-systems work on disaggregation. It is a concrete example of a narrow, application-specific disaggregation design beating more general abstractions because the operator split, traffic shape, and placement policy are all co-designed.

## Limitations

The design is specialized to DLRMs with a stable split between embedding-heavy CPU work and dense GPU work. The paper argues that this graph structure stays stable through deployment, but it does not show how robust the partitioning heuristic is for models whose cut is less obvious or whose intermediate tensors are much larger. The favorable communication regime also seems important: 80% of services send under 10 MiB per request, and the return path is tiny. Models with fatter cross-cut activations may look much worse.

Deployment assumptions are also fairly strict. Prism keeps all instances of one service inside a pod because cross-pod placement costs more than 50% performance, so the system depends on local placement headroom. The paper also reports interference from mixed online/offline workloads under container overlay networking, where TCP activity can perturb RDMA performance enough that offline tasks must be evicted. That is a real operational caveat, not a solved problem.

Finally, the evaluation is strong on internal production evidence but narrow on external reproducibility. Most experiments use an optimized internal TensorFlow stack, the graph partitioner is heuristic rather than proven optimal, and the paper does not compare against an independent disaggregated inference system because none appears to exist in this domain.

## Related Work

- _Ke et al. (HPCA '22)_ - `Hercules` provisions DLRM inference on monolithic heterogeneous servers, while `Prism` changes the deployment model by splitting CPU and GPU execution across separate node pools.
- _Li et al. (EuroSys '23)_ - `Lyra` elastically colocates training and inference in shared clusters, whereas `Prism` focuses on removing the CPU-to-GPU mismatch that makes loaned training nodes inefficient for DLRM serving.
- _Duato et al. (HPCS '10)_ - `rCUDA` exposes remote GPUs by remoting CUDA APIs, while `Prism` partitions the DLRM graph itself and jointly optimizes communication, placement, and SLO-aware scheduling.
- _Shan et al. (OSDI '18)_ - `LegoOS` is a general-purpose OS for hardware disaggregation; `Prism` is a narrower but production-tested application-level system specialized for recommender inference.

## My Notes

<!-- empty; left for the human reader -->

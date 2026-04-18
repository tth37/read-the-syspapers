---
title: "Fast Cloud Storage for AI Jobs via Grouped I/O API with Transparent Read/Write Optimizations"
oneline: "AITURBO uses grouped read/write APIs, host-DRAM staging, and compute-fabric broadcasts so cloud storage can transparently deduplicate and rebalance AI checkpoint and KVCache I/O."
authors:
  - "Yingyi Hao"
  - "Ting Yao"
  - "Xingda Wei"
  - "Dingyan Zhang"
  - "Tianle Sun"
  - "Yiwen Zhang"
  - "Zhiyong Fu"
  - "Huatao Wu"
  - "Rong Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "Huawei Cloud"
conference: fast-2026
category: ai-era-storage
tags:
  - storage
  - disaggregation
  - datacenter
  - llm-training
  - llm-inference
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`AITURBO` treats AI storage traffic as grouped collective I/O rather than independent file operations. Its grouped API lets the storage layer deduplicate payloads, stage data in idle host DRAM, and use the faster compute fabric when the storage fabric is the bottleneck. On checkpoint writes it is `3.9-58.8x` faster than the provider's general-purpose storage path and up to `5.9x` faster than `GEMINI`; on KVCache reads it lowers mean TTFT by `23%` against `Mooncake`.

## Problem

The paper starts from a concrete cloud observation: at Huawei Cloud, AI jobs already consume more than `10%` of cloud-storage bandwidth in one local datacenter. The dominant operations are bulk checkpoint writes, checkpoint reads for autoscaling or recovery, and KVCache reads for LLM serving. These are not tiny metadata-heavy requests; they move tens of megabytes to hundreds of gigabytes, so end-to-end time is dominated by bandwidth.

Disaggregated cloud storage makes that bandwidth hard to improve cheaply. Compute servers reach storage over a slower storage fabric, while XPUs already have a faster compute fabric among themselves. Buying more storage bandwidth is costly and still does not remove the frontend bottleneck imposed by each compute node's storage NICs; the paper's example shows a `16x` per-GB price jump when provisioned bandwidth rises from `1.6 GB/s` to `80 GB/s`. Application-level fixes are also unsatisfying. `Megatron` spends roughly a quarter of its codebase on checkpoint I/O but still cannot optimize with a global view of storage topology.

The missing piece is group semantics. In distributed training, all ranks write checkpoint shards together. In autoscaling, multiple new instances read the same model together. In agentic serving, several requests may need the same shared-prefix KVCache blocks at once. If storage only sees singleton `getfile` and `putfile` calls, it misses both duplication and opportunities to route traffic more intelligently.

## Key Insight

The central claim is that cloud storage should expose a minimal grouped-I/O abstraction and then let the storage layer derive the optimizations that frameworks now implement separately. Once the application tells storage which clients participate in a read or write group, the service can detect duplicate payloads, see where the real bottleneck link is, and decide when compute-fabric transfers should replace repeated storage transfers.

The target is storage overhead as experienced by the AI job, not abstract storage throughput. For writes, the key observation is that many checkpointing workloads can resume once data reaches replicated DRAM buffers, with durable write-back deferred. For reads, fetching one copy from storage and broadcasting it across the compute fabric can beat issuing the same read to storage from every XPU. `AITURBO` therefore turns storage into a collective-I/O planner for AI jobs.

## Design

`AITURBO` adds `group_getfile` and `group_putfile` to the storage API. The caller still asks to read or write files, but now also names the participating group. Grouped writes return two futures: one for "buffered in DRAM" and one for "durably stored." That split is useful for periodic checkpoints, where buffered persistence is often enough to unblock training.

The implementation has three main pieces: a staging-buffer manager that pools idle host DRAM, a communicator that moves data over the compute fabric, and a stateless job controller that computes read/write plans. The grouped-write path has three phases: detect duplicates, place the deduplicated chunks into DRAM buffers, and flush those buffers to storage. Deduplication is checksum-based, supports granularity from whole files down to `4 MB` chunks, and is cheap enough to run on XPUs (`7.8 ms` to checksum a `1 GB` file on the paper's `V100`, versus `35.6 ms` on CPU). Because checkpoint structure is repetitive, the controller caches dedup metadata across rounds.

The write and read planners are the core mechanism. The paper formulates buffer placement and write-back as a bilinear program that minimizes completion time under source, destination, link-bandwidth, replication, and DRAM-capacity constraints. The solver fixes the end-to-end time variable `t`, checks linear feasibility, and tightens the bound iteratively; on a `38B` training trace over `64` XPUs, a simple single-threaded Python solver finds a plan in `4` seconds. Grouped reads reuse the same idea from the opposite direction: fetch only one copy of duplicated chunks from storage, then broadcast them along the compute fabric using a `BlitzScale`-style serial chain. The system also supports distributed caching across compute nodes, uses a tensor-native file format to avoid serialization, and establishes direct point-to-point RDMA connections instead of paying `NCCL` communicator setup cost.

## Evaluation

The experiments run on two clusters with up to `64` XPUs, including `Ascend 910B` and `NVIDIA A800` systems. Each compute node has eight XPUs, `192` CPU cores, `1.5 TB` of host DRAM, one `100 Gbps` storage NIC, and up to `30 GB/s` of backend storage bandwidth. This is a good fit for the paper's disaggregated-storage argument.

For checkpoint writes, the authors evaluate `1.5B`, `13B`, and `38B` models with and without `ZeRO`, comparing `Megatron` over the provider's existing storage path (`SFST URBO`), `GEMINI`, and `AITURBO`. `AITURBO` is up to `58x` faster than `Megatron` over `SFST URBO`, and up to `5.9x` faster than `GEMINI` when duplicated payload exists across nodes. The ablation is also informative: deduplication alone gives another `4.3-47.2%` improvement for duplicated checkpoint configurations, and the explicit write plan adds up to `76%` more reduction by balancing traffic across nodes.

Checkpoint reads show the strongest benefit of grouped reads. Before any copy is cached, all systems are equally storage-bound: reading the `135 GB` `Qwen 72B` checkpoint on `8` XPUs with `1 GB/s` provisioned storage takes `173` seconds. After one copy is loaded, however, `AITURBO` can broadcast it quickly across the compute fabric. The paper reports `2.25` seconds to deploy `Qwen 72B` on `64` XPUs from the cached copy, whereas tuned `ServerlessLLM` still needs `1,384` seconds to fan the checkpoint out through the slower storage path.

The KVCache study is smaller but consistent with the same story. Replaying the `Qwen-Bailian` trace on `8` XPUs with `Qwen-14B`, replacing `Mooncake`'s storage read path with `AITURBO` lowers mean TTFT by `23%`. The paper also makes a credible engineering-effort claim: integrating `AITURBO` requires only `286` LoC on top of `Megatron`, versus `2,228` lines of application-level optimization in the original framework, and extra group-coordination overhead tops out at only `45 ms` on `64` XPUs.

## Novelty & Impact

Relative to _Wang et al. (SOSP '23)_, `AITURBO` pushes the `GEMINI` idea of in-memory checkpointing down into the storage layer and broadens it with transparent deduplication and topology-aware planning. Relative to _Wan et al. (NSDI '25)_, it seeks the same kind of optimized checkpoint I/O as `ByteCheckpoint` but moves the logic out of each training framework and into a storage API that also serves inference reads. Relative to _Qin et al. (FAST '25)_ and _Zhang et al. (OSDI '25)_, it turns ideas from KVCache systems and autoscaling broadcast into a common grouped-I/O substrate.

That makes the contribution feel like a mechanism rather than a one-off optimization. It gives cloud providers a way to exploit spare DRAM and spare compute-fabric bandwidth without provisioning a more expensive storage tier, and it gives framework authors a much smaller integration surface. The fact that Huawei has already deployed it for production training jobs makes the systems impact claim believable.

## Limitations

The paper is explicit that `AITURBO` targets bulk transfers. Small reads and writes are unlikely to benefit, because the design assumes the dominant cost is bandwidth rather than metadata or control overhead. The benefits also depend on there being useful idle host DRAM and underutilized compute-fabric bandwidth; if either resource is already saturated, the main advantage shrinks.

The grouped API is also not free semantically. Applications must identify the participating group, and the paper admits this is harder for live inference than for fixed training jobs; the `Mooncake` experiment therefore does not use the full group API. Isolation is handled only with off-the-shelf hardware QoS, and the buffered-write model is still a durability tradeoff before `future_1` completes. Those are reasonable engineering choices, but they limit how universal the design is.

## Related Work

- _Wang et al. (SOSP '23)_ — `GEMINI` uses in-memory checkpoints for fast failure recovery, while `AITURBO` adds transparent deduplication and storage-layer read/write planning across broader AI I/O patterns.
- _Wan et al. (NSDI '25)_ — `ByteCheckpoint` also optimizes checkpoint traffic, but it requires framework-specific support; `AITURBO` moves the optimization boundary into the storage service through grouped APIs.
- _Qin et al. (FAST '25)_ — `Mooncake` is a KVCache-centric serving architecture, whereas `AITURBO` is a general cloud-storage substrate that accelerates checkpoint reads, checkpoint writes, and KVCache misses.
- _Zhang et al. (OSDI '25)_ — `BlitzScale` shows fast large-model autoscaling with host caching and broadcast; `AITURBO` reuses similar broadcast intuition as one phase inside a more general grouped-read planner.

## My Notes

<!-- empty; left for the human reader -->

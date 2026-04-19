---
title: "daredevil: Rescue Your Flash Storage from Inflexible Kernel Storage Stack"
oneline: "daredevil replaces blk-mq's fixed core-to-queue bindings with SLA-aware request routing and NQ scheduling to isolate mixed tenants on commodity NVMe SSDs."
authors:
  - "Junzhe Li"
  - "Ran Shu"
  - "Jiayi Lin"
  - "Qingyu Zhang"
  - "Ziyue Yang"
  - "Jie Zhang"
  - "Yongqiang Xiong"
  - "Chenxiong Qian"
affiliations:
  - "The University of Hong Kong"
  - "Microsoft Research"
  - "Peking University"
  - "Zhongguancun Laboratory"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717482"
code_url: "https://github.com/HKU-System-Security-Lab/Daredevil"
tags:
  - storage
  - kernel
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

daredevil argues that NVMe multi-tenancy breaks not because Linux lacks priority knobs, but because `blk-mq` hard-wires each CPU core to one queue path. It replaces that fixed path with SLA-aware request routing plus queue scheduling, letting latency-sensitive and throughput tenants use different NVMe queues even on commodity SSDs. On the authors' testbeds, that cuts L-tenant latency by up to 3-170x while largely preserving T-tenant throughput.

## Problem

The paper studies a familiar cloud-local-storage setting: multiple tenants share an NVMe SSD, but their SLAs differ sharply. L-tenants issue small requests and care about latency, while T-tenants batch large requests and care about throughput. Once both classes land in the same NVMe I/O queue, head-of-line T-requests delay the smaller L-requests during both submission and completion. In the authors' motivating experiment, forcing L- and T-requests to interfere inside the same queues increases L-tenant average latency by up to 3.49x and tail latency by up to 15.7x.

Existing software fixes inherit `blk-mq`'s structure. FlashShare and D2FQ overprovision queues per core, which means hot cores cannot steal idle queues from cold ones. `blk-switch` uses cross-core scheduling to move work around, but that entangles two different objectives: CPU placement and I/O isolation. None of those designs handles the multi-namespace case cleanly, because Linux builds one `blk-mq` instance per namespace even though namespaces still share the same physical NVMe queues underneath.

## Key Insight

The paper's core claim is that queue ownership should be separated from core ownership. If a core can route a request to any NVMe queue, then queue assignment becomes an SLA problem instead of a static binding problem. That lets the kernel isolate L- and T-requests in software without depending on modified SSD firmware.

This also explains why daredevil can support multiple namespaces with the same mechanism. The queue being used is a device-level fact, not a namespace-local one. Once the block layer can see and schedule queues directly, it can enforce one global policy across all namespaces instead of making each namespace solve the problem independently and incompletely.

## Design

daredevil has three pieces. `blex` is the decoupled block layer. It removes the fixed SQ-to-HQ path in `blk-mq` and exposes each submission queue through a lightweight `nproxy`, so any per-core software queue can reach any NVMe submission queue. That gives full core-to-queue connectivity while preserving driver modularity.

On top of that, `troute` decides where requests go. It derives a tenant's base SLA from `ionice`: real-time tenants become high priority L-tenants, and the rest become low priority T-tenants. It also detects T-tenants that regularly emit synchronous or metadata outlier requests, using `REQ_SYNC` and `REQ_META`, and can assign those tenants both a default low-priority queue and an outlier high-priority queue. Untagged rare outliers are handled with per-request queue selection. The result is queue-level separation without cross-core migration.

The third piece, `nqreg`, assigns each queue a role and schedules queue selection. It splits queues into high- and low-priority groups, then uses a two-step scheduler: first choose a completion queue that best improves IRQ balance, then choose a submission queue under that completion queue that best reduces contention. Merits are smoothed over time, updates are throttled with an MRU policy, and concurrent scheduler queries use RCU. Finally, daredevil makes the service path SLA-aware: high-priority queues notify the controller immediately and use per-request completion, while low-priority queues batch both submission notifications and completions.

## Evaluation

The main evaluation uses Linux 6.1.53 on a 64-core EPYC 7702P server with a 3.2 TB Samsung PM1735 NVMe SSD, and compares daredevil against vanilla `blk-mq` and a port of `blk-switch` to the same kernel. In the main single-namespace FIO test, 4 L-tenants run with increasing T-pressure on 4 shared cores. On the server, daredevil reduces L-tenant 99.9th-percentile latency and average latency by up to 3.2x and 33x; on a second workstation with more submission queues per core, the gains reach 40x and 170x. The paper's broader claim of 3-170x latency reduction is therefore supported, and the effect is strongest exactly where the design says it should be: under heavy queue interference and with more queues available for routing.

The multi-namespace results are the most convincing evidence that the design is not just another single-namespace tuning. With 4, 8, and 12 namespaces, daredevil cuts L-tenant tail latency and average latency by up to 15.3x and 39.3x while keeping throughput comparable to vanilla. That matches the paper's diagnosis that prior software stacks miss interference that survives across namespace boundaries.

The real-workload story is more mixed and therefore more credible. For RocksDB on YCSB, daredevil improves the tail latency of updates in YCSB-A by 2x over `blk-switch`, and also helps YCSB-F. For Filebench Mailserver, it lowers `fsync` latency by 2-3 ms and `delete` latency by 0.5-1.2 ms. But it does little for CPU- or cache-dominated cases such as YCSB-B, YCSB-E, and the cached portion of Mailserver. The overhead study is also useful: cross-core submission and completion steps are 1.4-1.6x and 3.3-3.6x costlier in isolation, yet those costs account for at most 1.7% of end-to-end latency because queue scheduling spreads contention. One red flag is rapid SLA churn: frequent `ionice` updates can drive L-tenant IOPS down to 7.4% of normal and T-throughput to 25%, so the mechanism assumes priorities are not flapping constantly.

## Novelty & Impact

The novelty is not a new SSD scheduler in isolation, but a new decomposition of the Linux storage stack. FlashShare and D2FQ try to separate request classes while keeping `blk-mq`'s basic binding model; daredevil argues that the binding model itself is the obstacle. `blk-switch` is closer in spirit, but it relies on cross-core scheduling, whereas daredevil makes request routing the first-class control point and keeps queue assignment independent from CPU placement.

That is a meaningful systems contribution. Anyone building low-latency local NVMe services for cloud databases, caches, or storage sidecars can cite this paper as evidence that queue-path flexibility matters even before touching firmware. The design also appears extensible to other multi-queue devices, which broadens its relevance beyond just one SSD stack.

## Limitations

The paper is explicit that daredevil does not recover microsecond-scale latency. Even after queue separation, L-requests still see millisecond-scale latency because SSD-internal interference remains, including device-side queueing and flash-media effects. That boundary matters: daredevil fixes a kernel-side bottleneck, not the whole stack.

There are several additional limits. The current design does not support VMs because guest applications are invisible to the host kernel in the required way. It assumes a trusted environment where tenants' `ionice` values honestly reflect SLAs. The benefits are smaller on workloads dominated by CPU or cache activity rather than actual SSD access. And although the evaluation is solid, it still centers on one enterprise SSD plus one workstation SSD rather than a broad hardware survey.

## Related Work

- _Zhang et al. (OSDI '18)_ - FlashShare also targets mixed latency and throughput traffic on NVMe SSDs, but it depends on firmware-aware mechanisms and still works within a more rigid queue-binding structure than daredevil.
- _Woo et al. (FAST '21)_ - D2FQ provides fair queueing for NVMe SSDs, whereas daredevil focuses on isolating SLA classes by removing fixed core-to-queue paths in the kernel storage stack.
- _Hwang et al. (OSDI '21)_ - `blk-switch` is the closest software baseline: it rearchitects Linux storage around cross-core scheduling, while daredevil instead treats request routing and queue scheduling as the main control surface and adds multi-namespace support.
- _Peng et al. (USENIX ATC '23)_ - LPNS tackles latency-predictable local storage virtualization in clouds, while daredevil operates lower in the host kernel and concentrates on queue-level separation over shared NVMe devices.

## My Notes

<!-- empty; left for the human reader -->

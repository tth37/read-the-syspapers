---
title: "Tai Chi: A General High-Efficiency Scheduling Framework for SmartNICs in Hyperscale Clouds"
oneline: "Tai Chi turns idle SmartNIC data-plane cycles into preemptible virtual CPUs, so control-plane work speeds up without breaking data-plane SLOs."
authors:
  - "Bang Di"
  - "Yun Xu"
  - "Kaijie Guo"
  - "Yibin Shen"
  - "Yu Li"
  - "Sanchuan Cheng"
  - "Hao Zheng"
  - "Fudong Qiu"
  - "Xiaokang Hu"
  - "Naixuan Guan"
  - "Dongdong Huang"
  - "Jinhu Li"
  - "Yi Wang"
  - "Yifang Yang"
  - "Jintao Li"
  - "Hang Yang"
  - "Chen Liang"
  - "Yilong Lv"
  - "Zikang Chen"
  - "Zhenwei Lu"
  - "Xiaohan Ma"
  - "Jiesheng Wu"
affiliations:
  - "Alibaba Group"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764851"
tags:
  - smartnic
  - scheduling
  - virtualization
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Tai Chi treats SmartNIC control-plane work as preemptible vCPU execution while keeping data-plane services on native CPUs. A unified IPI layer and a hardware workload probe let the system switch between the two at microsecond scale, cutting production VM startup latency by 3.1x with about 0.7% average data-plane overhead.

## Problem

Modern SmartNIC deployments already split data-plane services such as DPDK and SPDK from control-plane tasks such as device initialization, monitoring, and orchestration. Operators pin CPUs statically so control-plane code cannot disturb latency-sensitive packet and storage processing. The paper shows that this is both wasteful and increasingly inadequate: in Alibaba's IaaS fleet, data-plane CPUs spend 67.5% of cycles idle for 99% of runtime, yet control-plane work still misses SLOs as instance density rises. At 4x density, average control-plane task time grows 8x and VM startup time exceeds its target by 3.1x.

Borrowing idle data-plane cycles is not straightforward. Control-plane tasks are not best-effort batch jobs; they also have hard operational SLOs. More importantly, they regularly enter millisecond-scale non-preemptible kernel routines, so co-running them directly with data-plane threads can inject long-tail latency spikes. The production trace reports more than 456K routines longer than 1 ms in 12 hours, with a maximum of 67 ms. Existing LC/BE schedulers mostly target bare metal, assume different task semantics, need dedicated scheduling CPUs, or require intrusive changes across a control-plane ecosystem of 300 to 500 heterogeneous tasks.

## Key Insight

The central idea is to use virtualization as a precise scheduling primitive rather than as a full guest boundary. If control-plane tasks run inside vCPU contexts, they become preemptible at VM-exit boundaries even when their code is inside non-preemptible kernel paths. If data-plane services remain on physical CPUs in the native SmartNIC OS, their steady-state fast path avoids the usual virtualization tax.

This would still seem too slow because switching away from a vCPU costs about 2 microseconds. Tai Chi's second insight is that SmartNIC I/O accelerators observe incoming work before software does. The paper measures a 3.2 microsecond preprocessing window, enough to trigger a preemption and restore the data-plane thread before the packet reaches the polling loop. That turns hardware offload into a scheduling oracle.

## Design

Tai Chi exposes virtual CPUs and physical CPUs inside one OS image. Control-plane tasks are bound to vCPUs using normal CPU affinity, while data-plane services stay pinned to physical CPUs. The vCPU scheduler performs context switches through a dedicated softirq. When the data plane appears idle, Tai Chi picks a runnable vCPU and enters it on that physical core. When a time slice expires or new I/O arrives, it saves the vCPU state, restores the physical CPU state, and resumes the data plane.

The software workload probe drives DP-to-CP scheduling. Each polling data-plane thread reports extended empty-polling streaks through a small API, and Tai Chi adapts the emptiness threshold based on VM-exit reasons. Time-slice expirations mean the core stayed idle longer than expected, so the threshold decreases; preemptions caused by newly arriving I/O mean Tai Chi yielded too aggressively, so the threshold increases. vCPU time slices start at 50 microseconds, double when idleness persists, and reset when the hardware probe forces a preemption.

Two mechanisms make the single-OS illusion work. First, the unified IPI orchestrator intercepts inter-processor interrupts and routes them correctly across physical CPUs and vCPUs, including waking sleeping vCPUs when needed. Tai Chi also registers vCPUs as native CPUs, so existing control-plane processes need no code changes to use them. Second, the hardware workload probe runs in the SmartNIC accelerator. It keeps per-CPU P/V state, checks the destination CPU before I/O preprocessing, and raises an interrupt if that CPU is currently running a vCPU. Tai Chi overlaps the resulting VM-exit with the accelerator's 2.7 microsecond preprocessing plus 0.5 microsecond DMA stage, effectively hiding the switch back to the data plane. The paper also adds a lock-aware rule: if a preempted control-plane task holds a lock, Tai Chi immediately rehomes that vCPU on another available core to avoid deadlock.

## Evaluation

The evaluation uses an IaaS SmartNIC deployment with 12 SmartNIC CPUs, 96 host CPUs, and production-like networking and storage services. The baseline is the production static partition of 8 CPUs for the data plane and 4 for the control plane. That is the right deployment baseline, though it means the paper mostly argues through ablations rather than direct head-to-head comparisons with prior academic schedulers.

On the control plane, Tai Chi improves the synthetic CP benchmark by 4x at 32 concurrent tasks while holding data-plane utilization at the production p99 level of 30%. On the virtualization question, the ablations are decisive: running the data plane inside vCPUs costs about 8% network throughput and 6% storage IOPS, while a type-2 QEMU/KVM design loses 26% and 25.7%. Full Tai Chi keeps those overheads to 0.2% and 0.06%, which supports the claim that DP must stay on physical CPUs. The hardware probe is equally important: without it, ping RTT rises from 26/30/38 microseconds min/avg/max to 32/37/115; with it, Tai Chi is effectively identical to baseline at 27/30/38. Across netperf, sockperf, MySQL, and Nginx, average data-plane overhead is 0.7%, peaking at 1.92%. The strongest evidence is the production deployment result: over more than three years, high-density clusters saw average VM startup latency fall by 3.1x with no reported user-visible I/O SLO violations during rollout and steady operation.

## Novelty & Impact

Tai Chi's novelty is the combination of three ideas that are usually studied separately: vCPU-based preemptibility, native same-OS IPC between virtual and physical CPUs, and accelerator-assisted prediction of when the data plane must resume. The result is not just a better scheduler; it is a SmartNIC execution model that lets cloud providers treat spare data-plane cycles as safe, reclaimable control-plane capacity. This paper is likely to matter to SmartNIC runtime designers, cloud control-plane engineers, and researchers studying heterogeneous scheduling under small CPU budgets.

## Limitations

The approach depends on hardware-assisted virtualization plus programmable SmartNIC accelerators that expose the needed preprocessing window. Its implementation also assumes deep kernel integration, IPI interception, and a small data-plane API change to report idle polling, so "zero code modifications" applies to legacy control-plane systems, not to the whole stack. The evidence for cross-vendor portability is architectural rather than empirical: the deployment is from one provider, and the paper does not show the framework on third-party SmartNIC platforms. The evaluation is strong on internal ablations and production relevance, but weaker on direct comparison against other academic schedulers under identical hardware conditions.

## Related Work

- _Ousterhout et al. (NSDI '19)_ - Shenango reclaims cores for latency-sensitive services on bare metal; Tai Chi targets SmartNIC data/control-plane co-scheduling where the borrowed work also has SLOs.
- _Fried et al. (OSDI '20)_ - Caladan reallocates cores at microsecond timescales, but still relies on conventional software scheduling paths that do not break SmartNIC control-plane non-preemptible routines.
- _Iyer et al. (SOSP '23)_ - Concord improves microsecond-scale scheduling efficiency, whereas Tai Chi uses hybrid virtualization and accelerator hints to preserve both native IPC and SmartNIC compatibility.
- _Barham et al. (SOSP '03)_ - Xen demonstrates type-1 virtualization as a general isolation substrate; Tai Chi keeps only the control plane virtualized so the data plane avoids guest-mode overhead.

## My Notes

<!-- empty; left for the human reader -->

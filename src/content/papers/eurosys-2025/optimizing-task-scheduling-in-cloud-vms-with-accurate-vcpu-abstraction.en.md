---
title: "Optimizing Task Scheduling in Cloud VMs with Accurate vCPU Abstraction"
oneline: "vSched probes vCPU capacity, activity, and topology from inside the guest, then steers CFS away from slow, stacked, or sleeping vCPUs without hypervisor changes."
authors:
  - "Edward Guo"
  - "Weiwei Jia"
  - "Xiaoning Ding"
  - "Jianchen Shan"
affiliations:
  - "Hofstra University"
  - "The University of Rhode Island"
  - "New Jersey Institute of Technology"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3696092"
code_url: "https://github.com/vSched"
tags:
  - scheduling
  - virtualization
  - kernel
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

vSched argues that Linux inside a cloud VM schedules against a false CPU model: vCPUs change capacity, disappear for inactive periods, and move across topologies. It probes those properties from inside the guest and feeds them into CFS, yielding up to 42% lower tail latency, up to 82% higher throughput in underloaded overcommitted VMs, and only 0.7% average overhead when the default abstraction is already accurate.

## Problem

In a VM, vCPUs are not ordinary cores. A runnable task may stop making progress because the host preempted its vCPU; an idle vCPU may look attractive even when its true capacity is poor; and the topology Linux sees can be stale or wrong. As a result, existing capacity-aware and topology-aware heuristics misplace work, small tasks land on high-latency vCPUs, and running tasks can stall even though another vCPU in the same VM is idle.

Even work conservation can backfire: scheduling onto a very weak idle vCPU creates stragglers, and scheduling onto an idle vCPU stacked with another busy vCPU can trigger priority inversion or lock-holder-style pathologies. Prior fixes usually require hypervisor changes, which are hard to deploy across public or multi-cloud environments. The paper asks whether the guest kernel can recover enough vCPU truth on its own to schedule well without paravirtualization.

## Key Insight

The key insight is that the guest does not need full hypervisor state. It only needs the three properties that actually drive scheduler decisions: current vCPU capacity, expected wakeup latency, and effective topology. If those can be probed cheaply online, Linux can reuse most of CFS and add only a few virtualization-aware heuristics where the default abstraction is structurally wrong.

## Design

vSched combines `vProbers` with three policies. `vcap` cooperatively samples steal time and periodic high-priority probes to estimate dynamic capacity, then smooths the result with EMA. `vact` uses a heartbeat plus steal-time jumps to infer whether a vCPU is active and to estimate average inactive periods, which the paper treats as vCPU latency. `vtop` infers topology from cache-line transfer latency between vCPU pairs, distinguishing SMT, same-socket, cross-socket, and stacked relationships.

Those signals feed `bvs`, `ivh`, and `rwc`. `bvs` steers small latency-sensitive tasks toward high-capacity, low-latency vCPUs that are already active or likely to wake soon. `ivh` proactively migrates a CPU-bound running task off a vCPU that is about to go inactive; the crucial trick is pre-waking the target and completing the move only when both sides are active, so migration delay does not erase the benefit. `rwc` intentionally hides harmful idle vCPUs, especially stragglers and stacked ones, from task placement. The prototype extends Linux 6.1 CFS with a kernel module and BPF hooks and totals 1612 LoC.

## Evaluation

Evaluation on x86 Linux VMs over KVM is well aligned with the thesis: the authors first validate probing, then show that better abstraction improves existing heuristics, and finally measure the new policies. `vtop` reconstructs topology quickly, with full probing taking 547 ms on the smaller VM and 665 ms on the larger one.

The probe results matter. With asymmetric capacity, `vcap` moves Sysbench execution onto fast vCPUs from 44% to 81%, yielding 32% higher throughput; even in symmetric settings it cuts adverse migrations by 74% and improves throughput by 4%. With correct SMT/socket topology, Linux uses 15-16 cores instead of 11-12 in one underloaded test, boosts Matmul by up to 18% in mixed workloads, and improves average throughput by 26% across Dedup, Nginx, and Hackbench while cutting IPIs by as much as 99%.

The activity-aware policies are the paper's main win. `bvs` reduces Tailbench p95 latency by 42% on average; on Masstree, queueing time drops from 32.73 ms to 9.92 ms without best-effort work and from 20.66 ms to 15.47 ms with it. `ivh` improves throughput by up to 82% in overcommitted underloaded VMs and still gives 17% average improvement even at 16 threads. End to end, full vSched improves average throughput by 69% and latency by 1.6x on the resource-constrained VM, and improves throughput by 18% and latency by 2.3x on the higher-performance VM. The main caveat is realism: everything is on KVM with controlled contention, pinning, and bandwidth shaping rather than live public-cloud deployments.

## Novelty & Impact

The novelty is the boundary the paper chooses. Rather than adding one more hypervisor mechanism, vSched treats guest-side scheduling as a probing problem first and a policy problem second. Relative to XPV or CPS it avoids paravirtualization; relative to UFO it focuses on what a tenant can do inside the VM it already has. That makes the paper useful both as a measurement framework for virtualized scheduling pathologies and as a practical recipe for guest kernels that cannot rely on provider cooperation.

## Limitations

Deployability is the biggest limitation. vSched requires guest-kernel changes around CFS, instrumentation, a module, and BPF hooks, so it is not a drop-in feature for stock or commercial guests. Its sampling-based design also reacts within seconds, not at hypervisor event time, so sub-second vCPU changes are better handled by cooperative host-guest schemes such as XPV or CPS.

The evaluation scope is also narrow. Results are on x86 Linux over KVM, and some workloads with user-level spin synchronization still regress slightly when corrected topology exposes more cross-socket imbalance. vSched also cannot control host-side vCPU scheduling, so it can mitigate but not eliminate problems whose best fix is at the hypervisor.

## Related Work

- _Bui et al. (EuroSys '19)_ - XPV exposes NUMA changes from the hypervisor to the guest, while vSched tries to recover enough topology and capacity information from within the guest to avoid paravirtualization.
- _Liu et al. (ASPLOS '23)_ - CPS cooperatively exposes cache topology and core load from the hypervisor; vSched targets a similar scheduler-quality problem but removes hypervisor changes from the deployment path.
- _Panwar et al. (ASPLOS '21)_ - vMitosis probes NUMA locality inside VMs for page-table optimization, and vSched extends that measurement mindset to scheduling-relevant topology, including stacking and SMT relationships.
- _Peng et al. (NSDI '24)_ - UFO improves QoS by managing vCPU allocation at the hypervisor layer, whereas vSched assumes the VM must make the best of the vCPUs it already has.

## My Notes

<!-- empty; left for the human reader -->

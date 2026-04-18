---
title: "To PRI or Not To PRI, That’s the question"
oneline: "VIO moves I/O page-fault handling out of the DMA critical path by snooping VirtIO requests, pinning hot pages, and switching back to passthrough under high IOPS."
authors:
  - "Yun Wang"
  - "Liang Chen"
  - "Jie Ji"
  - "Xianting Tian"
  - "Ben Luo"
  - "Zhixiang Wei"
  - "Zhibai Huang"
  - "Kailiang Xu"
  - "Kaihuan Peng"
  - "Kaijie Guo"
  - "Ning Luo"
  - "Guangjian Wang"
  - "Shengdong Dai"
  - "Yibin Shen"
  - "Jiesheng Wu"
  - "Zhengwei Qi"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Alibaba Group"
conference: osdi-2025
tags:
  - virtualization
  - memory
  - datacenter
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

VIO is a host-side replacement for PRI in oversubscribed clouds. It snoops VirtIO requests before the device consumes them, makes DMA pages resident, pins I/O hot pages, and switches back to passthrough when IOPS is high.

## Problem

SR-IOV and device passthrough give VMs near-native I/O, but because most devices cannot survive I/O page faults, the hypervisor must statically pin DMA-visible guest memory. That blocks overcommit and cold-page reclamation. In the 300-node environment, legacy VMs hold about 800 GB, more than 34% cold; VIO could reclaim about 120 GB per day while meeting SLOs.

PRI promises device-side faults, but the paper argues it is both unavailable and badly placed. Mainstream NICs and storage devices generally lack PRI support, many legacy guests lack support too, and even PRI-enabled handling is slow because faults sit on the DMA critical path. The paper reports latency roughly 3x to 80x slower than CPU page faults and emphasizes the secondary damage from drops and retransmissions.

## Key Insight

VIO's claim is that clouds should avoid device-side faults rather than optimize them. The VirtIO queue is the control point: if the host inspects a request before the backend sees it, the host can resolve missing pages first and the device never experiences IOPF.

This only needs to run when reclamation is worth it. Low-IOPS VMs tolerate a few microseconds of snooping; high-IOPS VMs usually need their memory resident anyway, so VIO switches them back to plain passthrough.

## Design

VIO has three coupled mechanisms. IOPA-Snoop uses a shadow index and shadow available ring. When the guest advances the real ring, the device still sees the old shadow state. A host snooping thread parses descriptors, checks EPT mappings, swaps pages in if needed, and then advances the shadow ring so DMA starts only after buffers are resident.

Elastic passthrough keeps both the native ring and the shadow ring. Entering snooping briefly unmaps the ring, copies it to the shadow ring in about 10 us, and atomically remaps the IOMMU to the shadow copy. Leaving snooping is triggered by an IOPS monitor, 100k IOPS in production. The host prefetches needed pages while snooping continues, then remaps back to the native ring. Orthus live upgrade lets the authors roll this out to legacy VMs.

Lockpage cuts repeat faults. VIO tracks I/O page accesses with a 2 MB bitmap plus active/inactive lists inspired by Linux LRU, pinning pages likely to be reused. The paper also uses a static lockpage policy for the VirtIO RX queue because its contiguous buffers make pinning cheap.

## Evaluation

Once fault handling leaves the device path, both throughput collapse and jitter mostly disappear. On a production-like platform inside a large CSP, average IOPA-Snoop overhead is about 4 us. Lockpage hits cost about 3.5 us, misses about 4.5 us, and a true page fault averages 700 us. That makes snooping affordable for low-IOPS VMs but too expensive to leave on indefinitely for hot ones.

Against VPRI, under injected faults with 10 ms latency, VPRI loses about 60% throughput in Redis, 45% in Nginx, and 57% in Memcached because device-side faults trigger drops and retransmissions. VIO keeps loss below 10% by resolving faults before DMA. In the iperf jitter test, VPRI bandwidth repeatedly collapses toward zero, while VIO stays near 10 Gbps.

In a one-hour Redis YCSB run at 30% memory oversubscription, the system sees 1,464,225 unique page accesses and only one IOPF. Daily counts show 37 I/O-side faults versus 7,474 CPU page faults, below 1%. The ablation explains the mode split: lockpage improves snooping throughput by 3.4%, and full passthrough is still 11.1% faster than snooping at high IOPS. Application benchmarks hold VIO in snooping mode even where production would switch, so dynamic switching is validated mostly through ablation and deployment evidence.

## Novelty & Impact

Compared with _Guo et al. (SOSP '24)_, VIO does not accelerate PRI; it removes PRI from the critical path. Compared with guest-cooperative systems such as _Amit et al. (USENIX ATC '11)_ and _Tian et al. (USENIX ATC '20)_, it requires no guest modification, which suits clouds full of legacy VMs.

The impact is operational rather than conceptual. VIO is a deployable hypervisor technique for reclaiming memory from passthrough VMs before universal PRI support arrives. The year-long deployment across 300K VMs makes that claim credible.

## Limitations

VIO still assumes VirtIO in the guest and a backend or DPU that can support VirtIO offload, so it is not a universal fix for all passthrough stacks. It also relies on infrastructure control over EPT and IOMMU mappings.

Some decisions remain pragmatic. Production uses static rather than adaptive lockpage, Windows VirtIO behavior drives the p99 lockpage rate to 79%, and the 100k-IOPS switch threshold is tuned.

## Related Work

- _Amit et al. (USENIX ATC '11)_ — vIOMMU uses para-virtual cooperation between guest and hypervisor to support dynamic DMA pinning, whereas VIO avoids guest changes and intercepts VirtIO queue progress entirely on the host.
- _Tian et al. (USENIX ATC '20)_ — coIOMMU also tackles direct-I/O memory management in software, but it still relies on cooperative tracking and the paper's own ablation shows it well below VIO at high IOPS.
- _Guo et al. (SOSP '24)_ — VPRI accelerates PRI-style page faults in hardware, while VIO removes device-side page-fault handling from the critical path instead of optimizing it.
- _Dong and Mi (Internetware '24)_ — IOGuard dedicates a CPU core to software IOPF handling, whereas VIO uses VirtIO snooping plus lockpage to keep host overhead low without guest modification.

## My Notes

<!-- empty; left for the human reader -->

---
title: "FastIOV: Fast Startup of Passthrough Network I/O Virtualization for Secure Containers"
oneline: "FastIOV makes SR-IOV practical for secure containers by parallelizing VFIO opens, skipping useless image mappings, lazily zeroing DMA pages, and hiding guest driver init."
authors:
  - "Yunzhuo Liu"
  - "Junchen Guo"
  - "Bo Jiang"
  - "Yang Song"
  - "Pengyu Zhang"
  - "Rong Wen"
  - "Biao Lyu"
  - "Shunmin Zhu"
  - "Xinbing Wang"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Alibaba Cloud"
  - "Zhejiang University"
  - "Hangzhou Feitian Cloud"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696066"
code_url: "https://github.com/AlibabaResearch/fastiov-eurosys25"
tags:
  - networking
  - virtualization
  - isolation
  - serverless
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

FastIOV argues that SR-IOV is already good enough for secure-container datapaths; the real problem is the control path that attaches a VF to a microVM-backed container at scale. By decomposing VFIO locking, skipping image-memory mappings, lazily zeroing RAM pages via EPT-fault interception, and overlapping guest NIC bring-up with app launch, it cuts VF-related startup overhead by 96.1% and average / p99 startup time by 65.7% / 75.4%.

## Problem

SR-IOV looks ideal for containers, but secure containers such as Kata, Firecracker, and RunD run inside microVMs. Instead of simply moving a pre-created host interface into a namespace, the system must register the VF through VFIO, build IOMMU DMA mappings, and wait for a guest NIC driver to bring the device up.

At 200 concurrent starts, that extra machinery adds 12.2 seconds and inflates average startup time by 305% relative to a no-network baseline. VFIO devset opening alone is 48.1% of average startup time and 59.0% at p99; DMA mapping of RAM and image memory adds 13.0% and 5.6%; guest driver initialization adds 3.4%. The bottleneck is therefore passthrough control-path work, which is exactly what hurts serverless cold starts.

## Key Insight

The key insight is that secure-container SR-IOV startup is not a single device-setup cost. It is three distinct bottlenecks with different causes: unnecessary serialization in VFIO devset management, overly eager work in DMA mapping, and guest-driver initialization exposed on the critical path. Because those causes are different, the fixes can be local: parallelize independent VF opens, skip memory that will never see DMA, defer page zeroing until first guest touch, and overlap NIC bring-up with the rest of container launch.

## Design

FastIOV combines four optimizations. It replaces the single devset mutex with a parent `rwlock` plus one mutex per VFIO device, so different VF opens can proceed in parallel while global-state updates still serialize. It also hides guest VF-driver initialization: the runtime launches the container while a guest agent brings up the NIC in parallel and only gates actual network use on readiness.

On the DMA side, FastIOV skips mappings for microVM image memory because that region is read-only and never used for DMA. For guest RAM it decouples zeroing from allocation. A kernel module, `fastiovd`, tracks uncleared pages, and KVM calls it on the first-touch EPT fault: FastIOV zeroes the host page, then KVM installs the EPT entry. BIOS and kernel pages written before guest launch go to an eager-zero whitelist, and `virtioFS` buffers trigger proactive EPT faults so host-written data is not wiped later. The implementation also removes a Kata-specific rebinding inefficiency by using dummy host interfaces so VFs stay bound to VFIO.

## Evaluation

On dual-socket Intel Xeon Gold 6348 servers with 256 GB RAM and a 25 GbE Intel E810 NIC, using Kata-QEMU microVMs sized at 0.5 vCPU and 512 MB with 2 MB hugepages, FastIOV cuts VF-related startup time by 96.1% versus a repaired vanilla SR-IOV CNI baseline. End-to-end average startup falls 65.7% and p99 75.4%, bringing the system to 39.1% above the no-network lower bound on average and 11.6% at p99.

The gains hold across regimes. Startup time falls 46.7%-65.6% from concurrency 10 to 200, and at 2 GB per container vanilla startup grows 60.5% while FastIOV rises 21.5%. Even Pre100 is 56.4% slower on average, and memory throughput and latency stay within 1% of vanilla. On four SeBS-style serverless workloads, average task completion drops 12.1%-53.5% and p99 20.3%-53.7%.

## Novelty & Impact

FastIOV's novelty is not a new dataplane but an end-to-end decomposition of secure-container SR-IOV cold start. It shows that the worst delays come from serial control-path structure across the CNI, VFIO, KVM, IOMMU setup, and guest driver lifecycle, not from SR-IOV hardware itself. Unlike _Zhang et al. (EuroSys '24)_ on HD-IOV, it targets concurrent VF attach latency rather than density and flexibility; unlike _Tian et al. (ATC '20)_ on coIOMMU, it does not depend on delayed DMA mapping for overcommitment and instead identifies eager page zeroing as the actual startup culprit. That framing should be useful to secure-container CNIs and serverless platforms.

## Limitations

FastIOV is invasive. It modifies VFIO, KVM, QEMU, Kata runtime, guest agents, and `virtioFS`, so it is realistic only when the cloud operator controls most of the stack. It also assumes device drivers can cooperate with the lazy-zeroing safety condition; for other SR-IOV devices, especially closed-source ones, that may require something like vDPA.

The evaluation is intentionally narrow. The paper assumes hugepages, focuses on startup rather than steady-state networking, and tests a limited device set. It is best read as a cold-start optimization study, not a full alternative networking stack.

## Related Work

- _Agache et al. (NSDI '20)_ - Firecracker cuts general microVM startup cost, while FastIOV targets the remaining passthrough-networking path.
- _Li et al. (ATC '22)_ - RunD improves secure-container startup, but not SR-IOV-specific VF attachment costs.
- _Tian et al. (ATC '20)_ - coIOMMU delays DMA mappings for overcommitment; FastIOV attacks eager page zeroing on the startup path.
- _Zhang et al. (EuroSys '24)_ - HD-IOV improves SR-IOV scalability and flexibility, while FastIOV focuses on concurrent VF attach latency.

## My Notes

<!-- empty; left for the human reader -->

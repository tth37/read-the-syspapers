---
title: "HyperAlloc: Efficient VM Memory De/Inflation via Hypervisor-Shared Page-Frame Allocators"
oneline: "HyperAlloc lets the hypervisor write the guest page allocator directly, reclaiming 2 MiB VM memory DMA-safely and far faster than ballooning or hotplug."
authors:
  - "Lars Wrenger"
  - "Kenny Albes"
  - "Marco Wurps"
  - "Christian Dietrich"
  - "Daniel Lohmann"
affiliations:
  - "Leibniz Universität Hannover"
  - "Technische Universität Braunschweig"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717484"
code_url: "https://github.com/luhsra/hyperalloc-bench"
tags:
  - virtualization
  - memory
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HyperAlloc shares the guest page-frame allocator with the hypervisor, letting it reclaim 2 MiB VM frames by editing allocator metadata instead of talking through a balloon driver. Reclaimed pages are reinstalled through an explicit allocate-time hypercall, so DMA safety is preserved. On Linux/QEMU, the paper reports 344.8 GiB/s shrink speed, up to 362x faster than virtio-balloon and 10x faster than virtio-mem, plus a 17 percent lower Clang memory footprint under automatic reclamation than virtio-balloon.

## Problem

VM memory demand is bursty, but reclaiming memory from live guests is still too awkward for fine-grained billing or aggressive overcommitment. That leaves DRAM stranded during low-demand phases even though prior work shows many VMs could be deflated substantially most of the time.

Existing cooperative mechanisms each fail one of the needed constraints. Virtio-balloon supports automatic reclaim, but it works through an in-guest driver, 4 KiB granularity, and fault-based repopulation; that makes it chatty and incompatible with passthrough devices that cannot trigger I/O faults. Virtio-mem is DMA-safe and uses 2 MiB blocks, but it prepopulates memory on growth and lacks automatic reclamation. VProbe is closer, yet still infers allocations indirectly from `struct page` side effects. The paper's target is the combination prior work does not offer cleanly: fast de/inflation, automatic elasticity, and DMA safety in one mechanism.

## Key Insight

The hypervisor should participate in the guest allocator's state directly rather than steer it from the outside. HyperAlloc shares LLFree's compact, lock-free metadata between guest and hypervisor, so reclaim becomes a state update plus unmapping instead of a proxy-driver protocol or a trap on allocator side effects. DMA safety then becomes explicit: reclaimed pages are marked unavailable until the guest issues an install hypercall that remaps and pins backing memory before use. The paper's broader claim is that allocator co-design, not just larger reclaim granularity, is what makes fast and safe VM elasticity possible.

## Design

HyperAlloc builds on LLFree, a lock-free Linux page-frame allocator, and extends it into a bilateral host/guest allocator. The hypervisor gets shared-memory access to LLFree metadata inside the guest and operates at 2 MiB huge-page granularity to cut reclaim overhead.

Each frame has a host state `(M, R)` and a guest-visible state `(E, A)`: whether backing memory is mapped, whether the frame is installed or reclaimed, whether the guest sees it as evicted, and whether the guest has allocated it. Hard reclamation sets `A=1` and `E=1`, unmaps the frame from EPT and IOMMU tables, and prevents repopulation on demand; soft reclamation keeps the frame logically allocatable but currently unbacked. Returning memory converts hard-reclaimed pages back to soft-reclaimed ones. If the guest later allocates an evicted page, it issues an explicit install hypercall that remaps and pins memory before CPU or device access, which is the key DMA-safety move.

Automatic reclaim runs every 5 seconds by scanning dense, pointer-free metadata for installed but unallocated huge pages. HyperAlloc also modifies LLFree's reservation policy to reduce huge-page fragmentation, which directly improves reclaimability. The prototype lives in user-space QEMU rather than KVM, so install operations still pay one extra context switch and use calls such as `madvise(DONT_NEED)` and VFIO interfaces to manipulate mappings.

## Evaluation

Experiments run on a dual-socket Xeon host with Debian 12, Linux 6.1, and QEMU/KVM 8.2.50. The main baselines are virtio-balloon, huge-page ballooning, and virtio-mem, with and without VFIO where relevant. The main missing comparison is VProbe, which the authors discuss but could not obtain in runnable form.

On the microbenchmarks, HyperAlloc is strongest where the design predicts. Reclaiming 19 GiB of touched memory reaches 344.8 GiB/s, versus 0.95 GiB/s for virtio-balloon and about 34 GiB/s for virtio-mem. Reclaiming already-unmapped memory reaches 4.92 TiB/s because HyperAlloc mostly edits allocator metadata and skips unmap work. Return-plus-install lands around 4 GiB/s, close to virtio-mem and slightly below huge-page ballooning because the QEMU prototype pays an extra context switch during install.

The more important result is that live resizing barely perturbs the guest. Under a 12-thread STREAM run, HyperAlloc's first-percentile bandwidth is 70.1 GB/s, essentially at baseline, whereas virtio-balloon drops to 30.9 GB/s and virtio-mem to 31.9 GB/s during shrink. On a Clang 16 build inside a 16 GiB VM, HyperAlloc reduces memory footprint by 17 percent relative to virtio-balloon with no noticeable runtime cost; after page-cache drop it shrinks to 1.9 GiB versus 8 GiB for virtio-balloon. In a three-VM offset-peak experiment, aggregate peak demand drops to 28.11 GiB under HyperAlloc versus 35.98 GiB under virtio-balloon. That said, part of the elasticity gain comes from LLFree's lower fragmentation, so the paper evaluates a co-designed mechanism-plus-allocator stack rather than a narrowly isolated reclaim primitive.

## Novelty & Impact

The novelty is not merely larger reclaim granularity. HyperAlloc turns VM memory deflation into a shared-allocation problem: the hypervisor and guest operate on the same allocator state, but with limited visibility so safety is preserved. That is a different stance from virtio-balloon, virtio-mem, and VProbe, which all still influence the guest allocator indirectly. The likely impact is twofold: a concrete research example of allocator co-design across the virtualization boundary, and a plausible path toward finer-grained VM memory billing and higher consolidation in passthrough-heavy clouds.

## Limitations

HyperAlloc's biggest deployment cost is that it requires replacing the guest page allocator with LLFree. That is a much stronger assumption than loading a balloon or hotplug driver, and the paper explicitly notes that porting the idea to pointer-heavy, lock-based allocators is difficult and potentially unsafe.

Effectiveness is also tied to 2 MiB huge-page availability, so fragmentation and page-cache behavior directly shape how much memory can be reclaimed. The prototype remains in QEMU rather than KVM, cannot grow beyond the initial VM size without hotplug integration, and does not solve host-wide overcommit events. Finally, the most similar DMA-safe auto-deflation competitor, VProbe, is discussed but not measured.

## Related Work

- _Hu et al. (MEMSYS '18)_ - HUB raises ballooning granularity to huge pages and improves speed, but it still relies on fault-based repopulation and is not DMA-safe.
- _Hildenbrand and Schulz (VEE '21)_ - virtio-mem provides explicit 2 MiB hot(un)plug and DMA safety, but it lacks automatic reclamation and pays prepopulation costs on growth.
- _Wang et al. (USENIX ATC '23)_ - VProbe also exposes guest memory metadata to the hypervisor for DMA-safe auto deflation, but it tracks allocations indirectly through `struct page` side effects instead of sharing allocator state explicitly.
- _Wrenger et al. (USENIX ATC '23)_ - LLFree is the scalable, fragmentation-aware allocator substrate that HyperAlloc extends from guest-only allocation into bilateral host/guest memory management.

## My Notes

<!-- empty; left for the human reader -->

---
title: "ODRP: On-Demand Remote Paging with Programmable RDMA"
oneline: "ODRP turns chained RDMA work requests into a remote swap device, enabling 4 KB remote page allocation with ideal utilization and zero memory-node CPU on the swap path."
authors:
  - "Zixuan Wang"
  - "Xingda Wei"
  - "Jinyu Gu"
  - "Hongrui Xie"
  - "Rong Chen"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, SEIEE, Shanghai Jiao Tong University"
conference: nsdi-2025
category: memory-serverless-and-storage
code_url: "https://github.com/SJTU-IPADS/ODRP"
tags:
  - memory
  - rdma
  - disaggregation
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ODRP turns a commodity RNIC into a remote swap device by chaining native RDMA work requests. With client-assisted preprocessing on the CNode, it supports `4 KB` remote allocation, `100%` remote-memory utilization, and zero MNode CPU on the swap fast path, with `4.1%-14.2%` application overhead relative to one-sided static swapping.

## Problem

Swap-based memory disaggregation needs per-page allocation, free, translation, and isolation, not just remote reads and writes. RDMA makes one-sided page I/O cheap, but dynamic memory management still goes through slow CPU-driven registration: the paper reports about `80 us` for `4 KB` and `600 us` for `1 MB`. So prior systems pick between static slabs that waste memory and CPU-mediated dynamic or two-sided designs that overload weak MNodes.

## Key Insight

ODRP's claim is that the allocator can live on the RNIC if the RNIC only executes small fixed logic. The CNode precomputes TT addresses, remembers whether a slot is already mapped, and piggybacks queue-recycling metadata; the RNIC performs queue updates, TT writes, page movement, and completion signaling. Two small meta operators, modulo FAA and `EndianSwap`, fill the RDMA semantic gaps that would otherwise bloat the chains.

## Design

ODRP exposes a Linux `frontswap` backend on each CNode and pre-registers all MNode memory as one large MR. The MNode slices memory into `4 KB` pages managed by a FIFO free-page queue and keeps a per-CNode TT mapping swap addresses to page addresses.

The RNIC hosts four WR chains: `load`, `mapped store`, `unmapped store`, and `invalidate`. `unmapped store` is the key path: it FAA-dequeues a free page, endian-converts the fetched pointer, writes it into the TT entry, stores the incoming page, and signals completion. `invalidate` returns the page to the queue and clears the TT. ODRP reuses old WR chains by piggybacking updated WAIT/ENABLE indices and doorbell state from the client instead of posting fresh WRs from the MNode CPU. Heartbeats reclaim pages from crashed CNodes, and registration boundaries plus protection faults keep each CNode inside its own TT.

## Evaluation

The evaluation uses one shared MNode and up to eight CNodes, each with a `12`-core Xeon E5-2650, `128 GB` DRAM, and a `100 Gbps` ConnectX-5 RNIC; each CNode has `12 GB` of swap. Against one-sided static, one-sided dynamic with `1 MB` slabs, two-sided `4 KB`, and one-sided dynamic `4 KB`, ODRP achieves `100%` remote-memory utilization. One-sided static reaches only `58.3%`, and one-sided dynamic can fall to `55%` on Quicksort with `50%` local memory. ODRP uses zero measured MNode CPU on the data path, whereas one-sided dynamic and two-sided saturate the single MNode core.

Application results back the mechanism. Relative to one-sided static, ODRP adds `9.7%` on Quicksort, `14.2%` on Kmeans, `7.2%` on Memcached, and `4.1%` throughput loss on VoltDB. More than `60%` of swap requests are page loads, and those loads reach `92.1%` of native one-sided throughput at high I/O depth with `5.5 us` latency versus `2.9 us` for raw RDMA. At eight CNodes, ODRP sustains `87.3%` of one-sided-static swap throughput with `14.6%` execution-time overhead while tripling remote-memory utilization.

## Novelty & Impact

Compared with `Fastswap`, ODRP moves page-granularity allocation and free into RNIC-side logic instead of relying on coarse slabs or CPU-assisted allocation. Compared with `RedN`, it turns RNIC programmability from a proof of possibility into a concrete systems recipe: client-assisted decomposition, small meta operators, and CPU-free WR recycling. The broader lesson is that RNIC offload can host a small stateful service, which matters beyond swap.

## Limitations

ODRP depends on specific Mellanox/NVIDIA features: enhanced atomics, scatter-gather lists, and mutable WAIT/ENABLE metadata. It is also not zero-CPU in every case: empty-queue recovery, crashed-CNode reclamation, and lazy budget monitoring still use MNode software. The evaluation covers only a single-MNode Linux `4.15` / ConnectX-5 cluster, so multi-MNode and non-swap settings remain open.

## Related Work

- _Amaro et al. (EuroSys '20)_ - _Fastswap_ made Linux frontswap-based far memory fast, and ODRP can be read as replacing its coarse or CPU-assisted remote allocator with page-granularity RNIC offload.
- _Reda et al. (NSDI '22)_ - _RedN_ established the programmability of chained RDMA WRs in theory; ODRP demonstrates how to package that power into a complete remote-memory service.
- _Qiao et al. (NSDI '23)_ - _Canvas_ improves remote swapping with isolation and adaptive asynchrony on the CNode side, whereas ODRP changes the remote device itself so allocation can remain fine-grained without CPU mediation.

## My Notes

<!-- empty; left for the human reader -->

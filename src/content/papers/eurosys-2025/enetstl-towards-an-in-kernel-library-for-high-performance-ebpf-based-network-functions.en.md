---
title: "eNetSTL: Towards an In-kernel Library for High-Performance eBPF-based Network Functions"
oneline: "eNetSTL factors common slow paths across 35 eBPF network functions into a small in-kernel library, restoring missing functionality and improving throughput by up to 1.8x."
authors:
  - "Bin Yang"
  - "Dian Shen"
  - "Junxue Zhang"
  - "Hanlin Yang"
  - "Lunqi Zhao"
  - "Beilun Wang"
  - "Guyue Liu"
  - "Kai Chen"
affiliations:
  - "Southeast University"
  - "Hong Kong University of Science and Technology"
  - "Peking Univeristy"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696094"
code_url: "https://github.com/chonepieceyb/eNetSTL"
tags:
  - networking
  - ebpf
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

eNetSTL argues that many eBPF network functions fail for the same small set of reasons, so the right fix is a reusable in-kernel library rather than per-function kernel modules or a redesigned ISA. It packages one memory wrapper, three algorithms, and two data structures behind kfunc/kptr interfaces, making some impossible eBPF NFs implementable and speeding the rest up by 14.6%-75.4% over pure eBPF while staying within 3.42% of kernel implementations on average.

## Problem

The paper starts from a practical survey: the authors re-implement the core operations of 35 network functions across seven categories using eBPF. Three are not implementable at all, mainly because eBPF cannot safely persist a variable number of dynamically allocated objects for non-contiguous structures such as skip lists or custom queues. Of the rest, 28 lose 14.8%-49.2% versus in-kernel code because eBPF lacks SIMD and bit-manipulation instructions, couples linked lists to spin locks, and pays too much for helpers such as `bpf_get_prandom_u32`. The obvious fixes are both unattractive: extending the ISA and verifier is intrusive, while shipping one kernel module per NF variant defeats eBPF's maintainability story.

## Key Insight

These 35 designs are more similar than they first appear. Across key-value lookup, membership tests, sketches, counting, load balancing, and queueing, the authors identify six shared performance-critical behaviors: bit operations, multiple hashes, basic data structures, random updates, non-contiguous memory, and multi-bucket operations on contiguous memory. Once those behaviors become the unit of abstraction, eNetSTL can stay small and stable: it exports only the few higher-level primitives that real NFs repeatedly need, instead of exposing a general kernel-programming substrate to eBPF.

## Design

eNetSTL has three main mechanisms. First, for non-contiguous memory, it introduces a proxy-managed memory wrapper: allocated objects hand ownership to a proxy persisted in a BPF map, while `node_connect` and `get_next` maintain pointer-like relationships. Safety comes from lazy checking. Instead of validating every traversal, eNetSTL records relationships on connection and rewrites incoming edges to `NULL` when a node is released, preventing use-after-free without taxing the hot path.

Second, for speed, it deliberately exports high-level interfaces whenever low-level wrappers would force extra copies across the eBPF/kernel boundary. Bit operations such as `ffs` and `popcnt` are exposed directly, but SIMD is wrapped as whole algorithms like `find_simd` and `reduce_simd`, and multi-hash routines are fused with their post-processing in `hash_simd_cnt`, `hash_simd_bit`, and `hash_simd_comp`. Two tuned data structures, `list-buckets` and `random_pool`, handle linked-list-heavy queues and randomized updates without repeated map lookups or helper calls. The implementation uses Rust, `rust-no-panic`, reference counting, and verifier-visible kfunc metadata such as `KF_ALLOC` and `KF_RELEASE` to keep API use disciplined from the eBPF side.

## Evaluation

The evaluation runs on two back-to-back servers with Intel XL710 40 Gbps NICs, dual Xeon E5-2630 v4 CPUs, Linux 6.6, and XDP in native mode; traffic is replayed with `pktgen` over DPDK 22.11 and pinned to one RX queue for single-core measurements. The paper studies 11 representative NFs in depth, comparing pure eBPF, kernel implementations, and eNetSTL.

The strongest functionality result is NFD-HCS's skip-list-based key-value query, which native eBPF could not implement. eNetSTL enables it and stays within 7.33% of kernel throughput on lookup and 8.54% on update/delete. For already-implementable but slow NFs, the gains are broad: Count-min sketch is 47.9% faster than eBPF on average and up to 70.9% faster at 8 hash functions, Carousel queueing improves by 38.4%, Cuckoo Switch by 27.4% on average and 33.08% at full load, Eiffel by 14.6% on average and 20.9% at bitmap level 4, and Nitro Sketch by 75.4%. Just as important, eNetSTL stays close to handwritten kernel code: 3.42% average gap overall and 5.24% worst case. Abstraction choice matters: individual algorithms and data structures improve operation time by 52.0%-513%, while the rejected low-level interfaces would be 59.0%-73.1% slower. End-to-end latency does not materially increase, and integrating eNetSTL into real projects improves throughput by 21.6% on average.

## Novelty & Impact

The novelty is not kfuncs themselves, but the library boundary the authors choose. eNetSTL turns a scattered set of NF-specific bottlenecks into a compact standard library for the eBPF dataplane and shows that the right abstraction level is above raw instructions but below full custom modules. That should matter to people building eBPF dataplanes, NF frameworks, and kernel-side packet-processing accelerators.

## Limitations

The authors are explicit that Rust does not eliminate all risk here. eNetSTL still contains `unsafe` Rust for raw-pointer interop and low-level instructions, so manual review remains part of the safety story, and the current toolchain cannot prove arbitrary unbounded loops terminate safely. The library also covers only the six shared behaviors extracted from the 35 surveyed designs, so an NF with a different bottleneck may not benefit. Finally, the evaluation is strong for XDP-style packet processing on one testbed, but it does not show multi-core scaling or how much of the gap would remain if future eBPF revisions add more of the same primitives directly.

## Related Work

- _Jia et al. (HotOS '23)_ - argues that verifier-centric kernel extension safety is untenable; eNetSTL takes a narrower path by using Rust and verifier metadata without replacing the existing eBPF model.
- _Kuo et al. (EuroSys '22)_ - KFuse reduces tail-call overhead by merging verified eBPF programs, whereas eNetSTL targets the cost of missing dataplane primitives inside a single NF.
- _Miano et al. (ASPLOS '22)_ - Morpheus specializes hot paths in eBPF-based data planes, while eNetSTL supplies reusable in-kernel building blocks for operations that are hard to express efficiently in eBPF at all.
- _Bonola et al. (ATC '22)_ - accelerates eBPF packet processing with FPGA NIC offload, while eNetSTL stays on the host CPU and improves the software abstraction boundary instead.

## My Notes

<!-- empty; left for the human reader -->

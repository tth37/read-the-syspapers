---
title: "Efficient Remote Memory Ordering for Non-Coherent Interconnects"
oneline: "Moves remote ordering into PCIe and the Root Complex, using acquire/release semantics plus an RLSQ so MMIO transmit and ordered RDMA reads avoid source-side stalls."
authors:
  - "Wei Siew Liew"
  - "Md Ashfaqur Rahaman"
  - "Adarsh Patil"
  - "Ryan Stutsman"
  - "Vijay Nagarajan"
affiliations:
  - "University of Utah, Salt Lake City, Utah, USA"
  - "Arm, Cambridge, UK"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790156"
code_url: "https://github.com/icsa-caps/efficient-remote-memory-ordering.git"
tags:
  - hardware
  - networking
  - rdma
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

The paper argues that non-coherent interconnects are not slow because PCIe bandwidth is too low, but because ordering is enforced in the wrong place. Its fix is to carry acquire/release intent through PCIe and enforce it in Root Complex hardware, which lets a CPU reach line-rate MMIO transmit without fences and lets ordered RDMA reads approach unordered performance.

## Problem

The target problem is fine-grained ordering across non-coherent CPU-device communication. Real software needs these orderings all the time: a CPU transmitting packets to a NIC must preserve write order, and an RDMA NIC doing a key-value lookup must often read a lock or version before reading the object itself. PCIe, however, only gives part of what software wants. Posted writes preserve `W->W`, but reads do not preserve `R->R`, and MMIO ordering on the CPU side is typically enforced with store fences that serialize the source core.

That mismatch is costly in two different ways. On the DMA side, ordered remote reads become stop-and-wait: the NIC must issue one read, wait for the full round-trip completion, then issue the dependent read. The paper measures about `300 ns` of extra latency per dependent DMA read on ConnectX-6 Dx, and shows that this caps ordered 64 B RDMA READ throughput at only about `5.0 Mop/s` (`2.37 Gb/s`) on one queue pair. On the MMIO side, the interconnect itself could pipeline writes efficiently, but the CPU must execute an `sfence` after each ordered packet-sized write to flush the write-combining buffer in program order. That destroys throughput: even with `512 B` packets, ordering cuts measured MMIO throughput by `89.5%`.

The broader consequence is that software stops using the obvious protocols. Packet transmit paths fall back to doorbells plus DMA fetches instead of direct MMIO, and one-sided RDMA key-value stores resort to validation passes or per-cache-line metadata because they cannot trust the interconnect to preserve a simple "check, then read" sequence. The paper's claim is that this complexity is largely compensation for missing architectural ordering support rather than an inherent property of fast I/O.

## Key Insight

The remembered proposition is that remote ordering should be an explicit end-to-end semantic, not an accident of source-side stalls. If software can mark a request as an acquire or a release, then the source no longer needs to serialize itself just to create a visibility edge. It can pipeline requests aggressively and let hardware near the destination enforce the relevant dependency.

That shift matters because it changes where the unavoidable serialization lives. In today's design, the source pays a full interconnect-plus-memory round trip, roughly `500 ns` in the paper's model, every time it must preserve order. In the proposed design, the Root Complex becomes the ordering point, so the bottleneck is instead the local sequencing cost of host-memory accesses, roughly `100 ns`, and then even that residual stall can be reduced with speculation. The paper is therefore not just adding new fence bits; it is relocating the serialization point to where latency is much lower and parallelism is easier to recover.

## Design

The design has three layers: PCIe semantics, host-ISA support, and Root Complex microarchitecture.

At the PCIe layer, the paper adds acquire/release-style remote ordering. Reads gain an acquire bit, while writes reuse the existing relaxed-ordering encoding to distinguish release writes from ordinary unordered writes. This is more precise than a crude "strong versus weak" split. A producer-consumer pattern such as "read flag, then read object" can be expressed as one acquire read followed by relaxed reads, so only the dependency that matters is enforced.

At the CPU interface, the authors argue that remote MMIO operations should become first-class ISA operations. They sketch `MMIO-Store`, `MMIO-Release`, `MMIO-Load`, and `MMIO-Acquire`, and they also explain a pragmatic transitional interpretation for RISC-V-style fences: instead of forcing the core to drain prior MMIOs, the fence can inject ordering metadata into the outbound stream. For MMIO writes, each thread's operations carry sequence numbers, and a reorder buffer at the Root Complex reconstructs program order before forwarding writes to the device. That preserves `W->W` semantics without the source-side stall that makes direct MMIO unattractive today.

The most interesting piece is the new Remote Load-Store Queue (`RLSQ`) at the Root Complex. In the simple version, relaxed DMA requests issue concurrently, an acquire blocks later same-thread requests until it completes, and a release waits until earlier same-thread requests are done before issuing. To avoid false dependencies across unrelated queue pairs or thread contexts, PCIe packets also carry a thread ID, and ordering is enforced per thread rather than globally.

The optimized `RLSQ` then borrows a CPU idea: out-of-order execution with in-order commitment. For an `Acquire->Read` sequence, it can speculatively issue both host-memory accesses in parallel, buffer the later read, and only respond once the acquire has resolved. Correctness comes from coherence integration, not from inventing a new coherence protocol. The `RLSQ` is treated as another coherent agent, snoops invalidations, and squashes only the conflicting speculative read if a host write intervenes. The same idea overlaps coherence work for `Write->Release` pairs. The paper also discusses peer-to-peer traffic: if flows to different destinations share a queue, virtual output queues are needed to avoid head-of-line blocking.

## Evaluation

The evaluation combines real-NIC measurements with gem5 simulation, and the numbers line up with the paper's story. On ConnectX-6 Dx, an RDMA WRITE submitted entirely through MMIO completes in a median `2,941 ns`; adding one DMA read raises that to `3,234 ns`, while two ordered DMAs raise it to `3,613 ns`. That is the empirical basis for the paper's claim that ordered remote reads suffer an extra `~300 ns` stop-and-wait cost per dependency. The MMIO experiment is similarly direct: unordered write-combined stores reach `122 Gb/s`, but inserting `sfence` to preserve ordering collapses throughput for small packets and still loses `89.5%` at `512 B`.

The simulation results then show what the proposed hardware would buy. For ordered DMA reads, speculative `RC-opt` reaches essentially the same bandwidth as unordered reads across object sizes, while source-side NIC ordering falls far behind. In the key-value-store benchmark, simply moving ordering from the NIC to the Root Complex improves single-QP get throughput by `29.1x`, and speculative `RC-opt` improves it by `50.9x` for `64 B` objects. Under more concurrency and larger batches, `RC-opt` is the only correct ordered design that comes close to saturating a `100 Gb/s` link.

The real-hardware emulation is also telling. Because the proposed ordered design should match today's unordered hardware in read-only, no-conflict cases, the authors use existing ConnectX-6 Dx NICs as a proxy for best-case ordered-read performance. In that setup, their `Single Read` key-value protocol, which becomes safe only with ordered reads, outperforms FaRM by `1.6x` for `64 B` objects while using a simpler on-wire layout than FaRM's per-cache-line version metadata. Finally, the hardware cost is modest: CACTI estimates put the added `RLSQ` plus reorder buffer below `0.9%` area and below `0.6%` static power of the referenced I/O hub. The main caveat is that the architectural claims are still primarily simulation-backed; the paper validates the model carefully, but it does not build a full ordered Root Complex prototype.

## Novelty & Impact

Relative to _Liew et al. (HotOS '25)_, the novelty is not just the claim that direct MMIO can beat doorbells plus DMA if fences disappear. This paper turns that observation into a full end-to-end interface, spanning PCIe semantics, host ISA, Root Complex queues, and application protocols. Relative to _Schuh et al. (ASPLOS '24)_, it argues that explicit ordering on a non-coherent fabric can recover much of the benefit that coherent CPU-NIC interfaces seek, without paying coherence's protocol complexity. Relative to _Yu et al. (ISCA '25)_, it focuses on non-coherent host-device I/O and adds a concrete acquire/release contract for both reads and writes.

That makes the paper useful to several communities at once: interconnect architects, NIC designers, ISA designers considering better MMIO abstractions, and RDMA-system builders who currently pay a software tax for unordered reads. The contribution is a new mechanism and a new architectural framing, not a production deployment study.

## Limitations

The design asks for coordinated changes across the PCIe specification, host ISA support, Root Complex microarchitecture, and endpoint behavior, so deployment is clearly not incremental. Many of the strongest claims, especially around speculative ordered reads, are backed by simulation and by emulation on today's unordered hardware rather than by a fabricated prototype of the full design.

The application coverage is also selective. The paper makes an excellent case for CPU-NIC transmit paths and read-heavy RDMA key-value gets, but it is less of a broad software study of full network stacks or general accelerator communication. Some corner cases still fall back to source-side ordering: if the same process must order reads across different destination devices, the paper explicitly says the source NIC should serialize them. Multi-destination topologies also need virtual output queues to avoid head-of-line blocking. So the idea is strong, but its cleanest wins appear in the specific producer-consumer patterns the paper targets.

## Related Work

- _Schuh et al. (ASPLOS '24)_ — CC-NIC uses coherence to give the NIC a faster host interface, whereas this paper argues that explicit ordering on non-coherent PCIe can recover much of the same benefit more simply.
- _Liew et al. (HotOS '25)_ — shows that CPU-to-NIC MMIO is attractive once fence costs disappear; this paper generalizes that point into a complete remote-ordering interface and enforcement mechanism.
- _Yu et al. (ISCA '25)_ — CORD adds directory-based ordering for heterogeneous release consistency, while this paper centers on acquire/release ordering for non-coherent host-device interconnects and RDMA-style communication.
- _Jasny et al. (TODS '25)_ — documents how today's unordered RDMA reads force complicated synchronization protocols for disaggregated data structures; this paper provides hardware ordering that directly simplifies those protocols.

## My Notes

<!-- empty; left for the human reader -->

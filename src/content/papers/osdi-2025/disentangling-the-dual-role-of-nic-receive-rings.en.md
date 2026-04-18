---
title: "Disentangling the Dual Role of NIC Receive Rings"
oneline: "rxBisect splits the NIC Rx ring into small allocation rings and large reception rings, preserving burst absorption while shrinking the DDIO working set."
authors:
  - "Boris Pismenny"
  - "Adam Morrison"
  - "Dan Tsafrir"
affiliations:
  - "EPFL"
  - "NVIDIA"
  - "Tel Aviv University"
  - "Technion – Israel Institute of Technology"
conference: osdi-2025
tags:
  - networking
  - smartnic
  - memory
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

The paper argues that a NIC receive ring is doing two different jobs at once: holding empty buffers for allocation and delivering full buffers to software. rxBisect separates those jobs into small allocation rings (Ax) and large bisected reception rings (Bx), so the system keeps burst tolerance without forcing every core to pin a full 1 Ki worth of receive buffers in the DDIO working set. In software-emulated experiments, that redesign improves throughput by up to 37% over private per-core rings and up to 20% over an idealized dynamic shRing baseline under imbalanced load.

## Problem

The paper starts from a cache-capacity problem that appears once fast NICs meet multicore packet processing. Modern 100 Gbps and faster NICs distribute traffic across per-core receive rings so software can process packets in parallel. Each ring is prepopulated with MTU-sized buffers, typically 1,024 entries by default. That means the receive-side I/O working set is at least `N x R x 1500 B`, where `N` is the number of rings and `R` is the ring size. On a many-core machine, the combined footprint easily exceeds the last-level cache and even the subset of LLC ways exposed to DDIO. Once that happens, freshly DMAed packets evict packets that software has not processed yet, turning packet access into a main-memory problem and pushing the memory subsystem onto the critical path.

The obvious fix is to reduce the amount of receive-buffer state per core, but existing interfaces make that hard. Shrinking private rings lowers the working set, yet it also reduces the burst absorption each core gets, causing packet loss under realistic bursts. The prior shRing design attacks the same problem by sharing a large receive ring across multiple cores, but that creates a different coupling: the same shared structure now governs both who owns empty buffers and who has room to receive packets. shRing therefore pays synchronization overhead on the fast path, and it breaks down under persistent load imbalance because overloaded cores can monopolize the shared ring and starve underloaded ones. The paper uses a real CAIDA trace to show that such imbalance is not rare or pathological: the ratio between the busiest and least busy core remains between 325% and 433% in its example.

## Key Insight

The central claim is that the existing Rx interface is wrong at the abstraction boundary. A receive ring looks like one circular queue, but semantically it combines two orthogonal producer-consumer relationships: the core produces empty buffers that the NIC consumes, and the NIC produces full buffers that the core consumes. Those relationships need different capacities and different sharing policies. If they are disentangled, software can share the pool of empty buffers across cores without also sharing packet-reception capacity.

That proposition explains why prior designs hit a tradeoff that looked fundamental but is not. Burst absorption really requires a large reception structure, because incoming packets may briefly outrun software. Buffer provisioning does not require the same thing; it only needs enough empty buffers, across the application as a whole, to keep the NIC fed while software replenishes them. rxBisect exploits exactly that asymmetry: keep reception large, keep allocation small, and let the NIC move empty buffers across cores in hardware rather than asking software to synchronize on a shared receive ring.

## Design

rxBisect replaces each conventional Rx ring with two ring types. An allocation ring (Ax) contains descriptors for empty packet buffers that the NIC may consume. A bisected reception ring (Bx) contains notifications for software: pointers to received packets and notifications that a buffer from some Ax ring was consumed. A Bx ring can be associated with several Ax rings, and multiple Bx rings may share the same candidate Ax set, as long as they belong to the same software entity and NUMA node.

On packet arrival, the NIC first chooses a destination Bx ring exactly as it would choose a receive ring today, for example via RSS. It then finds an Ax ring with an available empty buffer, DMA-reads that buffer pointer, stores the packet into the buffer, and writes the delivery notification into the destination Bx ring. If the buffer came from another core's Ax ring, the NIC also notifies that allocating core so it can replenish its Ax entry. In the common case where the receiving and allocating core are the same, the paper piggybacks both facts into one Bx descriptor.

Software processing stays simple. Each core polls its Bx ring, collects packet pointers for actual work, and for any notification that one of its Ax buffers was consumed, allocates a fresh buffer and advances the Ax tail. The required allocator capability is only that one core may allocate a buffer and another core may free it later; the authors argue DPDK and the Linux kernel already support this style of two-level per-core-plus-shared-pool allocation.

The crucial engineering point is that rxBisect decouples size. The paper's recommended setup for 100 Gbps NICs is large 1 Ki Bx rings, to absorb bursts, and much smaller Ax rings, often 128 entries, to keep `k x |Ax| x 1500 B` within DDIO capacity while still ensuring `k x |Ax| >= |Bx|`. This gives the application a shared empty-buffer pool without a shared reception queue. The authors also argue that the NIC-side critical path is unchanged versus today's Rx-plus-completion-ring hardware: packet delivery still consists of reading a buffer address, writing packet data, and writing completion-style metadata. The main difference is that the NIC's ring-selection logic now chooses among Ax rings when the local one is empty, moving what shRing handled in software locks into NIC hardware.

## Evaluation

The prototype is not a real ASIC implementation. The authors emulate rxBisect in DPDK with a dedicated emulator core acting as the NIC and compare it against native privRing, small privRing, and shRing baselines on dual-socket Dell R640 servers with two pairs of 100 Gbps ConnectX-5 NICs. They first validate that emulation is conservative: compared with native execution, emulation reduces throughput by up to 12% and can increase latency by up to 94%, so wins from emulated rxBisect are not coming from a favorable measurement setup.

On balanced NAT and load-balancing network functions at 200 Gbps with 1500-byte packets, rxBisect sustains line rate while native privRing loses up to 20% throughput and suffers up to 11x higher latency because its large I/O working set overflows DDIO and then the LLC. The no-drop burst experiment makes the design logic even clearer: with four cores and a single 100 Gbps NIC, rxBisect reaches about 80 Gbps single-flow no-drop throughput with 256-entry Ax rings, whereas privRing needs 1 Ki receive rings to achieve the same burst tolerance. The difference is precisely the benefit of sharing empty buffers without sharing reception.

The paper also shows the benefit on a non-NF macrobenchmark. On the MICA key-value store, rxBisect improves throughput by up to 37% over emulated privRing, 7% over emulated shRing, and even 18% and 6% over their native privRing and shRing runs, respectively. Under imbalance, the contrast with shRing becomes sharper. When one target core's per-packet processing is inflated, shRing throughput drops by up to 60%; when the target core receives a higher fraction of traffic, shRing drops by up to 49%. rxBisect stays near line rate until the emulator itself becomes the bottleneck. On the real CAIDA trace co-located with PageRank, rxBisect outperforms the paper's idealized dynamic shRing baseline by 16% on load balancing and 20% on NAT. The evaluation supports the main claim well: rxBisect wins both when the bottleneck is LLC pressure and when shRing's shared queue becomes the bottleneck under skew.

## Novelty & Impact

Relative to _Pismenny et al. (OSDI '23)_, rxBisect is not just a better heuristic for shared receive rings; it changes the interface so that buffer sharing and packet reception are no longer tied to the same queue. Relative to _Fried et al. (NSDI '24)_, which uses Mellanox RMP-based sharing plus a dedicated monitoring core in Junction, rxBisect pushes the sharing logic into the NIC and keeps all cores available for useful work. Relative to _Sadok et al. (OSDI '23)_, which improves NIC-application communication with a streaming interface, rxBisect attacks a different layer of the bottleneck by shrinking the DMA working set rather than PCIe software overhead.

That makes the paper's likely impact fairly broad. Anyone building high-speed kernel-bypass runtimes, end-host packet-processing pipelines, or future NIC receive interfaces can reuse the paper's framing: the real problem is not "how big should a receive ring be?" but "why is one queue encoding two resource-allocation policies at once?" The mechanism is specific, but the abstraction lesson is the bigger contribution.

## Limitations

The main limitation is that rxBisect is evaluated through software emulation, not a hardware prototype. The authors make a credible case that the emulator is conservative and that the NIC-side critical path need not get longer, but they still do not demonstrate a shipping ASIC, real firmware, or interoperability with an existing production NIC. Any deployment claim therefore depends on the plausibility of their hardware argument rather than on an end-to-end implementation.

The design also assumes a supportive software substrate. Buffers may be allocated on one core and freed on another, so allocators must support cross-core handoff efficiently. The paper argues modern allocators do, and its measurements show allocator overhead below 0.2% of cycles, but that result is specific to the evaluated DPDK-style environment. Similarly, rxBisect can still consume extra buffers under heavy imbalance because overloaded cores may fill their Bx rings with buffers sourced from other cores; the paper notes that preallocated buffer pools must therefore be sized to tolerate such cases.

Finally, the evaluation scope is narrower than the abstraction might suggest. The prototype keeps the transmit side unchanged, focuses on kernel-bypass applications and MICA, and mostly evaluates same-node, same-NUMA buffer sharing. The paper does not study commodity socket stacks, multi-tenant isolation issues, or failure modes beyond packet drops and queue clogging. Those are reasonable omissions for an OSDI paper, but they leave real deployment questions open.

## Related Work

- _Pismenny et al. (OSDI '23)_ — shRing also shrinks the receive working set by sharing buffers, but it still ties buffer ownership and reception capacity to one shared ring, which is exactly the entanglement rxBisect removes.
- _Fried et al. (NSDI '24)_ — Junction shares receive buffers through Mellanox RMP and compensates for imbalance with work stealing and a helper core, whereas rxBisect lets the NIC perform cross-core buffer sharing directly.
- _Sadok et al. (OSDI '23)_ — Enso redesigns the NIC-application streaming path to reduce communication overhead, while rxBisect focuses on cache pressure from oversized receive-buffer working sets.
- _Farshin et al. (ATC '20)_ — Reexamining direct cache access characterizes how DDIO and leaky DMA hurt high-speed networking; rxBisect responds by changing the receive interface that creates that cache footprint.

## My Notes

<!-- empty; left for the human reader -->

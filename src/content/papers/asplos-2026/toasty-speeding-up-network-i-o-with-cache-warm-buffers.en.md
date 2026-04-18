---
title: "Toasty: Speeding Up Network I/O with Cache-Warm Buffers"
oneline: "Turns AF_XDP packet buffers into a cache-warm working set via LIFO reuse and adaptive RX-ring refill, preserving burst tolerance without smart NIC support."
authors:
  - "Preeti"
  - "Nitish Bhat"
  - "Ashwin Kumar"
  - "Mythili Vutukuru"
affiliations:
  - "Indian Institute of Technology, Bombay, Mumbai, India"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790235"
code_url: "https://github.com/networkedsystemsIITB/toasty"
tags:
  - networking
  - kernel
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Toasty targets a very specific bottleneck in AF_XDP-style packet I/O: DDIO helps only if recently received packet buffers still fit in cache when the application touches them again. It therefore combines LIFO reuse of freed buffers with a kernel policy that adaptively limits how many descriptors are kept live in the NIC RX ring. The result is near-ideal cache behavior in steady state, but without the packet drops that a permanently tiny buffer pool would cause during bursts.

## Problem

The paper starts from a tension that looks minor at first and turns out to dominate performance on modern NICs. Kernel-bypass frameworks such as AF_XDP and DPDK pre-allocate a large userspace pool of packet buffers, hand buffer descriptors to the NIC, and let the NIC DMA packets directly into those buffers. With Intel DDIO, those DMA writes land in the last-level cache instead of going straight to DRAM, so the application can often read the packet from cache. That benefit disappears when the active packet-buffer working set is larger than the DDIO portion of the LLC.

Two pathologies follow. First, leaky DMA: newly arriving packets evict older packets from cache before the application processes them, so the application falls back to DRAM anyway. Second, unnecessary writebacks: once the application has processed a buffer and returned it to the free pool, the dirty cachelines may still be evicted back to memory before the NIC reuses that buffer, even though the next DMA will overwrite the contents completely. Both effects waste the cache capacity that DDIO was supposed to exploit.

The obvious answer is to keep the packet-buffer pool small enough to fit in cache. The authors show that this does maximize throughput for several AF_XDP network functions under steady load. But it creates the opposite failure mode under realistic traffic variation. With microbursts or Poisson-distributed arrivals, the NIC can simply run out of free descriptors in the RX ring and start dropping packets. The systems problem is therefore not just "use fewer buffers," but "keep only a small warm working set in circulation when the load is smooth, then temporarily expand when bursts would otherwise starve the NIC."

## Key Insight

The paper's main claim is that software can approximate the behavior of an ideal cache-aware NIC interface without changing commodity hardware, as long as it controls both reuse order and circulation depth. Reuse order matters because the most recently processed buffers are the ones most likely still resident in LLC or even lower-level caches. Circulation depth matters because those warm buffers will not actually be reused quickly if the hardware RX ring stays packed with thousands of colder descriptors ahead of them.

That leads to Toasty's two-part proposition. First, make the free-buffer pool behave like a LIFO stack so the most recently recycled buffers return to service first. Second, do not keep the RX ring permanently full; instead, refill it according to observed packet arrival and recycling rates so that the number of in-flight buffers tracks current demand. Together, these choices preserve a small cache-warm working set in steady state, while still allowing the system to pull colder buffers into service when burst resilience matters more than cache locality.

## Design

Toasty is implemented on top of AF_XDP in busy-poll, zero-copy mode. The first change is in userspace. AF_XDP's fill queue normally behaves like a FIFO queue: the application returns free buffers at the producer tail, and the driver later consumes them from the consumer head after cycling through the whole pool. Toasty changes only the buffer-descriptor ordering, not the data itself. After the application recycles a batch of buffers, it atomically swaps those descriptors with the descriptors currently at the head of the fill queue. That effectively turns the free pool into a LIFO structure, so recently touched buffers are the next candidates for NIC DMA. In busy-poll mode the producer and consumer do not run concurrently, which lets Toasty avoid extra synchronization; the paper explicitly notes that interrupt mode would need stronger race protection and does not implement that path.

The second change is in the kernel driver. A LIFO free pool alone is not enough because the NIC RX ring is still FIFO. If the driver keeps thousands of descriptors posted at all times, the warm buffers moved to the front of the fill queue will still sit behind a long line of colder descriptors already resident in the ring. Toasty therefore adaptively decides how many buffers to place into the RX ring on each iteration. The policy uses three readily available counters: how many buffers the application recycled into the fill queue since the previous iteration, how many packets the NIC DMAed in the last iteration, and how many free buffers remain available in the RX ring. It then tries to maintain roughly `k * N_RXQ` buffers in the ring, with `k = 10` in the implementation.

The refill behavior splits by load. If the available-buffer count falls below the target and the recent traffic rate is high, Toasty refills aggressively to restore headroom, even if that means pulling colder buffers from deeper in the pool. If the load is below a 50% link-utilization threshold, Toasty refills mainly from the newly recycled warm region or skips refill entirely, allowing excess cold buffers already in circulation to drain out. The paper also adds a transmit-path tweak so transmitted packet descriptors are returned to the free pool sooner, which matters for forwarding-style workloads such as L2Fwd.

## Evaluation

The evaluation uses six AF_XDP applications with distinct access patterns: NAT, IDS, decryption, L2Fwd, MICA, and Maglev. The main server is an Intel Xeon Gold 5418Y with an Intel E810 100 GbE NIC, and the default baseline uses a large pool of 16,384 packet buffers with a 4,096-entry RX ring. The paper compares Toasty against that default and against an "ideal" per-application static configuration whose pool size is manually chosen to maximize throughput by fitting the working set into the DDIO-enabled cache region.

The core result is that Toasty recovers almost all of the cache benefit of the hand-tuned small-pool configuration without inheriting its fragility. Across the six applications, Toasty improves single-core saturation throughput by up to 78% over default AF_XDP, while producing near-zero LLC miss rates similar to the ideal configuration. Under co-located memory pressure generated by Intel MLC, the gains over default rise to 30-86%, which is strong evidence that the mechanism is really about cache residency rather than incidental scheduler effects.

The burst-handling results support the paper's central claim as well. With Poisson arrivals, Toasty achieves higher sustained throughput than both baselines because it avoids the ideal configuration's packet losses while still keeping a small warm working set most of the time. For the no-drop-rate metric, the relative ordering stays the same. Under the paper's microburst and Poisson workloads, Toasty keeps packet-drop percentages close to the large-pool default and far below the ideal small-pool setting. That is exactly the tradeoff the design set out to solve.

I found the comparison set thoughtful. The paper does not stop at the two obvious AF_XDP baselines; it also studies user-only LIFO buffer reuse, DPDK's stack mempool, ShRing, software prefetching, and ablations of the user-space and kernel-space pieces. Those experiments make the main argument more credible: LIFO reuse alone helps, but full gains require adaptive RX-ring refill too. The main weakness is scope. Most experiments are on one CPU family, one NIC family, and one AF_XDP operating mode, so the paper demonstrates a strong mechanism rather than universal deployment behavior.

## Novelty & Impact

Relative to _Tootoonchian et al. (NSDI '18)_, Toasty's novelty is that it rejects a fixed "fit the ring in cache" sizing rule and instead keeps a large configured pool while shrinking the live working set at runtime. Relative to DPDK's LIFO mempool, its key addition is recognizing that free-pool order is not enough if the hardware RX ring remains deeply queued. Relative to _Pismenny et al. (OSDI '23)_ and _Liu et al. (SIGCOMM '25)_, it occupies a different point in the design space: software-only control on commodity NICs instead of new smart-NIC capabilities or a redesigned NIC-CPU interface.

That makes the paper useful to two audiences. Practitioners can view it as an immediately deployable AF_XDP optimization for high-speed packet processing on existing servers. Researchers can view it as a clean demonstration that packet-buffer lifetime management is a first-class systems lever, not just a low-level implementation detail. The contribution is a new software mechanism, not a new workload or measurement study.

## Limitations

Toasty depends heavily on the DDIO/cache-residency story, so its gains are tied to platforms where inbound DMA placement and cache behavior look similar to the paper's Intel setup. The implementation is designed around AF_XDP busy-poll mode; the paper explicitly notes that interrupt mode would require extra synchronization to avoid races between producer and consumer operations. The driver policy also relies on heuristics, especially `k = 10` and the 50% link-utilization threshold, and while the sensitivity study suggests a reasonable stability range, these are still tuning knobs rather than proven optimal controls.

The workload coverage is good but not unlimited. Benefits are smaller for compute-bound decryption and for transmission-heavy L2Fwd, where faster recycling helps but reduced TX batching adds overhead. The experiments are mostly single-server and mostly single-core, with multicore scaling demonstrated on replicated per-core RX rings rather than more heterogeneous deployments. Finally, the paper does not address whether the same technique behaves as well across other kernels, NIC vendors, packet sizes, or multi-tenant software stacks outside the AF_XDP environment.

## Related Work

- _Tootoonchian et al. (NSDI '18)_ — ResQ argues for sizing RX resources to fit in LLC, whereas Toasty keeps the configured pool large and instead shrinks the active working set dynamically.
- _Pismenny et al. (OSDI '23)_ — ShRing reduces the I/O working set by sharing receive rings across cores using smart-NIC support; Toasty pursues similar cache goals with software on commodity NICs.
- _Alian et al. (MICRO '23)_ — IDIO proposes microarchitectural support to reduce unnecessary network-I/O writebacks, while Toasty attacks the same waste by reusing freed buffers before they cool.
- _Liu et al. (SIGCOMM '25)_ — CEIO redesigns the NIC-CPU datapath with hardware credit management, whereas Toasty leaves the hardware alone and changes refill policy in software.

## My Notes

<!-- empty; left for the human reader -->

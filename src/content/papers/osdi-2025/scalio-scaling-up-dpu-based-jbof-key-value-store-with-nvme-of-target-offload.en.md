---
title: "Scalio: Scaling up DPU-based JBOF Key-value Store with NVMe-oF Target Offload"
oneline: "Scalio offloads JBOF reads to NVMe-oF target offload, serves hot keys from an RDMA-visible inline cache, and batches writes so one DPU can keep scaling past four SSDs."
authors:
  - "Xun Sun"
  - "Mingxing Zhang"
  - "Yingdi Shan"
  - "Kang Chen"
  - "Jinlei Jiang"
  - "Yongwei Wu"
affiliations:
  - "Tsinghua University"
  - "Quan Cheng Laboratory"
conference: osdi-2025
code_url: "https://github.com/madsys-dev/scalio-osdi25-ae"
tags:
  - storage
  - smartnic
  - disaggregation
  - caching
  - rdma
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Scalio argues that high-density DPU-based JBOF key-value stores are bottlenecked by the DPU CPU, not by SSD media or network IOPS. It therefore pushes reads onto one-sided RDMA plus NVMe-oF target offload, keeps hot items in a compact RDMA-visible DRAM cache, and leaves the DPU CPU mostly with buffered writes and coherence management. The key systems result is that this combination keeps linearizability while letting a single DPU scale past the four-SSD plateau reported for prior JBOF KV stores.

## Problem

The paper starts from a mismatch in modern JBOF hardware. Vendors now sell DPU-based JBOF boxes with 26 or 36 SSDs, so throughput per watt should improve as more flash devices share the same control plane. But existing software stacks do not exploit that density. In LEED, the authors show that throughput stops improving once roughly four SSDs are attached because the DPU spends too many cores handling SSD I/O and metadata work. In their own reproduction, CPU usage for SSD I/O reaches 400% at the same point that throughput plateaus, even though network I/O utilization stays below 1% of the ConnectX-6 peak.

That bottleneck is especially painful for the paper's target workload: small key-value operations, like the ones common in serving systems and cloud applications. In that regime, each SSD request is cheap enough that the weak DPU cores become the scarce resource. The obvious fix, "just bypass the CPU," is incomplete, because once clients can directly read from SSD and manipulate DRAM-resident cache metadata through RDMA, the system can no longer lean on ordinary CPU-side coherence. The real problem is therefore twofold: move as much I/O work as possible out of the DPU CPU, and still define a cache/update protocol whose interleavings are linearizable.

## Key Insight

Scalio's central claim is that a DPU-based JBOF should treat the HCA and network path as the fast path for reads, and reserve the DPU CPU for the parts that genuinely need centralized coordination. NVMe-oF target offload already lets the server-side HCA translate remote NVMe requests into peer-to-peer SSD commands without involving the DPU cores; the paper's key move is to build the KV store around that primitive instead of around CPU-issued SSD I/O.

That idea only works because Scalio pairs it with a very small DRAM structure that clients can read and update directly. Hot items live inline in hash blocks, so a cache hit is a single RDMA read. A miss still avoids the DPU CPU: the client locks a victim slot, learns the SSD offset from the same block, performs an NVMe-oF target-offloaded read, and fills the slot itself. Writes are not made fully one-sided, but the paper argues that they can be amortized with ring-buffered batching and group commit. The remaining correctness challenge is solved with two explicit slot-state flags, `occupied` and `complete`, so clients can distinguish empty, filling, valid, and invalidated cache entries instead of assuming DRAM and SSD are automatically coherent.

## Design

Scalio splits the data path into a read-mostly offloaded fast path and a write path that still uses the DPU CPU, but in bulk. The in-memory structure is an RDMA-accessible hash table whose blocks are stored contiguously in DRAM. Each slot stores the key and value inline, plus `occupied`, `complete`, and `last_ts` metadata. The paper's sensitivity study says blocks up to 1 KB do not saturate network bandwidth; that is enough to keep up to ten 100-byte key-value pairs in one block. Each block also carries a `next_offset` pointer into the SSD-resident hash index, so a miss can jump directly to the flash-side metadata.

The read workflow is almost entirely one-sided. A client first RDMA-reads the hash block. If it finds the key in a valid slot, it returns immediately. Otherwise it chooses a victim using client-maintained LRU timestamps, uses RDMA CAS on `complete` to lock the slot, double-reads the block to make sure no competing client inserted the same key elsewhere, then issues an NVMe-oF target-offloaded read to the SSD and fills the slot with RDMA writes. This is the part that turns underused network/HCA capacity into storage throughput: the target offload path delivers similar read IOPS to standard NVMe-oF, but the paper measures 0 target CPU usage instead of 562% CPU for the conventional software target.

The write workflow is deliberately different. Clients append updates and client IDs into a ring buffer in DRAM. The DPU CPU polls this buffer, batches writes, flushes them to SSD, updates the in-memory `next_offset`, then notifies clients so they can invalidate stale cached copies. The batching matters because LEED performs two SSD writes per update; Scalio's group commit drives that down to about one write per update in the experiments. The consistency protocol formalizes four slot states: reusable empty slots, slots being filled, valid complete slots, and invalidated-in-flight slots. Readers retry on in-progress entries, writers invalidate by clearing `occupied`, and an optional lease can reclaim abandoned fills after client failure. The paper then gives linearization points for cache hits, misses, and writes and proves that every read returns the value of its closest preceding write.

## Evaluation

The evaluation uses one storage node and five client nodes over RDMA, with seven Samsung 970 PRO SSDs and a ConnectX-6 HCA on the storage side. To emulate a commodity DPU JBOF, the server is capped at 8 Xeon cores and 8 GB of memory. Workloads are YCSB A, B, C, D, and F over 20 million key-value pairs, with keys up to 16 bytes and values up to 64 bytes. Baselines are LEED and LEED combined with Ditto as a remote in-memory cache.

The main scaling result is straightforward: as SSD count grows from 1 to 7, LEED and LEED+Ditto flatten once the server hits its CPU wall, while Scalio keeps scaling. The paper reports 1.8x-3.3x higher throughput than LEED+Ditto and 2.5x-17x higher throughput than LEED. On read-heavy workloads B, C, and D, the gain reaches about 3x; on write-heavy A and F, about 2x. The improvement breakdown is also useful. Offloaded reads alone contribute 1.5x-3.2x, inline caching absorbs 72.2%, 85.2%, and 62.6% of operations on YCSB B, C, and D and yields 3.6x, 6.7x, and 2.7x improvements there, and batched writes add up to another 1.96x by halving SSD writes per update.

The evaluation also shows the tradeoff the design makes. Without batched writes, Scalio is both faster and lower-latency than LEED+Ditto, with 20%-30% lower average latency across workloads. With batching enabled, throughput rises further, but write latency increases because the linearization point is tied to SSD logging plus cache invalidation. The authors give YCSB A as an example where Scalio gets 2.1x higher throughput at 1.97x higher latency, reaching 614 us average latency. The paper's evidence is strongest on the CPU-offload thesis and somewhat weaker on deployment realism: the system is evaluated on an emulated, not production, DPU platform and only up to seven SSDs, even though the motivation is 26-36 SSD JBOFs.

## Novelty & Impact

Relative to _Guo et al. (SIGCOMM '23)_, Scalio is not just a better SSD-backed KV layout for JBOFs; it changes which hardware component sits on the critical path. LEED still spends DPU CPU cycles on SSD operations, whereas Scalio re-routes read I/O through NVMe-oF target offload and treats DRAM metadata as a remote RDMA object. Relative to _Shen et al. (SOSP '23)_, the contribution is also more than "add a cache": Ditto is an elastic disaggregated DRAM cache, while Scalio integrates the cache with SSD-backed offsets and a correctness protocol that spans DRAM plus flash.

The paper's impact is likely to be on systems builders working on SmartNIC/DPU storage servers, storage disaggregation, and small-object KV serving. Its main contribution is a new mechanism combination rather than a new workload study: target-offloaded SSD reads, inline RDMA-visible caching, buffered writeback, and an explicit cache-consistency state machine. The result is a credible argument that target offload should be treated as a first-class storage-system primitive, not just as an NVMe transport optimization.

## Limitations

Scalio is tuned for small point operations. The evaluation uses keys up to 16 bytes, values up to 64 bytes, and omits YCSB E because the system does not target range queries. The paper does not show how the inline-block design behaves for large values, multi-record transactions, or workloads whose locality is too weak for the DRAM cache to absorb many reads.

The system also does not eliminate the control-plane role of the DPU CPU; it narrows it. Writes still go through server-side batching, notifications, and invalidation, so the design trades some write latency for throughput. The reported failure story is also partial. Scalio adds an optional lease for abandoned fills, but server failures are largely pushed to orthogonal redundancy such as RAID or dual-DPU deployment rather than handled inside the core protocol. Finally, the evaluation is only on an emulated 8-core/8 GB DPU setting and up to seven SSDs, so the paper's strongest claims about very high-density JBOFs are extrapolations rather than full end-to-end demonstrations.

## Related Work

- _Guo et al. (SIGCOMM '23)_ - LEED targets the same SmartNIC JBOF setting, but its DPU CPU still executes SSD I/O and becomes the scale-up bottleneck that Scalio attacks.
- _Shen et al. (SOSP '23)_ - Ditto is a disaggregated DRAM caching system; Scalio borrows the idea of client-visible remote cache state but integrates it with SSD-backed offsets and linearizable invalidation.
- _Sun et al. (CLUSTER '22)_ - SKV offloads parts of a distributed KV store to SmartNICs, whereas Scalio focuses on a JBOF server and pushes direct SSD reads through NVMe-oF target offload.
- _Zhang et al. (FAST '22)_ - FORD uses one-sided RDMA atomics for distributed transactions over disaggregated persistent memory; Scalio instead uses a lighter RDMA protocol for cache/index maintenance in an SSD-backed KV store.

## My Notes

<!-- empty; left for the human reader -->

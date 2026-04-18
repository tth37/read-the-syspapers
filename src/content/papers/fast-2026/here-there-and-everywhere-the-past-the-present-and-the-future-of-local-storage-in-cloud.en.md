---
title: "Here, There and Everywhere: The Past, the Present and the Future of Local Storage in Cloud"
oneline: "Surveys Alibaba Cloud's three local-storage generations and proposes a local-plus-EBS hybrid that restores availability and elasticity while keeping near-local speed."
authors:
  - "Leping Yang"
  - "Yanbo Zhou"
  - "Gong Zeng"
  - "Li Zhang"
  - "Saisai Zhang"
  - "Ruilin Wu"
  - "Chaoyang Sun"
  - "Shiyi Luo"
  - "Wenrui Li"
  - "Keqiang Niu"
  - "Xiaolu Zhang"
  - "Junping Wu"
  - "Jiaji Zhu"
  - "Jiesheng Wu"
  - "Mariusz Barczak"
  - "Wayne Gao"
  - "Ruiming Lu"
  - "Erci Xu"
  - "Guangtao Xue"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Alibaba Group"
  - "Solidigm"
conference: fast-2026
category: cloud-and-distributed-storage
tags:
  - storage
  - virtualization
  - hardware
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

This paper is both an industrial retrospective and a forward-looking design study. It explains why Alibaba Cloud's local-storage stack moved from a kernel/Virtio path to `ESPRESSO`, then `DOPPIO`, then `RISTRETTO`, and argues that the next step is hybrid rather than purely local: keep a fast local tier for latency-sensitive I/O, then pair it with Elastic Block Storage for durability, elasticity, and wider deployment. In microbenchmarks, `RISTRETTO` reaches `949K` 4KB random-read IOPS and `6.7 GB/s` read throughput on one virtual disk, close to a physical Gen4 SSD, while the `LATTE` prototype reaches `8.9 GB/s` read bandwidth at a `75%` hit rate.

## Problem

Cloud local storage is attractive because it is physically attached to the compute server, so it avoids the network hop and delivers near-device performance at a lower price than disaggregated block storage. The problem is that the same architectural decision that makes local disks fast also makes them operationally awkward. Local disks are hard to scale elastically, they are not naturally replicated, and they are only practical in regions with enough demand to keep directly attached SSDs busy. That means the product has always lived under a tension between performance and cloud friendliness.

The paper argues that SSD evolution repeatedly broke older assumptions. Alibaba's original HDD-era kernel stack was acceptable when devices were slow, but NVMe SSDs amplified the cost of VM exits, system calls, and interrupts. Moving to an SPDK polling stack in `ESPRESSO` removed much of that software overhead, but it consumed dedicated host cores and still paid completion-path context-switch costs. `DOPPIO` then pushed virtualization and I/O handling into ASIC-based DPUs to eliminate host CPU usage, yet that created a different ceiling: fixed-function hardware could not keep up with newer `1.5M`-IOPS SSDs or quickly absorb new cloud features like logical volume management and ZNS support.

The paper's final problem statement is broader than fast I/O. Even if `RISTRETTO` makes a local disk behave almost like a physical SSD, purely local storage still suffers from weak availability, fixed capacity granularity, and limited accessibility. High-end remote storage such as Alibaba `EBSX` solves those issues, but the paper says a `1M`-IOPS, `4 TB` `EBSX` disk can cost roughly `20x` a comparable `RISTRETTO` local disk. The real question, then, is how to keep the latency advantages of locality without inheriting locality's product limitations.

## Key Insight

The paper's central proposition is that local storage should not be treated as one fixed design point. As devices get faster, the dominant bottleneck moves from software context switches, to host CPU reservation, to the rigidity of fixed-function offload hardware, and finally to the product limits of purely local disks. A viable architecture therefore needs to place the latency-critical fast path in specialized hardware while leaving policy, feature evolution, and cloud semantics in programmable software.

That logic motivates `RISTRETTO`'s split design: the ASIC owns NVMe emulation, DMA routing, and interrupt injection, while the ARM SoC owns the block abstraction layer and feature logic. It also motivates `LATTE`: once availability and elasticity become the main problem, the right answer is not to make local disks more complicated, but to demote them into a high-performance front tier and let remote `EBS` provide the durable, elastic backing store. The most durable lesson is therefore an abstraction boundary, not a single mechanism.

## Design

`ESPRESSO` is the first SSD-era redesign. It moves the storage stack into user space with `SPDK`, uses polling instead of interrupts, and binds each virtual disk thread to a dedicated host core with share-nothing data structures. That substantially reduces the context-switch overhead that crippled the old kernel stack, and it scaled to tens of thousands of servers. But the price is clear in deployment: bare-metal instances become impossible on those hosts, CPU utilization is poor because the reserved cores are only about `60%` utilized at the `99th` percentile, and the completion path still triggers `eventfd` plus hypervisor transitions.

`DOPPIO` offloads that path to commercial ASIC-based DPUs. Each DPU manages two NVMe SSDs, exposes namespaces as `SR-IOV` virtual functions, fetches guest NVMe commands via DMA, buffers data in DPU DRAM, and notifies the guest with hardware `MSI` interrupts. This removes host-CPU dependence and cuts the software completion overhead that remains in `ESPRESSO`. The downside is that the DPU becomes the new bottleneck: with one DPU serving two Gen4 SSDs, a `DOPPIO` virtual disk tops out around `1.3M` IOPS, and the hard-wired logic is a bad match for evolving cloud features.

`RISTRETTO` is the paper's main architecture. It is a PCIe extension board that combines an ASIC, `4` ARM Cortex-A72 cores, and `64 GB` of DRAM. The ASIC emulates the NVMe controller, fetches guest commands, routes DMA directly between SSD and host memory, injects hardware interrupts, and maintains virtual queues between ASIC and SoC. The SoC runs an `SPDK`-based runtime that polls those queues, performs queue mapping, and inserts a programmable block abstraction layer for `LVM`, `RAID`, caching, and even host-side `FTL` logic for devices like `ZNS` SSDs. Multiple virtual queues mirror the guest's NVMe queue pairs, so the design preserves parallelism instead of funneling all traffic through one software path.

The paper then treats `EBSX` and `LATTE` as the future branch of the design space. `EBSX` is Alibaba's high-performance remote block store, with about `30 us` latency, `6 GB/s` throughput, and `1M` IOPS, but it is expensive because of premium hardware and stronger redundancy. `LATTE` uses `RISTRETTO` as a front-end cache and standard `EBS` as the backend, building on `CSAL`. Writes go through an `ML` dispatcher that looks at per-I/O latency, size, and queue depth over a sliding window of `5` I/Os, then uses a linear `SVM` to choose cache or backend. Reads use an `S3-FIFO`-style admission policy so one-hit blocks do not pollute the local tier. The system keeps an `L2P` map, preserves write ordering across cache and backend flushes, retrains its tiny model when latency variance exceeds `10%`, and keeps inference overhead low enough that the paper reports at most `200 ns` per decision.

## Evaluation

The evaluation mostly supports the paper's claims because it aligns the methodology with the argument. The three generations of local storage are tested on the same SSD model in one environment, so the core comparisons are not artifacts of device choice. Under 4KB random reads on a single virtual disk, `RISTRETTO` reaches `949K` IOPS versus `572K` for `ESPRESSO` and `661K` for `DOPPIO`; with `8` virtual disks, it scales to `7.385M` IOPS and `53.4 GB/s` sequential-read throughput. The near-physical claim is credible: Table 1 reports about `900K/180K` read/write IOPS and `6.7/4.0 GB/s` throughput for a local `RISTRETTO` virtual disk, compared with `1,000K/180K` and `6.9/4.1 GB/s` for the underlying physical SSD.

The microbenchmarks also explain why the earlier designs lose. `ESPRESSO` has the highest read and write latency because the interrupt and hypervisor path remains visible at high IOPS. `DOPPIO` removes much of that overhead, but its read throughput stays around `4.1 GB/s` on a Gen4 SSD because the DPU's PCIe channel is the limiter. `RISTRETTO` fixes both issues: it uses hardware interrupts for the guest-facing completion path but keeps enough software programmability on the SoC side to avoid the feature dead end of `DOPPIO`.

`LATTE` is evaluated more like a prototype than a deployed product, but the results are still interesting. With a `75%` cache hit rate, it reaches `8.9 GB/s` read bandwidth and `7.8 GB/s` write bandwidth, outperforming both `RISTRETTO` and `EBSX` by using the bandwidth of the local tier and backend together. On three production traces, the reported read hit rates are `90.23%`, `88.79%`, and `82.80%`, and the trace replay shows clearly lower latency than standard `EBS` and `EBSX`. In MySQL Sysbench, `RISTRETTO` beats `DOPPIO` and `ESPRESSO` on read-only and mixed workloads, while `LATTE` surpasses `RISTRETTO` on write-only workloads by combining local buffering with backend throughput. The main caveat is maturity: `LATTE` is still a proof of concept, and its strongest microbenchmark results depend on favorable hit rates and auto-scaling behavior that are not yet backed by field deployment.

## Novelty & Impact

Relative to _Kwon et al. (OSDI '20)_ and _Chen et al. (HPCA '23)_, this paper is not just another storage-offload device. Its novelty is the longitudinal argument that each generation of cloud local storage solved one bottleneck only to expose the next, and that the right endpoint is an ASIC/SoC split plus a local-cloud hybrid rather than a pure-software or pure-hardware extreme. Relative to _Zhou et al. (EuroSys '24)_, `LATTE` extends a local-plus-remote write-caching foundation into a fuller hybrid block store with dispatch and admission control. Relative to _Zhang et al. (FAST '24)_, it complements a cloud-block-store evolution story with the opposite perspective: what happens when storage is brought back onto the compute node.

That makes the paper valuable to practitioners more than to algorithm designers. People building VM storage virtualization, storage DPUs, or hybrid local/remote tiers will cite it because it turns several years of operational lessons into concrete architectural boundaries. The contribution is part new mechanism, part experience report, and part product-design argument about where local storage should stop.

## Limitations

The paper is strongest on `RISTRETTO` and weaker on the final `LATTE` vision. `RISTRETTO` has several-thousand-node deployment experience behind it, but `LATTE` is explicitly still a proof of concept, so the future-facing claims about QoS, cost reduction, and operability are less validated than the local-disk results. The paper also admits that if multiple tenants share one local disk and burst at the same time, maintaining predictable QoS is hard.

Even in the hybrid design, durability is conditional. The paper says all data eventually reaches `EBS`, but in write-back mode unflushed local data can still be lost on a local-disk crash; stronger guarantees require `O_DIRECT` or `O_SYNC`, which changes the performance regime. Cost also remains open: `LATTE Auto` improves the normalized monthly price to about `2.1-4.0x` `RISTRETTO`, but that is still materially above a pure local disk.

I also think the paper inherits the limits of experience-report framing. It is persuasive about why each bottleneck mattered, but some of the system-level conclusions are Alibaba-specific: regional accessibility assumptions, product packaging, and the economics of `EBSX` may not transfer directly to every cloud. The microbenchmarks are careful, yet the end-to-end operational complexity of hybrid failover, retraining, and cache sharing is only partially quantified.

## Related Work

- _Kwon et al. (OSDI '20)_ — `FVM` uses FPGA-assisted virtual device emulation for storage virtualization, while this paper studies ASIC- and ASIC/SoC-based offload under cloud local-disk product constraints.
- _Zhou et al. (EuroSys '24)_ — `CSAL` is the immediate software base for `LATTE`, but `LATTE` adds ML-based path selection plus `S3-FIFO` admission so the local tier is not just a write buffer.
- _Zhang et al. (FAST '24)_ — `EBS Glory` explains the evolution of Alibaba's remote block store; this paper covers the complementary local-storage lineage and the bridge back to `EBS`.
- _Yang et al. (SOSP '23)_ — `S3-FIFO` provides the queue structure that `LATTE` adopts for cache admission and eviction to avoid filling the local tier with one-hit blocks.

## My Notes

<!-- empty; left for the human reader -->

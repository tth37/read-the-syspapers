---
title: "Sleeping with One Eye Open: Fast, Sustainable Storage with Sandman"
oneline: "Sandman cuts all-flash storage energy by sleeping polling cores, waking them via cache-coherent user waits, and detecting bursts from NIC queues instead of CPU load."
authors:
  - "Yanbo Zhou"
  - "Erci Xu"
  - "Anisa Su"
  - "Jim Harris"
  - "Adam Manzanares"
  - "Steven Swanson"
affiliations:
  - "UC San Diego"
  - "Shanghai Jiaotong University"
  - "Samsung Semiconductor"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764804"
tags:
  - storage
  - scheduling
  - energy
  - datacenter
category: storage-and-databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Sandman targets a specific waste in modern all-flash servers: polling stacks keep many CPU cores hot even though storage demand is bursty. It keeps an SPDK-style polling datapath, but consolidates work onto fewer cores, puts idle polling cores into shallow sleep, wakes them through cache-coherence-based user-wait instructions, and detects bursts from NIC queue arrivals rather than CPU-cycle estimates. The result is near-SPDK latency with materially lower energy use.

## Problem

The paper starts from an uncomfortable observation: faster SSDs have made storage-server software, not flash media, the dominant energy cost. In their NVMe-oF setup, one logical core can drive about `800K` IOPS with SPDK, so a single PCIe 5.0 SSD that can reach `2,500K` IOPS already needs at least three logical cores. That makes all-flash servers expensive not just in raw CPU budget but also in the secondary power they induce from memory and cooling.

Busy polling makes the situation worse. On their 16-SSD server, CPU power stays near the peak-load level even when the workload is under `5%` of maximum IOPS, and the total wasted energy in real cloud traces can be `3.4x` the energy actually needed for the arriving requests. The underlying reason is that operators provision for bursts, but those bursts are short and frequent rather than sustained.

Existing power-saving approaches each fail in a different way. Linux interrupts save power at light load but pay context-switch overhead and can even consume more energy than SPDK at heavy load because they need more CPU work per I/O. Governor lowers frequency, but hardware P-state transitions take hundreds of microseconds. Dynamic Scheduling turns polling cores on and off, but it estimates load from CPU cycles and wakes sleeping cores through software interrupts, so it misreads microsecond-scale bursts and adds wakeup overhead. Hybrid Polling avoids the worst latency penalties, but short and independent sleep intervals leave little room for real energy savings.

## Key Insight

The core proposition is that storage stacks should scale compute by sleeping and waking polling cores, not by lowering CPU frequency or reintroducing interrupt-heavy critical paths. That only works if wakeups are fast enough and the scheduler knows about bursts before CPU-load statistics catch up.

Sandman therefore couples two claims. First, shallow sleep is the right low-power state because it preserves a fast return path; the paper measures roughly `3 us` exit latency for `C-1` sleep versus about `450 us` for dropping to `400 MHz` and about `800 us` for deeper sleep states. Second, the best burst signal is not thread load but incoming I/O count at the NIC queues, because queue arrivals reveal sudden demand before a thread has accumulated enough CPU cycles to look busy. Together, those choices let Sandman stay close to static polling on latency while still shutting down excess compute capacity most of the time.

## Design

Sandman runs on top of SPDK and splits cores into one main core and multiple worker cores. Every core still executes a polling datapath for RDMA networking and NVMe completions, but the main core also runs the scheduler. Work is packaged as lightweight user-level I/O threads, each representing a set of tasks and stored in a ring list. A core repeatedly takes an I/O thread from the head, runs its tasks, and puts it back at the tail; moving work across cores just means unlinking the I/O thread from one ring and inserting it into another.

The fast wakeup mechanism is the paper's most distinctive systems trick. When a worker core becomes idle, Sandman moves away its I/O threads, arms `monitorx` on the next event-queue slot, and executes `mwaitx` so the core enters shallow sleep while watching that cache line. When the scheduler wants to reuse that core, another core writes a scheduling event into the queue; the coherence state change wakes the sleeping core directly, without a system call or interrupt in the critical path. Measured thread movement costs only `106.52 ns`, while the software-interrupt wakeup path in Dynamic Scheduling costs about `27 us`.

The control policy has two time scales. Every `1 s`, Sandman monitors core load and consolidates lightly loaded threads onto healthy cores, preferring placements that let sibling hyper-threads sleep together. The default healthy threshold is `80%` busy cycles, leaving a `20%` buffer for bursts; the idle threshold is half of that. Every `10 us`, Sandman performs burst detection. Instead of using CPU load, it counts incoming I/Os per thread from RDMA receive queues, maintains a moving average plus standard error, builds a confidence interval, and treats counts above the upper bound as burst evidence. When that happens, it wakes an unused core and gives the bursting thread an entire core immediately, then lets the coarse-grained scheduler reconsolidate later if the burst subsides.

Implementation-wise, the paper extends SPDK's scheduler, event queues, and pollers, then adds a user-wait abstraction, a queue-based burst-detection module, and a new scheduler. The design is therefore evolutionary rather than a new storage stack from scratch: the datapath remains SPDK-style busy polling, while the novelty sits in how Sandman decides when that polling footprint should shrink or expand.

## Evaluation

The evaluation uses two AMD EPYC 9454P servers connected by dual `200 Gbps` RDMA, with `16` Samsung PM1743 PCIe 5.0 SSDs per storage node. The baseline comparison is demanding: SPDK is treated as the best-performance case, while Linux, Governor, Dynamic Scheduling, and Hybrid Polling are tuned alternatives.

On stable `4 KB` random-read workloads across `16` SSDs, Sandman matches Governor and Dynamic Scheduling on power draw but stays much closer to SPDK on latency. The paper reports that Sandman's tail latency differs from SPDK by only `4.8%`, while Governor reaches up to `161.5%` higher latency and Dynamic Scheduling degrades sharply once thread migrations become frequent. This supports the paper's argument that sleep-based scaling plus better burst signals beat frequency scaling or cycle-based scheduling.

On explicit burst workloads, Sandman is stronger: it cuts system power by up to `39.38%` relative to SPDK yet matches SPDK's tail latency and IOPS, unlike Linux and Governor. The ablation study is also useful. Replacing frequency scaling with sleeping cores reduces latency by `41.34%`; adding NIC-queue burst detection gives another `25.13%`; removing interrupts from the wakeup path yields a further `17.69%`. On the power side, hybrid polling helps, but sleeping cores and sibling-aware packing deliver the larger savings. The burst detector reaches `93.45%-95.78%` accuracy on stable workloads by avoiding unnecessary migrations and `97.84%` accuracy on actual bursts.

Application-level results go in the same direction. On SPDK RAID-5 and RocksDB/YCSB, Sandman combines the lower power of Governor-like approaches with throughput and latency closer to SPDK. On 24-hour block traces from Alibaba and Tencent, it achieves the paper's most important end-to-end claim: energy consumption falls by `30.23%` relative to Linux and `33.36%` relative to SPDK while the latency distribution remains the closest to SPDK among all power-saving designs.

## Novelty & Impact

Sandman's novelty is not a new SSD datapath or a new scheduling theory in isolation. It is the combination of three ideas that prior systems treated separately: shallow-sleep core scaling, syscall-free wakeup via cache-coherence-based user waits, and burst detection from network queue arrivals instead of CPU-cycle accounting. That combination turns energy efficiency into a first-class objective for polling-based storage stacks without abandoning the performance profile that made SPDK attractive in the first place.

The likely impact is on storage backends and disaggregated flash servers where operators already pay the cost of overprovisioning for bursty demand. The paper also contributes a useful argument for sustainable systems work more broadly: once hardware gets fast enough, "high performance" and "always busy" are not synonyms, and the software stack becomes a major part of the carbon story.

## Limitations

Sandman depends on fairly modern hardware and software assumptions. Its best wakeup path requires unprivileged user-wait instructions now present on newer Intel and AMD server CPUs; on older platforms it falls back to software interrupts and loses some of its advantage. The design also assumes a polling datapath built around SPDK, RDMA queues, and explicit per-thread queue visibility, so the paper does not show how well the same control logic transfers to very different storage stacks.

The scheduler itself is not free. At a `10 us` fine-grained interval, the main core spends `16.6%` of its CPU time running the scheduling algorithm, though the paper argues this mostly lands on a core otherwise reserved for scheduler work and idle threads. More importantly, the evaluation focuses on a narrow class of modern all-flash servers, mostly `4 KB` random reads plus a few application benchmarks and two field traces. That is enough to make the systems case, but not enough to prove Sandman is the right answer for every storage workload or deployment topology.

## Related Work

- _Fried et al. (OSDI '20)_ - Caladan shows that microsecond-scale userspace scheduling can respond quickly to load changes; Sandman applies that timing discipline to storage-server energy management rather than RPC interference control.
- _Jia et al. (SOSP '24)_ - Skyloft also uses userspace mechanisms to reduce scheduling overhead, but its focus is efficient scheduling itself, whereas Sandman uses fast wakeups as part of a storage-specific power-management loop.
- _Reidys et al. (OSDI '22)_ - BlockFlex demonstrates that cloud block-storage demand is bursty and harvestable; Sandman tackles the CPU-energy waste that those bursty storage backends incur when implemented with always-on polling.
- _Shu et al. (OSDI '24)_ - Burstable cloud block storage with DPUs shifts burst handling toward dedicated devices, while Sandman keeps the software stack on the storage server and reduces the power burned by its polling cores.

## My Notes

<!-- empty; left for the human reader -->

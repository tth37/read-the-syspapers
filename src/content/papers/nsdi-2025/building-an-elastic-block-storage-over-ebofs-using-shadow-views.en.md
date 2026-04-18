---
title: "Building an Elastic Block Storage over EBOFs Using Shadow Views"
oneline: "Shadow Views turn an opaque EBOF into a software telemetry plane, letting Flint spread extents, schedule I/Os by cost, and auction bandwidth across all SSDs."
authors:
  - "Sheng Jiang"
  - "Ming Liu"
affiliations:
  - "Carnegie Mellon University"
  - "University of Wisconsin-Madison"
conference: nsdi-2025
code_url: "https://github.com/netlab-wisconsin/Flint"
tags:
  - storage
  - disaggregation
  - observability
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

The paper argues that today's EBOFs are fast but opaque: clients see only fixed block volumes, not the bottlenecks inside the box. Shadow View reconstructs those runtime conditions in software, and Flint uses that view to spread extents, schedule I/Os by cost, and allocate bandwidth fairly. On a Fungible FS1600, Flint reaches 9.3/9.2 GB/s read/write bandwidth and improves a MinIO deployment by up to 2.9x.

## Problem

EBOFs are attractive because they replace a CPU-heavy storage server with a switch-centric box full of NVMe drives, exposing ordinary block volumes to clients. But that convenience comes from a smart-sender dumb-receiver design: each volume is pinned to one SSD, bandwidth reservation scales with volume size instead of actual demand, and the device reveals almost nothing about which internal ports, queues, or SSDs are congested.

That creates three pathologies. Single-volume throughput sticks near one-drive limits even though the chassis has many internal paths. Small-but-hot workloads over-allocate capacity to buy bandwidth, while large-but-cold workloads reserve bandwidth they do not use. Interference still appears once requests collide at SSDs or inside the pipeline; the authors show millisecond-scale tail-latency blowups and major drops on fragmented drives.

## Key Insight

The paper's claim is that clients can reconstruct enough hidden state in software. Because datacenter communication is only a few microseconds, per-I/O observations from clients plus a central controller can maintain a "shadow view" of which ports, pipes, and SSDs are busy. Once that view exists, placement, scheduling, and bandwidth allocation can react to real bottlenecks instead of static volume metadata.

That is why the contribution is broader than a better logical volume manager. Shadow View makes an otherwise closed EBOF observable enough to support elastic extent placement, per-I/O scheduling, and runtime bandwidth auctioning without changing the hardware datapath.

## Design

Shadow View models an EBOF as Ethernet ports flowing through NetPipes to internal I/O ports and then through IOPipes to SSDs. It tracks port traffic, pipe throughput and delay, and SSD state such as capacity, estimated bandwidth headroom, delay, and fragmentation. A view agent beside each client reports `<session, target SSD, type, size, RTT>` for completed I/Os; a view controller maps those vectors onto the model, maintains windowed statistics, synchronizes partial views with per-entity counters and a hybrid push/pull protocol, and back-propagates bottlenecks from SSDs to the affected pipes and sessions.

Flint turns that telemetry into storage policy. Its elastic volume (`eVol`) stores data in 2 MB extents that can live on any SSD. An arbiter creates one mega-volume per SSD, lazily allocates extents on first write, and chooses destinations with a weighted score over prior allocations, used capacity, busy degree, fragmentation, and user preference. On the client side, `io_uring` handles asynchronous submission while a PIFO-like eIO scheduler ranks requests by estimated cost and admits cheaper I/Os first without reordering within a stream.

Bandwidth is managed separately from capacity. Each active NVMe-oF session carries a three-part deficit vector for NetPipe, IOPipe, and SSD resources. The arbiter combines deficit round robin with a gang-scheduling style test and grants a slice only when the shadow view says the entire path has room. Reads and writes use a fast path when the client already owns enough slice budget; otherwise they renew slices on a slow path, and writes may also allocate a new extent. Flint can also replicate extents across three SSDs with chain replication.

## Evaluation

The prototype is about 7,600 lines of C++ on Dell R7525 clients, a Dell Z9264F-ON ToR, and a Fungible FS1600. The headline result is that eVol uses the EBOF as a box rather than as one SSD: it reaches 9.3 GB/s random-read and 9.2 GB/s sequential-write bandwidth, 14.5x and 13.6x better than a single physical volume. For 4 KB random reads and 4 KB sequential writes, median latency stays close to the baseline while P99 improves by 48.1% and 13.4%.

Fairness results support the bandwidth-auction design. Across mixed 4 KB/128 KB and read/write contests, Flint keeps bandwidth closer to demand than to volume size; without the auction, one case lets 128 KB reads take 4x the bandwidth of competing 4 KB writes. When 4 KB victim I/Os share an SSD with heavier background traffic, the eIO scheduler cuts latency sharply: against 128 KB random reads, it improves P50/P99/P999 by 4.8x/2.6x/7.5x. With deliberately congested SSDs, dynamic remapping and scheduling reduce average latency by 40.1% under read congestion and 29.8% under write congestion, and they beat LVM by 2.3x to 3.8x.

At the application level, MinIO over Flint gains up to 2.9x throughput and up to 66.4%/74.6% average read/write latency reduction versus the basic EBOF volume. The telemetry path remains light: `view_query` is 24 us P50 / 31 us P99, and `view_sync` is 38 us P50 with sub-70 us P99.

## Novelty & Impact

The main novelty is not the elastic volume alone but the shadow-view abstraction: it extracts actionable state from an opaque vendor EBOF without changing the hardware. Flint matters because it shows that one reconstructed view can drive placement, scheduling, and fairness together. That makes the paper relevant to deployable storage disaggregation, especially when the hardware is fixed but the control plane can still be smarter.

## Limitations

Shadow View still infers much of the SSD state indirectly from end-to-end latency, so bad estimates could mislead scheduling and bandwidth decisions. The system also depends on an external arbiter and controller, and the evaluation stays at small scale.

Replication exposes another gap between idea and hardware: because FS1600 does not expose recirculation, chained writes add extra network round trips and raise 4 KB / 128 KB write P50 by 2.9x / 3.5x. Finally, single-volume throughput is still capped by client NIC bandwidth, so scale-out needs multiple sessions or clients.

## Related Work

- _Klimovic et al. (EuroSys '16)_ - Flash storage disaggregation characterized the performance case for remote flash, while this paper focuses on how to manage an opaque EBOF box once that hardware exists.
- _Klimovic et al. (ASPLOS '17)_ - Reflex builds a custom low-overhead remote-flash datapath; Flint instead leaves the vendor EBOF datapath mostly intact and adds a software telemetry and control layer around it.
- _Min et al. (SIGCOMM '21)_ - Gimbal targets multi-tenant SmartNIC JBOFs and uses more conservative interference control, whereas Flint uses Shadow View to estimate runtime bottlenecks and schedule at per-I/O granularity over EBOFs.
- _Shu et al. (OSDI '24)_ - Burstable cloud block storage with DPUs also adds intelligence outside commodity storage devices, but Flint's distinctive move is reconstructing hidden in-box state to drive extent placement and bandwidth auctioning.

## My Notes

<!-- empty; left for the human reader -->

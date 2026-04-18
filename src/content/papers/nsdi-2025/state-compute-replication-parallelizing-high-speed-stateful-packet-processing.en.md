---
title: "State-Compute Replication: Parallelizing High-Speed Stateful Packet Processing"
oneline: "SCR round-robins packets across cores and piggybacks bounded packet history, so each core rebuilds flow state locally and one stateful flow can scale beyond one core."
authors:
  - "Qiongwen Xu"
  - "Sebastiano Miano"
  - "Xiangyu Gao"
  - "Tao Wang"
  - "Adithya Murugadass"
  - "Songyuan Zhang"
  - "Anirudh Sivaraman"
  - "Gianni Antichi"
  - "Srinivas Narayana"
affiliations:
  - "Rutgers University, USA"
  - "Politecnico di Milano, Italy"
  - "New York University, USA"
  - "Queen Mary University of London, UK"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
code_url: "https://github.com/smartnic/bpf-profile"
tags:
  - networking
  - smartnic
  - hardware
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SCR scales one stateful flow across multiple cores by steering packets round-robin and piggybacking a bounded packet history on each delivered packet. Each core replays the missed history to rebuild local state, which avoids both lock contention and the one-core-per-flow ceiling of RSS sharding.

## Problem

The paper studies CPU-bound software datapaths such as load balancers, DDoS filters, connection trackers, and telemetry services. Single-core packet-processing throughput has mostly flattened, while NIC line rates continue climbing toward 200 Gbit/s and beyond, so multicore scaling is the only credible way forward.

But state makes the obvious approaches fail. Shared-state parallelism uses locks or atomics and collapses on hot flows because of cache bouncing and synchronization. Flow sharding with RSS removes contention by pinning each flow to one core, yet every elephant flow is still limited by single-core speed. RSS++ can rebalance shards, but it still cannot split one overloaded flow across several cores. The authors want a method that handles general stateful updates, does not care how skewed the flow distribution is, and improves rather than regresses as cores are added.

## Key Insight

The central observation is that correctness requires all cores to replay the same ordered state transitions, not to receive every packet as a separately dispatched software event. That distinction matters because in high-speed packet processing, dispatch often costs more CPU than the actual program logic.

SCR therefore replicates state and computation, but not dispatch. If a sequencer sends every kth packet to a core and includes the previous k-1 packets' relevant metadata, that core can replay the missed transitions locally, catch up its private state, and then process its assigned packet correctly. When dispatch dominates compute, this duplicated replay work is cheaper than lock contention or one-core-per-flow sharding.

## Design

The design assumes a deterministic packet-processing program that can be viewed as a finite-state machine. Each core holds a private state replica. A packet-history sequencer sees all packets, sprays them round-robin across cores, and keeps a bounded ring buffer of only the fields needed to evolve state. That history depends on core count and metadata width, not on the number of active flows.

Each delivered packet carries the original packet, a compact recent history, and an index or pointer naming the oldest history entry. The history is placed before the original packet so hardware can write it at a fixed location and software can still parse the original frame as one contiguous region. In the top-of-rack-switch deployment, the sequencer adds a dummy Ethernet header so the host NIC accepts the rewritten packet.

An SCR-aware program first replays the piggybacked history to fast-forward its private state, then processes the packet assigned to that core. Because all cores eventually observe the same ordered history, the replicas stay consistent without explicit cross-core synchronization.

The sequencer is implemented in two ways. On Tofino, a register-based design stores the ring index, reads history into packet metadata, and overwrites the oldest entry selected by that index. On NetFPGA-PLUS, a Verilog module stores an `N x b` history array plus a pointer, prefixes the full history to each packet, updates one row, and advances the pointer. For rare loss between sequencer and cores, packets carry sequence numbers and each core maintains a log with `history`, `LOST`, and `NOT_INIT` entries so a lagging core can recover missing history from peer logs instead of copying full flow state. For non-determinism, the sequencer can attach timestamps and programs using randomness should share a fixed seed.

## Evaluation

The evaluation uses two back-to-back 100 Gbit/s servers with Intel Ice Lake CPUs and ConnectX-5 NICs. The DUT runs five XDP/eBPF programs: a DDoS mitigator, heavy-hitter monitor, TCP connection tracker, token-bucket policer, and port-knocking firewall. Traffic comes from a university datacenter trace, a CAIDA backbone trace, and a synthetic hyperscaler datacenter trace for bidirectional TCP connection tracking.

Across all five programs, SCR is the only technique that keeps scaling monotonically as cores are added. The paper reports linear throughput growth over the tested core counts, while lock-based sharing collapses after a few cores and RSS or RSS++ flatten once one hot flow exceeds single-core capacity. The key result is therefore structural: SCR removes the single-elephant-flow bottleneck that sharding leaves in place.

Counter measurements explain the difference. Compared with lock-based sharing, SCR gets higher L2 hit ratios and lower compute latency because it avoids shared-state contention. Compared with RSS and RSS++, it gets higher and more even retired IPC because work is not stranded on a handful of hot-flow cores. The gains shrink when program compute grows relative to dispatch, which matches the paper's simple model.

The deployment-cost results are also useful. Loss recovery adds logging and synchronization overhead, but SCR still stays ahead of the baselines. The NetFPGA sequencer meets timing at 340 MHz on a 1024-bit datapath and, with 112-bit history rows, can support up to 128 cores while using very little FPGA area. The Tofino version is more constrained by available stateful ALUs, but it can still hold 44 32-bit history fields.

## Novelty & Impact

The novelty is the scaling principle itself: replicate state and replay bounded history so one stateful flow can use many cores without locks and without flow-level sharding. Prior systems mostly choose between shared-state contention and shared-nothing sharding; SCR opens a third point in the design space.

That matters for software datapaths whose bottleneck is packets per second rather than bytes per second. With modest sequencing support in future NICs or programmable switches, operators could keep middlebox logic in software while still tracking higher line rates and more adversarial traffic distributions.

## Limitations

SCR depends on strong but explicit assumptions. The program must be deterministic, or be made deterministic with sequencer-supplied timestamps and fixed random seeds. It also needs a sequencer capability that commodity NICs do not expose today, so real deployment depends on programmable NICs, switch pipelines, or future fixed-function support.

Piggybacked history is another limit. The extra bytes increase DDIO and cache pressure, consume PCIe bandwidth, and can move the bottleneck from CPU to NIC; the paper shows this happening after about 11 cores in one setup. SCR also works best when dispatch dominates compute. If the program itself is expensive, replaying history duplicates too much work and the scaling advantage fades.

## Related Work

- _Barbette et al. (CoNEXT '19)_ — `RSS++` improves flow sharding by migrating shards across cores, but it still cannot split one overloaded stateful flow across multiple cores.
- _Pereira et al. (NSDI '24)_ — automatic parallelization of software network functions also stays flow-oriented, whereas SCR replicates computation to parallelize a single flow.
- _Katsikas et al. (NSDI '18)_ — `Metron` accelerates NFV chains at hardware speed, but its scaling model is still based on distributing work across flows rather than replaying bounded history on every core.
- _Sadok et al. (HotNets '18)_ — packet spraying in software middleboxes argues for even packet distribution, while SCR adds the missing state-reconstruction mechanism needed for fully stateful per-packet updates.

## My Notes

<!-- empty; left for the human reader -->

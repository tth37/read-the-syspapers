---
title: "Phantom: Virtualizing Switch Register Resources for Accurate Sketch-based Network Measurement"
oneline: "Phantom turns a switch recirculation lane into virtual sketch registers, then replays timestamped updates on servers to raise measurement accuracy without reducing throughput."
authors:
  - "Xiang Chen"
  - "Hongyan Liu"
  - "Zhengyan Zhou"
  - "Xi Sun"
  - "Wenbin Zhang"
  - "Hongyang Du"
  - "Dong Zhang"
  - "Xuan Liu"
  - "Haifeng Zhou"
  - "Dusit Niyato"
  - "Qun Huang"
  - "Chunming Wu"
  - "Kui Ren"
affiliations:
  - "Zhejiang University"
  - "Quan Cheng Laboratory"
  - "The University of Hong Kong"
  - "Fuzhou University"
  - "Yangzhou University"
  - "Southeast University"
  - "Nanyang Technological University"
  - "Peking University"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696077"
tags:
  - networking
  - smartnic
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Phantom treats a programmable switch's isolated recirculation lane as extra storage for sketch register updates. By generating updates on the switch, replaying stateful register logic on monitoring servers, and rate-limiting exports by bandwidth and buffer budgets, it gives sketches O(10^6) effective registers and improves application-level accuracy by up to 86% without reducing switch throughput.

## Problem

Sketches are a standard way to measure Tbps-scale traffic, but they get better mainly by getting larger. More registers mean fewer hash collisions, which means lower per-flow error. The paper shows this directly with HashPipe: moving from 10^2 to 10^6 registers raises heavy-hitter F1 from 0.01 to 0.99 and recall from 0.61% to 98.99%.

Programmable switches, however, are bad at holding large sketches. Each pipeline stage exposes only a few register arrays, each array can only hold a few thousand 32-bit registers, and the total number of stages is fixed. That creates two hard limits at once: only a small number of arrays per sketch, and only a small number of counters per array. Prior systems mostly accept that ceiling. Static-allocation frameworks only pack sketches until SRAM is full. SCREAM and NetVRM improve utilization by multiplexing or pooling resources, but they still cannot create more per-switch state than the hardware exposes. Switch-chip redesigns and off-chip state stores ask for new hardware or large extra pipeline cost.

The missing piece is a way to increase effective sketch state on today's switches without sacrificing line-rate forwarding or saturating the link between the switch and its monitoring servers.

## Key Insight

Phantom's key claim is that a sketch register does not have to exist as a fixed SRAM cell inside the normal match-action pipeline. For measurement, what matters is preserving the ordered updates that define that register's value. Modern programmable switches already contain an isolated internal recirculation lane, with its own ports and bandwidth, that is usually underused. Phantom repurposes that lane as a backing store for virtual registers by recirculating timestamped register updates through it.

That alone is not enough, because many sketches do read-modify-write operations. Phantom therefore splits sketch logic across the switch and the monitoring server. The switch performs only the stateless part: hash the packet, determine the addressed register, and package the update. The server performs the stateful part by replaying updates in timestamp order and reconstructing register contents. The result is a clean separation: the switch provides fast update generation and temporary storage, while the server provides the full state view needed for correctness.

## Design

Phantom starts from three user budgets: recirculation bandwidth, traffic-manager buffer space, and switch-to-server link bandwidth. From those budgets, plus switch limits such as stage count, hash-function count, and expected packet rate, the control agent computes the maximum number of register arrays and the maximum number of registers per array that a sketch may request. Users still write sketches in normal P4 style; Phantom hides which registers are physical and which are virtual.

Deployment works in two steps. First, Phantom marks virtual registers. If a sketch needs more arrays than the switch has physical arrays, the extra arrays become virtual. If an array is larger than physical per-stage capacity, the tail of that array becomes virtual. Second, the switch handler changes how those registers are updated. A packet that hashes to a physical register updates it normally. A packet that hashes to a virtual register generates a compact register update containing the index, an operation-specific variable, and a timestamp. For write-after-read sketches such as Elastic Sketch or UnivMon, the switch includes the operand needed later by the server-side comparison logic.

The switch handler then manages these updates carefully. It meters recirculation so the total rate stays below the configured bandwidth budget, reserves a bounded amount of TM buffer for queued updates, and emits an update to the server only when doing so will not violate the export-bandwidth budget. Otherwise the update keeps circulating inside the switch. Because individual updates are only 13 bytes, Phantom aggregates multiple updates from the same packet so the switch still handles them at line rate.

At the end of an epoch, the server handler combines two streams: physical-register dumps pushed from the switch, and virtual-register updates received during the epoch. It buffers virtual updates, sorts them by timestamp, and replays them against a shadow copy of the sketch. Write-only updates are applied directly; write-after-read updates perform the deferred read, compare, and write on the server. The final sketch state is the union of physical and reconstructed virtual registers.

## Evaluation

The implementation runs on a 64x100 Gbps Tofino switch, with the switch handler in P4 and the server handler in C++ over DPDK. The evaluation covers five representative sketches: Count-Min, Count Sketch, Elastic Sketch, FlowRadar, and UnivMon.

The first result is capacity. Under 1-3 Tbps traffic, Phantom can virtualize more than 10^5 registers with only 100 Gbps of recirculation budget and 5 MB of buffer, and it reaches O(10^6) virtual registers in the broader operating region emphasized by the paper. In the studied setup, 40 Gbps of switch-to-server bandwidth is already enough to avoid becoming the main bottleneck.

The second result is application accuracy. On CAIDA trace replay at 3 Tbps, using heavy hitter, global iceberg, and superspreader detection as end tasks, Phantom improves application-level accuracy by up to 86% over SwitchILP, SPEED, MTP, P4All, and NetVRM. The paper also compares Phantom with an offline optimum that gives sketches the same memory budget but no real-time constraints; the gap is below 1%, which is strong evidence that the virtualization mechanism itself is not the new source of error.

The third result is deployability. In a network-wide placement study, Phantom accepts up to 84% more sketches than the compared deployment systems because it expands each switch's effective register budget rather than only packing the original SRAM more tightly.

Finally, the overhead results are unusually strong. The switch handler uses less than 2% of measured switch resources, the server needs only a few tens of CPU cycles per register update and processes several million updates per second per core, Phantom reports no packet or update loss up to 3 Tbps in the out-of-band setting, and the forwarding path keeps full throughput while adding only 0.23 us of latency.

## Novelty & Impact

The paper's novelty is not a new sketch algorithm. It is a resource-virtualization layer for programmable-switch measurement. Prior work mostly shared scarce switch memory more intelligently; Phantom asks whether the switch already contains another isolated resource that can be converted into logical register capacity. That reframing is useful beyond this one prototype. It gives sketch designers a way to think in terms of update streams instead of fixed counters, and it gives systems builders a concrete recipe for co-designing switch pipelines with monitoring servers when ASIC SRAM is the hard bottleneck.

## Limitations

Phantom only helps when the operator is willing to spend some recirculation bandwidth, buffer memory, and export bandwidth on measurement. If those budgets are set tightly, or if traffic rates move into the paper's more extreme regime, Phantom intentionally reduces or disables virtualization rather than violate the configured limits.

The reliability story is also pragmatic rather than strong. The implementation assumes the common out-of-band collection model and argues that loss is near-zero under its bandwidth control, but it does not provide a robust end-to-end recovery protocol for in-band transfer or persistent server disconnection. The authors explicitly leave ACK-based durability and better loss handling to future work.

The evidence is also concentrated on one hardware target: a Tofino switch. The paper argues that recirculation is common across other programmable switches, but portability, operational complexity, and performance tradeoffs on those platforms are not yet measured. More fundamentally, Phantom is a measurement substrate, not a general way to extend arbitrary in-switch stateful programs; its server-side replay model fits epoch-based telemetry, not arbitrary low-latency control logic.

## Related Work

- _Moshref et al. (CoNEXT '15)_ - SCREAM dynamically allocates sketch SRAM, but it still stays within the switch's original physical capacity, whereas Phantom tries to create additional effective capacity.
- _Zhu et al. (NSDI '22)_ - NetVRM pools register memory across switches and sketches, while Phantom focuses on bypassing the per-switch ceiling by exploiting local recirculation hardware.
- _Namkung et al. (NSDI '22)_ - SketchLib makes sketch programming and composition practical on programmable switches, and Phantom can be read as addressing the lower-level memory bottleneck that still constrains those sketches.
- _Kim et al. (SIGCOMM '21)_ - RedPlane externalizes switch state for fault tolerance, whereas Phantom uses switch-server cooperation to increase sketch accuracy on today's hardware.

## My Notes

<!-- empty; left for the human reader -->

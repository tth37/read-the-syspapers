---
title: "Marlin: Enabling High-Throughput Congestion Control Testing in Large-Scale Networks"
oneline: "Marlin pairs an FPGA NIC with a programmable switch so custom congestion-control logic can drive 1.2 Tbps of faithful test traffic across 65,536 flows."
authors:
  - "Yanqing Chen"
  - "Li Wang"
  - "Jingzhi Wang"
  - "Songyue Liu"
  - "Keqiang He"
  - "Jian Wang"
  - "Xiaoliang Wang"
  - "Wanchun Dou"
  - "Guihai Chen"
  - "Chen Tian"
affiliations:
  - "State Key Laboratory for Novel Software Technology, Nanjing University, China"
  - "School of Electronic Science and Engineering, Nanjing University, China"
  - "Shanghai Jiao Tong University, China"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3717486"
tags:
  - networking
  - datacenter
  - smartnic
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Marlin splits congestion-control testing across two devices: an FPGA NIC runs per-flow CC logic and scheduling, while a programmable switch amplifies those decisions into bulk traffic. With that split, one 100 Gbps FPGA control link drives 1.2 Tbps of CC-shaped traffic through a single Tofino pipeline and supports up to 65,536 concurrent flows.

## Problem

Operators need to validate a chosen congestion-control algorithm and its parameters before deployment, not just simulate them. Simulators miss implementation bugs, chip behavior, and misconfigurations that only show up in real packet-processing pipelines, so a usable tester must do three things at once: generate traffic that follows CC behavior, let users customize the CC algorithm, and do so at datacenter-scale throughput.

Existing tools only satisfy two of those goals at a time. Software and FPGA testers are programmable but throughput-limited. Switch-based and commercial testers can generate large traffic volumes, but they do not expose a general framework for custom CC execution. Marlin starts from the observation that no single device combines enough programmability, packet-processing frequency, and aggregate throughput, so the tester must be split across heterogeneous hardware.

## Key Insight

The key insight is to decouple decision-making from packet generation. The FPGA NIC keeps per-flow state, runs the CC algorithm, handles timers, and decides which flow should send next; the programmable switch simply materializes those decisions as large `DATA` packets. Because the control packets are tiny, one 100 Gbps link carrying 64-byte scheduling messages at about 148.8 Mpps can keep twelve 100 Gbps data ports busy when the test MTU is 1024 bytes. The rest of the system is about making that handoff precise enough that the generated traffic still behaves like the intended CC algorithm.

## Design

Marlin uses five packet types. `SCHE` packets are 64-byte send instructions from the FPGA. `TEMP` packets circulate inside the switch at line rate as templates. When a `TEMP` packet dequeues metadata for its egress port, it becomes a real `DATA` packet. Returning `ACK` packets are compressed by the switch into 64-byte `INFO` packets and sent back to the FPGA. This creates a closed loop in which the switch never runs the CC algorithm itself; it only executes packet-generation and feedback-compaction primitives.

The switch dataplane has three roles: process inbound `DATA` and emit `ACK`, rewrite returning feedback into `INFO`, and maintain per-port queues of packet metadata that drive `TEMP`-to-`DATA` conversion. Those queues sit at egress, not ingress, so a template can only dequeue metadata for the port it actually reaches. That avoids misrouting and keeps the port budget manageable.

On the FPGA side, incoming `INFO` packets become events in per-port RX FIFOs. The CC module, written in Vivado HLS C++, reads per-flow state from BRAM, updates algorithm variables, and emits scheduling, retransmission, timer, and logging actions. The interface is intentionally narrow: a fixed intrinsic state block plus 64 bytes of user-defined CC state. The paper implements Reno, DCTCP, and DCQCN on top of that interface.

Two control mechanisms make the design run correctly at line rate. First, Marlin recycles active flows through per-port scheduling FIFOs: if a flow may still send, its event is reinserted as a rescheduling event instead of re-entering the full CC pipeline. That preserves fairness and prevents FIFO blowup by keeping only one active scheduling event per flow. Second, Marlin rate-limits both directions. RX timers pace `INFO` delivery so BRAM read-modify-write operations do not conflict, and TX timers pace `SCHE` emission so switch-side per-port queues do not overflow. With a 1518-byte MTU, the safe per-port rate is 8.127 Mpps.

This is why one Tofino pipeline allocates twelve 100 Gbps ports to test traffic and uses the remaining ports for the control and loopback path. In that layout, one 100 Gbps FPGA port drives 1.2 Tbps of test traffic.

## Evaluation

The evaluation is structured to show both correctness and scale. On a single DCTCP flow, Marlin's traced `cwnd` and `alpha` evolution under injected loss and ECN events matches ns-3's expected state transitions. Its scheduler also behaves as intended: multiple uncongested flows on one port share 100 Gbps fairly, while one flow per port across multiple ports lets each port independently reach 100 Gbps.

Under real congestion, the behavior still tracks the target algorithms. When flows from multiple ports compete for one 100 Gbps bottleneck, both DCTCP and DCQCN converge toward even sharing and reclaim bandwidth when other flows finish. The paper's strongest fidelity result compares Marlin's DCQCN implementation against Mellanox ConnectX-5 NICs in 2-cast-1 and 3-cast-1 RDMA Write experiments with a WebSearch traffic model; the FCT CDFs are close, suggesting Marlin is reproducing meaningful CC behavior rather than merely replaying traffic at high speed.

The headline number is the comprehensive test: Marlin sustains near-line-rate traffic on each port, aggregates to about 1.2 Tbps, and supports 65,536 concurrent flows. In that regime, DCQCN still beats DCTCP on short-flow FCT, which is exactly the sort of algorithm distinction a useful tester must preserve.

## Novelty & Impact

Marlin's novelty is architectural. It is not proposing a better congestion-control law; it is showing how to combine a programmable endpoint and a switch dataplane so a tester can simultaneously have CC fidelity, algorithm customizability, and Tbps-scale throughput. That makes it useful both as a pre-deployment harness for operators and as an experimental platform for CC researchers. The reusable idea is the switch-as-amplifier pattern, not any one specific algorithm module.

## Limitations

Marlin works best for algorithms whose sender-side per-packet logic fits the FPGA timing budget. The paper notes that more complex logic such as Cubic can still take about 100 clock cycles per packet after optimization, which is too slow for single-flow line rate without relaxing the workload. The evaluation is also narrow in algorithm coverage: the paper implements Reno, DCTCP, and DCQCN, and the strongest fidelity comparison is only for DCQCN.

The tester is deliberately stripped down to isolate congestion control. Because it does not model real payload semantics or much higher-layer protocol logic, it is less suitable for debugging application-stack interactions. Deployment cost is another real limitation: the design assumes a programmable switch, an FPGA NIC, and enough on-chip memory for per-flow state. The reported 65,536-flow limit already uses 72 Mb of BRAM, so further scaling remains hardware-dependent.

## Related Work

- _Chen et al. (NSDI '23)_ - Norma also uses programmable switches for high-throughput network load testing, but it does not synthesize congestion-control behavior or let users swap in custom CC logic.
- _Zhou et al. (CoNEXT '19)_ - HyperTester shows that programmable switches can drive high-performance traffic generation, whereas Marlin adds an FPGA-executed feedback loop so the generated traffic follows CC dynamics.
- _Arashloo et al. (NSDI '20)_ - Tonic makes transport protocols programmable on FPGA NICs, but it is an endpoint offload engine rather than a switch-amplified tester for Tbps-scale experiments.
- _Boo et al. (ISCA '23)_ - F4T demonstrates full-stack TCP acceleration on FPGA, while Marlin uses FPGA programmability mainly for per-flow control and relies on the switch for throughput scaling.

## My Notes

<!-- empty; left for the human reader -->

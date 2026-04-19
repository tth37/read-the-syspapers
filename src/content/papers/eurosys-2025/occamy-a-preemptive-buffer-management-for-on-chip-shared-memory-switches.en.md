---
title: "Occamy: A Preemptive Buffer Management for On-chip Shared-memory Switches"
oneline: "Occamy makes switch buffer management preemptive by reclaiming over-allocated queue space with head drops, so shallow on-chip buffers absorb bursts and isolate traffic better."
authors:
  - "Danfeng Shan"
  - "Yunguang Li"
  - "Jinchao Ma"
  - "Zhenxing Zhang"
  - "Zeyu Liang"
  - "Xinyu Wen"
  - "Hao Li"
  - "Wanchun Jiang"
  - "Nan Li"
  - "Fengyuan Ren"
affiliations:
  - "Xi'an Jiaotong University"
  - "Huawei"
  - "Central South University"
  - "Tsinghua University"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3717495"
code_url: "https://github.com/ants-xjtu/Occamy"
tags:
  - networking
  - datacenter
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Occamy keeps DT-like admission but makes shared-buffer management preemptive by head-dropping packets from over-allocated queues with spare on-chip metadata bandwidth. That improves burst absorption by up to 57% and average query completion time by up to 55%.

## Problem

Modern datacenter switches keep packet buffers on chip so 25.6 Tbps to 51.2 Tbps fabrics can access them at line rate, but buffer size scales much more slowly than bandwidth. The paper notes that buffer per unit bandwidth has shrunk by about 4x over the last decade even as incasts, low-latency disaggregation RPCs, and distributed training all demand more burst tolerance.

Commodity chips mostly rely on Dynamic Threshold (DT), which caps each queue by a threshold derived from current free buffer. DT is simple, but non-preemptive: once a packet is admitted, the switch can only wait for that queue to drain. That forces some free-buffer reservation and still fails when traffic shifts quickly; in simulation, DT can drop packets with only about 66% buffer utilization at the 99th percentile.

The practical symptom is buffer choking. On a Huawei CE6865, low-priority background traffic can increase high-priority incast query completion time by up to 8x, and a separate inter-port setup still causes up to 2x degradation, because a slow-draining queue keeps excess buffer while newly bursty traffic drops before it receives its fair share.

## Key Insight

Occamy's key claim is that preemption is feasible again on modern shared-memory switches because expelling a packet is mostly a metadata operation. In the common cell-based design, the switch removes a packet descriptor and returns cell pointers to the free list; it does not need to reread payload SRAM.

That reframes the problem. Instead of inventing a smarter admission rule, Occamy makes expulsion simple enough to coexist with the existing traffic manager: admission never waits for expulsion, and expulsion trims all over-allocated queues in round-robin order rather than tracking the longest queue in real time.

## Design

Occamy keeps DT for packet admission, but raises `alpha` so the switch reserves only a small free fraction for newly active traffic. This preserves existing admission logic while depending on fast reclamation instead of large static headroom.

The reactive component runs at egress. Any queue whose length exceeds the current threshold `T(t)` is marked over-allocated in a bitmap, and a round-robin arbiter selects one such queue for head-drop. This is the main departure from classical Pushout: Occamy avoids both enqueue-time blocking and longest-queue tracking.

The selected queue issues a head-drop request that competes with normal dequeue for descriptor and cell-pointer access. A fixed-priority arbiter always favors the output scheduler, so preemption only uses otherwise idle bandwidth. The executor removes the head packet by dequeuing its descriptor and returning its cell pointers to the free list. Because payload cells are untouched, the operation can be merged into the existing dequeue pipeline. The paper recommends `alpha = 8`.

## Evaluation

The feasibility results are strong enough to support the mechanism. The Verilog implementation of selector, arbiter, and executor costs about 1,300 LUTs, about 50 flip-flops, less than 0.03 mm^2 of ASIC area, and about 1 mW. The timing report implies one expulsion every two cycles at 1 GHz.

The performance story is consistent. On a Tofino P4 prototype, Occamy absorbs about 57% larger bursts than DT at `alpha = 4`. On the DPDK software switch, it lowers average QCT by up to 55% versus DT and 42% versus ABM while keeping background-flow FCT comparable; in the buffer-choking setup, background traffic can inflate DT's average QCT by up to 6.6x and p99 QCT by up to 60x, whereas Occamy stays close to Pushout. In 128-host leaf-spine simulations, it reduces average QCT slowdown by up to 44% versus DT under web-search traffic and still improves query QCT by up to 33% with all-to-all and 48% with all-reduce.

## Novelty & Impact

The contribution is not a smarter threshold formula but a practical preemptive architecture for commodity-style shared-memory switches. For switch designers, the value is the small hardware sketch; for operators, the paper explains why admission tuning alone cannot fully solve microburst absorption or isolation once buffers become too shallow relative to link speed.

## Limitations

The paper does not implement the full design inside a production ASIC traffic manager. The P4 prototype cannot realize the whole selector and fixed-priority arbiter, and the DPDK switch is only an emulation. The gains also depend on redundant memory bandwidth being available; the paper argues this is common and reports about 38% median free memory bandwidth even at 90% simulated load, but the advantage shrinks near the full-bisection worst case. Finally, `alpha = 8` is recommended empirically rather than from a deployment-independent rule.

## Related Work

- _Fan et al. (GLOBECOM '99)_ - Dynamic Threshold is the admission-only baseline Occamy deliberately keeps for packet admission while replacing DT's passive waiting with active reclamation.
- _Shan et al. (INFOCOM '15)_ - EDT improves DT's burst absorption within the non-preemptive model, whereas Occamy argues that the model itself is the bottleneck.
- _Addanki et al. (SIGCOMM '22)_ - ABM improves performance isolation by accounting for drain time, but it still relies on natural queue drain and therefore cannot fully eliminate buffer choking.
- _Wei et al. (GLOBECOM '91)_ - Classical pushout policies established the optimality of evicting buffered packets; Occamy is the hardware-conscious adaptation that drops from over-allocated queues without longest-queue tracking or enqueue-time blocking.

## My Notes

<!-- empty; left for the human reader -->

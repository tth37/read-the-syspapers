---
title: "Fork: A Dual Congestion Control Loop for Small and Large Flows in Datacenters"
oneline: "Fork splits datacenter transport: <=100 KB flows use a sender-driven high-priority loop, large flows use receiver credits, and ECN pressure is shifted to elephants."
authors:
  - "Yuan Liu"
  - "Wenxin Li"
  - "Yulong Li"
  - "Lide Suo"
  - "Xuan Gao"
  - "Xin Xie"
  - "Sheng Chen"
  - "Ziqi Fan"
  - "Wenyu Qu"
  - "Guyue Liu"
affiliations:
  - "Tianjin Key Laboratory of Advanced Networking, Tianjin University"
  - "Huaxiahaorui Technology (Tianjin) Co., Ltd."
  - "Peking University"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696101"
tags:
  - networking
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Fork argues that datacenter transports should stop using one feedback loop for both mice and elephants. It runs <=100 KB flows in a sender-driven high-priority loop that shares congestion history across destination-based flow groups, while >100 KB flows wait for receiver credits in a lower-priority loop whose ECN signals are adjusted to absorb pressure caused by elephants. On the paper's 100 Gbps testbed and leaf-spine simulations, that separation cuts small-flow FCT sharply without worsening large-flow completion times.

## Problem

The paper starts from an empirical point that many DCN papers blur together: heavy-tailed workloads contain mostly small flows by count, but most bytes come from large flows. Across the five workloads the authors study, 89.77%-99.57% of bytes come from flows larger than 100 KB, yet the average small flow still finishes within at most 3 RTTs on an unloaded 100 Gbps network, while large flows need 13.3-178.4 RTTs. That asymmetry means one extra RTT is catastrophic for mice but often negligible for elephants.

Prior transports do not respect that difference. Sender-driven reactive designs such as DCTCP couple both flow classes to the same ECN feedback. Receiver-driven proactive designs such as Homa and Aeolus couple them through the same credit machinery, and in Homa's case also let every new flow inject 1 BDP of unscheduled traffic in the first RTT. The consequence is diagnostic ambiguity: when a small flow sees queueing, it cannot tell whether it is colliding with another small flow or paying for a large one, so it slows down even when the right answer would be to keep mice fast and push elephants back.

The paper also rules out two obvious alternatives. Pure priority scheduling, even with pFabric-like SRPT approximations, still shares switch buffers and a single control loop, so congestion feedback remains entangled. Statically splitting switch buffers between high- and low-priority queues decouples them too rigidly and wastes capacity when one class is idle or bursts.

## Key Insight

Fork's core claim is that small and large flows should share the network fabric but not the congestion-control loop. Small flows need immediate sender-side action, because receiver scheduling costs an extra RTT they cannot afford. Large flows can tolerate that RTT and are a better fit for receiver-side control, because credits can meter their rate smoothly after startup.

That separation only works if the two loops still cooperate. Fork therefore preserves two invariants. First, mice always transmit in the highest priority queue and should behave almost as if elephants were absent. Second, elephants should not starve; they should expand to fill whatever capacity mice leave unused. The novel part is the glue between those invariants: share recent congestion history across many small flows so new mice do not start blind, and reinterpret ECN seen by mice as elephant-induced congestion when active large flows are present so elephants, not mice, absorb the slowdown.

## Design

Fork classifies flows at start time using a 100 KB threshold. Small flows enter the small-flow control loop, or SCP. SCP groups flows by destination, based on the observation that many concurrent flows between the same sender and receiver will experience similar path congestion. Each group carries one shared congestion window, so a new small flow inherits the current sending rate instead of probing from scratch.

SCP updates that group window per ACK rather than per RTT. The receiver ACKs every packet and echoes ECN marks. The sender then looks at two consecutive ECN-echo bits as a four-state machine: `00` and `10` increase `cwnd` by 1, `01` decreases by 1 and initializes a congestion counter `alpha`, and `11` increments `alpha` and cuts the window more aggressively by `alpha`. The point is to react at mouse timescales while still using more than a single bit of transient queue information. Within a group, Fork assigns window space by SRPT so the smallest remaining flow goes first.

Large flows enter the large-flow control loop, or LCP, which is receiver-driven in the style of Homa but changes both startup and control law. A new large flow sends a request, not 1 BDP of data, and waits for credits. The receiver maintains granted credits `GC` and updates them per arriving packet: if no large-flow congestion event is detected, `GC` increases by `1/GC`; if a congestion event is detected, `GC` drops by `1/2`. That gives additive increase and multiplicative decrease over a receiver credit budget.

The key mechanism is congestion diagnosis plus ECN migration. When an ECN-marked packet arrives from a large flow, the congestion is obviously attributed to elephants. When it arrives from a small flow, the receiver asks whether any large flows are active and whether the large-flow credit budget is already at its minimum. If elephants are active and still have room to slow down, the receiver suppresses the ECN echo back to the small-flow sender and instead counts that mark against the large-flow side, forcing `GC` down. In effect, Fork converts queueing observed by mice into a throttle on elephants whenever the elephants are the plausible cause.

The implementation is host-only: about 2200 lines on DPDK. Switches only need ECN and strict priority queues, both already present in commodity gear.

## Evaluation

The strongest part of the evaluation is that it uses both an 8-server 100 Gbps testbed and larger leaf-spine simulations over five realistic heavy-tailed workloads: Web Server, Cache Follower, Web Search, Facebook Hadoop, and RPC Read. Those workloads clearly exercise the paper's target bottleneck, namely startup bursts and mixed mice-elephant contention.

On the real testbed, Fork beats both Homa and Aeolus on small-flow latency across all workloads. Relative to Homa, it cuts average small-flow FCT by 27.5%-65.1% and tail FCT by up to 97.9%; relative to Aeolus, the average reduction is 33.1%-67.7% and the tail reduction reaches 82.9%. At the same time, average large-flow FCT also improves by 5.3%-36.3% over Homa and 5.7%-36.0% over Aeolus. The paper also reports far fewer drops: 42.9%-83.9% fewer than Homa and 98.2%-99.8% fewer than Aeolus in three representative workloads.

The simulations broaden the regime. Against Homa, Aeolus, and dcPIM, Fork reduces average small-flow FCT by up to 81.4%, 67.3%, and 66.3%, with tail reductions up to 99.9%, 67.6%, and 90.1%, respectively. Large-flow average FCT also improves in most cases, by up to 35.9% over Homa, 50.4% over Aeolus, and 40.1% over dcPIM. Queue occupancy data supports the claimed mechanism: average queue lengths are similar to Homa and Aeolus, but maximum queue length drops to 239 KB, 33.6% below Homa and 10.5% below Aeolus in the highlighted comparison.

The fairness story is good but not perfect. The baselines are credible and the authors use their published simulators, but the cross-simulator comparison is inherently less airtight than a single common codebase, and Aeolus is evaluated with Homa's overcommitment degree set to 2 rather than the value 6 used in the Aeolus paper. The authors acknowledge that this choice affects drop behavior. Even so, the consistency between testbed and simulation makes the central claim believable.

## Novelty & Impact

Fork's novelty is not merely using two priorities. The paper's real contribution is to decouple mice and elephant control loops while keeping them complementary rather than isolated. The destination-grouped ACK clocking in SCP addresses the startup problem that usually kills sender-side control for tiny flows, and the ECN-migration plus AIMD-credit logic in LCP gives the large-flow loop a concrete way to yield to mice without leaving the link empty.

That makes Fork relevant to researchers building the next generation of datacenter transport, especially those deciding between purely receiver-driven designs and ECN-reactive sender loops. The paper is likely to be cited as a clean argument that mixed workloads deserve structurally different control paths rather than a single compromise algorithm.

## Limitations

Fork assumes flow size is known in advance so it can classify at arrival time. The paper points to workloads like machine learning and Hadoop, and to separate flow-size estimation work, but that assumption is still a real deployment constraint for interactive or user-driven services.

The design also relies on a fixed 100 KB threshold and on the claim that small flows are the latency-sensitive class. The discussion section explicitly notes counterexamples such as real-time media, where a large flow can still be delay-sensitive. Likewise, if the threshold rises too far above 2 BDP, the SCP loop begins to absorb too many large flows and performance degrades.

Finally, the operational evidence is still limited. The prototype runs on an 8-node testbed, much of the scale argument comes from simulation, and the paper itself notes open issues around discrete arrivals, fluctuating ECN states under asymmetric paths, and tuning the timeout used to preserve congestion history for inactive flow groups.

## Related Work

- _Montazeri et al. (SIGCOMM '18)_ - Homa is the closest receiver-driven baseline, but it still couples mice and elephants through one credit loop and sends unscheduled traffic in the first RTT.
- _Hu et al. (SIGCOMM '20)_ - Aeolus tries to make Homa's first RTT safer by selectively dropping unscheduled packets, whereas Fork instead eliminates unscheduled elephant data and moves congestion pressure via ECN migration.
- _Cai et al. (SIGCOMM '22)_ - dcPIM is another proactive receiver-coordinated transport, but it still computes one shared schedule rather than giving mice and elephants distinct control loops.
- _Alizadeh et al. (SIGCOMM '10)_ - DCTCP is the canonical ECN-reactive sender design that motivates Fork's argument that a single feedback signal should not govern both small and large flows.

## My Notes

<!-- empty; left for the human reader -->

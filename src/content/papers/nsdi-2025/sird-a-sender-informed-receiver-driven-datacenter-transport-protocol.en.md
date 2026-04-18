---
title: "SIRD: A Sender-Informed, Receiver-Driven Datacenter Transport Protocol"
oneline: "SIRD keeps receiver-driven scheduling for exclusive downlinks, but uses sender and ECN feedback to ration credits on shared links and keep queues small."
authors:
  - "Konstantinos Prasopoulos"
  - "Ryan Kosta"
  - "Edouard Bugnion"
  - "Marios Kogias"
affiliations:
  - "EPFL"
  - "UCSD"
  - "Imperial College London"
conference: nsdi-2025
category: datacenter-networking-and-transport
code_url: "https://github.com/epfl-dcsl/SIRD-Caladan-Impl"
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

SIRD argues that receiver-driven transport should not treat every bottleneck the same. Receivers should explicitly schedule exclusive downlinks, but shared links such as sender uplinks and the fabric core should be controlled with reactive feedback. That asymmetric design lets SIRD keep 100 Gbps links busy with much less overcommitment and substantially less buffering than prior receiver-driven protocols.

## Problem

The paper starts from a hardware trend: datacenter link speeds keep rising, but switch SRAM per unit of bisection bandwidth is falling. Congestion control therefore has less buffer to hide control-loop lag, yet applications still want both high throughput and very low latency. Sender-driven schemes such as DCTCP and Swift react after congestion appears, which costs round trips and makes it hard to express message-level scheduling. Receiver-driven protocols improve this situation at receiver downlinks because one receiver owns that link and can pace arrivals precisely with credits.

The trouble is that not all bottlenecks are exclusive. Sender uplinks and core links are shared by multiple receivers. If receivers independently send credits to the same sender, that sender becomes congested and accumulates unusable credit; if several receivers pull through the same core bottleneck, their schedules interfere there as well. Existing receiver-driven designs each pay for this in a different way: Homa overcommits the downlink and relies on priorities, dcPIM inserts matching rounds before larger messages can start, and ExpressPass pushes complexity into switch configuration and path symmetry. The paper's target is to keep the receiver-driven benefits for incast while handling shared-link conflicts without either high queueing or heavyweight in-network support.

## Key Insight

The durable idea is to separate link management by ownership. A link with a single owner can be scheduled proactively, while a link shared across receivers should be handled by reactive control. In SIRD, the receiver still decides which sender to pull from next, but it does so with fresh information about whether that sender and the network path are currently congested.

That changes overcommitment from a blind statistical hedge into an informed one. Instead of handing every active sender enough credit to potentially fill the downlink, the receiver caps each sender with a per-sender bucket whose size shrinks when feedback says the sender uplink or core path is under pressure. Credit therefore flows toward senders that can consume it immediately, which keeps utilization high while sharply reducing the standing queues that prior receiver-driven schemes tolerate to stay work-conserving.

## Design

SIRD is an RPC-oriented transport layered over UDP/IP with ECN enabled in the network. It defines two packet types. `DATA` carries message payload and may be scheduled or unscheduled. `CREDIT` flows from receiver to sender and authorizes transmission of scheduled data. Messages larger than a configurable `UnschT` threshold begin by sending a zero-length `DATA` packet to request credit; smaller messages may send an initial unscheduled prefix of up to `min(BDP, msg_size)` bytes so they do not pay an extra RTT before making progress.

Credit management has two levels. Each receiver keeps a global bucket `B` that bounds total credited-but-not-yet-received bytes, and a per-sender bucket that bounds how much of that total any single sender may hold. The global bucket controls downlink overcommitment. The per-sender bucket is where SIRD's sender-informed design lives: it is set to the minimum of a sender-side congestion estimate and a network-side congestion estimate, each maintained by its own AIMD loop.

The sender-side signal is a `sird.csn` bit carried back in `DATA` packets. A sender sets this bit when accumulated credit from all receivers exceeds a threshold `SThr`, meaning receivers are collectively giving it more credit than it can currently consume. The network-side signal is ordinary ECN marking on the returning data packets. Each receiver updates one AIMD controller from `sird.csn` and another from ECN, then uses the more conservative result to size that sender's credit bucket. The paper's steady-state analysis shows that `B >= BDP + SThr` is enough to preserve full downlink utilization even with arbitrarily many congested senders under fair sharing; in practice they use `B = 1.5 x BDP` and `SThr = 0.5 x BDP`.

Two more pieces matter. First, receivers pace credits slightly below line rate, which keeps scheduled traffic from building a persistent queue even within the `B - BDP` bound. Second, scheduling policy stays at the edges: the receiver can pick senders in round-robin or approximate SRPT order, while the sender also schedules among active receivers. Because SIRD aims to keep the fabric nearly empty, it does not need the switch fabric itself to enforce message priorities, though the design can optionally benefit from two priority levels for credit and small unscheduled packets.

## Evaluation

The implementation result is meaningful on its own. SIRD is implemented in about 4300 lines on top of Caladan, and on CloudLab nodes with 100 Gbps ConnectX-6 DX NICs it sustains line-rate-class operation with an unloaded RTT around 18 us. In a six-sender incast, saturated downlinks add only a few microseconds to 8-byte request latency, whereas the paper reports kernel TCP Cubic above 1 ms median in the same experiment. With 500 KB requests, receiver-side SRPT keeps latency near unloaded levels while still reaching 96 Gbps, showing that credit pacing and message-aware scheduling work in software.

The sender-informed mechanism is tested with an outcast experiment: one sender transmits 10 MB messages to three receivers whose demand starts at different times. Without sender feedback, credit accumulation at the sender keeps growing as new receivers join. With `SThr = 0.5 x BDP`, the receivers converge to a regime where sender-held credit stays around the threshold and excess credit remains at receivers, ready to be redirected to uncongested senders.

The broader comparison comes from ns-2 simulations over a 144-host leaf-spine topology across balanced, core-bottleneck, and incast configurations, using three workloads with mean message sizes of 3 KB, 125 KB, and 2.5 MB. Against DCTCP, Swift, Homa, ExpressPass, and dcPIM, SIRD is the only design the authors claim stays near the Pareto frontier on utilization, queueing, and slowdown at once. The headline numbers are strong: 12x less peak queueing than Homa with competitive utilization and latency; versus dcPIM, 9% higher goodput, 43% lower peak queueing, and 46% lower slowdown; versus ExpressPass, 10x lower slowdown and 26% higher goodput. Even under full fabric saturation, SIRD's ToR queueing tops out at 0.8 MB in receiver-bottleneck cases and 2.3 MB in core-bottleneck cases, which the paper maps to 8% and 23% of a 3.13 MB/Tbps switch-buffer budget. The evaluation supports the paper's central claim, but it does so partly under idealized simulation assumptions such as infinite switch buffers and no packet drops except the intentional credit drops in ExpressPass.

## Novelty & Impact

Relative to _Montazeri et al. (SIGCOMM '18)_, SIRD keeps the receiver-driven model but replaces Homa's controlled overcommitment with sender-informed overcommitment, so utilization no longer depends on deliberately creating large inbound pressure and then escaping it with switch priorities. Relative to _Cai et al. (SIGCOMM '22)_, it removes dcPIM's semi-synchronous sender-receiver matching and lets large messages start immediately while adapting online. Relative to _Cho et al. (SIGCOMM '17)_, it tackles shared-link congestion end to end rather than via hop-by-hop switch behavior.

That combination makes SIRD more than a small protocol tweak. The paper offers a design rule for receiver-driven transport under modern ASIC constraints: keep scheduling where ownership is singular, and turn shared resources into explicit feedback channels. If future datacenter operators want Homa-like latency without Homa's buffering and priority assumptions, SIRD is a credible blueprint.

## Limitations

SIRD depends on several deployment assumptions. Message sizes must be known in advance or streams must be chunked into message-sized units, ECN must be configured across the network, and the protocol assumes fine-grained load balancing via random UDP source ports. Those are reasonable in some RPC fabrics, but they narrow the set of drop-in deployments.

The design also gives up some optimality to stay stable and deployable. Compared with Homa, SIRD only approximates SRPT because part of each sender uplink remains fair-shared across receivers and because per-sender buckets are adjusted equitably when a sender is congested. The paper reports that in the balanced configuration SIRD's 99th-percentile slowdown for medium-sized group-C messages is 1.85x and 2.68x higher than Homa's at 50% and 70% load respectively. On the implementation side, the authors avoid very small `SThr` values in software because batched credit arrivals could trigger spurious congestion marking.

The evaluation also leaves open questions. The large-scale results use infinite-buffer switches to study protocol behavior without drop artifacts, so real hardware interactions with shallow finite buffers are not directly measured there. Homa's simulator also lacks its incast optimization, and the paper notes that some baseline behavior would differ under two-way RPC workloads. Those caveats do not invalidate the results, but they do mean the comparison is closer to a principled design-space study than to a literal apples-to-apples deployment forecast.

## Related Work

- _Montazeri et al. (SIGCOMM '18)_ - Homa is the closest receiver-driven baseline, using controlled overcommitment and network priorities to approximate SRPT; SIRD keeps receiver scheduling but reduces the queueing cost of staying work-conserving.
- _Cai et al. (SIGCOMM '22)_ - dcPIM coordinates shared sender uplinks with explicit sender-receiver matching rounds, whereas SIRD replaces pre-transmission matching with continuous feedback and per-sender credit caps.
- _Cho et al. (SIGCOMM '17)_ - ExpressPass manages congestion hop by hop by throttling credits in switches; SIRD accepts a small amount of queueing to avoid specialized switch configuration and path-symmetry requirements.
- _Gao et al. (CoNEXT '15)_ - pHost exposed the unresponsive-sender problem in receiver-driven transport; SIRD generalizes that issue into explicit sender congestion notification plus AIMD-based reallocation.

## My Notes

<!-- empty; left for the human reader -->

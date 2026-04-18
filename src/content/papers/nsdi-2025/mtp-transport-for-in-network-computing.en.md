---
title: "MTP: Transport for In-Network Computing"
oneline: "MTP moves transport to messages and pathlets, so in-network offloads can mutate, intercept, reorder, and delay traffic without breaking reliability or congestion control."
authors:
  - "Tao Ji"
  - "Rohan Vardekar"
  - "Balajee Vamanan"
  - "Brent E. Stephens"
  - "Aditya Akella"
affiliations:
  - "UT Austin"
  - "University of Illinois Chicago"
  - "Google and University of Utah"
conference: nsdi-2025
tags:
  - networking
  - smartnic
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

MTP is the first transport designed around in-network computing rather than around end hosts alone. By making messages and pathlets explicit transport objects, it keeps reliability and congestion control correct even when offloads mutate, intercept, reorder, or delay application traffic.

## Problem

The paper targets on-path L7 offloads such as caches, load balancers, transaction accelerators, and in-network aggregators running on switches or SmartNICs. These devices can change a message's contents and size, suppress a message entirely, reorder messages across replicas, or hold a message for a long and unpredictable time while processing it. Those behaviors are not corner cases for INC; they are the point of INC.

That breaks today's transports in different ways. TCP variants and RDMA rely on continuous byte or packet sequence spaces, so a size-changing mutation or an intercept makes ACK accounting ambiguous, while reordering looks like loss. Homa already works at message granularity, but its receiver asks for missing byte ranges, which no longer map cleanly back to the original message after mutation. Congestion control also becomes unreliable, because delay can now come from a slow offload rather than the fabric, and offload hardware usually cannot afford to host a full transport stack with large buffers and per-flow state. The paper's goal is therefore broader than "one more transport": it wants a transport contract that INC platforms can implement without special transport-specific state on every device.

## Key Insight

The durable idea is that transport should align with the unit that offloads actually manipulate: messages. Once the protocol names and tracks messages directly, mutation, intercept, and reordering stop being exceptional cases and become normal operations over message descriptors.

The second insight is to treat each offload instance, or a fate-sharing group of replicated instances, as a `pathlet`. Pathlets can explicitly tell the sender when a message has arrived, when it has left, and how congested they are. That lets MTP separate "the message is delayed inside an offload" from "the message was probably lost in the network," which is the distinction legacy transports cannot make.

## Design

MTP is connection-based and assumes the network can provide pathlet discovery plus source-routed forwarding through a selected chain of pathlets. When an application posts a message descriptor, MTP assigns a message number, chooses pathlets, segments the payload, and sends packets carrying the message number, segment number, total message length, and a virtual-channel id. The receiver is intentionally passive: it records which segments arrived and sends an end-to-end ACK only when the full message is present. Reordering therefore does not trigger gap processing. Mutation is legal because a pathlet can change message length and segment count; intercept is legal because a pathlet can terminate a message by emitting the end-to-end ACK.

Reliability is sender-driven. Instead of asking the receiver for missing byte ranges, the sender retransmits an entire message on timeout. Pathlets refine this with `PRX` ACKs when a message has been fully buffered and `PTX` ACKs when it has been transmitted onward. The sender can therefore use a short fabric RTO between endpoints and a looser pathlet RTO while the message sits inside an offload. To preserve exactly-once delivery without an unbounded reorder window, MTP uses a fixed set of virtual channels: each inflight message occupies one channel, and the receiver remembers only the last completed message number for that channel.

Congestion control is also pathlet-aware. Each pathlet maps its queue occupancy to an 8-bit feedback value, the sender runs a Swift-inspired controller per pathlet plus one for link congestion, and proactive pathlet switching moves later messages away from pathlets that stay hot. Offloads only need to emit ACKs and congestion feedback; they do not maintain transport sequence spaces.

## Evaluation

The DPDK prototype is tested with NetCache, controlled middleboxes, and ns-3. In the 25 Gbps NetCache setup, the MTP client sustains over 95% of peak system throughput, while a UDP client with timeout-and-retry falls behind once offered load reaches 80%; the paper summarizes that end-to-end result as over 15% higher throughput for MTP. With heavy-tailed offload delay plus 1% fabric drops, `PRX` and `PTX` ACKs create a broad `400-1050 us` fabric-RTO region where MTP still delivers over 90% goodput with zero false positives; a single end-to-end RTO has no such safe region. For pathlet congestion, early multi-bit feedback converges to fair shares where ECN-style feedback does not, and proactive pathlet switching reaches about 98% of the combined average throughput of two asymmetric pathlets, versus about 90% for ECMP. Overheads are measurable but modest: with 4 KB messages and two pathlets, ACK traffic consumes 6% of link bandwidth, and the sender-side MTP stack spends about 55% of two cores' cycles in its RX routine while still saturating 25 Gbps. In ns-3 packet-spraying experiments, MTP cuts TCP tail completion time by about 65% and largely eliminates the 10-15% retransmission rate TCP suffers when it mistakes reordering for drops.

## Novelty & Impact

The novelty is a transport contract for INC, not a narrowly optimized transport algorithm. The paper combines message-oriented reliability, pathlet-oriented congestion control, and a low-state offload interface into one design. That is useful both to transport researchers and to builders of caches, aggregators, and SmartNIC/switch offloads who currently hand-roll transport workarounds.

## Limitations

MTP assumes explicit message boundaries, service/pathlet discovery, and source routing. It is designed mainly for full-buffering pathlets; native streaming and branching or multicast pathlets are left out. Security is also unresolved because INC conflicts directly with end-to-end encrypted transports. ACK overhead grows with message rate and pathlet count, and the evaluation is still a prototype plus simulation rather than a production deployment across many offload types. The appendix also suggests fairness degrades once mutation changes message size by more than about 20%, so the DCTCP-derived controller is not final.

## Related Work

- _Montazeri et al. (SIGCOMM '18)_ - `Homa` is already message-oriented, but its loss recovery assumes byte ranges remain meaningful after transmission; `MTP` is built for cases where an offload can change the message itself.
- _Sapio et al. (NSDI '21)_ - `SwitchML` demonstrates the upside of in-network aggregation, while `MTP` tries to supply the general-purpose transport substrate that such offloads currently reimplement in ad hoc ways.
- _Liu et al. (ASPLOS '23)_ - `NetReduce` keeps aggregation transparent when message size does not change, whereas `MTP` explicitly supports size-changing mutation, intercept, and reordering.
- _Qureshi et al. (SIGCOMM '22)_ - `PLB` redirects traffic away from congested paths; `MTP` adapts that spirit to congested offload instances through proactive pathlet switching.

## My Notes

<!-- empty; left for the human reader -->

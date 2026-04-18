---
title: "HA/TCP: A Reliable and Scalable Framework for TCP Network Functions"
oneline: "HA/TCP uses replicated sockets and in-stack traffic replication so endpointing TCP network functions can fail over or migrate without breaking connections."
authors:
  - "Haoyu Gu"
  - "Ali José Mashtizadeh"
  - "Bernard Wong"
affiliations:
  - "University of Waterloo"
conference: nsdi-2025
code_url: "https://github.com/rcslab/hatcp/"
tags:
  - networking
  - fault-tolerance
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HA/TCP embeds active replication into the TCP stack and exposes the result as replicated sockets, so endpointing layer-7 network functions can fail over or migrate without resetting live connections. Its key trick is to replicate each packet before local TCP processing, let the replica acknowledge receipt immediately, and only then let the primary advance; that keeps both replicas TCP-consistent while still supporting 100 Gbps-class throughput.

## Problem

Prior NF reliability systems mostly target layer-2/3 functions whose per-flow state is small and updated infrequently. That assumption breaks for endpointing layer-7 NFs such as SOCKS proxies, TCP splicers, and WAN accelerators. These systems terminate TCP, keep full transport control-block state, buffer payload inside socket queues, and often transform traffic before forwarding it. If such an NF fails, there is no fail-to-wire escape hatch: the downstream endpoint may no longer understand bypassed traffic, and the remote peers simply see broken connections.

Replicating only the application state is also not enough. A TCP acknowledgment only says that the peer TCP stack accepted bytes, not that the NF application finished consuming, rewriting, or forwarding them. If the primary acknowledges data too early and crashes, the sender may never retransmit bytes the replica has not yet processed. But delaying acknowledgments until the application finishes would inflate RTT, perturb congestion control, and reduce throughput. The paper therefore asks for a mechanism that preserves seamless failover for endpointing TCP NFs without pushing every packet through expensive remote state lookups or requiring client-side protocol changes.

## Key Insight

The paper's main claim is that the right replication boundary is inside the transport stack, not at an external state store and not at full application record/replay granularity. If the primary and replica observe the same packet stream and the same nondeterministic TCP-visible state transitions in the same order, then much of the NF's externally relevant behavior becomes deterministic.

HA/TCP packages that idea as a replicated socket abstraction. The primary waits only for a fast receipt acknowledgment from the replica, not for the replica to finish TCP processing or application execution. The replica can lag locally and mask that lag with a queue, as long as it preserves externally visible output determinism. This narrows the synchronization surface to traffic plus a few control variables, which is much cheaper than trying to replicate arbitrary application state on every packet.

## Design

HA/TCP extends the FreeBSD 13.1/F-Stack TCP stack. On the primary, an incoming packet is intercepted after checksum validation and TCP control-block lookup. HA/TCP queues the original mbuf, duplicates the packet, prepends a small HA/TCP header carrying metadata such as packet size and congestion-window updates, and sends the copy over a dedicated replication channel. Only after the replica acknowledges receipt does the primary release the queued original back into normal TCP processing.

The replication channel is deliberately an IP protocol rather than TCP or UDP. The authors argue that this avoids extra control-block lookups, locking, congestion control, and the TCP-over-TCP meltdown they saw in an earlier design. Because large receive offload (LRO) coalesces traffic into packets up to roughly 64 KiB, HA/TCP then combines shallow copying with IP fragmentation so it can both keep a local reference to the original packet chain and emit 9 KB fragments on the replica link without repeated deep copies. To avoid IP reassembly collisions at high rate, each replicated TCP connection gets a unique 32-bit ID and timestamp option. Packet loss on the replication path is handled indirectly: if the primary never gets replica acknowledgment, it withholds the client-side TCP acknowledgment and relies on the client to retransmit.

The replica immediately acknowledges replicated packets on the NIC thread, then queues them until its local TCP state is ready to accept them. That queue hides performance skew between primary and replica and lets HA/TCP preserve SACK state, timestamp monotonicity for PAWS, and in-order delivery conditions. HA/TCP also replicates listening sockets and the connection handshake: the primary forwards the SYN, its initial sequence number, and a timestamp offset; later it replicates the final ACK and initial congestion-window information. Around the transport path, HA/TCP uses CARP for leader election and failover and adds an "IP Clustering" mechanism based on distributed LACP so multiple nodes can share one IP/MAC for connection-level load balancing.

## Evaluation

The evaluation runs on dual-socket Xeon Gold 6342 servers with dual-ported 100 Gbps ConnectX-6 NICs, using a 1500-byte MTU toward clients and a 9000-byte MTU on the replication link. The first headline result is that HA/TCP can still saturate a 100 Gbps link with four connections. Its IP-clustering design also scales almost linearly to six nodes and finishes only 2% below ideal aggregate throughput.

Migration is the clearest systems win. HA/TCP completes migration in 38 us including network latency, with 22 us coming from communication latency and 16 us from local processing. The paper reports this is 2.4x faster than Prism and 1.7x faster than Capybara on the authors' comparison. For failover, the transport switchover after detection is only 13 us, although the user-visible interruption is dominated by CARP's configured 300 ms detection interval.

Steady-state overhead is modest but asymmetric. In iPerf3, receive-bound throughput falls by 3.4% because the primary's input path must wait on replica receipt before completing TCP processing; transmit-bound throughput falls by only 0.3% because the primary mostly tracks outgoing acknowledgments. In a latency benchmark with a 100 kQPS background workload, replication adds 11 us on average. The paper also estimates peak steady-state replication memory at about 875 KiB at 100 Gbps, derived from the replication link's bandwidth-delay product.

The application studies are more persuasive than the microbenchmarks. A WAN accelerator shows no statistically significant throughput loss and fails over all connections 132 us after failure detection. A SOCKS proxy loses 2% throughput and uses 29% more CPU on the primary, but its failover takes 84 ms after detection because the replica can lag by about 44 buffered requests. A distributed load balancer migrates 32 of 64 connections from one server to another, increasing aggregate throughput from 90.6 to 181.2 Gbps. Together these results support the central claim that continuous replication of TCP-visible state can be practical, though the evidence is confined to a low-loss LAN, one replica, and one software stack/NIC family.

## Novelty & Impact

Relative to prior NF reliability work, HA/TCP changes the unit of replication. It does not treat a layer-7 NF as "application state plus generic failover"; it treats the transport path itself as the object that must remain deterministic. That yields a reusable replicated-socket API rather than a one-off migration mechanism for a single proxy.

This is useful for builders of virtual appliances, proxies, and service-function chains that still terminate TCP in software. The paper's lasting contribution is both a mechanism and a design lesson: for endpointing NFs, the least ambiguous place to pay for high availability is before local TCP processing makes lost work invisible to the sender.

## Limitations

HA/TCP is not cheap in absolute terms. It assumes kernel modifications to FreeBSD/F-Stack, prefers a dedicated replication link, and assumes packet loss is rare enough between primary and replica that client retransmissions can repair gaps without noticeable harm. Those are reasonable engineering choices, but they reduce drop-in deployability.

The failover story is also split between internal and external latency. Once failure is detected, switchover is very fast; in deployment, however, CARP's detection delay dominates, and queue backlog on the replica can stretch recovery further, as the SOCKS experiment shows. The current prototype also does not yet combine IP clustering with replication, so the full "elastic and highly available" story still needs additional orchestration. Finally, the evaluation stays within a single low-latency environment and does not test how robust the approach is under harsher replica-link loss or wider-area placements.

## Related Work

- _Woo et al. (NSDI '18)_ - `S6` elastically scales stateful layer-2/3 network functions via remote/coalesced state, whereas `HA/TCP` must preserve full TCP and in-flight payload state for endpointing layer-7 NFs.
- _Sherry et al. (SIGCOMM '15)_ - `FTMB` uses rollback-recovery and replay for middleboxes; `HA/TCP` instead keeps replicas synchronized continuously inside the transport stack to enable much faster transparent takeover.
- _Hayakawa et al. (NSDI '21)_ - `Prism` migrates proxy connections with proxy-specific mechanisms, while `HA/TCP` turns migration plus failover into a reusable replicated-socket substrate and reports lower migration latency.
- _Choi et al. (APSys '23)_ - `Capybara` achieves fast live TCP migration with a library OS and custom stack, while `HA/TCP` targets production-style FreeBSD/F-Stack NFs and adds steady-state replication for failover, not only migration.

## My Notes

<!-- empty; left for the human reader -->

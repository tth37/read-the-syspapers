---
title: "DISC: Backpressure Mitigation in Multi-tier Applications with Distributed Shared Connection"
oneline: "DISC splits response metadata from final payload and lets backend datapaths send payload bytes on the client's original TCP/TLS connection, bypassing relay tiers."
authors:
  - "Brice Ekane"
  - "Djob Mvondo"
  - "Renaud Lachaize"
  - "Yérom-David Bromberg"
  - "Alain Tchana"
  - "Daniel Hagimont"
affiliations:
  - "Univ. Rennes, Inria, CNRS, IRISA, France"
  - "Univ. Grenoble Alpes, CNRS, Inria, Grenoble INP, LIG, 38000 Grenoble, France"
  - "IRIT, Université de Toulouse, CNRS, Toulouse INP, UT3 Toulouse, France"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - datacenter
  - networking
  - kernel
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

DISC attacks backpressure in multi-tier applications by treating a response as two different things: metadata that must still traverse the application chain, and final payload bytes that usually do not. It lets several tiers jointly act as endpoints of one TCP/TLS connection, so a backend-side datapath can transmit the payload directly on the client's original connection while frontends and intermediates still see the response headers and footers they need.

## Problem

The paper studies a common pattern in datacenter software: a client request enters a front end, passes through one or more intermediate services, and eventually reaches a backend that owns the data. In many applications, the backend's reply is already final data, such as an image, a mail body, or a database object. Yet those bytes still travel hop by hop back through every earlier tier. The result is backpressure: frontend and intermediate tiers burn CPU receiving and retransmitting payload they do not semantically modify, so their load grows with backend activity and they can saturate before the tier doing the useful work.

The authors show this directly on a 3-tier NGINX chain and on SpecWeb and SpecMail. As payload size grows, FE and IS CPU rise faster than BE CPU, which is the opposite of the scaling behavior operators want. Prior shortcuts based on connection handoff do not solve this cleanly. They mostly target 2-tier load-balancer/backend topologies, assume the same application protocol and API on both ends, and bypass the intermediary completely. That is too restrictive for real multi-tier applications, where response headers or footers may still matter to previous tiers and where a request path can mix HTTP, IMAP, SOAP, gRPC, and database protocols.

## Key Insight

DISC's core idea is that the system does not need full connection migration; it needs distributed send authority over one response stream. If the reply is decomposed into metadata and payload, then the metadata can continue along the normal backward chain while the large payload bypasses tiers that only relay it.

This yields a distributed shared connection. A frontend can temporarily delegate emission of a payload byte range to a backend datapath and then resume control later to send a footer or the next response. That preserves tier-local semantics without forcing the whole chain to adopt a single protocol or to give up visibility into the response.

## Design

DISC adds a DISC-PROT header above TCP and installs localized hooks in each tier. Request headers carry the tier position and a bitmap of which tiers agree to be bypassed; response headers carry whether the payload is bypassed, the payload size, an identifier for the buffered payload, and the backend address hosting the datapath. In the general case, the protocol can support shortcuts on arbitrary subchains, not just a single FE-BE pair.

The execution path has four important pieces. `feHook`, `isHook`, and `beHook` make the application-level changes. `kHook`, implemented as kernel hooks backed by BPF state, records connection metadata and rewrites sequence or acknowledgment numbers. `DP` on the backend buffers the payload and later emits raw packets on behalf of the frontend. `ackSender` forwards relevant ACK/SACK information from the frontend host to the backend datapath. In a shortcut, the backend sends only DISC and application headers up the chain, stores the payload in `DP`, and marks the response as bypassed. The frontend records the payload range in shared kernel state and remotely asks `DP` to transmit those bytes on the original client connection.

The hard part is keeping TCP semantics correct without modifying the Linux TCP stack. DISC therefore maintains a global sequence-number view across FE and BE transmissions. When `DP` is invoked, it gets the current global sequence state, emits payload bytes in that range, and later relies on `kHook` to translate subsequent FE packets so the client still sees one contiguous byte stream. Incoming ACKs, SACKs, and duplicate ACKs are intercepted at FE; acknowledgments for FE-originated bytes are translated back into FE's local numbering, while acknowledgments for bypassed payload are routed to `DP` so it can slide its window or retransmit. The paper explicitly argues that this remains compatible with keep-alive connections, piggybacking, pipelining, and TCP congestion control.

TLS support extends the same delegation model. DISC serializes the `wolfSSL` session on FE, imports it on `DP` so the backend can encrypt the bypassed payload in the same TLS session, and then returns the session to FE after transmission. The client remains unchanged; the practical cost is that TLS work moves from FE to BE while the bypass is active.

## Evaluation

The evaluation uses CloudLab and combines a controllable NGINX microbenchmark with SpecWeb, SpecMail, Train Ticket, and Social Media. The microbenchmark varies chain depth and payload sizes from 16 KB to 64 KB, which matches the paper's target failure mode: large final payloads relayed by tiers that do not transform them.

The CPU results are the clearest evidence. In a 4-tier `FE-IS1-IS2-BE` chain with 64 KB payloads, DISC reduces CPU by 63.4% on FE, 64.3% on `IS1`, and 60.4% on `IS2`, while increasing BE CPU by 98.8%. That shift is still a net win: cumulative CPU drops from 246% in vanilla to 145% with DISC, versus 208% for single-hop DSR. The same trend appears in the macrobenchmarks, where cumulative CPU falls by 41.5% on SpecWeb and 36.5% on SpecMail.

DISC also improves the scaling point of the system. In the `FE-BE` microbenchmark with 32 KB payloads and two cores per tier, vanilla reaches about 18 Kreq/s before latency rises, while DISC reaches 26 Kreq/s on the same resources, a 45% improvement, and then plateaus around 30 Kreq/s when the NIC saturates. Latency is nearly unchanged when no intermediate tier exists, which matches the paper's claim that DISC removes relaying work rather than round trips. As the chain gets deeper, tail latency improves sharply: with two intermediates, the 99.99th percentile drops from 4.803 s to 2.959 s, and with ten intermediates the paper reports a 5.71x reduction, from 8 s to 1.4 s. In Train Ticket, average latency falls from 3.57 s to 0.928 s and throughput rises from 635.8 to 889.2 req/s, showing that the mechanism still helps in a microservice setting.

Overall, the experiments support the central claim: DISC does not make the system cheaper by magic, it moves work to the tier that should own it and prevents useless payload forwarding from dominating FE and IS.

## Novelty & Impact

DISC differs from classic connection migration by sharing transmission responsibility instead of transferring full connection ownership. That is the key move that lets headers and footers keep following the application chain while payload bytes take a shorter return path. Compared with `Prism` and `CRAB`, DISC is not limited to a single load-balancer/backend shortcut; compared with QUIC-based direct-server-return designs such as `QDSR`, it keeps clients unchanged and tolerates heterogeneous application protocols inside the service chain.

The contribution is therefore more than an implementation trick. The paper packages a protocol, a TCP/TLS coordination mechanism, and an integration pattern that makes partial response-path bypass plausible for existing datacenter applications. Cloud providers or operators of managed multi-tier platforms are the most obvious adopters.

## Limitations

Deployment is still heavy. DISC must run on all servers participating in shortcuts, and it needs both application-level hooks and kernel-side packet interception. The paper is explicit that the design relies on IP spoofing, so it is practical for cloud providers or tightly managed infrastructure, not ordinary IaaS tenants.

The benefit is also workload-sensitive. DISC helps when a backend returns large final data and earlier tiers merely relay it. If intermediates transform the body, or if the payload is small, bypass opportunities narrow quickly. Train Ticket exposes this clearly: the gateway remains expensive because much of its cost comes from traffic shaping rather than payload forwarding.

Finally, DISC creates a more capable backend datapath. `DP` must buffer payload, handle ACK-driven retransmission, and absorb TLS work during bypass. The evaluation shows that this concentration is usually worthwhile, but it still means capacity planning shifts toward the backend side.

## Related Work

- _Hayakawa et al. (NSDI '21)_ - `Prism` removes relay cost between a proxy and a backend, whereas DISC supports arbitrary-depth chains and bypasses only payload bytes rather than the whole response path.
- _Kogias et al. (SoCC '20)_ - `CRAB` bypasses a load balancer without full regret, but it is still a 2-tier shortcut; DISC distributes transmission rights across multiple intermediary hops and mixed protocols.
- _Snoeren et al. (USITS '01)_ - Fine-grained failover uses connection migration, while DISC deliberately avoids full migration and instead shares send authority over one logical connection.
- _Wei et al. (USENIX ATC '24)_ - `QDSR` applies direct server return to QUIC-based load balancing, whereas DISC keeps clients unchanged and targets heterogeneous multi-tier service chains.

## My Notes

<!-- empty; left for the human reader -->

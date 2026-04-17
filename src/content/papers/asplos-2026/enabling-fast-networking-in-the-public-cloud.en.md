---
title: "Enabling Fast Networking in the Public Cloud"
oneline: "Machnet brings low-latency userspace networking to cloud VMs by targeting only portable vNIC features and using randomized RSS-based flow placement in a sidecar runtime."
authors:
  - "Alireza Sanaee"
  - "Vahab Jabrayilov"
  - "Ilias Marinos"
  - "Farbod Shahinfar"
  - "Divyanshu Saxena"
  - "Gianni Antichi"
  - "Kostis Kaffes"
affiliations:
  - "University of Cambridge and Huawei, Cambridge, United Kingdom"
  - "Columbia University, New York, USA"
  - "NVIDIA, London, United Kingdom"
  - "Politecnico di Milano, Milan, Italy"
  - "The University of Texas at Austin, Austin, USA"
  - "Queen Mary University of London, London, United Kingdom"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790158"
code_url: "https://github.com/microsoft/machnet"
tags:
  - networking
  - virtualization
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Machnet starts from the claim that public-cloud vNICs are their own platform, not a slightly worse bare-metal NIC. It defines a least-common-denominator vNIC model, builds a sidecar userspace stack around that model, and restores multi-core flow placement with a randomized RSS-based handshake called `RSS--`. The result is cloud-portable kernel-bypass networking with latency close to specialized systems and below Linux TCP in the paper's target workloads.

## Problem

The paper starts from a deployment mismatch. Existing userspace stacks such as eRPC or TAS assume features like flow steering, RSS-table control, deep RX queues, or DMA from application memory. Public-cloud tenants in VMs do not get that interface. Across Azure, AWS, and GCP, the authors find a far smaller common feature set: packet I/O, opaque RSS, one queue pair per core, and only `256` descriptors per queue.

The software model is also a poor fit for cloud applications. LibOS-style stacks often let one application own the NIC and expect one polling thread per queue. Real cloud VMs host multiple processes, high-level languages, and more threads than cores. The problem is therefore not just making packet I/O fast, but making low-latency userspace networking portable and usable for ordinary multi-process VM workloads.

## Key Insight

The paper's key claim is that the right abstraction is not "what a modern NIC can do" but "what every cloud vNIC reliably exposes." Once the stack is built around that LCD device model, the remaining problem is to recover enough structure on top of opaque RSS and shared-memory IPC to preserve low latency without privileged hardware control.

Two observations make this practical. First, the sidecar hop is small relative to cloud RTTs; the paper measures roughly `250 ns` one way through shared memory. Second, opaque RSS still preserves flow affinity even if the hash is hidden. Machnet exploits that by randomizing UDP port pairs during connection setup until packets land on the desired engine queues. Deterministic NIC control is replaced by probabilistic steering on the cold path, while the hot path stays shared-nothing.

## Design

Machnet has two components: a userspace sidecar that owns the NIC and a shim library that applications link against. Applications talk to the sidecar through isolated shared-memory channels with TX/RX queues and buffer references. The shim exposes a BSD-like API (`bind`, `listen`, `connect`, `send`, `recv`) so applications can replace only their networking layer.

On the wire, Machnet uses a reliable message-oriented transport over UDP plus a Machnet header. New flows go through slower cloud SDN control paths, so the system prefers connection reuse. It supports fragmentation, reassembly, selective acknowledgments, in-order delivery, messages up to `8 MB`, and multiple outstanding messages per flow.

The most original mechanism is `RSS--`. Machnet runs one busy-polling engine per core in a shared-nothing architecture, so each flow must hit the right engine at both endpoints. Because the NIC exposes only opaque RSS, Machnet repeatedly tries randomized SYN and SYN-ACK port pairs until one hashes to the intended queues. By decoupling Machnet's logical flow identity from the UDP four-tuple, the two directions can use different successful UDP port pairs and cut setup cost to about `25` packets for `4x4` engines and `55` for `8x8` at `95%` success probability. Around this core, the system makes pragmatic choices: DPDK instead of AF_XDP, blocking receive for oversubscribed VMs, and optional provider-specific offloads when extra features are exposed.

## Evaluation

The evaluation is persuasive because it tests both portability and real applications. Machnet runs on Azure, AWS, and GCP, plus several bare-metal NICs. In the basic echo benchmark on Azure, Machnet reaches `27/32/49 us` round-trip latency at median/`p99`/`p99.9` for `64 B` messages, versus Linux TCP's `62/79/118 us`. AWS and GCP show the same qualitative result for small messages. For `32 kB` messages, Machnet still beats Linux on Azure and EC2, but loses on GCP.

The macrobenchmarks show the design survives contact with real software. Porting Hashicorp's Go-based Raft implementation to Machnet yields `34%` lower median latency and `37%` lower `p99` than Linux TCP, with Machnet around `185 us` median and `625 us` at `p99`. On Mongoose, Machnet sustains roughly `68K` requests per second on Azure while keeping `p99` near `60-70 us`; Linux exceeds `4000 us` and struggles beyond `40K` RPS. For FASTER, Machnet reaches about `700K` RPS versus Linux TCP's `210K`, a `3.3x` throughput gain, while cutting `p99` latency from roughly `250 us` to `50 us`.

The microbenchmarks clarify the tradeoff. Machnet is close to eRPC on 64-byte latency, within `10%` at median and `p99`, but about `45%` below eRPC in large-message, large-window throughput. The point is not to beat every specialized stack on peak datapath throughput, but to recover most of the latency win while buying a deployment model cloud tenants can actually use.

## Novelty & Impact

Relative to _Kalia et al. (NSDI '19)_, Machnet's novelty is not a faster RPC fast path, but a reframing: public-cloud networking should be designed against an LCD vNIC model, not against bare-metal features tenants do not control. Relative to _Kaufmann et al. (EuroSys '19)_, it keeps the sidecar idea but adds a concrete answer to per-application placement under opaque RSS. Its impact is practical: researchers get a clearer statement of the real cloud hardware contract, and practitioners get evidence that Go services, web servers, and replicated stores can use kernel-bypass networking without turning the VM into an OS appliance.

## Limitations

The paper is candid that Machnet is not for every workload. It does not target RDMA-like highest-throughput regimes, and its data shows a clear throughput deficit versus eRPC once large windows and large messages dominate. The portable baseline also pays extra copies, which can erase its win for large messages on some clouds, as the `32 kB` GCP result shows. `RSS--` removes the missing-flow-steering problem from the hot path but not from the system: connection setup remains probabilistic and sub-millisecond rather than free. Machnet also offers socket-like APIs, not binary compatibility with unmodified sockets applications, and most experiments stay within one availability zone.

## Related Work

- _Kalia et al. (NSDI '19)_ — eRPC shows how far a libOS-style RPC stack can go with advanced NIC features, while Machnet asks what remains possible when those features are unavailable to cloud tenants.
- _Kaufmann et al. (EuroSys '19)_ — TAS also treats networking as an OS-side service, but depends on NIC control that Machnet excludes from its portable baseline and lacks explicit application-to-engine isolation.
- _Marty et al. (SOSP '19)_ — Snap shares the microkernel networking instinct, yet it assumes provider-controlled host infrastructure rather than the tenant-facing vNIC constraints that define Machnet's design space.
- _Fried et al. (NSDI '24)_ — Junction similarly aims to make kernel bypass practical in cloud settings, but the Machnet paper argues that direct NIC access and non-LCD features still leave it out of reach for many ordinary VM tenants.

## My Notes

<!-- empty; left for the human reader -->

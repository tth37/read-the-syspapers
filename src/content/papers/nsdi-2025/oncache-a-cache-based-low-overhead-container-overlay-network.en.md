---
title: "ONCache: A Cache-Based Low-Overhead Container Overlay Network"
oneline: "ONCache caches stable cross-layer overlay-network results and uses an eBPF fast path to skip repeated veth, filtering, routing, and encapsulation work."
authors:
  - "Shengkai Lin"
  - "Shizhen Zhao"
  - "Peirui Cao"
  - "Xinchi Han"
  - "Quan Tian"
  - "Wenfeng Liu"
  - "Qi Wu"
  - "Donghai Han"
  - "Xinbing Wang"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Broadcom"
conference: nsdi-2025
pdf_url: "https://www.usenix.org/system/files/nsdi25-lin-shengkai.pdf"
code_url: "https://github.com/shengkai16/ONCache"
tags:
  - networking
  - kernel
  - ebpf
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ONCache keeps a normal container overlay as a fail-safe fallback, but caches the repeated results of connection tracking, filtering, routing, and encapsulation so later packets can bypass most overlay work. The implementation is small, eBPF-based, and gets much closer to bare metal than standard Antrea or Cilium overlays while preserving container-IP flexibility and compatibility.

## Problem

The paper starts from a practical tension in container networking. Host networking, bridges, Macvlan/IPvlan, and SR-IOV can all be fast, but they either force port coordination, constrain placement, or require the underlay to understand container IP addresses. Tunnel-based overlays solve that deployment problem by decoupling container addresses from the physical network, which is why they are attractive in Kubernetes-like environments, but they pay for that flexibility with extra kernel work on every packet.

The authors do not treat that overhead as a vague complaint. They break Antrea and Cilium down against bare metal and show that the added cost is spread across veth traversal, OVS or equivalent packet processing, connection tracking, filtering, and VXLAN encapsulation or decapsulation. In their experiments, a tunnel-based overlay lowers single-flow TCP throughput by about 11% and TCP request-response rate by about 29% relative to bare metal, while consuming noticeably more CPU. That distribution of overhead is exactly what makes the problem awkward: no single hot function explains the loss, so a local optimization to one layer does not recover the whole gap.

Prior work only covers parts of the trade-off surface. Slim reduces overhead with socket replacement, but loses compatibility with UDP, ICMP, live migration, and some underlay policies that rely on tunnel headers. Falcon and related work parallelize ingress processing, but keep the overlay work itself and can increase CPU cost. ONCache is therefore framed as a systems design problem: how to keep standard overlay semantics while eliminating the repeated work that makes them slow.

## Key Insight

The key insight is that most of the "extra" overlay processing becomes invariant after a flow is established. Once conntrack has observed traffic in both directions, the connection state is stable; once filters have accepted a flow in that state, the decision is stable; once the destination container is known, the intra-host routing decision is stable; and most outer-header fields used for tunneling are also stable for packets going to the same destination.

That means the right unit of optimization is not one subsystem such as OVS flow matching, but the whole cross-layer result of overlay processing. ONCache caches that result once and then substitutes a few map lookups plus lightweight header updates for repeated trips through veth traversal, filtering logic, routing logic, and encapsulation logic. The paper's claim is that overlay overhead is repetitive enough to be memoized without giving up the fail-safe fallback path or the semantics that production overlays need.

## Design

ONCache is implemented as a plugin layered on top of an existing overlay such as Antrea or Flannel. Its fast path is built from four TC-hooked eBPF programs plus three per-host eBPF maps and one userspace daemon. The three caches are the core abstraction. The egress cache stores the invariant result of "where should packets to this container destination go, and what outer headers do they need?" To save memory it is split into two levels, from container destination IP to host destination IP, then from host destination IP to outer headers, inner MAC rewrite, and host interface index. The ingress cache stores the reverse intra-host routing result: destination container IP to destination MAC and veth index. The filter cache acts as a whitelist of established flows.

Cache population is intentionally conservative. On a cache miss, ONCache marks the packet by reserving one DSCP bit as a miss mark and lets the normal overlay process it. The fallback overlay is configured to add an est mark, using another DSCP bit, once conntrack sees the flow as established. Two initialization programs then watch those marked packets at the host interface and container-side veth, extract the now-known routing and header information, and populate the caches. This means ONCache never guesses. It learns from the authoritative behavior of the existing overlay, then reuses the result.

On a cache hit, the fast path is symmetric. The egress program first checks the flow whitelist and then performs a reverse check to ensure the opposite direction is also cache-ready; this prevents one-sided eviction from breaking later reinitialization. It then rewrites the inner MAC header, reconstructs outer headers, updates the variable IP and UDP fields, and redirects the packet to the host interface. On ingress, the program validates that the packet is actually for the local host, checks the whitelist and ingress cache, strips the outer headers, restores the inner MAC, and redirects the packet directly to the destination veth with `bpf_redirect_peer`.

The design is explicitly fail-safe. Any miss or failed precondition falls back to the standard overlay instead of dropping traffic. A userspace daemon maintains coherency by deleting affected cache entries on container deletion, migration, or policy change, then letting the overlay repopulate them. The authors also quantify memory cost for a very large cluster and argue it is modest: roughly 1.56 MB for egress cache, 2.2 KB for ingress cache, and 20 MB for the filter cache per host.

## Evaluation

The evaluation is broad enough to support the paper's main claim. The testbed is a Kubernetes 1.23.6 cluster on three CloudLab c6525-100g nodes with 100 Gb NICs, Ubuntu 20.04, and Linux 5.14. ONCache is deployed as an Antrea plugin and compared with Antrea and Cilium as standard overlay baselines, bare metal as an upper bound, and Slim and Falcon as representatives of two alternative optimization ideas.

The microbenchmarks are the strongest evidence because they directly target the claimed bottleneck. For TCP, ONCache improves throughput over Antrea by 11.53% and 13.96% in 1-flow and 2-flow tests, then hits the same physical bandwidth ceiling as the other networks at higher parallelism. More important, request-response rate improves by 35.81% to 40.91%, with per-RR CPU utilization dropping by 26.02% to 32.03%. UDP also benefits: throughput rises by 19.68% to 31.76% in the lower-parallelism regimes, and UDP RR improves by 34.13% to 39.12%. The low-level breakdown in Table 2 matches the end-to-end story: ONCache cuts stack latency to 17.49 us versus 22.97 us for Antrea, close to bare metal's 16.57 us.

The application results show that the gains survive outside toy benchmarks. Memcached average latency drops by 22.71% and throughput rises by 27.83% versus Antrea. PostgreSQL average latency falls by 22.34% and throughput rises by 29.40%. For HTTP/1.1 on Nginx, latency improves by 21.53% and throughput by 27.43%. CPU cost also falls sharply across these workloads. The weakest result is HTTP/3: ONCache still lowers CPU utilization, but latency and throughput remain poor and largely unchanged across networks, which the authors attribute to Nginx's experimental QUIC support. That caveat makes the paper more credible, not less.

## Novelty & Impact

The novelty is the cross-layer cache. OVS already caches flow matching, and prior work already explored socket replacement or packet-level parallelism, but ONCache is the paper that treats overlay overhead as one compound result that spans multiple layers of the kernel datapath. That framing explains why a small amount of eBPF code can recover a large fraction of the bare-metal gap: the design is not making one stage faster, it is removing repeated work across several stages at once.

The likely impact is practical. ONCache is deployable as an add-on to existing CNIs, keeps tunneling semantics, supports TCP and UDP, and is compatible with operational concerns such as live migration, data-plane policies, and service meshes. Researchers studying container networking will cite it as a clean systems argument for cross-layer memoization; practitioners may treat it as evidence that overlay flexibility does not have to imply an unavoidable performance tax.

## Limitations

ONCache does not accelerate all traffic. It targets inter-host container traffic; intra-host traffic, container-to-host traffic, and container-to-external-IP traffic stay on the fallback path. It also only helps after cache initialization, so the first packets of a flow still pay the normal overlay cost. The CRR experiments make this visible: connection setup improves relative to Antrea only because the request-response portion benefits once caches are warm.

The invariance assumption is also a real boundary. ONCache natively supports filters whose decision becomes stable in an established state, but packet-hash filters and unusual stateful filters without such a stable state do not fit the model. The implementation further assumes that two DSCP bits can be reserved for miss and established marks. In environments that depend on all DSCP bits for differentiated services, that choice could be awkward.

Finally, some of the remaining performance gap is knowingly left open. Default ONCache still pays egress namespace-traversal overhead, and the authors' best optional improvements require kernel or tunneling-protocol changes such as `bpf_redirect_rpeer` or a rewriting-based tunnel. For CNIs that already embed TC eBPF in their datapath, such as Cilium or Calico, ONCache also needs reimplementation rather than drop-in integration. The paper demonstrates a strong mechanism, but not a universal zero-cost overlay.

## Related Work

- _Zhuo et al. (NSDI '19)_ - `Slim` uses socket replacement to avoid overlay overhead for TCP, whereas ONCache keeps ordinary tunneling semantics and retains compatibility with UDP, ICMP, and live migration.
- _Lei et al. (EuroSys '21)_ - `Falcon` parallelizes packet processing across CPU cores, while ONCache instead reduces the amount of packet processing that must happen on either path.
- _Dalton et al. (NSDI '18)_ - `Andromeda` caches routing and filtering decisions in VM network virtualization, but ONCache argues container overlays need a cross-layer cache that also captures conntrack, veth, and tunneling work.
- _Pfaff et al. (NSDI '15)_ - `Open vSwitch` caches flow matching, yet ONCache shows that layer-local caches leave the rest of the overlay datapath overhead intact.

## My Notes

<!-- empty; left for the human reader -->

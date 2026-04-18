---
title: "eTran: Extensible Kernel Transport with eBPF"
oneline: "eTran adds eBPF egress, packet-generation, and pacing hooks so transports can keep state in-kernel yet get much of user-space transport performance."
authors:
  - "Zhongjie Chen"
  - "Qingkai Meng"
  - "ChonLam Lao"
  - "Yifan Liu"
  - "Fengyuan Ren"
  - "Minlan Yu"
  - "Yang Zhou"
affiliations:
  - "Tsinghua University"
  - "Nanjing University"
  - "Harvard University"
  - "UC Berkeley & UC Davis"
conference: nsdi-2025
code_url: "https://github.com/eTran-NSDI25/eTran"
tags:
  - ebpf
  - kernel
  - networking
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

eTran turns the kernel into a transport substrate by extending eBPF with `XDP_EGRESS`, `XDP_GEN`, and `PKT_QUEUE`. Those additions let the authors keep transport state inside the kernel for protection while still beating Linux TCP and Linux Homa by up to `4.8x` and `1.8x` in throughput, with up to `3.7x` and `7.5x` lower latency.

## Problem

Datacenter transports evolve faster than Linux can absorb them. DCTCP took years to upstream, MPTCP took nearly a decade, and Homa was still out of tree. RPC services, storage systems, and ML jobs want different transport policies.

Kernel bypass is the usual escape hatch, but it weakens protection: applications or NIC firmware gain direct influence over transport behavior, while debugging, telemetry, and multi-tenant isolation get harder. Staying in the kernel preserves protection, yet current eBPF hooks are too weak for full transports: XDP only sees ingress packets, cannot generate ACK or credit packets, and lacks a pacing buffer. The challenge is to make kernel transport extensible without giving up kernel safety or most of the performance benefits of user-space designs.

## Key Insight

The paper's key claim is that most transport logic can stay in kernel eBPF if the kernel exposes just three missing primitives and pushes only awkward work to a privileged daemon. The daemon handles program attachment, AF_XDP resource creation, connection setup and teardown, advanced congestion control that needs floating point, and timeout-based recovery.

Everything timing-critical stays in-kernel: state machines, header processing, ACK or credit handling, pacing, and packet validation. The user-space library only moves packet data through AF_XDP and reconstructs application-facing abstractions; it never directly mutates transport state.

## Design

eTran splits into a control path and a data path. The control path is a root daemon that attaches transport-specific eBPF programs, creates AF_XDP sockets and UMEMs, and handles slow-path control operations. The data path runs across kernel eBPF and a thin user-space library; the library reassembles messages and exposes POSIX-like or RPC APIs, but transport state stays in eBPF maps. To span multiple NIC queues, eTran also builds a virtual AF_XDP socket with DRR scheduling.

The kernel changes are the heart of the system. `XDP_EGRESS` hooks the AF_XDP transmit path so eBPF can fill headers, enforce ownership with `umem_id`, transmit immediately, buffer, or drop. `XDP_GEN` runs at the end of NAPI polling so ingress code can enqueue metadata and later batch-generate ACK or credit packets from preallocated frames. `BPF_MAP_TYPE_PKT_QUEUE`, combined with extended BPF timers, becomes a pacing engine for both rate-based and credit-based scheduling.

The case studies show the substrate is not TCP-specific. For TCP with DCTCP, eTran keeps connection state in a hashmap, shares congestion-control state with the daemon through an mmap-able array, validates packets at `XDP`, and uses the pacing queue when congestion or flow-control windows block transmission. For Homa, it stores RPC state in eBPF, uses `bpf_rbtree` for receiver-driven credit scheduling, adds a `bpf_rbtree_lower_bound` kfunc to emulate Homa's priority search, and uses tail calls to fit the verifier's instruction limits.

## Evaluation

On 25 Gbps CloudLab machines, eTran Homa cuts median 32 B RPC latency from `15.6 us` to `11.8 us`, raises 1 MB throughput from `14.5` to `17.7 Gbps`, and improves client/server RPC rate from `1.7/1.8` to `2.9/3.3 Mops`. In the 10-node cluster workloads, it lowers short-message P99 latency by `3.9x-7.5x`.

For TCP, eTran beats Linux TCP with DCTCP across the authors' echo and key-value benchmarks. On the key-value store it reaches up to `4.8x` Linux's throughput and lowers unloaded P50/P99 latency from `64.2/89.3 us` to `17.2/27.5 us`. It still trails TAS, which is expected: TAS busy-polls on dedicated cores and bypasses more of the kernel.

The support measurements make the substrate story more credible. `PKT_QUEUE` rate limiting stays within `0.4%` of target rates, an empty `XDP_EGRESS` costs `6.6%` throughput on the microbenchmark, and eTran cuts per-request CPU cost from `12.51` to `4.37` kcycles for TCP and from `17.43` to `5.48` for Homa. The main caveat is scope: one NIC family, one driver, and two full transport implementations.

## Novelty & Impact

What is new here is not a single transport algorithm but a reusable kernel substrate for transports. `eTran` says the right abstraction boundary is "teach eBPF how to host transports once" rather than "merge each transport into Linux separately."

That makes the paper relevant to transport researchers, cloud operators who want kernel-resident protection, and kernel developers deciding how far XDP/AF_XDP should go. It sketches a middle ground for protected in-kernel fast paths.

## Limitations

eTran's biggest limitation is deployment friction. `XDP_EGRESS`, `XDP_GEN`, `PKT_QUEUE`, the new timer modes, and the tree-search kfunc all require kernel changes, so the approach depends on upstreaming and ongoing security review.

Performance is also not universally best. TCP remains slower than TAS, eBPF still lacks floating-point arithmetic and rich synchronization, thread scheduling hurts tail latency, and the mlx5 setup in the paper lacks AF_XDP features such as TSO or multi-buffer support. The safety story moreover assumes trust in the kernel and verifier ecosystem; the new kfuncs are carefully constrained, but not formally verified here.

## Related Work

- _Kaufmann et al. (EuroSys '19)_ - `TAS` treats transport as a microkernel-style user-space service, while `eTran` pulls the fast path back into kernel eBPF to regain protection and coexistence with the Linux stack.
- _Fried et al. (NSDI '24)_ - `Junction` makes kernel bypass practical in clouds, whereas `eTran` chooses a different point in the design space: lower peak speed in exchange for in-kernel isolation and state protection.
- _Zhou et al. (NSDI '23)_ - `Electrode` offloads distributed protocol logic into kernel eBPF, while `eTran` extends eBPF itself so transport protocols can live on top of it.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Pegasus: Transparent and Unified Kernel-Bypass Networking for Fast Local and Remote Communication"
oneline: "Pegasus fuses symbiotic Linux processes into one protected monitor so unmodified binaries get a local TCP fast path and remote NIC bypass under the same socket API."
authors:
  - "Dinglan Peng"
  - "Congyu Liu"
  - "Tapti Palit"
  - "Anjo Vahldiek-Oberwagner"
  - "Mona Vij"
  - "Pedro Fonseca"
affiliations:
  - "Purdue University"
  - "Intel Labs"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696083"
tags:
  - networking
  - datacenter
  - scheduling
  - isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pegasus treats tightly coupled cloud services as a single scheduling and communication domain: it fuses symbiotic Linux processes into one protected user-space monitor, replaces local TCP with an in-process fast path, and sends remote traffic through a DPDK-backed kernel-bypass stack. The result is transparent acceleration for unmodified binaries, with 19%-33% higher throughput for local communication, 178%-442% for remote communication, and 222% for a workload that needs both.

## Problem

The paper starts from a practical change in cloud software structure, not from a new NIC. Modern deployments split one application into multiple processes, containers, or sidecars that communicate constantly through ordinary sockets, pipes, HTTP, and gRPC. That makes the kernel expensive twice over: remote communication still pays the familiar network-stack cost, but even local communication between co-located components now incurs scheduler wakeups, mode switches, and kernel IPC overhead. The paper's futex microbenchmark makes the control-path problem concrete: waking a thread through Linux takes 1.37 us, which is already comparable to or worse than some fast-network operations.

Existing solutions only cover part of the problem. Shared-memory IPC can speed up the data path for local communication, but still relies on kernel synchronization. Remote kernel-bypass systems remove the kernel from NIC I/O, but usually require custom APIs, rewrites, or language-specific runtimes. That leaves operators with an awkward tradeoff: either refactor applications around new interfaces, or keep the POSIX/Linux ABI and accept communication overhead even when services are co-located.

## Key Insight

Pegasus's central claim is that local and remote communication should be optimized by the same abstraction boundary: not a library call, but a protected user-space execution environment that already owns scheduling, memory management, and socket mediation for a group of symbiotic processes. Once those processes are fused into one address space, the system can decide transparently whether a TCP connection should become a shared-memory message path or a kernel-bypass remote path, while still presenting ordinary Linux process and socket semantics to the application.

That framing matters because shared memory alone is insufficient. The real win comes from removing the kernel from both the data path and the control path. Pegasus therefore virtualizes process execution itself with vProcesses and vThreads, so blocking, waking, and handoff between communicating services happen inside the monitor rather than through futexes and kernel scheduling.

## Design

Pegasus runs multiple applications inside one Linux process but preserves logical process boundaries with a privileged monitor. Each loaded program becomes a `vProcess` with one or more `vThread`s. A user-space ELF loader creates those abstractions, loads PIE binaries and their dynamic linker into per-program regions, and starts execution at the Linux ABI level, so the applications themselves are unchanged.

The control plane is intentionally OS-like. Pegasus implements a user-space scheduler with per-worker run queues and wait queues, roughly following CFS. Cooperative scheduling happens at intercepted blocking points such as `futex`, `read`, and `clone`; preemption is added with `SIGALRM`, and cross-core preemption with `SIGURG`. For memory and kernel-context isolation, Pegasus combines Intel MPK with implicit kernel context switching from uSwitch. The monitor owns domain 0, each application gets its own MPK domain, and mode-switch gates carefully update `PKRU`, stack state, and kernel resource selection so a buggy process cannot escape into the monitor or another vProcess.

Compatibility is the second major mechanism. Pegasus uses per-domain Seccomp filters to trap important syscalls, but avoids paying a signal on every call. It first intercepts libc-wrapped calls with `LD_PRELOAD`, then rewrites direct `syscall` instructions the first time they fault, using the resulting `SIGSYS` frame to find the exact instruction boundary. It also virtualizes file descriptors so a local fast-path socket can still occupy an ordinary descriptor slot.

With that substrate in place, Pegasus installs two communication fast paths. For local traffic, if one fused process connects to a local TCP address of another fused process, Pegasus replaces the kernel stack with shared ring buffers and schedules the receiver directly along the message critical path. For remote traffic, it intercepts the normal socket API and forwards it to an F-Stack/DPDK backend, letting unmodified programs use kernel bypass without adopting a custom networking API. `io_uring` fills the gaps for blocking file and timer operations and also acts as the default backend when remote kernel bypass is unavailable.

## Evaluation

The experiments run on two CloudLab r6525 servers with dual 2.8 GHz AMD EPYC 7543 CPUs, 256 GiB RAM, and Mellanox ConnectX-6 100 Gbps NICs. The paper evaluates both microbenchmarks and real applications, including Redis, Nginx, Memcached, Caddy, Node.js, and an Istio service-mesh setup.

For local communication, the strongest result is that Pegasus fixes the control path, not just the copy path. Futex wakeup latency drops from 1.37 us to 0.49 us, and condition-variable wakeup from 1.51 us to 0.56 us. End-to-end protocol latency also falls sharply: TCP echo goes from 7.8 us to 1.2 us, Redis `SET` from 11.0 us to 4.8 us, and Memcached `set` from 10.3 us to 3.7 us. On larger applications, a Node.js + Redis + Nginx web app gains 19% peak throughput, and an Istio sidecar deployment gains 33%. In the reverse-proxy experiment, Pegasus peaks at a 74% throughput increase when all requests go through the proxy, which is exactly the regime where local communication dominates.

For remote communication, Pegasus does not beat the best specialized datapaths on raw microseconds, but it stays close while remaining transparent. TCP round-trip latency falls from 27.78 us on Linux to 13.88 us on Pegasus, only 1.91 us slower than F-Stack. Redis reaches 801 KQPS, 323% above Linux's 189 KQPS, 153% above Demikernel, and only 1.5% below F-Stack. Nginx and Memcached improve maximum throughput by 178% and 442% over Linux, respectively, while staying in the same performance band as Junction and F-Stack.

The mixed-communication experiment is the most convincing validation of the paper's thesis. For a Caddy server fronted by an Nginx TLS reverse proxy, Linux reaches 12.1 KQPS. Pegasus reaches 39.0 KQPS, a 222% increase. Turning on only the remote fast path yields 16.8 KQPS, and only the local fast path 20.4 KQPS, showing that the two optimizations contribute independently and compose cleanly.

## Novelty & Impact

Pegasus is novel because it treats Linux ABI compatibility, local communication bypass, remote kernel bypass, and in-process isolation as one systems problem instead of four separate patches. Unlike _Fried et al. (NSDI '24)_ on Junction, Pegasus keeps a protected monitor and a true local fast path rather than fate-sharing fused programs and routing all traffic through the NIC path. Unlike _Ousterhout et al. (NSDI '19)_ on Shenango or _Zhang et al. (SOSP '21)_ on Demikernel, it preserves unmodified POSIX/Linux binaries instead of asking developers to port to a new threading or socket interface. Unlike _Li et al. (SIGCOMM '19)_ on SocketDirect, it does not stop at shared-memory data transfer, but also moves scheduling and wakeup decisions into user space.

That combination makes the paper relevant to service meshes, reverse proxies, sidecar-heavy platforms, and container runtimes. The likely impact is not that everyone will run Pegasus directly, but that future kernel-bypass systems will have to justify why local IPC, ABI transparency, and isolation are treated as optional extras rather than part of the main design.

## Limitations

Pegasus is transparent only within a fairly specific deployment envelope. Programs must be PIE binaries, cannot rely on fixed-address mappings, and cannot duplicate their address space with `fork`; the authors explicitly call out Apache- and Bash-like workloads as unsupported today. The isolation goal is also functional rather than side-channel resistant, and the MPK design inherits the practical limit of 16 protection domains, which constrains how many isolated vProcesses fit in one instance.

The remote path is also partly inherited technology. Pegasus depends on F-Stack for kernel-bypass networking, so features F-Stack lacks, such as netlink, netfilter, and virtual network interfaces, are unavailable when that backend is enabled. Some OS functions, especially disk I/O and less performance-critical facilities, still fall back to Linux and incur measurable virtualization overhead. The paper also does not study multi-tenant deployment or performance isolation in depth; it assumes symbiotic processes from the same tenant.

## Related Work

- _Fried et al. (NSDI '24)_ - Junction also pursues Linux ABI-compatible kernel bypass, but Pegasus adds protected in-process isolation and a local-only TCP fast path instead of sending every packet through a centralized NIC-oriented path.
- _Ousterhout et al. (NSDI '19)_ - Shenango moves scheduling and networking into user space for latency-sensitive services, whereas Pegasus keeps the stock Linux ABI for unmodified binaries rather than exposing a new application interface.
- _Zhang et al. (SOSP '21)_ - Demikernel offers a datapath OS architecture and new APIs for microsecond-scale datacenter systems; Pegasus accepts a small latency premium to avoid any application porting.
- _Li et al. (SIGCOMM '19)_ - SocketDirect accelerates compatible local sockets with shared memory, while Pegasus extends the idea to remote kernel bypass and user-space process virtualization under one framework.

## My Notes

<!-- empty; left for the human reader -->

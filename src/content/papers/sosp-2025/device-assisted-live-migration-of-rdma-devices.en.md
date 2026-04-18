---
title: "Device-assisted Live Migration of RDMA devices"
oneline: "Adds a device-level migration API and two-phase PCIe quiescing so passthrough RDMA NICs, including GPUDirect setups, can live-migrate transparently with sub-second downtime."
authors:
  - "Artem Y. Polyakov"
  - "Gal Shalom"
  - "Aviad Yehezkel"
  - "Omri Ben David"
  - "Asaf Schwartz"
  - "Omri Kahalon"
  - "Ariel Shahar"
  - "Liran Liss"
affiliations:
  - "NVIDIA Corporation, USA"
  - "NVIDIA Corporation, Israel"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764795"
tags:
  - rdma
  - virtualization
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

The paper argues that transparent live migration of passthrough RDMA devices is only practical if the NIC participates directly in migration. It therefore exposes a device-level migration API, preserves RDMA namespaces and connections instead of rebuilding them in software, and adds a two-phase quiescing scheme for PCIe peer-to-peer traffic, yielding sub-second downtime for realistic HPC and AI configurations.

## Problem

Cloud operators already depend on live migration for maintenance and rolling upgrades, but passthrough RDMA devices break the abstraction that makes migration work. Once a VM talks to an RDMA NIC directly through SR-IOV and PCIe passthrough, the hypervisor no longer has direct access to the device state. RDMA makes this worse because device-assigned identifiers such as QP numbers and memory keys are visible outside the device, and transport progress plus one-sided memory access live inside the NIC rather than in a software layer the hypervisor can serialize.

The software-only fallback is to virtualize RDMA resources above the hardware: recreate QPs and MRs on the target, translate identifiers at runtime, drain outstanding work, and reconnect peers. The paper argues that every part of that plan is a deployment problem. Verbs-based reconstruction costs seconds, draining ties downtime to network conditions and message size, and guest or middleware modifications are not acceptable for cloud tenants. AI VMs raise the stakes further because GPUDirect lets the NIC access GPU memory over PCIe peer-to-peer links, so migration must preserve both device state and inter-device consistency.

## Key Insight

The paper's core claim is that RDMA migration must happen at the device-state level, not at the RDMA-object level. If the NIC itself exports a semantically sufficient image and reconstructs the same namespaces, local addresses, and transport progress on the target, migration can stay transparent to both the guest and its peers without runtime translation or global coordination.

This works because only the device knows the hidden state precisely enough to preserve it cheaply. The NIC can stop at packet granularity instead of draining queue pairs, preserve wire-visible identifiers instead of inventing translations, and distinguish state that must be copied from state that is obsolete or reconstructible. The same idea extends to multiple passthrough devices: rather than freezing devices one by one, the hypervisor should quiesce the memory fabric in phases so posted PCIe transactions are flushed before any device is sealed.

## Design

The design is organized as a set of device assists. For transparency, the NIC preserves RDMA namespaces, local connection state, and remote connection state. That keeps QP numbers and memory keys stable, recreates MAC/IP or LID/GID addresses and QPs exactly on the target, and avoids explicit peer coordination by relying on exponential-backoff retransmission timers during the pause.

The most important assist is packet-granularity quiescing. Prior work drains communication, which makes downtime depend on message size and network conditions. Here, the device stops at transport-packet granularity, so retransmission stays bounded and transport state such as expected packet sequence numbers and atomic-operation metadata can be resumed directly. State export follows the same philosophy: instead of serializing RDMA objects through Verbs, the device emits a black-box image in blocks, tracks compatibility with a vendor-specific migration tag, and exposes generic commands such as `PreCopy`, `DevThrottle`, `Suspend-Active`, `Suspend-Passive`, and image save/load iteration.

The second major contribution is a two-phase suspend/resume protocol for multiple passthrough devices on fabrics such as PCIe. In the active phase, a device stops initiating DMA but continues serving incoming requests as a target. In the passive phase, its state is sealed for extraction. The paper uses PCIe ordering rules to argue that issuing active suspends to all devices before any passive suspend yields a consistent cut even when devices exchange peer-to-peer traffic.

The implementation targets NVIDIA ConnectX-7 and adds about 6K lines of firmware plus changes in Linux VFIO and QEMU. Most per-VF state lives in per-VF ICM pages managed by the device but stored in hypervisor memory. `Suspend-Active` disconnects the VF from the embedded switch, halts transmit queues, completes guest control-path commands, and disables DMA mastering. `Suspend-Passive` flushes device caches and distills the image by removing location-dependent references and obsolete runtime state. Pre-copy communicates the ICM layout to the target so pages can be pre-allocated, and traffic shaping provides dirty-rate control.

## Evaluation

The evaluation runs on three servers with 96-core AMD EPYC 9654 CPUs, 128 GB RAM, NVIDIA L40S GPUs, and ConnectX-7 200 Gbit/s NICs, with QEMU's out-of-band migration channel limited to an effective 16 Gbit/s. The first result is that bulk state transfer is much cheaper than object-by-object reconstruction. For 100K QPs, bulk image load takes 2.5 s, whereas creating and connecting them individually through Verbs takes about 9.14 s plus 5.88 s. For 100K MRs, bulk loading takes 0.1 s versus 37.75 s to recreate them, because the image path avoids guest-side memory pinning.

Downtime numbers support the paper's main claim, though they also expose the remaining bottleneck. With 100K QP/CQ pairs, the image grows to 395 MB. Pre-copying ICM allocation cuts downtime by 25% at 100 QPs and by 75% at 100K QPs. Pipelining mainly saves memory footprint, reducing migration memory to a fixed 16 MB of buffers, but only trims downtime by another 3% because the 16 Gbit/s out-of-band channel dominates transfer time. From the application's point of view, an `ib_write_lat` probe sees a 310 ms RTT spike that matches QEMU's measured 308 ms downtime; a second 81 ms spike comes from route reconfiguration in the authors' setup.

The performance story is strong in the narrow regime the paper promises. For `ib_write_bw` and message-rate tests, there is no visible degradation during pre-copy and performance returns to bare-metal levels immediately after downtime, even when the VM also holds 100K idle QPs. MPI NAS Parallel Benchmarks pass integrity checks with only slight runtime increase under one migration, and NCCL Allreduce on 1 GB vectors restores full bandwidth after migration in a 500-iteration loop. The caveat is convergence: when RDMA traffic reaches 18 Gbit/s, above the out-of-band channel, migration no longer converges; even 15 Gbit/s requires 99.7 s and 46.4 pre-copy rounds, versus 31 s and 5.6 rounds at 1 Gbit/s throttling.

## Novelty & Impact

Relative to software RDMA migration systems, the novelty is not merely "use hardware help," but to define what that help must provide: namespace preservation, packet-granularity quiescing, black-box image extraction, dirty-rate control, and a two-phase quiesce protocol for directly interacting devices. Relative to device-assisted Ethernet migration work, it extends transparency to a harder regime where wire-visible RDMA state and peer-to-peer GPU/NIC communication must survive migration.

The impact is practical as well as conceptual. The mechanism is positioned as generally available in production Linux virtualization stacks, and the API is device-agnostic enough that later support for other passthrough devices can reuse the same control flow.

## Limitations

The most obvious limitation is portability. The approach depends on substantial firmware support, device-specific state knowledge, and hypervisor integration, and the paper demonstrates it only for ConnectX-7. The compatibility scheme is also only partially flexible: feature-version growth is allowed, but any ICM layout change still requires a cold reboot.

Performance limits remain as well. Downtime still grows with image size, pre-copy may fail to converge when device dirtying outruns the migration channel, the current implementation pays resume overhead for scanning QPs in firmware, and post-copy support is left unevaluated. Connection preservation still relies on timeout inflation, which the authors note can conflict with fast failure detection and path management. The application study is convincing for correctness and recovery of steady-state performance, but it is still limited to one NIC family, one hypervisor stack, and one testbed network.

## Related Work

- _Cao et al. (HPDC '14)_ - DMTCP checkpoint-restart over InfiniBand handles RDMA in software, whereas this paper moves consistency and state capture into the NIC to avoid object recreation and peer coordination.
- _Planeta et al. (USENIX ATC '21)_ - MigrOS also seeks transparent RDMA migration, but it depends on object-level serialization and a new `Paused` QP state; this paper instead preserves namespaces and uses timeouts, avoiding wire-protocol changes and deadlock risk.
- _Li et al. (APNet '24)_ - MigrRDMA amortizes software reconstruction during pre-copy with guest involvement, while this work exports a black-box device image and requires no guest or peer modifications.
- _Zhang et al. (IEEE TC '24)_ - Un-IOV demonstrates device-assisted transparent migration for VirtIO devices, whereas this paper tackles RDMA semantics and the added challenge of PCIe peer-to-peer multi-device consistency.

## My Notes

<!-- empty; left for the human reader -->

---
title: "RosenBridge: A Framework for Enabling Express I/O Paths Across the Virtualization Boundary"
oneline: "Moves NDP-style storage offload from the guest into QEMU via a paravirtualized uBPF device, so VMs can use XRP/GDS-like fast paths without breaking isolation."
authors:
  - "Shi Qiu"
  - "Li Wang"
  - "Jianqin Yan"
  - "Ruofan Xiong"
  - "Leping Yang"
  - "Xin Yao"
  - "Renhai Chen"
  - "Gong Zhang"
  - "Dongsheng Li"
  - "Jiwu Shu"
  - "Yiming Zhang"
affiliations:
  - "NICE Lab, XMU"
  - "SJTU"
  - "KylinSoft"
  - "Huawei Theory Lab"
  - "NUDT"
  - "THU"
conference: fast-2026
category: os-and-io-paths
tags:
  - virtualization
  - storage
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

RosenBridge makes bare-metal-style express storage paths usable inside VMs by moving NDP logic across the guest-host boundary instead of leaving it trapped behind virtio. Its `virtio-ndp` device lets a guest load verified uBPF programs into QEMU, trigger them on I/O submission or completion, and use helper-based address translation to safely resubmit I/O near the host NVMe driver. On the paper's two case studies, this closes much of the gap to bare-metal XRP and GDS while using much less CPU than conventional virtio/vhost paths.

## Problem

The paper starts from a now-familiar inversion: NVMe devices have become fast enough that the software stack, not the SSD, dominates end-to-end I/O cost. In their breakdown of a `4 KB` random read through `virtio-blk`, software accounts for `87%` of total latency, and the VM burns `498.3%`, `630.4%`, and `581.0%` more CPU than the host to reach the same `2`, `4`, and `8 GB/s` throughput points. Virtualization turns what is already a nontrivial storage path into a longer one with guest kernel work, VM exits, QEMU processing, and a second host-side storage stack.

Bare-metal express I/O mechanisms such as XRP and GPU Direct Storage attack exactly this overhead by pushing logic close to the device and resubmitting I/O without bouncing back to userspace. But those optimizations stop at the virtualization boundary. A guest VM sees only a paravirtualized device, not the host NVMe queues or the host's address translations, so the guest cannot safely run the same NDP logic where it would matter. Pushing such logic into the guest virtio frontend still leaves the host stack in the path; pushing it into the host kernel would violate the isolation model cloud operators depend on.

## Key Insight

The paper's core claim is that VMs can use express I/O paths if the hypervisor exposes a narrowly scoped programmable execution substrate on the host side, rather than trying to tunnel a bare-metal fast path through opaque virtualization layers. In RosenBridge, the offloaded program does not need arbitrary host privileges. It needs three specific capabilities: a place to run inside the host, hook points that can intercept submission and completion events, and helper functions that translate guest-visible addresses and offsets into host-side ones.

That leads to a pragmatic placement choice. RosenBridge runs verified uBPF programs in QEMU user space, not in the guest and not in the host kernel. User-space execution preserves the hypervisor's safety envelope, while still sitting close enough to `io_uring` passthrough and the NVMe driver to make resubmission useful. The mechanism works because RosenBridge couples programmability with explicit bounds: limited context objects, verifier-checked memory access, helper-mediated translations, and shared throttling state so a VM cannot create a shadow I/O path that escapes QoS control.

## Design

RosenBridge introduces `virtio-ndp`, a new paravirtualized device with a guest frontend and a QEMU backend. The guest gets four main interfaces: `BPF_HOST_ATTACH` and `BPF_HOST_DETACH` to load and unload a BPF program on the host, and `read_nd` / `write_nd` to issue I/O associated with a previously attached program. The virtio request header is extended with a program identifier plus buffer metadata so QEMU can distinguish ordinary I/O from program load, unload, and NDP-triggering requests.

Once a `read_nd` or `write_nd` request reaches QEMU, RosenBridge routes it to a dedicated worker thread and executes the corresponding uBPF program. The data path then relies on `io_uring` passthrough so requests issued from the host userspace runtime can still bypass most of the conventional kernel I/O stack and reach the NVMe driver efficiently. To support the two workload shapes the paper cares about, RosenBridge adds two hook points to `io_uring`: one at submission queue preparation and one at completion handling. Submission hooks support on-path rewrites such as GDS buffer remapping; completion hooks support content-driven resubmission as in XRP.

The semantic-gap machinery is equally important. Guest metadata is copied into a guest-host shared-memory region mapped through the `virtio-ndp` PCI BAR, and the BPF program receives a `rosenbridge_md` context containing `meta`, `meta_end`, `data`, and `data_end` pointers. For state that exists only on the host, RosenBridge exposes helper functions such as `BPF_disk_trans` and `BPF_mem_trans` to translate guest-visible disk offsets or memory pointers into host-side addresses. The paper's two case studies are straightforward applications of that substrate: RosenXRP attaches at completion, checks whether another B-tree read is needed, translates the next offset, and resubmits via a fresh SQE; RosenGDS attaches at submission, looks up the offloaded GPU memory mapping, translates the phony buffer to a host-visible GPU address, and lets peer-to-peer DMA proceed.

Security and fairness are built into the mechanism instead of being treated as afterthoughts. RosenBridge introduces a dedicated `BPF_PROG_TYPE_ROSENBRIDGE` context and relies on the PREVAIL verifier at load time to ensure termination and in-bounds accesses. Runtime checks in `BPF_uring_set_sqe` confine memory references to VM-owned regions and disk accesses to the VM's virtual-disk range. Because offloaded I/O creates a second submission path, RosenBridge also shares QEMU's leaky-bucket throttling state across standard and uBPF-triggered requests, so the VM's total quota still applies.

## Evaluation

The evaluation uses a dual-`64`-core server with `512 GB` of DRAM, Linux `6.1.0` on both host and guest, QEMU `7.1.50`, an Intel `P5800X`, and a passed-through `48 GB` GPU for the GDS experiments. The baselines are well chosen for the paper's claims: `virtio-blk`, `vhost-kernel-blk`, and `vhost-user-blk` for RosenXRP, plus bare-metal XRP and GDS as upper bounds.

For RosenXRP, the headline result is that offloading the programmable resubmission logic across the boundary matters much more than merely accelerating the traditional paravirtualized path. On random key lookups, RosenXRP improves throughput by `461.8%` over `virtio-blk`, `243.5%` over `vhost-kernel-blk`, and `102.1%` over `vhost-user-blk`; average latency falls by `82.1%`, `70.7%`, and `49.4%`, respectively. It still trails bare-metal XRP, reaching about `65%` of its bandwidth while paying `55%` higher average latency, which is consistent with the fact that each VM operation must still cross the virtualized stack once. Range-query results show the same pattern and become relatively closer to XRP as query length grows. CPU efficiency is a second strong point: RosenXRP uses only `14.73%`, `28.69%`, and `41.85%` of the CPU consumed by the three virtualized baselines on key lookup, and even less on range queries. The fairness experiment is narrow but useful: with each VM capped at `1300 MB/s`, disabling RosenBridge's throttling lets XRP-like traffic push a neighboring virtio VM down to roughly `30%` of its limit, while enabling collaborative throttling keeps both near their configured rates.

RosenGDS is less dramatic but still convincing. Compared with `virtio-blk` plus `cudaMemcpy`, it reduces single-thread latency by `27.5%` to `56.4%` across I/O sizes and cuts CPU usage by at least `35.2%`. Under four threads, it outperforms the virtio path up to the point where the disk saturates and delivers only `26%` lower average bandwidth than bare-metal GDS. At `1 MB` and `4 MB`, it uses just `45.2%` and `79.7%` of the CPU consumed by `virtio-blk`. Overall, the experiments support the paper's central claim: RosenBridge does not remove virtualization overhead, but it removes enough avoidable stack work that NDP-style fast paths become worthwhile inside a VM.

## Novelty & Impact

Compared with _Zhong et al. (OSDI '22)_ on XRP, RosenBridge is not a new storage function mechanism so much as a way to preserve XRP-like semantics after virtualization would normally destroy them. Compared with _Qiu et al. (SC '24)_ on EXO, it goes beyond accelerating address translation inside paravirtualized storage and instead offloads programmable NDP logic itself, eliminating more of the repeated guest-host crossings within one logical operation.

That makes the paper a new systems mechanism, not just a faster virtio variant. Its likely impact is on cloud local-storage stacks, virtualized databases and analytics engines, and GPU-heavy VMs that currently lose too much performance to storage mediation. More broadly, it shows a reusable pattern for crossing the virtualization boundary safely: put programmable logic in the hypervisor's userspace, give it carefully bounded helper access to host semantics, and make resource control shared rather than optional.

## Limitations

RosenBridge does not make virtualization disappear. The paper is explicit that RosenXRP still incurs noticeable overhead versus bare metal because every operation must traverse the virtualized storage stack at least once before the host-side fast path can take over. That also means the win is largest for multi-stage or resubmission-heavy workloads, not for every possible I/O pattern.

The deployment assumptions are also nontrivial. RosenBridge requires a modified virtio device, QEMU backend changes, `io_uring` hook integration, and helper functions tailored to the offloaded optimization. Guest applications must use extended APIs and keep shared metadata consistent, which pushes some burden onto the application or guest runtime. The security story is plausible, but it depends on verifier quality and a narrow helper surface. Finally, the evaluation covers only one host platform, one SSD configuration, one GPU setup, and two case studies; the paper argues the framework is general, but that generality is demonstrated more by mechanism than by breadth of workloads.

## Related Work

- _Zhong et al. (OSDI '22)_ — XRP uses eBPF in the bare-metal NVMe path to resubmit storage requests from within the driver; RosenBridge recreates that resubmission model for VMs by offloading verified uBPF into QEMU.
- _Qiu et al. (SC '24)_ — EXO accelerates KVM/QEMU storage paravirtualization with eBPF-based mapping logic, while RosenBridge exposes a more programmable cross-boundary execution model for NDP optimizations.
- _Amit and Wei (USENIX ATC '18)_ — Hyperupcalls let the hypervisor invoke guest-registered eBPF handlers without guest context switches, but they are host-initiated and do not provide a general express storage path from guest to host.
- _Leonardi et al. (ISC '22)_ — eBPF-based extensible paravirtualization moves eBPF logic between host and guest for VM tuning, whereas RosenBridge focuses on safe guest-to-host programmable storage I/O with explicit fairness controls.

## My Notes

<!-- empty; left for the human reader -->

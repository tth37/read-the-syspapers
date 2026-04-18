---
title: "Atmosphere: Practical Verified Kernels with Rust and Verus"
oneline: "Keeps the kernel pointer-centric in Rust, then uses Verus, flat permission maps, and explicit memory management to make verified kernels practical."
authors:
  - "Xiangdong Chen"
  - "Zhaofeng Li"
  - "Jerry Zhang"
  - "Vikram Narayanan"
  - "Anton Burtsev"
affiliations:
  - "University of Utah"
  - "Palo Alto Networks"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764821"
tags:
  - kernel
  - verification
  - security
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Atmosphere argues that verified kernels become practical when the code stays low-level but the proofs are reorganized. It keeps raw-pointer Rust data structures, then uses Verus, flat permission maps, and explicit memory management to prove refinement, safety, and noninterference for a full-featured microkernel.

## Problem

Prior verified kernels either demanded theorem-prover-scale effort or simplified the kernel enough to fit SMT automation. Real kernels are hard because their state is recursive and pointer-heavy: process trees, page tables, linked lists, reverse pointers, and objects with long, nonlinear lifetimes. Those patterns fit neither idiomatic Rust ownership nor bounded SMT reasoning, and automatic memory management hides the whole-system state needed for leak-freedom and noninterference arguments. Atmosphere targets the harder middle ground: a separation kernel with processes, threads, IPC, virtual memory, IOMMU, and mixed-criticality containers, but verified with a workflow closer to ordinary systems development.

## Key Insight

The paper's central claim is that proof structure, not kernel functionality, should be flattened. Atmosphere keeps raw pointers in executable Rust, but stores permissions to inner objects in subsystem-level flat maps. That gives Verus a direct view of all containers, threads, or page-table nodes, so many recursive arguments become global non-recursive invariants. By also making allocation and deallocation explicit, the kernel can state whole-machine safety and isolation properties over actual memory ownership instead of over local partial views.

## Design

Atmosphere is a big-lock microkernel: syscalls and interrupts run under one global lock on multiprocessor hardware. It provides address spaces, threads, dynamic memory, IPC endpoints, IOMMU support, and containers that reserve memory and CPU cores. Containers form a tree, and parents reclaim a descendant's resources by terminating the descendant rather than by fine-grained revocation, because stable ownership boundaries make verification simpler.

Inside the kernel, the process manager holds flat tracked-permission maps for containers, processes, threads, endpoints, and related objects. The executable code looks like an unsafe C kernel, but Verus permissions prove each pointer access valid. Ghost state such as a container's `path` and `subtree` exposes hierarchy information without recursive traversals. Closed spec functions capture structural invariants; open specs describe each operation's before/after effect; separate proof functions show those effects preserve the structural invariants.

Manual memory management is equally deliberate. Atmosphere allocates kernel objects from 4 KiB, 2 MiB, and 1 GiB pages, tracks pages as free, mapped, merged, or allocated, and gives each subsystem a `page_closure()` spec so memory safety and leak freedom can be proved bottom-up. The same flat-spec style supports the paper's A/B/V noninterference example: two untrusted containers remain isolated while both talk to a small verified mediator container.

## Evaluation

Atmosphere contains 6,048 lines of executable code and 20,098 lines of proof/spec code, a 3.32:1 proof-to-code ratio. The authors report less than 2.5 person-years total effort, with about 1.5 person-years on verified components. Full verification takes 1 minute 7 seconds on an 8-thread CloudLab c220g5 and under 20 seconds on a recent laptop. The flat design also pays off directly: compared with the Verus-verified NrOS page table, Atmosphere's page table needs about 3x less proof per line of executable code and verifies more than 3x faster on one thread.

Runtime performance is close to strong baselines. Call/reply IPC takes 1,058 cycles versus 1,026 for seL4, and page mapping takes 1,984 cycles versus 2,650 in seL4's comparable test. The Ixgbe driver hits 10 GbE line rate at batch size 32, the NVMe driver matches SPDK-like reads and trails Linux writes by about 10%, Maglev reaches 13.3 Mpps with a dedicated driver core, and `httpd` serves 99.4 K requests/s versus Nginx's 70.9 K. The results support the claim that verification did not force a toy kernel.

## Novelty & Impact

Relative to seL4 and CertiKOS, Atmosphere contributes better proof economics rather than stronger assurance. Relative to Hyperkernel, it preserves a richer kernel interface instead of simplifying functionality to fit automation. Relative to prior Verus systems, it tackles exactly the difficult case many people expected to break SMT-based verification: recursive, pointer-centric kernel state with manual lifetimes. Its lasting contribution is a design pattern: keep the low-level representation efficient, flatten proof ownership, make memory explicit, and separate structural invariants from local transition proofs.

## Limitations

The paper does not solve fine-grained kernel concurrency: Atmosphere relies on a big lock, and the verified mediator example is single-threaded. Noninterference only covers syscall effects, not timing channels through shared hardware such as caches, and long-running operations can still leak timing because they hold the lock for a long time. The coarse revocation model is another tradeoff: killing a container is easier to verify than revoking arbitrary resources in place.

The trusted computing base also remains large. The proof trusts the Verus frontend, Z3, the Rust compiler and `core`, specifications for core primitives, extra axioms missing in Verus, tracked-permission setter code, trusted low-level Rust and assembly, the boot loader, and the underlying CPU/firmware platform. Atmosphere therefore reduces verification effort dramatically, but it does not eliminate trust.

## Related Work

- _Klein et al. (SOSP '09)_ - seL4 established the first practical verified microkernel, while Atmosphere pursues lower proof effort and faster iteration through SMT-based Rust verification.
- _Nelson et al. (SOSP '17)_ - Hyperkernel showed highly automated kernel verification, but only after constraining the kernel interface much more aggressively than Atmosphere does.
- _Lattuada et al. (SOSP '24)_ - Verus provides the linear-ghost and SMT-based foundation; Atmosphere shows how to shape a real microkernel around that verifier instead of verifying a small isolated component.
- _Zhou et al. (OSDI '24)_ - VeriSMo is another substantial Verus-based verified system, but its state is less recursively pointer-centric than a general-purpose microkernel.

## My Notes

<!-- empty; left for the human reader -->

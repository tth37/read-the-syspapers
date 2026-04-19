---
title: "A Hardware-Software Co-Design for Efficient Secure Containers"
oneline: "CKI uses PKS plus small ISA tweaks to create a container-kernel privilege level inside the host kernel, removing EPT and syscall-redirection overhead from secure containers."
authors:
  - "Jiacheng Shi"
  - "Yang Yu"
  - "Jinyu Gu"
  - "Yubin Xia"
affiliations:
  - "Institute of Parallel and Distributed Systems, SEIEE, Shanghai Jiao Tong University"
  - "Engineering Research Center for Domain-specific Operating Systems, Ministry of Education, China"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3717473"
tags:
  - virtualization
  - isolation
  - kernel
  - security
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CKI argues that secure containers need a third privilege level, but current CPUs only expose two natural software levels for applications and kernels. It uses PKS plus a few lightweight hardware changes to create that level inside ring 0, so each container keeps its own kernel without paying the usual EPT, shadow paging, or syscall-redirection costs. The prototype matches native syscall latency, cuts page-fault latency to 1.067 us, and improves nested-cloud secure containers by up to 72% on memory-intensive workloads and 6.8x on memcached throughput.

## Problem

The paper starts from a mismatch between the isolation structure of secure containers and the privilege structure of today's CPUs. OS-level containers are efficient, but they share one kernel and inherit its attack surface; the authors' survey of 209 Linux kernel CVEs exploitable from containers shows that most lead to denial of service. VM-level containers avoid that by giving each container a guest kernel, yet this effectively needs three privilege levels: container apps, container kernel, and host kernel. Commodity x86 gives software only two natural levels, so existing systems synthesize the third one in expensive ways.

Hardware-assisted designs such as Kata Containers rely on VMX, EPT, and nested virtualization machinery built for arbitrary VMs. That buys clean isolation, but it also imports costs containers do not need: two-dimensional page-table walks, EPT management, and slow nested VM exits. The paper cites 46% average latency overhead from two-dimensional page walks and measures 28%-226% slowdowns for page-fault-heavy workloads in nested clouds. Software-based virtualization such as PVM avoids L0 intervention, but shifts cost into syscall redirection and shadow paging.

## Key Insight

The key claim is that secure containers do not need full VM hardware semantics; they need a narrow privilege boundary around each guest kernel. CKI therefore treats container isolation as an intra-kernel isolation problem. If the guest kernel stays in ring 0 but loses access to dangerous memory and privileged instructions, then syscalls and user exceptions stay native, nested VM exits disappear, and two-stage translation can be removed because containers do not need a fake physical-address space.

## Design

Each secure container gets its own address space containing guest user processes, a guest kernel, and a kernel security monitor (KSM). PKS separates the guest kernel from the KSM inside that address space: the KSM runs with unrestricted PKRS, while the guest kernel runs with `PKRS_GUEST` and cannot access KSM memory. Because different containers already live in different address spaces, CKI needs only two PKS domains per container and sidesteps PKS's 16-domain limit.

PKS alone is not enough because it does not block privileged instructions. CKI therefore adds a small ISA extension: when PKRS is non-zero, destructive privileged instructions trap to the host. Harmless hot-path instructions such as `swapgs`, `sysret`, and `invlpg` remain executable, while `wrmsr`, `iret`, CR3 writes, and interrupt masking are mediated by the KSM or host kernel. A new `wrpkrs` instruction plus binary rewriting ensures PKRS changes happen only at approved gates.

Fast paths are reserved for frequent operations. Syscalls and user exceptions enter the guest kernel directly because it remains mapped into guest user address spaces. KSM calls handle private-data-only privileged work such as PTE updates and `iret`; hypercalls go to the host for operations touching global state such as VirtIO or timers. To avoid trusting `kernel_gs`, CKI maps a per-vCPU KSM area at a constant virtual address via per-vCPU top-level page-table copies.

Memory protection is enforced by monitoring page-table updates. CKI adopts nested-kernel-style invariants: only declared pages can be page-table pages, declared PTPs are read-only to the guest, and only declared top-level PTPs can enter CR3. Instead of shadow paging, each guest manages contiguous host-physical segments and writes hPAs directly into PTEs, with KSM validation on updates. CKI also hardens interrupts by placing the IDT, interrupt gates, and IST stacks in KSM memory and extending hardware-interrupt entry so PKRS is reset automatically, preventing forged interrupt jumps.

## Evaluation

The prototype runs Linux 6.7.0-rc6 as the guest kernel and adds about 2 KLoC plus fewer than 80 modified lines. Experiments use an AMD EPYC-9654 server with 125 GB memory; nested-cloud tests run inside a 16-vCPU, 16 GB L1 VM. Baselines are RunC, Kata Containers as hardware-assisted virtualization, and PVM.

The microbenchmarks line up with the design. A page fault costs 1,067 ns in CKI, versus 4,407 ns in PVM, 3,257 ns in bare-metal HVM, and 32,565 ns in nested HVM; only 77 ns of CKI's path comes from KSM calls for PTE updates and `iret`. A simple `getpid` syscall stays at roughly 90 ns, identical to RunC and HVM, while PVM takes 336 ns. In nested clouds, an empty hypercall costs 390 ns in CKI, 486 ns in PVM, and 6,746 ns in HVM because HVM still involves L0 intervention.

Application results are strongest where paging and exits dominate. On PARSEC and vmitosis memory-intensive workloads, CKI reduces latency by 24%-72% versus nested HVM, 1%-18% versus bare-metal HVM, and 2%-47% versus PVM, while staying within 3% of RunC. On TLB-miss-intensive GUPS and BTree lookup, CKI trims latency by 19% and 6% over bare-metal HVM. For I/O-heavy software, CKI improves SQLite throughput by up to 24% over PVM on tmpfs. In nested-cloud key-value stores, it reaches up to 6.8x memcached throughput and 2.0x Redis throughput over nested HVM, and 1.5x/1.3x over PVM.

## Novelty & Impact

The novelty is not merely applying PKS to secure containers; it is redefining the boundary so the guest kernel remains a kernel, but not a fully privileged one. CKI combines PKS, address-space isolation, monitored page-table writes, and interrupt-safe switch gates into a coherent third-privilege-level design. That is a different stance from VM-based secure containers and user-mode guest-kernel designs.

## Limitations

The biggest limitation is that CKI depends on hardware that does not yet exist in shipping CPUs. The prototype emulates `wrpkrs` with `wrpkru`, emulates PKRS switching on interrupt entry and `iret`, and uses Gem5 to argue the missing checks are cheap. That makes the results plausible, but not a measurement of the exact proposed hardware.

The memory design also trades utilization for speed. CKI allocates contiguous physical segments to each secure container so KSM validation stays cheap and the Linux buddy allocator remains effective, which can hurt utilization through fragmentation. Compatibility is also not free: the guest kernel needs para-virtualized hooks, a new boot flow, and CKI-specific restrictions on dynamic kernel code. Finally, CKI inherits the VM-level-container trust model, so the host kernel and KSM remain trusted, and transient-execution attacks within one secure container are out of scope.

## Related Work

- _Huang et al. (SOSP '23)_ - PVM avoids hardware virtualization in nested clouds via shadow paging and syscall redirection, whereas CKI removes both costs by giving the guest kernel a restricted in-kernel privilege level.
- _Van't Hof and Nieh (OSDI '22)_ - BlackBox protects containers from an untrusted OS with a security monitor and a shared kernel, while CKI instead keeps VM-level kernel separation to resist container-induced DoS.
- _Dautenhahn et al. (ASPLOS '15)_ - Nested Kernel monitors critical page-table operations in a deprivileged kernel; CKI adapts that invariant-driven style to per-container kernels and adds fast gates plus interrupt defenses.
- _Gu et al. (USENIX ATC '20)_ - UnderBridge isolates kernel components with virtualization-assisted intra-kernel domains, whereas CKI deliberately avoids reliance on virtualization hardware so it remains deployable in nested clouds.

## My Notes

<!-- empty; left for the human reader -->

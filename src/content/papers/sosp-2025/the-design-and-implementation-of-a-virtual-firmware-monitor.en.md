---
title: "The Design and Implementation of a Virtual Firmware Monitor"
oneline: "Miralis runs unmodified RISC-V vendor firmware in user space, traps privileged operations, and removes firmware from the TEE trusted base without slowing native OS execution."
authors:
  - "Charly Castes"
  - "François Costa"
  - "Neelu S. Kalani"
  - "Timothy Roscoe"
  - "Nate Foster"
  - "Thomas Bourgeat"
  - "Edouard Bugnion"
affiliations:
  - "EPFL, Switzerland"
  - "ETH Zurich, Switzerland"
  - "Cornell and Jane Street, USA"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764826"
tags:
  - virtualization
  - security
  - confidential-computing
  - formal-methods
category: embedded-os-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

This paper argues that vendor firmware does not need to share the CPU's highest privilege level with the security monitor. Miralis, a virtual firmware monitor (VFM) for RISC-V, runs unmodified firmware in user space as a virtual M-mode, traps privileged operations, and enforces policies that protect the OS, enclaves, or confidential VMs while preserving native OS performance through a small fast path.

## Problem

Modern TEEs depend on a tiny security monitor to protect enclaves or confidential VMs from an untrusted OS or hypervisor, but on real machines that monitor is usually co-located with vendor firmware at the most privileged CPU level. That makes the firmware part of the TCB even though firmware is large, vendor-specific, often closed-source, and routinely found to contain vulnerabilities. On RISC-V, systems such as Keystone place the security monitor alongside firmware in M-mode; on Arm, extra privilege levels separate components structurally, but the security monitor still depends on even more privileged firmware. In both cases the least-privilege story breaks at the last layer.

The obvious alternative, privilege-separating firmware itself, has been hard to deploy. Dorami shows it is possible on RISC-V, but it needs firmware refactoring and platform-specific binary scanning. The authors therefore ask a sharper question: can a system operator sandbox vendor firmware even when the firmware binary is opaque and unmodified, and can that be done without slowing the normal OS path?

## Key Insight

The paper's central insight is that the highest privilege mode can be virtualized just like a kernel can be virtualized, provided the ISA satisfies the classical Popek-Goldberg trap-and-emulate conditions. RISC-V M-mode meets those conditions: sensitive operations trap, so firmware can run in U-mode as a virtual M-mode while Miralis emulates privileged instructions, CSRs, interrupts, and machine resources.

That observation matters because it cleanly separates two concerns. Miralis handles generic firmware virtualization once, while isolation policies become pluggable modules layered on top. The system can therefore deprivilege firmware without requiring hardware changes, firmware modifications, or re-engineering each TEE monitor per platform.

## Design

Miralis is a 6.2 KLoC Rust monitor that executes in M-mode with interrupts disabled. Each hart is always in one of two worlds: direct execution for the native OS, or vM-mode for the virtualized firmware. Traps from vM-mode go through an instruction emulator and device/memory emulation; traps from the OS are either handled directly by Miralis or reinjected into the firmware. The emulator supports 12 privileged instructions and 84 CSRs using a shadow CSR state, then performs world switches by saving physical state, installing the right CSR view, changing permissions, flushing the TLB, and resuming the other world.

Memory protection is built around PMP virtualization. Miralis multiplexes the physical PMP entries so some always protect Miralis itself and virtual devices, while the remaining entries expose a virtual PMP interface to firmware. It also emulates awkward architectural details such as the default M-mode access semantics, ToR's implicit lower bound at address 0, and `mstatus.MPRV`, which it implements by trapping data accesses and performing them on the firmware's behalf. For devices, Miralis mostly avoids full virtualization: it forces delegation of non-M-mode interrupts, emulates the CLINT for timer/IPI handling, and blocks or would virtualize DMA-capable devices depending on IOPMP support.

The design is practical because current RISC-V firmware traffic is highly skewed. On the VisionFive 2, 99.98% of traps during Linux boot come from five causes, largely software emulation of optional architectural features. Miralis therefore adds a small fast path that directly handles those common SBI-style operations, especially time reads and timer/IPI operations, instead of always bouncing through virtualized firmware. Finally, Miralis exposes seven policy hooks and demonstrates three policies: a firmware sandbox for protecting the OS, a Keystone-derived enclave monitor, and an ACE-derived confidential-VM monitor.

The paper also treats specification as part of the design. The authors define faithful emulation and faithful execution as two criteria that connect a VFM to the ISA's authoritative semantics, translate the RISC-V Sail model to Rust, and use Kani to exhaustively symbolically execute critical Miralis paths against that reference.

## Evaluation

The evaluation is convincing on the main claim. Miralis virtualizes unmodified vendor firmware on two commercial boards, StarFive VisionFive 2 and SiFive HiFive Premier P550, by inserting itself between the first and second firmware stages. It also virtualizes RustSBI, Zephyr, and even a closed-source Star64 firmware image extracted from flash. That directly supports the portability claim: the approach is not limited to a single open firmware stack.

Performance results show that the OS path stays effectively native once common firmware operations are offloaded. Emulating one privileged instruction costs 483 cycles on VisionFive 2 and 271 cycles on Premier P550; a world-switch round trip costs 2704 and 4098 cycles respectively, but those switches become rare. With fast path enabled, Miralis reduces boot-time firmware interactions from roughly 5500 traps per second to about 1.17 per second, and the paper reports no measurable degradation across CoreMark-Pro, IOzone, Memcached, Redis, MySQL, GCC, or boot time. In several cases Miralis is slightly faster than the native firmware because its fast path is more efficient than the vendor implementation.

The negative result is equally important: current hardware still needs that fast path. Without offloading, reading time grows from 208 ns to 7.26 us and an IPI from 3.65 us to 39.8 us on VisionFive 2, with up to 29% boot-time overhead and large slowdowns on network-heavy workloads. The paper is honest here: the mechanism is sound, but today's RISC-V platforms still rely on firmware for operations that should eventually be handled by hardware extensions such as Sstc. The formal-methods part is also substantive rather than ornamental: the verification covers 2.7 KLoC, or 43% of Miralis, and found 21 bugs during development.

## Novelty & Impact

The main novelty is conceptual as much as implementation-level. Miralis introduces VFMs as a new software layer below TEEs: instead of building yet another enclave or CVM monitor that assumes privileged firmware is benign, it virtualizes firmware itself and turns security monitors into policy modules. Relative to Dorami, it gets privilege separation without firmware rewriting or binary scanning. Relative to existing TEE monitors, it removes vendor firmware from the TCB while preserving the same higher-level abstractions.

That makes the paper useful to two audiences. TEE designers get a deployment strategy for reducing trust in opaque firmware on existing RISC-V hardware. Verification and architecture researchers get a reusable methodology for deriving VFM checks from authoritative ISA models rather than hand-writing a second specification. The authors' O(N + M) portability argument is credible: once the VFM handles platform virtualization, multiple monitors can share that substrate.

## Limitations

The biggest limitation is architectural scope. The paper's clean story depends on RISC-V M-mode being classically virtualizable; Arm EL3 is not, so the same design would need paravirtualization or ISA changes. Even on RISC-V, the solution assumes platform-specific CSRs and MMIO regions are documented correctly. If a vendor hides privileged control paths or undocumented side effects, policy enforcement can be bypassed.

Security is also not end-to-end proven. The verified portion is large enough to matter but still leaves most of the code base, assembly, device emulation, and fast path in the TCB. Sandbox and Keystone policies are not formally verified, and DMA protection is strongest only when an IOPMP-like mechanism exists. The threat model excludes physical attacks, denial of service, and transient-execution side channels. Finally, ACE support is demonstrated on QEMU rather than real hardware, so that part establishes compatibility more than performance.

## Related Work

- _Lee et al. (EuroSys '20)_ — Keystone protects enclaves from an untrusted OS, but its original design still shares M-mode with firmware; Miralis ports Keystone as a policy while moving firmware out of the TCB.
- _Ferraiuolo et al. (SOSP '17)_ — Komodo uses verification to reduce enclave TCB size, whereas Miralis targets the privileged firmware layer that such monitors normally assume away.
- _Li et al. (OSDI '22)_ — Arm Confidential Compute Architecture isolates confidential VMs with ISA support, while Miralis shows how software-only firmware deprivileging can offer a similar trust reduction on existing RISC-V platforms.
- _Ozga et al. (HASP '23)_ — ACE provides a security monitor for confidential VMs; Miralis hosts ACE as a policy module and adds firmware isolation beneath it.

## My Notes

<!-- empty; left for the human reader -->

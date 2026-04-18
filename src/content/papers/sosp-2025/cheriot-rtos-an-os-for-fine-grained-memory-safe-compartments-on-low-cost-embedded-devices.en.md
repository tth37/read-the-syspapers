---
title: "CHERIoT RTOS: An OS for Fine-Grained Memory-Safe Compartments on Low-Cost Embedded Devices"
oneline: "CHERIoT RTOS combines CHERI-only compartments, capability quotas, and firmware auditing so low-cost MCUs can get memory-safe isolation and micro-rebootable services."
authors:
  - "Saar Amar"
  - "Tony Chen"
  - "David Chisnall"
  - "Nathaniel Wesley Filardo"
  - "Ben Laurie"
  - "Hugo Lefeuvre"
  - "Kunyan Liu"
  - "Simon W. Moore"
  - "Robert Norton-Wright"
  - "Margo Seltzer"
  - "Yucong Tao"
  - "Robert N. M. Watson"
  - "Hongyan Xia"
affiliations:
  - "Apple"
  - "Microsoft"
  - "SCI Semiconductor"
  - "Google"
  - "University of British Columbia"
  - "University of Cambridge"
  - "ARM Ltd."
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764844"
tags:
  - kernel
  - security
  - hardware
  - isolation
  - fault-tolerance
category: embedded-os-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CHERIoT RTOS argues that cheap embedded devices can get strong isolation only if the hardware and OS are designed together around CHERI capabilities. The result is an MMU-less RTOS with memory-safe compartments, quota-controlled sharing, interface-hardening APIs, and firmware auditing that still fits the cost envelope of tens to hundreds of kilobytes of RAM.

## Problem

The paper starts from a simple embedded-systems mismatch: the cheapest and most widely deployed devices often run legacy C/C++ firmware, lack an MMU, and are still expected to sit on networks or critical infrastructure. That makes ordinary memory-corruption bugs and software-supply-chain mistakes disproportionately dangerous.

Existing defenses miss the target. MPU- and TrustZone-based designs isolate only at coarse granularity, so they cannot cheaply split many small components or safely share fine-grained objects across distrustful code. Automatic compartmentalization of legacy firmware helps only partway because it does not solve interface hardening, fault recovery, or auditability. Full rewrites into safe languages are also unattractive when deployments depend on old code, binary-only components, and regulatory constraints. The paper therefore wants stronger isolation without giving up low cost or realistic migration paths.

## Key Insight

The core claim is that embedded isolation becomes practical when CHERI capabilities are the only protection mechanism on an MMU-less core. If every pointer already carries bounds, permissions, and tags, the machine can enforce spatial safety directly, and the OS can express least privilege in terms of capability propagation instead of coarse memory regions.

That hardware substrate matters because it supports the exact operations the OS needs: temporal safety via a load filter and revoker, deeper delegation control via `permit-load-mutable` and `permit-load-global`, and richer sealing/sentry behavior for cross-compartment calls. The OS then turns those primitives into compartments, opaque objects, quota-controlled allocation, TOCTOU-resistant claims, and micro-rebootable fault domains. The paper's remembered proposition is therefore that capability-safe sharing is the enabling programming model, not just a low-level enforcement trick.

## Design

The architecture has four trusted components: a boot-time loader, a switcher for context and compartment transitions, a shared-heap allocator, and a scheduler. Compartments are static code-and-data domains; threads are also static and can move between compartments only through declared entry points. Shared libraries run inside the caller's domain, which keeps code reuse cheap without blurring protection boundaries.

The most important co-design choice is to make CHERI the only isolation mechanism. Temporal safety comes from revocation bits, a load filter that clears tags on capabilities to freed objects, and a background revoker that eventually makes memory reusable. Delegation is stronger than ordinary read/write stripping because capabilities can enforce deep immutability and deep no-capture, while sentries structure cross-compartment control flow and interrupt posture.

Above that substrate, the OS exposes the abstractions that make the model usable. Opaque objects let callers hold another compartment's per-flow state without mutating it. Allocation capabilities attach explicit quotas and free authority to heap use, and quota delegation lets a service allocate on behalf of its caller. Interface-hardening APIs de-privilege shared capabilities, validate inputs, and use claims to block free-based TOCTOU attacks. Error handlers and micro-reboot support make compartments actual fault-containment domains, and the linker emits a JSON report so external tools can audit imports, MMIO access, and quotas with Rego policies before deployment.

## Evaluation

The evaluation is honest about the absence of a direct apples-to-apples baseline: there is no comparable embedded platform that offers this mix of fine-grained isolation and memory safety on CHERIoT hardware. The authors therefore combine code-size accounting, microbenchmarks, porting studies, and an end-to-end IoT case study on a 33 MHz Arty A7 FPGA board with 256 KiB of SRAM.

The cost results are credible for the paper's target. The CHERIoT core adds about 4.5% area over a 16-entry PMP design, and bare-metal CoreMark slows by 20.65% relative to non-CHERI RISC-V 32E. At the OS level, the base system is 25.9 KB of code and 3.7 KB of data, with only 18.4 KB of code remaining after the loader erases itself at boot. An empty compartment call costs 209 cycles on average, a call using 256 B of stack costs 452 cycles, and interrupt latency averages 1028 cycles, about 31 microseconds at 33 MHz. The allocator also sustains about 5 MiB/s on network-relevant buffer sizes above 1 KiB, which is enough to keep up with a 10 Mbit link.

The strongest evidence is the full-system demonstration. A JavaScript IoT application using MQTT over TLS runs in 13 compartments and fits in 243 KB total memory. When the authors inject a crash into the TCP/IP stack, the stack micro-reboots in 0.27 seconds and the application reconnects. Porting evidence also supports the source-compatibility claim: the FreeRTOS TCP/IP stack and BearSSL run with wrappers rather than rewrites, while Microvium runs essentially unmodified. Taken together, these experiments support the central claim that the design is deployable on real low-cost embedded profiles, though the lack of direct competitive baselines means the paper proves feasibility more than dominance.

## Novelty & Impact

Relative to the earlier MICRO'23 CHERIoT hardware paper, the novelty here is the OS and programming model: the compartment/thread structure, the least-privilege TCB split, opaque objects, quota delegation, interface hardening, and firmware auditing. Relative to prior embedded isolation work, the main move is to make memory safety, sharing, recovery, and auditing all consequences of one capability substrate rather than separate add-ons.

That is useful both practically and conceptually. Practically, it offers a migration path for embedded C/C++ code that cannot be rewritten or moved onto MMU-heavy hardware. Conceptually, it shows how a capability architecture can shape OS APIs, deployment policy, and recovery mechanisms, not just low-level access checks.

## Limitations

The design depends on strong assumptions. The CHERIoT hardware and TCB must be correct, physical attacks and side channels are out of scope, and integrators still have to write sensible error handlers and auditing policies. The system also cannot stop logic bugs that never trap, and repeated trap-triggering can still cause denial of service by forcing continual micro-reboots.

Deployment costs remain real. CHERIoT needs specialized hardware, targets source compatibility rather than binary compatibility, and sometimes requires nontrivial wrappers around existing services. Dynamic allocation is also discouraged in strictly deterministic phases because revocation is asynchronous. The evaluation is therefore convincing on feasibility, but it leaves open how the design behaves across broader hardware generations and production toolchains.

## Related Work

- _Amar et al. (MICRO '23)_ — the earlier CHERIoT hardware paper provides the capability ISA, load filter, and revoker; this SOSP paper builds the OS structure and programming model that make those features useful to software.
- _Levy et al. (SOSP '17)_ — Tock uses Rust to get memory safety on tiny embedded devices, whereas CHERIoT RTOS targets legacy C/C++ components, stronger compartment boundaries, and explicit firmware auditing.
- _Clements et al. (USENIX Security '18)_ — ACES automatically partitions embedded software on existing hardware, but CHERIoT argues that coarse retrofit isolation is not enough for safe sharing, temporal safety, or hardened interfaces.
- _Zhou et al. (EuroSys '22)_ — OPEC isolates bare-metal embedded operations with existing hardware, while CHERIoT couples new capability hardware with fault-tolerant compartments and capability-safe delegation.

## My Notes

<!-- empty; left for the human reader -->

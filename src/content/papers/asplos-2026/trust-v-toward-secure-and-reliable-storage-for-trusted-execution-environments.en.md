---
title: "Trust-V: Toward Secure and Reliable Storage for Trusted Execution Environments"
oneline: "Locks storage-controller MMIO and runs driver fragments in sandboxed Virtual-M mode so TEEs get integrity-protected persistent storage without new hardware."
authors:
  - "Seungkyun Han"
  - "Jiyeon Yang"
  - "Jinsoo Jang"
affiliations:
  - "Chungnam National University, Daejeon, Requblic of Korea"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790242"
code_url: "https://github.com/Trust-V-opensource/Trust-V"
tags:
  - confidential-computing
  - storage
  - security
  - kernel
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Trust-V argues that TEE persistent storage integrity can be enforced by treating the storage controller's MMIO path as the control point, rather than by trusting the rich OS or requiring new secure-storage hardware. It partitions an SD card into trusted and untrusted regions, locks the controller MMIO from Linux, and runs only small instrumented driver fragments inside a sandboxed M-mode called Virtual-M. On a RISC-V prototype, that design preserves TEE-owned storage access while keeping ordinary block I/O overhead small.

## Problem

The paper starts from a real gap in many TEE stacks. Systems such as SGX, OP-TEE, and Keystone already support sealing or encrypting enclave data before writing it to disk, so confidentiality is preserved even if the OS is hostile. But integrity is weaker: a compromised OS can still delete sealed files, reformat partitions, redirect requests, or overwrite encrypted blobs with ransomware-like writes. Hash checks detect some tampering after the fact, but they do not stop the OS from corrupting the storage namespace that enclaves depend on.

That makes persistence awkward for any enclave that needs long-lived state rather than transient checkpoints. The paper's examples include enclave data pages, a key-value store, and a device root key used by the security monitor. Existing hardware-backed options, such as RPMB-style storage or other secure-storage features, are not always available on the legacy or cost-sensitive devices that TEEs increasingly target. On RISC-V in particular, optional features such as PMP support in commodity SoCs and H-extension virtualization may be missing or immature. The systems problem is therefore: how do we give TEEs storage whose integrity survives a malicious OS, while assuming only broadly available processor features?

## Key Insight

The paper's core claim is that persistent-storage integrity can be reduced to a narrow I/O mediation problem. If the untrusted OS cannot directly touch the storage controller's MMIO registers or the secure transfer buffer, and if every request aimed at a TEE-owned partition is checked by trusted code that knows the request's provenance and owner, then the OS loses the power to silently mutate enclave state on disk.

What makes this practical is the authors' decision not to move an entire driver stack into privileged firmware. Instead, Trust-V uses the highest privilege level only as a sandbox for tiny MMIO-handling fragments that already exist in the Linux driver. Virtual-M mode combines M-mode execution with `MPRV`, shared page tables, and temporarily enabled `SUM`, so those fragments can access protected MMIO and trusted buffers while still respecting kernel-style virtual-memory permissions. In other words, the design spends privilege only on the minimal instructions that must touch the controller, and keeps policy in metadata maintained by the security monitor.

## Design

Trusted Storage divides physical media into a non-trusted region for normal Linux state and several trusted partitions reserved for the security monitor and individual enclaves. Trust-V states four concrete requirements: the OS must be blocked from the controller MMIO and secure I/O buffer, the TCB should stay small, each trusted partition must have a unique owner, and I/O requests must be verifiable and tamper-resistant.

The first layer is memory isolation. Trust-V marks protected regions such as the locked MMIO area, the secure I/O buffer, and the Virtual-M stack as user pages and normally clears `SUM`, so S-mode Linux cannot access them. Because `SUM` can sometimes be enabled legitimately and because U-mode should not see those regions either, the security monitor also removes mappings to trusted memory during context changes and when needed. To stop Linux from undoing that setup, Trust-V deprivileges the OS: writes to registers such as `SATP`, `SSTATUS`, and `STVEC`, and page-table modifications, are replaced with `ECALL`s that trap into the security monitor for validation and emulation. Shared page tables are marked read-only so the OS cannot silently remap protected regions.

The second layer is M-mode sandboxing. Physical-M mode is the fully privileged monitor context that edits metadata and page tables. Virtual-M is the constrained context used for secure I/O: code executes in M-mode, but memory accesses are forced through the kernel's page tables via `MPRV`, and `SUM` is enabled only so the driver fragment can touch trusted memory. Entry and exit are carefully controlled with `enterVirtualM()` and `exitVirtualM()`. The monitor uses `MEPC`, overwrites `RA`, and disables interrupts so the sequence "enter, run the designated fragment, exit" is atomic and cannot be hijacked by a loadable module or a ROP chain.

Trust-V then builds a storage protocol around metadata. The monitor records the locked device, the secure-I/O context, and a mapping table from trusted partition numbers to enclave hashes. Partition 0 is reserved for the monitor; enclave partitions start at 1 and are assigned on demand. A secure I/O request begins when an enclave asks to read or write its trusted partition. The monitor fills in metadata, exposes a 4 KB secure buffer to the enclave, and later checks the request in two phases: the command phase verifies the target MMIO and sector range, and the data phase verifies that transfers use the protected buffer and updates the transferred-block count after each block exchange. The design intentionally uses raw blocks rather than a filesystem inside Trusted Storage so that no filesystem code has to be ported into the TEE.

## Evaluation

The prototype runs on a SiFive HiFive Unleashed board with a U540-C000 SoC, 8 GiB DRAM, Linux `5.10.186`, Keystone `v1.0.0`, and a Samsung 64 GB Evo Plus microSD card. The implementation totals `5,053` lines of code, including `1,223` LoC in the Linux kernel and only `66` LoC of Virtual-M driver logic. That small privileged code footprint matters because much of the security argument depends on the offloaded fragment being easy to audit.

At the system level, CoreMark-Pro shows no significant overhead, but LMBench exposes the real cost of the design: operations that frequently trap through the monitor for page-table or status-register mediation see up to `3.86x` slowdown, and file deletion latency rises by as much as `45%`. The authors explain that this comes less from secure storage itself than from repeated mode switches caused by protecting sensitive kernel operations. For storage workloads on ordinary, non-trusted ext4 data, the picture is better. Fio reports at most `6.6%` throughput loss, IOzone overhead stays at or below `0.2%`, and mount overhead is negligible. That supports the paper's deployment claim: the extra mediation is visible, but it does not make the whole block stack unusable.

The application-level results are more mixed and therefore more informative. Simple enclave block I/O to Trusted Storage takes about `0.14-0.55 s` for reads and `0.15-0.58 s` for writes across `512 B` to `4 KB` transfers. Compared with a baseline that seals data and stores it in non-trusted storage, Trust-V is slightly faster for the tested `4 KB` case, by about `0.6%` on writes and `0.3%` on reads, because it avoids encryption, decryption, and filesystem overheads. The key-value store experiment shows that reads have negligible overhead, but write-heavy workloads are more expensive: `key_put` and `key_delete` reach `52%` overhead at 32 operations and a maximum of `2.05x` at 64 operations. Finally, provisioning a device root key through the monitor takes about `0.83 s`, split into `0.55 s` to fetch the key material and `0.28 s` to derive and map the enclave key. Overall, the evaluation supports the main claim for SD-card-backed TEEs on legacy RISC-V hardware, though it says less about faster media, high concurrency, or multi-device systems.

## Novelty & Impact

Relative to sealing-based TEE storage such as _Lee et al. (EuroSys '20)_ on Keystone or vendor secure-storage stacks such as OP-TEE, Trust-V's novelty is that it protects the storage path itself, not just the bytes after encryption. Relative to hardware-assisted secure I/O proposals such as _Dhar et al. (NDSS '20)_, its contribution is occupying the opposite point in the design space: no new hardware, but tighter software control over MMIO, page tables, and request provenance. Relative to intra-mode privilege separation work, the interesting move is using RISC-V `MPRV` plus shared page tables to create a practical, driver-facing M-mode sandbox rather than an all-powerful monitor.

That should make the paper useful to two groups. TEE architects can cite it as a concrete design for integrity-protected persistence on feature-poor SoCs. Systems builders working on RISC-V monitors or secure peripherals can cite it as evidence that careful privilege structuring around existing drivers may be enough to prototype secure I/O before specialized hardware arrives.

## Limitations

The paper is explicit about several assumptions. It trusts secure boot, M-mode firmware, and the host and peripheral hardware, and it excludes physical attacks, side channels, and denial-of-service against enclave invocation. Those are reasonable scoping choices, but they matter because the storage-integrity guarantee only holds inside that trust model.

There are also practical limits. Trust-V serializes secure I/O through one monitored context, uses raw blocks instead of a filesystem, and requires recompilation to change the number or size of trusted partitions. The write path can be significantly slower for update-heavy applications, and the whole system is evaluated on an SD-card stack rather than a faster NVMe-class device where fixed monitor-transition costs may dominate differently. The prototype also disables Keystone's PMP use to emulate legacy hardware, so the paper demonstrates feasibility more than it demonstrates the best possible implementation.

## Related Work

- _Lee et al. (EuroSys '20)_ — Keystone provides an open RISC-V TEE framework, but Trust-V extends that ecosystem with integrity-protected persistent storage rather than only enclave isolation and sealed swapping.
- _Dhar et al. (NDSS '20)_ — ProtectIOn secures I/O on compromised platforms using stronger hardware support, whereas Trust-V deliberately targets general-purpose RISC-V features and software mediation.
- _Feng et al. (ASPLOS '24)_ — sIOPMP adds scalable hardware I/O protection for TEEs; Trust-V is the software-centric counterpart for systems that do not yet have such support.
- _Shinagawa et al. (VEE '09)_ — BitVisor uses a thin hypervisor to enforce I/O device security, while Trust-V offloads only minimal driver fragments into sandboxed M-mode and specializes the mechanism for TEE-owned storage.

## My Notes

<!-- empty; left for the human reader -->

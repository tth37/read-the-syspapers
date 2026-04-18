---
title: "TeeM3: Core-Independent and Cooperating Trusted Execution Environments"
oneline: "Moves TEE isolation out of CPU modes into tile-level controllers so CPU and accelerator TEEs can cooperate through locked channels and exclusive regions."
authors:
  - "Nils Asmussen"
  - "Sebastian Haas"
  - "Carsten Weinhold"
  - "Nicholas Gordon"
  - "Stephan Gerhold"
  - "Friedrich Pauls"
  - "Nilanjana Das"
  - "Michael Roitzsch"
affiliations:
  - "Barkhausen Institut, Dresden, Germany"
  - "TU Dresden, Dresden, Germany"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790232"
code_url: "https://github.com/Barkhausen-Institut/M3-Bench"
tags:
  - confidential-computing
  - security
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

TeeM3 argues that TEEs for heterogeneous systems should not be implemented as special CPU modes. Instead, it puts isolation in a tile-level communication controller, adds exclusive memory regions and lockable communication channels, and uses a small root of trust plus a bare-metal runtime to let CPU and accelerator TEEs cooperate. On the authors' FPGA prototype, this adds low runtime overhead while reducing the hardware TCB by `1.8x` and the software TCB by `3.42x` relative to standard M3.

## Problem

The paper starts from a mismatch between where modern workloads run and where TEEs exist. Real embedded and edge systems increasingly span CPUs, accelerators, memory controllers, and I/O devices, but mainstream TEE designs are usually tied to a single processor architecture. If one stage of an IoT or cyber-physical pipeline runs on an accelerator, existing platforms either leave that stage outside the TEE boundary or bolt on another accelerator-specific TEE. That raises complexity and makes secure cross-component communication a special-case engineering problem instead of a property of the platform.

The authors also object to how current TEEs inherit the weaknesses of the cores that host them. When protection is implemented as a special processor mode, the TEE shares microarchitectural state with other software and with privileged system code. That leaves it exposed to the long line of side-channel attacks the paper cites against in-core TEE designs. Even if those attacks are ignored, the firmware and hidden microcode that implement existing TEEs still sit inside the trusted computing base.

M3, the base hardware/software co-design platform used here, already has strong tile isolation, but it is not yet a TEE architecture. Its kernel can reconfigure every TCU, parent services still own child resources, TileMux changes state while loading programs, and the kernel must remain able to reclaim a misbehaving tile. TeeM3 therefore has to solve four concrete problems at once: remove the kernel from confidentiality and integrity, give TEEs exclusive resource ownership, keep resource reclamation possible, and make the measured state predictable enough for remote attestation.

## Key Insight

The central idea is that heterogeneous TEEs become tractable once isolation is enforced by a hardware component outside the compute core. In TeeM3, each tile already has a trusted communication unit (TCU) that mediates cross-tile memory and message traffic. By teaching that component two new rules, "only authorized tiles may access this memory region" and "once this tile is locked, channel changes require the tile's consent," the system can treat CPUs, accelerators, and even the root-of-trust tile through the same protection model.

That shift matters because it changes what must be trusted. A TEE no longer needs to trust a privileged kernel, TileMux, or core-specific enclave firmware for confidentiality and integrity. The OS becomes remote system software: it can still load binaries, propose channel changes, and kill a tile for availability, but it cannot silently read TEE memory or splice itself into already-protected communication paths. In the authors' framing, out-of-core enforcement is what makes cooperation among heterogeneous TEEs a platform feature instead of a collection of ad hoc crypto tunnels.

## Design

TeeM3 extends each TCU with exclusive memory regions. These are power-of-two, size-aligned regions registered in the receiving tile's TCU rather than permissions stored only in the sender. For every incoming memory request, the TCU checks whether the requester owns an overlapping exclusive region; if not, access is denied. This is what strips parent services and even the kernel of implicit access to a TEE's private memory. The same mechanism also supports cooperating TEEs by allowing shared ownership of selected regions. Region management stays in RoT firmware, which records when a region is "closed" for attestation and zeros memory before final reuse.

The second hardware mechanism is tile locking. Once a tile enables its lock bit, the kernel can no longer rewrite endpoint registers outright. Instead, TeeM3 uses a propose-freeze-accept protocol: a kernel write freezes the endpoint, the TEE inspects the proposed configuration, and only the TEE can unfreeze it with the new settings. This keeps dynamic channel setup possible without handing channel integrity back to the kernel. Generation counters handle the harder case where the kernel resets a tile and reuses an old communication path; endpoints become invalid if their stored generation does not match the tile's current counter.

On the software side, TeeM3 replaces TileMux with UniMux for both TEEs and the remote-attestation service. UniMux is a much smaller Rust library that supports exactly one activity on one eagerly mapped address space and refuses page-table manipulation requests from the kernel. This avoids the self-referential attestation problem where the runtime that must be measured is still mutating during load. It also means TEEs run bare-metal on a tile while still using OS services through TCU-backed protocols.

The root of trust is itself a dedicated tile with a boot ROM, multi-stage firmware, a SHA-3 accelerator, and the remote-attestation service (RAS). Following a DICE-style sequence, it measures later firmware stages, derives attestation keys, measures the kernel and base services, then locks itself and serves attestation requests. RAS also manages exclusive regions and only removes a region after checking that the owning tile's generation counter increased, which prevents the kernel from tearing down live TEE memory behind the application's back.

## Evaluation

The evaluation runs on an FPGA prototype built on a Xilinx VCU118 board with eight processing tiles, two memory tiles, a 2x2 star-mesh NoC, Rocket and BOOM RISC-V cores for user and kernel tiles, and PicoRV32 cores for the RoT and AES accelerator tiles. This matters because the paper is not simulating a conceptual design; it is measuring a full M3-derived platform with both CPU and accelerator TEEs.

The low-level results support the paper's main engineering claim. Creating communication endpoints as a TEE costs less than `4%` more than in a non-TEE setup, and steady-state communication has effectively zero extra cost because TCU channels bypass the kernel instead of forcing enclave exits or cryptographic wrapping. Exclusive-region checks are cheap for DRAM-heavy accesses, below `1.5%` slowdown even with all `16` configured regions active, because the checks overlap with slow off-chip reads. They are more noticeable for on-chip scratchpad memory, where the worst-case slowdown reaches about `20%`, which is a real cost but also the paper's most latency-sensitive microbenchmark.

The accelerator experiments are more persuasive than the microbenchmarks because they exercise the "cooperating heterogeneous TEEs" story directly. Across AES streaming, file hashing through the RoT's SHA-3 unit, and an IoT-style pipeline that encrypts data and hashes the ciphertext, TeeM3 stays below `5%` overhead, mostly from setup and teardown of locks and exclusive regions. At the application level, LevelDB running as a TEE shows no measurable slowdown on the authors' workloads. The architectural tradeoff is similarly modest: adding TEE support raises TCU LUTs by about `19%` and FFs by about `27%`, yet the overall confidentiality/integrity hardware TCB is still `1.8x` smaller than standard M3, while the software TCB shrinks from `248,308` to `72,587` RISC-V instructions. That evidence is strongest for M3-like tiled systems, not for commodity multicore servers, but within that scope it supports the paper's claim well.

## Novelty & Impact

Relative to SGX-, TDX-, or Keystone-style TEEs, TeeM3's key novelty is not attestation itself but relocating enforcement out of the processor core and into a uniform per-tile controller. Relative to CURE and HECTOR-V, its distinctive move is to make heterogeneous cooperation first-class: the same enforcement substrate protects general-purpose tiles, accelerator tiles, and the RoT while still exposing OS services through remote protocols. That combination of out-of-core isolation, cooperation, and TCB accounting is the paper's real contribution.

I expect this paper to matter most to researchers and practitioners building confidential embedded or cyber-physical platforms, especially where workloads naturally cross CPUs and accelerators. It is a mechanism paper with a clear systems thesis: if heterogeneity is the norm, TEE enforcement has to become more modular than "one enclave mode per processor type."

## Limitations

TeeM3 does not make the kernel harmless; it moves the kernel into the availability TCB instead of eliminating it. A malicious kernel can still freeze endpoints, deny service, reset tiles, or refuse to create channels. The design also assumes the TCUs and NoC are trusted, and it leaves timing attacks, power side channels, rowhammer-style effects, and NoC/DRAM interference outside scope unless extra protection such as memory encryption is added at the SoC boundary.

The tile abstraction also imposes a deployment constraint: one TEE per tile. The paper explicitly says lifting that restriction would complicate the TCB because the TCU could no longer guarantee which in-tile software receives a message or owns a memory region. Message passing is intentionally less restrictive than memory access as well, so TEEs must filter unexpected senders themselves and accept that the kernel can still create nuisance traffic. Finally, the whole system is built around custom M3 hardware and an FPGA prototype, so the paper is a convincing architecture demonstration, but not yet evidence that the same design would be cheap to retrofit into mainstream SoCs.

## Related Work

- _Lee et al. (EuroSys '20)_ - Keystone keeps TEE support anchored in CPU firmware and a security monitor, whereas TeeM3 moves enforcement into a separate tile-level mechanism shared across processing-unit types.
- _Bahmani et al. (USENIX Security '21)_ - CURE also pushes some protection outside the core, but TeeM3 emphasizes cooperating heterogeneous TEEs and reports a smaller confidentiality/integrity hardware TCB than CURE.
- _Nasahl et al. (AsiaCCS '21)_ - HECTOR-V is closer architecturally, yet TeeM3 argues its own design is more flexible because TEEs and accelerators can use OS services and cooperate through the same TCU abstraction.
- _Tang et al. (ASPLOS '19)_ - HIX secures CPU-GPU interaction as a specialized pairing, while TeeM3's goal is one uniform enforcement model for arbitrary accelerators and other tiles.

## My Notes

<!-- empty; left for the human reader -->

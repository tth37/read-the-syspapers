---
title: "Erebor: A Drop-In Sandbox Solution for Private Data Processing in Untrusted Confidential Virtual Machines"
oneline: "Erebor turns a confidential VM into per-client sandboxes that block both the guest OS and the service code from exfiltrating data, without requiring hypervisor changes."
authors:
  - "Chuqi Zhang"
  - "Rahul Priolkar"
  - "Yuancheng Jiang"
  - "Yuan Xiao"
  - "Mona Vij"
  - "Zhenkai Liang"
  - "Adil Ahmad"
affiliations:
  - "National University of Singapore"
  - "Arizona State University"
  - "ShanghaiTech University"
  - "Intel Labs"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3717464"
code_url: "https://github.com/ASTERISC-Release/Erebor"
tags:
  - confidential-computing
  - security
  - virtualization
  - isolation
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Confidential VMs keep the host out, but they do not stop the guest OS or the service itself from leaking client data. Erebor inserts a small privileged monitor inside the guest kernel, uses it to build per-client sandboxes with mediated memory, exits, and I/O, and avoids any hypervisor or paravisor changes. On Intel TDX, the prototype runs real CPU-bound services with 4.5%-13.2% runtime overhead and cuts memory use by up to 89.1% through secure sharing of common read-only state.

## Problem

The paper targets a realistic SaaS setting: clients send sensitive inputs to a service provider running inside a confidential VM rented from a cloud provider. From the client's point of view, both the service provider and the cloud provider are honest-but-curious. That means the usual CVM guarantee is insufficient. TDX, SEV, and similar TEEs protect guest memory from the host, but they still let the guest OS, the service program, and cooperating software inside the VM see and leak the client's data.

The authors make the threat model concrete with three attack classes. First, the guest OS can read or remap the program's memory and inspect register state during interrupts. Second, the service program can leak data directly via syscalls or hypercalls. Third, it can use those same exits as covert channels by encoding data in arguments, frequencies, or other software-visible behavior. In other words, the paper is not trying to protect a trusted enclave from an untrusted OS; it is trying to protect client data from the whole software stack that processes it.

Prior CVM-isolation systems such as Veil and NestedSGX do not fully solve that problem. They use VM partitioning to create enclave-like compartments, which helps against OS reads, but they still trust the code inside the compartment not to exfiltrate data. They also need cloud-side support from the hypervisor or paravisor. Erebor's bar is stricter: stop both outside reads and intentional disclosure by the sandboxed program, while remaining deployable by a tenant as a drop-in guest-side change.

## Key Insight

The key insight is that the right trusted component is not a new enclave partition or a whole replacement OS, but a very small monitor embedded inside ring 0 and protected from the rest of the guest kernel by intra-kernel privilege isolation. If that monitor exclusively controls the handful of interfaces that determine confidentiality, namely MMU state, critical control registers and MSRs, interrupt/exception dispatch, and guest-host communication, then the ordinary kernel can be treated as a deprivileged service layer rather than part of the trust base.

That observation matters because it lets Erebor provide a stronger sandbox than enclave-style CVM systems without asking the cloud provider for new platform support. Once the monitor owns all writable mappings, all exits, and the attested communication path, the sandbox can run a service-provider program plus a LibOS for convenience, yet still be forbidden from talking to the OS or hypervisor after client data arrives. The result is a data-processing sandbox, not just a memory-isolated compartment.

## Design

Erebor has two major pieces: Erebor-Monitor in privileged guest-kernel mode and Erebor-Sandbox for each client request. The monitor is established by a two-stage boot. First, firmware and the monitor load and get measured. Then the monitor loads a deprivileged Linux kernel after checking that sensitive instructions have been removed or instrumented. Those sensitive operations include CR/MSR writes, IDT installation, `stac`, and `tdcall`; the kernel must request them through an Erebor-Monitor-Call gate instead.

The protection story is built from standard x86 features, but the composition is the paper's main systems idea. PKS protects monitor memory and page-table state from the normal kernel. SMEP and SMAP stop the kernel from executing or reading user pages outside the monitor's mediation. CET indirect-branch tracking constrains entry into the monitor to a deterministic gate, and interrupts are wrapped so that any temporary permissions to monitor memory are revoked before control returns to the OS. The monitor also enforces W^X on kernel memory and validates dynamic code paths it still allows.

Inside the sandbox, memory is split into confined and common regions. Confined pages hold code, heap, stacks, temporary files, and client data; only the sandbox may write them. Common pages hold large shared assets such as models or databases; multiple sandboxes may map them, but once client data is installed they become read-only from the sandbox's point of view. Confined pages are pinned to avoid secret leakage through paging, and DMA exposure is blocked by keeping sandbox memory private and tightly controlling guest-host communication.

The runtime story is equally important. Erebor uses a Gramine-derived LibOS to emulate heap management, an in-memory filesystem, threading, synchronization, and I/O helpers inside the sandbox. After client data is delivered, the monitor forbids software-controlled exits: syscalls, synchronous VM exits, and user interrupts cause the sandbox to be killed. Normal timer and device interrupts are handled by saving and masking the sandbox context, letting the OS run, and then resuming the sandbox. `cpuid` is the special case: the monitor emulates it once and caches the result. Client communication goes through a secure monitor-client channel bootstrapped by TDX attestation, and the monitor copies input and output through a reserved `ioctl` interface while padding output sizes and zeroing sandbox memory on teardown.

## Evaluation

The evaluation is careful about decomposition. The authors compare against native CVM execution and also run ablations that isolate LibOS cost, memory-view isolation cost, and exit-protection cost. At the mechanism level, an empty Erebor monitor call costs 1224 cycles, versus 684 for an empty syscall and 5276 for a TDX `tdcall`. The expensive case is MMU manipulation: a page-table entry update grows from 23 cycles natively to 1345 cycles under Erebor, a 58.5x increase, because it now goes through the gated monitor path. That sounds alarming, but the paper correctly argues that these operations are relatively infrequent and should be judged in end-to-end workloads rather than in isolation.

That broader view is the paper's strongest empirical evidence. Across five CPU-bound services, `llama.cpp`, YOLO image processing, Drugbank retrieval, GraphChi PageRank, and the Unicorn intrusion detector, Erebor adds 4.5%-13.2% runtime overhead, with an 8.1% geometric mean. The ablation numbers are useful: LibOS-only overhead is just 1.7% on average, while memory isolation and exit protection contribute 3.6% and 3.9%. The highest overhead is `llama.cpp` at 13.15%, driven by large shared-memory footprints, page faults, and synchronization. On the memory side, secure common-memory sharing reduces usage by 0.15x-9.2x, up to 89.1%; the paper's example is especially compelling, shrinking eight replicas of a roughly 4 GB model from about 36 GB to about 8 GB.

The evaluation also shows the tradeoff clearly. System-event latency can rise by as much as 3.8x in LMBench, and initialization overhead ranges from 11.5% to 52.7% because pre-allocation and page faults are monitor-mediated. Background non-sandboxed I/O services also pay some system-wide cost: average throughput drops 8.2% for OpenSSH and 5.1% for Nginx. This all supports the paper's central claim of practicality, although not universal cheapness. One reviewer-style caveat is that the prototype uses DebugFS to emulate the communication path instead of a real network relay, so the I/O path is not evaluated end to end in production form.

## Novelty & Impact

The paper's main novelty is the combination of two ideas that were usually separate: intra-kernel privilege separation as a systems mechanism, and anti-exfiltration sandboxing as a confidentiality goal. Relative to Veil, the novelty is not just "another CVM monitor." Erebor changes the trust boundary by assuming the service code itself is adversarial once it holds client data, then designing the sandbox so that no ordinary syscall or VM-exit path remains available. Relative to SGX-style anti-leakage systems like Ryoan and Chancel, Erebor shows how to obtain a similar security objective inside modern CVMs without compiler-enforced SFI or new cloud-side partition support.

That makes the paper interesting to both confidential-computing and OS-isolation communities. If its threat model matches a deployment, especially private inference, information retrieval, or per-client analytics inside a shared CVM, then the system offers a plausible middle ground between heavyweight one-VM-per-client designs and enclave schemes that trust in-sandbox code too much. The broader contribution is a new mechanism in service of a new framing: full data sandboxing inside a CVM, rather than just stronger guest memory encryption.

## Limitations

The prototype stops short of a production-ready cloud stack. It supports CPU-only applications and explicitly leaves accelerators, trusted device I/O, timing channels, and microarchitectural side channels out of scope. The actual communication path in the prototype is DebugFS-based, not a deployed network transport. Linux support for CET backward-edge shadow stacks was incomplete, so the implementation uses forward-edge CET but omits the full backward-edge story envisioned by the design.

Compatibility is also narrower than the headline might suggest. The monitor currently disables huge pages, loadable kernel modules, and eBPF to simplify fine-grained protection-key enforcement. Sandbox applications need modest source changes around the monitor-mediated `ioctl` interface, and the LibOS runs the container in a single address space with pre-created threads. Finally, the evaluation compares mainly to native CVM baselines and ablations, not directly to VMPL-based competitors, so the paper demonstrates practicality and stronger threat coverage more clearly than it demonstrates superiority to every alternative.

## Related Work

- _Ahmad et al. (ASPLOS '24)_ - Veil also protects data inside CVMs, but it trusts enclave code and depends on VMPL-style partitioning, whereas Erebor assumes the service program may leak data and stays guest-side only.
- _Hunt et al. (OSDI '16)_ - Ryoan is the closest anti-exfiltration predecessor conceptually, but it uses NaCl-style software fault isolation for distributed services rather than a privileged in-guest monitor for CVMs.
- _Ahmad et al. (NDSS '21)_ - Chancel shows efficient multi-client isolation with shared memory under adversarial SGX code; Erebor imports a similar goal into confidential VMs and enforces it with page-table and exit mediation.
- _Dautenhahn et al. (ASPLOS '15)_ - Nested Kernel pioneered the intra-kernel privilege-separation technique that Erebor adapts from kernel hardening to confidential-data sandboxing.

## My Notes

<!-- empty; left for the human reader -->

---
title: "TickTock: Verified Isolation in a Production Embedded OS"
oneline: "TickTock replaces Tock's monolithic MPU process abstraction with a Flux-verified granular design that proves embedded process isolation and fixes real kernel bugs."
authors:
  - "Vivien Rindisbacher"
  - "Evan Johnson"
  - "Nico Lehmann"
  - "Tyler Potyondy"
  - "Pat Pannuto"
  - "Stefan Savage"
  - "Deian Stefan"
  - "Ranjit Jhala"
affiliations:
  - "UCSD"
  - "NYU"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764856"
tags:
  - kernel
  - security
  - verification
  - isolation
category: verification-and-reliability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

TickTock is a verification-guided fork of the Tock embedded OS that proves each process can access only its own code and RAM on all supported ARMv7-M platforms and three 32-bit RISC-V platforms. The key move is to replace Tock's monolithic MPU abstraction with a granular one that keeps the kernel's logical memory layout aligned with what the hardware actually enforces, then verify the kernel, MPU drivers, and ARM interrupt path in Flux. In the process, the authors found seven Tock bugs, six of which broke isolation.

## Problem

Tock already sits in security-critical deployments such as Google Security Chip and Microsoft's Pluton 2, so its process isolation is not an academic nicety. A compromised application that can read or write kernel memory can steal secrets, brick the device, or take over the OS. Rust helps only partway: it isolates kernel components from each other and prevents many confused-deputy mistakes, but Tock applications can be written in arbitrary, memory-unsafe languages, and the microcontrollers Tock targets do not have MMUs.

That leaves Tock relying on MPUs or RISC-V PMP to isolate user processes. The problem is that these mechanisms are awkward to program. ARM Cortex-M regions have power-of-two size and alignment constraints, optional subregions, and per-process dynamic reconfiguration. The kernel must also switch between privileged and unprivileged execution modes correctly while handling interrupts and context switches. The obvious implementation strategy is to hide the hardware quirks behind one high-level process-memory abstraction, but the paper shows that this is exactly where Tock went wrong: the abstraction mixed logical process layout with low-level MPU constraints, forced the kernel to recompute memory boundaries, and let the kernel's view of accessible memory diverge from the hardware's real view.

The paper illustrates the stakes with concrete bugs found during verification. One bug let process-owned subregions overlap kernel-owned grant memory. Another omitted the ARM mode switch when jumping to a process, so code could run privileged and bypass the MPU entirely. A third let integer underflow in `update_app_mem_region` turn malformed `brk` inputs into a kernel crash. The core problem is therefore not just "verify Tock," but redesign the process abstraction so isolation is both true and tractable to prove.

## Key Insight

The central insight is that verification becomes practical when the kernel stops pretending it can abstract away MPU constraints with a single monolithic interface. Instead, the kernel should ask the hardware layer for explicit regions that already satisfy alignment and sizing rules, then store the exact accessible boundaries those regions imply.

That shift fixes two issues at once. First, it removes entanglement: process allocation logic no longer needs to reason about subregions, power-of-two rounding, or register encodings. Second, it removes disagreement: the kernel's remembered `app_break`, `kernel_break`, and memory extent are derived from the same region descriptors that will later be written to hardware, so it does not need to reconstruct them heuristically. Once those exact boundaries exist, Flux can prove layered invariants over the kernel's logical state, the hardware-facing region abstraction, and the assembly-level interrupt path. The remembered proposition is that the right abstraction boundary is the enabling mechanism for verification, not just a cleanup of existing code.

## Design

TickTock replaces Tock's original `allocate_app_mem_region` and `update_app_mem_region` style interface with a granular split between a `RegionDescriptor` abstraction and a narrower `MPU` interface. `RegionDescriptor` captures the abstract properties of one enforced region, such as start, size, overlap, and whether the region is active, while hiding architecture-specific details like ARM subregions or the more flexible RISC-V PMP layout. The `MPU` trait then exposes methods such as `new_regions`, `update_regions`, and `configure_mpu`, which deal only with creating or reconfiguring hardware-valid regions.

The kernel-side allocator becomes generic over those abstractions. To allocate process RAM, it asks the MPU layer for up to two contiguous regions spanning at least the requested process memory. From those returned regions, the kernel computes the actual enforced start and size of process-accessible RAM and records them in an `AppBreaks` structure. `AppBreaks` carries the logical boundaries that matter for isolation: the beginning of process memory, its size, the end of process-accessible memory (`app_break`), and the start of kernel-owned grant memory (`kernel_break`). Flux invariants then require, among other things, that `app_break < kernel_break`, so user RAM and grant memory never overlap.

The proof is layered. First, the authors refine `RegionDescriptor` with logical predicates such as abstract `start`, `size`, `matches`, and `can_access`. Second, they verify that the kernel's logical view of each process matches Tock's intended memory model. Third, they prove that the array of stored regions and the `AppBreaks` structure correspond exactly: flash is readable and executable, process RAM is readable and writable, and other memory remains inaccessible. Finally, they verify the ARMv7-M and RISC-V MPU drivers against those contracts by relating register contents to the abstract region semantics.

Interrupts are handled separately for ARMv7-M through `FluxArm`, a Rust-executable formalization of the relevant ISA subset. The authors model inline assembly handlers, mode-switching, stack-save/restore behavior, and exception return, then prove that after a process is preempted the machine returns to a privileged kernel state with the required registers and MPU assumptions intact. This matters because one of the real bugs they found was precisely a missing mode switch in context-switch assembly.

## Evaluation

The evaluation is aimed at feasibility rather than headline throughput, and for this paper that is the right target. First, the authors ran differential testing on 21 upstream Tock applications. On ARM hardware they used an nRF52840dk board; on RISC-V they used QEMU. TickTock and Tock both completed the tests, and the five output differences were expected because those tests inspected memory layout or sensor output. That is reasonable evidence that the verified fork still behaves like the production OS.

Performance on ARM is close to Tock and occasionally better. `setup_mpu` is about `8.08%` slower, which is the clearest regression. But several paths are faster because TickTock no longer recomputes MPU-derived layout information: `allocate_grant` improves by `50.32%`, `brk` by `21.71%`, `build_readonly_buffer` by `20.00%`, and `build_readwrite_buffer` by `34.02%`. Application-level context switching is effectively unchanged: upstream Tock averages `32,640` cycles versus `32,740` for TickTock, roughly `0.3%` overhead.

The verification-time results are arguably the paper's strongest quantitative win. The granular redesign cuts the kernel verification workload from `5m19s` for the monolithic design to `36s`, with most kernel functions checking in under a second and a mean of `0.05s` per function. Interrupt verification is still expensive, taking `2m34s`, but the whole project remains under three minutes. The proof effort totals about `3.6 KLOC` of checked specifications over `22 KLOC` of Rust. That supports the paper's main claim: the redesign is not merely more elegant, it is substantially easier to verify.

## Novelty & Impact

The paper's novelty is not "Rust plus proofs" in the abstract. It is the combination of a verification-guided redesign and a full end-to-end isolation argument for a production embedded OS that already existed. Prior verified kernels often start from proof-oriented designs or target hypervisors and microkernels; TickTock instead retrofits machine-checked process isolation into Tock, a deployed MCU OS with real hardware constraints and inline assembly in the hot path.

That makes the result important beyond Tock itself. The paper shows that Rust's baseline safety is not enough around privilege transitions, MPU programming, and arithmetic edge cases, but also that these areas can be brought under automated verification if the abstraction boundary is chosen carefully. Embedded OS and firmware teams are likely to cite it as evidence that partial but strong verification of isolation can fit a production engineering workflow rather than a research-only clean-slate kernel.

## Limitations

The proof target is process isolation, not full functional correctness. TickTock does not prove liveness, fairness, side-channel resistance, or the correctness of the broader capsule ecosystem. The interrupt proof is also ARMv7-M specific; the paper verifies RISC-V MPU drivers, but not an equivalent RISC-V interrupt path.

The trusted base is still meaningful. The implementation contains trusted functions used for solver limitations, proof scaffolding, and out-of-scope routines, and the ARM and RISC-V hardware semantics are lifted from architecture manuals rather than derived inside Flux. Some arithmetic lemmas had to be proved separately in Lean because SMT solvers timed out on the required bit-level alignment facts. So the result is strong, but it is not a minimal-TCB theorem in the seL4 sense.

The empirical evaluation is also bounded. Performance numbers are only for ARM, and the application testing is a differential sanity check over 21 programs, not a broad study of deployment workloads or adversarial stress. The paper convincingly demonstrates that the verified design is practical and inexpensive, but not that it exhaustively characterizes every failure mode of Tock in the field.

## Related Work

- _Levy et al. (SOSP '17)_ - Tock introduced safe multiprogramming on tiny devices with MPU-backed isolation; TickTock is a verified fork that hardens exactly that process abstraction.
- _Mai et al. (ASPLOS '13)_ - ExpressOS used Dafny to verify security invariants in a newly designed C# kernel, whereas TickTock retrofits verification into an existing Rust embedded OS.
- _Li et al. (USENIX Security '21)_ - SeKVM verifies memory protection for a commodity hypervisor; TickTock brings comparable machine-checked isolation reasoning to MPU-based microcontroller processes.
- _Johnson et al. (S&P '23)_ - WaVe verifies a Rust WebAssembly sandbox runtime, while TickTock verifies kernel, MPU, and interrupt machinery for OS-level process isolation on bare metal.

## My Notes

<!-- empty; left for the human reader -->

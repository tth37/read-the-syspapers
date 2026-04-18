---
title: "Tock: From Research to Securing 10 Million Computers"
oneline: "Tock turns Rust's type system, capsules, grants, and a redesigned syscall ABI into a deployed secure embedded OS that now protects tens of millions of devices."
authors:
  - "Leon Schuermann"
  - "Brad Campbell"
  - "Branden Ghena"
  - "Philip Levis"
  - "Amit Levy"
  - "Pat Pannuto"
affiliations:
  - "Princeton University"
  - "University of Virginia"
  - "Northwestern University"
  - "Stanford University"
  - "University of California, San Diego"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764828"
tags:
  - kernel
  - security
  - isolation
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

This is a ten-year systems retrospective on Tock, a secure embedded OS in Rust that grew from a research platform for sensor networks into production firmware protecting tens of millions of machines. The paper's main lesson is that Rust helped Tock make isolation and least privilege practical on tiny devices, but only after the kernel ABI and internal structure were redesigned to respect Rust's ownership and soundness rules rather than emulate a conventional C kernel.

## Problem

Tock started from a hard niche: microcontrollers with roughly 100 kB of RAM, no virtual memory, primitive memory protection, many peripherals, and strict energy constraints. Deployments such as Signpost wanted multiple concurrent applications, portability across different boards, and robustness even when an application or driver was buggy. Conventional embedded OSes usually put everything in one protection domain, expose ad hoc driver interfaces, and offer little help if one component corrupts memory or exhausts shared kernel resources.

The stakes rose when Tock moved from urban sensing into hardware roots of trust. These chips store keys, verify boot images, and sit at the base of system security in laptops, servers, and security tokens. The problem the paper addresses is therefore not merely "can Rust implement an embedded kernel," but how a research OS can evolve into production security firmware without losing soundness, deployability, or extensibility.

## Key Insight

The paper's core claim is that Rust becomes a systems advantage only when the OS architecture is deliberately shaped around the language's semantics. Tock's durable ideas all turn privilege or ownership into explicit structure: capsules forbid `unsafe` and isolate most kernel extensions with the type system; grants keep per-process kernel state inside that process's protected memory region; capabilities turn privileged APIs into zero-cost typed permissions. These mechanisms let Tock preserve strong boundaries on hardware that lacks the resources for heavyweight isolation.

The flipside is equally important. Whenever Tock treated Rust like "safer C," it ran into soundness trouble. Asynchronous system calls that let capsules hold userspace references opaquely, aliased mutable buffers passed through `allow`, and null zero-length slices all violated Rust assumptions in subtle ways. The lasting insight is that production deployment did not invalidate the original research design; it revealed exactly where ownership, aliasing, and lifetime rules had to be made first-class in the ABI itself.

## Design

Tock divides the system into hardware-isolated userspace processes, a small privileged kernel core and chip-specific layer, and semi-trusted kernel extensions called capsules. Capsules are Rust crates in which `unsafe` is forbidden, so they can touch only their own state and explicit safe interfaces. To make a single-stack asynchronous kernel workable in Rust, Tock uses interior mutability for circular references between components, accepting extra runtime checks and careful reentrancy handling in exchange for a simpler structure than message passing.

Two other original choices matter for dependability. The kernel is heapless: per-application dynamic state lives in that application's protected memory via grants, so one process can exhaust only its own memory. And the kernel plus syscall ABI are fully asynchronous, which matched the original low-power sensor-network use case.

Root-of-trust deployments forced the big redesigns. To support sound Rust userspace, Tock v2.0 gave `allow` and `subscribe` swapping semantics so the kernel, not capsules, owns shared buffers and callbacks; it also added `allow-readonly` for flash-resident keys. Signed per-application updates turned process loading into an asynchronous state machine that checks structure, authenticity, and runnability. The paper also highlights later Rust-specific techniques: compile-time driver composition checks, the `SubSlice` abstraction for split-phase buffers, typed MMIO descriptions, and capability-style privileges.

## Evaluation

This is an experience paper, so the evidence is longitudinal rather than benchmark-centric. The strongest result is deployment itself. Tock moved from the Signpost research platform to Google's OpenSK and Ti50, then to server roots of trust, secure laptop boot, automotive systems, and space systems; the paper says the OS now secures tens of millions of computers. That breadth is the main result: the paper is about which design decisions survived real products.

The case studies are concrete enough to be informative. Oxide rejected Tock because asynchronous userspace was the wrong fit for its fixed sequential services and built Hubris; Ti50 forked partly because asynchronous syscall sequences were costly in code size on RISC-V. Security deployments pushed other changes upstream, including signed process loading and the v2.0 syscall redesign. Figure 5 adds one quantitative signal: between 2018 and 2024 the kernel grew substantially while the number of `unsafe` blocks stayed roughly flat. What is missing is a controlled comparison against Zephyr, NuttX, or Hubris on performance, memory overhead, or exploit resistance.

## Novelty & Impact

Relative to _Levy et al. (SOSP '17)_, this paper explains what scaled from research prototype to production root-of-trust OS and what had to be rewritten. Relative to Rust OS efforts such as RedLeaf or Theseus, its novelty is the mixed-language, security-critical setting: Tock must preserve Rust's guarantees across hostile process boundaries and real deployment constraints, not only within an all-Rust kernel.

Its impact is twofold. Technically, it distills reusable patterns such as capsules without `unsafe`, grants, swapping syscalls, `SubSlice`, typed MMIO, and capabilities. Institutionally, it argues that a research OS can stay useful for follow-on work in security and verification while also shipping in real products.

## Limitations

The paper is a retrospective written by long-time Tock maintainers, so much of the evidence is qualitative and self-reported. It gives a convincing account of design pressure from real deployments, but it does not rigorously isolate the contribution of Rust from hardware protection, project stewardship, or the needs of root-of-trust chips. Readers looking for broad embedded-kernel benchmarks or controlled experiments will not find them here.

Several tensions also remain unresolved. Asynchronous userspace is still awkward for many sequential applications, integrating third-party libraries safely remains an open problem, and Rust does not prevent subtle logic bugs in timer virtualization or memory protection. Industrial adopters may still fork rather than upstream changes, so the paper's lessons are strongest for small, security-sensitive MCUs rather than general-purpose kernels.

## Related Work

- _Levy et al. (SOSP '17)_ - The original Tock paper introduced safe multiprogramming on a 64 kB computer; this SOSP 2025 paper explains which parts of that design survived real deployment and which had to change.
- _Narayanan et al. (OSDI '20)_ - RedLeaf also explores isolation and communication in a safe OS, but it is framed as a Rust OS architecture rather than a decade-long account of deploying an embedded root-of-trust kernel.
- _Boos et al. (OSDI '20)_ - Theseus pushes Rust-native OS structure further by assuming Rust components throughout, whereas Tock focuses on preserving soundness at the boundary to legacy applications and hardware.
- _Rindisbacher et al. (SOSP '25)_ - TickTock verifies isolation in production Tock, illustrating how Tock's deployed interfaces became a substrate for later formal assurance work.

## My Notes

<!-- empty; left for the human reader -->

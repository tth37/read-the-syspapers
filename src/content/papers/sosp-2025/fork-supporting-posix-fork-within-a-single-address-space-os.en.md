---
title: "µFork: Supporting POSIX fork Within a Single-Address-Space OS"
oneline: "µFork emulates POSIX processes inside one address space by relocating CHERI-tagged pointers on demand, preserving fork semantics without reintroducing multiple address spaces."
authors:
  - "John Alistair Kressel"
  - "Hugo Lefeuvre"
  - "Pierre Olivier"
affiliations:
  - "The University of Manchester"
  - "The University of British Columbia"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764809"
code_url: "https://github.com/flexcap-project/ufork"
tags:
  - kernel
  - isolation
  - memory
category: embedded-os-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

µFork shows that a true single-address-space OS can support POSIX `fork` without falling back to per-process page tables or VM cloning. It does so by treating the child as a new region inside the same virtual address space, using CHERI tags to find and relocate absolute pointers, and replacing copy-on-write with a more selective copy-on-pointer-access policy.

## Problem

Single-address-space operating systems promise fast IPC, cheaper context switches, and lower memory footprint because the kernel and applications live in one shared address space. That design is attractive for unikernels, FaaS runtimes, and other lightweight systems, but it collides head-on with a large class of real software: multiprocess POSIX applications built around `fork`. The problem is structural, not cosmetic. Traditional `fork` duplicates a process into a fresh address space, and the separation between parent and child is what simultaneously delivers isolation and the expected memory semantics.

Prior attempts solve only part of that problem. Early SASOS designs such as Mungi relied on segment-relative addressing so a copied process could be moved without rewriting arbitrary pointers, but that assumption no longer fits modern ISAs, toolchains, JITs, and handwritten assembly. Other systems keep compatibility by delegating `fork` to a host OS or hypervisor, or by reintroducing multiple address spaces internally. Those approaches regain POSIX behavior, but they give up the defining benefit of SASOSes: lightweightness from a single address space. The paper therefore asks for a stricter target: can a SASOS preserve one address space, preserve POSIX semantics, preserve isolation, and still beat a conventional kernel on fork-heavy workloads?

## Key Insight

The paper's central claim is that the hard part of SASOS `fork` is not copying bytes, but relocating authority. If the child lives at a different virtual address range inside the same address space, any absolute pointer copied from the parent still points back into the parent's memory. A correct design therefore needs a reliable way to distinguish pointers from ordinary data and then retarget only the pointers that cross protection boundaries.

µFork uses CHERI to make that feasible. CHERI capabilities carry bounds and permissions, and valid capabilities are tagged in memory. Compiling code as PIC means most references are already relative to the stack, base pointer, or program counter and do not need rewriting. What remains are absolute references embedded in memory or registers. µFork can identify them by tag, relocate them into the child's region, and rely on CHERI bounds to ensure the relocated references do not escape that region. That turns "fork inside one address space" from a compiler fantasy into a runtime operation.

## Design

µFork introduces the notion of a `µprocess`: a POSIX-like process abstraction whose memory occupies one contiguous region inside the global address space. On `fork`, the kernel reserves a new contiguous region for the child, copies the parent's page-table entries so that parent and child initially share most physical pages, duplicates process resources such as file descriptors, and creates a new thread with a new PID to run the child. Some structures, including allocator metadata and GOT entries, are copied eagerly so the child resolves globals and heap state against its own region from the start. Absolute references already sitting in registers are relocated before the child begins execution.

The memory-sharing optimization is where the design departs from ordinary copy-on-write. Standard CoW is insufficient because a child can read a stale pointer from a shared page long before either side writes to that page. µFork therefore defines Copy-on-Access (CoA), where any child access to a shared page may trigger a copy and relocation, and then refines it into Copy-on-Pointer-Access (CoPA). Under CoPA, ordinary reads can stay shared, but if the child loads a capability from a shared page, that page is copied first. The implementation uses a CHERI page-table bit that faults on capability loads. On the fault path, µFork allocates a private page, copies the page contents, scans it in 16-byte capability-sized chunks, and relocates every tagged capability that still targets the parent's region. Writes by either side also trigger copies, as in CoW.

Isolation is handled at two levels. Between `µprocess`es, CHERI's monotonic bounds ensure a process cannot forge a capability with wider access, and CoPA ensures parent capabilities are not silently leaked into the child. Between user code and the kernel, µFork uses sealed capabilities for trapless system-call entry, removes the permission needed to execute privileged instructions, validates syscall arguments, and copies by-reference buffers into kernel memory to block TOCTTOU attacks. Importantly, the paper makes this isolation parameterized: a deployment can enable full adversarial isolation for privilege separation, lighter fault isolation for trusted-but-buggy code, or disable some checks for fully trusted workloads such as Redis snapshotting.

## Evaluation

The prototype is built on Unikraft, ported to CHERI on Arm Morello, and compared against CheriBSD running natively plus Nephele's VM-based results where direct artifact comparison is not possible. The microbenchmarks establish the basic claim. Forking a minimal process takes 54 µs in µFork, versus 197 µs on CheriBSD and 10.7 ms in Nephele. The proportional memory cost of a forked minimal process is 0.13 MB, compared with 0.29 MB on CheriBSD and 1.6 MB in Nephele. On Unixbench's Context1 IPC benchmark, µFork finishes in 245 ms versus 419 ms, supporting the paper's claim that preserving a single address space matters not just for `fork` latency but also for post-fork communication.

The application studies make the story more convincing. For Redis background snapshots, overall save time is lower across database sizes: 1.8 ms versus 3.4 ms at 100 KB, and 109 ms versus 158 ms at 100 MB. With a 100 MB database, the forked Redis child consumes 6 MB under µFork versus 56 MB on CheriBSD. The paper also isolates the benefit of CoPA: at that same database size, a full synchronous copy would cost 23.2 ms and 144 MB, CoA reduces that to 283 µs and 101 MB, and CoPA drops further to 260 µs and 6 MB. For a MicroPython Zygote-style FaaS benchmark, µFork serves 24% more functions per second than CheriBSD, which is exactly the regime where fork latency dominates. Nginx results are more mixed: µFork runs the unmodified server and on a single core beats single-core CheriBSD by 9%, but the paper also admits that Unikraft's immature SMP support prevents a strong multi-core comparison.

## Novelty & Impact

Relative to segment-relative SASOSes, µFork's novelty is practical modernity: it works with PIC binaries and runtime relocation rather than demanding a special addressing model throughout the stack. Relative to Graphene or Nephele, its novelty is architectural honesty: the system really remains a single-address-space OS instead of outsourcing `fork` to another protection domain. Relative to prior isolation work, the paper's contribution is not just "use CHERI," but "use CHERI tags, bounds, and load barriers together to recreate POSIX `fork` semantics within one address space."

That makes the paper relevant to several communities. SASOS and unikernel researchers get the first fully articulated path to transparent `fork` without abandoning their core model. Capability-system and CHERI researchers get a concrete systems payoff beyond memory safety. Systems builders working on Redis-like snapshots, prewarmed language runtimes, or privilege-separated services get evidence that the awkward dependence on `fork` is not incompatible with lightweight kernels after all. This is both a new mechanism and a strong reframing of what "POSIX compatibility for SASOSes" should mean.

## Limitations

The design is tightly coupled to CHERI, especially for the best-performing version. The paper argues that other tagging mechanisms could help identify pointers, but it explicitly says it knows of no non-CHERI mechanism that can fault precisely on capability loads in the way CoPA needs. That means the cleanest version of µFork is not obviously portable to mainstream commodity hardware today.

The prototype also inherits engineering constraints from Unikraft and from its chosen memory layout. Each `µprocess` occupies a large contiguous virtual region, so long-lived or highly forking workloads may eventually hit fragmentation pressure. The implementation uses statically allocated private heaps, which simplifies the TCB but inflates the cost of the "full copy" baseline. Multi-core Nginx scaling is undercut by Unikraft's current big-kernel-lock SMP story rather than by µFork itself, so the concurrency case is plausible but not fully demonstrated. Finally, most measurements are on Morello/CHERI, and the Nephele comparison is partly indirect because Nephele is x86_64-only.

## Related Work

- _Heiser et al. (SPE '98)_ — Mungi preserves a single address space through segment-relative addressing, whereas µFork targets modern PIC toolchains and relocates tagged absolute references at runtime.
- _Tsai et al. (EuroSys '14)_ — Graphene supports multiprocess applications by piggybacking on the host OS's `fork`, while µFork implements `fork` within the SASOS itself.
- _Lupu et al. (EuroSys '23)_ — Nephele clones unikernel VMs to emulate `fork`, but µFork keeps kernel and child inside one address space and therefore preserves fast IPC and much lower fork overhead.
- _Lefeuvre et al. (ASPLOS '22)_ — FlexOS studies how to compose multiple isolation mechanisms inside library OSes; µFork builds a concrete POSIX `fork` design on top of that broader intra-address-space isolation agenda.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Ghost in the Android Shell: Pragmatic Test-oracle Specification of a Production Hypervisor"
oneline: "Embeds executable ghost-state specifications into Android's pKVM and checks them at runtime, finding real hypervisor bugs without a heavyweight proof stack."
authors:
  - "Kayvan Memarian"
  - "Ben Simner"
  - "David Kaloper-Meršinjak"
  - "Thibaut Pérami"
  - "Peter Sewell"
affiliations:
  - "University of Cambridge, UK"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764817"
code_url: "https://github.com/rems-project/linux/tree/pkvm-verif-6.4"
tags:
  - virtualization
  - security
  - formal-methods
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

The paper does not fully verify Android's pKVM. Instead, it embeds executable ghost-state specifications in C, records abstract state at lock and trap boundaries, and checks that the implementation reached an allowed post-state. That middle ground exposed real pKVM bugs and many specification mistakes while staying practical for testing.

## Problem

pKVM sits at Arm EL2 and isolates the Android host kernel from protected VMs. Assurance is hard because the hypervisor is conventional C and assembly, runs bare-metal, manipulates page tables that the hardware also walks implicitly, and is concurrent with the host, guests, and other CPUs. Ordinary kernel testing can show that the system boots, but not whether each hypercall preserves the intended ownership and mapping invariants.

Full functional verification is the other obvious route, but the authors argue that it still demands specialist tooling, verification-oriented code structure, and high maintenance cost. The paper asks whether there is a usable middle ground: rich executable specifications in the implementation language, strong enough to check functional behavior, but cheap enough to apply to an existing production hypervisor.

## Key Insight

The key move is to define a reified ghost state that captures the meaning of pKVM state rather than its concrete representation. The spec records abstract mappings, ownership annotations, VM metadata, and per-CPU state as C data structures with a clear mathematical interpretation.

Each hypercall or trap is then specified as a function from recorded pre-state to expected post-state. This only works if recording follows pKVM's real ownership discipline: a component is captured when the implementation owns it, typically at trap entry or exit and at lock acquire or release, instead of imposing a global lock that would distort concurrency.

## Design

The ghost state includes pKVM's own mapping, the host's annotation and shared mappings, guest VM metadata, globals, and per-CPU locals. Concrete Arm page tables are traversed by abstraction functions that turn them into finite maps from input pages to output pages plus permissions and ownership attributes.

Instrumentation is narrow. Thread-local state is recorded at top-level trap entry and exit, and shared state is recorded when the relevant locks are acquired and released. For `host_share_hyp`, the checker snapshots the host and pKVM page-table abstractions, computes the expected transition, and compares it with the recorded post-state. The specification is much shorter than the implementation: it converts addresses, checks that the page is exclusively host-owned, inserts the abstract mappings, and updates the saved return register.

The authors keep the specs loose where exact behavior is not semantically important. They parameterize specs by observed return codes and reads from shared memory, and they allow behaviors such as `-ENOMEM` without modeling allocator internals. Around this, they build a `hyp-proxy` kernel patch, EL2 coverage tooling, an OCaml test library, and a model-guided random generator so testing can explore interesting states without immediately crashing the host.

## Evaluation

The feasibility story is solid. The handwritten suite has 41 tests: 19 success paths, 22 error paths, and a few concurrency-heavy cases. For the `__pkvm_host_share_hyp` path used as the running example, the authors report 100% line coverage once unreachable KVM helper code is excluded. Across all specification functions, coverage is 92%: 459 of 497 lines.

Random testing is guided rather than blind. In QEMU on a Mac Mini M2, it runs about 200,000 hypercalls per hour, with 24-hour runs, and it found nine specification bugs concentrated in subtle error cases. The broader effort found five pKVM bugs acknowledged by developers, including a host-pagefault race that could panic the hypervisor. Only one of those five came from runtime specification checking directly; the others were found while understanding the code well enough to write the spec.

The cost argument is also plausible. pKVM is about 11 KLoC, while the specification and support code total about 14 KLoC. The authors estimate roughly one person-year of work versus around 30 person-years of pKVM development. Runtime overheads are about 18 MB of memory, 3.2x slower boot in QEMU, and 11.5x slower handwritten tests. Those numbers would be unacceptable in production, but they are acceptable for a test oracle.

## Novelty & Impact

The paper's contribution is not a new verifier or a new hypervisor mechanism. It shows that post hoc, full-functional executable specs in plain C can work for a concurrent production hypervisor whose semantics depend on low-level hardware translation state.

That matters because many kernel or hypervisor teams will not adopt a full proof stack. This paper offers a cheaper path that is still stronger than sanitizers and integration tests.

## Limitations

The coverage is partial. The work does not specify device assignment, GIC, or IOMMU behavior, and it targets functional correctness rather than side channels, denial of service, or liveness.

Some concurrency corners remain out of scope, especially phased hypercalls that drop and retake locks and races around page-table updates. Because the ghost machinery mirrors implementation ownership, significant refactors can also require substantial spec maintenance.

## Related Work

- _Amit et al. (SOSP '15)_ — Virtual CPU validation tests hypervisor instruction emulation against ISA-level expectations, while this paper specifies pKVM hypercall and memory-ownership behavior that had no pre-existing formal oracle.
- _Bornholt et al. (SOSP '21)_ — The Amazon S3 work also uses executable ambient-language specifications for differential checking, but this paper extends that style to a concurrent bare-metal hypervisor in C rather than a user-space storage node in Rust.
- _Bishop et al. (JACM '19)_ — Engineering with Logic argues for post hoc test-oracle specifications over existing network code; this paper brings the same philosophy to EL2 hypervisor code and runtime state abstraction.
- _Cebeci et al. (SOSP '24)_ — Practical verification of standard-C systems components aims for stronger automated guarantees, whereas this paper accepts weaker guarantees in exchange for immediate deployment on existing production code and conventional tooling.

## My Notes

<!-- empty; left for the human reader -->

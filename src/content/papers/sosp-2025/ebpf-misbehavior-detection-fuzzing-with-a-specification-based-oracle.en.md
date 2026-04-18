---
title: "eBPF Misbehavior Detection: Fuzzing with a Specification-Based Oracle"
oneline: "Veritas pairs eBPF fuzzing with a Dafny specification oracle to catch both unsafe programs the Linux verifier accepts and safe ones it wrongly rejects."
authors:
  - "Tao Lyu"
  - "Kumar Kartikeya Dwivedi"
  - "Thomas Bourgeat"
  - "Mathias Payer"
  - "Meng Xu"
  - "Sanidhya Kashyap"
affiliations:
  - "EPFL"
  - "University of Waterloo"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764797"
code_url: "https://github.com/rs3lab/veritas"
tags:
  - ebpf
  - kernel
  - security
  - fuzzing
  - formal-methods
category: verification-and-reliability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Veritas pairs a generator with SpecCheck, a Dafny model of eBPF instruction semantics and safety properties, and treats any disagreement with the Linux verifier as a bug. That makes the oracle precise enough to catch both unsafe accepts and safe rejects, yielding 13 core verifier discrepancies and 15 total bugs in the authors' campaign.

## Problem

The Linux eBPF verifier is the gatekeeper for code that will execute inside the kernel, so verifier bugs create either usability problems or security problems. Rejecting a safe program wastes developer time and obscures the verifier's intended rules; accepting an unsafe program can leak pointers, hang the kernel, or enable privilege escalation. The paper argues that both are operationally important because eBPF is already used pervasively in tracing, networking, and policy enforcement.

Prior approaches each miss part of that space. Formal verification has mainly covered narrow pieces such as range analysis. Alternative verifiers such as Prevail offer cleaner semantics but must keep pace with a moving production implementation. Existing fuzzers explore the verifier well, but their oracles are indirect: they rely on KASAN, UBSAN, or runtime state mismatches, so they mainly catch bugs that manifest after execution and are weak at explaining the verifier's actual semantic error. The authors organize the missed cases into four root causes: abstraction imprecision (RC1), inconsistent safety rules (RC2), implementation mistakes (RC3), and buggy optimizations such as unsound path pruning (RC4).

## Key Insight

The key idea is to turn "is this concrete eBPF program safe?" into SMT-checkable proof obligations over an exact executable specification. SpecCheck therefore models the eBPF VM's dynamic types directly, including uninitialized data, scalars, non-null pointers, nullable pointers, region identities, and offsets, instead of relying on the verifier's own abstractions.

The other half is to write the verifier's intended policy down explicitly. The paper derives five properties: control-flow safety, memory safety, resource safety, VM integrity, and data safety. Once those per-instruction rules are encoded, a mismatch with the Linux verifier becomes informative: the verifier either accepted something unsafe, rejected something safe, or blamed the wrong instruction.

## Design

SpecCheck's semantic layer models registers and memory slots as `Uninit`, `Scalar`, `PtrType`, or `PtrOrNullType`, over discontiguous memory regions such as stack, context, packet, and maps. Alignment and field-boundary constraints are part of the model, so partial pointer loads and stores become explicit violations. This matters because many verifier bugs hide in exactly those interactions between stack layout, pointer typing, and coarse abstraction.

On top of that, the authors build a safety specification from confidentiality, integrity, and availability goals. Control-flow safety requires bounded execution and explicit exit. Memory safety enforces non-null, in-bounds, permission-respecting accesses and tracks allocation state. Resource safety checks that memory and locks are released before exit. VM integrity forbids writes to `r10`. Data safety prevents reading uninitialized data, leaking pointers through maps or helpers, or using arithmetic and memory operations that silently turn pointers into public scalars.

The encoding is deliberately modular. Each instruction becomes a pure Dafny function whose preconditions are the relevant safety rules and whose body computes the next immutable VM state. Veritas then shallow-embeds generated eBPF programs into Dafny, asks Dafny and Z3 to discharge the obligations, and compares the result with the real verifier. To keep the solver practical, the system biases toward small programs, samples verifier state inside a patched kernel so checking can start near the culprit instruction, and runs the checker asynchronously in parallel with fuzzing.

## Evaluation

The results match the paper's claim that a precise oracle broadens coverage beyond runtime-triggered bug hunting. Over three months, Veritas found 15 bugs in total. Thirteen are the core semantic discrepancies summarized in Table 1: three unsafe accepts, nine safe rejects, and one case where atomic operations on local memory were incorrectly allowed. Twelve reports were acknowledged and eight were fixed by the time of writing. The two remaining bugs in the total count were KASAN and UBSAN findings in the verifier itself and are reported separately from the 13 core mismatches.

The mix of findings is important. Some are serious security bugs, including privilege escalation and kernel-pointer disclosure. Others are pure usability failures that waste hours of developer debugging time. The culprit instructions span arithmetic, data movement, memory operations, and control flow, which supports the claim that the specification is broad rather than tied to one narrow subsystem.

The comparison against prior work is especially persuasive. SpecCheck rediscovers all 14 verifier bugs collected from earlier fuzzers. Existing open-source fuzzers, in contrast, fail to catch the new Veritas bugs even when handed exact proof-of-concept programs, because their oracles depend on runtime manifestations. Performance remains reasonable for an offline oracle: on a 224-core server Veritas sustains 23 to 25 tests per second, averages about 10 seconds per checked test, times out on about 0.2% of cases, and saves 754 CPU-core hours over a 40-hour run by sampling verifier state. Coverage reaches 32% branch coverage, which is enough here because the oracle is searching for semantic mismatches rather than crashes alone.

## Novelty & Impact

The paper's novelty is to make the verifier's intended semantics and policy executable, then use that artifact as an external oracle against the production implementation. That gives Veritas a capability prior eBPF fuzzers mostly lacked: systematic detection of safe rejects and policy inconsistencies, not just unsafe accepts that later crash. For maintainers, the result is a practical regression oracle; for researchers, it is a reusable specification that could support stronger verification or proof-carrying-code style workflows later.

## Limitations

Coverage is the clearest limitation. SpecCheck models all 171 ISA opcodes in the RFC but only the 50 most frequently used helper or kernel functions out of 455, so helper-mediated memory behavior outside that set is explicitly out of scope. The system also relies on bounded loop unrolling, assumes many interesting bugs live in small programs, and accepts occasional SMT timeouts instead of forcing completeness.

There are also practical dependencies. Efficient checking needs a patched kernel for verifier-state sampling, and the paper does not target JIT bugs, helper implementation bugs, or speculative-execution mitigations beyond assuming the eBPF VM can rewrite programs appropriately.

## Related Work

- _Gershuni et al. (PLDI '19)_ - Prevail rebuilds eBPF safety checking on a cleaner abstract-interpretation foundation, whereas Veritas leaves the production verifier in place and uses a specification as an external oracle.
- _Vishwanathan et al. (CAV '23)_ - Agni verifies the verifier's range-analysis component, while this paper aims for broader bug coverage by specifying full instruction behavior and safety constraints for testing.
- _Sun and Su (OSDI '24)_ - SEV validates the eBPF verifier via state embedding, but it still relies on runtime-oriented evidence and cannot naturally explain or detect safe programs that the verifier rejects.
- _Sun et al. (EuroSys '24)_ - Structured and sanitized-program fuzzing improves eBPF verifier testing, yet its oracle still depends on runtime manifestations, whereas Veritas can flag silent semantic mismatches before execution.

## My Notes

<!-- empty; left for the human reader -->

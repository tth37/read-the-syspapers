---
title: "Arancini: A Hybrid Binary Translator for Weak Memory Model Architectures"
oneline: "Combines static and dynamic binary translation around a proof-guided IR so x86-64 binaries run correctly on Arm and RISC-V weak-memory hosts."
authors:
  - "Sebastian Reimers"
  - "Dennis Sprokholt"
  - "Martin Fink"
  - "Theofilos Augoustis"
  - "Simon Kammermeier"
  - "Rodrigo C. O. Rocha"
  - "Tom Spink"
  - "Redha Gouicem"
  - "Soham Chakraborty"
  - "Pramod Bhatotia"
affiliations:
  - "TU Munich, Munich, Germany"
  - "Huawei Research, Edinburgh, UK"
  - "University of St Andrews, St Andrews, UK"
  - "RWTH Aachen University, Aachen, Germany"
  - "TU Delft, Delft, Netherlands"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790127"
tags:
  - compilers
  - verification
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Arancini is a hybrid x86-64 binary translator for Arm and RISC-V that routes both its static and dynamic paths through a shared IR, then uses mechanized memory-model mappings to preserve x86 ordering on weaker hosts. The result is coverage beyond a pure static translator while staying up to `5x` faster than the QEMU-derived Risotto baseline. Its strongest claim is that the implementation follows proofs all the way down to mixed-size Arm accesses.

## Problem

The paper starts from two limits in the existing translator landscape. Static binary translators can leverage LLVM-style optimization and avoid full CPU-state emulation, but they are fundamentally incomplete because binary disassembly loses control-flow structure and cannot reliably recover every jump target. Dynamic binary translators have the opposite shape: they are much more complete in practice because they translate only the code they reach, but they pay JIT latency, optimize only local regions, and often end up `5-10x` slower than native execution.

Cross-ISA concurrency makes the tradeoff sharper. Arancini translates from x86-64 to Armv8 and RISC-V, so a stronger guest memory model must be preserved on weaker hosts. If the translator gets that mapping wrong, it can admit executions impossible on the guest machine; the paper cites prior work showing that QEMU handles these cases incorrectly and therefore disables concurrency. Mixed-size accesses make the problem even subtler, because transformations that look harmless at the instruction level, such as splitting a larger access into smaller ones, can change legal outcomes. The systems problem is therefore to recover DBT-like coverage without giving up either performance or memory-model correctness.

## Key Insight

The central proposition is that hybrid translation only works cleanly if static and dynamic translation share the same semantic substrate. Arancini's answer is ArancinIR, a low-level IR that remains close enough to machine execution for fast dynamic lowering, but structured enough to support static optimization. Once both paths compile through the same IR, the system can enforce one memory-model story instead of maintaining a separate correctness argument for LLVM lowering and for the JIT.

The second half of the insight is to make the IR itself proof-carrying. The authors define an axiomatic memory model for ArancinIR, AIMM, then prove mappings from x86-64 to AIMM and from AIMM to Armv8 and RISC-V. That lets the implementation insert the required fences and atomic forms because the proof says they are necessary, not because a backend heuristic guessed well. With correctness pushed into the translation substrate, a hybrid binary plus runtime lookup tables becomes enough to fill in code dynamically without reopening the semantic gap.

## Design

ArancinIR is organized around packets and chunks. A packet is a DAG for one guest instruction; a chunk is a linear sequence of packets, large enough to represent a function statically or a basic block dynamically. Inside each packet, value nodes compute intermediate results and action nodes commit architectural effects such as register and memory writes. That split preserves explicit points where guest state must be consistent while still allowing local simplifications such as dead-flag elimination.

Correctness is anchored in AIMM, the ArancinIR memory model. AIMM defines loads, stores, RMWs, and a set of fences, then composes thread-local order with cross-thread communication. The paper proves mappings from x86-64 to AIMM and from AIMM to Arm and RISC-V, claiming those mappings are minimal: every inserted fence is needed for some program. One especially useful negative result is that splitting a larger access into smaller accesses is unsound because it can admit mixed-size behaviors absent from the source. That observation explains both why the Arm mixed-size result matters and why unsupported wide accesses are not a trivial engineering gap.

The rest of the system turns this proof-guided core into a usable hybrid translator. The static pipeline discovers ELF symbols, lifts reachable code to ArancinIR, raises it to LLVM IR, runs LLVM `O2` plus fence merging, and emits a hybrid ELF that contains translated host code, original guest code, and metadata such as a guest-address-to-host-function map. The runtime initializes guest stacks and thread-local state, mediates system calls such as `clone`, and triggers dynamic translation when control reaches a guest PC with no static translation. That dynamic path reuses the same frontend and IR, lowers one basic block at a time through a lightweight backend into a code cache, and chains cached blocks to reduce future lookup overhead.

## Evaluation

The evaluation uses Phoenix's multi-threaded benchmarks in both `pthread` and map-reduce variants, with x86-64 guest binaries built using Clang 18 and musl, then translated for a ThunderX2-99xx Arm host and a SOPHON SG2042 RISC-V host. On completeness, the story is clear: Arancini translates all seven benchmarks in both variants, whereas Lasagne misses every map-reduce case and several `pthread` cases because static lifting cannot resolve their dynamic control flow. That supports the paper's main systems claim that hybrid translation provides real fallback value rather than a mostly idle escape hatch.

The performance result is more modest but still meaningful. Relative to native, Arancini is `8.01x` slower on Arm and `4.52x` slower on RISC-V by geometric mean; linking native libraries improves that to `6.01x` and `3.81x`. The important comparison is against other translators: Arancini is generally on par with or faster than Risotto, and the paper summarizes the gain as up to `5x` over QEMU-based dynamic translation. The performance anatomy also matches the design. At most `2.1%` of uniquely translated instructions are discovered dynamically, perf sampling shows execution is dominated by statically translated code, and scaling with thread count remains close to native on the reported Arm experiments. That makes the paper's thesis plausible: the runtime mostly repairs control-flow coverage, while the static path pays for the useful work.

For correctness, the paper leans on proofs first and experiments second. It translates several lock implementations from the Linux kernel and libvsync-style code, reporting slowdowns between `3.11x` and `3.56x` versus native, and explicitly points to `lockref` as a mixed-size Arm case covered by the proof-guided mapping. That is not exhaustive validation, but it is aligned with the formal claim the paper is actually making.

## Novelty & Impact

Relative to _Rocha et al. (PLDI '22)_, Arancini's advance is not better static translation in isolation, but combining static and dynamic translation without abandoning a formally verified strong-on-weak mapping story. Relative to _Gouicem et al. (ASPLOS '23)_, it gives up some pure-DBT uniformity in exchange for a hybrid architecture that spends most cycles in ahead-of-time translated code while extending the proof line to RISC-V and mixed-size Arm accesses. Relative to earlier hybrid systems, its distinctive move is treating the IR, the runtime format, and the proof obligations as one co-designed artifact.

That combination matters to both binary-translation builders and verification researchers. Practitioners get a concrete recipe for escaping the static-versus-dynamic tradeoff without hand-waving memory correctness. Verification-oriented readers get a case where mechanized proofs shape a real systems implementation rather than a toy compiler. The durable contribution is the claim that hybrid translation needs a shared semantic substrate, not merely a shared cache.

## Limitations

The implementation does not yet deliver the full completeness story suggested by the design. The paper explicitly says Arancini has not implemented all features present in Risotto and QEMU, so "complete like any DBT" remains an architectural direction rather than a finished artifact. The current system also supports only musl-linked binaries, does not yet implement the relocation machinery needed for C++ `new` and `delete`, and treats self-modifying code as a difficult invalidation problem.

There are also limits on the formal result. Mixed-size correctness is proven for the x86-to-Arm path, but not for RISC-V because the referenced RISC-V model lacks mixed-size accesses. Non-temporal accesses are out of scope, and Advanced Vector Extensions are unsupported because naive splitting of 512-bit accesses would be unsound. Finally, the evaluation is narrow: Phoenix is a sensible concurrent suite, but it is still a small collection of C programs, so the paper demonstrates the mechanism more convincingly than it proves deployment readiness.

## Related Work

- _Rocha et al. (PLDI '22)_ — Lasagne proves that proof-guided static translation to weak-memory hosts is possible, but Arancini adds a dynamic fallback path and a hybrid binary/runtime design to recover code Lasagne cannot lift.
- _Gouicem et al. (ASPLOS '23)_ — Risotto provides the completeness side of the story through pure DBT; Arancini borrows the strong-on-weak concern but shifts most work into static translation to reduce overhead.
- _Deshpande et al. (EuroSys '24)_ — Polynima is also hybrid, but it targets practical multithreaded binary recompilation for patching rather than proof-guided cross-ISA translation under weak memory models.
- _Gao et al. (USENIX ATC '24)_ — CrossMapping also studies memory-consistency preservation in cross-ISA translation, whereas Arancini embeds that concern inside a full hybrid translator with mechanized mappings and runtime integration.

## My Notes

<!-- empty; left for the human reader -->

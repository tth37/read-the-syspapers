---
title: "Building Bridges: Safe Interactions with Foreign Languages through Omniglot"
oneline: "Omniglot combines sandboxing, typestate wrappers, and compile-time scopes so Rust can call untrusted foreign libraries without giving up soundness or zero-copy sharing."
authors:
  - "Leon Schuermann"
  - "Jack Toubes"
  - "Tyler Potyondy"
  - "Pat Pannuto"
  - "Mae Milano"
  - "Amit Levy"
affiliations:
  - "Princeton University"
  - "University of California, San Diego"
conference: osdi-2025
code_url: "https://github.com/omniglot-rs/omniglot"
tags:
  - security
  - isolation
  - pl-systems
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Omniglot makes Rust-to-foreign-language FFI safe by putting foreign code behind a memory sandbox and by treating foreign pointers and return values as typestates that must be upgraded and validated before Rust may use them normally. Its key move is to encode the temporal rules around validation, mutation, callbacks, and allocation revocation as compile-time scopes, so it preserves Rust soundness while staying close to isolation-only overheads.

## Problem

The paper starts from a practical tension in systems migration. Teams increasingly adopt Rust for kernels, services, and embedded software because Rust eliminates large classes of memory bugs, but those systems still depend on mature libraries written in C or other foreign languages. The usual answer is the C ABI plus generated bindings such as `rust-bindgen`, which flatten rich language invariants into raw pointers and `unsafe` blocks. That boundary gives the compiler almost no help: the developer must manually prove that the foreign library will not violate Rust's assumptions about memory layout, aliasing, valid values, lifetimes, or concurrency.

The running `aes_encrypt` example shows why this is hard. Foreign code can overwrite `Vec` metadata and destroy memory safety, return a pointer that aliases an existing mutable borrow and thus violate Rust's aliasing-XOR-mutability rule, or return a non-`0`/`1` `bool` that exploits Rust's niche-filling layout and causes an enum to be misread as a different variant. Simple sandboxing is not enough, because even a library confined to its own pages can still hand Rust values that are semantically invalid. Copying or serializing every crossing would restore safety more easily, but that gives up the efficiency that makes FFI attractive in kernels and performance-sensitive libraries.

## Key Insight

Omniglot's core claim is that Rust does not need a proof that the full mixed-language program is correct. It only needs a boundary discipline that restores Rust's own invariants before any foreign value is treated as a Rust value. Omniglot therefore downgrades everything coming from foreign code to a weaker, tainted representation, and then re-establishes soundness in stages.

Those stages line up with two distinct facts. First, Rust must know that a pointer names live foreign memory of the right size and alignment. Second, Rust must know that the bytes stored there satisfy the validity rules of the claimed Rust type and remain stable while Rust is using them. Omniglot captures these facts as typestate transitions and binds them to lexical scope tokens. Because Rust's borrow checker already enforces shared-versus-unique access, the same machinery can rule out writes, foreign calls, or allocation changes that would invalidate earlier checks. That lets Omniglot keep zero-copy sharing while still preserving host-language soundness.

## Design

Omniglot combines three mechanisms. The first is a pluggable runtime, `OGRt`, that loads a foreign library into a sandbox, allocates memory inside foreign-owned regions, prepares callbacks, and invokes foreign functions only inside the protected domain. The paper implements this twice: `OGPMP` for the Tock kernel using RISC-V PMP, and `OGMPK` for Linux userspace using x86 MPK. The strong version is `OGPMP`, because it can fully restrict foreign memory access and prevent uncontrolled concurrency; `OGMPK` is explicitly weaker because MPK can be bypassed through mechanisms such as `mmap`, signals, and background threads unless the deployer adds extra controls.

The second mechanism is Omniglot's reference ladder. A raw pointer may point anywhere and carries no guarantee. `upgrade` turns it into `OGMutRef<T>` after checking that the address lies in an active foreign allocation with sufficient size and alignment. `validate` can then turn that into `OGVal<T>` if the bytes satisfy Rust's validity constraints for `T`. Omniglot implements validation for primitive and layout-checkable types, but not for types whose invariants depend on provenance or lifetimes, such as Rust references or typestates; those must instead be represented symbolically. To handle possible mutable aliasing in foreign memory, `OGMutRef<T>` is represented as `&UnsafeCell<MaybeUninit<T>>`, which prevents Rust from assuming normal aliasing and initialization guarantees.

The third mechanism is the paper's most original one: temporal constraints are enforced with branded allocation and access scopes. `OGRt::new` returns unique `AllocScope` and `AccessScope` markers for one library instance. Upgrading a pointer borrows the allocation scope, so references cannot outlive the allocation regime they depend on. Validating a value borrows the access scope, and any operation that might invalidate validated data, such as `write` or `invoke`, requires a unique borrow of that same scope. In effect, Omniglot turns "do not keep using this validated value after a foreign write, callback, or revocation" into an ordinary borrow-checking error. A modified `rust-bindgen` plus an `invoke` trampoline then make this usable with ordinary C ABIs without libffi-style dynamic marshaling.

## Evaluation

The evaluation is structured to test both generality and cost. The authors run `OGPMP` inside the Tock kernel on an OpenTitan-based RISC-V FPGA platform, and `OGMPK` in Linux userspace on a CloudLab Xeon node. Their workloads cover three Tock libraries with different interaction patterns, `CryptoLib`, `LittleFS`, and `LwIP`, plus three Linux libraries, `Brotli`, `libsodium`, and `libpng`. This is a credible spread: one-shot calls, stateful libraries, callbacks, strings that require validation, and byte buffers whose validation can be optimized away.

The headline result is that Omniglot adds very little beyond the cost of isolation itself. Relative to isolation-only execution, the added overhead is `0%` for `CryptoLib`, `Brotli`, and `libsodium`, `0.5%` for `LittleFS`, `0.8%` for `libpng`, and `3.4%` for callback-heavy `LwIP`. Compared with unsafe FFI, the larger slowdowns mostly come from protection-domain switching rather than from Omniglot's validation logic. The `libpng` comparison against Sandcrust is also important: Omniglot stays close to native FFI because it can read foreign memory zero-copy, while Sandcrust pays growing serialization and copying costs as image size increases. The microbenchmarks reinforce the mechanism story: `validate` is linear for strings, optimized away for unconditionally valid types like `u8`, and the hot-path `invoke` cost is `98.90 ns` on MPK and `6.57 us` on PMP. The main gap is that the evaluation demonstrates efficiency and API coverage better than it demonstrates behavior under truly malicious userspace libraries, which the paper itself says is outside `OGMPK`'s threat model.

## Novelty & Impact

Relative to prior Rust sandboxing systems, Omniglot's contribution is not just another protection-domain switch. The novelty is the composition of sandboxing, runtime value validation, and compile-time temporal scopes into a single FFI discipline that preserves Rust soundness across calls to unmodified foreign libraries. Relative to linking-types work, it is much more operational: instead of expressing foreign semantics in the type system and assuming the foreign side is internally correct, it checks and contains what Rust can safely trust at runtime.

That makes the paper useful to several communities. Systems teams incrementally rewriting kernels or services in Rust can keep existing libraries without collapsing back to fully `unsafe` boundaries. Security researchers studying cross-language attacks get a concrete mechanism for turning "unsafe FFI" into a defendable interface. PL and systems researchers get a good example of typestate and borrow checking solving a systems integration problem rather than a purely language-internal one. This feels like a real new mechanism, not just a benchmarking exercise.

## Limitations

The strongest limitation is that Omniglot's guarantees are only as strong as its runtime. `OGPMP` matches the paper's adversarial model, but `OGMPK` does not: a hostile library can potentially escape MPK restrictions via system calls, signal handlers, or concurrent threads unless the deployer adds auditing or seccomp-style controls. Omniglot also preserves Rust soundness, not application correctness. A foreign library may still compute the wrong answer, leak information through side channels, or be corrupted by host writes into foreign memory.

There are also expressiveness and adoption limits. Omniglot cannot validate types whose safety depends on provenance, lifetimes, or richer logical invariants, so some APIs must be redesigned around symbolic handles instead of direct references. The API is not drop-in compatible with existing unsafe FFI, because callers must use Omniglot's allocation, callback, and invocation setup; the `libpng` case even required a C wrapper to translate `longjmp`-style failure into a normal error return. Finally, the evaluation focuses on library-scale benchmarks rather than large end-to-end applications, so the engineering cost of adopting Omniglot across a large Rust codebase is not yet clear.

## Related Work

- _Lamowski et al. (PLOS '17)_ - Sandcrust isolates unsafe components in Rust through IPC and serialization, while Omniglot targets arbitrary foreign libraries and keeps zero-copy access to foreign memory.
- _Bang et al. (USENIX Security '23)_ - TRust provides in-process isolation for untrusted code, but Omniglot additionally models type validity, aliasing, and temporal constraints at the FFI boundary.
- _Kirth et al. (EuroSys '22)_ - PKRU-Safe uses MPK to separate safe and unsafe language heaps, whereas Omniglot must also validate foreign values and manage reference lifetimes across arbitrary library calls.
- _Patterson et al. (PLDI '22)_ - Semantic soundness for language interoperability reasons about multilingual composition semantically, while Omniglot gives a pragmatic runtime discipline for unmodified, untrusted libraries.

## My Notes

<!-- empty; left for the human reader -->

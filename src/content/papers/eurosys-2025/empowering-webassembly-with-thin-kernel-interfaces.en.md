---
title: "Empowering WebAssembly with Thin Kernel Interfaces"
oneline: "Thin kernel interfaces expose stable OS syscalls directly to Wasm, letting existing userspace software recompile into portable sandboxed binaries and moving APIs like WASI above the engine."
authors:
  - "Arjun Ramesh"
  - "Tianshu Huang"
  - "Ben L. Titzer"
  - "Anthony Rowe"
affiliations:
  - "Carnegie Mellon University"
  - "Carnegie Mellon University, Bosch Research"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717470"
code_url: "https://github.com/arjunr2/WALI"
tags:
  - kernel
  - virtualization
  - isolation
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

The paper argues that Wasm does not need a brand-new OS API to become a serious userspace virtualization target. A thin kernel interface can expose stable kernel syscalls directly to Wasm, preserve its in-process sandboxing guarantees, and move APIs such as WASI out of the engine and into Wasm libraries. The Linux prototype, WALI, runs complex existing software with small interface overhead and much better startup behavior than containers.

## Problem

Wasm already gives systems builders many properties they want for edge and cyber-physical deployments: ISA portability, small binaries, static validation, memory sandboxing, and built-in control-flow integrity. The missing piece is the system interface. Outside the browser, the obvious answer is WASI, but the paper argues WASI is misaligned with long-lived edge software stacks: it is still evolving, it intentionally diverges from POSIX, and it omits features such as `mmap`, processes, asynchronous I/O, signals, and users/groups that real applications depend on.

That matters because the paper is not targeting greenfield functions. It wants to virtualize legacy Linux userspace, long-lived embedded deployments, and multi-vendor software stacks that will not be rewritten around a new capability API. The authors therefore ask whether the kernel syscall ABI itself can be the Wasm interface. Their feasibility study says yes: many applications use fewer than 100 unique syscalls, the union lands around 140-150, and Linux exposes a large common core across x86-64, aarch64, and riscv64.

## Key Insight

The key insight is to expose the kernel/userspace boundary instead of inventing a new low-level OS abstraction. Syscall ABIs are historically stable, every libc and runtime already targets them, and they are close enough across major ISAs that a Wasm-facing version can stay thin. That means ordinary software often needs only recompilation, not redesign.

This also untangles execution from policy. The engine can focus on executing Wasm safely and quickly, while filesystem mediation, capability discipline, and APIs such as WASI move above WALI as ordinary Wasm modules. The payoff is not just compatibility; it is better layering, a smaller TCB, and more freedom to experiment with higher-level security models.

## Design

The Linux interface, WALI, exposes roughly 150 host functions, mostly corresponding one-for-one with Linux syscalls plus a few support calls for arguments and environment state. Most syscalls are direct pass-throughs: the engine mainly performs fast address-space translation for pointer arguments and, when necessary, ABI layout conversion for structs whose layout differs across ISAs. Fewer than 10% of syscalls need this heavier struct-copy path.

Two areas need real adaptation. First, because Wasm memory is a sandboxed linear region, `mmap`, `mremap`, and `munmap` are virtualized inside Wasm memory rather than returning arbitrary native addresses. Second, because core Wasm has no native process or async-signal model, the paper sketches 1-to-1, N-to-1, and future threadless process designs, then implements the simplest 1-to-1 version in WAMR with instance-per-thread semantics. Async signals use a virtual signal table, a pending queue and bitset, and compiler-inserted safepoints at loop headers. Cross-platform support comes from a name-bound union of syscalls across Linux ISAs. Security-wise, WALI keeps Wasm's native sandbox, blocks `/proc/self/mem`, traps direct `sigreturn`, and forbids stack-breaking control transfers such as `setjmp`/`longjmp`.

## Evaluation

The prototype is implemented in WAMR with the 1-to-1 process model and loop-header signal polling. The authors implement the 137 most common Linux syscalls in about 2000 lines of C, with under 100 lines of platform-specific code, across x86-64, aarch64, and riscv64. That first result already matters: the interface remains thin in practice.

The portability experiment is the paper's strongest evidence. With a WALI-targeting LLVM toolchain, they compile and run `bash`, `lua`, `memcached`, `openssh`, `sqlite`, `make`, `vim`, `openssl`, `libevent`, `libncurses`, the Linux Test Project harness, and even `libuvwasi`. Nearly everything runs without source changes; the interesting failures are undefined C function-pointer casts, which WALI's typed indirect calls expose instead of silently tolerating. `libuvwasi` passes all 22 unit tests, which is the cleanest demonstration that WASI can sit above the thin kernel interface.

Intrinsic overhead is small. Representative syscalls add only a few hundred nanoseconds in most cases, and WALI itself consumes less than 1% of runtime on most macrobenchmarks, with `memcached` reaching 2.4%. `clone` costs about 500 microseconds, but the paper attributes that mostly to WAMR's thread manager. Signal polling at loop headers or function entries usually adds under 10% slowdown, whereas polling every instruction exceeds 10x overhead. End to end, WALI lands between Docker and QEMU: still roughly 2x slower than native and Docker on CPU-bound work, but with only a few milliseconds of startup time and far less base-memory overhead than Docker's roughly 30 MB platform cost.

## Novelty & Impact

The contribution is less a new mechanism than a new layering decision. Relative to WASI and WASIX, the paper refuses to make the low-level interface also be the main security model. Relative to containers and hypervisors, it virtualizes only userspace while inheriting Wasm's CFI, non-addressable execution state, and ISA portability.

That framing has two practical impacts. It gives engines a thinner target, and it gives existing software stacks a path into Wasm that looks much more like recompilation than porting. The Zephyr prototype, WAZI, strengthens the claim that the recipe is not Linux-only: the same approach compiles a Lua toolchain onto a Zephyr board with 384 kB of SRAM.

## Limitations

The measured system is narrower than the conceptual claim. Only the simplest 1-to-1 design is implemented, only in WAMR, and WAZI remains a prototype. Compatibility also stops short of full Linux: the toolchain assumes static linking, it does not support direct hardware access or `ucontext`/`mcontext`, and it forbids `setjmp`/`longjmp`-style non-local control transfer. Finally, although WALI itself is thin, CPU-heavy workloads still inherit the broader performance gap of current Wasm runtimes.

## Related Work

- _Powers et al. (ASPLOS '17)_ - Browsix emulates a POSIX-like environment for browser JavaScript, whereas WALI drops below libc and exposes the kernel boundary directly to Wasm.
- _Porter et al. (ASPLOS '11)_ - Drawbridge pursues a minimal ABI for Windows library OSes; WALI shares the thin-interface instinct but uses the existing syscall interface rather than defining a new portable ABI.
- _Agache et al. (NSDI '20)_ - Firecracker provides lightweight virtualization with hardware assistance, while WALI targets userspace-only virtualization and gains ISA portability from Wasm rather than from a guest VM.
- _Lefeuvre et al. (ASPLOS '24)_ - Loupe studies how OS compatibility layers should choose which APIs to support; WALI uses a very similar syscall-prevalence argument to justify implementing a small but high-value subset.

## My Notes

<!-- empty; left for the human reader -->

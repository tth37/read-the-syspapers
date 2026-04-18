---
title: "How to Copy Memory? Coordinated Asynchronous Copy as a First-Class OS Service"
oneline: "Copier turns memory copy into an OS-managed async service that overlaps copy with use, dispatches work across AVX and DMA, and removes redundant cross-boundary copies."
authors:
  - "Jingkai He"
  - "Yunpeng Dong"
  - "Dong Du"
  - "Mo Zou"
  - "Zhitai Yu"
  - "Yuxin Ren"
  - "Ning Jia"
  - "Yubin Xia"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "Engineering Research Center for Domain-specific Operating Systems, Ministry of Education, China"
  - "Huawei Technologies Co., Ltd."
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764800"
code_url: "https://github.com/SJTU-IPADS/Copier"
tags:
  - memory
  - kernel
  - scheduling
category: memory-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Copier argues that memory copy should be treated as a first-class OS service rather than a blocking library primitive. Its async `amemcpy`/`csync` interface, cross-user/kernel dependency tracking, and AVX+DMA dispatcher let medium-sized copies overlap with computation and let copy chains collapse into shorter paths, yielding up to `1.8x` better Redis latency and `1.6x` speedup over zIO.

## Problem

The paper starts from a simple observation: copy is still everywhere, and it is still expensive. Syscalls, IPC, network stacks, serialization libraries, compression code, and storage services all spend a large fraction of their cycles moving bytes. In the authors' measurements, copy can consume up to `66.2%` of cycles in representative applications, and it remains visible even in a modern smartphone OS.

Existing fixes are fragmented. Hardware-assisted copy helps only where software can actually reach the hardware: user libraries can use SIMD, but the kernel usually avoids it because saving and restoring vector state is expensive; DMA can save CPU cycles, but user applications cannot easily drive it and small transfers pay too much submission overhead. Zero-copy techniques help in some cases, but they come with sharp constraints: page alignment, single-owner semantics, difficulty supporting multiple replicas, extra ownership bookkeeping, and TOCTTOU exposure when the receiver observes mutable shared buffers. Their performance regime is also narrow, with Linux `MSG_ZEROCOPY` recommended only for large messages and zIO requiring at least medium-sized copies to win.

So the missing piece is not one better `memcpy()`. It is a system-wide way to coordinate copies across privilege boundaries, hide copy latency behind useful work, and optimize whole copy chains instead of one call site at a time.

## Key Insight

The core claim is that copy should become an asynchronous, globally managed OS service because programs usually copy data in bulk but consume it incrementally. The paper calls the gap between finishing a copy and first using the data the Copy-Use window, and measures that this window is often `2x` to `10x` the time needed to copy the same bytes. If the OS can start the copy early and expose fine-grained readiness, much of the latency can disappear from the critical path without giving up private-buffer semantics.

Making copy a service matters for two more reasons. First, the service can centrally exploit heterogeneous engines such as AVX and DMA in ways that individual call sites cannot. Second, it can see chains like kernel-to-buffer followed by buffer-to-database and eliminate intermediate copies entirely when correctness permits. The paper's thesis is therefore stronger than "async memcpy is useful": coordinated async copy plus a global system view is what unlocks the win.

## Design

Copier exposes high-level APIs `amemcpy()` and `csync()`, implemented over three per-client queues mapped into the process: a `Copy Queue`, a `Sync Queue`, and a `Handler Queue`. Each copy task carries source, destination, length, granularity, and a descriptor bitmap. Copier copies in fixed-size segments and flips descriptor bits as segments complete, so clients can `csync()` only the range they are about to touch instead of waiting for the whole transfer. A `Sync Queue` task can promote the needed segments and their dependencies, avoiding head-of-line blocking from strict FIFO copy order. Post-copy actions such as freeing buffers are handled through delegated handlers rather than extra ownership syscalls.

The difficult part is correctness across user and kernel activity. Copier keeps separate user-mode and kernel-mode queue sets per process, then inserts barrier tasks around trap and return events to infer cross-queue order. When `csync()` promotes a task, Copier also walks backward through overlapping regions to discover data dependencies, so it does not reorder copies past writes that would change the bytes. The appendix gives a rely-guarantee simulation proof that `amemcpy` plus correctly inserted `csync` refines ordinary synchronous copy semantics.

Hardware utilization is handled by a piggyback dispatcher. Copier splits a copy into subtasks based on physically contiguous regions, sends larger subtasks to DMA when worthwhile, and runs the rest on AVX. Instead of waiting idly for DMA, it piggybacks DMA work under AVX work in the same scheduling round, trying to align their completion times. An `ATCache` memoizes virtual-to-physical translations for recurring buffers, which matters because recycled I/O buffers are common.

Copier's other distinctive optimization is layered copy absorption. If the system sees `A -> B` followed by `B -> C`, and only some of `B` has actually been materialized or modified, it builds `C` from the newest segments available rather than blindly copying from a single source. Lazy tasks and abort-style syncs extend this to proxies and other pipelines that inspect only headers before forwarding payloads. Because Copier is a shared service, it also adds CFS-like scheduling over copy length, a copier cgroup controller for fairness, auto-scaling copier threads, and proactive fault handling that resolves CoW and paging issues before the copy thread dereferences user virtual addresses. The toolchain around it includes `libCopier`, `CopierSanitizer`, and an early `CopierGen` compiler pass for partial automation.

## Evaluation

The main server experiments run on dual Xeon E5-2650 v4 machines with Linux `5.15.131`; Copier uses one dedicated core for copy. The paper evaluates both the raw copy substrate and end-to-end applications, comparing against Linux ERMS copy, AVX2 user copy, DMA, `io_uring`, zero-copy sockets, UB, and zIO.

At the micro level, the copy engine itself is clearly stronger than any single baseline in its target regime. Copier improves copy throughput by up to `158%` over kernel ERMS and up to `38%` over userspace AVX2 without buffer reuse, with further gains when recurrent buffers let `ATCache` help. For OS services, `recv()` latency drops by `16%` to `92%` and `send()` by `7%` to `37%`; Binder IPC latency falls by `9.6%` to `35.5%`; CoW page-fault blocking time drops by `71.8%` for `2 MB` pages.

The application results are the most convincing evidence for the paper's thesis. Redis benefits from both overlapping and copy absorption: GET latency improves by `4.2%` to `42.5%`, SET latency by `2.7%` to `43.4%`, and throughput rises by up to `50%`. TinyProxy gains `7.2%` to `32.3%` throughput because Copier can collapse a three-copy forwarding path into one effective transfer, something zIO cannot do across privilege boundaries. Protobuf deserialization improves by up to `33%`, OpenSSL `SSL_read()` by up to `8.4%`, and HarmonyOS video decoding by `3%` to `10%` with only `0.07%` to `0.29%` more energy.

The evaluation generally supports the central claim: Copier wins when there is a real Copy-Use window, a copy chain to absorb, or enough idle CPU capacity to dedicate a copy thread. The baselines are serious and varied. The main caveat is that large aligned sends still favor classic zero-copy, and the authors explicitly show that saturated machines can trade some overall throughput for lower request latency.

## Novelty & Impact

The novelty is a new systems abstraction, not just a faster kernel primitive. Prior work separately explored async syscalls, DMA-assisted copying, and zero-copy I/O, but Copier is the first design here to treat memory copy itself as a schedulable OS service with explicit programming primitives, dependency tracking across privilege boundaries, and whole-chain optimization.

That framing matters. Many systems papers observe copy overhead, but most solutions remain tied to one subsystem such as networking, IPC, or storage. Copier instead proposes a reusable substrate that can sit under network stacks, CoW handlers, Binder, serializers, proxies, and application libraries. If the abstraction is practical, future systems can optimize copy once in the OS rather than re-solving it in each stack.

## Limitations

Copier's win depends on workload structure. It is designed for regular access patterns and meaningful Copy-Use windows; random-access consumers cannot safely postpone synchronization and will recover less overlap. The programming model is also not free: developers must insert `csync` at the right points, and although the sanitizer and proof reduce the risk, the system still relies on correct usage.

The implementation cost is also real. Copier uses polling threads and a dedicated copy core in the server experiments. When all CPU cores are busy, the paper reports better latency but `4.3%` to `6.5%` lower overall Redis throughput in one saturated setting. Zero-copy send still beats Copier for large messages of at least `32 KB`, and the compiler-based porting story is still early, with complex pointer-heavy cases left as future work.

## Related Work

- _Stamler et al. (OSDI '22)_ — zIO also tries to remove unnecessary copies, but it relies on remapping and page faults, works only in a narrower size regime, and cannot absorb cross-privilege copy chains the way Copier can.
- _Su et al. (FAST '23)_ — Fastmove uses DMA to speed a specific OS storage path, while Copier generalizes hardware-assisted copy into a shared service that coordinates AVX, DMA, fairness, and asynchronous semantics.
- _Soares and Stumm (OSDI '10)_ — FlexSC made syscalls asynchronous; Copier pushes the same broad idea one layer down by making the copy itself asynchronous and globally scheduled.
- _Du et al. (ISCA '19)_ — XPC accelerates secure cross-process calls, whereas Copier targets general memory movement across syscalls, IPC, libraries, and application pipelines.

## My Notes

<!-- empty; left for the human reader -->

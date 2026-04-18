---
title: "KRR: Efficient and Scalable Kernel Record Replay"
oneline: "KRR records only the guest kernel, using a guest-host split recorder and replay-coherent serialization to cut multi-core and kernel-bypass RR overhead."
authors:
  - "Tianren Zhang"
  - "Sishuai Gong"
  - "Pedro Fonseca"
affiliations:
  - "SmartX"
  - "Purdue University"
conference: osdi-2025
tags:
  - kernel
  - virtualization
  - observability
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

KRR argues that kernel debugging does not need whole-VM record replay. It narrows the recording boundary to the guest kernel, then uses a split recorder across the guest and hypervisor plus a replay-coherent serialization scheme to capture exactly the inputs the kernel observes. That cuts recording overhead sharply: on 8-core RocksDB and kernel compilation, KRR slows execution by 1.52x to 2.79x, versus 8.97x to 29.94x for a whole-machine baseline, and kernel-bypass workloads get close to native performance.

## Problem

The paper starts from a practical pain point: kernel failures in deployment are hard to reproduce, and the hardest failures are often non-deterministic. Record-replay is attractive because it can capture one failing execution and replay it exactly, enabling reverse debugging and heavyweight offline analysis. The problem is that existing systems pay for accuracy by recording the entire application or the entire VM, and that cost becomes brutal on the workloads operators actually care about now.

Two trends make the mismatch worse. First, modern workloads are increasingly multi-core, and existing VM record-replay systems usually regain determinism by serializing execution or by logging enough shared-memory ordering to be similarly expensive. Either way, overhead can exceed the number of cores. Second, many data-center applications are now I/O-intensive and increasingly use kernel-bypass stacks such as SPDK or DPDK. In those settings, whole-VM record replay still records all hardware-facing activity, even though much of that activity no longer passes through the guest kernel. So the classic approach pays the full cost of high-throughput I/O while the developer only wants to debug the kernel slice.

KRR's target is therefore narrower but still demanding: reproduce the kernel's execution faithfully enough for debugging, while avoiding the unnecessary cost of recording guest user-space behavior that does not affect the kernel.

## Key Insight

The central claim is that the right replay boundary for kernel debugging is not the machine interface but the kernel interface. If the developer cares about reproducing the kernel, the system should record every non-deterministic input visible to the kernel and only that input.

That sounds harder, not easier, because the kernel receives inputs from two directions. Some arrive from below as interrupts, DMA, and device reads; others arrive from above as system calls, copied user buffers, shared-memory queues such as `io_uring`, page-table side effects, and user-triggered exceptions. KRR's insight is that this dual interface is still tractable because the kernel's input points are relatively well-defined. Once those inputs are captured, the expensive part of multi-core replay can also be narrowed: KRR serializes only kernel execution, letting user-space threads continue in parallel. That makes overhead depend on how much work actually runs in the kernel, which is exactly why kernel-bypass workloads become cheap to record.

## Design

KRR uses a split-recorder architecture. The guest recorder lives inside the guest kernel and logs software-facing inputs: system call numbers and arguments, data copied through interfaces such as `copy_from_user` and `get_user`, reads from shared-memory interfaces like `io_uring`, updates to page-table accessed and dirty bits that can steer memory management, exceptions caused by user-space, and non-deterministic instructions such as `RDTSC` and `RDRAND`. Recording those instructions in the guest matters because trapping each one at the hypervisor would cause a VM exit on every use.

The hypervisor recorder handles hardware-facing inputs: interrupts, PIO/MMIO reads, and DMA data from emulated devices. For asynchronous events such as interrupts and DMA, KRR tags each event with a kernel-mode instruction count obtained from a reserved hardware counter, so replay can inject the event at the same execution point. For kernel-bypass devices, the system can deliberately ignore user-space device traffic that never enters the kernel.

The tricky part is multi-core determinism. KRR introduces a replay-coherent, or RC, spinlock that allows only one vCPU to execute kernel code at a time. Unlike an ordinary spinlock, the RC lock records both acquisition order and the amount of spinning before acquisition, so replay can reproduce the same order without corrupting instruction counts. The kernel releases and reacquires this lock around some internal locks to avoid deadlock, and rare hypercalls resynchronize instruction counts when waiting on those locks. Together with atomic trace updates, this gives KRR one total order of kernel-relevant events without paying VM-exit costs on every kernel entry and exit.

Replay starts from a VM snapshot, re-injects the recorded event stream, and runs inside QEMU emulation so developers can use GDB-style replay debugging. KRR also supports reverse debugging by taking periodic snapshots and tagging them with a per-vCPU instruction-count vector, which avoids the ambiguity of using one global counter in a multi-core replay.

## Evaluation

The evaluation is broad enough to support the main claim. First, KRR passes replay validation on 8,156 Linux Test Project cases. On multi-core RocksDB and Linux kernel compilation, it is consistently far cheaper than a comparable whole-machine baseline. On 2-core RocksDB, KRR slows workloads by 1.01x to 1.67x, while the baseline needs 2.71x to 4.93x; on 4 cores the ranges are 1.06x to 2.03x versus 5.08x to 11.76x. For 8-core RocksDB and kernel compilation, the abstract's headline numbers summarize the result: 1.52x to 2.79x for KRR versus 8.97x to 29.94x for whole-VM record replay.

Kernel-bypass workloads are where the boundary choice pays off most clearly. With RocksDB over SPDK, KRR keeps latency slowdowns to 1.17x to 1.27x, whereas whole-VM replay explodes to 29.36x to 64.51x because it serializes the polling thread and worker despite the I/O path living in user-space. On Redis with DPDK, KRR reduces GET throughput by only 0.26 percent and SET throughput by 1.14 percent on average, with P99 latency changes between -5.19 percent and 11.27 percent. Nginx with DPDK shows the boundary condition: for small 1 KB and 4 KB files, KRR still hurts because the kernel-side file path dominates; for 16 KB and 64 KB files, the bottleneck moves to network transfer and KRR's overhead drops to about 2 percent and 5 percent.

The bug study is also important. KRR reproduces all 6 deterministic Syzbot bugs, 5 of 6 non-deterministic ones, and all 5 tested high-risk kernel CVEs. The one failure, a BPF-related deadlock, requires true parallel lock contention across cores, which KRR's serialization model cannot express.

## Novelty & Impact

Relative to _Ren et al. (ATC '16)_, KRR is not another faster whole-machine recorder; it changes the replay boundary and pays to record user-to-kernel inputs so it can stop recording irrelevant VM behavior. Relative to _O'Callahan et al. (ATC '17)_, it shows why application-level record replay does not transfer directly to kernels: kernel debugging also needs hardware inputs, DMA timing, and privileged instruction handling. Relative to _Ge et al. (ATC '20)_, it chooses exact replay rather than partial reconstruction, which costs more up front but gives a cleaner debugging target.

The paper's main impact is conceptual as much as mechanical. It argues that for debugging, narrowing the replay target can improve both performance and scalability, provided the narrower layer has a disciplined interface that can actually be instrumented. That is a useful design lesson beyond kernels.

## Limitations

KRR's biggest limitation is structural: it cannot reproduce bugs that require true parallel kernel execution on multiple physical cores, including some weak-memory behaviors and lock-contention races. The paper's failed reproduction of bug #8 makes that limit concrete. Scalability also starts to flatten beyond roughly 8 cores because the RC spinlock becomes a contention point, so KRR is not a path to cheap record replay on very large SMP guests.

There are other tradeoffs. For non-bypass workloads, KRR records more data than whole-machine replay because it must additionally log software inputs from user-space to the kernel; the authors report 53.39 MB/s versus 8.26 MB/s on RocksDB before compression, though gzip reduces KRR traces by 6.91x. Replay is also slow, about 20x to 150x slower than native execution, because the prototype uses single-step QEMU emulation. Finally, pass-through and SR-IOV devices outside the kernel-bypass setup are not yet supported.

## Related Work

- _O'Callahan et al. (ATC '17)_ - Mozilla RR provides deployable application-level record replay, but it does not solve kernel-visible hardware inputs or guest-kernel replay inside a VM.
- _Mashtizadeh et al. (ASPLOS '17)_ - Castor logs synchronization order for race-free user applications, whereas KRR assumes the kernel is race-prone and enforces determinism by serializing only kernel execution.
- _Ren et al. (ATC '16)_ - Samsara is the closest multi-core whole-machine baseline; KRR differs by slicing the boundary down to the kernel and exploiting kernel-bypass workloads to avoid recording irrelevant VM traffic.
- _Ge et al. (ATC '20)_ - Kernel REPT reconstructs kernel failures from traces and dumps, while KRR spends more during recording to guarantee faithful replay of long executions.

## My Notes

<!-- empty; left for the human reader -->

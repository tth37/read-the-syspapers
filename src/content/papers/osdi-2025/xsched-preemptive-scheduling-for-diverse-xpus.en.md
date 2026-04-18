---
title: "XSched: Preemptive Scheduling for Diverse XPUs"
oneline: "XSched wraps accelerator command queues in a preemptible XQueue abstraction and three preemption levels, letting one scheduler enforce policy across GPUs, NPUs, ASICs, and FPGAs."
authors:
  - "Weihang Shen"
  - "Mingcong Han"
  - "Jialong Liu"
  - "Rong Chen"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
conference: osdi-2025
code_url: "https://github.com/XpuOS/xsched"
tags:
  - scheduling
  - gpu
  - hardware
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

XSched treats accelerator work as preemptible XQueues and implements them with three levels of preemption over pending, in-flight, and running commands. That lets the same scheduler run across GPUs, NPUs, ASICs, and FPGAs; across ten XPUs it cuts high-priority P99 latency by up to 2.10x, and its case studies show 9.26x lower NPU frame-latency tails and 30.0% lower high-priority Triton inference latency.

## Problem

XPUs are increasingly shared by unrelated tasks: cloud tenants multiplex one GPU, AI PCs run multiple models on one NPU, and autonomous or multimedia systems mix latency-sensitive work with background inference. Yet most devices still schedule work with non-preemptive FCFS queues or coarse round-robin across processes, so a critical task can sit behind a long batch of already-submitted commands. The paper's motivating example is concrete: on an Intel NPU, a real-time fake-background task sees its tail latency rise by more than 20x when it co-runs with speech-to-text.

Prior host-managed schemes prove that software preemption is possible, but they are tied to one accelerator family, one driver stack, or one trick such as kernel rewriting or a vendor ioctl. They therefore do not give the OS a common unit of scheduling across devices, and they age badly as hardware features move in or out of firmware. XSched argues that the missing piece is a portable abstraction and capability model for accelerator scheduling.

## Key Insight

The paper's core claim is that the real commonality across XPUs is the host-issued command queue. Despite architectural differences, most accelerators already execute tasks as ordered streams of commands such as kernels, copies, or operators. XSched therefore treats a task as a preemptible command queue, XQueue, in the same way an OS treats CPU work as a preemptible thread.

Once the abstraction is phrased in terms of command states rather than device brands, hardware diversity becomes manageable. The paper defines three levels: preempt pending commands before launch, preempt in-flight commands after launch but before execution, and preempt running commands. Weak devices can still participate at Level 1, while richer devices expose queue deactivation or interrupts for Levels 2 and 3. Host control also does not require fully synchronous execution: by keeping only a bounded number of commands in flight, software can preserve pipeline efficiency while bounding preemption latency.

## Design

XQueue exposes four interfaces: `submit`, `wait`, `suspend`, and `resume`. Applications can either call them directly or rely on XShim, a preload shim that intercepts native driver APIs and redirects them into XSched. Underneath, XPreempt implements the queue abstraction, XAL maps abstract operations to per-device mechanisms, and XScheduler runs as a daemon that applies policies across processes or containers.

The key implementation challenge is how to keep the host in control after commands are submitted. Synchronizing after every command would work, but the paper shows that it destroys accelerator pipelining and can impose 8.2% to 151.3% overhead. XSched instead uses progressive command launching: each XQueue keeps a pending buffer, a log of in-flight commands, a worker thread, and a threshold on how many commands may escape into the hardware queue. When that threshold is exceeded, the worker waits for half of the in-flight commands to finish before launching more, so suspension waits only for a bounded frontier rather than the full task.

The multi-level hardware model turns this into a family of implementations. Level 1 is universal: pause launches and synchronize outstanding commands. Level 2 adds `deactivate` and `reactivate` so in-flight commands never begin execution; XSched implements this either with firmware-assisted stalling on Intel NPUs or with dynamic binary instrumentation on NVIDIA GPUs, where a guardian snippet aborts kernels after the host flips a per-queue flag. Level 3 adds `interrupt` and `restore` for running commands. The paper shows both TSG-level interrupts on newer NVIDIA GPUs and a finer queue-level path built on undocumented trap handling, though interrupted kernels are restarted from the beginning and must be idempotent.

## Evaluation

The evaluation is broad on platform coverage and mostly convincing on the paper's central claim. XSched is ported to seven software platforms and ten XPUs, and basic Level 1 support takes only 214 to 841 lines of C++ per platform.

For scheduling behavior, the fixed-priority policy brings foreground latency close to standalone execution across the tested devices. With native scheduling, foreground P99 latency can be 1.60x to 2.19x worse than standalone; with XSched it stays within 1.02x to 1.30x of standalone and improves by up to 2.11x. The bandwidth-partition policy enforces a 75/25 split with only 1.5% average overhead, and coordinating GPU and NPU queues together cuts foreground NPU P99 latency by up to 2.63x.

The results also validate the multi-level model itself. When the in-flight threshold is eight commands of duration `T`, Level 1 yields roughly `8T` P99 preemption latency, Level 2 drops that to about `T`, and on GV100 the Level 3 path reaches 32 us independent of `T`. Runtime overhead stays below 3.4% for Level 1 across all tested XPUs. The case studies matter because they use real systems: XSched harvests 2.74x more opportunistic GPU work than TGS while protecting production containers, cuts Intel NPU video-frame P99 from 880 ms to 95 ms, and lowers high-priority Triton inference P99 by 30.0% with ten lines of integration. The deepest low-latency mechanisms, however, are demonstrated most strongly on NVIDIA GPUs and one Intel NPU.

## Novelty & Impact

Relative to TimeGraph, EffiSha, and FLEP, XSched is not another accelerator-specific preemption hack. Its main contribution is to factor preemption into a portable abstraction plus a capability ladder, so the same policy logic can survive across vendors and device classes. Relative to REEF, it widens the scope from one GPU stack to a menu of interchangeable implementations, including what the authors claim is the first software-based preemptive support for NPUs and ASICs. That makes the paper useful beyond its benchmark wins: it gives runtimes a thread-like scheduling unit for accelerators and gives hardware designers a vocabulary for exposing progressively richer scheduling support without forcing upper layers to rewrite their policies.

## Limitations

XSched's portability is real but uneven. Level 1 is broadly reusable, but Levels 2 and 3 depend on firmware features, undocumented interfaces, or device-specific binary instrumentation. The queue-level Level 3 path on NVIDIA GPUs only handles idempotent kernels and currently relies on manual identification, which is a practical deployment constraint rather than a minor engineering detail.

The framework also assumes the common host-managed, command-offload execution model. Devices that proactively execute tasks without host-issued queues, single-command tasks such as CUDA graphs or monolithic NPU inference calls, and oversubscribed device-memory scenarios are not solved directly. Finally, the design assumes mediated access: a malicious tenant that bypasses XQueue or XShim could still monopolize the accelerator unless virtualization or API remoting enforces control underneath.

## Related Work

- _Kato et al. (USENIX ATC '11)_ — TimeGraph throttles GPU command launches to approximate preemptive scheduling, while XSched generalizes that idea into a portable abstraction spanning multiple XPU classes.
- _Chen et al. (PPoPP '17)_ — EffiSha enables GPU preemption through kernel transformation, whereas XSched treats such flushing techniques as one interchangeable Level 2 implementation inside a broader framework.
- _Han et al. (OSDI '22)_ — REEF achieves microsecond GPU preemption on AMD hardware, but XSched lifts preemption into a cross-vendor, cross-accelerator model with multiple implementation paths.
- _Ng et al. (SOSP '23)_ — Paella is a GPU-specific serving scheduler, while XSched provides the reusable scheduling substrate that can be integrated into serving systems such as Triton.

## My Notes

<!-- empty; left for the human reader -->

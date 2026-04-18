---
title: "Proto: A Guided Journey through Modern OS Construction"
oneline: "Proto turns OS education into a five-stage, app-driven build on Raspberry Pi hardware, adding only the mechanisms needed to reach games, media playback, files, threads, and a desktop."
authors:
  - "Wonkyo Choe"
  - "Rongxiang Wang"
  - "Afsara Benazir"
  - "Felix Xiaozhu Lin"
affiliations:
  - "University of Virginia"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764811"
code_url: "https://github.com/fxlin/uva-os-main"
tags:
  - kernel
  - scheduling
  - memory
  - filesystems
  - hardware
category: embedded-os-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Proto argues that an instructional OS becomes more motivating and still teachable if students build it through a series of usable apps on real ARM hardware, not through isolated subsystem exercises. The system is decomposed into five self-contained prototypes that grow from bare-metal graphics to a windowed multicore desktop, while staying fast enough to run DOOM, video playback, and music on a Raspberry Pi 3.

## Problem

Traditional instructional OSes are optimized for concept coverage, but many feel disconnected from the kinds of programs students actually want to build and show to other people. Headless shells and toy file systems do teach abstractions, yet they do little to counter the perception that systems work is mostly invisible machinery, boilerplate, and pain. The authors also argue that this matters more now because OS is increasingly an elective: the students who take it may be capable, but they still need a reason to care.

The obvious alternative, teaching with Linux or Android, has the opposite failure mode. The software is real, but the codebase is too large and indirect for students to experience whole-system construction. Proto therefore aims for a middle ground: an end-to-end OS that remains small enough to build within a semester, but whose milestones are emotionally legible and demoable, such as spinning donuts, Mario, music playback, DOOM, and a desktop on portable commodity hardware.

## Key Insight

The paper's central proposition is that applications should act as the dependency oracle for OS design. Instead of enumerating canonical subsystems first and then inventing assignments for them, Proto picks a sequence of target apps and asks what minimum viable mechanism each app truly needs. That choice keeps every prototype self-contained, gives students a visible reason for each abstraction, and prevents feature accretion for its own sake.

This works because the chosen apps expose concrete failure modes. Graphics needs framebuffer and timers; Mario motivates user/kernel separation and page tables; music forces asynchronous I/O, DMA, and synchronization; DOOM and a blockchain miner justify nonblocking I/O, threads, multicore execution, and a window manager. The incremental prototypes are therefore not just scaffolding, but the actual method for rationing complexity without losing realism.

## Design

Proto's complete system is a monolithic ARMv8 kernel, broadly xv6-like in structure, with EL1 kernel mode, EL0 user mode, per-process address spaces, 28 syscalls, procfs/devfs-style interfaces, and a mixed ramdisk-plus-FAT32 storage layout. The key design move is to fully implement that system first and then factor it into five snapshots that remain runnable in their own right.

Prototype 1 is bare-metal I/O: one app, one core, no privilege separation, framebuffer rendering, timer interrupts, and polling UART. The pedagogical move is to make graphics first-class immediately, so the earliest artifact is already demonstrable. Prototype 2 adds multitasking and simple scheduling by running multiple donut tasks with independent timing. Prototype 3 introduces user/kernel separation, virtual memory, fork/exec-style task management, and direct framebuffer mapping so a userspace Mario build can run in its own address space.

Prototype 4 is where the OS stops feeling toy-like. It adds xv6's simple filesystem on a ramdisk, file syscalls, device files for framebuffer, audio, and keyboard, USB keyboard support via a ported bare-metal USB stack, and DMA-backed audio output. The Mario event loop at this stage is deliberately structured around IPC so that asynchronous inputs become visible in the design. Prototype 5 adds the heavier machinery demanded by richer apps: FatFS on an SD card, a small polling SD driver, nonblocking I/O, `clone(CLONE_VM)`-style threads, semaphores, user-level synchronization primitives, multicore scheduling across the Pi 3's four cores, and a compact window manager implemented as a kernel thread that composites surfaces and routes focus-sensitive input.

Two design choices are especially revealing. First, the paper repeatedly prefers simple, UNIX-like interfaces that make existing libraries portable, even if they are not the most elegant design. Second, it invests heavily in self-hosted debugging on real hardware, including ARM debug exceptions, a stack unwinder, tracing, and a GPIO-triggered panic button, because the system is meant to survive outside QEMU.

## Evaluation

The evaluation has two parts: systems usefulness and pedagogical usefulness. On the systems side, the complete prototype reaches about 33K kernel SLoC, but the kernel core stays below 10K SLoC, which keeps it within instructional-OS scale. Microbenchmarks report about 3.4 microseconds for a syscall and 21 microseconds for one-way IPC, with latencies generally close to xv6 and within roughly 0.5x-2x of Linux and FreeBSD on the same Pi 3. App benchmarks are the more important result: Proto runs DOOM at 61.8 FPS, 480p video at 26.7 FPS, and Mario variants at roughly 72-115 FPS depending on the software structure. Power draw is about 3W at shell prompt and about 4W under game or media load, corresponding to about 3.7 and 2.6 hours of battery life on the handheld setup.

This evidence is reasonably aligned with the paper's practical claim. The authors compare against Linux and FreeBSD using the same hardware, compiler settings, and app sources, which makes the throughput comparison credible even when Proto loses on `fork()` and file I/O. The weaker half is the pedagogical evidence: a Spring 2025 survey with 48 responses out of 59 students found strong support for the four design principles, and 64% of students chose to experiment on real hardware. That supports the motivation story, but it is still self-reported evidence from a single course offering.

## Novelty & Impact

Relative to xv6, Pintos, and similar teaching OSes, Proto changes the unit of curriculum design from subsystem milestone to app milestone. Relative to Linux- or Android-based courses, it insists on whole-system ownership rather than modification of a production codebase. The novelty is therefore not a new kernel algorithm, but a co-design of OS architecture, hardware target, and lab progression that makes "modern OS construction" legible within one semester.

That is a useful contribution. Educators can reuse the decomposition itself, while systems builders can take the broader lesson that usability and demonstrability are not superficial extras in systems education; they are part of the abstraction boundary students are learning to build.

## Limitations

Proto is intentionally selective about modernity. It omits crash consistency, networking, pthreads, signals, and HDMI audio, either because the app story did not justify them or because the implementation burden would overwhelm the course. Even included subsystems are often simplified: the SD driver polls instead of using DMA, FatFS is bridged through pseudo-inodes, and the window manager lives in the kernel to avoid cross-process graphics IPC.

The pedagogical evaluation is also narrower than the paper's rhetoric. There is no controlled comparison against xv6- or Linux-based courses, no long-term retention study, and no evidence that the same prototype sequence transfers cleanly to different institutions or hardware. The student feedback quoted in the paper also surfaces real costs: hardware setup can be awkward, the workload can be intense, and the breadth-first design leaves less room for deep treatment of any single subsystem.

## Related Work

- _Hovemeyer et al. (SIGCSE '04)_ - GeekOS gives students a bare-metal OS to extend, whereas Proto organizes progress around increasingly rich graphical applications and real-device demonstrations.
- _Pfaff et al. (SIGCSE '09)_ - Pintos also uses sequential labs on a small OS, but its milestones are classic subsystems; Proto's milestones are end-user apps that force those subsystems into existence.
- _Andrus and Nieh (SIGCSE '12)_ - Android-based teaching gains realism from production software, while Proto keeps the stack small enough that students can still own the whole system.
- _Gebhard et al. (SIGCSE '24)_ - Embedded Xinu on bare-metal RISC-V shares Proto's emphasis on real hardware, but Proto adds media-rich apps, USB, FAT32, and windowed interaction as the main motivational loop.

## My Notes

<!-- empty; left for the human reader -->

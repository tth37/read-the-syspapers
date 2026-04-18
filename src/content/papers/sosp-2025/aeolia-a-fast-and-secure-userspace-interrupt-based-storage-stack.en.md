---
title: "Aeolia: A Fast and Secure Userspace Interrupt-Based Storage Stack"
oneline: "Aeolia delivers NVMe completions directly to userspace, combines MPK-protected trusted components with sched_ext, and makes kernel-bypass storage sharable."
authors:
  - "Chuandong Li"
  - "Ran Yi"
  - "Zonghao Zhang"
  - "Jing Liu"
  - "Changwoo Min"
  - "Jie Zhang"
  - "Yingwei Luo"
  - "Xiaolin Wang"
  - "Zhenlin Wang"
  - "Diyu Zhou"
affiliations:
  - "Peking University"
  - "Zhongguancun Laboratory"
  - "Microsoft Research"
  - "Igalia"
  - "Michigan Technological University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764816"
code_url: "https://github.com/TELOS-syslab/Aeolia"
tags:
  - storage
  - filesystems
  - scheduling
  - security
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Aeolia shows that a userspace storage stack does not need polling to be fast. It uses user interrupts for NVMe completions, MPK-protected trusted code for permissions and metadata integrity, and `sched_ext` to avoid wasteful sleep-and-wakeup decisions. That keeps `AeoDriver` near SPDK for isolated I/O while letting `AeoFS` behave like a sharable, scalable file system.

## Problem

Fast NVMe SSDs have pushed media latency into the single-digit microsecond range, so software overhead now dominates. Polling-based userspace stacks such as SPDK win on raw latency because they bypass syscalls and kernel layering, but they do not safely share disks among untrusted tasks and they waste CPU time spinning, which hurts shared-core latency. Kernel interrupt-based stacks can arbitrate permissions and scheduling, yet they still pay trapping, layering, and scheduler overhead.

The file-system story is also unsatisfactory. uFS restores sharing by moving the file system into a separate polling process, but every operation then pays IPC and relies on centralized workers that limit scalability.

## Key Insight

The paper's core claim is that polling's advantage has been overstated. For a `4 KB` read, Aeolia's breakdown attributes only `0.6 us` of the `2.8 us` gap between default `io_uring` interrupts and polling to the interrupt mechanism; `1.8 us` comes from the kernel's choice to sleep the issuer and later wake it. If completions go directly to userspace and the stack yields only when another runnable thread should run, interrupts recover most of polling's latency benefit without polling's CPU waste.

That observation creates a new design point. A userspace stack can stay direct-access and low-latency while still being sharable, as long as interrupt delivery, permissions, and scheduling state are all made first-class in userspace.

## Design

Aeolia has three pieces. `AeoKern` sets up queue pairs, permissions, and scheduling state. `AeoDriver` is a userspace NVMe driver that submits requests directly and handles completions in userspace. `AeoFS` is a POSIX-like library file system on top.

To make device completions look like user interrupts, Aeolia matches the device vector to `UINV` and maps the thread's `UPID` into trusted `AeoDriver` memory so the handler can rewrite `PIR` without trapping back into the kernel. Out-of-schedule completions still enter the kernel first so the scheduler can mark the target thread runnable immediately.

Protected sharing uses MPK rather than a separate privileged server. Trusted code runs in a protected domain, `AeoDriver` enforces a per-block permission table, and `AeoFS` splits trusted core metadata from untrusted caches. That lets the file system do eager checks on operations such as `create`, `rename`, and inode updates instead of Trio's lazy verifier model.

Scheduling coordination comes from `sched_ext`. Trusted userspace reads EEVDF-like state from eBPF maps and calls `sched_yield()` only at the same logical decision points where the kernel would reschedule. `AeoFS` then builds scalable caches, per-inode locks, and per-thread ordered-mode journaling on top of that substrate.

## Evaluation

The experiments use a 128-core Xeon Platinum 8592 with an Optane P5800X, which is a worst case for Aeolia because device latency is already tiny. Against tuned Linux baselines and SPDK, `AeoDriver` is much better than the kernel path and close to SPDK: on `512 B` reads it reaches `2x` POSIX throughput with `48%` lower median latency, and its worst small-I/O gap to SPDK is `10.7%` throughput on `512 B` reads.

The decisive result is shared-core behavior. When latency-sensitive I/O tasks run with compute-bound or throughput tasks, `AeoDriver` cuts tail latency relative to `SPDK` and `iou_poll` by `8.18x` to `291.72x`, showing that interrupt-driven userspace coordinates with the scheduler far better than polling.

`AeoFS` also benefits. On single-thread `4 KB` data access it beats `ext4` and `f2fs` by up to `12.6x` and `12.8x`, and on a `64`-thread `2 MB` write it is up to `19.1x`, `28.9x`, and `8.4x` faster than `ext4`, `f2fs`, and `uFS`. Filebench shows up to `3.1x` and `6.6x` gains over `ext4` and `f2fs`, while LevelDB shows up to `2.9x`, `3.4x`, and `8.2x` over `ext4`, `f2fs`, and `uFS`. The paper also reports `96` handcrafted attacks against the trusted components and says Aeolia blocks them all. Overall the evidence is broad, but crash consistency is only unit-tested, and one `uFS` macrobenchmark comparison had to be rerun with the repository's own settings after the initial setup did not produce stable runs.

## Novelty & Impact

The novelty is not a faster SPDK clone. Aeolia combines userspace direct access with interrupt delivery, protected sharing, and scheduler awareness in one design point that earlier work treated as impractical. Its broader impact is the argument that kernel bypass does not have to imply polling.

## Limitations

Aeolia depends on new platform features: Intel user interrupts, MPK-style intra-process isolation, and Linux `sched_ext`. Small requests below `4 KB` still favor polling slightly. The prototype also does not yet implement the launch-time signature-registration and privileged-launch path used to justify one protection invariant.

`AeoFS` falls behind `uFS` when multiple untrusted applications repeatedly update the same file or shared directory, because rebuilding auxiliary state and synchronizing eager checks becomes expensive. The crash-consistency design is plausible, but the paper does not validate it with a dedicated crash-testing framework.

## Related Work

- _Yang et al. (CloudCom '17)_ - SPDK established the performance case for polling-based direct userspace storage; Aeolia keeps direct NVMe access but replaces polling with user interrupts and adds protected sharing.
- _Liu et al. (SOSP '21)_ - uFS also seeks high-performance userspace file systems, but it relies on IPC and dedicated polling workers, whereas AeoFS keeps the fast path inside the application process with trusted in-process components.
- _Zhou et al. (SOSP '23)_ - Trio separates core state from auxiliary state for secure library file systems on NVMM; AeoFS adopts that split for SSDs and switches from lazy verification to eager metadata checks.
- _Zhong et al. (OSDI '22)_ - XRP preserves file-system semantics by pushing storage functions into the kernel NVMe driver, while Aeolia moves the stack outward into userspace and solves isolation and scheduling there.

## My Notes

<!-- empty; left for the human reader -->

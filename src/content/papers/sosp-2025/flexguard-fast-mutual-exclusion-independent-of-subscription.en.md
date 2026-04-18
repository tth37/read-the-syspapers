---
title: "FlexGuard: Fast Mutual Exclusion Independent of Subscription"
oneline: "FlexGuard uses eBPF scheduler hooks to block lock waiters exactly when a critical section is preempted, keeping spinlock latency without oversubscription collapse."
authors:
  - "Victor Laforet"
  - "Sanidhya Kashyap"
  - "Călin Iorgulescu"
  - "Julia Lawall"
  - "Jean-Pierre Lozi"
affiliations:
  - "Inria"
  - "EPFL"
  - "Oracle Labs"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764852"
code_url: "https://gitlab.inria.fr/flexguard"
tags:
  - scheduling
  - kernel
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

FlexGuard is a user-space lock design plus an eBPF-based preemption monitor that makes waiting threads stop spinning exactly when the scheduler has preempted a thread that is already on the lock's critical path. The core result is subscription-agnostic behavior: it stays close to a fast spinlock when threads fit on hardware, but falls back to blocking quickly enough to avoid the catastrophic collapse that oversubscribed spinlocks suffer.

## Problem

The paper targets a familiar but still unresolved tradeoff in multicore software. Pure spinlocks minimize handover latency because the next owner is already running, but once the number of contending threads exceeds the available hardware contexts, spinning threads can preempt the lock holder itself. At that point the machine burns CPU without advancing the critical path, and latency explodes. Pure blocking locks avoid this collapse because waiters sleep, but every contended handover pays kernel-mediated wakeup and context-switch cost, so they lose badly when the system is not oversubscribed.

The standard compromise is spin-then-park, used by POSIX locks and many research locks. The difficulty is that these schemes all need a heuristic for when to stop spinning. Prior work infers preemption indirectly from stale timestamps, periodic thread-count probes, sleep-slot buffers, or timeslice tuning. The paper argues that this is the wrong level of abstraction: the scheduler already knows whether the critical path has been interrupted, so guessing from user space inevitably leaves either too much spinning or too much blocking.

## Key Insight

The key claim is that lock contention should react to actual critical-section preemptions, not to proxies for them. With eBPF attached to `sched_switch`, the system can inspect every context switch, determine whether the descheduled thread currently holds a lock or is in lock/unlock code that already belongs to the critical section, and maintain a system-wide counter of such preemptions. Once that counter becomes positive, the lock can switch immediately from busy-waiting to blocking; once it returns to zero, the lock can resume spinning.

That direct signal matters for two reasons. First, it addresses lock-holder preemptions without guessing timeout values. Second, it also handles next-waiter preemptions in queue-based locks: if the thread that should receive the next handoff is itself stalled, FlexGuard stops insisting on strict spin-based queue progression and temporarily lets blocked threads compete through a simpler blocking path. The scheduler is no longer a black box but an explicit input to the lock algorithm.

## Design

FlexGuard has two pieces. The Preemption Monitor is an eBPF handler on `sched_switch`. For each thread, lock code maintains a thread-local `cs_counter` that is incremented after acquisition and decremented before release. The monitor also uses assembly labels and saved registers to catch the narrow windows inside `lock()` and `unlock()` where the thread logically holds the lock even though `cs_counter` has not yet been updated. If a preempted thread is in any of those regions, the monitor marks it as preempted in a critical section and increments the global `num_preempted_cs`; when that thread runs again, the counter is decremented.

The lock algorithm itself combines a simple single-word lock with an MCS queue. In busy-waiting mode, threads first try a TATAS-like fast path; under contention they enter an MCS-style slow path so that only the queue head spins on the shared lock word while others spin on local queue nodes. This preserves the low cache-coherence cost of queue locks. If `num_preempted_cs` becomes positive, the algorithm enters blocking mode. Threads abandon or bypass the MCS queue, mark the shared word as `LOCKED_WITH_BLOCKED_WAITERS`, and sleep with `futex_wait()`. Unlock wakes one blocked waiter only when necessary, which keeps the Futex path off the uncontended fast path.

Two invariants are central. Mutual exclusion always reduces to ownership of the single-variable lock, regardless of waiting mode. Liveness comes from the fact that blocked threads sleep only while the lock state indicates blocked waiters, and each release issues `futex_wake()` when that state is set. The system-wide preemption counter is also deliberate: a waiter on one lock can preempt the holder of another, so freeing CPUs globally is better than using a per-lock signal.

## Evaluation

The evaluation covers two microbenchmarks and five applications on two Linux 6.9 servers: a 104-hardware-context Intel machine and a 512-hardware-context AMD machine. In the shared-memory-access microbenchmark, FlexGuard delivers the paper's clearest result: compared with a pure blocking lock, it reduces critical-section latency by up to 92% on Intel and 100% on AMD while still avoiding the orders-of-magnitude oversubscription collapse seen in MCS. The hash-table microbenchmark shows the same pattern at many locks: FlexGuard remains stable as thread counts rise, while conventional spinlocks degrade sharply.

The application results are broad rather than cherry-picked around a single workload. On a PiBench memory-optimized B+-tree index, FlexGuard averages 4.2x POSIX throughput in non-oversubscription and 3.4x under oversubscription. On Dedup, which allocates up to 266K locks, it beats POSIX by 24.7% and 38.3% on average in the two regimes, helped by using one queue node per thread instead of one per thread per lock. On LevelDB, it improves `readrandom` by 67% and 25% on average, and `fillrandom` by 14% and 11%. Raytrace sees smaller but still positive gains, around 4% and 21% on average. The main exception is Streamcluster on Intel under a concurrent workload, where FlexGuard can be up to 82% worse than POSIX because extra runnable spinners delay barrier completion; the authors explicitly frame barriers as future work.

The supporting analyses strengthen the paper's central claim. Hackbench shows the preemption monitor adds less than 1% scheduler overhead in a worst-case context-switch-heavy test. Fairness remains good: in a worst-case mode-flipping scenario, FlexGuard's fairness factor stays below 0.58, comparable to MCS. The runnable-thread trace also explains why the design works: unlike MCS, which keeps all contenders runnable, and unlike pure blocking, which often leaves only one runnable owner, FlexGuard keeps just enough runnable waiters for fast handoff without letting spinning consume the machine.

## Novelty & Impact

The novelty is not merely "another hybrid lock." FlexGuard changes the control signal for hybrid synchronization from heuristics to direct scheduler feedback. That shift lets it match spinlock behavior when spinning is safe and revert to blocking precisely when spinning would stall the critical path. Relative to Shuffle-style or Malthusian designs, the important contribution is not the MCS-plus-single-word structure itself, but the fact that eBPF exposes lock-relevant preemption information without kernel modification.

This should matter to both lock designers and systems implementers. The paper shows that modern kernels expose enough observability to let user-space synchronization adapt to scheduler state in real time, and it suggests the same pattern could extend beyond mutexes to reader-writer locks, condition variables, barriers, or more advanced delegation and NUMA-aware locks. It is a new mechanism with immediate practical implications for libraries that currently default to conservative spin-then-park policies.

## Limitations

FlexGuard is not universal. Its monitor is tied to lock implementations that can expose critical program points through inline assembly labels and predictable register usage, and the paper's implementation is for Linux plus x86. Porting to other architectures or operating systems appears feasible, but it is engineering work, not an automatic win. The scheme also assumes access to a Futex-like primitive and eBPF scheduler tracepoints.

The evaluation also reveals a workload boundary. FlexGuard is built around the insight that spinning is harmful when it blocks lock progress, but barrier-heavy programs can still suffer if extra runnable threads preempt non-lock-holding work. Streamcluster on Intel demonstrates this clearly. More broadly, the strongest results come from lock-dominated workloads; the paper is less informative about mixed applications where lock handoff is only a secondary bottleneck. The timeslice-extension variant sometimes helps further, which also implies FlexGuard alone does not eliminate every scheduler-induced loss mode.

## Related Work

- _He et al. (HiPC '05)_ - MCS-TP infers lock-holder preemption from stale timestamps, whereas FlexGuard directly detects preempted critical sections through `sched_switch`.
- _Dice (EuroSys '17)_ - Malthusian locks reduce runnable waiters by culling threads with heuristic spin-then-park behavior; FlexGuard blocks because the critical path is known to be stalled, not because a timeout expired.
- _Kashyap et al. (SOSP '19)_ - Shuffle lock combines MCS and a simple lock to reduce cache contention, and FlexGuard borrows that structure, but replaces heuristic parking with scheduler-driven mode switches.
- _Patel et al. (EuroSys '20)_ - u-SCL coordinates with the scheduler using fixed lock slices, while FlexGuard reacts to actual preemptions and preserves ordinary lock handoff when no preemption occurs.

## My Notes

<!-- empty; left for the human reader -->

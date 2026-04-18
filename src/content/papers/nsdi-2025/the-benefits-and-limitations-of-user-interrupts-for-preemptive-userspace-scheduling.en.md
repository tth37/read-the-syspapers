---
title: "The Benefits and Limitations of User Interrupts for Preemptive Userspace Scheduling"
oneline: "Measures user interrupts as a preemption primitive, showing they cut signal overhead 6x but help only when the runtime can exploit fine-grained scheduling."
authors:
  - "Linsong Guo"
  - "Danial Zuberi"
  - "Tal Garfinkel"
  - "Amy Ousterhout"
affiliations:
  - "UC San Diego"
conference: nsdi-2025
code_url: "https://github.com/LinsongGuo/aspen.git"
tags:
  - scheduling
  - datacenter
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

The paper evaluates Intel user interrupts as a userspace preemption primitive by implementing them in Aspen-KB and Aspen-Go. User interrupts cut basic preemption overhead from `2.4 us` with signals to `0.4 us`, usually outperform compiler instrumentation once quanta exceed about `10 us`, and deliver large tail-latency wins only when the runtime is built to exploit fine-grained preemption.

## Problem

Server workloads mix sub-microsecond and hundreds-of-microsecond tasks, so short requests queue behind long ones and tail latency grows quickly. Kernel schedulers preempt too coarsely for sub-millisecond latency, while userspace runtimes mostly avoid preemption because current mechanisms are unsatisfying. Signals are expensive because every preemption crosses the kernel twice, and compiler instrumentation depends heavily on control flow and tuning. The paper asks whether user interrupts can make frequent userspace preemption cheap and predictable enough to matter in real runtimes.

## Key Insight

User interrupts help because they make asynchronous preemption cheap and regular, not because they fix scheduling by themselves. The runtime still needs to skip unnecessary preemptions, handle non-preemptible regions, save register state correctly, poll for fresh work promptly, and prioritize newly arrived work over already-preempted tasks. That is why the same primitive yields big gains in a kernel-bypass runtime and only modest gains in Go.

## Design

The authors first compare signals, compiler instrumentation, and user interrupts on 24 benchmark programs. User interrupts require one-time kernel registration, then sender and receiver communicate entirely in userspace, avoiding per-preemption kernel mediation. They then build two schedulers.

Aspen-KB extends Caladan with a timer core that can see RX queues and scheduler timestamps in shared memory. It preempts only when a thread has exhausted its quantum and other work exists. Each core uses two queues: newly runnable work enters a high-priority new queue, while preempted work goes to a lower-priority queue with a longer quantum. The implementation keeps software deferral for non-preemptible code because `clui`/`stui` would add too much overhead in frequent regions such as `malloc`, and it conservatively saves general-purpose and AVX-512 registers on context switch. Aspen-Go makes smaller changes: a busy-spinning `sysmon`, user-interrupt delivery, and more aggressive network polling, but it keeps Go's global/local queue structure and dependence on the OS network stack.

## Evaluation

Signals cost `2.4 us` per preemption versus `0.4 us` for user interrupts. For a slowdown budget of `10%`, signals support only about a `30 us` quantum, while user interrupts remain viable at `5 us`. Compiler instrumentation can be slightly cheaper below `10 us`, but the results are fragile and highly sensitive to probe placement.

On Aspen-KB, the cheaper mechanism translates into better scheduling. For RocksDB with `95%` GET and `5%` SCAN, user interrupts improve GET throughput by `58.2%` over the non-preemptive baseline while keeping GET tail latency under `50 us`; the best quantum is `5 us` for user interrupts versus `15 us` for signals. Fine-tuned Concord can get close, but the default configuration is brittle: one SCAN triggers over `95,000` checks and suffers `31.2%` slowdown at `5 us`, versus `2.3%` after tuning. On DataFrame, whose tasks span `5 us` to `250 us`, a `20 us` quantum works best; user interrupts raise short-task throughput by about `30%` over non-preemptive execution and `9%` over fine-tuned Concord because compiler instrumentation still pays `3.3 us` on tight-loop tasks where user interrupts add only `0.37-0.32 us`.

Aspen-Go shows the limit. On BadgerDB, Aspen-Go UINTR improves GET throughput by only `17.5%` over stock Go at a `1000 us` tail-latency target, and compiler instrumentation is another `6%` better. The paper attributes this to Go's design: packets can wait in the kernel network stack, new goroutines may be appended to the global queue, `sysmon` cannot see whether packets are waiting, and interrupts that land at unsafe points are discarded. Timer scalability shows the same pattern: at `5 us`, one timer core supports `22` application cores with user interrupts, `24` with compiler instrumentation, and only `2` with signals.

## Novelty & Impact

The novelty is not merely using user interrupts, but explaining when they matter. By comparing three mechanisms inside both a low-latency kernel-bypass runtime and a mainstream language runtime, the paper turns user interrupts from a hardware curiosity into a design rule: they are usually the best default once quanta are around `10 us` or larger, but only if the runtime can actually convert frequent preemption into earlier service for new work.

## Limitations

The study covers only two runtimes on Intel hardware with user-interrupt support, so the quantitative results should be read as upper and lower bounds rather than universal constants. Compiler instrumentation can still win at ultra-small quanta. User interrupts also leave context-switch cost, unsafe points, thread-local-state handling, and extended-register saving as real engineering burdens. They remove one bottleneck, not the whole scheduling problem.

## Related Work

- _Kaffes et al. (NSDI '19)_ - `Shinjuku` also targets microsecond-scale tail latency with preemptive scheduling, but this paper focuses on how Intel user interrupts compare with signals and compiler instrumentation as the primitive underneath that policy.
- _Iyer et al. (SOSP '23)_ - `Concord` represents the compiler-instrumentation approach to microsecond scheduling, and this paper shows exactly where that approach remains competitive and where it becomes brittle or tuning-heavy.
- _Li et al. (HPCA '24)_ - `LibPreemptible` also uses hardware-assisted userspace preemption, while Aspen-KB emphasizes skipping unnecessary preemptions and per-core two-queue scheduling to better control head-of-line blocking.
- _Fried et al. (NSDI '24)_ - `Junction` uses user interrupts in kernel-bypass cloud systems, whereas this paper centers the mechanism tradeoff itself and tests how much benefit survives inside a mainstream runtime like Go.

## My Notes

<!-- empty; left for the human reader -->

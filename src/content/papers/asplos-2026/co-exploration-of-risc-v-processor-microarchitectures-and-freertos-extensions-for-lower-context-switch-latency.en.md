---
title: "Co-Exploration of RISC-V Processor Microarchitectures and FreeRTOS Extensions for Lower Context-Switch Latency"
oneline: "Adds a configurable RTOSUnit to RISC-V cores so FreeRTOS can overlap context save/restore and optionally hardware-schedule tasks, cutting latency and jitter."
authors:
  - "Markus Scheck"
  - "Tammo Mürmann"
  - "Andreas Koch"
affiliations:
  - "Technical University of Darmstadt, Darmstadt, Hesse, Germany"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790141"
code_url: "https://github.com/esa-tu-darmstadt/RTOSUnit_Integration"
tags:
  - scheduling
  - kernel
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

The paper argues that FreeRTOS context switches are slow not because any one instruction is expensive, but because saving state, choosing the next task, and restoring state are serialized in software. RTOSUnit breaks that serialization with a configurable hardware block that can offload context storing, context loading, and scheduling independently. Across three RISC-V cores, the strongest configuration cuts mean context-switch latency by up to `76%` and can eliminate jitter on the simplest core.

## Problem

In embedded real-time systems, an interrupt often cannot finish the real work inside the ISR itself; instead it wakes or switches to a task that performs the deferred handling. That means the interrupt response time includes the full RTOS context switch. FreeRTOS must save 29 mutable general-purpose registers plus `mstatus` and `mepc`, run its scheduler over ready and delay lists, then restore the next task. The paper treats the total delay from interrupt trigger to `mret` as the relevant latency, and the spread between best and worst cases as jitter.

That jitter matters as much as the mean. Control loops and safety-critical software need predictable upper bounds for WCET analysis, but FreeRTOS’s software scheduler and memory traffic make switch time vary with queue contents, delayed tasks, and microarchitectural effects. A naive answer would be "just use bare metal," but that throws away the modularity and synchronization abstractions that make RTOSes usable. The real question is therefore whether one can preserve the FreeRTOS programming model while removing the serialized software path that dominates latency and predictability.

## Key Insight

The central idea is that RTOS context switching has more overlap than standard software implementations exploit. Once an interrupt arrives, the processor does not actually need to wait for every architectural register to be written back to memory before running the scheduler; it only needs a clean register bank so the ISR can execute. Likewise, once the next task is known, restoring its state can proceed in parallel with the tail of the ISR. If the ready and delay lists are also moved into hardware, the ISR shrinks to little more than updating `currentTCB`.

That insight leads to a design-space argument rather than a single monolithic accelerator. Different embedded deployments care differently about area, average latency, and jitter, so RTOSUnit exposes composable features: `S` for background context storing, `L` for hardware context loading, `T` for hardware scheduling, plus optional dirty-bit skipping, load omission, and speculative preloading. The paper’s claim is not merely that hardware can help, but that these specific pieces can be combined to trade silicon cost for timing guarantees in a controlled way.

## Design

RTOSUnit is tightly integrated through custom RISC-V instructions instead of MMIO. The baseline `vanilla` path keeps the normal FreeRTOS ISR. In configuration `S`, the core gains an alternate register-file bank for ISR execution. On interrupt entry, the processor switches to fresh registers immediately, while a store FSM writes the interrupted task’s 31-word context to a reserved memory region in the background. Each task gets a fixed 32-word slot indexed by a task ID, so the hardware can derive the save address directly instead of updating stack pointers in the TCB.

Configuration `L` adds a restore FSM. After software selects the next task and emits `SET_CONTEXT_ID`, RTOSUnit starts loading that task’s saved context into the application register file and the relevant CSRs. The `mret` that exits the ISR is stalled until the restore completes, so correctness is preserved while the load overlaps with ISR work. When both `S` and `L` are present, register-bank switching happens automatically on interrupt entry and exit.

Configuration `T` moves FreeRTOS ready and delay lists into hardware. `ADD_READY`, `ADD_DELAY`, and `RM_TASK` maintain the lists, while `GET_HW_SCHED` returns the head of the ready queue and requeues it to preserve round-robin behavior within a priority. The delay list is sorted by remaining ticks and then priority; timer interrupts decrement delays and automatically move expired tasks back into the ready list. This does not handle FreeRTOS event lists for synchronization primitives, so the design is a partial scheduler offload rather than a whole-kernel replacement.

The optional optimizations are pragmatic. Dirty bits avoid writing back registers that were never modified; load omission skips restore when the next task is identical to the previous one; preloading speculatively fetches the context of the current head of the ready list into a 31-word buffer. Preloading is fastest when the guess is right, but it can mispredict when an interrupt wakes a higher-priority task. The integration story is also part of the contribution: the authors port RTOSUnit to a simple in-order CV32E40P, a CVA6 core with out-of-order write-back, and a fully out-of-order NaxRiscv that requires buffering custom instructions until they are known to have committed and translating architectural to physical register addresses.

## Evaluation

The evaluation uses all RTOSBench tests for the RISC-V FreeRTOS port, run for 20 iterations, with ready and delay lists sized to eight entries. Latency is measured from interrupt trigger to `mret`, and jitter is max minus min latency. The authors compare multiple RTOSUnit configurations against unmodified software switching and against a reimplementation of Balas et al.’s `CV32RT` snapshotting design on all three cores.

The first important result is that overlapping the switch phases beats partial snapshotting. `CV32RT` improves average latency by only `3%-12%`, whereas RTOSUnit’s simplest `S` mode improves it by `17%-27%` with similar jitter. Hardware scheduling alone is especially strong for predictability: on CV32E40P, jitter drops from `188` cycles to `16`, over a `90%` reduction, while mean latency still improves by `23%`, `29%`, and `9%` on CV32E40P, CVA6, and NaxRiscv respectively. The fully accelerated `SLT` configuration minimizes both metrics: it removes jitter entirely on CV32E40P, reduces jitter by up to `88%` on the larger cores, and leaves context movement itself as the remaining bottleneck.

The second important result is about hard-real-time bounds and silicon cost. For CV32E40P, the baseline WCET is `1649` cycles; `SL` lowers that to `1442`, `T` to `202`, and `SLT` to `70` cycles, matching the measured latency. On average latency, the conclusion reports up to `69%` reduction for the hard-real-time-oriented `SLT` design, while the abstract reports up to `76%` reduction across the explored design space, reflecting that aggressive options such as preloading can push the mean lower at the cost of more variability. Area overhead ranges from effectively zero for scheduling-only `T` on CV32E40P to about `44%` for the preloading-heavy `SPLOT` configuration; power tends to track area, with relative increases up to `72%` on CV32E40P but much smaller absolute power changes. This evaluation supports the paper’s main point well: the best configuration depends on whether the target system prioritizes worst-case predictability, mean latency, or silicon budget.

## Novelty & Impact

Relative to _Balas et al. (TVLSI '24)_, the paper does not just speed up part of register spilling; it overlaps full-context save and restore with ISR execution and couples that with an optional hardware scheduler. Relative to _Rafla and Gauba (MWSCAS '11)_, it emphasizes portability across very different RISC-V cores instead of a single tightly tailored processor design. Relative to FASTCHART-style hardware RTOS work, it avoids assuming unrealistic one-cycle context dumps and instead works within ordinary memory bandwidth limits.

That makes the contribution useful to two audiences. For embedded architects, it is a concrete recipe for where to cut into the processor/RTOS boundary to improve response time without abandoning FreeRTOS. For real-time researchers, it is a design-space study showing that scheduling offload can matter as much as raw context spill bandwidth when the goal is low jitter rather than just a lower average.

## Limitations

The hardware scheduler mirrors only FreeRTOS ready and delay lists; event lists and synchronization remain in software. That means the system is not a fully hardware-managed RTOS kernel, and workloads dominated by mutex or semaphore interactions may still pay meaningful software overhead. The fixed context-memory region and hardware queue sizes also impose design-time upper bounds on task count, though the paper notes that systems can fall back to software scheduling beyond the configured limit.

Portability is demonstrated across three cores, but all are RV32IM_Zicsr FreeRTOS systems. Extending the context logic to floating-point or vector state is left as future work, as is multicore support. WCET analysis is only carried out for CV32E40P; for CVA6 and NaxRiscv, the authors explicitly treat precise WCET analysis as out of scope because cache behavior and speculation complicate it. So the strongest hard-real-time claims apply to the simpler in-order core, not yet to the more aggressive microarchitectures.

## Related Work

- _Balas et al. (TVLSI '24)_ — CV32RT snapshots half of the register file to speed interrupts, whereas RTOSUnit overlaps full context movement and can also offload scheduling.
- _Rafla and Gauba (MWSCAS '11)_ — adds custom instructions and banked context memory on MIPS, but the ASPLOS paper targets broader configurability and evaluates three distinct RISC-V cores.
- _Grunewald and Ungerer (EUROMICRO '96)_ — assigns each task its own register file bank, making switching extremely fast but tying area cost directly to task count; RTOSUnit instead stores contexts in memory.
- _Nakano et al. (IEICE '99)_ — STRON offloads much of RTOS management to a coprocessor, while RTOSUnit focuses on a tighter processor-integrated path for scheduling and context handling.

## My Notes

<!-- empty; left for the human reader -->

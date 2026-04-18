---
title: "Sequential Specifications for Precise Hardware Exceptions"
oneline: "Extends PDL with pipeline exceptions so sequential processor specs can synthesize precise traps, interrupts, and CSR handling with unchanged CPI and modest cost."
authors:
  - "Yulun Yao"
  - "Drew Zagieboylo"
  - "Andrew C. Myers"
  - "G. Edward Suh"
affiliations:
  - "Cornell University, Ithaca, NY, USA"
  - "NVIDIA, Westford, MA, USA"
  - "Cornell University / NVIDIA, Ithaca, NY, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3760250.3762233"
code_url: "https://github.com/apl-cornell/PDL"
tags:
  - hardware
  - compilers
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

XPDL extends PDL with pipeline exceptions so a sequential processor specification can directly express precise traps, interrupts, and CSR-style control transfers. Programmers write ordinary pipeline code plus a `commit` block, an `except` block, and `throw` sites; the compiler generates rollback and flush logic automatically. On the evaluated RISC-V cores, common-case CPI stays unchanged and maximum frequency drops by `3.3%`.

## Problem

PDL is attractive because it gives pipelined processors a one-instruction-at-a-time (`OIAT`) programming model instead of exposing designers directly to RTL concurrency. The missing piece is that real processors must implement faults, traps, interrupts, system calls, and CSR updates while preserving older state and squashing younger work.

In hand-written RTL, that logic is usually intertwined with the rest of the pipeline and relies on bookkeeping structures or custom rollback paths. The paper argues that this is hard to reason about and that reusing PDL's speculation machinery would be a bad fit: exceptions are part of the ISA, not a performance optimization, and usually deserve a different area-time tradeoff.

## Key Insight

The key claim is that precise exceptions can still be expressed sequentially if an exceptional instruction is treated as a special bubble that reaches one finalization point. Older instructions finish their committed effects before rollback begins, while younger instructions are blocked from making architectural changes at all.

That works because PDL already separates transient pipeline work from final effects using locks and ordered commit points. XPDL turns exception handling into another explicit final path, then uses static rules to ensure an instruction either commits normally or rolls back and runs the exception handler atomically.

## Design

The language addition is small. `throw(args)` marks the current instruction as exceptional. `commit` contains the final actions for normal completion, usually releasing write locks so buffered writes become architectural state. `except(args)` contains the final actions for exceptional completion, such as writing CSRs and redirecting `pc` to a handler.

Compilation introduces two hidden flags: `lef`, a per-instruction exception bit that travels with the datapath, and `gef`, a pipeline-wide flag that turns off normal pipeline work during exception handling. When `throw` fires, generated code sets `lef` and stores the exception arguments. At the end of the ordinary pipeline, non-exceptional instructions enter `commit`; exceptional ones set `gef`, wait for older instructions already in the final region to finish, then execute rollback.

Rollback consists of clearing pipeline registers (`pipeclear`), clearing speculative state (`specclear`), and calling `abort` on every lock to discard uncommitted state. Only after that does the `except` block run. Bypass queues, renamed registers, and similar components therefore get exception recovery by implementing `abort` once.

The static rules preserve precise behavior. The except block must be self-contained. Final blocks are non-speculative. Write locks acquired in the pipeline body cannot be released early; they release only in `commit`. For interrupts, XPDL adds `volatile` memories so the pipeline can read externally updated device state while preserving sequential ordering.

## Evaluation

The implementation adds about `2k` lines of compiler and hardware support on top of PDL. The evaluation uses a 5-stage RV32IM baseline with speculation, register renaming, and a write queue, then adds fatal exceptions, system calls and interrupts, CSR instructions, and a combined design. Correctness is tested with directed examples plus software runs.

The strongest result is that common-case throughput is unaffected. With no exceptions firing, the baseline and exception-enabled processors both run at `1.59` CPI on `MachSuite-aes`. Frequency cost is modest: the fully featured design drops from `169.49 MHz` to `163.93 MHz` after synthesis and place-and-route in `45 nm` FreePDK. Compilation time is essentially unchanged, moving from `15.34 s` to `15.50 s`.

Area overhead is broken down rather than summarized by a single number. The paper says up to `65%` of the area increase within a configuration comes from register files and CSRs, which reflects the added functionality itself. Extra stage registers are the next main source, CSR decoding contributes about `10%` in the CSR-heavy case, and the full design remains under `500` lines of code.

## Novelty & Impact

Relative to prior PDL work, the novelty is giving exceptions their own language construct and synthesis path rather than forcing them through speculation or RTL handcrafting. Relative to checkpoint-and-rollback extensions for Verilog, XPDL raises the abstraction level and derives recovery behavior from lock interfaces. Relative to continuation-based synthesizable exceptions, it targets native processor exception semantics.

## Limitations

The simplification comes with real constraints. XPDL handles only one exception at a time, and the pipeline must be cleaned up before the handler runs, so interrupt latency is not minimal. Exception handling is non-speculative, and communication between exceptional and non-exceptional instructions is limited to architectural state.

The evaluation also stays within a narrow scope: mostly 5-stage RISC-V variants plus synthesis and simulation results, not direct comparisons against hand-tuned RTL exception machinery. That is enough to show feasibility, but not enough to prove clean scaling to wider or more out-of-order cores.

## Related Work

- _Zagieboylo et al. (PLDI '22)_ — PDL introduces an `OIAT` sequential HDL for pipelined processors, and XPDL extends that model with precise traps, interrupts, and CSR-style exception handling.
- _Chan et al. (DAC '12)_ — this work adds checkpointing and rollback mechanisms to Verilog processes, whereas XPDL raises exceptions to the language level and auto-generates rollback from lock abstractions.
- _Pelton et al. (PLDI '24)_ — Kanagawa targets high-level hardware synthesis for pipelined designs, but the XPDL paper argues it lacks an `OIAT`-style semantic guarantee and does not directly address non-sequential ISA behaviors.
- _Teng and Dubach (ASPDAC '25)_ — continuation-based synthesizable exceptions translate software-style exceptions into hardware, while XPDL focuses on native processor exception semantics and precise architectural state.

## My Notes

<!-- empty; left for the human reader -->

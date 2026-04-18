---
title: "Parameterized Hardware Design with Latency-Abstract Interfaces"
oneline: "Introduces latency-abstract interfaces and Lilac so generated hardware can expose compile-time timing parameters without paying latency-insensitive handshake overheads."
authors:
  - "Rachit Nigam"
  - "Ethan Gabizon"
  - "Edmund Lam"
  - "Carolyn Zech"
  - "Jonathan Balkind"
  - "Adrian Sampson"
affiliations:
  - "MIT CSAIL, Cambridge, USA"
  - "Cornell University, Ithaca, USA"
  - "UC Santa Barbara, Santa Barbara, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790199"
tags:
  - hardware
  - pl-systems
  - verification
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

The paper argues that many generated hardware blocks are wrapped in latency-insensitive interfaces only because their exact latency is unknown until generation time, not because their latency is truly dynamic. It introduces latency-abstract interfaces and Lilac, a parameterized HDL that treats timing as compile-time output parameters and proves every elaborated design is free of structural hazards.

## Problem

The paper separates two cases that hardware languages often blur together. When latency is fundamentally input dependent, designers need latency-insensitive (LI) handshakes. But many generated modules are really latency-sensitive (LS): their exact latency depends on design-time choices such as bitwidth or target frequency, yet becomes fixed once the generator runs. Designers still wrap those modules in LI interfaces because the rest of the design cannot easily adapt to timing changes.

That convenience is expensive. In the paper's FPU example, LI integration adds ready/valid logic, a control FSM, and a FIFO just to hide latency changes. Compared with LS implementations of the same FPU, the LI versions use 29-31% more LUTs, 3-4x more registers, and run 21-25% slower.

## Key Insight

The central observation is that generated hardware occupies a middle ground: timing is abstract while the parent module is written, but concrete by elaboration time. The right abstraction is therefore latency-abstract (LA): represent timing symbolically during design, then compile it into an efficient LS circuit after generation.

The enabling mechanism is upward-flowing output parameters. A child module returns values such as latency or initiation interval to its parent, and the parent uses those values to schedule downstream logic, insert balancing delays, and compute its own interface timing. This keeps timing adaptability at design time without paying LI handshake overhead at run time.

## Design

Lilac extends Filament-style timeline types with parameterization and output parameters. A generated adder interface still has ordinary input parameters such as bitwidth, but it also exports an output parameter `#L` for latency. Parents may use `#L` in timing expressions without knowing its concrete value ahead of elaboration. In the FPU example, a naive design that muxes adder and multiplier outputs immediately is rejected because the two values may become valid in different cycles. The corrected design reads `Add::#L` and `Mul::#L`, computes their maximum, and inserts parameterized shift registers to balance both datapaths and the opcode path.

Lilac adds compile-time bundles and loops so those timing expressions remain manageable. The type system checks three symbolic properties: values are read only when valid, ports are not multiply driven in the same cycle, and partially pipelined submodules are reinvoked only after their initiation interval allows it.

Elaboration then proceeds bottom-up: the compiler runs generators when their inputs are concrete, extracts output-parameter bindings, evaluates loops and conditionals, and lowers the result to Filament and then Verilog.

## Evaluation

The evaluation asks whether Lilac captures real generator interfaces and whether LA removes meaningful LI overhead. The examples in Figure 8, from a 480-line three-stage RISC core to 1346-line BLAS kernels, type-check in 160-1295 ms, with most cases under one second. The interface study also shows that Lilac can represent input-controlled latency, output-parameter-dependent latency, parameter-dependent initiation intervals, and multi-cycle input hold times.

The first hardware case study is the FloPoCo FPU. When adder and multiplier latencies are `(1,1)`, LI uses 614 LUTs and 824 registers versus 441 LUTs and 205 registers for LS, and frequency falls from 163.0 MHz to 134.5 MHz. At `(4,2)`, LI uses 662 LUTs and 1426 registers versus 459 LUTs and 482 registers, with frequency dropping from 280.8 MHz to 224.4 MHz.

The second case study is a Gaussian Blur Pyramid built from Aetherling-generated convolutions. The LI baseline wraps the same generated modules with ready/valid state machines; the Lilac version uses LA interfaces plus parameterized serializers and pipeline balancing. Averaged across five design points, LI costs 26.2% more LUTs, 33.0% more registers, and 6.8% lower frequency. As Aetherling exposes more parallelism, Lilac's serializer cost shrinks while the LI FSM overhead stays roughly constant.

## Novelty & Impact

Relative to _Nigam et al. (PLDI '23)_, the novelty is not just timeline-typed scheduling but making timing itself parameterized and allowing it to flow from child generators back to parents. Relative to parameterized HDLs such as Bluespec, Lilac describes how parameters affect temporal behavior and verifies that relationship compositionally. Relative to generator systems such as FloPoCo or Aetherling, Lilac is an integration layer that lets designers consume shifting timing contracts without defaulting to LI wrappers.

Its broader claim is that some ready/valid-heavy designs are artifacts of poor abstractions rather than hard necessities.

## Limitations

The paper does not claim that LA replaces LI. If timing is genuinely input dependent at runtime, LI synchronization remains necessary. Lilac only addresses the regime where timing is abstract during design but concrete after elaboration.

Even there, the approach has limits. The SMT reasoning can require user-supplied facts for harder equalities, and the elaborator needs enough concrete structure to break cycles in the instantiation graph. The evaluation also focuses on FPGA-oriented generators and structural overhead rather than user productivity or ASIC flows. Finally, LA designs can still need serializer or balancing logic, so the gain is from removing unnecessary runtime coordination, not from making control logic disappear.

## Related Work

- _Nigam et al. (PLDI '23)_ — Filament provides timeline types for fixed-latency designs, and Lilac extends that foundation to parameterized timing and generator-produced output latencies.
- _Yu et al. (arXiv '25)_ — Anvil generalizes timing-safe HDLs toward dynamic, event-parameterized contracts, whereas Lilac focuses on compile-time-abstract but elaboration-concrete timing.
- _De Dinechin and Pasca (IEEE Design & Test '11)_ — FloPoCo exemplifies the generator ecosystem Lilac is designed to integrate efficiently rather than replace.

## My Notes

<!-- empty; left for the human reader -->

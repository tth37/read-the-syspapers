---
title: "Rage Against the State Machine: Type-Stated Hardware Peripherals for Increased Driver Correctness"
oneline: "Abacus turns hardware device protocols into Rust typestates that stay sound under hardware-driven transitions, catching driver protocol bugs at compile time."
authors:
  - "Tyler Potyondy"
  - "Anthony Tarbinian"
  - "Leon Schuermann"
  - "Eric Mugnier"
  - "Adin Ackerman"
  - "Amit Levy"
  - "Pat Pannuto"
affiliations:
  - "UC San Diego, La Jolla, California, USA"
  - "Princeton University, Princeton, New Jersey, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790207"
tags:
  - kernel
  - hardware
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Abacus observes that conventional typestates fail for drivers not because hardware lacks protocol structure, but because hardware can move the state machine without software's permission. It classifies hardware states into stable and transient states, restricts operations in transient states to those valid across all hardware-reachable successors, and asks drivers to explicitly re-synchronize when they need precision again. The result is a Rust DSL and code-generation framework that catches real device-protocol bugs while adding essentially no code-size cost and little runtime overhead.

## Problem

The paper targets device protocol violations: cases where a driver issues MMIO operations that are legal at the raw interface level but illegal under the device's actual protocol. This is a large practical problem. The authors cite prior work showing that such violations account for 38% of patched bugs in Linux USB/1394/PCI drivers, and they find 21 patched examples in the Tock and Redox Rust OSes as well. Rust helps with memory safety, but it does not by itself prevent a driver from writing the wrong register in the wrong device state.

Why is this hard? Hardware exports a permissive interface, typically a struct of read/write registers, while the real protocol lives in prose datasheets and changes with device state. A UART transmit register, for example, may be writable only when the hardware FIFO is not full; an Ethernet filter register may be writable only when reception is disabled; a radio shortcut may be safe only in a narrow transient phase. These are exactly the invariants drivers routinely get wrong, especially once interrupts, DMA engines, or autonomous hardware transitions enter the picture.

The obvious candidate is type-state programming: encode each device state as a type, expose only valid methods, and let the compiler reject invalid transitions. But standard typestates assume software owns the state machine. Drivers do not. Hardware can independently drain a queue, finish a reset, disconnect a port, or move between radio phases. Once that happens, the software's static type no longer matches reality, and traditional typestate guarantees collapse.

## Key Insight

The paper's core insight is that drivers do not need full ownership of a hardware state machine to recover useful static guarantees. They only need a disciplined way to reason about which states hardware may have moved into behind their backs.

Abacus introduces two classes of states. A stable state can only be exited by software. A transient state has at least one hardware-initiated outgoing edge. In stable states, ordinary typestate reasoning remains sound. In transient states, Abacus accepts that the software view may diverge from the true hardware state, but preserves correctness by allowing only operations that are valid in the intersection of all hardware-reachable states. When the driver needs finer knowledge again, it must re-synchronize by polling a status register, handling an interrupt, or issuing a reset-like operation that forces hardware into a known state.

That move is the paper's real contribution. It turns "hardware concurrency breaks typestate" into "hardware concurrency narrows the admissible API until synchronization restores precision." The authors frame this as a rely-guarantee style refinement of typestate, but the practical takeaway is simpler: compile-time driver correctness is still possible if transient uncertainty is made explicit and conservative.

## Design

Abacus is implemented as a Rust framework plus a DSL embedded in procedural-macro annotations on register definitions. A developer starts from the device's state machine and labels each state as stable or transient. They then annotate each register or bitfield with either a standard access constraint or a state-changing constraint `SC(from, to)`, which simultaneously says when an operation is legal and what state transition it causes.

From those annotations, Abacus generates a hardware object generic over state, wrapper types that expose MMIO methods only in valid states, an enum over the current possible states, and compiler-checked obligations for synchronization. For transient states, the developer must implement a `SyncState` trait that inspects hardware and returns the refined state. This code is trusted, but the framework makes missing synchronizers a compile error.

The UART example captures the mechanics well. Writing the data register in `QueueReady` transitions the peripheral into a maybe-full state. Configuration accesses are allowed only in `QueueReady<Idle>`. Reset is allowed from any state and forces the device back to `QueueReady<Idle>`. If the driver is in a transient state such as `QueueMaybeFull`, Abacus simply does not generate a `data.write()` method there, because hardware may already have moved to any reachable successor and only the intersection-safe operations remain valid.

To fit common Rust driver structure, Abacus also provides `AbacusCell`, an interior-mutable cell that lets `&self` driver methods move type-stated register objects through closures without abandoning Rust ownership discipline. The framework is not a verifier in the full theorem-proving sense; it is a restricted compilation strategy that turns protocol invariants into type errors.

## Evaluation

The evaluation asks three practical questions: can Abacus be integrated into real drivers, what bugs does it catch, and what does it cost?

On usability, the authors port five Tock drivers and one Redox xHCI driver. The annotation burden ranges from 4 to 45 DSL lines per driver, while the driver refactors range from dozens to hundreds of lines depending on state-machine complexity. The nRF52 15.4 radio is the largest case, with 8 states, 33 annotation lines, and a sizeable driver rewrite. This is real effort, but it is still in the "systems engineering" regime rather than the "months of proof labor" regime.

On bug finding, Abacus surfaces an attempted write to a disabled peripheral in the nRF52840 UARTE driver and a missing state check in the Redox xHCI PortSC path, where the driver reads PLS bits while hardware may still be in a Resetting state that makes those bits undefined. The paper also explains how earlier Redox Ethernet and Tock UART bugs would become compile-time errors once the relevant protocol constraints are encoded.

On overhead, the results are strong. Across the five Tock integrations, the kernel image grows by at most 8 bytes, effectively zero at roughly 100-200 KB total kernel sizes. The Redox xHCI driver is actually 7.5 KB smaller, a 0.33% reduction, because Abacus removes redundant runtime checks. Runtime microbenchmarks show near-parity or small wins in several cases, with the worst measured penalty only 40 cycles for an STM32 USART receive path. Macrobenchmarks show at most a 1.2% end-to-end slowdown in the temperature driver, while the Nordic UART improves by eliminating redundant checks. The standout case study is the nRF52 15.4 radio: after integrating Abacus, the authors enabled the full set of hardware shortcuts in under two hours, cutting interrupts by 50% and transmit runtime overhead by 8%.

These results support the paper's central claim well. Abacus is not free in developer effort, but the compiled artifact cost is negligible, and the evaluation shows that stronger protocol enforcement can sometimes unlock optimizations that cautious hand-written drivers avoid.

## Novelty & Impact

Relative to classic driver DSLs such as _Mérillon et al. (OSDI '00)_, Abacus's novelty is not merely describing protocols in a higher-level language, but doing so with explicit state sensitivity and hardware-driven transitions. Relative to hardware/software co-verification work such as _Ryzhyk et al. (ASPLOS '11)_, it gives up full proof strength in exchange for something lightweight enough to retrofit into existing Rust drivers. Relative to typestate work such as _LeBlanc et al. (OSDI '24)_, its key step is handling concurrent hardware custody rather than only software-controlled or synchronous devices.

That makes the paper important for OS, embedded, and safe-systems engineers who want more than memory safety but cannot afford full formal verification. The likely long-term influence is not a new driver architecture, but a reusable pattern for pushing protocol rules from PDFs into the type checker.

## Limitations

Abacus depends on the developer's protocol model being correct. If the DSL annotations mistranslate the datasheet, the framework can faithfully enforce the wrong rule. The trusted `SyncState` hooks are another escape hatch: they are necessary, but not formally checked. The approach also works only when the protocol is expressible as a manageable state machine and when hardware offers some way to re-synchronize, such as status bits, interrupts, or reset transitions. Timing-only rules without observable hardware state are out of scope.

The evaluation is also narrower than the broad framing might suggest. The paper studies a modest set of Rust drivers, not Linux-scale ecosystems, and the strongest performance win comes from a particular radio-shortcut case where better protocol tracking enables extra hardware features. That is encouraging, but it does not mean every driver integration will pay back the annotation effort equally.

## Related Work

- _Ryzhyk et al. (EuroSys '09)_ — Dingo characterizes device-protocol bugs and motivates the problem; Abacus responds with a static enforcement mechanism inside the driver language rather than a bug taxonomy.
- _Mérillon et al. (OSDI '00)_ — DEVIL uses a DSL to describe devices, but Abacus adds explicit reasoning about hardware state and compile-time restriction of operations across transient uncertainty.
- _Ryzhyk et al. (ASPLOS '11)_ — hardware-verification reuse pursues stronger hardware/software correctness, whereas Abacus is a lighter-weight, retrofit-friendly mechanism for everyday drivers.
- _LeBlanc et al. (OSDI '24)_ — SquirrelFS shows how Rust typestates can enforce filesystem invariants; Abacus extends that style to peripherals whose state can change concurrently outside software control.

## My Notes

<!-- empty; left for the human reader -->

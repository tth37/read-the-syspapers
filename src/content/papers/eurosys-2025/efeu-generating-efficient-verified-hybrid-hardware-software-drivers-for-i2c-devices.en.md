---
title: "Efeu: generating efficient, verified, hybrid hardware/software drivers for I2C devices"
oneline: "Efeu specifies an entire I2C subsystem once, model-checks interoperability including quirks, and generates C, Verilog, and hybrid drivers that approach hand-tuned hardware performance."
authors:
  - "Daniel Schwyn"
  - "Zikai Liu"
  - "Timothy Roscoe"
affiliations:
  - "ETH Zurich"
conference: eurosys-2025
category: reliability-and-formal-methods
doi_url: "https://doi.org/10.1145/3689031.3696093"
project_url: "https://gitlab.inf.ethz.ch/project-opensockeye/efeu"
tags:
  - formal-methods
  - hardware
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Efeu lets developers specify an entire I2C subsystem once, model-check interoperability including known quirks, and then generate C, Verilog, or hybrid drivers with the split point chosen at compile time. On a Zynq MPSoC, the generated `Transaction` and `EepDriver` designs reach 392-396 kHz on a 400 kHz bus while using 8% and 4% CPU in interrupt mode.

## Problem

I2C lacks the isolation that makes PCIe or USB drivers fail locally. Controller and responders share two wires, so one buggy device, workaround, or controller quirk can wedge the whole bus. That matters because I2C often controls power, sensors, clocks, and BMC functions where failures mean lockups, wasted energy, or hardware damage.

Prior driver-assurance work usually verifies one driver against one device, or synthesizes code for a standard interface. The paper argues that this misses the real systems problem: interoperability across a whole bus of off-the-shelf components, including devices and controllers that deviate from the standard. The Raspberry Pi clock-stretching bug makes the point: software can be correct, yet the subsystem still fails because the controller hardware itself violates I2C.

## Key Insight

The key claim is that I2C should be specified as one layered subsystem shared by verification and implementation. Once controllers, responders, and topology are written in that form, the same source can generate a Promela model, software drivers, hardware blocks, or mixtures of both.

This is possible because layer communication is symmetric rather than fixed to a software call direction. Efeu can therefore choose the hardware/software boundary later, while verification keeps state explosion manageable by replacing lower layers with behavior models.

## Design

Efeu models the stack as `Electrical`, `Symbol`, `Byte`, `Transaction`, and a device-specific top layer such as `EepDriver`. Interfaces are written in ESI, a small DSL for bidirectional typed channels. Implementations are written in ESM, a restricted C-like FSM language with `talk` and `read` for blocking exchanges between adjacent layers.

ESMC has three backends. The Promela backend preserves structure for SPIN. The C backend compiles layers to stack-based coroutines and uses a compile-time call graph to decide which layer becomes the external entry point. The Verilog backend lowers layers to ready/valid state machines. If the split crosses hardware and software, Efeu inserts an AXI Lite MMIO boundary and turns `valid` and `ready` into one-shot signals so software timing cannot accidentally duplicate or drop packets.

Verification is also layered. For each layer above `Electrical`, the authors write a behavior spec and input space, then check assertions plus deadlock/livelock freedom. Quirks stay local: the KS0127 decoder quirk needs 13 extra ESM lines in responder `Byte`, controller compatibility adds 10 more, and modeling Raspberry Pi's missing clock-stretch support is a 3-line `Symbol` change.

## Evaluation

Abstraction pays off immediately. `EepDriver` verification drops from 584.78 seconds to 9.15 seconds when lower layers are replaced with behavior models; `Transaction` drops from 104.53 to 6.11 seconds, and `Byte` from 11.33 to 4.01 seconds. The paper also verifies multiple EEPROM topologies, but runtime still grows quickly with payload length and device count.

On a Zynq UltraScale+ MPSoC with a real 24AA512 EEPROM, the software-only `Electrical` design reaches 154.44 kHz, close to Linux bit-banging at 162.81 kHz. Moving `Symbol` into hardware reaches 263.32 kHz; moving `Byte` reaches 359.98 kHz with polling or 342.9 kHz with interrupts. With `Transaction` in hardware, the generated drivers reach 392.48 and 392.24 kHz, slightly above the Xilinx I2C IP baseline at 386.57 kHz. A fully hardware `EepDriver` reaches 396.02 kHz. CPU usage falls with the same shift: all polling designs consume a full core, while interrupt-driven `Symbol`, `Byte`, `Transaction`, and `EepDriver` use 64%, 36%, 8%, and 4%, versus 12% for Xilinx. The `Transaction` design costs 2.08x the LUTs and 2.11x the FFs of the handcrafted IP, but only 0.70% of LUTs and 0.34% of FFs on the target FPGA.

## Novelty & Impact

The novelty is not just generating an I2C controller. Efeu makes bus-wide interoperability, quirk modeling, verification, and hardware/software partitioning part of the same artifact. Earlier verified-driver work usually assumes one device at a time; earlier synthesis work usually assumes standard behavior. Efeu is interesting because it targets the shared-bus failure mode that actually breaks BMCs and embedded platforms.

## Limitations

The verification is bounded: `Transaction` and `EepDriver` only explore small payloads with fixed contents, and larger multi-device systems still hit state explosion. The assurance story also trusts the compiler, generated C/Verilog, EDA flow, and the handwritten bus-timing adapter. Performance is measured on one MPSoC with one EEPROM class, and the paper reports only reads because EEPROM writes are dominated by device busy time. One design point also fails outright: interrupt-driven `Electrical` generates too many interrupts to work.

## Related Work

- _Humbel et al. (SPIN '21)_ - The authors' earlier model-checked I2C stack established the layered idea; Efeu extends it to realistic multi-device topologies and code generation.
- _Ryzhyk et al. (SOSP '09)_ - Termite synthesizes drivers for individual devices, whereas Efeu targets a whole shared-bus subsystem.
- _Ortega and Borriello (ICCAD '98)_ - Communication co-synthesis generates hardware/software interfaces, but Efeu adds quirk modeling and formal interoperability checks.
- _Pohjola et al. (PLOS '23)_ - Pancake lowers the cost of writing verifiable drivers; Efeu's distinct contribution is reasoning about multiple devices on one bus.

## My Notes

<!-- empty; left for the human reader -->

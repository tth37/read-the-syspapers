---
title: "Architecting Scalable Trapped Ion Quantum Computers using Surface Codes"
oneline: "Uses a QCCD compiler and error model to show that trapped-ion surface-code systems favor 2-ion traps and grid links, with wiring constrained by a power-speed tradeoff."
authors:
  - "Scott Jones"
  - "Prakash Murali"
affiliations:
  - "Department of Computer Science and Technology, University of Cambridge, Cambridge, United Kingdom"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790128"
tags:
  - hardware
  - compilers
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

This paper asks what a scalable trapped-ion QCCD machine should actually look like once the workload is no longer NISQ circuits, but repeated surface-code error correction. Its answer is unexpectedly simple: use very small traps, specifically capacity-two traps, preserve the code's 2D locality with grid connectivity, and compile aggressively enough that the design-space comparison is meaningful. The same study also shows that today's promising low-power wiring schemes solve one bottleneck only by creating another, much slower logical clock.

## Problem

The motivating gap is large. Current trapped-ion systems are still below roughly sixty physical qubits, while practical fault-tolerant applications need on the order of `100-1000` algorithmic qubits at logical error rates around `10^-9`. Getting there requires quantum error correction, and the paper focuses on surface codes because their planar locality fits a modular trapped-ion architecture better than many alternatives. The hardware target is QCCD: many small traps connected by transport segments and junctions, with ions shuttled around so required two-qubit interactions can happen inside a trap.

What is missing in prior work is not the idea of QCCD itself, but guidance on which QCCD design point actually makes sense for logical qubits. Trap capacity, inter-trap topology, and electrode-to-DAC wiring all interact. Large traps reduce communication, but serialize more gates and can worsen fidelity. Small traps expose more parallelism, but they maximize movement. Rich communication topologies seem attractive, but may not matter if the code already has regular local structure. Existing compilers and architecture studies mostly target NISQ circuits, manual mappings, or a narrow set of hardware choices, so they do not tell a device architect how to build a surface-code-oriented machine.

## Key Insight

The paper's main claim is that for surface-code workloads, minimizing communication is the wrong first principle. Because parity-check circuits are regular and local, the more important objective is to preserve parallelism while routing only the structured movements that the code truly needs. Once the compiler respects both the code topology and the hardware topology, a capacity-two design that looks communication-heavy on paper turns out to be best in practice.

That conclusion only emerges because the authors tie compilation, noise, and hardware cost together in one loop. They do not just count swaps or trap crossings. They compile full syndrome-extraction rounds, simulate logical error with a trapped-ion-aware noise model, and estimate control-system cost from electrode counts and wiring style. The result is a systems argument rather than an isolated compiler claim: small traps win not only on cycle time, but also on logical error and even on hardware efficiency once the full code distance needed for a target logical error rate is included.

## Design

The toolflow starts by translating surface-code parity-check circuits into native QCCD instructions: single-qubit rotations, Mølmer-Sørenson gates, measurement, reset, and explicit movement primitives such as split, merge, shuttling, and junction crossing. The compiler then maps logical qubits to physical ions in two stages. First, it partitions the surface-code interaction graph into balanced clusters of size `capacity - 1`, intentionally leaving one empty slot per trap so incoming ions can be accommodated during communication. For surface codes, the partitioner exploits the grid structure directly instead of solving a general NP-hard mapping problem from scratch. Second, it places those clusters onto physical traps with a geometry-aware matching step that tries to keep neighboring code regions on neighboring traps.

Routing is built around QCCD constraints rather than abstract swap edges. At any moment, traps have finite capacity, segments and junctions may hold only one ion, and ancilla ions must be moved so that required entangling gates occur inside a common trap. The compiler models the device as a directed graph, allocates shortest paths for ancilla motion in passes, removes saturated components during a pass, and then emits movement operations plus the gates that became enabled. A list scheduler finally assigns time using primitive durations and a precedence graph, prioritizing ready operations by weighted critical path.

The authors then attach a physical model to the compiled schedule. Runtime comes from operation latencies. Logical error comes from a Stim-based noise simulation that includes dephasing during idle or movement, depolarizing gate noise, reset and measurement error, and the effect of ion heating on later gate fidelity. A separate resource model converts trap count, junction count, and electrode counts into controller-to-QPU bandwidth and power, letting the paper compare standard direct wiring against WISE-style multiplexed control.

## Evaluation

The evaluation covers rotated surface codes with code distances from `2` to `20`, sweeping trap capacities from `2` to `30`, three interconnect topologies, two wiring styles, and physical-gate-improvement scenarios from `1x` to `10x`. Before using that framework for design exploration, the paper validates the compiler. Against hand-optimized small cases, compiled schedules are within `1.09x` of the theoretical minimum elapsed time on average, and routing is within `1.04x` of the theoretical minimum number of movement operations. Against prior trapped-ion compilers, the new compiler reduces movement time by `3.85x` on average and movement operations by `1.91x`, which is important because the architecture conclusions only matter if the compilation layer is not the bottleneck.

The most important result is the trap-capacity study. Capacity-two traps achieve the lowest QEC round times and, unlike higher capacities, keep cycle time roughly constant as code distance grows. The reason is that extra intra-trap communication savings never compensate for the loss of parallelism once more qubits are packed into one trap. On logical error, the paper reports one to two orders of magnitude improvement for capacity-two designs over larger capacities across the examined gate-quality scenarios. Under a `10x` physical-gate improvement, the authors project that a distance-`13` code with trap capacity two can reach the target `10^-9` logical error rate.

The connectivity results are also crisp. A linear topology is much worse because routing congestion dominates; for example, the paper reports that at `d=5, capacity=2`, the linear design needs more than about `275 ms` per logical-identity operation, roughly `12x` slower than grid or all-to-all-switch topologies. By contrast, grid and switch look nearly identical in both elapsed time and logical error, which means the simpler grid topology already captures almost all of the useful locality of surface codes.

Finally, the wiring study exposes a second bottleneck. With standard direct wiring, the best design point still needs about `1.3 Tbit/s` of controller bandwidth and roughly `780 W` per logical qubit to hit `10^-9`, which is clearly impractical at scale. WISE reduces data rate and power by more than two orders of magnitude, but because it restricts which movement primitives can occur simultaneously, near-`10^-9` operating points can become up to `25x` slower. That supports the paper's broader claim: trapped-ion scalability is not just a qubit-count problem, but a cross-layer architecture problem in which control electronics can dominate.

## Novelty & Impact

Relative to _Murali et al. (arXiv '20)_, this paper changes both the workload and the answer: instead of NISQ applications preferring traps with roughly `15-25` ions, surface-code logical qubits favor the smallest plausible trap. Relative to _Malinowski et al. (PRX Quantum '23)_, it does not invent a new wiring technique, but integrates WISE into a full logical-qubit study and shows exactly where the power savings turn into runtime pain. Relative to _Leblond et al. (SC-W '23)_, it is less a fixed resource estimator for one canonical architecture and more a compiler-backed design-space exploration across trap sizes and topologies.

That makes the paper useful to both trapped-ion architects and systems researchers working on quantum hardware-software co-design. Its biggest contribution is not a single routing trick, but a quantitative correction to community intuition about what "scalable trapped-ion design" should mean under fault tolerance.

## Limitations

The paper deliberately narrows the problem to one logical qubit running repeated surface-code checks, so it does not directly model networking many QCCD modules together or scheduling many interacting logical qubits at once. The authors argue that lattice-surgery-style interactions should preserve much of the same structure, but that is still an extrapolation rather than an evaluated result. The noise model is grounded in prior trapped-ion studies, yet the headline feasibility points also depend on assumed `5x` and `10x` gate improvements, so the exact distance needed for `10^-9` is somewhat roadmap-sensitive.

There are also architectural assumptions that may age. The analysis assumes no practical parallel two-qubit gates within a trap, and that assumption is one reason capacity-two traps look so strong. If future devices make highly parallel intra-trap gates cheap, the tradeoff could shift. Likewise, WISE is evaluated with cooling support and a specific global reconfiguration style; another control architecture could land at a better point on the power-versus-cycle-time frontier.

## Related Work

- _Murali et al. (arXiv '20)_ — studies QCCD design choices for NISQ workloads, whereas this paper retargets the analysis to surface-code logical qubits and reaches the opposite trap-capacity recommendation.
- _Malinowski et al. (PRX Quantum '23)_ — proposes WISE as a scalable trapped-ion wiring architecture; this paper quantifies its logical-clock penalty when used for surface-code QEC.
- _Leblond et al. (SC-W '23)_ — TISCC compiles surface-code workloads for a fixed trapped-ion design, while this paper searches the wider architecture space and models explicit primitive routing.
- _Wu et al. (ISCA '22)_ — explores how to map surface-code structures onto superconducting devices, whereas this work makes trapped-ion transport, topology, and control wiring first-class constraints.

## My Notes

<!-- empty; left for the human reader -->

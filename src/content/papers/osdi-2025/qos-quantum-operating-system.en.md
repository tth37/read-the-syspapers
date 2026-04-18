---
title: "QOS: Quantum Operating System"
oneline: "QOS turns noisy heterogeneous QPUs into a schedulable cloud resource by composing error mitigation, fidelity estimation, compatibility-aware multiprogramming, and latency-aware scheduling."
authors:
  - "Emmanouil Giortamis"
  - "Francisco Romão"
  - "Nathaniel Tornow"
  - "Pramod Bhatotia"
affiliations:
  - "Technical University of Munich"
conference: osdi-2025
code_url: "https://github.com/TUM-DSE/QOS"
tags:
  - quantum
  - scheduling
  - hardware
  - datacenter
category: quantum-computing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

QOS turns a quantum circuit into a shared `Qernel` abstraction and uses it to coordinate error mitigation, fidelity estimation, compatibility-aware multi-programming, and scheduling. On IBM QPUs, that lets the system trade small fidelity losses for much lower queueing delay and better resource efficiency, rather than optimizing each layer in isolation.

## Problem

Current cloud QPUs are small, noisy, and heterogeneous across both machines and calibration cycles. Larger circuits and denser packing improve utilization but usually reduce fidelity, while sending every job to the best-fidelity backend creates queue hotspots. In today's cloud interfaces, users still make many of those tradeoffs manually.

Existing work tackles pieces of the problem in isolation, such as circuit cutting, qubit freezing, simple multi-programming, or heuristic scheduling. The paper argues that this is the wrong decomposition. Mitigation changes which QPUs are viable, which changes safe co-location and queueing behavior. Without a coordinating system, operators choose among fidelity, utilization, and waiting time with disconnected heuristics.

## Key Insight

The paper's key claim is that the right unit of management is not a raw circuit but a richer execution object. QOS calls that object a `Qernel`: it stores static properties such as width, depth, gate mix, and SupermarQ features, plus dynamic state such as fidelity estimates, scheduling status, and post-processed results. Once every layer reads and writes the same object, fidelity-oriented and utilization-oriented policies become composable.

This works because the same facts drive every tradeoff. If mitigation shrinks width or removes noisy interactions, more QPUs become feasible and co-location decisions change; if estimation says a slightly worse QPU is still acceptable, the scheduler can reduce queueing sharply. QOS therefore reframes quantum cloud management as one joint optimization problem over circuit structure, calibration data, and queue state.

## Design

QOS exposes hardware-agnostic APIs such as `run`, `results`, and `backends`, then lowers user circuits into Qernels. The error mitigator analyzes hotspot qubits and applies a budgeted pipeline: qubit freezing first, then circuit cutting, then qubit reuse if the circuit still does not fit available QPUs. A paired post-processor reconstructs fragmented outputs after execution.

The estimator predicts fidelity without running the job by combining target-specific transpilation with calibration data. The multi-programmer then decides whether low-utilization Qernels should share a QPU, using effective utilization, compatibility score, and one- or two-qubit buffer zones to limit crosstalk; if mappings overlap, it re-transpiles and re-estimates before accepting the bundle. Finally, the scheduler estimates runtime from the Qernel's longest gate path and uses either a formula-based policy or NSGA-II to balance fidelity, waiting time, and utilization.

## Evaluation

The evaluation uses real IBM Falcon r5.11 devices, mostly the 27-qubit Kolkata QPU, with more than 7,000 real quantum runs and more than 70,000 benchmark instances from nine benchmark families. The motivation measurements justify the system goal: average fidelity falls by 98.9% when moving from 4 to 24 qubits, nominally identical QPUs differ by 38% on one GHZ workload, and queue lengths differ by as much as 57x across same-size QPUs.

The error mitigator is the strongest single-layer result. Relative to Qiskit, CutQC, and FrozenQubits, it improves fidelity by 2.6x, 1.6x, and 1.11x on 12-qubit circuits, and by 456.5x, 7.6x, and 1.67x on 24-qubit circuits. The paper also reports the cost: 16.6x classical overhead and 31.3x quantum overhead at 12 qubits, dropping to 2.5x and 12x at 24 qubits. Higher in the stack, the estimator usually beats the naive "always use Auckland" choice; the multi-programmer improves fidelity by 1.15x to 9.6x at matched utilization while losing about 9.6% on average relative to running each circuit alone; and the scheduler, with fidelity weight `c = 0.7`, cuts waiting time by about 5x for about 2% lower fidelity while keeping QPU load within 15.2%. That supports the central claim, though the scheduler comparison is mostly internal because prior work could not be reproduced faithfully.

## Novelty & Impact

Relative to _Ayanzadeh et al. (ASPLOS '23)_ and _Tang et al. (ASPLOS '21)_, QOS is not just another mitigation heuristic; it composes qubit freezing, circuit cutting, and qubit reuse under one runtime abstraction. Relative to _Das et al. (MICRO '19)_, it adds compatibility-aware co-location, buffer zones, and effective utilization. Relative to _Ravi et al. (QCE '21)_, it makes scheduling one layer of a stack that already knows mitigation outcomes and fidelity predictions. That architectural lesson should matter to future quantum cloud runtimes and, potentially, fault-tolerant resource managers.

## Limitations

The evidence is still bounded by today's hardware and by the paper's evaluation method. Most experiments target IBM Falcon-class 27-qubit systems, so portability across providers and architectures is argued more than demonstrated. Error mitigation can be expensive on small circuits, several thresholds and weights are hand-tuned, and the scheduler study is trace-driven rather than a live deployment. The paper also argues that the same ideas should extend to fault-tolerant quantum computing, but it does not demonstrate that regime.

## Related Work

- _Ayanzadeh et al. (ASPLOS '23)_ - FrozenQubits improves QAOA fidelity by freezing hotspot nodes, while QOS uses qubit freezing as one stage in a broader budgeted mitigation pipeline.
- _Tang et al. (ASPLOS '21)_ - CutQC uses circuit cutting to run larger circuits on smaller hardware, whereas QOS treats cutting as one composable mechanism inside an OS stack.
- _Das et al. (MICRO '19)_ - A Case for Multi-Programming Quantum Computers studies co-locating quantum jobs, while QOS adds compatibility scoring, buffer zones, and effective utilization.
- _Ravi et al. (QCE '21)_ - Adaptive Job and Resource Management for the Growing Quantum Cloud focuses on quantum job scheduling, while QOS integrates scheduling with mitigation and fidelity estimation.

## My Notes

<!-- empty; left for the human reader -->

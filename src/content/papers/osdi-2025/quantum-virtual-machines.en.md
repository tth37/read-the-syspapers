---
title: "Quantum Virtual Machines"
oneline: "HyperQ exposes architecture-specific quantum VMs, then binpacks them across qubits and time so cloud hardware can run multiple isolated quantum programs concurrently."
authors:
  - "Runzhou Tao"
  - "Hongzheng Zhu"
  - "Jason Nieh"
  - "Jianan Yao"
  - "Ronghui Gu"
affiliations:
  - "University of Maryland, College Park"
  - "Columbia University"
  - "University of Toronto"
conference: osdi-2025
code_url: "https://github.com/1640675651/HyperQ"
tags:
  - quantum
  - virtualization
  - scheduling
category: quantum-computing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

HyperQ turns a quantum processor into a set of quantum virtual machines, or qVMs, whose topology matches repeated regions of the underlying chip. Programs compile against those qVMs independently, and HyperQ later packs multiple qVMs into one composite circuit using space and time multiplexing. On IBM's 127-qubit Eagle hardware, this improves throughput, utilization, and user-visible latency substantially while preserving, and sometimes improving, fidelity.

## Problem

Current quantum cloud services treat a whole machine as the scheduling unit. A user submits one circuit, that circuit monopolizes the quantum processor until it finishes, and then the next job runs. This is wasteful because most NISQ workloads use only a small subset of available qubits, yet they still block all other tenants. The paper argues that this underutilization is especially painful because public fleets are small, demand is high, and users can wait days for results.

The obvious fix, running multiple circuits together, is not straightforward. Existing quantum multiprogramming work mostly merges circuits at compile time using custom compilers, so the system must know exactly which programs will co-run before compilation. That breaks independent compilation, scales poorly, and gives up the mature optimizations already implemented in standard toolchains such as Qiskit. At the same time, quantum hardware lacks QRAM and therefore lacks the save/restore mechanisms that classical systems use for preemptive context switching. HyperQ therefore has to multiplex work without assuming either a new compiler stack or hardware support for quantum context switches.

## Key Insight

The paper's key claim is that quantum virtualization should be defined around the repeated physical structure that real chips already expose. IBM Eagle, for example, is built from repeating 7-qubit I-shaped regions. If HyperQ defines a qVM to be one such region, or a fixed rectangular composition of those regions, then a circuit compiled for the qVM can later be relocated to any matching place on the real chip by simple qubit relabeling instead of recompilation.

That physical decomposition also gives HyperQ a practical isolation boundary. By ensuring that qubits belonging to different qVMs are not directly connected, HyperQ reduces crosstalk between concurrently executing programs. The result is a virtualization abstraction that satisfies the classical goals of efficiency, resource control, and equivalence closely enough for today's quantum cloud setting: compiled instructions still execute directly on hardware, HyperQ retains placement control, and users can keep writing ordinary programs against existing compiler frameworks.

## Design

HyperQ exposes each qVM as a virtual backend with the same kind of coupling map and gate set that a real backend provides. For IBM hardware, the basic qVM is a 7-qubit I-shaped region, identical to the topology of the smaller Falcon machine. HyperQ also defines scaled qVMs, built as m x n arrays of the basic region plus connector qubits, and fractional qVMs for very small programs. During compilation, HyperQ inspects how many qubits a program needs, chooses the smallest qVM shape that fits, and lets Qiskit compile against the corresponding virtual backend. This preserves standard routing and gate-decomposition passes instead of replacing them with a custom multiprogramming compiler.

Scheduling is split into a space pass and a time pass. The space scheduler is a greedy FIFO binpacker over the chip's grid of regions: it scans jobs in arrival order and places each one at the top-left-most compatible unoccupied location. A noise-aware variant ranks basic regions using the hardware's daily calibration data, avoids the worst regions when possible, and can steer noise-resilient jobs onto lower-quality regions. The time scheduler then fills slack left by uneven circuit lengths. It estimates runtime from gate delays on the critical path, plus the cost of mid-circuit measurement and reset, and appends later qVMs onto regions whose total length will not exceed the longest region selected by space scheduling.

Once a batch is chosen, HyperQ aggregates it into one executable circuit. It translates each virtual qubit to its assigned physical qubit, adjusts undirected qVM edges to the directed gate orientation of the target region, inserts resets and barriers when a region is reused in time, concatenates all subcircuits, and submits the result to the cloud service as an ordinary job. After execution, it demultiplexes the returned classical bits back to per-qVM results. HyperQ also isolates unusual circuits with many mid-circuit measurements or resets by pulling them into separate circuits so they cannot perturb co-scheduled jobs.

## Evaluation

The implementation targets the IBM Quantum Platform and Qiskit, and the experiments run on IBM Brisbane, a public 127-qubit Eagle machine. The workload comes from QASMBench: a `small-only` benchmark with 145 jobs and a `small&med` benchmark with 196 jobs. Every job is executed with 4000 shots, and the paper evaluates four configurations: baseline IBM Quantum, HyperQ with space scheduling, HyperQ with space plus time scheduling, and HyperQ with noise-aware placement.

The main performance result is that multiplexing works at meaningful scale. With all jobs arriving at once, HyperQ with space-plus-time scheduling improves throughput by 9.7x on `small-only` and 4.9x on `small&med`, while utilization rises by 11x and 5.8x respectively. Under a Poisson arrival process, the gains are smaller but still substantial: around 3.2x-3.6x better throughput and utilization depending on the benchmark. User-visible latency also drops sharply in the paper's empty-queue model. Average latency falls by 43x for `small-only` and 26x for `small&med` under Poisson arrivals, because most of the delay in today's service comes from waiting for earlier whole-machine jobs to drain.

The fidelity story is just as important. Using L1 distance to an ideal simulator on the small benchmark, HyperQ's space-only scheduling matches IBM Quantum almost exactly on average, and its noise-aware mode improves the average L1 score from 0.55 to 0.50 under Poisson arrivals, where lower is better. Time multiplexing is somewhat noisier because today's mid-circuit measurement and reset operations are still expensive, but even then the reported averages remain well below the paper's rough "more than half-correct" threshold of L1 = 1. The paper also includes a focused crosstalk experiment showing that leaving one unused qubit between concurrent programs restores success rate from 81% back to 85%, the same as running alone.

## Novelty & Impact

Relative to prior quantum multiprogramming papers such as _Das et al. (MICRO '19)_ and _Liu and Dou (HPCA '21)_, HyperQ changes the abstraction boundary. Those systems mainly treat multiprogramming as a compile-time circuit-composition or mapping problem. HyperQ instead introduces an architecture-specific qVM abstraction, preserves independent compilation, and pushes composition to runtime scheduling. That is a systems contribution rather than just a better mapper.

The likely impact is on quantum cloud runtime design. If public quantum services continue to expose scarce, noisy devices to many users, then scheduling, isolation, and elastic right-sizing will matter as much as compiler quality. HyperQ shows that even with today's hardware limitations, a VM-like layer can make cloud quantum computing look less like a single-user batch queue and more like a multiplexed service.

## Limitations

HyperQ depends on structural regularity in the hardware. Its qVM construction assumes the machine has a repeated region pattern plus predictable connectors, which is true for the evaluated superconducting devices but may not hold for all future architectures. The paper also assumes static circuit structure when estimating execution time; dynamic circuits with richer control flow could make the time scheduler less accurate.

There are practical costs as well. Because current machines still lack QRAM, HyperQ cannot preempt and resume arbitrary quantum state; it can only multiplex by composing full circuits ahead of execution. Time scheduling relies on mid-circuit measurement and reset, and the evaluation shows those operations still inject noticeable noise. Finally, utilization is capped by external fragmentation: on Eagle, even when all nine basic qVM regions are occupied, only 85 of 127 qubits are usable under HyperQ's isolation layout. The evaluation is also limited to IBM Brisbane and QASMBench-style workloads, so broader evidence across hardware families is still missing.

## Related Work

- _Das et al. (MICRO '19)_ - Introduces compile-time multiprogramming for quantum computers, whereas HyperQ keeps compilation independent and composes jobs at runtime through qVM scheduling.
- _Liu and Dou (HPCA '21)_ - QuCloud focuses on cloud-side qubit mapping for multiprogrammed execution, while HyperQ adds a full virtualization interface plus time multiplexing and result demultiplexing.
- _Niu and Todri-Sanial (DATE '22)_ - Studies whether parallel circuit execution can help NISQ systems, but HyperQ turns that idea into a cloud-compatible runtime system rather than a scheduling argument alone.
- _Murali et al. (ASPLOS '20)_ - Uses noise-adaptive mapping to place one circuit on better qubits; HyperQ generalizes the same intuition to region-level placement for many concurrent qVMs.

## My Notes

<!-- empty; left for the human reader -->

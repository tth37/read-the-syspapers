---
title: "Fast End-to-End Performance Simulation of Accelerated Hardware–Software Stacks"
oneline: "NEX runs host software natively while DSim splits accelerator timing from functionality, cutting full-stack simulation to seconds with about 7% average error."
authors:
  - "Jiacheng Ma"
  - "Jonas Kaufmann"
  - "Emilien Guandalino"
  - "Rishabh Iyer"
  - "Thomas Bourgeat"
  - "George Candea"
affiliations:
  - "EPFL"
  - "MPI-SWS"
  - "UC Berkeley"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764825"
tags:
  - hardware
  - observability
  - ml-systems
category: gpu-and-accelerator-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

NEX+DSim speeds up full-stack accelerator simulation by running the host software stack natively and simulating only the unavailable, performance-critical parts. NEX synchronizes at accelerator boundaries and DSim separates timing from functionality, yielding `6x-879x` speedups over gem5+RTL with `7%` average and `14%` worst-case end-to-end timing error when CPU cores are not underprovisioned.

## Problem

Full-stack simulation is increasingly needed because software teams often develop against accelerators they do not yet have or co-design hardware and software before tapeout. But the dominant gem5+RTL style simulates CPUs, memory, interconnects, and accelerators all at fine granularity, so simulating one second of execution can take hours. That cost turns iteration on drivers, runtimes, and hardware parameters into a batch process. Faster substitutes such as analytical models or API interception usually lose exactly the interactions systems developers care about: OS behavior, DMA timing, and overlap between host execution and accelerator work.

## Key Insight

The paper's minimality principle is simple: simulate only components that are unavailable, and within those components simulate only the performance-critical aspects. If the target CPU exists and CPU microarchitectural visibility is unnecessary, the host should run natively and the simulator should intervene only at MMIO, shared-buffer, and DMA boundaries. Inside the accelerator, functionality and timing can likewise be split: one model determines what requests and results occur, another determines when they occur. Synchronizing only at externally visible events preserves the timing questions systems developers care about while discarding expensive internal detail.

## Design

NEX is the host-side orchestrator. Its Linux `sched-ext`/eBPF scheduler advances virtual time in fixed epochs and prevents any thread from entering epoch `i+1` until all threads and all synchronization events from epoch `i` are complete. The runtime protects MMIO regions or task buffers, traps accesses via `ptrace`, advances the relevant accelerator simulator to the current epoch, performs the read or write, and resumes the application. Lazy synchronization is the default; hybrid synchronization adds periodic catch-up for interrupts, and tick mode lets drivers batch multiple accesses behind one explicit trap.

DSim is the accelerator-side di-simulator. Its performance track is an LPN that models stages, pipelining, backpressure, resource contention, and DMA emission times. Its functionality track is a conventional functional simulator that computes correct outputs and records the DMA requests needed for the current task. DSim first runs the functional track using zero-cost DMA, queues requests by tag, and then lets the LPN emit timestamped DMA events; each emitted event is paired with the matching recorded request. At the host interface, DSim behaves like an RTL simulator but does far less internal work.

NEX also exposes `CompressT`, `SlipStream`, and `JumpT` so developers can do what-if acceleration studies or fast-forward uninteresting code.

## Evaluation

The evaluation uses three open-source accelerators with real software stacks: Apache VTA, Protoacc's serializer, and a JPEG decoder. The baseline is SimBricks with gem5 plus Verilator RTL; VTA is also compared against two FPGA testbeds. Against FPGA execution, NEX+DSim stays within `6%` average and `12%` worst-case error on single-VTA workloads. Against gem5+RTL across all accelerators, the error is `7%` on average and `14%` at worst.

The speedups are the headline result: `6x-879x` over gem5+RTL. The component breakdown is also useful: NEX alone gives `2x-157x` speedups by removing CPU timing simulation, DSim alone helps when accelerator simulation dominates, and the two together beat the best single component by up to `92x`. The interactive case studies show why that matters: a VTA ResNet-50 design that starts at `677 ms` can be explored down to `292 ms`, `162 ms`, and `146 ms` by varying interconnect latency, placement, and cache-level DMA service, with each run taking less than a minute.

## Novelty & Impact

Relative to SimBricks or gem5-RTL, the main contribution is a new speed/visibility point: native host execution coordinated by epochs, plus accelerator di-simulation that reunites timing and functionality only at externally visible events. Relative to _Ma et al. (OSDI '24)_, which introduced LPNs, this paper shows how LPNs become practically useful in full-stack work once they are paired with a functional track and a host-side synchronizer. The broader impact is methodological: full-stack accelerator simulation stops looking like a last-stage verification bottleneck and starts looking like a routine, interactive systems tool.

## Limitations

The paper is candid about what it leaves out. NEX does not model host-accelerator memory contention or I/O TLB translation cost for accelerator DMAs, because both would require more detailed host memory simulation. Accuracy also degrades when physical cores are underprovisioned or when oversubscribed workloads depend heavily on Linux scheduling details, as seen with the OpenMP SP and LU benchmarks. Finally, the evaluation is limited to open-source accelerators and mostly single-node settings, so generality beyond those regimes is promising but not fully established.

## Related Work

- _Reinhardt et al. (SIGMETRICS '93)_ — Wisconsin Wind Tunnel already ran available computation natively, but NEX extends that idea to modern accelerator-integrated full stacks with explicit MMIO, DMA, and interrupt boundaries.
- _Li et al. (SIGCOMM '22)_ — SimBricks offers modular full-system composition, whereas this paper changes the speed/visibility point by combining native host execution with a di-simulated accelerator.
- _Karandikar et al. (ISCA '18)_ — FireSim provides cycle-exact FPGA-based system simulation, while NEX+DSim stays purely in software and targets interactive iteration rather than full-SoC RTL availability.
- _Ma et al. (OSDI '24)_ — Performance Interfaces introduced LPNs as accelerator performance models; this paper turns them into one half of a practical end-to-end simulator by pairing them with functional simulation and host-side orchestration.

## My Notes

<!-- empty; left for the human reader -->

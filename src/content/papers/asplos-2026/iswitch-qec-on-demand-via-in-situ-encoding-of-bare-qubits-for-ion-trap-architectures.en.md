---
title: "iSwitch: QEC on Demand via In-Situ Encoding of Bare Qubits for Ion Trap Architectures"
oneline: "Runs non-Clifford 1Q gates on bare ion-trap qubits and encodes only when protection is needed, using in-situ switching plus a compiler to cut EFT overhead."
authors:
  - "Keyi Yin"
  - "Xiang Fang"
  - "Zhuo Chen"
  - "David Hayes"
  - "Eneet Kaur"
  - "Reza Nejabati"
  - "Hartmut Haeffner"
  - "Wes Campbell"
  - "Eric Hudson"
  - "Jens Palsberg"
  - "Travis Humble"
  - "Yufei Ding"
affiliations:
  - "University of California, San Diego, San Diego, California, USA"
  - "Quantinuum, Broomfield, Colorado, USA"
  - "Cisco Quantum Lab, San Jose, California, USA"
  - "University of California, Berkeley, Berkeley, California, USA"
  - "University of California, Los Angeles, Los Angeles, California, USA"
  - "Oak Ridge National Laboratory, Oak Ridge, Tennessee, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790177"
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

iSwitch argues that trapped-ion systems do not need to keep every qubit logically encoded all the time. Instead, it leaves qubits bare for high-fidelity single-qubit non-Clifford gates, switches them into surface-code patches only when protection is needed, and uses a compiler to manage those transitions. On the paper's VQA workloads, that hybrid strategy preserves early-fault-tolerant fidelity while cutting qubit demand by roughly one-third to one-half relative to stronger always-encoded baselines.

## Problem

The paper starts from a familiar obstacle in fault-tolerant quantum computing: surface codes make long computations possible, but their overhead is dominated by two costs. First, each logical qubit needs a large 2D patch of physical qubits, and practical logical error rates often require distances much larger than the textbook threshold arguments suggest. Second, non-Clifford gates such as `T` or arbitrary `Rz(theta)` rotations are not native to the code, so the standard fully fault-tolerant path uses state injection and magic-state distillation, which consume many ancilla qubits and substantial runtime.

That is a bad fit for the regime the authors care about. Near-term trapped-ion machines are expected to reach thousands of physical qubits, not the millions needed for monolithic FTQC, so the real target is early fault tolerance rather than universal large-scale fault tolerance. Existing partial-FT approaches already try to relax the full-encoding assumption, but they still pay heavily for ancillary logical states, probabilistic injection protocols, and code-growth steps around the injected state. The systems question is therefore not merely how to run surface codes on ion traps, but how to spend scarce protection only where it buys the most fidelity.

## Key Insight

The central claim is that trapped-ion hardware makes a sharper split possible: single-qubit gates are already accurate enough to run directly on bare qubits, while two-qubit operations benefit much more from logical protection. If the machine can convert a data qubit in place between bare and logical form, then a program can execute non-Clifford one-qubit work cheaply on bare qubits and pay surface-code overhead mainly around the noisier multi-qubit interactions.

That idea only works if switching is cheap and controllable. iSwitch's real insight is that surface-code gauge-fixing can be adapted into a runtime encoding protocol that grows a bare data qubit into a logical patch without first preparing a separate logical ancilla. Once that conversion exists, the architecture can expose switching as a first-class instruction and the compiler can treat logical patches as a scarce register file, allocating them only around operations that justify the cost.

## Design

The design has three layers. The first is the runtime encoding protocol. Starting from a bare qubit carrying arbitrary program state, iSwitch initializes surrounding ancillas in a carefully chosen `|+>` / `|0>` pattern, performs one gauge-fixing round, and then runs `d - 1` rounds of normal surface-code correction to promote the state into a distance-`d` logical qubit. The reverse operation shrinks a logical qubit back to bare form by measuring out ancillas and correcting any sign changes on the surviving qubit. A key technical result is that not all conversions are equally safe: naive placement leaves too many random stabilizers, so the paper proposes a triangular initialization pattern that maximizes deterministic stabilizers and lowers conversion-induced logical error.

The second layer is a hybrid ISA for a QCCD trapped-ion machine. Bare-region instructions move ions and apply native one-qubit gates. Logical-region instructions move whole surface-code patches and perform transversal logical CNOT by shuttling two patches into overlap so paired physical CNOTs can run in parallel inside 1D traps. Two explicit instructions, `CodeSwitch_B2L` and `CodeSwitch_L2B`, are confined to a boundary region, which keeps the architecture modular and gives the compiler a clear place to schedule encoding changes.

The third layer is the compiler. For encoding allocation, it treats logical patches like limited registers and bare qubits like lower-fidelity memory, using a greedy linear-scan style policy to decide when qubits should be promoted or shrunk. Two-qubit gates trigger logical allocation for both operands; one-qubit non-Clifford gates are postponed until the qubit can run bare. For placement, the compiler uses SABRE-like routing over the 2D logical grid, emitting `LogicMove` instructions for patches and coordinating movement with conversion constraints near the boundary. The aim is not just fewer moves, but fewer noisy conversions.

## Evaluation

The evaluation is simulation-heavy but more grounded than a pure abstract model. The authors calibrate their noise model from randomized benchmarking data on Quantinuum's H1 device, using error rates around `1e-5` for one-qubit gates, `1e-3` for two-qubit gates and SPAM, `1e-5` for idling, and `1e-4` for shuttling. They then simulate logical operations with `Stim` and `Pymatching`, and run end-to-end VQA benchmarks based on UCCSD circuits for physics and chemistry workloads, including Heisenberg and Ising instances up to `30` logical qubits.

The logical-operation study supports the main mechanism. `LogicCX` and `LogicMove` error rates fall with code distance, while `CodeSwitch` error stays roughly distance-independent, which matches the paper's argument that conversion errors come from a small fixed set of vulnerable qubits rather than from the asymptotic code distance. That in turn explains why the authors settle on distance `9`: beyond that point, logical CNOT is already good enough and conversion becomes the bottleneck.

At the application level, iSwitch improves final VQA energy over the bare NISQ baseline by `4.34x-43.4x`, depending on workload size. Against other QEC baselines, the resource story is the main result. Compared with the fully fault-tolerant `MSD-Logical` design, iSwitch needs `2.06x` fewer physical qubits on average to reach the same fidelity, because it avoids dedicating a large fraction of the machine to magic-state factories and does not decompose every `Rz(theta)` into long Clifford+`T` sequences. Compared with the partial-FT injection baseline, it needs `1.49x` fewer qubits on average and avoids probabilistic ancilla preparation. The evaluation is convincing for the intended regime: medium-scale VQA-style workloads on trapped-ion QCCD hardware with tight qubit budgets. It says less about broader algorithms, multi-program scheduling, or real hardware execution at scale.

## Novelty & Impact

Relative to standard surface-code FTQC, iSwitch's novelty is not a new decoder or code family, but a systems-level refusal to encode everything all the time. Relative to injection-based EFT, it replaces ancillary logical-state preparation with an in-situ conversion path that directly repurposes the program qubit. Relative to trapped-ion architecture papers, it connects hardware capability, ISA design, and compiler policy into one selective-QEC stack.

That makes the paper likely to matter to researchers working on trapped-ion architecture, early fault tolerance, and quantum compilation under hardware constraints. Its main contribution is a concrete design point for the "few-thousand-physical-qubit" era, where full FTQC is still too expensive but NISQ execution is already too noisy.

## Limitations

iSwitch is still only partially fault tolerant. The paper shows that conversion error is largely independent of code distance, so once logical CNOT becomes reliable, code switching itself becomes the limiting factor. That means the scheme cannot simply scale by dialing up the surface-code distance. The authors also evaluate almost entirely through calibrated simulation rather than a live end-to-end experiment, and the benchmark set is centered on UCCSD-style VQAs where one-qubit non-Clifford rotations are sparse enough that selective encoding pays off.

There are hardware-specific assumptions too. The design relies on trapped-ion strengths such as ultra-high-fidelity one-qubit gates, QCCD ion shuttling, and efficient transversal logical CNOT through patch overlap. If those assumptions weaken on another platform, the bare-versus-logical split may stop being attractive. The paper also observes a diminishing-return point where full FTQC starts to catch up: around `5k` physical qubits for the evaluated `20`-logical-qubit workloads and around `7k` for the `30`-logical-qubit cases.

## Related Work

- _Jones and Murali (ASPLOS '26)_ — studies how to build scalable trapped-ion surface-code hardware, while iSwitch assumes that substrate and asks how to avoid keeping every qubit logically encoded on it.
- _Liu et al. (ASPLOS '26)_ — AlphaSyndrome optimizes syndrome-measurement scheduling inside a fixed QEC execution model; iSwitch instead changes when qubits are encoded and when they are left bare.
- _Acharya et al. (Nature '25)_ — demonstrates progress toward full surface-code fault tolerance on superconducting hardware, whereas iSwitch targets a lower-overhead early-FT operating point for trapped ions.

## My Notes

<!-- empty; left for the human reader -->

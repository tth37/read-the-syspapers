---
title: "Reconfigurable Quantum Instruction Set Computers for High Performance Attainable on Hardware"
oneline: "Makes an SU(4)-native quantum ISA practical by co-designing a time-optimal gate scheme, compiler pipeline, and routing strategy around real hardware constraints."
authors:
  - "Zhaohui Yang"
  - "Dawei Ding"
  - "Qi Ye"
  - "Cupjin Huang"
  - "Jianxin Chen"
  - "Yuan Xie"
affiliations:
  - "The Hong Kong University of Science and Technology, Hong Kong"
  - "Fudan University, Shanghai Institute for Mathematics and Interdisciplinary Sciences, Shanghai, China"
  - "Tsinghua University, Beijing, China"
  - "DAMO Academy, Alibaba Group, Bellevue, WA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790208"
project_url: "https://zenodo.org/records/18163249"
tags:
  - hardware
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

ReQISC argues that the usual CNOT-centered quantum ISA is leaving performance on the table, but that a richer ISA only helps if hardware control, calibration, compilation, and routing are redesigned together. Its answer is to expose the full `SU(4)` family as the ISA, realize arbitrary two-qubit gates in theoretically optimal time under arbitrary coupling Hamiltonians, and compile programs so that the richer gate set actually reduces circuit cost on hardware-relevant benchmarks.

## Problem

The paper starts from a familiar asymmetry in quantum systems. Hardware vendors increasingly expose more expressive native two-qubit interactions than plain CNOT or CZ, and prior work shows that richer basis gates can reduce the number of entangling gates needed to synthesize a program. But those theoretical wins rarely survive contact with practice. Every additional native two-qubit gate increases calibration burden, the control stack for continuous gate sets is often complicated or hardware-specific, and standard compilers still treat the richer ISA as a curiosity rather than as the organizing abstraction for the whole stack.

That makes the real bottleneck cross-layer. A more expressive ISA is only useful if three things hold at once. First, hardware must implement arbitrary or near-arbitrary two-qubit gates without long pulse sequences or obvious fidelity loss. Second, calibration must stay manageable enough that the ISA is not dead on arrival. Third, the compiler must restructure real programs, not just isolated gates, so that the extra expressivity reduces two-qubit count, depth, routing overhead, and ultimately runtime. The paper's claim is that previous work usually addressed one of these pieces at a time, which is why CNOT-based compilation still dominates.

## Key Insight

The paper's core idea is that the full `SU(4)` space can be made practical if it is treated as a reconfigurable machine interface rather than as a bag of special-case gates. Any two-qubit unitary can be reduced, up to local one-qubit rotations, to a point in the Weyl chamber. ReQISC uses that geometric view as the shared contract between compiler and microarchitecture: the compiler emits canonical `SU(4)` instructions, and the control stack drives the hardware to the corresponding Weyl point in optimal time.

That only works because ReQISC solves two practical obstacles that would otherwise break the abstraction. The first is hardware generality: its gate scheme is not tied to one coupling such as pure `XY`, but handles arbitrary canonical two-qubit couplings with a small set of local-drive parameters. The second is pathological near-identity gates, which would require unbounded pulse amplitudes if executed naively. ReQISC mirrors those gates toward the SWAP corner and accounts for the implied qubit remapping in the compiler, preserving optimality without paying extra two-qubit gates in the common case.

## Design

ReQISC has two major layers. The first is the microarchitecture, really a pulse-generation and control scheme for arbitrary two-qubit instructions. Given a target unitary and a hardware coupling Hamiltonian, ReQISC first extracts canonical Weyl coordinates through KAK decomposition. It then chooses one of three execution subschemes: no-detuning (`ND`), equal-amplitude-plus (`EA+`), or equal-amplitude-minus (`EA-`). Each mode solves for a small control vector consisting of local drive amplitudes, shared detuning, and gate duration. The important systems claim is that this is both unified and time-optimal: the same logic works across `XY`, `XX`, and more general couplings, while the resulting duration matches the theoretical lower bound.

The second layer is the compiler, which is where the paper becomes more than a pulse-control result. For structured quantum programs built from `CX`/`CCX`/`MCX`-like building blocks, ReQISC uses a program-aware template synthesis pass that rewrites refined three-qubit IR fragments into pre-synthesized `SU(4)` templates. It then applies a hardware-agnostic hierarchical synthesis pass that partitions circuits into `SU(4)` blocks, conditionally runs approximate synthesis on compact three-qubit regions, and uses a DAG-compacting pass based on approximate commutation to create better local synthesis opportunities. Finally, it routes on constrained topologies with mirroring-SABRE, a variant of SABRE that prefers SWAP insertions that can be absorbed by surrounding `SU(4)` gates.

The calibration story is also part of the design, not an afterthought. ReQISC offers an "Eff" mode that skips the most aggressive local synthesis in order to keep the number of distinct `SU(4)` gates very small, and a "Full" mode that accepts more calibration burden for more gate-count reduction. For variational programs, the authors explicitly recommend decomposing back into fixed two-qubit families plus parametrized one-qubit gates rather than recalibrating arbitrary variational `SU(4)` instructions every run.

## Evaluation

The microarchitectural results are strong and easy to interpret. On `XY` coupling, ReQISC needs only `1.341 g^-1` average pulse duration to synthesize Haar-random `SU(4)` gates, versus `6.664 g^-1` for conventional CNOT-based realization, a `4.97x` reduction. The advantage persists across `XX` coupling and random couplings as well, which is important because the paper's generality claim would be hollow if the gains only appeared on one favored Hamiltonian.

At the compiler level, the authors evaluate `132` benchmarks from `17` categories against Qiskit, TKet, BQSKit, and SU(4)-augmented variants. ReQISC-Full reduces two-qubit gate count by `51.89%`, two-qubit depth by `57.5%`, and pulse duration by `71.0%` on average, while ReQISC-Eff still cuts duration by `68.03%`. Those averages are much larger than the baselines' reductions, which suggests the win is not merely "SU(4) is better than CNOT," but that the compiler's specialized passes are doing real work. The ablation section supports that interpretation: removing DAG compacting materially hurts results, and BQSKit-SU(4) achieves some gate reduction but at the cost of an impractically large distinct-gate set.

The hardware-aware results are also useful. Under routing, ReQISC's geometric-mean overhead is `1.36x` on a 1D chain and `1.09x` on a 2D grid, compared with `2.45x` and `1.79x` for CNOT-based compilation. In noisy simulation on twelve benchmarks, ReQISC improves fidelity as well as speed, with an average `2.36x` error reduction and `3.06x` speedup at logical level, growing to roughly `3.18x-3.34x` error reduction and `4.30x-4.55x` speedup after topology mapping. The calibration tradeoff looks plausible rather than hand-waved: ReQISC-Eff stays below `10` distinct `SU(4)` gates, while ReQISC-Full stays below `200`, and more than three quarters of Full-compiled programs still use fewer than `20` distinct two-qubit gates.

## Novelty & Impact

Relative to _Chen et al. (ASPLOS '24)_, ReQISC's main step is not just "another continuous gate family," but a generalization from `XY`-centric gate control to arbitrary coupling Hamiltonians plus a full compiler and routing stack around it. Relative to _Huang et al. (PRL '23)_, which argues that better two-qubit basis gates matter, ReQISC pushes the idea to its endpoint by exposing the full `SU(4)` space instead of picking a slightly better fixed basis. Relative to `Qiskit`-, `TKet`-, or `BQSKit`-style flows, the impact is architectural: the paper treats ISA design, pulse generation, optimization, and topology-aware routing as one co-designed problem.

That makes the paper important for quantum hardware-software co-design rather than only for compiler specialists. If later hardware platforms really can calibrate continuous families cheaply enough, ReQISC is a credible blueprint for how to consume that capability end to end.

## Limitations

The biggest limitation is that most of the evidence is still simulation and modeling rather than full end-to-end execution on a live quantum processor. The paper cites prior experiments that calibrated similar gates at high fidelity, and its own control scheme is analytically grounded, but ReQISC itself is not demonstrated as a deployed production stack on hardware. That means the calibration and crosstalk story is promising, not settled.

There are also workload and tooling boundaries. The program-aware synthesis pass is especially well matched to structured Boolean-style quantum programs composed from `CX`/`CCX`/`MCX` patterns, and the paper is explicit that variational programs need a more conservative path to avoid continuous recalibration. ReQISC-Full also trades away calibration simplicity for lower gate count; even if the distinct-gate count remains moderate in the experiments, some labs may still prefer the weaker but safer Eff configuration. More broadly, the fidelity study uses a duration-scaled depolarizing model, so it validates the value of shorter gates under a standard abstraction, not every hardware-specific error mechanism.

## Related Work

- _Chen et al. (ASPLOS '24)_ — AshN shows that a reduced continuous ISA can be time-optimal on `XY` coupling; ReQISC generalizes the control scheme and adds end-to-end compilation plus routing.
- _Huang et al. (PRL '23)_ — Quantum Instruction Set Design for Performance argues that better native two-qubit gates shrink synthesis cost, while ReQISC turns that observation into a full `SU(4)` machine interface.
- _Lin et al. (MICRO '22)_ — hardware-aware basis-gate selection adapts compilation to available native gates, whereas ReQISC redesigns the native interface itself around arbitrary `SU(4)` realizability.
- _McKinney et al. (HPCA '24)_ — MIRAGE uses mirror gates to improve decomposition and routing for alternative fixed gate sets; ReQISC uses mirroring for a different purpose, namely avoiding near-identity control singularities in an `SU(4)`-native ISA.

## My Notes

<!-- empty; left for the human reader -->

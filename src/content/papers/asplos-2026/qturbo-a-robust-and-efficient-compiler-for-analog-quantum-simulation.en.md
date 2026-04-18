---
title: "QTurbo: A Robust and Efficient Compiler for Analog Quantum Simulation"
oneline: "Factorizes analog-quantum compilation into a global linear solve, local mixed solves, evolution-time tightening, and residual refinement to generate shorter, more accurate pulses."
authors:
  - "Junyu Zhou"
  - "Yuhao Liu"
  - "Shize Che"
  - "Anupam Mitra"
  - "Efekan Kökcü"
  - "Ermal Rrapaj"
  - "Costin Iancu"
  - "Gushu Li"
affiliations:
  - "University of Pennsylvania, Philadelphia, PA, USA"
  - "Lawrence Berkeley National Laboratory, Berkeley, CA, USA"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3760250.3762227"
code_url: "https://github.com/JunyuZhou2002/QTurbo.git"
tags:
  - quantum
  - compilers
  - hardware
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

QTurbo argues that analog-quantum compilation looks harder than it really is because current tools solve one monolithic mixed equation system. It lifts repeated coefficients into synthesized variables, solves a global linear system first, then solves only small connected mixed subsystems for the real controls. On top of that, it chooses the shortest feasible evolution time from hardware amplitude limits and uses a residual-refinement step to recover accuracy. The result is much faster compilation, shorter pulse schedules, and lower error than SimuQ on both simulated backends and QuEra's Aquila device.

## Problem

Analog quantum simulation is attractive because it avoids compiling everything down to enormous digital gate sequences and instead uses the hardware's native Hamiltonian directly. The catch is that the software stack is immature. The paper positions SimuQ as the only public compiler of this kind and treats it as the baseline to beat. SimuQ maps a target Hamiltonian to a simulator by forming one global mixed system over evolution time, pulse amplitudes, phases, atom positions, and indicator-like control choices.

That formulation is expressive, but it creates exactly the wrong search surface. The solver must explore coupled continuous and discrete dependencies across all instructions at once, so compilation time grows rapidly with system size. The paper shows exponential-looking growth for an Ising cycle benchmark as qubits increase. Even when SimuQ finds a feasible solution, it often does not minimize machine evolution time, so the resulting pulse schedule can be much longer than necessary. In analog hardware that matters twice: longer pulses are more vulnerable to decoherence and noise, and solver instability sometimes means the baseline fails to return a solution at all. The core problem is therefore not merely compiling analog programs correctly, but doing so quickly, predictably, and with pulse lengths that fit hardware coherence budgets.

## Key Insight

QTurbo's central insight is that the "one huge mixed system" is not actually structurally flat. Many terms in the equations repeat the same physical quantities, such as Rydberg interaction coefficients or amplitude-time products. If those repeated expressions are lifted into synthesized intermediate variables, the global matching problem becomes a linear system over target Hamiltonian coefficients. The remaining hard part is no longer one universal nonlinear solve, but several much smaller local mixed systems that recover the real control variables behind each synthesized coefficient.

The second part of the insight is that hardware constraints can be turned into an optimization principle instead of a nuisance. Runtime-dynamic controls such as detuning or Rabi amplitude have maximum legal values, so each local subsystem implies a shortest achievable evolution time for the instruction it represents. The slowest of those instructions becomes the bottleneck and therefore the right global simulator time. Once that time is fixed, QTurbo can solve the runtime-fixed variables and then use the more flexible dynamic controls to absorb residual error. In other words, the paper turns decomposition, timing, and accuracy control into one coherent pipeline rather than three unrelated heuristics.

## Design

The design has four connected stages. First, QTurbo builds a global linear system. For the Rydberg backend, expressions such as `C6 / 4|xi - xj|^6`, `Delta_i / 2 * T_sim`, and `Omega_i / 2 * cos(phi_i) * T_sim` are replaced by synthesized variables `alpha`. The compiler then writes linear equations stating that these synthesized coefficients must match the target Hamiltonian's coefficients after scaling by the target evolution time. This strips away most of the combinatorial structure before any nonlinear solving begins.

Second, QTurbo reconstructs the remaining dependencies as a graph between synthesized variables and the true amplitude variables. Connected components of that graph define localized mixed equation systems. Atom-position variables that share interaction terms end up in one local subsystem; each detuning or Rabi-drive group can become its own subsystem. Compared with SimuQ's all-at-once solve, this reduces the dimensionality and isolates hard dependencies to where they actually exist.

Third, QTurbo optimizes evolution time. The paper distinguishes runtime-dynamic variables, whose amplitudes can be changed during execution, from runtime-fixed variables such as atom positions. For each local subsystem with a time-critical dynamic variable, QTurbo asks: if this variable runs at its maximum hardware amplitude, what is the shortest legal `T_sim` that still satisfies the synthesized coefficients? The compiler computes such a minimum for each instruction and chooses the largest of them as the global machine evolution time, ensuring the bottleneck instruction is saturated while all others remain feasible. If the fixed-variable solve still violates constraints, QTurbo increases time iteratively until the solution becomes legal. For time-dependent Hamiltonians, the paper applies the same logic segment by segment after a piecewise-constant discretization.

Fourth, QTurbo adds an accuracy-refinement pass. The paper derives an `L1` error bound showing that total compilation error is the sum of error from the global linear solve and the localized mixed solves, scaled by the linear-system matrix norm. It then uses the residual of the first-round solution to adjust the synthesized variables associated with runtime-dynamic controls. Because those controls are more flexible than fixed variables, they can compensate for approximation error introduced earlier in the pipeline without reopening the full nonlinear problem.

## Evaluation

The evaluation covers both simulated and real hardware settings. On simulated backends, the paper targets Rydberg and Heisenberg analog instruction sets and benchmarks systems from `3` to `93` qubits, including Ising chain, Ising cycle, Kitaev, Ising cycle+, Heisenberg chain, MIS chain, and PXP. The baseline is always SimuQ, and the metrics are compilation time, machine execution time, and a coefficient-space relative error between compiled and target Hamiltonians.

For the Rydberg backend, QTurbo reports an average `350x` compilation speedup, `54%` shorter execution time, and `45%` lower compilation error; the refinement step alone cuts error by `66%` relative to running without refinement. For the Heisenberg backend, the average speedup rises to `800x`, execution time drops by `48%`, and the reported compilation error goes to zero on the evaluated cases. The paper's mapping case study reuses SimuQ's mapping and still sees a `61x` compilation speedup, which is useful because it shows the solver decomposition matters even when placement is held fixed. The time-dependent MIS-chain study is also strong: after discretizing into four segments, QTurbo reports `1300x` faster compilation, `64%` shorter execution time, and `77%` lower error.

The most persuasive evidence is the real-device section on QuEra's Aquila. For a `12`-atom Ising cycle, QTurbo compresses a `1.0 us` target evolution into a `0.25 us` machine pulse, while SimuQ needs `1.2 us`; for a `6`-atom PXP model, it compresses `20 us` target evolution into `0.4 us` instead of `3.4 us`. Those shorter pulses translate into lower measurement error: the paper reports average reductions of `59%` and `80%` on the two Ising observables, and `31%` and `36%` on the two PXP observables. That supports the paper's main claim well. The main caveat is that the real-device study is narrow, and the compiler's relative-error metric does not model decoherence directly, so the hardware results are necessary to validate the noise-robustness story.

## Novelty & Impact

Relative to _Peng et al. (POPL '24)_, QTurbo keeps the same goal of compiling arbitrary analog Hamiltonians but changes the computational structure completely: one global mixed solve becomes a linear stage plus local mixed stages, followed by explicit timing and refinement passes. Relative to pulse-programming frameworks such as Pulser or general control languages such as OpenQASM 3, QTurbo's novelty is not exposing more low-level control, but automatically solving for a good control schedule from a Hamiltonian specification under hardware constraints.

That makes the paper important for researchers who want analog quantum simulation to look more like a real compiler target and less like handcrafted numerical tuning. It is a compiler paper first, but one whose impact depends directly on hardware noise budgets and analog-device usability. If analog Rydberg, trapped-ion, or superconducting simulation keeps growing, this kind of decomposition-based compiler architecture is a likely reference point.

## Limitations

QTurbo does not solve the entire analog-programming stack. Its main wins assume the backend exposes a clear instruction abstraction and time-critical variables with known amplitude limits. Mapping is largely outside the contribution: the paper's mapping case study simply reuses the baseline's placement strategy. The time-dependent story also depends on piecewise-constant discretization, which is practical but can introduce approximation error before compilation even starts.

The evaluation is strongest on neutral-atom Rydberg systems and much thinner on real hardware diversity. Heisenberg results are simulated rather than run on cloud devices, and the real-device section uses two small case studies on Aquila. The compiler's main accuracy metric compares Hamiltonian coefficients, not final many-body state fidelity under a full noise model. None of that invalidates the paper, but it does mean QTurbo is best read as a strong compiler architecture for analog simulation, not a complete answer to mapping, calibration, and hardware-aware verification.

## Related Work

- _Peng et al. (POPL '24)_ — SimuQ also compiles arbitrary Hamiltonians to analog controls, but it solves one global mixed equation system instead of factorizing the solve the way QTurbo does.
- _Silvério et al. (Quantum '22)_ — Pulser offers a programmable interface for neutral-atom pulse design, whereas QTurbo focuses on automatic compiler synthesis from Hamiltonian descriptions.
- _Cross et al. (TQC '22)_ — OpenQASM 3 expands pulse-level programmability, but it does not itself optimize analog Hamiltonian compilation or evolution time.
- _Li et al. (ASPLOS '22)_ — Paulihedral optimizes digital Hamiltonian-simulation kernels after circuitization, while QTurbo stays in the analog domain and exploits native interactions directly.

## My Notes

<!-- empty; left for the human reader -->

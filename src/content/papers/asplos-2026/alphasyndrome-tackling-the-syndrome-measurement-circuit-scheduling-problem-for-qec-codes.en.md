---
title: "AlphaSyndrome: Tackling the Syndrome Measurement Circuit Scheduling Problem for QEC Codes"
oneline: "Uses MCTS plus decoder-in-the-loop simulation to schedule QEC syndrome measurements so hook errors avoid logical operators and decoder failure modes."
authors:
  - "Yuhao Liu"
  - "Shuohao Ping"
  - "Junyu Zhou"
  - "Ethan Decker"
  - "Justin Kalloor"
  - "Mathias Weiden"
  - "Kean Chen"
  - "Yunong Shi"
  - "Ali Javadi-Abhari"
  - "Costin Iancu"
  - "Gushu Li"
affiliations:
  - "University of Pennsylvania, Philadelphia, United States"
  - "University of California, Berkeley, Berkeley, United States"
  - "Amazon Quantum Technologies, Pasadena, United States"
  - "IBM Research, Yorktown Heights, United States"
  - "Lawrence Berkeley National Laboratory, Berkeley, United States"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3779212.3790123"
code_url: "https://github.com/acasta-yhliu/asyndrome.git"
project_url: "https://doi.org/10.5281/zenodo.18291927"
tags:
  - quantum
  - compilers
  - hardware
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

AlphaSyndrome treats QEC syndrome-measurement scheduling as a search problem over legal Pauli-check orders, not a depth-only optimization problem. It scores complete schedules with noisy simulation and the target decoder in the loop, reporting an average `80.6%` logical-error reduction versus lowest-depth schedules across `32` code/decoder instances.

## Problem

The paper starts from a subtle but important fact about stabilizer-based QEC: syndrome measurement has a very large scheduling space because most stabilizers commute, and most Pauli checks inside those stabilizer measurements commute as well. In an ideal noiseless circuit, many such schedules are equivalent. In a realistic noisy circuit, they are not. Errors on the ancilla can propagate through later two-qubit checks as hook errors, turning one local fault into multiple data-qubit faults. That means the order in which a stabilizer is measured changes which data qubits are most vulnerable and, ultimately, the logical error rate.

This is why the usual answers are unsatisfying. Lexical order is arbitrary. Lowest-depth schedules reduce idling, but the paper shows that lower depth does not imply lower logical error. Google's zig-zag schedule works for rotated surface codes, yet it depends on that code family's geometry and does not generalize cleanly. A schedule is also decoder-dependent and noise-model-dependent.

## Key Insight

AlphaSyndrome's central claim is that a good schedule should optimize two things at once: propagated faults should stay far from logical operators, and they should land in regions the chosen decoder can actually correct. The paper illustrates this with clockwise versus anti-clockwise surface-code schedules: both are valid, but one biases propagated faults toward logical `Z` strings while the other biases them toward logical `X` strings.

Neither objective admits a simple rule: general codes have exponentially many equivalent logical operators, and practical decoders are heuristic approximations to an NP-hard problem. So the paper moves to simulation-guided search over whole schedules.

## Design

AlphaSyndrome represents a syndrome-measurement round as ticks, where each Pauli check is a triplet `(data, ancilla, sigma)` assigned to one tick. Checks in the same tick cannot share a data or ancilla qubit. To preserve commutation constraints, the framework partitions stabilizers into compatible groups, runs MCTS on each partition, and concatenates the resulting partial schedules.

The MCTS state is a partially filled schedule. A move appends one unscheduled Pauli check at the earliest non-conflicting tick, while subtree reuse avoids restarting search from scratch after every decision. For a complete schedule, the system builds a `stim` sampling circuit, runs the noisy syndrome-measurement round, performs ideal correction with the chosen decoder, and checks whether logical observables flipped. The score is the inverse of the resulting overall logical error rate `1 / (1 - (1 - pX)(1 - pZ))`, so the search optimizes logical reliability directly instead of a proxy such as depth.

## Evaluation

The evaluation spans rotated surface codes, color codes, hyperbolic surface/color codes, defect surface codes, and bivariate bicycle codes, paired with `MWPM`, `BP-OSD`, and hypergraph union-find decoders. Relative to lowest-depth schedules, AlphaSyndrome reduces overall logical error by `80.6%` on average across `32` code/decoder instances, with a peak reduction of `96.2%`. It usually produces deeper circuits, but the paper argues that the reliability gain is large enough to dominate that cost.

That benefit carries to system-level cost because comparable logical error can often be reached with smaller-distance codes. Table 3 reports space-time-volume reductions from `18.4%` to `89.0%`. Against hand-crafted schedules, AlphaSyndrome matches Google's zig-zag schedule on rotated surface codes and outperforms IBM's `[[72, 12, 6]]` bivariate bicycle schedule by `44%` with `BP-OSD` and `10%` with union-find. The cross-decoder study is especially convincing: `BP-OSD`-compiled schedules beat union-find-compiled schedules by `25.4%` on average when tested under `BP-OSD`, while the reverse comparison favors union-find by `34.3%`. The paper also reports gains down to physical error rates of `10^-5`.

## Novelty & Impact

Relative to lowest-depth scheduling work, AlphaSyndrome's novelty is that it optimizes logical reliability rather than circuit depth. Relative to Google's and IBM's manual schedules, its contribution is generality: the search procedure applies across multiple code families instead of depending on one code's lattice geometry. Relative to QECC-Synth-style layout synthesis, it operates one layer lower by keeping the code fixed and optimizing the internal order of syndrome extraction itself.

## Limitations

The approach is expensive and specialized. The paper runs `4000-8000` MCTS iterations per step on a large multi-socket server with parallel `stim` simulations, so this is not a lightweight online scheduler. The output schedule is tailored to one decoder and one noise model, and the cross-decoder results show that this specialization does not transfer automatically. AlphaSyndrome also does not jointly optimize layout, routing, decoder design, or repeated-round adaptive control, and its space-time-volume argument relies on an IBM Brisbane timing model rather than hardware measurements.

## Related Work

- _Acharya et al. (Nature '25)_ — Google's rotated-surface-code schedule is the canonical hand-crafted reference that AlphaSyndrome matches automatically on that code family.
- _Bravyi et al. (Nature '24)_ — IBM's bivariate bicycle work provides another manual schedule target, and AlphaSyndrome improves on it in the paper's comparison.
- _Li et al. (ASPLOS '25)_ — QECC-Synth optimizes QEC layout synthesis on sparse hardware, whereas AlphaSyndrome keeps layout fixed and optimizes the internal syndrome-extraction order.
- _Gehér et al. (PRX Quantum '24)_ — Tangling-schedule analysis studies circuit-order effects and connectivity, while AlphaSyndrome searches schedules against decoder-conditioned logical error directly.

## My Notes

<!-- empty; left for the human reader -->

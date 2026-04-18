---
title: "COMPAS: A Distributed Multi-Party SWAP Test for Parallel Quantum Algorithms"
oneline: "Distributes the multi-party SWAP test across line-connected QPUs with Bell-pair teleportation, preserving constant depth while reducing entanglement use from naive quadratic scaling to O(nk)."
authors:
  - "Brayden Goldstein-Gelb"
  - "Kun Liu"
  - "John M. Martyn"
  - "Hengyun (Harry) Zhou"
  - "Yongshan Ding"
  - "Yuan Liu"
affiliations:
  - "Brown University, Providence, Rhode Island, USA"
  - "Yale University, New Haven, Connecticut, USA"
  - "Pacific Northwest National Lab, Richland, Washington, USA"
  - "Harvard University, Cambridge, Massachusetts, USA"
  - "QuEra Computing Inc., Boston, Massachusetts, USA"
  - "North Carolina State University, Raleigh, North Carolina, USA"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3779212.3790143"
code_url: "https://github.com/kunliu7/Distributed-Q-Algo"
tags:
  - quantum
  - hardware
  - compilers
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

COMPAS turns the constant-depth multi-party SWAP test into a distributed primitive for modular quantum computers. It keeps each input state local to one QPU, realizes shared GHZ control and remote `CSWAP`s with Bell-pair-assisted teleoperations, and uses Fanout to parallelize shared-control Toffolis. The result preserves constant depth while reducing the naive distributed Bell-pair cost to `O(n k)`.

## Problem

Useful quantum workloads will likely exceed the qubit count and wiring budget of a single chip, so future machines will need multiple QPUs. In that setting, nonlocal work must be expressed through Bell pairs, teleportation, and remote gates, so every long-range interaction spends scarce entanglement resources and adds noise. The authors focus on the multi-party SWAP test because it underlies Rényi entropy estimation, entanglement spectroscopy, virtual cooling and distillation, and parallel QSP.

The challenge is that the best monolithic constructions do not map cleanly onto modular hardware. A naive distributed implementation slices each input state across QPUs, gathers matching qubits to one node, and runs many local SWAP tests there. On a line topology, that worst case uses `O(n^2)` Bell pairs per QPU, and if the larger computation continues afterward the qubits must be teleported back. The paper therefore asks whether this primitive can be distributed while preserving constant depth and bounded GHZ width at realistic entanglement cost.

## Key Insight

The central claim is that the multi-party SWAP test is structured enough to distribute without paying a depth penalty. The cyclic shift can be laid out so each state interacts with at most two neighbors in an interleaved order such as `1, k, 2, k-1, ...`. That lets the system assign one state per QPU, keep state preparation local, and reserve communication for the SWAP-test phase.

COMPAS then combines distributed GHZ preparation, neighboring remote `CSWAP`s implemented via either `telegate` or `teledata`, and a Fanout-based rewrite that parallelizes the `n` Toffoli gates sharing one control qubit. The Fanout step is what keeps multi-qubit states at `O(1)` depth instead of serializing across width. Together, these choices retain the monolithic algorithm's constant-depth behavior while moving Bell-pair consumption down to `O(n k)`.

## Design

The architecture uses `k` QPUs in a line. QPU `i` stores one `n`-qubit state `rho_i`, and some QPUs also hold a GHZ control qubit. Preparing `rho_i` stays local; only the SWAP-test phase communicates. GHZ preparation adapts Quek et al.'s construction by replacing inter-QPU CNOTs with telegates, yielding a distributed `ceil(k/2)`-party GHZ state. The cyclic shift is then executed as two rounds of neighboring `CSWAP`s.

COMPAS offers two `CSWAP` implementations. In `telegate`, the remote swap is decomposed into teleported CNOTs and teleported Toffolis. In `teledata`, Bob teleports `rho_j` to Alice's ancillas, Alice performs the whole `CSWAP` locally, and then teleports the qubits back. Shared-control Toffolis are rewritten into Fanout-based circuits and ancillas are reused across steps. The per-QPU accounting is explicit: `telegate` needs `n` ancillas, `2 + 6n` Bell pairs, and depth `99`; `teledata` needs `2n` ancillas, `2 + 4n` Bell pairs, and depth `91`. The paper recommends `teledata` because its total memory cost is lower once Bell-pair distillation is included.

## Evaluation

This is an analytical and simulation-backed resource study, not a hardware prototype. The cost table already supports the main claim: COMPAS replaces quadratic Bell-pair scaling with linear scaling in `n k`, and `teledata` wins over `telegate` once Bell-pair distillation is counted. For Fanout, Stim shows the dominant failure mode is usually a `Z` error on the shared control qubit. For `CSWAP`, Qiskit simulations show `teledata` and `telegate` are close, with `teledata` averaging about `0.84%` higher fidelity.

These component models are composed into an overall lower bound of `(1 - p_GHZ(ceil(k/2))) (1 - p_CSWAP(n))^(k-1)`. The most useful result is the network-level bound: assuming perfect local gates and a depolarizing Bell-pair-distribution channel, the total fidelity satisfies `F_tot >= (1 - 43p/4)^(O(nk))`, implying `k <= O(epsilon / (n p))` to keep total error below `epsilon`. The paper then plugs in recent distillation results and notes that with `n = 100` qubits per QPU and logical Bell-pair infidelity below about `10^-6`, the system can involve up to `k = 5` QPUs before Bell-pair noise alone exceeds `epsilon = 10^-3`.

## Novelty & Impact

Relative to _Quek et al. (Quantum '24)_, COMPAS is not a new trace-estimation objective but a distributed realization of the constant-depth multi-party SWAP test. Relative to _Ferrari et al. (IEEE TQE '21)_, it is narrower than a general compiler framework, but that specialization lets it derive exact Bell-pair, ancilla, and noise formulas. Relative to _Huggins et al. (PRX '21)_ and _Martyn et al. (Quantum '25)_, COMPAS is enabling infrastructure for virtual distillation and parallel QSP rather than a new application-level algorithm.

## Limitations

The strongest results are still resource estimates, not end-to-end demonstrations. The `teledata` versus `telegate` comparison depends on assumptions about Bell-pair distillation, and the scaling is highly sensitive to network error rates. The bound `k <= O(epsilon / (n p))` means the architecture becomes harder to scale as state width or link noise grows.

There are also scope limits. COMPAS specializes to the multi-party SWAP test and its descendants, not generic distributed quantum circuits. The analysis assumes a line topology and abstracts away full fault-tolerant overheads, heterogeneous links, and Bell-pair-generation placement.

## Related Work

- _Quek et al. (Quantum '24)_ — gives the constant-depth monolithic trace-estimation construction that COMPAS ports to distributed QPUs.
- _Ferrari et al. (IEEE TQE '21)_ — studies general distributed-quantum compilation, whereas COMPAS gives a primitive-specific resource model.
- _Huggins et al. (PRX '21)_ — uses the multi-party SWAP test for virtual distillation; COMPAS extends that subroutine to modular hardware.
- _Martyn et al. (Quantum '25)_ — motivates one application class, while COMPAS supplies the distributed trace-estimation substrate.

## My Notes

<!-- empty; left for the human reader -->

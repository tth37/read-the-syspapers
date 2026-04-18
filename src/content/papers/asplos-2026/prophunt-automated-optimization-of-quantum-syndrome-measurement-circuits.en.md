---
title: "PropHunt: Automated Optimization of Quantum Syndrome Measurement Circuits"
oneline: "Iteratively rewrites syndrome-measurement circuits by finding ambiguous hook-error subgraphs and changing CNOT orderings until logical fault paths disappear."
authors:
  - "Joshua Viszlai"
  - "Satvik Maurya"
  - "Swamit Tannu"
  - "Margaret Martonosi"
  - "Frederic T. Chong"
affiliations:
  - "University of Chicago, Department of Computer Science, Chicago, IL, USA"
  - "University of Wisconsin-Madison, Department of Computer Sciences, Madison, WI, USA"
  - "Princeton University, Department of Computer Science, Princeton, NJ, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790205"
code_url: "https://github.com/jviszlai/PropHunt"
project_url: "https://doi.org/10.5281/zenodo.17945386"
tags:
  - hardware
  - compilers
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PropHunt treats bad syndrome-measurement circuits as a decoding ambiguity problem, not a depth problem. It samples ambiguous subgraphs from the circuit-level decoding graph, solves for the minimum-weight logical fault inside each one, and locally rewrites CNOT orderings until those ambiguities disappear. On the paper's benchmarks it recovers hand-designed surface-code schedules, improves LP and RQT logical error rates by `2.5x-4x`, and also yields intermediate circuits that make Hook-ZNE `3x-6x` better than DS-ZNE in the paper's setup.

## Problem

The paper starts from a bottleneck that matters only once quantum error correction becomes real infrastructure rather than theory. A CSS code is not fully characterized by its parity-check matrices; it must also be compiled into syndrome-measurement circuits that repeatedly extract stabilizer information while errors are actively occurring inside the extraction process itself. In that regime, the order of CNOTs changes how ancilla faults propagate into hook errors, which in turn changes which physical faults are detectable, which are correctable, and ultimately what logical error rate the code achieves.

That makes standard optimization targets look misaligned. NISQ-era circuit tools optimize gate count or circuit depth because their goal is to reduce the chance that any fault occurs. For syndrome measurement, faults are expected, so the key question is how the circuit transforms them. The paper shows that both circuit depth and effective code distance are incomplete predictors: two circuits with equal or better proxy values can still have worse logical behavior, and a minimum-depth schedule can be about `10x` worse than a better-ordered one for surface codes. Existing solutions also fail to scale cleanly. Hand-designed schedules are labor intensive and code specific, brute-force search only works on heavily reduced design spaces, and prior synthesis tools optimize those same imperfect proxies. The practical problem is therefore to optimize full syndrome-measurement circuits for logical reliability without assuming a human-crafted geometric trick for every new QEC code.

## Key Insight

The central claim is that logical faults in syndrome-measurement circuits can be viewed as ambiguity. Two different fault patterns can flip the same syndromes while implying different logical outcomes. A decoder then has no reliable basis for choosing between them, so the failure probability is driven by whichever of those ambiguous explanations is less likely. In the paper's notation, ambiguity exists when two error sets produce the same `H` syndrome image but different `L` logical images.

That perspective matters because ambiguity is not fixed by the code alone. The circuit-level matrices `H` and `L` depend on how CNOTs are ordered and how syndrome qubits are relatively scheduled on shared data qubits. If a local circuit change alters error propagation so that the relevant subgraph becomes unambiguous, one logical fault pathway disappears even if the stabilizer code itself has not changed. PropHunt therefore does not try to solve the whole circuit globally from scratch. It searches for local ambiguous subgraphs, repairs those subgraphs, and repeats. The paper's surface-code example makes the idea concrete: a poor schedule creates a reduced-distance logical fault because two competing hook-error explanations look identical to the decoder, while a small CNOT-ordering change makes one syndrome bit disambiguate the logical state.

## Design

PropHunt operates on the circuit-level decoding graph, a bipartite graph whose error nodes are gate faults and whose syndrome nodes are the syndrome bits flipped by those faults. The optimization loop has five stages. First, it samples random error nodes and expands outward until the current connected subgraph satisfies `L' notin rowsp(H')`, which certifies the presence of ambiguity on that subgraph. Restricting the search to connected subgraphs matters because disconnected components cannot share one ambiguous logical fault.

Second, once an ambiguous subgraph is found, PropHunt solves for a minimum-weight logical error inside it using MaxSAT. The encoding treats syndrome parities and logical observables as hard XOR constraints over error variables, adds hard constraints that the chosen pattern is undetected yet flips at least one logical observable, and uses soft constraints to minimize the number of selected faults. The implementation simplifies the model with `Z3`, converts it to CNF, and solves it with `Loandra`. Auxiliary variables avoid the exponential blow-up of naive XOR-to-CNF conversion.

Third, PropHunt maps each implicated gate fault back to its source CNOT and enumerates local rewrites. Reordering changes move a data-qubit interaction earlier within one stabilizer so the resulting hook error lands on a different set of qubits. Rescheduling changes swap the relative order of two syndrome qubits on a shared data qubit so the fault is detected at different times. For the latter, the tool uses a directed multigraph over syndrome qubits to track ordering dependencies and preserve stabilizer commutation.

Fourth, it prunes aggressively. Candidate rewrites must still correspond to a valid schedulable syndrome-measurement circuit, and the updated local `H'` and `L'` must show that the original ambiguity is gone without merely turning the same errors into another logical fault. Finally, it applies all compatible verified rewrites, breaking conflicts by choosing the shortest-depth circuit as a secondary objective. The effect is a local-search optimizer whose target is not depth or distance directly, but the decoder ambiguity that creates actual logical failures.

## Evaluation

The evaluation is strong on the paper's stated question. The authors start from the coloration circuit of Tremblay et al. as a general CSS baseline, then run PropHunt for up to `25` iterations with `500` subgraph samples per iteration and `48` Intel Xeon Silver 4116 cores for parallel subgraph finding. Logical error rates are simulated in `Stim` under a standard circuit-level noise model for `d` rounds; surface codes use `PyMatching`, while LP and RQT codes use `BP-LSD`.

Across `[[9,1,3]]` through `[[81,1,9]]` surface codes plus one LP and three RQT codes, PropHunt improves on the baseline everywhere. For surface codes, it reaches the performance of the known hand-designed schedules, which is an important sanity check that the search is finding the same kind of structure humans discovered manually. For LP and RQT codes, where good schedules were not already known, it reduces logical error rates by `2.5x-4x` at physical error rate `0.1%`. A robustness study that starts from three random coloration circuits shows similar improvement trends instead of one lucky trajectory.

The solver analysis is also persuasive because it justifies the paper's decomposition. For `[[49,1,7]]`, a global MaxSAT formulation needs `45050` variables and takes `1 hr 55 min`, while the ambiguous-subgraph formulation needs only `340` variables and solves in `1.28 s`. On `[[60,2,6]]`, the global solve times out entirely, whereas the subgraph version remains around `1.39 s`. The idle-error study is a useful reality check: PropHunt sometimes increases circuit depth, but across a wide range of idle-error strengths the logical-error gains still dominate, especially in regimes like neutral atoms where measurement times are far longer than two-qubit gate times. Finally, Hook-ZNE uses intermediate circuits from the optimization trace to create fine-grained logical-noise scaling at fixed distance. Under the paper's randomized-benchmarking setup with a `20,000`-shot budget, it produces `3x-6x` lower bias than DS-ZNE. That last result is narrower than the main QEC result, but it does support the claim that PropHunt exposes a useful continuum of logical noise levels.

## Novelty & Impact

Relative to hand-designed schedules such as the surface-code `N-Z` ordering, PropHunt's contribution is automation across code families rather than one more clever schedule for one lattice. Relative to brute-force parameterized searches for bivariate bicycle or color-code circuits, its key move is to search locally in ambiguity-bearing subgraphs instead of enumerating a reduced global design space. Relative to QECC-Synth-style work, it optimizes the internal order of syndrome extraction rather than code-to-hardware layout compatibility.

That makes the paper important to researchers working on fault-tolerant quantum architecture, QEC compilation, and decoder-aware circuit synthesis. It is not just a measurement study, and not just a solver engineering paper. It introduces a new optimization objective, ambiguity minimization, plus a practical tool chain that turns that objective into improved syndrome-measurement circuits and an unexpected ZNE application.

## Limitations

The scope is deliberately narrower than "optimize all QEC circuits." PropHunt targets CSS codes, and its evaluation stays within surface, LP, and RQT families. The optimization procedure is also computationally heavy: it relies on repeated subgraph sampling, MaxSAT solving, and parallel CPU execution, so this is an offline synthesis tool rather than something one would run in the critical path of a compiler backend. Because the search is local and randomized, the paper does not claim global optimality.

The experimental evidence is entirely simulation based. That is reasonable for fault-tolerant QEC work, but it means the logical-error improvements still depend on the paper's noise model, decoder choices, and baseline circuit family. The idle-error analysis helps, yet hardware-specific issues such as routing, calibration drift, and platform-constrained gate sets are mostly left to future work. Hook-ZNE is even more preliminary: it is evaluated on randomized benchmarking circuits under synthetic logical-noise scaling rather than end-to-end application workloads.

## Related Work

- _Tomita and Svore (PRA '14)_ — provides the canonical hand-designed surface-code schedule that PropHunt recovers automatically instead of assuming as input.
- _Tremblay et al. (PRL '22)_ — contributes the general coloration-circuit baseline for CSS codes, and PropHunt improves that baseline by changing error propagation rather than replacing the code itself.
- _Shutty and Chamberland (Physical Review Applied '22)_ — also uses solver-backed synthesis for fault-tolerant circuits, but with flag-based constructions, whereas PropHunt avoids extra ancilla and rewrites standard syndrome-measurement circuits directly.
- _Yin et al. (ASPLOS '25)_ — QECC-Synth studies compiling QEC codes onto sparse hardware layouts, while PropHunt keeps hardware compatibility fixed and optimizes the order of syndrome extraction inside the resulting circuit.

## My Notes

<!-- empty; left for the human reader -->

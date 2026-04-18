---
title: "Reducing T Gates with Unitary Synthesis"
oneline: "trasyn makes direct U3 synthesis practical for fault-tolerant compilation, cutting T gates by avoiding the usual three-Rz detour."
authors:
  - "Tianyi Hao"
  - "Amanda Xu"
  - "Swamit Tannu"
affiliations:
  - "University of Wisconsin-Madison, Madison, WI, USA"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3779212.3790210"
code_url: "https://github.com/haoty/trasyn"
tags:
  - quantum
  - hardware
  - compilers
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

The paper argues that fault-tolerant compilers pay an avoidable `T`-gate tax because they funnel arbitrary single-qubit operations through three separate `Rz` syntheses. `trasyn` removes that detour by directly synthesizing `U3` unitaries with a tensor-network-guided search, which cuts `T` count, reduces Clifford overhead, and often improves end-to-end circuit fidelity once logical errors are taken into account.

## Problem

The bottleneck is specific to fault-tolerant quantum computing, but the systems tradeoff is easy to recognize. In a QEC-protected machine, `T` gates are much more expensive than Clifford gates because each logical `T` requires magic-state distillation, which the paper describes as roughly two orders of magnitude slower than physical-gate execution. Since many useful algorithms contain arbitrary single-qubit rotations, the compiler must approximate those rotations with the restricted gate set allowed by the code. The resulting `T` count becomes a first-order proxy for runtime and hardware cost.

The dominant workflow today is optimized for `Rz`, not for general single-qubit unitaries. Number-theoretic tools such as `gridsynth` can produce optimal or near-optimal decompositions for one `Rz` gate at a target error threshold, so practical FT toolchains first express the circuit in a Clifford+`Rz` intermediate representation and then synthesize each rotation separately. The paper's complaint is that this is algorithmically convenient but structurally wasteful: a general `U3(theta, phi, lambda)` gate is typically implemented as three `Rz` rotations with interleaved `H` gates, so the compiler spends `T` gates three times for what was originally one unitary. If the total approximation budget is fixed, each of those three syntheses may also need a tighter per-rotation threshold, which pushes the `T` count up further.

Why not just synthesize `U3` directly? Because arbitrary-unitary synthesis is much harder than `Rz` synthesis. The diagonal structure that makes `Rz` amenable to number theory disappears. Existing alternatives either search exhaustively and stop scaling past small `T` budgets, or use heuristic search that the paper says is too slow or too unreliable at the error levels relevant to early fault tolerance. The systems question is therefore not merely how to shave a few gates off one decomposition, but how to make direct arbitrary-unitary synthesis practical enough that FT compilers can switch to a better intermediate representation.

## Key Insight

The core claim is that direct `U3` synthesis becomes tractable if the compiler stops treating candidate gate sequences as a flat search space and instead encodes them as a tensor network. `trasyn` precomputes many short exact Clifford+`T` sequences, stacks the resulting matrices into tensors, and then links those tensors into a matrix product state that implicitly represents exponentially many longer candidates. Once the target unitary is attached, the same structure can evaluate trace-based closeness scores for all of those candidates without enumerating them one by one.

That matters for two reasons. First, it turns synthesis into a guided sampling problem rather than a brute-force walk through sequence space. The paper interprets trace values as a probability distribution, so high-quality candidates are sampled more often than poor ones. Second, it lets the compiler work natively on `U3`, which unlocks an upstream IR change: adjacent rotations, or rotations separated by commuting structure, can be merged before synthesis instead of being frozen into multiple `Rz` subproblems. The remembered proposition is therefore: make arbitrary-unitary synthesis scalable enough, and the real win comes both from better synthesis and from enabling a better compilation workflow.

## Design

`trasyn` has one precomputation stage and three runtime stages. In step 0, the system enumerates all unique single-qubit matrices reachable within a fixed `T` budget, modulo global phase, and stores the shortest gate sequence for each matrix. The paper reports finding `24 * (3 * 2^#T - 2)` unique matrices up to global phase, matching the known theoretical count once phase variants are ignored. This table is expensive to build, but it is a one-time cost per gate set rather than a per-compilation cost.

At compile time, step 1 constructs an MPS from those precomputed tensors. Each tensor represents many exact short sequences with a bounded `T` count. By chaining tensors along their matrix dimensions, `trasyn` builds longer candidates without explicitly materializing every product. The target unitary is attached to the ends of this chain, and a sequence of contractions plus SVDs converts the network into canonical form while implicitly performing the trace computation `Tr(U†V)` for every represented candidate `V`. The resulting MPS is essentially a compressed table of candidate quality scores.

Step 2 samples gate sequences from that table. The design borrows MPS sampling techniques and treats squared trace quality as a joint distribution over tensor indices. Because the canonical form makes the conditionals local, the compiler can sample one tensor choice at a time, project on that choice, and continue to the next tensor. The important invariant is that every sampled index corresponds to a valid precomputed subsequence, so sampling never leaves the feasible Clifford+`T` search space. The algorithm also takes many samples per pass, which makes it practical to search large spaces quickly on GPUs.

Step 3 cleans up the concatenated result. Even if each sampled chunk was locally optimal when stored in the lookup table, two adjacent chunks may create a longer subsequence that has a shorter equivalent. `trasyn` therefore scans the sampled circuit and replaces such subsequences using the same equivalence information built during precomputation. An outer loop over increasing tensor counts or `T` budgets then lets the tool solve either "best accuracy under this `T` budget" or "smallest `T` budget meeting this error threshold."

## Evaluation

The paper evaluates both the synthesizer itself and the effect on compiled applications. For single-qubit synthesis, it samples 1000 Haar-random unitaries and gives `trasyn`, `gridsynth`, and `Synthetiq` ten minutes per target. At an error threshold of `0.001`, `trasyn` achieves a geometric-mean `3.74x` reduction in `T` count and `5.73x` reduction in Clifford count relative to the three-`Rz` `gridsynth` workflow. The scatter plots also show a qualitative win: at roughly equal `T` counts, `trasyn` often attains about two orders of magnitude lower synthesis error, and at comparable error it uses around 13 fewer `T` gates. Against `Synthetiq`, the story is mostly about scale and reliability: `Synthetiq` times out on 931 of 1000 instances at threshold `0.01` and on all 1000 at `0.001`, while `trasyn` keeps finishing in seconds for most instances.

The circuit-level evaluation is what makes the paper more than a synthesis microbenchmark. Across 187 circuits drawn from FT algorithms, quantum chemistry and material simulation, Hamiltonian benchmarks, and QAOA, the `U3` workflow enabled by `trasyn` reduces `T` count by `1.39x` on average and by up to `3.5x`, while also cutting `T` depth and non-Pauli Clifford count. Gains are largest when the source circuit contains diverse rotations that can be merged into richer single-qubit unitaries; circuits dominated by `Rz` alone benefit less. The paper also compares against `BQSKit + gridsynth` and finds that numerical resynthesis tends to increase the number of rotations instead of recovering the lost FT efficiency.

The most interesting evaluation result is the fidelity tradeoff. The authors model logical errors on synthesized gates and show that minimizing synthesis error indefinitely is not the right objective for early FTQC: tighter approximation means more `T` gates, which increases exposure to logical faults. Their experiments suggest an optimal synthesis threshold that scales roughly with the square root of the logical error rate, with about `0.001` being sufficient for logical error rates between `10^-6` and `10^-7`. Under those assumptions, `trasyn` improves overall circuit infidelity by up to `4x`. That supports the paper's central claim well: lower `T` count is not just a compiler aesthetic, it can be the right end-to-end operating point for qubit-starved early FT systems.

## Novelty & Impact

Relative to _Ross and Selinger (QIC '16)_, the novelty is not another refinement of `Rz` number theory, but changing the problem formulation so the compiler can synthesize the whole single-qubit unitary directly. Relative to _Paradis et al. (PACMPL OOPSLA '24)_, the contribution is not general heuristic search over arbitrary circuits, but a tensor-guided method that is far more reliable in the single-qubit FT regime the paper targets. Relative to `U3`-blind FT workflows built around `gridsynth`, the bigger impact is architectural: once direct arbitrary-unitary synthesis is practical, the compiler can adopt an IR that preserves more merge opportunities instead of prematurely exploding one unitary into three rotations.

That makes the paper important to FT compiler designers and hardware-software co-design researchers working on the early-fault-tolerance regime. It is not proposing new error-correcting codes or a new magic-state factory. It is showing that the synthesis layer itself was leaving performance on the table, and that fixing it changes both circuit cost and the best fidelity operating point.

## Limitations

The authors are clear that `trasyn` is not an analytic method like `gridsynth`, so it does not offer arbitrarily tiny approximation error on demand. Its practical sweet spot is the error range relevant to early FTQC, and the paper explicitly frames `0.001` as a comfortable operating region on an `A100`, not a universal limit. The approach also depends on heavy one-time precomputation: enumerating unique matrices up to 15 `T` gates reportedly took days on an `A100`, which is acceptable for a fixed gate set but still a real systems cost.

Scope is another limitation. The main algorithm is only evaluated for single-qubit synthesis, even though the paper notes that extending the gate set with `CNOT` would in principle generalize the method. The logical-error study also uses a simplified depolarizing model and simulation rather than a full architecture-specific FT stack. Finally, some of the application-level gains depend on obtaining a `U3`-friendly circuit form from upstream transpilation and commutation passes, so a weaker frontend could leave part of the benefit unrealized.

## Related Work

- _Ross and Selinger (QIC '16)_ — `gridsynth` gives optimal ancilla-free Clifford+`T` synthesis for `Rz`, and this paper's main argument is that FT workflows become needlessly expensive when they force every `U3` through three such syntheses.
- _Paradis et al. (PACMPL OOPSLA '24)_ — `Synthetiq` also tackles general unitary synthesis, but the paper shows its simulated-annealing search does not scale reliably to the error thresholds targeted here.
- _Amy et al. (TCAD '13)_ — meet-in-the-middle exact synthesis also searches discrete FT circuits, but it is aimed at very small exact instances, whereas `trasyn` trades exactness for scalable approximate synthesis at much higher `T` budgets.

## My Notes

<!-- empty; left for the human reader -->

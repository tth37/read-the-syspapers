---
title: "TreeVQA: A Tree-Structured Execution Framework for Shot Reduction in Variational Quantum Algorithms"
oneline: "Clusters similar VQA tasks under a mixed Hamiltonian, then splits them only when optimization diverges to cut quantum shots by 25.9x on average."
authors:
  - "Yuewen Hou"
  - "Dhanvi Bharadwaj"
  - "Gokul Subramanian Ravi"
affiliations:
  - "Computer Science and Engineering, University of Michigan, Ann Arbor, MI, USA"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3779212.3790239"
tags:
  - quantum
  - hardware
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

TreeVQA treats a VQA application as a family of related Hamiltonians instead of a bag of independent jobs. It jointly optimizes similar tasks under a mixed Hamiltonian, branches them only when their trajectories separate, and then picks the best final state per task. Across the paper's chemistry, physics, and QAOA benchmarks, that cuts shot counts by 25.9x on average and by more than 100x in the largest or finest-grained settings.

## Problem

The paper starts from a cost structure that is brutal even before full fault tolerance arrives. One VQA task already needs many optimization iterations, many Pauli terms per Hamiltonian evaluation, and enough repeated shots to estimate expectation values at useful precision. Real applications make this worse because they need many nearby tasks: chemistry sweeps molecular geometries, physics sweeps model parameters, and QAOA-based planning varies graph weights across scenarios.

Existing work mostly attacks cost inside one task. Better initialization can reduce iterations, and measurement grouping can reduce shots within one evaluation. But those methods do not address a higher-level redundancy: neighboring tasks in one application often solve closely related Hamiltonians whose ground states evolve smoothly. Running every task independently repeats quantum work exactly where tasks are most alike.

## Key Insight

The central claim is that many VQA tasks can share a substantial optimization prefix because similar Hamiltonians induce similar ground states and, therefore, similar useful variational parameters. The paper motivates this with adiabatic continuity: when Hamiltonians change gradually and the energy gap stays open, the ground-state wavefunction also changes gradually.

TreeVQA turns that into a simple rule: optimize similar tasks together while their losses move coherently, then split only when the joint trajectory stops helping some members. To decide similarity cheaply, it pads Hamiltonians to a common Pauli-term basis, measures the L1 distance between coefficient vectors, and converts that into an RBF similarity matrix. The claim is that this proxy tracks both ground-state proximity and gradient alignment well enough to guide branching.

## Design

The framework has a global controller and one or more VQA clusters. Each cluster owns a subset of Hamiltonians plus a shared parameterized state, and it builds a mixed Hamiltonian by averaging the padded Hamiltonians in the cluster. Optimizing that mixed objective is what lets one quantum execution stand in for several related tasks.

TreeVQA begins from one cluster per unique initial state and runs a standard VQA optimizer on each cluster's mixed Hamiltonian. The paper focuses on SPSA, but later evaluates COBYLA and argues the framework is optimizer-agnostic because it only needs loss evaluations. After a warmup phase, each cluster tracks a sliding-window slope for the mixed loss and for each member Hamiltonian. A split is triggered if the mixed optimization stalls or if any member's slope turns positive.

When a split is needed, TreeVQA applies spectral clustering to the similarity matrix and partitions the cluster into two child clusters. Both children inherit the parent's parameters, so branching is a warm start rather than a restart. After the shot budget is exhausted, post-processing evaluates every original Hamiltonian on every final cluster state and chooses the lowest-energy result per task. For QAOA, the same structure is reused with multi-angle QAOA so one parameterization can cover a family of related graph instances.

## Evaluation

The evaluation is broad enough to test the paper's actual claim, not just a narrow chemistry case. The authors cover molecular VQE benchmarks (`H2`, `LiH`, `BeH2`, `HF`, and `C2H2`), two spin models (XXZ and transverse Ising), and a QAOA MaxCut workload derived from the IEEE 14-bus system. Their baseline is conventional VQA that solves each task independently, with the same per-term shot allocation used by TreeVQA.

The headline result is substantial shot reduction at fixed fidelity. The paper reports 25.9x average savings overall. One concrete example is `HF`: independent VQE needs about `1.5e11` shots to reach roughly `98%` fidelity across tasks, while TreeVQA reaches the same point with about `4e9` shots, a `34.7x` reduction. Reported savings are `38.0x` for `LiH`, `30.0x` for `BeH2`, and `43.3x` for the transverse-field model. The weaker cases are informative too: `H2` with UCCSD gains only `5.0x` because the problem is small, and XXZ gains `4.1x` because its harder landscape forces earlier splits.

The strongest evidence is that the gain grows when the hypothesis should help most. As task precision gets finer, shot savings rise from roughly `5-10x` at coarse spacing to `80-100x`, and the extrapolated finest setting exceeds `250x`. On large-scale workloads, the abstract reports more than `100x` savings. For QAOA, TreeVQA still gives more than `20x` shot reduction when graph instances are highly similar and stays above `10x` even as edge-weight variance grows. Noisy simulations on `LiH` still show `12.0x-24.8x` savings depending on backend. Taken together, the results support the paper's thesis well.

## Novelty & Impact

Relative to _Cervera-Lierta et al. (PRX Quantum '21)_, TreeVQA's novelty is architectural rather than ansatz-centric: it keeps ordinary VQA formulations and adds online clustering, branching, and post-processing instead of baking Hamiltonian parameters into one specialized circuit family. Relative to measurement-reduction work such as _Gokhale et al. (IEEE TQE '20)_, TreeVQA is orthogonal: those methods reduce the cost of one Hamiltonian evaluation, while TreeVQA reduces duplicated optimization across many Hamiltonians. Relative to classical warm-start methods such as CAFQA, TreeVQA composes with them rather than competing with them.

That makes the paper important for quantum systems researchers interested in execution frameworks, not just better ansatzes. If useful NISQ or early fault-tolerant workloads continue to come in families of nearby parameter sweeps, this kind of application-level sharing could become a standard software layer.

## Limitations

TreeVQA only helps when applications really do contain similar tasks. When Hamiltonians diverge quickly, or when phase-transition-like behavior causes optimization landscapes to change abruptly, the tree will split early and the savings shrink; the XXZ result is evidence of that boundary.

There are also methodology limits. Most evidence is from simulation rather than live hardware. The large-scale studies rely on PauliPropagation and, in some cases, compare against a baseline that does not fully catch up within the allotted budget, so exact savings on future hardware may differ. Hyperparameters such as warmup, slope window, and split threshold matter, and the paper does not give a fully automatic controller. The QAOA evaluation also uses isomorphic graphs with varying weights, which is narrower than arbitrary combinatorial workloads.

## Related Work

- _Cervera-Lierta et al. (PRX Quantum '21)_ - Meta-VQE also targets Hamiltonian families, but it encodes family parameters into a specialized ansatz instead of branching execution online.
- _Grimsley et al. (Nature Communications '19)_ - ADAPT-VQE reduces circuit and measurement cost for one problem instance, whereas TreeVQA targets duplicated work across many related instances.
- _Gokhale et al. (IEEE TQE '20)_ - measurement grouping lowers the per-evaluation cost of VQE, while TreeVQA is orthogonal because it shares optimization across tasks.
- _Bhattacharyya and Ravi (ICRC '23)_ - classical initialization improves starting points for individual Hamiltonians, and TreeVQA builds on that style of warm start rather than replacing it.

## My Notes

<!-- empty; left for the human reader -->

---
title: "CHEHAB RL: Learning to Optimize Fully Homomorphic Encryption Computations"
oneline: "Uses reinforcement learning to choose FHE rewrite sequences that vectorize scalar circuits with fewer rotations, lower noise, and much lower compile time than Coyote."
authors:
  - "Bilel Sefsaf"
  - "Abderraouf Dandani"
  - "Abdessamed Seddiki"
  - "Arab Mohammed"
  - "Eduardo Chielle"
  - "Michail Maniatakos"
  - "Riyadh Baghdadi"
affiliations:
  - "New York University Abu Dhabi, Abu Dhabi, United Arab Emirates"
  - "Ecole Superieure d'Informatique, Algiers, Algeria"
  - "Center for Cyber Security, New York University Abu Dhabi, Abu Dhabi, United Arab Emirates"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790138"
code_url: "https://github.com/Modern-Compilers-Lab/CHEHAB"
tags:
  - security
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CHEHAB RL treats FHE optimization as sequential decision making over rewrite rules instead of heuristic or solver-driven search. A learned policy chooses which rewrite to apply and where, producing vectorized BFV circuits that are typically faster, shallower, and less noisy than Coyote while compiling much more quickly.

## Problem

A good FHE compiler must not only vectorize scalar code, but do so while controlling packing layout, rotations, circuit depth, and multiplicative depth, because those choices determine both latency and whether the circuit stays within its noise budget.

Prior systems only partially solve this. HECO and CHET mostly target structured programs, while Coyote and Porcupine support unstructured code but frame optimization as expensive search over packings and layouts. CHEHAB RL instead treats optimization as sequential decision making: learn how to compose rewrites directly, rather than re-solving a large combinatorial problem for every program.

## Key Insight

The key claim is that FHE vectorization can be learned as a rewrite policy if the state representation normalizes away irrelevant syntax and the reward captures FHE-specific costs. Instead of searching from scratch for each program, CHEHAB RL incrementally rewrites the IR toward a single global objective that proxies runtime and noise. That matters because FHE programs have strong long-range dependencies: an early commutativity or factoring rewrite may look locally unimportant, but it can unlock a much better packing and depth profile later. RL is used here to learn those delayed trade-offs.

## Design

CHEHAB itself is a full FHE compiler, but the paper's contribution is the optimization stage: an actor-critic term rewriting system inserted between IR construction and SEAL code generation. The rewrite system contains 84 rules plus `END`, covering both vectorization and algebraic simplification.

The state representation uses Identifier and Constant Invariant tokenization, which canonicalizes variable names and most constants so equivalent-looking programs map to the same token sequence. A 4-layer Transformer with 8 attention heads then produces a 256-dimensional embedding. Action selection is hierarchical: one network chooses the rewrite rule, and a second chooses which matched location in the IR should receive it.

The reward model is explicitly FHE-aware. It adds operation cost, circuit depth, and multiplicative depth, with vector additions priced at `1`, vector multiplications at `100`, rotations at `50`, and scalar operations at `250`. Training combines step rewards with a terminal reward so the policy does not get stuck optimizing only short-horizon improvements. Since no public FHE optimization corpus exists, the authors synthesize one with Gemini 2.5 Flash, then parse, deduplicate, and benchmark-filter it down to `15,855` unique expressions.

## Evaluation

The evaluation uses a Xeon E5-2680 v4 CPU server, BFV with `n = 16384`, and SEAL 4.1 across Porcupine kernels, Coyote kernels, and random polynomial trees. The experimental comparison is mainly against Coyote because Porcupine was unavailable. To isolate the optimization algorithm, the authors disable blocking in both compilers and disable CHEHAB's automatic rotation-key selection.

The headline results are compelling: CHEHAB RL produces circuits that run `5.3x` faster on geometric mean, compile `27.9x` faster, and consume `2.54x` less noise budget than Coyote. On `Poly. Reg. 32`, it is `50x` faster; on `Linear Reg. 32`, `114x` faster. The win comes from much smaller circuits with far fewer rotations and ciphertext-plaintext multiplications. The noise results support the same story: some Coyote outputs exhaust the budget on `Sort 4` and tree benchmarks, while CHEHAB RL still yields executable circuits. The ablations are also useful: LLM-generated training data clearly beats random data, step-plus-terminal reward beats step-only reward by `1.291x`, and ICI tokenization cuts training time from `68` to `43` hours for the same `2` million PPO steps. The main exception is `Tree 50-50-10`, where Coyote wins by using fewer ciphertext-ciphertext multiplications.

## Novelty & Impact

Relative to _Malik et al. (ASPLOS '23)_, the novelty is not a nicer heuristic inside the same search loop, but replacing the loop with an offline-learned rewrite policy. Relative to _Cowan et al. (PLDI '21)_, it keeps the structured-plus-unstructured ambition while pushing harder on automatic layout and scalability. Relative to _Dathathri et al. (PLDI '19)_ and _Viand et al. (USENIX Security '22)_, it moves FHE compilation beyond structured kernels. The broader impact is the idea of amortizing FHE optimization effort across many programs rather than paying a large search cost on every compile.

## Limitations

The scope is still fairly narrow. The backend is BFV on CPU through SEAL, so transfer to CKKS, GPUs, or other FHE libraries is unproven. The reward is based on an analytical cost model, not direct execution-time feedback. Experimentally, the paper compares mainly to Coyote because Porcupine was unavailable, and it disables blocking plus CHEHAB's automatic rotation-key selection for fairness. The main evaluation also moves input-layout transformation to the client before encryption, which is practical but shifts some work outside the server-side compiler.

## Related Work

- _Malik et al. (ASPLOS '23)_ - Coyote vectorizes encrypted arithmetic circuits with heuristic plus ILP-guided search, while CHEHAB RL replaces search-heavy optimization with a learned rewrite policy.
- _Cowan et al. (PLDI '21)_ - Porcupine also targets vectorized homomorphic encryption for structured and unstructured code, but CHEHAB RL positions itself as more scalable and more automatic about data layout.
- _Dathathri et al. (PLDI '19)_ - CHET focuses on optimizing homomorphic neural-network inference over structured tensor programs, whereas CHEHAB RL targets general arithmetic circuits including unstructured ones.
- _Viand et al. (USENIX Security '22)_ - HECO compiles structured FHE programs into vectorized code, while CHEHAB RL extends the optimization problem to arbitrary unstructured expressions and RL-guided rewrite sequencing.

## My Notes

<!-- empty; left for the human reader -->

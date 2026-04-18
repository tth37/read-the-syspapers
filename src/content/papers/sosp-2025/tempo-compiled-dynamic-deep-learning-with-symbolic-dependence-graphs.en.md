---
title: "Tempo: Compiled Dynamic Deep Learning with Symbolic Dependence Graphs"
oneline: "Tempo makes time an explicit tensor dimension, compiles symbolic cross-timestep dependencies, and jointly schedules execution and memory for dynamic LLM and RL workloads."
authors:
  - "Pedro F. Silvestre"
  - "Peter Pietzuch"
affiliations:
  - "Imperial College London"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764840"
code_url: "https://github.com/LSDS/Tempo"
tags:
  - ml-systems
  - compilers
  - gpu
  - scheduling
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Tempo is a deep-learning system for programs whose tensor dependencies vary across timesteps. It introduces recurrent tensors and symbolic dependence graphs so that dynamic attention, RL return computation, and similar patterns can still be optimized, tiled, scheduled, and memory-managed as one whole program. On a single RTX A6000, it reports up to 7x faster Llama-3.2-3B decoding than JAX and up to 54x faster RL training than existing frameworks, while cutting peak GPU memory by up to 16x.

## Problem

The paper targets a gap between the two dominant styles of DL execution. Eager systems such as PyTorch can express time-varying dependencies naturally in Python, but because the real computation only materializes at runtime, they cannot do whole-program optimization or schedule memory globally. Graph systems such as JAX and TensorFlow compile aggressively, but their graphs fundamentally assume static tensor shapes. As soon as a timestep depends on a dynamic prefix, window, or suffix of earlier tensors, users end up padding to a worst-case bound, masking invalid elements, or breaking the program into multiple static graphs.

That mismatch hurts real workloads. In autoregressive decoding, attention at step `t` reads a dynamic range of prior key/value pairs, which makes K/V cache management both algorithm-specific and difficult to optimize. In reinforcement learning, forward-looking or anti-causal loss terms force mainstream frameworks into actor-learner decompositions: the actor generates trajectories, the learner later replays them. The paper argues that this causes three concrete pathologies: duplicated forward computation, forced serialization between acting and learning, and excessive GPU memory demand from storing or replaying long trajectories.

## Key Insight

Tempo's central insight is that these "dynamic" programs become regular once time is promoted to a first-class tensor dimension. Instead of hiding timestep structure inside Python loops or opaque control flow, Tempo represents tensors as recurrent tensors whose domains explicitly include temporal axes such as timestep, iteration, or batch episode. Dependencies on past or future values are then just symbolic index expressions over those temporal dimensions.

Once those symbolic expressions are explicit, Tempo can build a symbolic dependence graph (SDG) that records, for every operator, where in time it executes and which symbolic slice of another operator it needs. This is the proposition the paper wants readers to remember: dynamic DL is not fundamentally beyond compilation; it is compilable if the compiler models symbolic temporal dependence directly instead of pretending every tensor is statically shaped.

## Design

The programming model is the recurrent tensor. RTs extend ordinary tensors with temporal domains, automatic domain inference, symbolic shapes, and symbolic indexing. They also support symbolic automatic differentiation: if one timestep of `x` contributes to multiple timesteps of `y`, Tempo inverts the dependence expression so gradients can be accumulated back onto the correct temporal slice of `x`. That lets the user write RL-style losses over future rewards without splitting the program into separate actor and learner graphs.

Tempo lowers RT code into an SDG. Each operator carries a temporal domain, and each edge carries a symbolic dependence expression. Branching is represented through `MergeOp`s, while model state such as optimizer parameters is encoded through graph cycles rather than special mutable variables. This gives Tempo a graph where state, control, and temporal dependence are all explicit enough to transform.

The optimizer then applies four key transformations. First, it performs symbolic algebraic simplifications and domain reduction. Second, it lifts recurrent patterns such as reductions, scans, and stencils into batch operators that are easier to optimize. Third, it vectorizes along temporal dimensions by moving time into space, which increases SIMD-style parallelism but may inflate memory. Fourth, when vectorization would create overly large tensors, it tiles a chosen spatial dimension back into a new temporal tile dimension. For causal attention, this turns one dynamic-length operation into a dynamic number of fixed-size tiles, so Tempo can reuse existing static code generators and only pad the final tile instead of the whole sequence. Finally, it fuses static islands into a single dataflow operator to reduce dispatch and simplify scheduling.

Scheduling is where the system becomes unusual. Because future dependencies mean topological sorting is not enough, Tempo uses the polyhedral model to solve an integer linear program over the SDG. The scheduler adds validity constraints from dependencies and proximity constraints to encourage locality. After it finds a schedule, Tempo augments the same graph with explicit memory operations for deallocation, GPU/CPU swap-out and swap-in, and buffer donation, then schedules those too. The output is an imperative AST that the runtime interprets against JAX or Torch backends. At runtime, Tempo stores tensors in point, block, or window stores depending on their access pattern, and wraps generated kernels so they can read from and write into those stores without needless copies.

## Evaluation

The evaluation is broad for a systems paper, but still clearly single-node and single-GPU. On Llama-3.2-3B decoding with an RTX A6000, Tempo is consistently better than eager Torch because it gets compiler optimizations, and it pulls ahead of JAX once JAX's whole-sequence padding becomes expensive. With causal attention at batch size 4, Tempo is 2.0x faster than JAX at 32,768 decoded tokens and 2.5x faster at 65,536. With window attention at batch size 16, Tempo reaches up to 3.9x over Torch and 7x over JAX at 16,384 tokens, and it is the only system that actually changes memory behavior to match the window dependency by deallocating old K/Vs and using a circular store.

The RL results are more dramatic. Against SampleFactory, RLGames, CleanRL, and RLlib on PPO, REINFORCE, and `n`-step return variants, Tempo is up to 54x faster than RLlib and on average 2.6x faster than the next-fastest baseline in the small-to-medium PPO study. The reason is consistent with the paper's thesis: Tempo keeps a whole-program view, reuses actor activations instead of recomputing them in the learner, vectorizes across timesteps, and schedules learning according to the real dependence pattern. For large image observations, the baselines hit OOM because they stage whole trajectories in actor-learner form, while Tempo scales to `3x256x256` observations by combining tiling with CPU/GPU swapping. Compilation time also stays roughly flat at about 18 seconds as transformer depth increases, because repeated layer structure is encoded through temporal dimensions rather than duplicated graph structure.

The evaluation supports the paper's main claim for workloads with regular temporal structure. The main caveat is that the RL environment is deliberately chosen to expose framework overhead, and the evidence is entirely on one RTX A6000 rather than across multiple GPU generations or distributed settings.

## Novelty & Impact

The paper's novelty is not merely "dynamic shapes for DL." Several prior systems already move in that direction. Tempo's distinctive move is to make symbolic temporal dependence the compiler's primary abstraction, then use that abstraction all the way down: symbolic autodiff, vectorization, static tiling of dynamic programs, polyhedral scheduling, and memory planning all operate on the same SDG.

That is why the work matters. For compiler researchers, it shows a credible path from recurrence-equation structure to practical DL execution. For systems people building LLM or RL runtimes, it offers a cleaner alternative to manually engineered K/V cache policies and actor-learner pipelines. Even if Tempo itself stays a research prototype, the paper is likely to be cited for the idea that dynamic DL should be compiled as a temporally indexed whole program, not approximated by padding and masks.

## Limitations

The authors are explicit that Tempo is still a prototype with scope limits. It is single-GPU only today; the discussion sketches possible distributed extensions, but none are implemented. It also does not yet support dynamic termination of temporal dimensions, so truly runtime-determined loop bounds remain future work.

Several practical policies are also immature. Tile size is user-chosen rather than auto-tuned, swapping decisions are not latency-aware, and the runtime still pays Python-level AST interpretation overhead on smaller models. The system also lacks first-class support for hand-optimized kernels such as FlashAttention, which matters because modern LLM stacks rely heavily on such kernels. Finally, although the results are convincing on Llama decoding and selected RL algorithms, the evidence for broader generality across architectures, multi-GPU training, and production serving stacks is still limited.

## Related Work

- _Ansel et al. (ASPLOS '24)_ — PyTorch 2 speculatively compiles dynamic Python with symbolic shapes, but Tempo goes after symbolic cross-timestep dependencies and whole-program scheduling rather than mostly dynamic-shape capture.
- _Lai et al. (ASPLOS '25)_ — Relax provides composable abstractions for dynamic ML compilation, whereas Tempo's focus is the narrower but harder case of dynamic temporal dependencies with integrated scheduling and memory planning.
- _Vasilache et al. (arXiv '18)_ — Tensor Comprehensions uses the polyhedral model for kernel-level tensor optimization, while Tempo uses polyhedral scheduling at whole-program scope across timesteps.
- _Rhu et al. (MICRO '16)_ — vDNN reduces training memory pressure with swapping, but Tempo derives deallocation and swap points from explicit dependence-aware schedules instead of treating memory management as a separate subsystem.

## My Notes

<!-- empty; left for the human reader -->

---
title: "It Takes Two to Entangle"
oneline: "Checks distributed ML implementations by proving sequential outputs can be cleanly reconstructed from distributed ones via iterative per-operator rewriting."
authors:
  - "Zhanghan Wang"
  - "Ding Ding"
  - "Hang Zhu"
  - "Haibin Lin"
  - "Aurojit Panda"
affiliations:
  - "New York University, New York, NY, United States"
  - "ByteDance Seed, Bellevue, WA, United States"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790178"
tags:
  - verification
  - formal-methods
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Entangle checks whether a distributed ML implementation refines its sequential specification, not by requiring identical outputs, but by asking whether the sequential outputs can be reconstructed from distributed outputs using only clean rearrangement and reduction operations. Its key move is to verify one sequential operator at a time with iterative rewriting over computation graphs, which keeps the search tractable while still producing bug-localizing failures. On real GPT-, Qwen2-, and Llama-3-based implementations, it reproduces nine real bugs and keeps verification time in the tens to low hundreds of seconds.

## Problem

The paper targets a very practical failure mode in modern ML systems. Large models are usually designed as sequential programs, then rewritten by implementers into tensor-parallel, sequence-parallel, expert-parallel, or otherwise distributed versions that actually fit across many GPUs. That translation inserts communication, slicing, padding, aggregation, and layout-conversion steps. A single wrong offset, scale factor, or missing collective can silently change semantics even though shapes and types still look fine.

The motivating examples are representative rather than exotic. ByteDance engineers saw an MoE auxiliary loss left unscaled under tensor parallelism, which made the loss `T` times too large after reduce-scatter. They also saw an MoE configuration bug where sequence parallelism was enabled but expert weights remained sharded instead of replicated, so the implementation computed only diagonal blocks of the intended matrix product. These are exactly the sorts of bugs that are expensive to notice late, because they may not crash and may only surface as degraded convergence or wrong model behavior.

The obvious correctness checks are unsatisfying. Runtime testing and fuzzing scale, but they do not prove correctness. Whole-graph equivalence checking is closer to what users want, but exact equality is too strong for distributed implementations whose outputs often differ in layout and need recombination, and generic SMT/EGraph approaches struggle to scale to present-day model graphs. The paper therefore asks for a middle ground: can we statically prove that the distributed model still computes the sequential one, while allowing the benign communication and rearrangement steps that distribution naturally introduces?

## Key Insight

The central claim is that correctness for distributed ML should be phrased as **model refinement**, not literal equality. A distributed implementation `G_d` is correct if the sequential model's outputs `G_s` can be recovered from `G_d`'s outputs using only "clean" expressions: tensor rearrangements such as slice, concat, or transpose, plus collective reductions such as sums. If reconstruction requires additional semantic computation, something important was lost during distribution.

That formulation matters because it exposes structure that the verifier can exploit. Programmers usually derive `G_d` from `G_s` by distributing one operator at a time while preserving the original operator order. Under that assumption, Entangle can process `G_s` in topological order and prove refinement operator by operator instead of exploring the full cross-product of two whole graphs. The paper argues this keeps soundness, because every successful step returns an explicit relation that acts as a certificate, while giving much better scalability and more useful failure locations.

## Design

Users provide Entangle with computation graphs for the sequential model `G_s`, the distributed implementation `G_d`, and a clean input relation that explains how sequential inputs map to distributed inputs. Entangle's job is to synthesize a complete clean output relation: for every output tensor of `G_s`, find an expression over `G_d`'s outputs that reconstructs it.

The algorithm is iterative. For each operator `v` in `G_s`, Entangle first rewrites `v`'s output expression using the current relation from already-mapped tensors in `G_s` to tensors in `G_d`. It then applies rewrite lemmas to generate equivalent expressions. These lemmas capture algebraic properties and distribution-aware identities for ATen operators and for optimized kernels when users add custom rules. Finally, it rewrites subexpressions back into tensors present in `G_d`, filters for clean expressions, and records the resulting relation `R_v`. If no clean mapping exists for some output of `v`, Entangle stops and reports that operator, which becomes the main bug-localization signal.

The engineering trick is how it avoids drowning in rewrites. Entangle uses `egg` EGraphs for saturation, but it also restricts graph exploration to tensors related to the current sequential operator's inputs or outputs. It grows this relevant set iteratively, rather than building one global relation over all of `G_d`. The tool also constrains "explosive" lemmas such as reshape and slice/concat rewrites, and keeps only the simplest representative among equivalent expressions. The result is a workflow that remains sound but is intentionally not complete: fused kernels, reordered operators, or mismatched optimizations between `G_s` and `G_d` can trigger false alarms because they violate the assumptions that make the iterative proof feasible.

The implementation combines about `9000` lines of Python with about `7800` lines of Rust, including roughly `4100` lines for ATen lemmas and validation. For PyTorch models the authors capture graphs with TorchDynamo; for NeuronX/HLO they add a translation utility. They also extend the system to check user-specified expectations about a particular refinement function, not just the existence of some refinement.

## Evaluation

The evaluation asks four questions: whether Entangle finds real bugs and localizes them, how long verification takes, how it scales with model size and parallelism degree, and how much manual effort new operators require. Experiments run on CloudLab nodes with 16-core AMD EPYC 7302P CPUs and 128 GB RAM. The workloads span a proprietary ByteDance model using TP, SP, and EP; Megatron-LM GPT-2; vLLM Qwen2; a HuggingFace regression model using gradient accumulation; and a NeuronX/HLO Llama-3 setup.

On the bug-finding side, Entangle reproduces nine real-world bugs: five from ByteDance and four from open-source systems. One of the ByteDance bugs was found by Entangle itself, while the others had been independently identified earlier. The reported bugs include wrong RoPE offsets under sequence parallelism, missing all-reduce steps in Megatron-LM and TransformerEngine, missing aggregation of a layernorm weight, and the auxiliary-loss scaling error used as a motivating example. The important systems point is not just that Entangle says "verification failed," but that it fails at the first unmappable operator and exposes the relevant input relations and earlier operators, which narrows debugging scope.

For end-to-end verification, the paper reports that the HuggingFace test case finishes in less than a second and that the remaining evaluated models finish in under two minutes when checked at parallelism size `2` on a single layer. In the broader scalability study over GPT and Llama-3, verification ranges from about `10` to `245` seconds while remaining practical up to degree `8` parallelism. Increasing graph width via higher parallelism hurts more than increasing depth via repeated layers, but the tool still stays within "developer waiting time" rather than "overnight job" territory.

The usability story is also credible. Models outside the built-in ATen subset need additional lemmas, but the paper argues the burden is small: only a small number of new lemmas per model, usually under `40` lines of code each, and most are structurally simple. The most commonly used lemmas are for clean operators such as `slice` and `concat`, which matches the paper's thesis that distributed correctness mostly hinges on layout rearrangement and aggregation rather than on re-proving arbitrary numeric kernels.

## Novelty & Impact

Relative to _Jia et al. (SOSP '19)_, Entangle is not trying to optimize tensor graphs; it borrows rewriting machinery but repurposes it for verification of distributed implementations. Relative to _Yang et al. (POPL '21)_, its contribution is not generic equality saturation, but a refinement formulation with a restricted class of clean reconstructions and an iterative proof strategy that scales to large ML models. Relative to _Arora et al. (POPL '25)_, it is less about proving local graph rewrites correct and more about validating the whole hand-written or compiler-generated distribution boundary. Relative to _Zulkifli et al. (EuroMLSys '25)_, the paper emphasizes soundness and a weaker, more deployment-relevant notion of equivalence: distributed outputs may differ from sequential ones as long as they can be cleanly reassembled.

That makes the paper interesting to both formal-methods researchers and practitioners building distributed training or inference stacks. The biggest contribution is not a new theorem in isolation, but a usable verification contract for parallelized ML implementations: ask for clean reconstructability, prove it one operator at a time, and return failures in a form engineers can act on.

## Limitations

The authors are explicit that Entangle is sound but not complete. If it proves refinement, the returned relation is a certificate. But it can also reject a correct implementation when its assumptions do not hold. The main assumptions are that `G_s` and `G_d` apply the same optimizations, preserve operator order, and keep each relevant distributed operator connected to the sequential operator's inputs or outputs. Kernel fusion or aggressive graph rewrites can therefore fall outside its comfort zone.

There are also practical adoption constraints. Users must provide the clean input relation, and models with custom or hardware-specific operators need extra lemmas. Some popular strategies, notably data parallelism and pipeline parallelism, were not evaluated because TorchDynamo could not expose the needed graph structure. Likewise, most experiments only verify the forward pass, with the full forward-plus-backward treatment demonstrated only for the proprietary ByteDance model after extra manual relation work. So the paper shows a strong path for pre-deployment checking, but not a push-button verifier for every training stack today.

## Related Work

- _Jia et al. (SOSP '19)_ — TASO verifies and searches tensor-graph rewrites for optimization, whereas Entangle verifies that a distributed implementation still refines the original sequential model.
- _Yang et al. (POPL '21)_ — Tensat contributes EGraph-based equality saturation, but Entangle adds the clean-reconstruction objective and per-operator iterative search needed for distributed-model checking.
- _Arora et al. (POPL '25)_ — TensorRight proves tensor-graph rewrites correct, while Entangle targets bugs introduced by parallelization strategies such as TP, SP, and EP.
- _Zulkifli et al. (EuroMLSys '25)_ — Aerify is close in spirit, but it seeks semantic equality, whereas Entangle accepts layout-different distributed outputs so long as they can be cleanly mapped back.

## My Notes

<!-- empty; left for the human reader -->

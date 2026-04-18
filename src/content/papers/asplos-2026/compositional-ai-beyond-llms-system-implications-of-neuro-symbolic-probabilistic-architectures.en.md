---
title: "Compositional AI Beyond LLMs: System Implications of Neuro-Symbolic-Probabilistic Architectures"
oneline: "Treats neuro-symbolic-probabilistic AI as a systems workload, showing why symbolic and probabilistic kernels break current hardware assumptions and how to optimize them."
authors:
  - "Zishen Wan"
  - "Hanchen Yang"
  - "Jiayi Qian"
  - "Ritik Raj"
  - "Joongun Park"
  - "Chenyu Wang"
  - "Arijit Raychowdhury"
  - "Tushar Krishna"
affiliations:
  - "Georgia Institute of Technology, Atlanta, GA, USA"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3760250.3762235"
tags:
  - ml-systems
  - gpu
  - hardware
reading_status: read
star: true
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

This paper studies neuro-symbolic-probabilistic AI as a first-class systems workload rather than "an LLM with some glue code." It shows that symbolic and probabilistic stages often dominate latency on current CPU/GPU platforms, then maps those bottlenecks to a practical toolbox of scheduling, mapping, circuit, compression, and precision optimizations.

## Problem

The paper starts from a clear mismatch between algorithm design and machine design. Recent systems such as AlphaGeometry, R2-Guard, BTProp, Ctrl-G, CoELA, COMBO, and ReST-MCTS improve reasoning by combining LLMs with symbolic search, logic, hidden Markov models, probabilistic circuits, or Monte Carlo inference. That modularity can beat monolithic LLMs on accuracy, robustness, and data efficiency, but the underlying hardware stack is still tuned for dense tensor algebra. GPUs excel at `MatMul` and attention, not irregular tree traversal, first-order logic, sparse probability updates, or multi-stage orchestration. The missing piece is therefore a systems-level answer to a simple question: once reasoning moves beyond a single dense model, what actually limits performance?

## Key Insight

The central proposition is that compositional AI creates heterogeneous critical paths, and those paths are dominated by symbolic/probabilistic behavior rather than neural throughput. The same modules that improve reasoning also introduce low arithmetic intensity, poor cache locality, serialized control flow, and expensive CPU-GPU transfers. Once the paper treats those pieces as first-class kernels, the optimization story becomes clearer: different composition patterns fail for different reasons, so bottleneck diagnosis has to precede tuning.

## Design

The paper is a characterization-and-optimization framework, not one monolithic runtime. It first defines five composition styles, from pipelined `LLM|Symbolic|Probabilistic` systems to LLM-driven tree-search systems with repeated calls. It then profiles seven representative workloads on H100/H200 GPUs and Sapphire Rapids CPUs, collecting latency breakdowns, operator mixes, roofline positions, cache behavior, DRAM bandwidth, dataflow dependencies, memory traces, and multi-node scaling. Across workloads, neural kernels stay close to the hardware sweet spot, while symbolic and probabilistic kernels are dominated by element-wise work, sparse state updates, branching, and data movement.

The optimization toolbox mirrors that diagnosis. Parallel node expansion attacks serialized LLM orchestration. Flexible LLM mapping routes easy modules to small local LoRA-tuned models. Pipeline scheduling overlaps LLM stages with symbolic/probabilistic work using adaptive batching. Probabilistic circuit optimization factorizes and deduplicates sum-product expressions. Model compression uses quantization plus pruning on large HMM-style kernels. Mixed-precision symbolic sampling lowers the cost of MCMC-style support modules while keeping statistical quality stable.

## Evaluation

The evaluation first justifies why these workloads matter. In the paper's scaling study, compositional systems outperform monolithic LLMs across several reasoning task families. For AlphaGeometry, the authors report harder IMO-style problems solved with `2-3x` lower latency and lower energy than RL-based chain-of-thought reasoning. That evidence is partly aggregated from workload results rather than one fully controlled harness, but it supports the motivation.

The characterization data are more direct and more persuasive. Symbolic and probabilistic stages consume disproportionate wall-clock time despite modest FLOP shares. On BTProp, they account for `29%` and `24%` of runtime on H100 while contributing only `13%` and `15%` of total FLOPs. Ctrl-G still needs `89s` for a text-infilling task, and BTProp takes `91s` for hallucination detection, so simply accelerating the LLM would not fix the user-visible latency. Roofline, cache, and bandwidth results line up with that diagnosis: these kernels are memory-bound and poorly matched to current accelerators.

The optimization results are large but intentionally workload-specific. Parallel node expansion speeds ReST-MCTS by `1.47x`. Flexible model mapping cuts latency by `3.7x` on CoELA and `2.9x` on BTProp with under `1%` accuracy loss. Pipeline scheduling raises throughput by `2.7x` on AlphaGeometry and `3.3x` on Ctrl-G. Probabilistic circuit optimization gives `18.8x`, `23.4x`, and `20.3x` speedups on R2-Guard, BTProp, and Ctrl-G. Compression shrinks Ctrl-G's HMM by `52.6x` with `1%` accuracy loss, and mixed-precision symbolic sampling adds `2.4x-3.8x` speedups with at most `0.4%` accuracy drop. When combined where applicable, latency falls by `50-70%`, including `34s` to `11s` on AlphaGeometry and `121s` to `39s` on R2-Guard.

## Novelty & Impact

Relative to earlier profiling papers, the novelty is the cross-layer view: taxonomy, measurement, and optimization guidance for compositional neuro-symbolic-probabilistic systems as a class. Relative to accelerator papers such as CogSys, the paper supplies the empirical case for which kernels need help. Relative to software systems such as Lobster or Dolphin, it is broader and less tied to one runtime. The likely impact is on architects and ML-systems builders who need to treat symbolic/probabilistic stages as first-class performance citizens instead of assuming the LLM dominates everything.

## Limitations

The breadth of the paper is also its main limit. The seven workloads are representative rather than exhaustive, and several are research prototypes instead of production services. The comparison against monolithic LLMs is partly literature-driven, so it is better as directional evidence than as a strict apples-to-apples benchmark. The optimization toolbox is also manual: each technique targets one bottleneck on one subset of workloads, and the paper does not offer a unified runtime that decides automatically when to pipeline, remap, compress, or offload. The multi-node results similarly diagnose poor scaling for symbolic/probabilistic kernels without fully solving it.

## Related Work

- _Wan et al. (ISPASS '24)_ — characterizes neuro-symbolic AI workloads, while this paper extends the scope to neuro-symbolic-probabilistic systems and adds a broader optimization toolbox.
- _Naik et al. (arXiv '24)_ — Dolphin studies CPU/GPU partitioning for neurosymbolic learning; this paper generalizes that placement question across multiple composition patterns and workload types.
- _Biberstein et al. (arXiv '25)_ — Lobster accelerates one neurosymbolic programming stack on GPUs, whereas this paper is a cross-workload measurement study rather than a single-language runtime.
- _Wan et al. (HPCA '25)_ — CogSys co-designs hardware for efficient neurosymbolic cognition; this paper provides the workload evidence and bottleneck analysis that motivate such co-design.

## My Notes

<!-- empty; left for the human reader -->

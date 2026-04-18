---
title: "Streaming Tensor Programs: A Streaming Abstraction for Dynamic Parallelism"
oneline: "STeP makes dynamic tensor shapes and control flow first-class on spatial dataflow accelerators, unlocking dynamic tiling, expert time-multiplexing, and load-balanced attention."
authors:
  - "Gina Sohn"
  - "Genghan Zhang"
  - "Konstantin Hossfeld"
  - "Jungwoo Kim"
  - "Nathan Sobotka"
  - "Nathan Zhang"
  - "Olivia Hsu"
  - "Kunle Olukotun"
affiliations:
  - "Stanford University"
  - "SambaNova Systems"
  - "Carnegie Mellon University"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790229"
tags:
  - hardware
  - compilers
  - pl-systems
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

STeP is a programming abstraction for spatial dataflow accelerators that makes dynamic tensor shapes and data-dependent control flow explicit instead of hiding them behind static padding or scalar-only control. By combining symbolic stream-shape semantics, explicit memory operators, and dynamic routing/merging operators, it can express dynamic tiling, configuration time-multiplexing, and dynamic parallelization; in simulation, those ideas deliver Pareto improvements of `1.33x-2.11x` and end-to-end speedups up to `1.27x`.

## Problem

The paper starts from a mismatch between modern ML workloads and SDA software abstractions. MoE routing, ragged sequence lengths, and runtime-varying batch composition produce dynamic tensor shapes and control flow, yet most accelerator abstractions still assume mostly static programs. Imperative systems such as Spatial and Revet expose memory hierarchy, but dynamic behavior is restricted, statically sized, or scalar-only. Streaming systems such as StreamIt, SAM, and Ripple better match asynchronous execution, but they either assume fixed rates, target sparse tensor algebra, or leave the memory hierarchy implicit.

That gap matters because the interesting optimizations are scheduling choices. The programmer wants to choose tile sizes from the number of rows routed to each expert, reuse one configured region across multiple experts, or dispatch attention work to whichever parallel pipeline becomes free first. Prior abstractions can often encode the final computation, but not the runtime-dependent schedule decisions that determine off-chip traffic, on-chip memory use, and parallelism.

## Key Insight

The key claim is that dynamic tensor programs can still be represented as streams with enough structure for optimization, provided the abstraction exposes symbolic shape information, explicit memory placement, and first-class routing. In STeP, each stream has a compile-time rank and data type, but dimensions may be static, dynamic-regular, or ragged, and stop tokens encode the tensor structure inside the stream.

Once those properties are visible, dynamic behavior becomes analyzable rather than opaque. The programmer can ask how much on-chip memory a schedule needs, how much off-chip traffic a control-flow pattern causes, or what tile shape should be formed at runtime. The paper's broader point is that dynamic optimization on SDAs does not require abandoning the stream abstraction; it requires making the stream semantics rich enough to carry runtime structure.

## Design

STeP's data types include tiles, selector vectors, on-chip-memory references, and tuples. Its operators fall into five groups: off-chip memory operators such as `LinearOffChipLoad` and `RandomOffChipLoad`; on-chip operators such as `Bufferize` and `Streamify`; routing operators such as `Partition`, `Reassemble`, and `EagerMerge`; higher-order operators such as `Accum`, `Map`, and `FlatMap`; and shape operators such as `Flatten`, `Reshape`, `Promote`, `Expand`, and `Zip`.

The simplified MoE example shows how these pieces compose. `Partition` routes token rows to experts and creates symbolic stream sizes `[D_i, 1]`. `Flatten`, `Reshape`, and `Accum` then pack multiple `[1,64]` tiles into `[4,64]` tiles so the expert kernel runs as matrix-matrix rather than repeated matrix-vector work. A `LinearOffChipLoadRef` uses `ceil(D_i / 4)` to fetch weights the right number of times, and `Reassemble` restores output order. Around this abstraction, the paper builds a symbolic Python frontend that derives off-chip-traffic and on-chip-memory equations using SymPy, plus a Rust simulator with a Roofline-style compute model and Ramulator-backed HBM timing. On a SwiGLU layer, the simulator tracks a cycle-accurate Bluespec HDL model with Pearson correlation `0.99`.

## Evaluation

The evaluation targets two dynamic parts of LLM inference: MoE layers with SwiGLU experts and decoding attention. Workloads come from Qwen3-30B-A3B and Mixtral-8x7B, with AzureLLMInference KV-length traces and HH-RLHF-based expert-routing traces. The baseline is not a straw man: the authors implement only Revet-expressible schedules in STeP and compare them against schedules that require STeP's added expressiveness.

Dynamic tiling is the paper's clearest win. At batch `64`, Mixtral gets a `1.65x` speedup at the same on-chip memory as static `tile=16`, while Qwen gets a `1.69x` speedup with `2.1x` less memory than static `tile=8`. At comparable performance points, dynamic tiling cuts memory by `1.33x` on Mixtral and `5.05x` on Qwen. At batch `1024`, where static tiling saturates, dynamic tiling delivers `1.86x` speedup on Mixtral and `1.87x` on Qwen; for Qwen it also cuts memory by `12.5x` relative to the best-performing static point while still improving cycles by `1.12x`.

Configuration time-multiplexing targets sparse expert activation. On Qwen3-30B-A3B it raises compute utilization by `2.64x` with under `1%` overhead under static tiling, or by `2.51x` with about `5%` overhead under dynamic tiling, while freeing `62%` of allocated on-chip compute and `46%` of memory resources. Dynamic parallelization targets attention imbalance: it improves over static interleaved parallelization by `1.14x-1.26x` when KV-length variation is low and `1.47x-1.57x` when variation is high, and reaches `2.72x` over coarse-grained static parallelization at batch `16`.

End-to-end, the full STeP implementations of Mixtral-8x7B and Qwen3-30B-A3B achieve `1.27x` and `1.15x` speedups over memory-matched static implementations. Qwen also uses `69%` less on-chip memory and `54%` fewer compute resources. Even against performance-matched static MoE implementations, the dynamic versions still win by `1.05x` on Mixtral and `1.14x` on Qwen because dynamic parallelization helps attention. Since the evidence is simulator-based, I read it as strong support for relative schedule comparisons rather than final proof of silicon-level deployment results.

## Novelty & Impact

Relative to _Hsu et al. (ASPLOS '23)_, STeP broadens asynchronous streaming from sparse tensor algebra to dense, dynamic tensor programs and adds explicit memory hierarchy. Relative to _Rucker et al. (HPCA '24)_, its main step is not just more dynamic control, but dynamic tiled dataflow that preserves reuse instead of collapsing to scalar threads. Relative to _Ghosh et al. (PLDI '25)_, it makes asynchronous blocks analyzable by exposing symbolic rates and scratchpad placement.

That makes the paper most relevant to accelerator/compiler researchers and to teams building future ML accelerators. Its contribution is a new programming model and schedule surface, not a new single kernel.

## Limitations

The biggest limitation is that the paper stops at abstraction, symbolic frontend, and simulation. The authors validate the simulator against a cycle-accurate HDL model on a representative SwiGLU layer, but they do not implement a full hardware backend for all dynamic STeP features or show results on fabricated silicon. Hardware support for dynamic memory virtualization, routing, and stop-token handling remains future work.

The workload scope is also focused rather than universal. The evaluation is centered on MoE and attention in LLM inference, and the paper does not ship a complete automatic compiler from PyTorch to STeP. Those choices are reasonable for a first paper, but they mean the results establish plausibility and schedule value more than end-to-end deployment maturity.

## Related Work

- _Hsu et al. (ASPLOS '23)_ — SAM introduced an asynchronous streaming tensor abstraction for sparse tensor algebra, while STeP broadens the model to dense dynamic tensors and explicit memory placement.
- _Rucker et al. (HPCA '24)_ — Revet supports dynamic dataflow threads on SDAs, but its scalar-oriented dynamic primitives make dynamic tiled reuse hard to express; STeP targets that gap directly.
- _Ghosh et al. (PLDI '25)_ — Ripple also embraces asynchronous programming for spatial dataflow architectures, but it leaves the memory hierarchy implicit where STeP exposes it as a first-class scheduling surface.
- _Koeplinger et al. (PLDI '18)_ — Spatial provides explicit memory hierarchy for accelerator programming, whereas STeP contributes a stream-first abstraction with symbolic shapes and routing for dynamic workloads.

## My Notes

<!-- empty; left for the human reader -->

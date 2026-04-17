---
title: "Graphiti: Formally Verified Out-of-Order Execution in Dataflow Circuits"
oneline: "Turns sequential dataflow loops into tagged out-of-order circuits via a refinement-checked rewrite framework, while largely preserving the speedups of prior unverified work."
authors:
  - "Yann Herklotz"
  - "Ayatallah Elakhras"
  - "Martina Camaioni"
  - "Paolo Ienne"
  - "Lana Josipović"
  - "Thomas Bourgeat"
affiliations:
  - "EPFL, Lausanne, Switzerland"
  - "ETH Zurich, Zurich, Switzerland"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790166"
project_url: "https://zenodo.org/records/18328388"
tags:
  - hardware
  - verification
  - compilers
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Graphiti gives dynamic HLS a formal rewrite substrate instead of treating aggressive dataflow optimizations as ad hoc graph surgery. It defines graph refinement in Lean 4, proves the rewrite engine sound, and verifies the key rewrite that turns a sequential dataflow loop into a tagged out-of-order one. The resulting circuits keep most of the speedup of prior unverified work while exposing a real bug in that prior compilation scheme.

## Problem

Dynamic HLS can already map irregular C programs to latency-insensitive dataflow circuits, but the next round of performance wins comes from overlapping loop iterations, reordering work, and exploiting pipelined operators. Those are also the hardest optimizations to trust. A locally plausible rewrite can silently add behaviors or break assumptions about loop-carried state.

The paper studies enabling out-of-order execution in a dynamic-HLS loop. Prior work showed that replacing a loop `Mux` with an unconditional `Merge` and wrapping the region with `Tagger/Untagger` can overlap loop instances, but that transformation had no machine-checked correctness argument.

## Key Insight

The paper's core claim is that aggressive dynamic-HLS rewrites become provable once dataflow circuits are given a modular refinement semantics. Graphiti judges a rewrite by refinement: the right-hand side may restrict behavior relative to the left-hand side, but it must not introduce any new behavior.

That viewpoint makes the out-of-order loop optimization manageable. The authors normalize the loop until its body can be treated as a single `Pure` component, prove one parametric rewrite over that shape, and then use the generic rewrite engine to apply it inside larger graphs.

## Design

Graphiti uses two graph languages. `ExprHigh` stays close to the dot graphs emitted by the front-end HLS tool and is convenient for matching. `ExprLow` is an inductive syntax built from base components, products, and explicit connections, and it is the representation over which the verified rewriting function operates. Each component is interpreted as a module with input, output, and internal transitions plus an initial state; whole-graph semantics come from composing those modules and turning connected output/input pairs into internal transitions.

The optimization itself is a rewrite pipeline. Nineteen auxiliary rewrites normalize loops by merging duplicated `Mux`/`Branch` structure, eliminating administrative `Join`/`Split` patterns, and collapsing an arbitrary loop body into a single `Pure` node. The verified core rewrite applies to a loop with one `Mux`, one `Branch`, and a `Pure` body `f : T -> T x Bool`: it converts the entry `Mux` into a tagged `Merge`, inserts `Tagger/Untagger`, and permits multiple loop instances to run concurrently while restoring outputs to input order at loop exit.

The proof obligation is not just local equivalence. The authors show that the sequential loop computes repeated application of `f` until the exit Boolean becomes false, then prove invariants for the out-of-order loop: values are not duplicated, tags stay ordered, and every in-flight value still corresponds to some original input. Those invariants define the simulation relation between the tagged out-of-order loop and the sequential specification.

## Evaluation

The implementation plugs Graphiti into a Dynamatic-based flow: import dot graphs from Dynamatic, apply Graphiti rewrites, export dot again, and reuse Dynamatic for buffer placement and VHDL generation. On a Kintex-7 FPGA with a 4 ns target, the paper compares four flows: in-order dynamic HLS (`DF-IO`), prior unverified out-of-order dataflow (`DF-OoO`), Graphiti, and the verified static-scheduling HLS compiler Vericert.

Graphiti reaches a geomean execution time of `47,335 ns`, versus `100,095 ns` for `DF-IO` and `275,336 ns` for Vericert, which is about `2.1x` faster than the in-order dynamic baseline and `5.8x` faster than the verified static-scheduling baseline. Relative to `DF-OoO`, it is usually close but can be slightly slower because some normalization rewrites introduce extra synchronization.

The most convincing result is qualitative rather than numeric: formalization found that the prior unverified scheme transformed `bicg` unsafely because a store remained inside the loop body. That is exactly the kind of bug the framework is meant to rule out.

## Novelty & Impact

Relative to _Elakhras et al. (FPGA '24)_, the new contribution is not tagged out-of-order execution itself, but recasting it as a verified graph rewrite over a formal refinement semantics. Relative to Vericert, the paper tackles a harder regime: dynamically scheduled dataflow circuits with local nondeterminism and reordering. Relative to mechanized-semantics work, Graphiti adds the compiler-facing layer that was missing: a rewrite engine plus proofs that local rewrites compose.

That matters because it gives dynamic-HLS researchers a way to make aggressive graph optimizations less trust-based. The `bicg` bug shows the framework has practical bite.

## Limitations

The proof story is not yet end-to-end. The rewriting engine and the main parametric loop rewrite are verified, but most supporting rewrites used to normalize loops and build the `Pure` body are still unverified, and rewrite placement depends on an external oracle. This is therefore a partially verified optimization pipeline, not a fully verified dynamic-HLS compiler.

The framework is also expensive and narrow. The Lean development is about 15.8k lines and reportedly took roughly one person-year, and the evaluation covers only the irregular-loop benchmarks inherited from the prior out-of-order dataflow paper. One omitted benchmark, `img-avg`, needs a different branch-reordering transformation that Graphiti does not implement.

## Related Work

- _Elakhras et al. (FPGA '24)_ — introduces the tagged out-of-order dataflow transformation that Graphiti re-expresses as verified rewrites and partially corrects.
- _Herklotz et al. (OOPSLA '21)_ — Vericert verifies HLS for statically scheduled hardware, whereas Graphiti targets dynamically scheduled dataflow circuits with reordering.
- _Law et al. (OOPSLA '25)_ — Cigr/Cilan provide mechanized semantics for dataflow circuits, but Graphiti goes further toward optimization by adding rewrite composition and refinement proofs.
- _Lin et al. (OOPSLA '24)_ — FlowCert translation-validates compilation to asynchronous dataflow, while Graphiti proves local circuit rewrites inside a dynamic-HLS flow.

## My Notes

<!-- empty; left for the human reader -->

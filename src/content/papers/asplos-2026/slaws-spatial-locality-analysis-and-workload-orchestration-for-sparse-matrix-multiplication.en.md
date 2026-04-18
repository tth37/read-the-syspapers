---
title: "Slaws: Spatial Locality Analysis and Workload Orchestration for Sparse Matrix Multiplication"
oneline: "Uses online sparsity analysis to reorder blocks, fuse rows into passes, and diagonally rebalance multiplier work for faster SpMSpM."
authors:
  - "Guoyu Li"
  - "Zheng Guan"
  - "Beichen Zhang"
  - "Jun Yu"
  - "Kun Wang"
affiliations:
  - "State Key Laboratory of Integrated Chips and Systems, College of Integrated Circuits and Micro-Nano Electronics, Fudan University, Shanghai, China"
  - "State Key Laboratory of Integrated Chips and Systems, School of Microelectronics, Fudan University, Shanghai, China"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790222"
tags:
  - hardware
  - caching
  - graph-processing
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Slaws is a sparse-matrix accelerator for `SpMSpM` that treats the two operands differently: it analyzes the left matrix online to recover both local and long-range reuse, and it reorganizes the right matrix's work so multipliers do not stall behind uneven row lengths. The two mechanisms, Pass-Aware and Shuffle-Compare, let the final `Slaws-POS` design beat Feasta by `1.46x`, Spada by `1.43x`, and an RTX 5080 GPU by `1.55x` on average.

## Problem

The paper starts from a mismatch between sparse-matrix theory and accelerator behavior. `SpMSpM` saves work by skipping zeros, but when both operands are sparse the irregularity appears in two places. If the sparse matrix is on the left, the accelerator fetches rows of `B` according to `A`'s nonzero columns, so reuse depends on the exact overlap pattern among rows, not just on row length. If the sparse matrix is on the right, row lengths differ sharply, so some multipliers finish early while others stay busy and the merger waits for late rows to preserve sorted order.

Prior accelerators handle only pieces of that problem. Spada uses row length as a proxy for overlap, but equal-length rows can still have very different nonzero positions. Feasta and Trapezoid support useful dataflows, yet their parallelism choices are fixed ahead of time. Software preprocessing can find better reorderings, but the paper argues that its cost is often much larger than one kernel execution. Slaws therefore aims for a low-cost online mechanism that recovers reuse on the left operand and balances work on the right operand without building an expensive exact scheduler.

## Key Insight

The central claim is that the two hard parts of `SpMSpM` need two different structural signals. For the left multiplicand, the important question is whether rows share column positions locally and whether distant blocks expose similar sparsity signatures globally. If hardware can sample those patterns cheaply, it can decide when to execute rows together with `Outer-Product`-style reuse and when to stay with `Gustavson`-style row processing.

For the right multiplicand, the key observation is that `CSR` rows are already sorted by column index. Slaws exploits that order to distribute elements diagonally across comparator trees and generate an approximate per-cycle top-`K` output without exact top-`K` hardware. Online approximate structure is enough: one mechanism saves memory traffic, and the other raises utilization by preventing short rows and merge dependencies from idling multipliers.

## Design

Slaws is built on a reconfigurable sparse accelerator that can mix Gustavson-style work within multiplier groups and Outer-Product-style work across groups. Its new logic sits around that baseline.

Pass-Aware has three stages. `Structure-Profiling` samples a window of rows from `A`, turns their nonzero locations into bitmaps, compresses away all-zero positions, and intersects the compressed bitmaps to count overlap. `Block-Reordering` then partitions `A` into cache-sized blocks, samples rows from each block, and greedily places similar blocks next to each other so the cache can benefit from long-range reuse. Finally, `Pass-Generation` examines consecutive rows inside a block and decides whether to fuse them into one pass by comparing the input reuse gained from sharing fetched `B` rows against the output-space cost of holding more partial sums at once. Rows inside a pass execute with `OutP`; across passes the accelerator falls back to `Gus`.

The right-side mechanism is `Shuffle-Compare`. Instead of binding one row to one multiplier, Slaws shuffles sorted elements from multiple rows into a diagonal pattern across comparator trees. A small scheduler tracks consumed entries, shifts survivors forward, and inserts new tail elements while preserving row order. The result is only approximate top-`K`, but it is close enough to keep the merger fed without the cost of exact selection hardware. The `Task Allocator` ties the design together by choosing a power-of-two reconfiguration factor near the current pass width and slicing rows accordingly.

## Evaluation

The evaluation combines a C++ cycle-accurate simulator with RTL synthesis of the new control logic in `TSMC 28nm` at `1 GHz`. The workloads come from `SuiteSparse`: square matrices are multiplied by themselves and non-square matrices by their transpose, with additional experiments for random right matrices and `SpMM`. The main baselines are Spada, Feasta, a Gustavson-only Feasta variant, and an `Nvidia RTX 5080` running `cusparseSpGEMM_compute()`.

Across the main `SpMSpM` workloads, `Slaws-POS` averages `1.46x` speedup over Feasta, `1.43x` over Spada, and `1.51x` over the Gustavson-only Feasta variant. The gains are small on regular matrices such as `cari` and `msc10848`, where row length already tracks pattern similarity reasonably well, and much larger on irregular matrices such as `email-Enron`, `dbir2`, and `ca-CondMat`, where direct overlap analysis and Shuffle-Compare matter more. For some matrices with long-range similarity, block reordering nearly halves `B`-matrix traffic.

The overhead analysis is the key validation. The Block-Reordering stage takes less than `2%` of kernel execution time, and its sampling adds only about `5%` of original `A` traffic on average. That is the paper's answer to software reorderers like Gamma and Bootes, whose preprocessing is reported as `6178x` and `4872x` longer than one kernel execution for the tested matrices. The paper also reports `1.45x` speedup over Feasta when the right matrix is random and `1.30x` improvement for `SpMM`, mostly from Pass-Aware's traffic reduction. Against the RTX 5080, Slaws still wins by `1.55x` on average despite the GPU's `7.5x` higher memory bandwidth, though the gap narrows on denser matrices such as `cari`.

## Novelty & Impact

Relative to _Li et al. (ASPLOS '23)_, Slaws' main novelty is refusing to treat row length as a sufficient summary of sparse structure. Relative to _Zhong et al. (ASPLOS '24)_, it moves from fixed compile-time parallelism to runtime structure analysis and pass formation. Relative to _Zhang et al. (ASPLOS '21)_ and _Yadav and Asgari (MICRO '25)_, its novelty is not better offline reordering quality, but a lightweight hardware method whose overhead is small enough for single-kernel use.

That makes the paper interesting to accelerator designers working on sparse linear algebra, graph kernels, and other reuse-sensitive irregular workloads. Its real contribution is the argument that sparse accelerators need online structure analysis, not just more configurable datapaths, if they want both generality and low memory traffic.

## Limitations

The paper's output-reuse estimate assumes matrix `B` behaves like a randomly sparse matrix, which keeps the hardware model tractable but may not fit every workload. The block-ordering and pass-fusion heuristics are also greedy approximations, so Slaws can miss the globally best schedule even if its measured overhead is low.

The evaluation is also narrower than the headline numbers suggest. Most accelerator comparisons are simulator-based rather than full-chip silicon, the GPU comparison uses only one software path and one device generation, and the wins shrink on regular or denser matrices where cache thrashing and work imbalance matter less. Shuffle-Compare is intentionally approximate as well, so some highly imbalanced cases still benefit from exact top-`K`.

## Related Work

- _Li et al. (ASPLOS '23)_ — Spada adapts dataflow using row-length windows, while Slaws argues that direct overlap analysis is a better signal for sparse-pattern similarity.
- _Muñoz Martínez et al. (ASPLOS '23)_ — Flexagon provides multi-dataflow hardware, but Slaws adds online structure analysis and workload rebalancing instead of relying mainly on the architecture alone.
- _Zhang et al. (ASPLOS '21)_ — Gamma exploits row reordering for Gustavson-style multiplication in software, whereas Slaws pursues cheaper hardware-assisted reordering that can be used per kernel.
- _Zhong et al. (ASPLOS '24)_ — Feasta offers a flexible sparse-tensor accelerator with predefined parallelism, while Slaws chooses passes and reuse opportunities at runtime from sampled sparsity patterns.

## My Notes

<!-- empty; left for the human reader -->

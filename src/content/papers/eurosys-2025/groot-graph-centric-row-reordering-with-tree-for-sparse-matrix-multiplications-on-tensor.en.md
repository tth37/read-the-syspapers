---
title: "Groot: Graph-Centric Row Reordering with Tree for Sparse Matrix Multiplications on Tensor Cores"
oneline: "Groot reorders sparse-matrix rows by Hamming-distance kNN graph plus MST traversal, making tensor-core SpMM/SDDMM condense into fewer dense tiles."
authors:
  - "YuAng Chen"
  - "Jiadong Xie"
  - "Siyi Teng"
  - "Wenqi Zeng"
  - "Jeffrey Xu Yu"
affiliations:
  - "The Chinese University of Hong Kong"
  - "Hong Kong University of Science and Technology"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717460"
code_url: "https://github.com/yuang-chen/Groot-EuroSys25"
tags:
  - graph-processing
  - gpu
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Groot is a row-reordering preprocessor for static sparse matrices that makes TC-GNN-style graph condensing produce fewer non-empty Tensor Core tiles. It replaces Jaccard/LSH grouping with Hamming-distance nearest-neighbor search plus MST traversal, and the paper reports average 1.80x TC-SpMM and 2.02x TC-SDDMM speedups.

## Problem

Real graph-derived sparse matrices are irregular, so SpMM and SDDMM on GPUs suffer from poor coalescing and load imbalance. TC-GNN's condensing helps by packing each row window into denser MMA tiles after deleting empty columns, but its benefit depends heavily on which rows land in the same window.

Prior GPU reorderers mostly use Jaccard similarity with LSH clustering. Groot argues that this is misaligned with the real target. Condensing wants each window to expose as few distinct nonzero columns as possible, not to maximize similarity to a cluster center. The authors also criticize LSH-style methods for approximation errors, cluster/window size mismatch, and purely local clustering without a global ordering objective.

## Key Insight

Groot's key insight is that condensing benefits from minimizing row differences rather than maximizing row similarity. If adjacent rows disagree in fewer column positions, later windowing is more likely to leave fewer surviving columns and therefore fewer TC tiles.

That leads to a cleaner objective: reorder rows so the total Hamming distance between consecutive rows is minimized. The exact window-aware problem is NP-hard, but the relaxed consecutive-row version is also NP-hard while now resembling open-loop TSP, which makes standard graph approximations applicable and decouples the order from any single MMA shape.

## Design

Each CSR row is represented by its sorted nonzero column indices. Groot defines sparse Hamming distance by merge-scanning those two index lists, counting unmatched positions. Instead of constructing the full all-pairs graph, it uses `kGraph` with that custom metric to build a sparse k-nearest-neighbor graph, keeping only the most relevant local edges.

Groot then extracts a minimum spanning tree with Kruskal's algorithm and uses preorder traversal of that tree or forest as the new row order. The MST preserves low-cost row transitions; preorder gives the paper a TSP-style approximation story. The result is a practical pipeline with overall complexity `O(n^1.14 + nk log nk)` rather than factorial search, and because the objective is no longer tied to a fixed window size, one reordered matrix can be reused across multiple MMA shapes.

## Evaluation

Experiments run preprocessing on a dual-socket AMD EPYC 7443 server and downstream kernels on an NVIDIA L40 40 GB GPU. The baselines are an open-source LSH reorderer and TCA, and the workloads are 17 graph datasets using TC-GNN's TC-SpMM/TC-SDDMM plus cuSPARSE CUDA-core kernels.

The main numbers support the paper's claim. On Tensor Cores, Groot averages 1.80x speedup for SpMM versus 1.20x for LSH and 1.11x for TCA; for SDDMM it averages 2.02x versus 1.08x and 0.98x. Strong cases include 2.64x on `artist` for TC-SpMM, 3.28x on `products`, 2.74x on `reddit`, and 3.99x on `reddit` for TC-SDDMM. The mechanism evidence matches: non-empty tile count falls by 37% on `amazon0505`, 69% on `products`, and 58% on `reddit`, and ablation shows unordered, kNN-only, and MST-only variants reach only 56%, 73%, and 77% of full Groot performance.

The gains are not universal. `Yeast` and `YeastH` barely improve, and LSH slightly wins on `proteins`. Reordering overhead is a one-time CPU cost of 0.27 s to 82 s, far below LSH's 1.5 s to 1.7 hr and TCA's up-to-more-than-15 hr on the tabled cases. End-to-end gains are smaller but still positive: 1.22x for GCN and 1.38x for AGNN, plus benefits on an OPT-30B sparse MLP matrix once sparsity exceeds 50%.

## Novelty & Impact

Groot's novelty is in reframing preprocessing, not in inventing a new sparse kernel. It replaces Jaccard/LSH row clustering with Hamming-distance graph construction and a tree-based global ordering that better matches TC-GNN-style condensation. That should make it relevant wherever a sparse pattern is static enough to amortize one reorder pass: graph analytics, GNN training/inference, and pruned-model serving.

## Limitations

The design assumes static, unstructured sparsity. Dynamic matrices would pay repeated reorder cost, and structured layouts such as NVIDIA 2:4 sparsity would be broken by row permutation. The paper's broader-system evidence is also narrower than its kernel story: GNN gains are smaller because dense layers still dominate part of runtime, and the LLM test is only one `28672 x 7168` OPT-30B weight matrix rather than a full serving stack. The CUDA-core section is also internally inconsistent, reporting average CU-SDDMM speedup once as 1.11x and later as 1.32x.

## Related Work

- _Wang et al. (USENIX ATC '23)_ - TC-GNN introduces graph condensing to map graph-derived sparse matrices onto Tensor Cores, while Groot is a preprocessing layer that makes that condensation produce fewer tiles.
- _Fan et al. (ASPLOS '24)_ - DTC-SpMM uses cache-aware reordering for tensor-core sparse MM, whereas Groot argues the underlying Jaccard-style objective is misaligned with condensing and replaces it with Hamming-distance ordering.
- _Jiang et al. (PPoPP '20)_ - This earlier GPU sparse-MM work groups rows with Jaccard similarity and LSH, while Groot swaps in graph-based ANN construction and an MST-derived global ordering.
- _Wei et al. (SIGMOD '16)_ - GOrder frames graph reordering as an NP-hard locality problem for graph analytics, and Groot adapts a similar global-ordering mindset to tensor-core tile formation rather than cache locality alone.

## My Notes

<!-- empty; left for the human reader -->

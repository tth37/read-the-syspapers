---
title: "Bingo: Radix-based Bias Factorization for Random Walk on Dynamic Graphs"
oneline: "Bingo factorizes edge biases into radix groups so dynamic biased random walks keep O(1) sampling while updates touch only O(K) group state on GPUs."
authors:
  - "Pinhuan Wang"
  - "Chengying Huan"
  - "Zhibin Wang"
  - "Chen Tian"
  - "Yuede Ji"
  - "Hang Liu"
affiliations:
  - "Rutgers, The State University of New Jersey, Piscataway, NJ, USA"
  - "State Key Laboratory for Novel Software Technology, Nanjing University, Nanjing, China"
  - "The University of Texas at Arlington, Arlington, Texas, USA"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717456"
tags:
  - graph-processing
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Bingo is a GPU random-walk engine for dynamic graphs that replaces per-vertex biased-sampling tables with a radix-factorized representation. It samples in two stages, updates only the affected radix groups on edge insertions and deletions, and reports O(1) sampling with O(K) update cost, where `K` is the number of bias bits.

## Problem

The paper starts from a practical gap: random walks are a core primitive for graph learning, recommendation, PPR, and similarity search, but real graphs are not static. Edges arrive, disappear, and change weight continuously. Existing random-walk systems such as KnightKing, C-SAW, GraphWalker, and gSampler are optimized for static graphs, while dynamic-graph engines mostly target analytics kernels rather than repeated biased sampling.

Why is this hard? The standard sampling choices all fail in a different way once the graph changes online. Alias tables preserve O(1) sampling, but a single edge update can require O(d) work to rebuild the affected vertex's table. Rejection sampling handles updates cheaply, but its sampling cost depends on the bias distribution and can degrade badly on skewed neighborhoods. Inverse transform sampling updates more easily, yet every sample still costs O(log d), which matters when high-degree vertices dominate the workload. The authors therefore want a system that can absorb both low-latency streaming updates and high-throughput batched updates without giving up the fast biased sampling that makes random walks practical in the first place.

## Key Insight

Bingo's central claim is that a biased neighborhood should not be maintained as one monolithic sampling table. It should be factorized by radix bits. If each edge bias is decomposed into its powers-of-two components, then every resulting group becomes an unbiased set of neighbors that all contribute the same sub-bias.

That changes both sampling and updating. Sampling becomes hierarchical: first sample which radix group to use based on the total weight of each group, then sample uniformly inside that group. Updating becomes cheap because an edge insertion or deletion only touches the groups corresponding to the nonzero bits of its bias, rather than rebuilding a structure proportional to the full vertex degree. The paper proves that summing over all groups preserves the original transition probability, so the factorization changes the representation, not the walk semantics.

## Design

For a vertex with neighbors and integer biases `w_i`, Bingo decomposes each `w_i` into the set of radix terms `{2^k}` whose bits are set. It then reorganizes those sub-biases by bit position. The per-vertex sampling space therefore has two levels. The inter-group level stores the total bias mass of each radix group and uses an alias table to choose a group in O(1) time. The intra-group level stores the neighbors that belong to the chosen group; because every element in that group contributes the same radix value, the second step is just uniform sampling, also O(1).

Streaming updates reuse the same structure. Insertions are easy: decompose the new edge bias, append the edge into the relevant groups, then rebuild the tiny inter-group alias table. Deletions are the harder case, so Bingo stores neighbor indices rather than neighbor IDs inside groups and maintains an inverted index telling it where each neighbor index sits in every group. That lets the system find a deleted edge in O(1), swap it with the group's tail element, and keep the list compact enough for uniform sampling.

The naive structure is memory-hungry, so Bingo adds adaptive group representations. Dense groups drop the per-group lists entirely and fall back to rejection sampling over the original neighbor list, because those groups are large but statistically less important. One-element groups store no auxiliary indices at all. Sparse groups use a reduced neighbor list containing only large-bias edges, shrinking the inverted index. Only the remaining regular groups keep the full structure. For floating-point weights, Bingo scales by an empirically chosen factor `lambda`, decomposes the integer part normally, and places the decimal residue into one extra group handled by ITS or rejection sampling.

Batched updates are the GPU-systems contribution on top of the sampling algorithm. The CPU first orders updates by vertex, then the GPU processes insert, delete, and rebuild phases separately. The key trick is a two-phase parallel delete-and-swap: the system stages the tail elements, removes any of those tail elements that are themselves being deleted, and then uses only guaranteed-live tail entries to fill holes at the front. That avoids corrupting the compact group layout while exposing massive parallelism.

## Evaluation

The evaluation is strong enough to support the paper's main claim, though it mixes algorithmic and systems wins. Bingo is implemented in about 2,000 lines of CUDA/C++, evaluated on a server with four A100-80GB GPUs, and tested on five real graphs from Amazon to Twitter with workloads drawn from biased DeepWalk, node2vec, and PPR. The update traces include insertion-only, deletion-only, and mixed batches.

The headline result is that Bingo consistently beats the three baselines the authors adapt for this setting: KnightKing by 24.46x-112.28x, gSampler by 8.74x-25.66x, and FlowWalker by 182.78x-271.11x across the reported workloads. The engine also reaches about 0.2 million streaming updates per second and up to 226 million batched updates per second. Just as important, the adaptive group representation cuts Bingo's own memory footprint by 14.6x-22.2x versus the naive design and avoids an out-of-memory case on Twitter.

The evidence is well aligned with the mechanism. Deletion is faster than insertion because memory can be reclaimed lazily, and batched updates are about three orders of magnitude faster than streaming updates because they rebuild the inter-group state only once per batch. Floating-point weights add only 1.02x time and 1.08x memory on average, which suggests the extra decimal group is not dominating the cost. The one caveat is that the comparison against gSampler and FlowWalker relies on rebuilding or reloading their structures after each round, since those systems do not natively support Bingo's update model.

## Novelty & Impact

The novelty is not a new random-walk objective. It is a new biased-sampling substrate for dynamic graphs. The radix-factorization idea turns a neighborhood update problem from "rebuild a degree-sized structure" into "touch a small number of radix groups," and the rest of the system work makes that representation practical on GPUs.

That matters for two audiences. For graph-systems researchers, Bingo is a clear alternative to the usual alias-vs-rejection tradeoff for dynamic biased sampling. For practitioners building graph-learning or recommendation pipelines on continuously changing graphs, it shows that online structure changes do not have to force a retreat to slow sampling or expensive full rebuilds.

## Limitations

Memory is still Bingo's biggest cost. Even after group adaptation, the paper shows cases where Bingo uses more memory than simpler baselines, especially on graphs with many high-bias vertices that induce more regular groups. The authors suggest tuning the dense and sparse thresholds or using a larger radix base, but that is more of an engineering escape hatch than a principled answer.

The floating-point story is also pragmatic rather than elegant. It depends on an empirically chosen scaling factor and a special decimal group handled by ITS or rejection sampling. The paper shows this is cheap in its experiments, but it is not as clean as the integer-bias path.

Finally, the evaluation uses synthetic update streams generated from static datasets, and two of the three main baselines have to be extended by rebuilding after each update round. That still demonstrates Bingo's value as a dynamic engine, but it means the measured end-to-end wins combine a better sampling representation with the fact that competing systems were not originally built for this problem.

## Related Work

- _Yang et al. (SOSP '19)_ - KnightKing is a fast random-walk engine for static graphs and dynamic bias handling, whereas Bingo targets structural graph updates directly.
- _Pandey et al. (SC '20)_ - C-SAW accelerates graph sampling on GPUs, but it assumes static sampling spaces instead of maintaining them under inserts and deletes.
- _Huan et al. (EuroSys '23)_ - TEA supports temporal-graph random walks, while Bingo handles structurally changing graphs whose adjacency lists evolve online.
- _Papadias et al. (VLDB '22)_ - Wharf updates already materialized random-walk outputs after graph changes, whereas Bingo maintains the biased-sampling substrate for future walks.

## My Notes

<!-- empty; left for the human reader -->

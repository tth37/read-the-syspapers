---
title: "OHMiner: An Overlap-centric System for Efficient Hypergraph Pattern Mining"
oneline: "OHMiner compiles a hypergraph pattern into overlap intersections and checks region sizes instead of per-vertex profiles, removing redundant incident-hyperedge work in HPM."
authors:
  - "Hao Qi"
  - "Kang Luo"
  - "Ligang He"
  - "Yu Zhang"
  - "Minzhi Cai"
  - "Jingxin Dai"
  - "Bingsheng He"
  - "Hai Jin"
  - "Zhan Zhang"
  - "Jin Zhao"
  - "Hengshan Yue"
  - "Hui Yu"
  - "Xiaofei Liao"
affiliations:
  - "National Engineering Research Center for Big Data Technology and System, Services Computing Technology and System Lab, Cluster and Grid Computing Lab, School of Computer Science and Technology, Huazhong University of Science and Technology, China"
  - "Department of Computer Science, University of Warwick, United Kingdom"
  - "National University of Singapore, Singapore"
  - "Zhejiang Lab, China"
  - "Jilin University, China"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717474"
tags:
  - graph-processing
  - compilers
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

OHMiner treats hypergraph pattern mining as an overlap problem rather than a per-vertex bookkeeping problem. It compiles a pattern into an Overlap Intersection Graph (OIG), validates candidates by comparing overlap-derived region sizes, and prunes partial embeddings as soon as one overlap violates the pattern. On the paper's real-world workloads, that is enough to beat HGMatch by 5.4x-22.2x.

## Problem

Hypergraph pattern mining (HPM) asks for every subhypergraph in a data hypergraph that is isomorphic to a user-specified pattern. Compared with ordinary graph pattern mining, the validation step is harder because hyperedges can overlap in many vertices, and one overlap can itself be nested inside larger overlaps. A system therefore has to do more than check whether the next hyperedge is adjacent to the current partial embedding; it must verify that the whole overlap structure is consistent.

Earlier match-by-vertex systems paid for that complexity with enormous search spaces. HGMatch improves the search order by extending one hyperedge at a time, but its candidate generation and validation still operate at vertex granularity. To extend a partial embedding, it repeatedly fetches incident hyperedges for different mapped vertices and then hashes per-vertex profiles to test isomorphism. The paper shows that this wastes most of the time: candidate generation plus validation consume 97%-99% of runtime, redundant computations account for up to 90% of the total time, and 68%-91% of the vertices touched during validation are redundant because many of them share exactly the same incident hyperedges.

## Key Insight

The key claim is that HPM should be expressed in terms of overlap regions, not individual vertices. If one views a set of hyperedges as a Venn diagram, each region corresponds to the vertices that share the same incident hyperedges. Two partial hypergraphs are therefore isomorphic exactly when the sizes of their corresponding regions match. That lets OHMiner replace HGMatch's repeated profile construction with overlap computations plus region-size comparisons.

The second insight is that these region computations can be compiled and reused. OHMiner applies the inclusion-exclusion principle to rewrite region-size formulas into set intersections, so the same overlap can serve as an intermediate result for multiple regions. It also observes that many candidate hyperedges are disconnected: in the authors' study, the connection density among degree-matched hyperedges is at most 0.11. Empty overlaps are therefore common, and a compiler can turn those disconnections into pruning rules before runtime.

## Design

OHMiner's front end builds an Overlap Intersection Graph for the input pattern. Level 1 vertices are pattern hyperedges, deeper levels are overlaps among them, and identical overlap vertices are merged so the same intersection is never computed twice. The compiler then derives an overlap order, a topological execution order that respects both the pattern's hyperedge matching order and the data dependencies between overlaps. It also groups OIG vertices so that disconnection information from one level can rule out empty overlaps in later levels without recomputing them individually.

From that analysis the back end emits an overlap-centric execution plan. For hyperedge vertices, the plan specifies how to generate candidates from adjacency and degree constraints. For overlap vertices, it specifies the exact set intersections, expected overlap degrees, equality constraints, and disconnection constraints that a valid embedding must satisfy. At runtime, OHMiner maintains an embedding OIG (EOIG) for each partial embedding and extends it incrementally. If one computed overlap has the wrong size, should be empty but is not, or should equal a previous overlap but differs, the engine prunes the partial embedding immediately instead of finishing a full vertex-profile comparison.

Candidate generation is also rewritten around hyperedges. OHMiner's degree-aware adjacency list (DAL) stores, for each hyperedge, its adjacent hyperedges grouped by degree. To generate a candidate for the next pattern hyperedge, the engine intersects only the degree-compatible adjacency groups of already matched hyperedges. This avoids HGMatch's repeated scans over mapped vertices' incident hyperedges. The implementation runs the search tree with DFS, assigns first-hyperedge candidates to OpenMP threads with dynamic scheduling, and uses AVX-512 SIMD for set operations.

## Evaluation

The evaluation is careful about fairness. The authors compare against HGMatch, the strongest prior HPM system, on a 64-core, 128-thread Xeon server with 1 TB of RAM, across eight real hypergraph datasets and sampled patterns with 2-6 hyperedges. They also strengthen the baseline by replacing HGMatch's original fine-grained parallelism with OHMiner's thread-level strategy because it was faster in their environment.

The main result matches the paper's thesis. For unlabeled HPM, OHMiner improves over HGMatch by 8.2x-22.2x, 7.2x-21.0x, 7.1x-17.0x, 5.4x-19.5x, and 6.2x-17.8x across the five pattern settings. For labeled HPM, the gain is still 5.1x-22.0x. On larger hypergraphs with 3.7 million and 22.5 million hyperedges, it remains 7.6x-12.2x and 9.9x-14.5x faster. The paper also shows that SIMD is helpful but not the whole story: even without SIMD, OHMiner still beats HGMatch by 3.8x-19.6x.

Ablations explain where the win comes from. Inclusion-exclusion alone gives a 1.40x-3.01x speedup over HGMatch, overlap-pruned validation raises that to 2.01x-4.74x, and the full DAL-based candidate generation adds another 2.56x-3.70x over the validation-only version. Overheads are modest: OIG compilation takes 0.04-1.78 ms, and DAL construction accounts for only 0.1%-3.4% of total HPM time. The main tradeoff is memory footprint, since DAL can reach 2.50 GB on one dataset. Overall, the evidence supports the paper's central claim that overlap-centric validation, not just a better matching order, is the dominant improvement.

## Novelty & Impact

OHMiner's novelty is that it changes the unit of reasoning in HPM. Prior hypergraph systems either reduced search space with better extension order or pruned candidates with handcrafted features, but they still validated embeddings by repeatedly reconstructing vertex-level incident-hyperedge structure. OHMiner instead compiles the pattern into overlap semantics and makes those semantics first-class runtime state.

That makes the paper relevant beyond one benchmark win. Hypergraph query engines and graph-mining compilers can borrow the same pattern-aware decomposition idea: represent nested overlaps explicitly, generate only the required intersections, and prune as soon as overlap constraints fail. The paper is likely to be cited both by future hypergraph matching work and by graph-mining systems that want to generalize set-centric execution to richer edge models.

## Limitations

The paper does not change the worst-case combinatorics of subhypergraph isomorphism. Its experiments use sampled patterns with only 2-6 hyperedges, so the scalability of OIG construction and overlap explosion for much larger or denser query patterns is still unclear, even though the dense-pattern study shows the method still wins in the tested regime.

The system also pays an indexing-memory tax to get faster candidate generation. DAL reaches 2.50 GB on `house-bills` and 1.25 GB on `AMiner`, which is fine on the authors' 1 TB server but may be material on smaller machines. Finally, the prototype is a shared-memory CPU system with OpenMP and AVX-512; the paper does not explore distributed HPM, GPU implementations, or dynamic hypergraphs.

## Related Work

- _Yang et al. (ICDE '23)_ - HGMatch already switches HPM from match-by-vertex to match-by-hyperedge, but it still validates candidates through redundant per-vertex profile construction; OHMiner replaces that path with overlap-centric compilation and pruning.
- _Su et al. (TKDE '23)_ - Efficient Subhypergraph Matching Based on Hyperedge Features prunes candidates with hyperedge-level features, whereas OHMiner attacks the remaining validation bottleneck after candidates are formed.
- _Chen and Qian (ASPLOS '23)_ - DecoMine compiles ordinary graph pattern mining through pattern decomposition; OHMiner plays a similar compiler role for hypergraphs, where nested overlap semantics replace ordinary edge intersections.
- _Shi et al. (SC '23)_ - GraphSet turns graph pattern mining into equivalent set transformations, and OHMiner adapts that set-centric style to hypergraphs by compiling reusable overlap intersections and empty-overlap pruning.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Jupiter: Pushing Speed and Scalability Limitations for Subgraph Matching on Multi-GPUs"
oneline: "Jupiter replaces remote neighbor fetching with delegated search contexts run where the graph slice lives, then batches the remaining tiny messages."
authors:
  - "Zhiheng Lin"
  - "Ke Meng"
  - "Changjie Xu"
  - "Weichen Cao"
  - "Guangming Tan"
affiliations:
  - "SKLP, Institute of Computing Technology, CAS, University of Chinese Academy of Sciences, Beijing, China"
  - "University of Chinese Academy of Sciences, Beijing, China"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717491"
code_url: "https://github.com/AnySparse/Jupiter"
tags:
  - graph-processing
  - gpu
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Jupiter treats a multi-GPU cluster as distributed shared memory and moves subgraph-matching work to the GPU that already owns the needed adjacency list instead of pulling that list over the fabric. It serializes each search subtask as a compact context, batches the resulting tiny messages, and reports up to 120x speedup over prior distributed GPU systems while handling graphs roughly 10x larger under the same memory budget.

## Problem

Distributed subgraph matching suffers from a mismatch that PageRank-style graph analytics do not: the answer a GPU needs from a remote partition is usually small, but the neighbor list it must fetch to compute that answer is large. A partial embedding needs remote topology only to filter a candidate set, and most candidates are false positives, so the returned intersection is tiny compared with the transferred adjacency list. The paper calls this communication amplification and measures it at up to 109.1x.

Existing systems mostly choose which cost to pay. Replication-based engines such as G2 Miner avoid communication by storing the whole graph on every GPU, but that caps scale. Host-memory systems such as VSGM and G2-AIMD stream overlapping k-hop views through PCIe, which reduces replication cost but reintroduces data duplication, CPU involvement, and poor overlap between transfer and computation. Pure data fetching is no better at scale: the paper estimates that a 14 GB graph can trigger about 8 TB of communication because the same remote neighbor lists are pulled repeatedly. Worse, if one tries to send only the minimum state, the traffic becomes tiny and irregular; for 4-clique listing, 93% of messages are under 200 bytes.

## Key Insight

Jupiter's key claim is that the mobile object should be the search state, not the graph topology. Repeated set operations shrink candidate sets, so a suspended matching subtask is usually much smaller than the remote adjacency list it wants to inspect.

That is why delegation works. Instead of copying `N(u)` to the GPU that owns the current partial embedding, Jupiter serializes the subtask, sends it to the GPU that already owns `N(u)`, resumes execution there, and sends back only the derived context or final answer. The search semantics stay the same as in data fetching, but repeated remote-topology transfers become local memory accesses on the remote GPU.

## Design

Jupiter exposes the cluster as one distributed shared-memory space over NVSHMEM. The `Executor` runs the normal set-centric matcher, the `Delegator` decides when a task should move to another GPU, and the `ContextManager` performs the low-level DSM allocation and put/get operations.

The transferable unit is a context `<S, P, op>`, where `S` and `P` are the candidate sets for the edge currently being matched and `op` is the set operation to apply. A remote GPU can restore that context, enumerate `v` in `S`, read local `N(v)`, and compute `N(v) op P` without importing topology first. When `S = P`, Jupiter records a reference marker instead of serializing the same set twice. The Delegator also partitions a produced context by graph partition so each target GPU receives only the vertices that already live there; this can recurse if later steps hit another remote partition.

Because delegation replaces big transfers with many tiny ones, Jupiter batches contexts in per-GPU shared buffers organized like CSR and managed with a lock queue. A runtime lookup table `LUT(s, t)` chooses the concurrency level that best matches the current message size and interconnect. Intra-node transfers use core dedication to avoid NVLink congestion; inter-node transfers use a two-stage forwarding scheme similar to ShenTu. The implementation keeps both graph partitions and work contexts in DSM, uses 1-D partitioning, and can optionally maintain a static graph-data cache to reduce repeated remote reads further.

## Evaluation

The evaluation spans up to 8 A100-80GB GPUs on one NVLink node and multiple nodes of 4 V100-32GB GPUs connected by InfiniBand. Datasets range from 500 MB CitePatents to 361 GB UK-2014, and the baselines include G2 Miner, VSGM, G2-AIMD, PBE, plus an internal data-fetching baseline `Jupiter-DF`. The paper also fixes matching order and symmetry-breaking rules across systems, which helps the comparison.

The results match the paper's claim. On a single GPU, Jupiter retains 84%-98% of G2 Miner's performance, so the distributed machinery is visible but modest. On 4x A100, it is on average 21.5x faster than VSGM and 12.2x faster than G2-AIMD, with a maximum reported speedup of 120x. More importantly, it solves graphs that replication or host-memory designs cannot finish: on 325 GB ClueWeb12 and 361 GB UK-2014, the competing systems time out or OOM while Jupiter still completes, which makes the paper's "about 10x larger graph" claim plausible.

The mechanism-level evidence is also strong. Delegation cuts communication volume by up to 105x and by 14x on average versus `Jupiter-DF`, shrinking communication's runtime share from 33%-42% to under 5%; context-switch overhead peaks at 3.1%. Intra-node bandwidth reaches 227 GB/s and inter-node bandwidth 10 GB/s, or 75.7% and 80% of peak respectively. GPU utilization stays above 95%, and scaling reaches 87.5%-92.5% efficiency on one 8-GPU node and 57.5%-75% across multiple 4-GPU V100 nodes. The important caveat is that G2 Miner, which fully replicates the graph, can still be faster when the graph fits on every GPU. Jupiter's advantage is that it keeps working after replication stops being feasible.

## Novelty & Impact

Jupiter's novelty is not a new matching algorithm but a new execution model for partitioned graph mining. Earlier systems replicated topology, streamed overlapping subgraphs from host memory, or fetched remote neighbor lists. Jupiter instead makes the search itself mobile: contexts move, topology stays put, and DSM plus batching make that practical on GPUs. Because delegation also composes with Subgraph Morphing and the Inclusion-Exclusion Principle, the paper's likely impact is broader than one engine: it offers a reusable way to run irregular graph-mining work on multi-GPU clusters without mirroring the full graph everywhere.

## Limitations

Jupiter wins most clearly in the regime it targets: large partitioned graphs where communication dominates. When graphs fit on every GPU, a replication design like G2 Miner can still be faster because it avoids delegation entirely. The paper also concedes that low-degree vertices may benefit less, since context-switch cost can approach the cost of fetching a tiny neighbor list.

The implementation is tightly bound to NVIDIA-style fabrics and tuning. It depends on NVSHMEM, NVLink/NVSwitch, and InfiniBand behavior, and its bandwidth policy relies on an empirical lookup table plus topology-specific scheduling. Multi-node scaling is good but still well below ideal, and the paper shows that too much inter-node concurrency can backfire because communication still relies on CPU proxy threads. It also does not study dynamic graph updates, online repartitioning, or portability to other accelerator ecosystems.

## Related Work

- _Chen and Arvind (OSDI '22)_ - G2 Miner parallelizes work across GPUs by fully replicating the graph, whereas Jupiter keeps non-overlapping partitions and pays communication only through delegated contexts.
- _Jiang et al. (SC '22)_ - VSGM extends GPU memory with host-managed overlapping k-hop views; Jupiter avoids those duplicated subgraphs and keeps communication inside GPU-side DSM instead of round-tripping through the CPU.
- _Yuan et al. (ICDE '24)_ - G2-AIMD refines VSGM's scheduling with AIMD-style control, but it still inherits the host-memory streaming model that Jupiter is explicitly trying to replace.
- _Chen and Qian (ASPLOS '23)_ - Khuzdul fetches missing adjacency data across distributed CPU partitions, while Jupiter argues that subgraph matching should send the suspended search to the data rather than pull the data to the search.

## My Notes

<!-- empty; left for the human reader -->

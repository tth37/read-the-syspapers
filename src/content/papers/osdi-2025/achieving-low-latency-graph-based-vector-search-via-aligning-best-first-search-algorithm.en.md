---
title: "Achieving Low-Latency Graph-Based Vector Search via Aligning Best-First Search Algorithm with SSD"
oneline: "PipeANN breaks best-first search's strict step-by-step compute/I/O order, pipelines speculative SSD reads, and recovers throughput with a two-phase dynamic pipeline."
authors:
  - "Hao Guo"
  - "Youyou Lu"
affiliations:
  - "Tsinghua University"
conference: osdi-2025
tags:
  - ml-systems
  - storage
  - databases
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

PipeANN is an SSD-resident graph ANNS system that stops treating best-first search as a rigid loop of "read a batch, wait, explore, repeat." Its core algorithm, PipeSearch, speculatively issues asynchronous reads from the current candidate pool before earlier reads have been fully explored, then PipeANN adds a two-phase dynamic pipeline and a conservative refill policy to keep most of the latency win without collapsing throughput.

## Problem

Graph-based ANNS gives excellent latency at high recall when the whole graph sits in memory, but that behavior does not survive the move to SSDs. The paper starts from a simple empirical gap: on the SIFT dataset, on-disk DiskANN is 4.18x slower than in-memory Vamana at 0.9 recall and still 3.14x slower at 0.99 recall. That gap matters because the target applications are exactly the ones that already operate at billion-vector scale, such as recommendation and retrieval-augmented generation, where search often has only about 10 ms of budget and any saved latency can be reinvested into higher recall.

The authors argue that the bottleneck is not just "SSDs are slower than DRAM." It is the interaction between SSD behavior and the best-first traversal used by graph indexes. Best-first search chooses the current top-W unexplored candidates, reads them, waits for the whole batch, explores their neighbors, and only then decides the next batch. On SSDs, that schedule wastes time in two ways. First, compute and I/O are serialized across steps even though SSD reads are long enough to matter; with greedy search, I/O latency is 7.43x compute latency, and even with W = 8 compute is still 45.6% of I/O time. Second, each step waits synchronously for the tail of a batch, so the SSD's parallel I/O capability is underused; the measured pipeline utilization is only 76% at W = 8 and 58% at W = 32.

## Key Insight

The paper's central claim is that best-first order is helpful for minimizing wasted reads, but it is not required for convergence of graph search. A graph ANN index offers multiple paths to the same vector because nodes have multiple in-edges. Best-first search is therefore only one way to approximate a short path toward the query; it is not the unique valid path the way a B+-tree traversal is.

That observation exposes what the authors call a pseudo-dependency. To decide the next read, the system only needs the in-memory candidate pool of vector IDs and approximate distances. It does not need to wait until all ongoing I/O completes or until every fetched vector has been explored. Once that dependency is broken, the system can overlap compute with I/O and keep more SSD requests in flight. The second insight is that speculative I/O waste is not uniform during a search: it is worst in the early "approach" phase, when the search is still moving toward the target, and shrinks in the later "converge" phase, when the candidate pool already contains many real top-k neighbors. That makes a dynamic pipeline width plausible.

## Design

PipeSearch keeps the familiar candidate pool `P`, explored set `E`, and beam-width-like pipeline width `W`, but changes the schedule. Whenever the I/O queue is not full, it issues a read for the nearest unread vector currently in `P`. Independently, it explores any already fetched vector in an unexplored set `U`, inserts its neighbors into `P` using in-memory PQ distances, trims `P` back to length `L`, and polls for completed reads. In other words, the algorithm no longer obeys search-step boundaries; reading and neighbor expansion advance opportunistically.

PipeANN turns that basic low-latency algorithm into a full system with better throughput. It stores the on-disk graph as adjacency-list records, keeps PQ-compressed vectors in memory for cheap neighbor scoring, and adds a small sampled in-memory graph index for entry-point selection. Search then runs in two phases. In the approach phase, PipeANN uses the in-memory index to land near the query and starts PipeSearch with a small fixed pipeline width of 4, because speculative reads are most wasteful early on. In the converge phase, it estimates how many good candidates have effectively been recalled and widens the pipeline when finished reads are still yielding vectors that remain in the candidate pool; the default dynamic policy increments `W` when that ratio exceeds 0.9.

The other crucial optimization is how PipeANN reacts when several reads complete together. A naive refill policy would immediately stuff the queue back to capacity, but that creates many read-but-unexplored vectors and causes later I/Os to miss too much neighbor information. PipeANN instead alternates: issue one new read, explore one vector, update candidates, then decide again. This bounds the amount of missing information behind each I/O decision. The implementation uses `io_uring` with SQ polling, overlaps the first SSD miss with per-query PQ-table initialization, and relies on non-temporal AVX-512 loads to avoid polluting caches during that setup.

## Evaluation

The evaluation is broad enough to support the paper's main latency claim. On 100M-vector datasets, PipeANN delivers 39.1% of DiskANN's latency and 48.5% of Starling's latency on average at 0.9 recall10@10, while also beating SPANN by 70.6% in the high-recall regime. Those numbers are not obtained by comparing against weak baselines: the authors rebuild PipeANN, DiskANN, and Starling from the same graph indexes, switch DiskANN and Starling to `io_uring` for fairness, and tune each baseline's pipeline width for best latency.

The throughput story is more nuanced, which increases the paper's credibility. At 0.9 recall on 100M datasets, PipeANN has the highest throughput, averaging 1.35x over the compared on-disk systems because pipelining shortens the critical path without yet saturating disk bandwidth. But at 0.99 recall, Starling can outperform PipeANN in throughput because Starling's reordered layout cuts average I/O per search, whereas PipeANN still pays for speculative reads. The paper is explicit that its latency-oriented schedule does not dominate every point in the design space.

The billion-scale results are the strongest headline numbers. On SIFT1B and SPACEV1B, PipeANN reaches 0.719 ms and 0.578 ms latency at 0.9 recall, which is 1.28x and 1.09x the corresponding 100M-dataset latency, and 35.0% of DiskANN's latency in SIFT with 1.71x higher throughput. Compared with in-memory Vamana, PipeANN is still slower, but the gap narrows at high recall: 2.02x on SIFT and 1.14x on DEEP at 0.9 recall. The ablations also line up with the design narrative: raw PipeSearch cuts latency sharply but hurts throughput, the one-by-one refill optimization recovers throughput, and the dynamic pipeline mostly helps at higher recall where the converge phase is longer.

## Novelty & Impact

Relative to _Subramanya et al. (NeurIPS '19)_, PipeANN keeps the same broad graph-index family as DiskANN but changes the search schedule itself instead of only widening the batch. Relative to _Wang et al. (SIGMOD '24)_, it does not primarily reduce I/O count through layout reordering; it reduces latency by overlapping unavoidable I/O with compute, which is orthogonal to Starling's technique. Relative to _Chen et al. (NeurIPS '21)_, it tries to recover cluster-index-like latency without giving up the fine-grained pruning and throughput advantages of graph search at high recall.

The likely impact is on vector-search infrastructure where high recall matters but full in-memory indexes are too expensive. The paper is not a new index structure; it is a new way to schedule graph traversal against SSD hardware. That is a real contribution because it reframes the system bottleneck from "find a better graph" to "stop executing the graph algorithm in a DRAM-centric order."

## Limitations

The main limitation is built into the approach: speculative reads remain speculative. PipeANN reduces I/O waste, but it does not eliminate it, so at low recall it can lose throughput to an ideal greedy best-first implementation and at very high recall it can lose throughput to Starling's reordered layout. The paper also shows that low-recall searches are where PipeANN looks least like an in-memory system; at 0.8 recall on SIFT100M, it is 3.38x slower than Vamana because the search spends most of its time in the approach phase, where the widened pipeline cannot yet help much.

There are deployment limits too. PipeANN still needs under 40 GB of DRAM for billion-scale datasets, mostly for PQ-compressed vectors plus the sampled in-memory graph. The evaluation is read-only and single-node, on one NVMe SSD, so it does not address update costs, multi-SSD striping, or how the system behaves under mixed serving and maintenance workloads. The paper argues the same ideas should extend to RDMA or CXL-backed remote memory, but that claim is reasoned rather than implemented.

## Related Work

- _Subramanya et al. (NeurIPS '19)_ — DiskANN established the standard SSD-resident graph ANNS design with best-first beam search; PipeANN keeps the graph model but removes strict per-step compute/I/O ordering.
- _Wang et al. (SIGMOD '24)_ — Starling lowers search cost through record reordering and better entry-point selection, while PipeANN attacks latency through asynchronous pipelining and dynamic scheduling.
- _Chen et al. (NeurIPS '21)_ — SPANN uses a cluster-based on-disk layout so only one parallel disk read sits on the critical path, trading finer graph traversal for coarser but I/O-friendly search.
- _Zhang et al. (OSDI '23)_ — VBASE observes a two-phase, relaxed-monotonicity behavior in vector indexing with tags; PipeANN uses a related two-phase view to decide when larger speculative pipelines become safe.

## My Notes

<!-- empty; left for the human reader -->

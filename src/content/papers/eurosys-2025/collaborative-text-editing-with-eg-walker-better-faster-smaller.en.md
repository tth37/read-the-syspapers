---
title: "Collaborative Text Editing with Eg-walker: Better, Faster, Smaller"
oneline: "Eg-walker stores edits as an event DAG and builds CRDT state only during concurrent replay, cutting steady-state memory by 10x+ and long-branch merges from hours to milliseconds."
authors:
  - "Joseph Gentle"
  - "Martin Kleppmann"
affiliations:
  - "Independent"
  - "University of Cambridge"
conference: eurosys-2025
category: reliability-and-formal-methods
doi_url: "https://doi.org/10.1145/3689031.3696076"
code_url: "https://github.com/josephg/diamond-types"
tags:
  - pl-systems
  - formal-methods
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Eg-walker keeps collaborative text editing index-based like OT, but materializes CRDT state only while replaying concurrent history. That lets it preserve peer-to-peer convergence, merge two offline branches in `O((k+m) log(k+m))`, and avoid the permanent per-character metadata cost that makes existing text CRDTs expensive to load and keep open.

## Problem

Collaborative editors still face a split between OT and CRDTs. OT works well when divergence is short, but once two users edit offline or on long-lived branches, merge cost grows at least quadratically in the number of edits on each side. The paper’s asynchronous trace A2 takes 61.1 minutes to merge with its OT baseline.

Text CRDTs avoid pairwise transforms by giving characters stable IDs, supporting peer-to-peer replication. But those IDs, tombstones, and ordering metadata have to stay on disk and in memory while the document is open. The paper says even the best current text CRDTs still use over 10x OT’s memory for viewing and editing.

## Key Insight

Eg-walker’s key move is to separate durable history from merge state. It persistently stores only the event DAG of original index-based operations plus the current plain-text document; unique IDs and CRDT ordering are introduced only while replaying the concurrent suffix.

It can do that because it maintains two logical versions at once. The prepare version is where the next event should be interpreted; the effect version is the rebased state after all processed events have taken effect. By moving the prepare version backward and forward through the DAG while the effect version only advances, the algorithm can interpret operations in their native context and still emit a single transformed history.

## Design

Each event in the DAG stores an insertion or deletion, a unique event ID, and a parent set. Eg-walker topologically sorts the graph so it does not retreat and re-advance more history than necessary.

Its transient internal state is a CRDT-style sequence of character records, including tombstones. Every record carries the event that inserted it, a prepare-state `s_p`, an effect-state `s_e`, and ordering fields for concurrent insertions. `s_p` can be `NotInsertedYet`, `Ins`, or `Del_n`; `s_e` is just `Ins` or `Del`. Three operators drive replay:

- `apply(e)` interprets `e` in the prepare version, updates both views, and emits the transformed operation.
- `retreat(e)` removes `e` from the prepare version.
- `advance(e)` adds `e` back into the prepare version.

This replaces OT’s pairwise transform matrix with one transient structure. To keep index translation fast, Eg-walker uses an order-statistic B-tree to map input indexes to visible records and back to output indexes in `O(log n)`, plus a second B-tree mapping event IDs to affected records so retreat and advance also stay logarithmic.

The other decisive optimization is the critical version: a frontier that cleanly separates all earlier events from all later ones. Once replay reaches such a version, earlier events no longer affect how later ones transform, so Eg-walker can discard the whole internal state and keep only the event graph plus current text. If concurrency later reappears, it rebuilds only the suffix after the latest relevant critical version, starting from a placeholder for the unknown earlier text. For two offline branches of lengths `k` and `m`, merge cost becomes `O((k+m) log(k+m))` instead of OT’s `O(km)`.

## Evaluation

The benchmark suite contains seven editing traces: three sequential, two live concurrent traces, and two asynchronous traces reconstructed from Git histories. The comparison includes Automerge, Yjs, a TTF-style OT baseline, and a reference CRDT.

Strongest result: async merging. On trace A2, Eg-walker needs 23.5 ms while OT needs 61.1 minutes; on A1 it is 56.1 ms versus 6.3 seconds. That shows the paper changes the branch-merge regime, not just constants.

On sequential traces, where critical-version clearing skips most metadata work, Eg-walker merges full histories in 1.8 ms, 2.7 ms, and 3.6 ms for S1-S3. The reference CRDT takes 17.9 ms, 19.1 ms, and 26.9 ms on the same traces, and Automerge/Yjs are slower. Cached load time is only 0.01-0.12 ms because Eg-walker can open the final plain-text document without rebuilding CRDT metadata. The paper also reports steady-state memory one to two orders of magnitude lower because only the document text remains resident.

## Novelty & Impact

Eg-walker is novel because it moves the abstraction boundary. OT keeps index-based operations but explodes on long divergent histories; text CRDTs make concurrency easy by paying permanent metadata cost. Eg-walker keeps the index-based model, uses a CRDT only as a transient replay engine, and introduces critical-version clearing so the metadata disappears again when concurrency stops mattering. That is useful for local-first editors, peer-to-peer collaboration tools, and CRDT researchers.

## Limitations

The design assumes reliable broadcast, causal parent availability, and non-Byzantine replicas, and the paper only studies plain text. The worst-case replay bound for arbitrary DAGs is still `O(n^2 log n)`, and the authors report that a bad traversal order can make A2 up to 8x slower. The benchmark suite is stronger than prior work, but still has only seven traces, two live concurrent ones, and no end-to-end product study covering network transport, UI latency, or richer document types.

## Related Work

- _Nichols et al. (UIST '95)_ - Jupiter keeps index-based operations but pays pairwise transformation costs; Eg-walker avoids that blowup on long branches.
- _Nicolaescu et al. (GROUP '16)_ - YATA-style shared editing keeps per-character IDs and ordering metadata live for the document lifetime; Eg-walker uses similar ordering ideas only during replay.
- _Attiya et al. (PODC '16)_ - the strong list specification is the correctness target Eg-walker claims to satisfy.
- _Roh et al. (JPDC '11)_ - replicated abstract data types keep identifier-heavy state persistently, whereas Eg-walker keeps it transient and suffix-local.

## My Notes

<!-- empty; left for the human reader -->

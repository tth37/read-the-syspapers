---
title: "Impeller: Stream Processing on Shared Logs"
oneline: "Impeller uses tagged shared-log records as progress markers, so stream operators can atomically commit work across multiple substreams without Kafka-style transactions."
authors:
  - "Zhiting Zhu"
  - "Zhipeng Jia"
  - "Newton Ni"
  - "Dixin Tang"
  - "Emmett Witchel"
affiliations:
  - "Lepton AI Inc."
  - "Google LLC"
  - "The University of Texas at Austin"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717485"
code_url: "https://github.com/ut-osa/impeller-artifact"
tags:
  - fault-tolerance
  - storage
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Impeller is a distributed stream processor built on a shared log. Its core move is a progress marker: one log record tagged for every relevant downstream substream, task log, and optionally change log, so an operator can atomically commit exactly-once progress without a Kafka-style transaction coordinator. On NEXMark, that yields 1.3×-5.4× lower p50 latency, or 1.3×-5.0× higher saturation throughput, than Kafka Streams.

## Problem

Exactly-once stream processing is hard because failures happen in the middle of computation. A task may have consumed an input and updated local state, but not yet made all downstream outputs durably visible. In a distributed DAG, that gets worse: one input can fan out to multiple downstream substreams, and after recovery the system has to know which outputs and state changes were the committed consequences of that input and which were partial side effects that must be ignored.

The standard fixes are expensive in different ways. Checkpointing gives a simple recovery story, but large state snapshots raise normal-path latency and recovery cost. Kafka Streams reduces the checkpoint burden with logging plus checkpointing, yet it still has to coordinate processed input positions, state updates, and outputs across multiple streams through a transaction protocol. The paper asks whether modern shared logs, which already provide global order, selective reads, and user-defined string tags, can absorb that coordination work directly.

## Key Insight

The paper's key claim is that progress itself can be represented as an atomically appended log record. If a task writes one progress marker whose tags include every downstream substream that should observe the commit, plus the task's own recovery stream, that record becomes a consistent cut across multiple logical streams. Downstream operators only treat upstream outputs as committed when an upstream marker says so, which turns multi-stream atomicity into one append instead of a two-phase protocol.

For stateful operators, the same idea extends by logging state mutations in the shared log. A progress marker that names the relevant input, output, and change-log LSN ranges is enough to reconstruct a consistent prefix after failure. The total order of the log matters because it lets Impeller summarize progress with scalar LSNs instead of per-stream vectors or external metadata tables.

## Design

Impeller executes a query as stages and tasks. Each stream is partitioned into substreams, and each log record carries tags such as `(X, 2a)` so only the intended consumer task reads it. Shared-log selective reads let tasks pull their own substream without separate physical logs per edge in the dataflow graph.

A stateless task periodically writes a progress marker recording the input range it has processed and the output ranges it produced. That marker is appended once, but it is tagged for all downstream substreams plus `(T, task id)` in the task log. Because the same physical record appears in all those logical streams, downstream consumers observe one atomic commit point even when an operator fans out to multiple outputs.

Stateful tasks additionally append updates to a change log tagged `(C, task id)`. During normal execution they may see upstream records whose status is not yet known, so they buffer and classify records as committed, uncommitted, or still unknown based on upstream progress markers. On recovery, a task reads its task log to find the latest marker, restores the most recent checkpoint if one exists, and replays the change log up to that marker. Impeller also addresses zombie tasks: the task manager keeps an instance number for each task in shared-log metadata, and conditional appends ensure that only the newest instance can commit a progress marker. Optional asynchronous checkpoints shorten recovery further, while the shared log remains the source of truth for streams, task logs, and change logs.

## Evaluation

The implementation is 16,895 lines of Go on top of Boki. It supports scan, filter, and map, plus stateful operators such as groupby, aggregates, stream-stream join, stream-table join, and table-table join. Experiments run on 13 EC2 c5d.2xlarge nodes: 4 storage nodes, 4 input generators, 4 compute nodes, and 1 control-plane node.

One useful sanity check is that Boki is not inherently a lower-latency transport than Kafka. For a 16 KiB append-to-consume test, Impeller's log is 1.3×-1.8× slower than Kafka at p50, so the end-to-end wins are not explained by a faster underlying messaging system. On NEXMark, Impeller is close to Kafka Streams on the simplest stateless queries, but for stateful Q3-Q8 it achieves 1.3×-5.4× lower p50 latency and 1.2×-5.7× lower p99 latency. Under a 1 second p99 limit, it sustains 1.3×-5.0× more input throughput. Compared with an aligned-checkpoint baseline implemented inside Impeller, progress markers deliver up to 4.5× lower p50 latency and 5.8× lower p99 latency. Recovery on Q8 also benefits from asynchronous checkpoints: recovery time drops from 3.858-4.758 seconds to 0.270-0.297 seconds, a 14×-16× speedup.

## Novelty & Impact

Impeller is not just stream processing on a new storage layer. Its novelty is using tagged, selectively readable shared-log records as the commit protocol for exactly-once execution. That collapses what Kafka Streams spreads across a coordinator, transaction stream, and per-stream bookkeeping into one mechanism driven by the log's own semantics.

The paper should matter to researchers working on shared logs, fault-tolerant dataflow, and low-latency exactly-once systems. It shows that log features that look like storage conveniences, especially total order and tags, can be lifted into the consistency protocol of the execution engine itself.

## Limitations

The design assumes a powerful log substrate: global ordering, multi-tag selective reads, shared metadata, and conditional append. If the storage layer only exposes ordinary partitions and offsets, Impeller's main technique disappears and the system falls back toward Kafka-style coordination.

The evaluation is also narrower than the mechanism's ambition. The paper uses only NEXMark, assigns one shared-log instance per query for simplicity, and explicitly leaves deeper treatment of skew and cross-query interference out of scope. Stateful operators still rely on change logs and an external checkpoint store, so Impeller reduces checkpoint pressure rather than eliminating recovery machinery. Finally, the biggest gains come from stateful workloads; the simplest stateless queries are closer to parity than to a decisive win.

## Related Work

- _Wang et al. (SIGMOD '21)_ - Kafka Streams also combines logging and checkpoints for exactly-once streaming, but it relies on a coordinator-driven multi-stream transaction protocol that Impeller tries to avoid.
- _Carbone et al. (VLDB '17)_ - Apache Flink's state-management design popularized checkpoint-centric exactly-once recovery, while Impeller targets the normal-path latency cost of that approach.
- _Akidau et al. (VLDB '13)_ - MillWheel materializes record IDs for deduplication, whereas Impeller records committed progress as log positions and change-log ranges.
- _Jia and Witchel (SOSP '21)_ - Boki provides the tagged shared-log substrate Impeller builds on, but Impeller contributes the streaming-specific progress protocol and recovery logic.

## My Notes

<!-- empty; left for the human reader -->

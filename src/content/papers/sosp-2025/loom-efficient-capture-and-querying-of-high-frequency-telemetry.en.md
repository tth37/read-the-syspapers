---
title: "Loom: Efficient Capture and Querying of High-Frequency Telemetry"
oneline: "Loom stores HFT in a hybrid log plus sparse chunk summaries, sustaining 9M records/s without drops while keeping observability queries interactive."
authors:
  - "Franco Solleza"
  - "Shihang Li"
  - "William Sun"
  - "Richard Tang"
  - "Malte Schwarzkopf"
  - "Andrew Crotty"
  - "David Cohen"
  - "Nesime Tatbul"
  - "Stan Zdonik"
affiliations:
  - "Brown University"
  - "University of Washington"
  - "Northwestern University"
  - "Intel"
  - "MIT"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764853"
code_url: "https://github.com/fsolleza/loom"
tags:
  - observability
  - storage
  - databases
category: storage-and-databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Loom targets the combination that existing telemetry backends miss: complete capture of high-frequency telemetry, interactive queries, and low probe effect on the host being observed. It does this by appending records into a hybrid log and indexing fixed-size chunks with lightweight histogram summaries and a coarse timestamp index instead of maintaining precise per-record indexes. The result is up to `9M` records/s ingest without drops, with common observability queries finishing in seconds rather than tens or hundreds of seconds.

## Problem

Engineers debugging tail latency often need application events, syscalls, packets, and hardware counters at the same time. Each source can emit millions of records per second, and the interesting anomalies are rare and not known in advance. In the paper's Redis example, six slow requests out of `9M` correlate with six mangled packets out of `35M`, so uniform sampling preserves neither enough slow requests nor the causative packets.

That exposes a three-way conflict. TSDBs like InfluxDB keep queries fast by maintaining indexes on the write path, but under HFT those indexes either induce probe effect or force data drops. Raw logs and files keep up with ingest, but queries become long scans or custom scripts. FishStore preserves ingest performance with exact PSF indexes, yet those indexes do not naturally support arbitrary lookback windows, percentiles, or other data-dependent observability queries.

## Key Insight

Loom's key claim is that observability queries usually need cheap chunk-level filtering, not precise per-record indexing. By summarizing each fixed-size chunk with per-bin counts, min/max/sum values, and time ranges, Loom can skip most irrelevant data later while keeping writes close to raw append cost.

The second half of the idea is to keep ingest and query paths decoupled. Loom never exposes a partially built chunk summary to readers. Queries may need to scan the small active chunk directly, but writers avoid synchronization on hot metadata, which is exactly what lets Loom sustain HFT ingest.

## Design

Loom runs as a library inside a monitoring daemon such as OpenTelemetry Collector. It keeps three append-only hybrid logs spanning memory and persistent storage: a record log for raw telemetry, a chunk index for value-oriented summaries, and a timestamp index for coarse navigation by time.

The record log interleaves records from many sources and links each source's records through back-pointers. Writes land in fixed-size in-memory blocks such as `64 MiB`; when one fills, Loom flushes it in the background and switches to a second block. The indexing unit is a smaller fixed-size chunk such as `64 KiB`. For indexed sources, Loom incrementally builds a histogram-based chunk summary with user bins plus two outlier bins, so range and tail queries remain efficient without precise indexing.

The timestamp index is always on and stores periodic record timestamps plus chunk-finalization events. Query execution is intentionally narrow: `raw_scan` walks a source over a time range, `indexed_scan` filters by time and value range, and `indexed_aggregate` answers min/max/count/sum and percentiles by combining chunk summaries with selective record scans. Readers copy immutable prefixes of the in-memory blocks via lock-free snapshots; if a block is flushed during the copy, Loom detects that race and resumes from persistent storage instead of blocking writers.

## Evaluation

The evaluation uses two realistic case studies. The Redis workload rises from `865k` records/s to about `7M` records/s across three debugging phases and exercises percentile, correlation, and time-window scans. The RocksDB workload runs at `4.7M` to `8M` records/s and focuses on max, percentile, and selective-count queries. Across both, Loom and FishStore ingest complete data, while InfluxDB drops `38%` to `93%` of records.

Loom's main win is query latency. On Redis, it is `14x` to `97x` faster than idealized preloaded InfluxDB and `1.5x` to `10x` faster than FishStore in the first two phases. In the hardest third phase, the maximum-latency-request query finishes in `0.4 s` on Loom versus `4.3 s` on InfluxDB-idealized and `18.3 s` on FishStore. On RocksDB, Loom serves the main max and tail-latency queries in `0.5` to `3.2 s`, while InfluxDB-idealized needs `23` to `380 s` and FishStore needs `38` to `48 s`.

The resource story is equally important. During RocksDB Phase 3, Loom causes `4.83%` probe effect, close to writing a raw file at `4.10%`, and much lower than FishStore with indexes at `9.94%` or InfluxDB at `14.08%`. The ablation study also shows both indexes matter: without them, latency climbs into the hundreds of seconds.

## Novelty & Impact

Loom's novelty is the design point between a TSDB and a raw log: append-only ingest plus observability-specific chunk summaries that are expressive enough for range scans, aggregates, percentiles, and time-based correlations, yet cheap enough to stay on the HFT write path.

That matters because many observability systems either aggregate and discard events too early or preserve them in forms that are hard to query. Loom shows that a single-host debugging backend can keep complete recent telemetry and still remain interactive.

## Limitations

Loom is explicitly for recent, ad hoc, single-host analysis, not archival telemetry storage. Its durability is also weaker than a database's: records acknowledged to clients can still be lost if the machine or monitoring daemon fails before the active in-memory block is flushed, with the loss bounded to the freshest block, roughly `64 MiB` or a few hundred milliseconds of data.

The index design also needs operator judgment. Histogram choices are workload-specific, new indexes apply only to future data, and exact short-lookback queries can still favor FishStore because Loom deliberately tolerates chunk-level false positives. Finally, Loom's operator set is intentionally small; joins and heavier analyses must run outside Loom, and the distributed design is only sketched.

## Related Work

- _Xie et al. (SIGMOD '19)_ - FishStore also targets high-rate observability ingest, but its PSF indexes are exact and rigid; Loom uses chunk summaries plus a time index to support percentiles and flexible lookback windows.
- _Lockerman et al. (OSDI '18)_ - FuzzyLog demonstrates the ingest advantages of append-only logs, whereas Loom adds observability-oriented sparse indexes so the log remains queryable on-host.
- _Solleza et al. (CIDR '22)_ - Mach argues that observability needs dedicated data management, but it is oriented toward metrics storage; Loom instead focuses on complete capture and drill-down over recent single-host HFT.
- _Zhang et al. (NSDI '23)_ - Hindsight traces rare distributed edge cases across services, while Loom is a local storage-and-query substrate for retaining and correlating raw HFT on one machine.

## My Notes

<!-- empty; left for the human reader -->

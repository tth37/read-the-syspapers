---
title: "Skybridge: Bounded Staleness for Distributed Caches"
oneline: "Skybridge replicates only recent write metadata out of band, then uses gap-detected queries and bloom filters to keep TAO caches within a 2-second staleness bound."
authors:
  - "Robert Lyerly"
  - "Scott Pruett"
  - "Kevin Doherty"
  - "Greg Rogers"
  - "Nathan Bronson"
  - "John Hugg"
affiliations:
  - "Meta Platforms Inc."
  - "OpenAI"
conference: osdi-2025
tags:
  - caching
  - datacenter
  - fault-tolerance
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Skybridge is a metadata-only side channel that tells TAO whether a specific cached key changed recently when Wormhole is lagging. By allowing out-of-order delivery and detectable gaps, it avoids turning a lagging shard into a full-shard cache miss.

## Problem

Meta fronts millions of MySQL shards with TAO caches across many regions, so it relies on asynchronous replication. That keeps latency low but makes write visibility unbounded; the paper shows both user-facing anomalies and an outage caused by downstream readers missing fresh writes.

TAO already stores item HLCs and shard watermarks, but a watermark older than 2 seconds makes every key on that shard look stale. Because the workload is heavily read-skewed, most of those keys were never rewritten, so shard-level checking causes false-positive refills, cross-region latency, and thundering herds. Stronger defaults such as linearizability or global read-your-writes are too expensive, so Meta needs a fine-grained stale-key oracle.

## Key Insight

Skybridge observes that bounded staleness for caches needs only recent-write evidence, not replicated values. It therefore replicates compact `<key, HLC>` metadata and leaves data refill on TAO's existing upstream path.

That enables replication with gap detection (RGD). Skybridge may deliver metadata out of order and may report incomplete results, as long as missing data is detectable. If a queried interval is complete and contains no newer HLC, the cache hit is safe; if the interval is incomplete, TAO conservatively refills. The freshness question therefore becomes much cheaper than full replication.

## Design

On the read path, TAO computes `HLCcache = max(HLCitem, HLCwatermark)`. If that is within the 2-second bound, it serves locally. Otherwise it checks the lag interval using host-local bloom filters streamed for lagging shards and, if needed, `getWrites(key, interval)`, which returns the newest matching HLC plus a completeness bit. A newer HLC triggers an HLC-conditional upstream refill; an incomplete answer also refills, but only for that key.

Completeness comes from Skylease and heartbeats on the write path. TAO writers open non-exclusive shard leases, derive HLC bounds from unsent heartbeat slots, and attach those bounds to MySQL writes so the DB aborts if it would mint an out-of-range HLC. After commit, the client records `<key, HLC>` into the matching heartbeat. Skybridge aggregates heartbeats into write windows and marks a window complete only after Skylease has sealed the lease-holder set beyond that interval and all required heartbeats have arrived. Cross-region replication then pulls short streams of windows from primary-region replicas, prioritizes newer ones, and tolerates duplicates and reordering because the payload is CRDT-like metadata rather than ordered data updates.

## Evaluation

Meta evaluates the property it actually wants: whether a sampled write is visible after 2 seconds at all TAO tiers in all regions. Without Skybridge, TAO achieves 99.993% 2-second consistency and often falls below 99.985%. With normal best-effort Skybridge it reaches 99.9993%, and with fail-closed requests it reaches 99.99998%.

Skybridge matters mostly because it prevents unnecessary refills. Wormhole watermarks alone prove 99.96% of reads fresh; preloaded bloom filters lift that to 99.98%; authoritative Skybridge queries raise it to 99.9996%, leaving only 0.0004% of reads to go upstream. P99 replication lag is about 700 ms, P99.99 about 1.5 seconds outside spikes, and the whole system uses 0.54% of TAO's footprint while retaining 93-109 seconds of recent writes. The main blind spot is shard lag beyond that retention window.

## Novelty & Impact

Compared with _Shi et al. (OSDI '20)_, Skybridge is not a per-user read-your-writes mechanism; compared with _Yang et al. (PVLDB '23)_, it targets caches in front of millions of shards rather than replica reads. Its contribution is the design point itself: replicate only freshness metadata, permit reorder and detectable loss, and rely on an existing authoritative refill path for correctness.

## Limitations

Default bounded staleness is still best-effort because TAO rate-limits expensive checks and may fail open to protect availability; the strongest guarantee comes only from fail-closed requests. The system is also bounded by in-memory retention, needs good time synchronization and HLC-bounded MySQL writes, and assumes a fairly intricate leasing control plane. Dynamic resharding and global secondary indexes remain future work.

## Related Work

- _Shi et al. (OSDI '20)_ - FlightTracker provides read-your-writes through per-user tickets, while Skybridge provides a coarser but default-on time bound for all writes.
- _Yang et al. (PVLDB '23)_ - PolarDB-SCC also uses fine-grained staleness metadata, but it targets strongly consistent replica reads for one database rather than globally distributed cache hierarchies.
- _An and Cao (PVLDB '22)_ - MCC improves cache consistency through eviction and version-selection policy, whereas Skybridge adds an out-of-band metadata stream to handle lagging invalidation paths.
- _Loff et al. (SOSP '23)_ - Antipode propagates causal lineage across services; Skybridge intentionally settles for bounded staleness because that is deployable at Meta's default scale.

## My Notes

<!-- empty; left for the human reader -->

---
title: "McQueen: Apple’s Geo-Distributed Object Store at Exabyte Scale"
oneline: "Shows how Apple moved from dual-region replication to five-region XOR segmentation, cutting replication factor from 2.40 to 1.50 at exabyte scale."
authors:
  - "Benjamin Baron"
  - "Aline Bousquet"
  - "Eric Metens"
  - "Swapnil Pimpale"
  - "Nick Puz"
  - "Marc de Saint Sauveur"
  - "Varsha Muzumdar"
  - "Vinay Ari"
affiliations:
  - "Apple"
conference: fast-2026
category: cloud-and-distributed-storage
tags:
  - storage
  - fault-tolerance
  - datacenter
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

McQueen is Apple’s production geo-distributed object store, serving billions of requests over several exabytes. The paper explains the move from McQueen 1.0’s local LRC plus full cross-region replication to McQueen 2.0’s five-region `4+1` XOR segmentation, cutting the overall replication factor from `2.40` to `1.50` while accepting slower full-object GETs.

## Problem

Apple wants one object store for iCloud data, media files, Maps assets, and internal datasets. Those workloads span tiny metadata objects to multi-GB video parts and mix user-facing latency with long-term durability.

McQueen 1.0 already offered strong availability via two active-active regions, intra-stamp erasure coding, degraded reads, and asynchronous cross-stamp replication. But after a decade, three costs dominated: `(20, 2, 2)` LRC plus a full remote replica yields a `2.40` replication factor; fixed-capacity stores force large clients to manage multiple endpoints; and the Cassandra metadata layer makes a unified multi-region deployment hard to scale cleanly.

## Key Insight

McQueen’s key idea is to separate redundancy by failure domain. Inside a stamp, LRC remains the right mechanism because local failures demand efficient repair. Across regions, whole-object mirroring is too expensive, so McQueen 2.0 splits each object into four data segments and one XOR parity segment. Any four recover the fifth. That invariant lets metadata track segment locations rather than twin objects, which in turn enables a single elastic endpoint and system-managed rebalancing.

## Design

McQueen 1.0 consists of two stamps in different regions. Each stamp has load balancers, stateless request handlers, a coordinator, metadata, and JBOD-backed storage hosts. Objects land in large containers; new data first goes to five-way replicated container clusters, then sealed clusters are converted to LRC-coded form, initially `(12, 2, 2)` and later `(20, 2, 2)`. The coordinator handles placement, compaction, and repair. Reads fall back from local data to LRC reconstruction and finally to the peer stamp.

McQueen 2.0 keeps the stamp abstraction but deploys it across five regions. A PUT handler splits each object or multipart part into four data segments and one XOR parity segment, sends them to five regions, and completes once four land. Missing segments are repaired asynchronously. GETs read the needed data segments or reconstruct one via parity; range GETs fetch only the relevant bytes when possible.

The control-plane change is ClassVI, a geo-distributed metadata store using RocksDB and Raft for row-level strong consistency. Handlers combine fast local inconsistent reads with later consistent validation to prefetch segments. McQueen 2.0 also adds a unified DNS endpoint, capacity-derived stamp weights, file-level rebalancing of sealed containers, geo-routing, and inter-stamp load-balancer bypass.

## Evaluation

The evaluation uses one month of live production traffic, so it reflects real workloads but not a perfectly controlled 1.0 versus 2.0 comparison. The main latency result is that 2.0 does not materially hurt writes: PUT latency remains similar because handlers stream into replicated containers and can issue segment writes in parallel. GET time to first byte is only slightly worse, while full-object GETs are about `50 ms` slower on average because some segments come from remote regions.

The durability result is stronger. In 1.0, cross-stamp replication finishes within `10 s` for `90%` of objects. In 2.0, `99.99%` of PUTs store all five segments inline, so only `0.01%` need asynchronous repair. Cross-region reconstruction adds about `0.3 ms` at p90; the bigger penalty is failover network distance. Inside a stamp, degraded reads add about `2 ms` of reconstruction work at p90 and roughly `30 ms` more latency up to p50. Apple also reports up to `60%` server-side latency reduction from pre-migration optimizations and `22%` lower p50 latency from load-balancer bypass.

## Novelty & Impact

McQueen’s contribution is the production synthesis: split redundancy by failure domain, rebuild metadata and placement around segments, and migrate a live exabyte store without downtime. Relative to _Muralidhar et al. (OSDI '14)_ and _Pan et al. (FAST '21)_, it is an operational account of geo-distributed exabyte storage. Relative to _Noghabi et al. (SIGMOD '16)_, it emphasizes strongly consistent geo-distributed metadata.

## Limitations

McQueen 2.0 tolerates one region failure, not two, so requests depending on missing segments fail when two or more regions are down. Its full-object GET path is unavoidably slower because geography is on the critical path. The comparison is partly observational because workloads changed during migration, and the durability table depends on standard independence and exponential-repair assumptions.

## Related Work

- _Muralidhar et al. (OSDI '14)_ — f4 also uses regional XOR coding, but McQueen applies the idea to a broader multi-tenant Apple object store.
- _Noghabi et al. (SIGMOD '16)_ — Ambry is geo-distributed immutable object storage; McQueen instead supports active-active writes with strongly consistent metadata.
- _Pan et al. (FAST '21)_ — Tectonic targets similar scale, while McQueen emphasizes multi-region redundancy and user-facing availability.

## My Notes

<!-- empty; left for the human reader -->

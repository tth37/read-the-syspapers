---
title: "Nemo: A Low-Write-Amplification Cache for Tiny Objects on Log-Structured Flash Devices"
oneline: "Nemo shrinks flash-cache hash space, flushes and evicts at Set-Group granularity, and uses Bloom-filter indexing to push tiny-object write amplification near the minimum."
authors:
  - "Xufeng Yang"
  - "Tingting Tan"
  - "Jingxin Hu"
  - "Congming Gao"
  - "Mingyang Liu"
  - "Tianyang Jiang"
  - "Jian Chen"
  - "Linbo Long"
  - "Yina Lv"
  - "Jiwu Shu"
affiliations:
  - "Xiamen University, Xiamen, China"
  - "Chongqing University of Posts and Telecommunications, Chongqing, China"
  - "Openharmony Community, Beijing, China"
  - "Tsinghua University, Beijing, China"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790191"
code_url: "https://github.com/XMU-DISCLab/Cachelib-Nemo"
tags:
  - storage
  - caching
  - databases
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Nemo argues that on modern log-structured SSDs, the main waste in tiny-object caching is no longer device GC but application-level rewrites caused by cache layout. It keeps set-associative lookup, but flushes and evicts large Set-Groups only after they are highly filled, then uses Bloom-filter indexing to keep metadata small. On the paper's Twitter-trace experiments, steady-state write amplification drops to `1.56` versus FairyWREN's `15.2`.

## Problem

Tiny-object KV caches must balance miss ratio, latency, metadata cost, and flash wear. Log-structured designs batch writes well, but exact indexing is expensive when objects are only a few hundred bytes. Set-associative designs save memory, but a tiny insertion can still trigger a full 4 KB set rewrite, so application-level write amplification becomes the dominant cost.

The paper argues that ZNS and FDP mostly solve device-level amplification, not cache-level amplification. In Kangaroo and FairyWREN, objects still migrate into a large set hash space, so each rewrite carries only a few new objects. After reproducing FairyWREN and fixing bugs in the released code, the authors measure more than `15x` write amplification on Twitter traces with average object size `246 B`, and attribute that to low set fill rate rather than SSD internals.

## Key Insight

The core claim is that tiny-object caches should intentionally raise collision probability before a flush so that each flash write carries many more useful objects. Nemo therefore abandons FairyWREN's log-to-set migration path and writes highly filled Set-Groups directly to flash.

That works because the logical lookup unit and the physical batching unit do not need to match. Nemo keeps set associativity inside each Set-Group, but shrinks the hash space and delays persistence until many sets in the group are well filled. Write amplification then becomes roughly the reciprocal of Set-Group fill rate.

## Design

Nemo stores objects in immutable on-flash Set-Groups (SGs), each made of many 4 KB sets, and keeps a small number of buffered SGs in memory. Flush and eviction both happen at SG granularity, so the system never has to migrate from a front log into individual sets.

The first challenge is short-term hash skew: one set in a fresh SG can fill early while its neighbors remain sparse. Nemo counters that with buffered in-memory SGs, probabilistic flushing, and hotness-aware writeback from an evicted SG into the SG about to be flushed. Together these mechanisms delay persistence until the SG is much fuller.

The second challenge is indexing. Exact object-to-SG mappings would destroy the memory savings, so Nemo uses Parallel Bloom Filter Groups (PBFGs). Filters are organized by set offset rather than by SG: the same-offset sets across many SGs form one Set-level PBFG. A lookup hashes the key to its intra-SG set, queries that PBFG for candidate SGs, and reads those sets in parallel.

The third challenge is eviction. Nemo combines recency from the in-memory PBFG cache with a 1-bit access bitmap, then periodically cools entries whose PBFGs are no longer hot. That keeps metadata cheap while still letting the system reinsert genuinely hot objects during SG eviction.

## Evaluation

The evaluation implements Nemo inside CacheLib on a 24-core server with `128 GB` DRAM and a Western Digital ZN540 ZNS SSD. Using merged Twitter traces with average object size `246 B`, Nemo reaches steady-state write amplification of `1.56`, versus `15.2` for FairyWREN, `16.31` for a plain set-associative cache, and `55.59` for Kangaroo. A fully log-structured cache gets `1.08`, but at more than `100 bits/object` of metadata.

Nemo also stays compact. Its metadata cost is `8.3 bits/object`, slightly below FairyWREN's `9.9 bits/object`. Tail latency is much steadier because Nemo issues occasional batched writes instead of constant small rewrites: `p99` read latency is about `131 us` versus `350 us` for FairyWREN, and `p9999` is `523 us` versus `1488 us`. Miss ratio remains similar. The ablation is consistent with the design story: SG fill rate rises from `6.78%` in naive Nemo to `64.13%` with buffered SGs plus probabilistic flushing, and to `89.34%` after hotness-aware writeback.

## Novelty & Impact

Relative to _McAllister et al. (OSDI '24)_, Nemo argues that log-to-set migration is the wrong abstraction for tiny objects. Relative to classic log-structured flash caches, its novelty is combining near-log-structured write behavior with approximate indexing that keeps memory in the range of compact set-associative designs.

## Limitations

Nemo buys write efficiency with more complicated reads. The paper reports read amplification more than `3x` higher than FairyWREN, even though latency still improves because those reads are parallelizable and writes interfere less. So the design depends on SSD parallelism and on workloads where extra candidate-set reads are cheaper than repeated rewrites.

The hotness and indexing logic are also approximate. PBFG false positives can trigger extra reads, and group-level recency can let cold objects ride along inside a hot set. The evaluation is convincing on one ZNS SSD, but it leaves open how stable the parameters are across different devices and workload mixes. The paper also notes that making Bloom filters more accurate can backfire by scattering the on-flash index pool.

## Related Work

- _McAllister et al. (SOSP '21)_ — Kangaroo introduced the hierarchical front-log/back-set structure for billions of tiny objects, whereas Nemo argues that the migration into large set spaces is exactly what keeps write amplification high.
- _McAllister et al. (OSDI '24)_ — FairyWREN folds garbage collection into log-to-set migration to improve Kangaroo, but Nemo shows that even this refined hierarchy still leaves application-level write amplification far from ideal.
- _Berg et al. (OSDI '20)_ — CacheLib provides the production set-associative substrate Nemo builds on, but Nemo changes the physical write unit from per-set rewrites to SG-level batched persistence.
## My Notes

<!-- empty; left for the human reader -->

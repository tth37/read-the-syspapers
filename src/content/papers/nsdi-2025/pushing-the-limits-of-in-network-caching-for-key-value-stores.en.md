---
title: "Pushing the Limits of In-Network Caching for Key-Value Stores"
oneline: "OrbitCache keeps hot key-value pairs circulating as packets instead of switch entries, letting a Tofino switch cache variable-length items and rebalance skewed workloads."
authors:
  - "Gyuyeong Kim"
affiliations:
  - "Sungshin Women’s University"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
tags:
  - caching
  - smartnic
  - networking
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`OrbitCache` replaces the usual "store hot items in switch SRAM" design with a different one: keep full key-value replies circulating inside the switch data plane and let requests wait as tiny metadata records. That shift removes the usual 16-byte-key and 128-byte-value limits of prior programmable-switch caches, and on a Tofino prototype it improves throughput by up to `3.59x` over an uncached baseline on highly skewed workloads.

## Problem

The paper starts from a mismatch between what programmable-switch caches can do in principle and what production key-value workloads actually look like. Systems such as `NetCache`, `DistCache`, and `FarReach` show that putting a cache into the switch can rebalance read-heavy stores far more cheaply than adding replicated cache servers. But they inherit the switch ASIC's structural limits: match keys are narrow, per-stage byte access is tiny, and only a small number of stages can be devoted to caching. In practice, that constrains prior designs to roughly 16-byte keys and 128-byte values.

That is too small for many real traces. The paper cites Twitter and Facebook workloads in which keys are often tens of bytes and many values are under 1 KB, meaning they still fit within one MTU-sized packet but not within previous in-switch cache formats. For 42 of 54 Twitter workloads, prior schemes cannot cache even one item because either the key or the value exceeds the hardware limit. The problem is therefore not that previous work fails on giant objects; it fails on ordinary small objects that are merely larger than the switch's table format.

A straightforward extension also does not work well. One could imagine recirculating requests multiple times to read a larger value from fragmented switch memory, but the switch has only one internal recirculation port. If every request loops several times, that port becomes the bottleneck immediately. The paper's core question is how to exploit the switch's packet-processing throughput without forcing the data itself into the switch's tiny random-access memories.

## Key Insight

The key idea is to stop thinking of the cache as data stored in switch tables. `OrbitCache` instead represents each cached item as a reply packet that keeps revisiting the switch data plane through the switch's built-in recirculation path. Requests no longer "read" cached values out of SRAM. They simply insert a small record containing client IP, port, and sequence number into a per-key request table. The circulating cache packet then checks whether anyone is waiting for its key; if so, the switch clones it, forwards one copy to the client, and keeps another copy circulating.

This inversion solves two different problems at once. First, the full key and value now live in the packet payload, so switch table widths no longer cap the item size as long as the item fits in one packet. Second, the full key is present when the reply returns to the client, so the switch can index the cache by a fixed-size key hash while the client resolves rare hash collisions by comparing the returned key against the requested key and issuing a correction request if needed. The important claim is that recirculation is affordable when only a small, fixed set of cache packets loops in the switch, but not when every request does.

## Design

The switch data plane has five main components. A lookup table maps a 128-bit key hash to a cache index. A state table marks each cached item as valid or invalid so reads do not observe stale data while a write is in flight. A request table buffers pending reads using a circular queue per cached key, implemented with multiple register arrays and pointer registers. Key counters track per-item popularity plus global cache-hit and overflow statistics for the control plane. Finally, a cloning module uses the switch packet replication engine to send one cache-packet copy to the client and one back to the recirculation port.

Read processing is intentionally asymmetric. On a miss, the request simply goes to the storage server. On a cache hit for a valid item, the switch inserts request metadata into that key's logical queue and drops the packet. Later, when the corresponding cache packet arrives from the recirculation port, it probes the request table. If it finds a waiting client, it rewrites the packet header with that client's metadata, clones the packet, forwards the original to the client, removes the consumed request record, and recirculates the clone so it can serve future requests.

Writes use an invalidation-based coherence protocol. A write to a cached key marks the item's state invalid and is always forwarded to the storage server. The server includes the new value in the write reply, letting the switch both validate the item again and create a fresh cache packet by cloning the reply. Cache updates are handled by the control plane: servers periodically report hot uncached keys, the switch reports popularity for already cached keys, and the controller evicts a victim entry, installs a new lookup-table mapping, and fetches the new value from the appropriate server.

Two design choices matter in practice. First, the request table isolates requests by key, so a burst on one hot key does not scramble queue state for others. Second, `OrbitCache` deliberately keeps the cache small. The paper leans on the small-cache effect: a few hot items can already balance a skewed store, and adding too many circulating packets only increases queueing delay on the recirculation path.

## Evaluation

The prototype uses `P4_16` on an Intel Tofino 1 switch and a server cluster with 100 GbE NICs. Most experiments emulate a rack with 32 storage servers, 10 million key-value pairs, 16-byte keys, and a bimodal value distribution in which `82%` of items are 64-byte values and `18%` are 1024-byte values. `OrbitCache` is compared primarily with `NoCache` and `NetCache`, with focused comparisons to `Pegasus` and `FarReach`.

The headline result is on skewed reads. Under a Zipf-0.99 key distribution, `OrbitCache` achieves `3.59x` the throughput of `NoCache` and `1.95x` the throughput of `NetCache`, while keeping server-side throughput roughly even across machines. It also scales almost linearly as the number of storage servers grows from 4 to 64, whereas the baselines fail to preserve balancing efficiency. Against production-inspired Twitter workloads, it is consistently the fastest of the three schemes because it can cache hot items that `NetCache` simply cannot represent.

The costs are visible but bounded. `OrbitCache` has about `1 us` higher latency than `NetCache` because requests must wait for a circulating packet to pick them up, yet its tail latency remains in the tens of microseconds even when server tails blow up near saturation. The paper also shows that cache sizing is not "more is better": throughput saturates around `128` cached entries, while at `256` entries overflow requests rise quickly because too many cache packets contend in the recirculation path. Performance degrades with write ratio and converges toward `NoCache` at 100% writes; compared with `FarReach`, `OrbitCache` wins until about `25%` writes, after which `FarReach` benefits from write-back caching. The robustness story is still strong: the system handles MTU-sized values, adapts to hot-set changes within a few seconds, and continues to balance loads across diverse production workload mixes.

## Novelty & Impact

The novelty is architectural rather than algorithmic. Prior switch caches asked how to squeeze more bytes into switch memory. `OrbitCache` asks how to keep data out of switch memory almost entirely, using hardware recirculation and packet cloning as the real cache substrate. That is a meaningful shift because it broadens in-network caching from toy-sized objects to the kinds of values actually seen in read-heavy key-value stores.

If adopted, the paper's main impact is on the design space of switch-based storage acceleration. It shows that built-in ASIC mechanisms usually treated as secondary features can support a qualitatively different cache architecture. Researchers building load balancers, in-network storage helpers, or other packet-resident services will likely cite it as evidence that the right abstraction is sometimes "a packet that keeps coming back," not "another switch table entry."

## Limitations

`OrbitCache` buys variable-length caching by giving up cache capacity. Because requests must wait for circulating cache packets, too many cached entries increase queueing on the recirculation path and cause overflow requests to fall back to servers. The evaluation suggests an effective cache size in the rough range of `32-128` entries, which is enough for the paper's skewed workloads but far smaller than conventional server-side caches.

The design is also weakest on write-heavy or rapidly changing workloads. It uses write-through invalidation, so cached reads lose their advantage while a write is pending, and `FarReach` overtakes it once writes become common. Hash collisions are handled at clients rather than inside the switch, which is elegant but does impose an extra RTT in the rare correction path or when an entry is replaced while stale requests remain queued. Finally, the evaluated design is mainly for single-packet items and depends on switch pipeline placement rules because metadata is not shared across pipelines; the paper discusses extensions for multi-packet items and multi-pipeline deployment, but those are not the main implemented result.

## Related Work

- _Li et al. (NSDI '16)_ - `SwitchKV` uses the switch for lookup acceleration while storing cached values on servers; `OrbitCache` keeps the value itself in the packet-resident switch path.
- _Jin et al. (SOSP '17)_ - `NetCache` caches tiny hot items directly in switch memory, whereas `OrbitCache` abandons that memory-centric model to support larger single-packet items.
- _Li et al. (OSDI '20)_ - `Pegasus` handles skew by selectively replicating hot items across servers; `OrbitCache` instead absorbs hot reads in the switch and is not bounded by server throughput in the same way.
- _Sheng et al. (ATC '23)_ - `FarReach` extends the `NetCache` line with write-back caching, but it inherits the same fixed item-size assumptions that `OrbitCache` is designed to escape.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Cache-Centric Multi-Resource Allocation for Storage Services"
oneline: "HARE reallocates cache together with the resources that cache saves, turning cache sensitivity into harvestable I/O, network, or RU budget without breaking fairness."
authors:
  - "Chenhao Ye"
  - "Shawn (Wanxiang) Zhong"
  - "Andrea C. Arpaci-Dusseau"
  - "Remzi H. Arpaci-Dusseau"
affiliations:
  - "University of Wisconsin–Madison"
conference: fast-2026
category: cloud-and-distributed-storage
tags:
  - storage
  - caching
  - datacenter
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`HARE` extends fair multi-resource allocation to systems where cache changes demand for other resources. It first harvests I/O, network, or backend capacity by giving more cache to cache-sensitive tenants while preserving baseline throughput, then redistributes the saved resources so every tenant improves together. The paper demonstrates the idea in both a Redis+DynamoDB cache (`HopperKV`) and an NVMe filesystem (`BunnyFS`), reporting up to `1.9x` and `1.4x` gains over the baseline.

## Problem

The paper starts from a gap between how storage systems are built and how fairness algorithms think. Modern multi-tenant services do not share only one bottleneck: a cloud KV tier may share cache, VM network bandwidth, DynamoDB read units, and write units, while a local filesystem may share page cache, SSD bandwidth, and worker CPU time. Existing dominant resource fairness (`DRF`) handles the case where each resource is linear and independent. Cache is neither. Its performance curve is non-linear, and changing cache size changes how much of the other resources a tenant needs.

That mismatch breaks both obvious approaches. If a system equal-partitions everything, it preserves sharing incentive but leaves performance on the table because tenants have different working-set sizes and different miss penalties. If it runs `DRF` on the non-cache resources and uses a separate cache allocator such as `Memshare`, it still misses the chance to reassign the I/O, network, or backend capacity that extra cache saves. If it simply leaves the cache global and unpartitioned, noisy neighbors can destroy fairness because miss ratios become interference-dependent.

## Key Insight

The central claim is that cache should be treated as a lever on other resources, not as a standalone pool. Giving additional cache to one tenant may reduce that tenant's need for I/O, network, or database reads enough that the system can "harvest" those saved resources and redistribute them to everyone else while still keeping the donor tenant at its baseline throughput.

`HARE` formalizes this with a fairness target the paper calls maximum minimum normalized throughput. Each tenant's normalized throughput is its current throughput divided by its baseline throughput under equal partition. The allocator must keep the minimum normalized throughput at or above `1`, preserving sharing incentive, and then push that minimum as high as possible. If tenants are equally cache-sensitive and no profitable cache trade exists, `HARE` collapses back to `DRF`; if cache sensitivity differs, cache becomes a source of extra allocatable slack.

## Design

The algorithm takes three pieces of information per tenant: a miss-ratio curve (`MRC`) as a function of cache size, a demand vector for the non-cache resources, and a cache-saving constant `alpha_i` for each resource that says how much of that resource a cache hit avoids.

`HARE` runs in two phases. In the harvest phase, it considers moving a cache chunk from one tenant to another. The donor asks how much extra resource it would need to keep baseline throughput after losing that cache chunk; the receiver reports how much of each resource it can relinquish if it gains the chunk. With a single correlated resource, the profitable deal is the one where relinquished capacity exceeds required compensation. With multiple correlated resources, the paper adds a crucial rule: choose deals based on the currently scarcest harvested resource, because that resource will bottleneck the later redistribution. In the redistribute phase, the harvested resources are then weighted back out to tenants in proportion to what they already own, increasing every tenant's throughput by the same relative amount.

The systems work is what makes the paper credible. `HopperKV` gives each tenant a dedicated Redis instance, loads a custom Redis module, and manages four resources: cache, network, DynamoDB read units, and write units. Ghost caches build `MRC`s online, spatial sampling at `1/32` keeps the overhead below `25 ns` per key with under `1%` error, and the control plane reruns `HARE` every `20` seconds over a one-minute window. To make this robust, the allocator applies only changes predicted to help by more than `5%`, migrates cache in `16 MB` chunks, and salts low miss ratios by `1%`. `BunnyFS`, built on `uFS`, uses the same control idea for page cache, SSD bandwidth, and worker CPU cycles.

## Evaluation

The evaluation is broad enough to test the paper's main claim, not just its favorite case. `HopperKV` runs on AWS with `2 GB` cache, `50 MB/s` network, and `1K` DynamoDB read and write units per second in the default setup. In the two-tenant microbenchmarks, `HARE` behaves as advertised: when no useful cache trade exists, it matches `DRF`; when working-set asymmetry appears, it improves minimum normalized throughput by `56%` in one case and by up to `63%` over the baseline overall. In the skew benchmark, where both tenants are read-unit-bound and `Memshare+DRF` over-favors the tenant with the steeper cache gradient, `HARE` still improves throughput by up to `38%` while keeping fairness.

The larger benchmarks matter more. In the `16`-tenant YCSB scaling experiment, pure `DRF` yields `1.2x-1.9x` normalized throughput over the baseline, but `HARE` reaches `1.6x-2.7x`, and `13` of `16` tenants get their best throughput under `HARE`. In the dynamic benchmark, `DRF` reacts faster because it touches only stateless resources, but `HARE`'s chunked cache migration converges smoothly and reaches up to `1.9x` improvement. On six Twitter cache traces, excluding one tenant already saturating the client VM, `HARE` improves throughput by at least `38%`, whereas `DRF` reaches only `16%` and `Memshare+DRF` degrades one workload by `4%`.

`BunnyFS` shows the idea is not tied to cloud KV services. On a `32`-tenant Optane-backed filesystem experiment, `DRF` improves throughput by only `10%`, while `HARE` improves most tenants by about `40%`. In the dynamic filesystem experiment, `HARE` consistently beats the two fair alternatives and avoids the fairness collapse seen when a shared LRU is combined with `DRF`. Taken together, the experiments support the core claim that joint cache/resource allocation beats both equal partition and cache-oblivious fairness.

## Novelty & Impact

Compared with classic `DRF`, the novelty is not merely "add cache to the vector." The paper introduces a different model for fairness under cache-correlated demand, plus a concrete harvest/redistribute mechanism that can exploit those correlations without dropping below baseline fairness. Compared with standalone cache allocators, it contributes the missing bridge from miss-ratio optimization to end-to-end multi-resource allocation.

That makes the paper more than a case study of `Redis` or `uFS`. It is a reusable control-plane idea for multi-tenant storage stacks, especially cloud caches, filesystems, and services that mix hardware and billable backend resources.

## Limitations

The authors are explicit that `HARE` is greedy, not globally optimal. Because miss-ratio curves can have arbitrary shapes, the paper does not claim to solve the optimal allocation problem, only to guarantee convergence and no worse performance than the equal-partition baseline or `DRF` with equal cache partitions.

There are also deployment limits. `HopperKV` is a single-node design in this paper; the multi-node version is future work. `BunnyFS` is primarily optimized for reads, and writes are treated largely as uncacheable reads. Adaptation is periodic rather than instantaneous, so `HARE` necessarily reacts more slowly than plain `DRF` whenever cache quota must move. Finally, the evaluation covers two convincing systems, but still only two, so the generality claim is strong in breadth of pattern, not in number of deployed implementations.

## Related Work

- _Ghodsi et al. (NSDI '11)_ - `DRF` equalizes dominant-resource share for independent resources, while `HARE` targets non-linear, cache-correlated demand.
- _Cidon et al. (USENIX ATC '17)_ - `Memshare` reallocates cache based on cache utility alone, whereas `HARE` also reallocates the backend resources that cache saves.
- _Park et al. (EuroSys '19)_ - `CoPart` coordinates last-level cache and memory bandwidth for a single correlated pair; `HARE` generalizes the idea to multiple cache-correlated storage resources.
- _Lee et al. (SOSP '25)_ - `Spirit` also jointly allocates interdependent resources, but focuses on remote-memory cache and network coupling rather than storage services with several correlated resources.

## My Notes

<!-- empty; left for the human reader -->

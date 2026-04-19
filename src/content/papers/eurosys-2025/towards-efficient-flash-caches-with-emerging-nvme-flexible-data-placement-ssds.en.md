---
title: "Towards Efficient Flash Caches with Emerging NVMe Flexible Data Placement SSDs"
oneline: "FDP lets CacheLib place small hot writes and large cold writes into different reclaim units, driving flash-cache DLWA to about 1 without redesigning the cache."
authors:
  - "Michael Allison"
  - "Arun George"
  - "Javier Gonzalez"
  - "Dan Helmick"
  - "Vikash Kumar"
  - "Roshan R Nair"
  - "Vivek Shah"
affiliations:
  - "Samsung Electronics"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696091"
code_url: "https://github.com/SamsungDS/cachelib-devops"
tags:
  - storage
  - caching
  - datacenter
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

The paper shows that CacheLib's device-level write amplification comes largely from mixing two very different streams on the same SSD blocks: small-object cache writes are hot and random, while large-object cache writes are cold and sequential. By tagging those streams with different `FDP` reclaim-unit handles, CacheLib can keep them apart physically and drive `DLWA` to about `1` on production traces without redesigning the cache.

## Problem

Large web services use flash caches because SSDs are much cheaper per byte than DRAM, but flash endurance is still a hard limit. The paper argues that this makes device-level write amplification (`DLWA`) a first-order systems problem: high `DLWA` shortens SSD lifetime, raises replacement cost, and increases embodied carbon.

CacheLib is the motivating example. Its small object cache (`SOC`) rewrites `4 KB` buckets in set-associative fashion, creating hot random writes, while its large object cache (`LOC`) writes large regions sequentially. When both streams share erase blocks, garbage collection must migrate cold `LOC` data together with frequently invalidated `SOC` data. Meta therefore overprovisions roughly `50%` of flash capacity just to keep `DLWA` near `1.3`. Conventional SSDs hide placement, while more invasive options such as `Open-Channel SSDs` and `ZNS` require substantial software changes. The paper wants placement control without host-managed flash.

## Key Insight

The core claim is that CacheLib already knows enough to place data well: `SOC` and `LOC` are separate engines with different lifetimes, so the host does not need full flash management to keep them apart. If `SOC` and `LOC` write into different `FDP` reclaim units, `LOC` becomes almost self-invalidating while the SSD's internal overprovisioned space can cushion only `SOC` garbage collection.

That is why `FDP` is a good fit. Each write carries a reclaim-unit handle (`RUH`), but the SSD still owns garbage collection. The benefit comes from avoiding one bad intermixing pattern rather than from building a host FTL. The paper's model treats segregated `LOC` as having `DLWA` near `1` and attributes the remaining cost to `SOC`.

## Design

The implementation adds a generic `placement handle` to CacheLib's SSD path. At initialization, a placement-handle allocator probes the device and, if `FDP` is available, gives different handles to `SOC` and `LOC`; otherwise both use the default handle and behavior is unchanged. An `FDP`-aware I/O layer maps those handles to NVMe placement-directive fields and submits them through Linux `io_uring` passthrough. Metadata and other small consumers keep the default path.

The final policy is intentionally simple. The authors tried adaptive placement and `LOC` eviction schemes that track reclaim-unit boundaries, but those added complexity with little gain. In the evaluated system, `SOC` and `LOC` simply get separate handles on a device with `8` initially isolated RUHs of about `6 GB` each. The paper argues that initially isolated handles are sufficient because, after separation, only `SOC` contributes meaningful live-data movement.

## Evaluation

The evaluation uses two servers with dual `24`-core Intel Xeon Gold `6432` CPUs, about `528 GB` of DRAM, and a `1.88 TB` Samsung `PM9D3` `FDP` SSD. Workloads come from public Meta KV-cache traces, Twitter `cluster12`, and a write-only KV variant.

The main result is clean. On the default Meta KV-cache setup with about `42 GB` of DRAM, `930 GB` of SSD cache, and `SOC` at `4%` of SSD size, separating `SOC` and `LOC` lowers `DLWA` from about `1.3` to `1.03` over more than `60` hours. When SSD utilization rises from `50%` to `100%`, the non-`FDP` version degrades from roughly `1.3` to `3.5` `DLWA`, while the `FDP` version stays near `1.03`. Throughput, DRAM hit ratio, NVM hit ratio, and `ALWA` are essentially unchanged, and at `100%` utilization p99 read and write latency improve by `1.75x` and `10x`.

The same trend holds on Twitter `cluster12` and the write-only KV trace: with `4%` `SOC`, `DLWA` stays near `1` at both `50%` and `100%` device utilization. The freed capacity can also be reused operationally: in a two-tenant write-only KV-cache setup sharing one `1.88 TB` SSD, each tenant gets about `930 GB` of flash cache yet still stays near `1` `DLWA` with `FDP`, while the non-`FDP` version remains around `3.5`. The limits are also clear. As `SOC` grows from `4%` to `64%`, `DLWA` rises from `1.03` to `2.5`, and at `90%` to `96%` `SOC` the benefit largely disappears. The authors further estimate `2x` lower SSD device cost, `4x` lower embodied carbon, and about `3.6x` fewer garbage-collection events for the same host-write volume.

## Novelty & Impact

The novelty is the argument that production caches can recover much of the benefit of host-managed flash interfaces with a much smaller contract. Instead of redesigning CacheLib or building a host FTL, the paper adds one placement abstraction and relies on `FDP` to keep hot random `SOC` traffic away from cold sequential `LOC` traffic. The upstreamed implementation makes the result more credible than a one-off prototype.

## Limitations

The limitations are mostly about scope and generality. The evaluation is on one Samsung `FDP` SSD family with `8` initially isolated RUHs, so it does not show how robust the result is across different controller policies or reclaim-unit geometries. The benefit also depends on workload shape: `SOC` must stay small and high-churn while `LOC` stays sequential and cold. Finally, `FDP` is still emerging, host garbage collection remains opaque, and the operational-carbon argument is inferred from garbage-collection counts rather than direct power measurements.

## Related Work

- _Berg et al. (OSDI '20)_ - `CacheLib` establishes the production hybrid-cache architecture that this paper keeps intact; the new contribution is adding `FDP` placement beneath `SOC` and `LOC` rather than redesigning the cache itself.
- _McAllister et al. (SOSP '21)_ - `Kangaroo` attacks flash-cache efficiency by changing cache organization for tiny objects, whereas this paper preserves the existing organization and reduces `DLWA` through device-aware placement.
- _McAllister et al. (OSDI '24)_ - `FairyWREN` extends `Kangaroo` to emerging write-read-erase interfaces such as `ZNS`; this paper pursues similar endurance goals with a less invasive `FDP` interface and no host-managed garbage collection.
- _Kang et al. (HotStorage '14)_ - Multi-streamed SSDs introduced host hints for segregating data by lifetime; `FDP` inherits that intuition but provides a more modern NVMe-compatible interface that the paper integrates into CacheLib.

## My Notes

<!-- empty; left for the human reader -->

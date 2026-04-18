---
title: "Quicksand: Harnessing Stranded Datacenter Resources with Granular Computing"
oneline: "Quicksand splits applications into compute and memory proclets, then keeps them small and migratable so a rack can combine stranded CPU and RAM without opaque far-memory stalls."
authors:
  - "Zhenyuan Ruan"
  - "Shihang Li"
  - "Kaiyan Fan"
  - "Seo Jin Park"
  - "Marcos K. Aguilera"
  - "Adam Belay"
  - "Malte Schwarzkopf"
affiliations:
  - "MIT CSAIL"
  - "Brown University"
  - "VMware Research by Broadcom"
  - "USC"
conference: nsdi-2025
category: memory-serverless-and-storage
code_url: "https://github.com/NSDI25-Quicksand/Quicksand"
tags:
  - datacenter
  - disaggregation
  - memory
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Quicksand is a rack-scale runtime that decomposes an application into compute proclets, memory proclets, and occasionally hybrid proclets. It keeps those proclets small enough to split, merge, and migrate in milliseconds, so the system can place CPU-heavy work where spare cores exist and memory-heavy state where spare RAM exists. The result is a software alternative to transparent memory disaggregation that can also reclaim stranded CPU.

## Problem

The paper starts from a simple but stubborn datacenter inefficiency: applications rarely need CPU and memory in the same ratio that a server provides. Once one resource fills up, the other becomes stranded, so operators either waste capacity or overprovision to survive bursts. Using Alibaba traces, the authors show that machines still average 56% idle CPU and 10% idle memory at peak load, and even an idealized packing exercise with perfect future knowledge still leaves 14% idle CPU and 3% idle memory because task demand ratios do not match machine supply ratios.

Existing fixes each leave an important gap. Transparent memory disaggregation can pool remote RAM, but it does nothing for stranded CPU and it hides locality from the application. That loss of control matters when compute intensity is low: a remote miss turns into a stall the programmer cannot predict or prefetch around. Granular systems such as Nu expose placement and migration, but their units still bundle compute and memory together, so they cannot independently place CPU-heavy work and memory-heavy state. They also push too much decomposition work onto developers.

The stakes are therefore broader than better bin-packing. The system needs an execution model that makes CPU and memory independently movable at fine granularity, while still being programmable enough that application authors do not manually maintain hundreds or thousands of tiny units.

## Key Insight

Quicksand's central claim is that resource fungibility requires decoupling resource consumption itself, not just moving a conventional process around the cluster. The runtime therefore introduces resource proclets: compute proclets that primarily consume CPU, memory proclets that primarily consume RAM, and hybrid proclets only when locality is worth the tighter coupling.

That abstraction works because Quicksand keeps remote access explicit. Compute proclets cannot directly dereference another proclet's memory; instead they invoke memory proclets through library APIs that expose reads, writes, iteration, and prefetch opportunities. This gives Quicksand a middle ground between local execution and transparent far memory: programmers and libraries still know when data may be remote, but the runtime can automate placement, migration, and granularity management underneath high-level abstractions such as sharded data structures, batch operators, and services.

## Design

The developer-facing API is intentionally high level. Quicksand provides libraries for sharded data structures, batch computing, and stateless or stateful services. Internally, all three compile down to resource proclets managed by an auto-sharding layer. A `ShardedVector`, for example, becomes a set of memory proclets keyed by index ranges; a `ForAll` batch operator becomes one or more compute proclets over input ranges; stateful services become paired compute and memory proclets with sticky routing by client identifier.

The data path stays explicit. Memory proclets encapsulate shard state and export `Read`, `Write`, and iterator-style access; when sealed read-only, they also enable safe prefetching. Compute proclets execute lambdas, optionally over a range, and can split by bisecting that range. Hybrid proclets arise only by promoting a memory proclet and are used when the paper decides locality dominates flexibility, such as in in-place sorting. The key invariant is that each proclet should mostly consume one resource type, because that is what gives the scheduler real placement freedom.

The control path is centralized but lightweight. The `AutoSharder` tracks a mapping from sharding-key ranges to proclets via a centralized mapping proclet, while clients cache that map and refresh on staleness. After each routed operation, shard-specific `ShouldSplit` and `ShouldMerge` policies decide whether the proclet has become too large or too small. Machine runtimes report resource usage and idle capacity to a centralized controller, which makes placement and migration decisions. The implementation uses RCU so ordinary accesses take reader locks and the heavier synchronization cost lands mostly on split and merge events.

This machinery matters because Quicksand aims to react on millisecond timescales. The libraries check queue length or proclet CPU usage every 2 ms, split compute proclets when more parallelism is needed, merge them when demand falls, and migrate memory or compute proclets away from oversubscribed machines. The system's promise is not only that proclets are movable, but that they are small enough that moving them is actually useful.

## Evaluation

The prototype is 10 KLoC of C++ on top of Nu, evaluated on eight machines with Xeon E5-2680 v4 CPUs, 64 GiB RAM, and 100 GbE. The paper ports four applications: an ML training pipeline, the DeathStarBench social network, an in-memory sorter, and ExCamera-style video encoding. The strongest comparison is against Hermit for transparent memory disaggregation and against Nu for prior granular programming.

For high-compute-intensity workloads, the ML pipeline shows the core benefit clearly. In an ideal balanced setup, throughput is 26k images/s. Under CPU-, memory-, and both-unbalanced placements with the same aggregate resources, Quicksand stays near that ideal by combining stranded CPU and RAM across machines. Hermit reaches only 83% of Quicksand in the memory-unbalanced case and falls to roughly half of Quicksand in CPU-unbalanced and both-unbalanced cases because it cannot reclaim stranded CPU. Nu does well in the balanced setup, but because its proclets still bundle resources, Quicksand is 2-4x faster in the harder imbalanced layouts.

For low-compute-intensity workloads, the social-network service is the harder test because locality dominates. Here Quicksand and Nu both reach 40%-84% of ideal throughput in memory-imbalanced settings, while Hermit drops to 9%-11% of ideal and only 4% in the pure memory-disaggregated layout. That is a useful sanity check: Quicksand does not make remote memory free, but its explicit-access model lets the library and application preserve enough locality to avoid the collapse seen with paging-based disaggregation.

The dynamic experiments show why split and merge speed matters. When GPU availability in the ML pipeline fluctuates every 200 ms, Quicksand keeps GPUs saturated while using 105 CPU cores on average, versus 140 for a static high-watermark baseline; slowing Quicksand's reaction time from 2 ms to 20 ms or 200 ms noticeably hurts utilization. Under induced memory pressure in the social network, Quicksand keeps p99 latency near 0.3 ms while using 37% less memory than a statically overprovisioned baseline, because it migrates sub-2 MiB shards quickly. The evaluation is fairer than usual to Hermit because the authors run one Hermit instance per machine and manually distribute work, yet the study is still limited to a small cluster rather than a production deployment.

## Novelty & Impact

The novelty is not just a better scheduler or a nicer programming model. Quicksand combines three ideas that are usually separate: explicit remote-access semantics from granular systems, resource-type decoupling from disaggregation, and automatic granularity management inside high-level libraries. That combination is the paper's real contribution: application developers write against familiar abstractions, while the runtime materializes fine-grained proclets that are intentionally biased toward one resource type.

This should matter to several communities. Rack-scale disaggregation work can cite Quicksand as evidence that software-only designs can recover a meaningful fraction of the benefit without transparent far-memory semantics. Granular-system work can treat it as an argument that proclets need resource specialization, not just migratability. Autoscaling and service-runtime researchers can read it as a demonstration that millisecond-scale split and merge control is practical when the abstraction boundary is chosen carefully.

## Limitations

Quicksand is explicitly a rack-scale design for fast, high-bisection networks, not a universal cluster runtime. Applications that depend on very low-latency memory access, direct accelerator control, or heavily monolithic legacy structure may be difficult to port without losing performance. The system also supports only compute and memory proclets today; other resources are future work, and fault tolerance is delegated to prior granular-computing techniques rather than built in directly.

There are also architectural costs. The controller and mapping proclet are centralized components. Hybrid proclets exist because some workloads still need locality, which is a reminder that decoupling is not always free. The appendix quantifies the remote-access cost directly: with 100-byte elements, Quicksand needs about 3 microseconds of computation per element to reach 99% efficiency, and larger elements require higher compute intensity. That means the system wins broadly, but not in every low-compute-intensity regime.

## Related Work

- _Ruan et al. (NSDI '23)_ - Nu introduces migratable proclets for resource fungibility, but its units still bundle CPU and memory and it leaves more granularity management to the application.
- _Qiao et al. (NSDI '23)_ - Hermit pools remote memory transparently, whereas Quicksand keeps remote access explicit and also reclaims stranded CPU.
- _Adya et al. (OSDI '16)_ - Slicer auto-shards datacenter applications, but at much coarser shard sizes and slower reaction times than Quicksand's millisecond-scale proclet control.
- _Ousterhout et al. (SOSP '17)_ - Monotasks also separates resource consumption conceptually, but as a performance-analysis abstraction for analytics jobs rather than a runtime for independently placing compute and memory across machines.

## My Notes

<!-- empty; left for the human reader -->

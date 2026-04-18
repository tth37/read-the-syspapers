---
title: "Spirit: Fair Allocation of Interdependent Resources in Remote Memory Systems"
oneline: "Spirit jointly prices DRAM cache and remote-memory bandwidth so applications can trade one for the other at runtime, staying fair while beating DRF by up to 21.6%."
authors:
  - "Seung-seob Lee"
  - "Jachym Putta"
  - "Ziming Mao"
  - "Anurag Khandelwal"
affiliations:
  - "Yale University"
  - "UC Berkeley"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764805"
code_url: "https://github.com/yale-nova/spirit"
tags:
  - memory
  - disaggregation
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Spirit argues that fair sharing in transparent remote-memory systems should be defined over delivered data-access throughput, not over fixed shares of DRAM cache and remote-memory bandwidth. Its Symbiosis allocator gives every application the same budget, prices the two resources based on contention, and uses runtime-estimated performance surfaces to let tenants trade cache for bandwidth or vice versa while preserving strong fairness guarantees.

## Problem

Swap-based remote memory is attractive because it lets unmodified applications exceed local DRAM capacity: hot data stays in the server's DRAM cache, while cold data is fetched over the network on a miss. In a multi-tenant deployment, however, performance depends on two resources at once: how much local cache an application gets, and how much remote-memory bandwidth it can consume when misses happen. Those resources are not independent. A cache-sensitive key-value store may need far less bandwidth if its cache allocation grows slightly, while a streaming workload may remain bandwidth-bound even if it is given more cache.

That breaks the assumptions behind standard multi-resource fairness schemes such as DRF. DRF expects fixed, independent per-resource demands that users can state a priori. Spirit shows that remote-memory applications usually cannot do that: many different `<cache, bandwidth>` bundles can deliver similar throughput, the best bundle is workload-specific, and it can change over time. If applications are forced to declare demands anyway, the rational move is to over-request both resources, which collapses allocation to static partitioning. The paper's motivating measurements make this concrete: Stream can sustain the same throughput under allocations such as `<100%, 75%>` and `<40%, 100%>`, while Memcached and SocialNetwork are much more cache-sensitive and DLRM is mostly insensitive to either resource.

## Key Insight

The paper's central proposition is that the fairness target should be application performance rather than raw resource shares. If each application receives the same budget and spends it on the cache-bandwidth bundle that maximizes its own throughput, prices become the exchange rate between two substitutable resources. Cache-sensitive tenants naturally buy more cache, bandwidth-sensitive tenants buy more bandwidth, and mixed workloads move between them as contention changes.

This framing matters because it turns fairness from a declaration problem into a market-clearing problem. Spirit does not ask users to state their utility curves; instead, it estimates each application's local performance function `f_i(c, b)` at runtime. That is what lets the system preserve sharing incentive, envy-freeness, and resource Pareto-efficiency without trusting user-specified demands.

## Design

Spirit has three layers: the Symbiosis allocator, a runtime estimator for `f_i(c, b)`, and a data plane that monitors and enforces allocations in an otherwise conventional swap-based remote-memory stack.

Symbiosis is an auction-style allocator derived from CEEI and Walrasian pricing. Cache capacity `C`, bandwidth `B`, total credits, and prices are normalized; each application gets budget `1/N`, and prices satisfy `p_c + p_b = 1`. For a given price vector, every application solves `argmax f_i(c, b)` subject to its budget. If total bids oversubscribe cache, Spirit raises the cache price; if they oversubscribe bandwidth, it raises the bandwidth price. Because every application can always afford the static fair share under the normalized budget, the final allocation preserves sharing incentive; equal prices and budgets also yield envy-freeness, while market clearing gives resource Pareto-efficiency.

The ideal search is expensive because `f_i` can be nonlinear and non-concave, so the implementation uses a PTAS. Spirit discretizes the cache-bandwidth space with `epsilon = 1/200`, effectively searching a `200 x 200` grid, then narrows that search to a local window of plus or minus `5 epsilon` around the current allocation because that is where its estimates are most accurate.

The estimator is the paper's main systems contribution beyond the allocator itself. Rather than building full miss-ratio curves from reuse distance, Spirit fits a power-law page-popularity function `g(x)` from sampled memory accesses. It collects Intel PEBS LLC-miss samples at one sample per 25 accesses, builds a histogram of page popularity, and runs a two-phase gradient-descent fit: first to match the sampled access distribution, then to calibrate against the measured miss ratio at the current cache size. From the estimated miss ratio at a target cache size and the application's current swap bandwidth usage, Spirit derives a slowdown model that converts nearby `<cache, bandwidth>` targets into relative throughput estimates. The paper reports average estimator convergence times as low as 140 ms.

The data plane keeps applications unmodified. Each application runs in its own Docker container. Spirit measures LLC misses per second via `perf`, reads swap-device bandwidth as a proxy for remote-memory accesses, caps cache through container memory limits, and throttles bandwidth with `io.max` in cgroups. Allocations are updated every 30 seconds, and the estimator is refreshed every five epochs.

## Evaluation

The evaluation models an AWS `m5a.8xlarge`-class environment on Intel Xeon 6252N servers: 32 vCPUs, 128 GB of memory, and 7.5 Gbps of network bandwidth, with local DRAM deliberately limited to 10-20 GB so the rest of the working set lives in remote memory. The main experiment runs 24 application instances across four servers: three Stream instances, one Meta KVS Memcached instance, one DLRM instance, and one SocialNetwork instance per server. Spirit is compared with user-demand DRF, a harvest-and-redistribute baseline, a direct trading baseline, and an offline Ideal allocator.

The main numbers support the paper's claim well. Relative to user-demand DRF, Spirit improves throughput by 21.6% for Stream and by 5.9%-6.1% for the cache-sensitive Meta KVS and SocialNetwork workloads. It also cuts p99 latency by 16.8% for Meta KVS and 6.1% for SocialNetwork, while DLRM stays essentially unchanged because it is compute-bound. Spirit tracks the offline Ideal allocator closely, whereas Harvest suffers from noisy short-term performance signals and Trade can improve one workload by hurting another because it lacks Spirit's fairness machinery.

The sensitivity results are also informative. When the local DRAM cache is doubled from 10 GB to 20 GB, Spirit's gain on Stream falls from 21.6% to 7.6%, showing that the market helps most when resources are scarce enough to trade but not so scarce that everyone simply hoards what they have. On the systems side, Symbiosis completes within one second and uses less than 3.3% of a single core in the 24-application setup; even at 1,000 applications, average allocation time remains within 20 seconds. Adaptation is not instantaneous, though: when workloads change from bandwidth-sensitive to cache-sensitive and back, Spirit can take up to 5 minutes to detect the shift in `f_i` and another 5 minutes to converge to a stable new allocation.

## Novelty & Impact

Spirit is novel because it inserts a formal fairness layer into transparent remote memory rather than proposing another paging fast path. Relative to systems such as Infiniswap, AIFM, or Canvas, its contribution is the allocator that treats cache and remote-memory bandwidth as interdependent resources and optimizes for achieved throughput. Relative to prior market-based cache-sharing work, it is the explicit modeling of substitutability in a production-style remote-memory stack, plus a runtime estimator that can support those auctions without application changes.

That makes the paper relevant beyond Ethernet swap over RDMA. The authors explicitly position Symbiosis as a general mechanism for cache-bandwidth-interdependent systems, including future CXL-style disaggregated memory and other shared in-memory caches. The larger lesson is that some resources should be allocated as exchangeable bundles rather than as separate dimensions with static quotas.

## Limitations

Spirit's assumptions also define its limits. The estimator assumes monotonic `f_i(c, b)` behavior, which fits LRU- or LFU-like policies but not arbitrary non-monotonic replacement behavior. Its estimates are intentionally local, which is why the implementation searches only near the current operating point instead of reconstructing a globally accurate performance surface.

The prototype also targets one shared cache and one bandwidth pool. Weighted priorities, hierarchical coordination with CPU or storage allocators, and distributed multi-cache deployments are all future work. More practically, Spirit helps only when there is something useful to trade: if all applications mostly want the same resource, or if resources are either too abundant or too scarce, the gain over static sharing shrinks sharply. Finally, the control loop is not fast enough for abrupt workload shifts on sub-minute timescales.

## Related Work

- _Gu et al. (NSDI '17)_ — Infiniswap made RDMA-backed remote memory practical, but it did not address how multiple tenants should fairly share the resulting cache and bandwidth bottlenecks.
- _Wang et al. (NSDI '23)_ — Canvas adds isolation and adaptive swapping for multi-application remote memory, whereas Spirit contributes an explicit fair-allocation layer over interdependent cache and bandwidth.
- _Majid and Lee (ASPLOS '14)_ — REF introduced market-style elasticity fairness for shared hardware resources, but its fixed utility model does not capture Spirit's workload-specific cache-bandwidth substitutability.
- _Wang and Martinez (HPCA '15)_ — XChange also uses market ideas for multi-resource allocation, but its hardware-cache utility modeling assumes a different setting and does not provide Spirit's sharing-incentive guarantee for remote memory.

## My Notes

<!-- empty; left for the human reader -->

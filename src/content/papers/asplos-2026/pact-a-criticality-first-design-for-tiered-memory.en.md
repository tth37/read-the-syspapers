---
title: "PACT: A Criticality-First Design for Tiered Memory"
oneline: "PACT estimates each page's stall criticality online and promotes the pages that actually bottleneck tiered-memory performance, not just the hottest ones."
authors:
  - "Hamid Hadian"
  - "Jinshu Liu"
  - "Hanchen Xu"
  - "Hansen Idden"
  - "Huaicheng Li"
affiliations:
  - "Virginia Tech, Blacksburg, USA"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790198"
code_url: "https://github.com/MoatLab/PACT"
tags:
  - memory
  - disaggregation
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

PACT argues that tiered memory should optimize for page criticality, not page hotness. It introduces Per-page Access Criticality (PAC), estimates PAC online from standard CPU counters plus sampled LLC misses, and uses that signal to drive promotion and demotion. Across DRAM/NUMA/CXL-style configurations, the result is up to 61% better performance than the next-best tiering design with far fewer migrations.

## Problem

The paper starts from a weakness in almost every page-tiering design: they mostly promote hot pages. That assumption is attractive because access frequency is easy to measure, but it is semantically wrong for heterogeneous memory. A page touched often during a streaming loop may be mostly harmless because the CPU overlaps many misses with high memory-level parallelism (MLP). A page touched less often during pointer chasing may be much more damaging because each miss serializes execution and directly stalls the core. If the fast tier is scarce, promoting by frequency can easily spend DRAM on the wrong pages.

That mismatch gets worse in modern tiered setups where the slow tier may be remote NUMA, persistent memory, or CXL-attached memory with materially higher latency. Existing systems cope through page sampling, hint faults, hotness tracking, or heuristic migration thresholds, but the paper argues that these mechanisms still optimize an indirect proxy. Even prior work that reasons about access cost does so coarsely, such as object-level offline profiling or reactive pressure signals layered on top of hotness. What is missing is an online, page-granular metric that asks a more direct question: how much does this page contribute to CPU stall time right now?

The obvious challenge is observability. CPUs expose coarse stall counters and access counters, but not a built-in "stall cost per page per tier" measurement. So the central systems problem is twofold: infer criticality online from cheap counters, then build migration policies that exploit that signal without creating churn.

## Key Insight

The paper's key insight is that for tiered memory, the right optimization target is the stall contribution of slow-tier accesses, and that target is estimable online with surprisingly little hardware support. PACT defines PAC as a page's contribution to CPU stall cycles. Rather than treating all LLC misses equally, it amortizes each tier's miss cost by the MLP that the tier is currently sustaining. The resulting model is simple: per-tier stall is proportional to `LLC-misses / MLP`, scaled by a hardware-specific coefficient.

Criticality is therefore phase-dependent rather than a static page label. The paper shows that MLP tends to remain stable over short windows on the order of tens of milliseconds, even though it changes over longer phases. Within such a window, PACT can estimate total slow-tier stall cost, then attribute that cost across sampled page accesses in proportion to how often each page appeared during the window. This turns a coarse processor-level signal into a usable per-page estimate.

## Design

PACT has three main pieces: PAC profiling, PAC tracking, and PAC-driven migration. PAC profiling runs every 20 ms. It reads four standard counters, including LLC misses and CHA/TOR occupancy counters, to estimate per-tier MLP and then slow-tier stalls. In parallel, Intel PEBS samples slow-tier LLC-miss accesses and records virtual addresses plus sampled access counts. PACT then attributes the window's estimated stall budget across sampled pages and updates each page's PAC score. The default configuration uses pure accumulation rather than cooling because newly critical pages already surface quickly.

The modeling step is the core technical move. PACT observes that the CHA/TOR queues sit between cores and off-core memory and therefore reflect the number of outstanding requests headed to a given tier. By dividing queue occupancy by the number of cycles with non-empty occupancy, the system estimates per-tier MLP online. That lets PACT distinguish a page that causes serialized misses from one whose misses are heavily overlapped. The paper validates this with 96 workloads and reports Pearson correlation above 0.98 between modeled and measured stall behavior across three latency setups.

Once PAC values exist, PACT needs a cheap way to find the best promotion candidates. A hash table stores per-page PAC metadata, but ranking is handled by adaptive bins rather than global sorting. The bins are sized online using reservoir sampling plus the Freedman-Diaconis rule, then widened or narrowed when too many or too few candidates crowd the promotion frontier.

Migration policy has two sides. Promotion is PAC-first: pages in the highest-priority non-empty bin are promoted immediately via `move_pages()`. Demotion is eager rather than purely reactive: PACT proactively frees DRAM space from the LRU side so that a high-PAC page is not blocked behind space reclamation. The implementation is pragmatic: Linux 5.15, modified `perf`, a shared-memory channel between perf and PACT, two helper threads, and about 25 bytes of metadata per tracked 4 KB page.

## Evaluation

The evaluation is strong and unusually comparative. PACT runs on a dual-socket Intel Skylake CloudLab machine with local DRAM at about 90 ns, remote NUMA at 140 ns, and an emulated CXL-like tier at 190 ns. The workload suite spans graph analytics, GPT-2 inference, Redis/YCSB, SPEC CPU, and other memory-intensive applications. The main comparison set is large: Soar/Alto, Memtis, Colloid, Nomad, TPP, Linux NUMA balancing tiering, plus a no-tiering baseline.

The headline claim is that across 13 workloads and 7 fast/slow-tier ratios, PACT improves performance by up to 61% over the second-best prior system. When PACT is not the top design, it stays close: the paper reports an average gap of 4.1% to the best performer and a worst gap of 11.8%. On the detailed `bc-kron` graph workload, PACT beats the other online baselines by 2-22% under 4 KB pages while using up to 10.4x fewer promotions than Colloid and up to 9.6x fewer than NBT. Under THP, it remains the best system across almost all tier ratios and still beats Memtis.

The all-workloads comparison at 1:1 is also telling. On `bc-urand`, PACT cuts slowdown by 20% relative to Colloid and 80% relative to Nomad. On `gpt-2`, every hotness-driven system does worse than leaving the workload unmigrated, while PACT is the only design that beats `NoTier`, with 27% slowdown versus 51% for Colloid and 49% for Nomad. The paper also checks bandwidth contention, colocation, and parameter sensitivity. Those experiments support the main narrative well: PACT wins by being more selective about which pages deserve migration.

I found the comparison methodology mostly fair. The baselines are numerous, the ratios are varied, and the paper explicitly separates the offline-profiled Soar comparison from the online designs. The main caveat is that the "CXL" tier is an emulated high-latency NUMA setup rather than a production CXL device.

## Novelty & Impact

Relative to _Liu et al. (OSDI '25)_, PACT's novelty is moving from coarse, partly offline cost reasoning to an online page-granular criticality signal that directly drives runtime tiering. Relative to _Vuppalapati and Agarwal (SOSP '24)_, it does not claim that latency alone is the key; it claims that latency must be filtered through MLP to reveal which pages truly stall the CPU. Relative to hotness-first systems such as Memtis or TPP, it changes the control variable itself: page placement is no longer "who was touched most," but "who hurt execution most."

That shift matters for both researchers and practitioners. For researchers, PAC is a reusable abstraction for future memory-tiering work. For practitioners, the paper offers a recipe for reducing migration churn while still reclaiming much of the benefit of a limited DRAM tier.

## Limitations

PACT's biggest limitation is attribution fidelity under mixed tenants. Its proportional attribution assumes a short window with relatively stable execution behavior, which the paper validates for many workloads but not for arbitrary multi-tenant interference patterns. The authors acknowledge that colocated streaming and pointer-chasing traffic in the same tier can blur attribution, even though their controlled experiment still favors PACT.

The design is also somewhat hardware- and platform-shaped. The current implementation leans on Intel PEBS and CHA/TOR counters, and although the authors sketch an AMD translation layer, they do not validate it experimentally. The evaluation uses an emulated CXL tier, not a real commercial CXL pool, and focuses on single-node memory-intensive applications. Finally, demotion still leans on Linux LRU behavior; PACT's main innovation is on promotion and ranking, not a full reinvention of eviction.

## Related Work

- _Liu et al. (OSDI '25)_ — Soar/Alto shows that memory-access cost matters more than hotness, but it relies on coarser or offline reasoning where PACT provides online per-page PAC.
- _Vuppalapati and Agarwal (SOSP '24)_ — Colloid emphasizes access latency and aggressive migration; PACT adds MLP-aware criticality and achieves similar or better performance with many fewer moves.
- _Lee et al. (SOSP '23)_ — Memtis dynamically classifies pages and page sizes, but still operates in a hotness-oriented space rather than estimating direct stall contribution.
- _Al Maruf et al. (ASPLOS '23)_ — TPP is an early CXL-aware transparent page placement system, whereas PACT rethinks the ranking signal used to decide which pages deserve the fast tier.

## My Notes

<!-- empty; left for the human reader -->

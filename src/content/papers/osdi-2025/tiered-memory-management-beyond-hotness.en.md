---
title: "Tiered Memory Management Beyond Hotness"
oneline: "AOL replaces hotness with latency/MLP-aware impact, then uses it to rank objects for placement and suppress low-value page promotions."
authors:
  - "Jinshu Liu"
  - "Hamid Hadian"
  - "Hanchen Xu"
  - "Huaicheng Li"
affiliations:
  - "Virginia Tech"
conference: osdi-2025
code_url: "https://github.com/MoatLab/SoarAlto"
tags:
  - memory
  - disaggregation
  - kernel
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Hotness is a poor proxy for tiering value because much slow-tier latency is hidden by memory-level parallelism (MLP). AOL estimates exposed cost and drives both Soar, an offline object-placement policy, and Alto, a migration-throttling policy.

## Problem

Most tiered-memory systems assume that the hottest pages are the ones that matter. But modern out-of-order CPUs overlap many misses. A frequently touched page inside a high-MLP stream may contribute little exposed stall time, while a colder page on a serialized pointer-chasing path may dominate runtime.

The paper makes this concrete with a microbenchmark containing one sequential thread and one pointer-chasing thread. The sequential region is 13.6x hotter, yet putting those hot pages in DRAM and the pointer-chasing pages in the slow tier drops performance to 52.4% of the all-DRAM baseline. Reversing the placement improves performance by 34%. Existing tiering systems therefore misplace data and then overspend on migrations that do not help.

## Key Insight

The key claim is that tiering should optimize exposed stall cost, not access count. A slow-tier access matters only when its latency is visible to the core; if misses overlap, the penalty per access is amortized. AOL captures that idea by combining memory latency, MLP, and observed LLC-stall pressure.

Once the system measures exposed cost instead of hotness, two policies follow naturally. Objects with the largest accumulated AOL-weighted contribution should start in the fast tier, and migrations should be throttled whenever AOL is low enough that slow-tier latency is already masked. AOL therefore answers both "what should live in DRAM?" and "when is migration worth doing?"

## Design

The technical core is an AOL-based slowdown predictor. The paper first shows that slowdown on the slow tier tracks added LLC stall cycles, then corrects the error for high-MLP workloads with a hardware-calibrated factor `K = f(AOL)`. Using four PMU counters, the final predictor improves the Pearson correlation with observed slowdown from 0.869 to 0.951 across 56 workloads.

Soar uses that signal offline. It intercepts `malloc`/`free` and `mmap`/`munmap` with `LD_PRELOAD`, groups allocations by call chain, samples LLC misses with PEBS, and records AOL-based performance events. By joining object lifetimes, sampled addresses, and interval-level performance estimates, it assigns each object an AOL-weighted score, normalizes by size, and ranks objects by unit score. At deployment time, `libnuma` steers top-ranked objects to the fast tier and leaves the rest in the slow tier.

Alto handles the online case by wrapping systems such as TPP, NBT, Nomad, and Colloid. Each sampling period it reads PMU counters, computes AOL, and compares it against low and high thresholds. Low AOL means promotions are likely wasted and should be throttled or disabled; high AOL leaves the baseline migration policy alone; intermediate AOL allows only a fraction of candidate promotions. The implementation changes only about 30 lines in Linux migration paths.

## Evaluation

The evaluation uses two platforms: a CloudLab Skylake NUMA server configured to emulate a 2.1x fast/slow latency gap, and a Sapphire Rapids machine with a real ASIC-based CXL expander showing a 2.4x gap. Workloads span graph analytics, ML, caching, and HPC.

Soar's strongest result is that impact-aware first placement often beats all reactive baselines. On `bc-urand`, Soar keeps slowdown under 20% even when 90% of memory is in the slow tier, while Nomad reaches 217% on the NUMA setup. On real CXL, Soar's worst point is 42% slowdown, compared with 588% for Nomad and 92% for Colloid. Across the broader workload suite at a 50% slow-tier ratio, Soar stays in the 4%-18% range, while NBT reaches 68%, Nomad 123%, and TPP 1246%.

Alto's value is mostly in avoiding bad work. It cuts page promotions by up to 127.4x and improves performance over the wrapped baselines by 2%-471% for TPP, 1%-23% for NBT, and 0%-18% for Colloid, while the few regressions over Nomad stay within about 2%-3%. The main caveat is bandwidth contention: queuing delays inflate AOL, so the default thresholds become less appropriate unless they are retuned upward.

## Novelty & Impact

Compared with _Al Maruf et al. (ASPLOS '23)_, _Xiang et al. (OSDI '24)_, and _Vuppalapati and Agarwal (SOSP '24)_, the main novelty is not a better hot-page detector but a different control signal: exposed latency cost rather than access frequency. The paper then reuses that signal in both offline placement and online migration control.

Its broader impact is conceptual. It gives CXL-era tiering work a compact metric that connects PMU-observable behavior to actual tiering benefit and argues that "hotter means more important" is the wrong default abstraction.

## Limitations

Soar requires a profile run with the workload entirely on the fast tier, so it fits applications with stable allocation sites and repeatable behavior. It also ranks whole objects, not sub-object hot regions, so mixed-criticality objects can still be placed imperfectly.

Alto is lightweight because it does not estimate per-page performance directly; it only regulates how aggressively an existing system migrates its own candidates. Its AOL thresholds are hardware-dependent, and the paper shows they become less reliable under heavy bandwidth contention. Automatic threshold tuning and finer-grained online policies are left to future work.

## Related Work

- _Dulloor et al. (EuroSys '16)_ — X-Mem uses coarser region-level classification rather than an explicit MLP-aware metric like AOL.
- _Al Maruf et al. (ASPLOS '23)_ — TPP is a representative hotness-driven CXL tiering system that Alto is designed to regulate.
- _Xiang et al. (OSDI '24)_ — Nomad reduces blocking with non-exclusive migration, while this paper argues many migrations should never happen at all.
- _Vuppalapati and Agarwal (SOSP '24)_ — Colloid emphasizes latency balancing under bandwidth saturation; Soar and Alto focus on exposed-latency cost and unnecessary movement.

## My Notes

<!-- empty; left for the human reader -->

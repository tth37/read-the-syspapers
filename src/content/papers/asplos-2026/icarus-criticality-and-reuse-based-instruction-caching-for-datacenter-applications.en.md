---
title: "ICARUS: Criticality and Reuse based Instruction Caching for Datacenter Applications"
oneline: "Uses branch-history-aware criticality detection and reuse-aware bins to keep long-reuse critical instruction lines in L2 for datacenter workloads."
authors:
  - "Vedant Kalbande"
  - "Hrishikesh Jedhe Deshmukh"
  - "Alberto Ros"
  - "Biswabandan Panda"
affiliations:
  - "Indian Institute of Technology Bombay, Mumbai, India"
  - "University of Murcia, Murcia, Spain"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790175"
tags:
  - caching
  - hardware
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

ICARUS targets a specific front-end bottleneck in datacenter CPUs: L2 instruction misses that leave decode starved even when L1I misses are mostly hidden by a decoupled front-end. The paper argues that two facts break prior criticality-only policies: most critical instruction lines are not consistently critical, and the critical lines that matter most are often the ones with longer local reuse. ICARUS therefore combines branch-history-aware critical-line detection with a reuse-aware eviction policy, improving performance by `5.6%` on average over TPLRU versus `2.2%` for EMISSARY.

## Problem

The paper starts from a practical observation about warehouse-scale software stacks. Their code footprints keep growing because application logic now runs through kernels, libraries, language runtimes, RPC stacks, and networking paths. Modern decoupled front-ends plus FDIP hide many L1I misses, so L1I capacity is not the dominant problem. The remaining pain point is the L2: when an instruction fetch misses there and the decode queue empties, the issue queue can drain and the whole core stalls.

The closest prior policy, EMISSARY, already recognizes that not every instruction line matters equally. It marks lines that previously caused decode starvation as critical and tries to retain them in L2. ICARUS argues that this is still too coarse for datacenter code. Only `3.49%` of instruction fetches are critical on average, but they account for `23.18%` of front-end stalls, so detection errors matter a lot. At the same time, only `28.32%` of critical lines stay critical across future accesses, which means a PC-only "once critical, always critical" rule wastes capacity and still misses important lines later.

## Key Insight

The paper's main claim is that instruction-cache criticality is contextual rather than intrinsic. The same instruction line can be harmless on one execution path and stall the core on another because the recent control flow changes its local reuse distance at L2. Branch history is therefore not just a branch-prediction aid; it is a compact summary of whether the next access to a line is likely to return before eviction.

That observation leads to a second claim: criticality alone is not enough for replacement. Once a line has been identified as critical, the next question is whether it is about to be reused soon, later, or not at all. ICARUS argues that the lines worth protecting most are critical lines that have not yet received their reuse, because evicting them loses the opportunity to convert a future decode-starving miss into an L2 hit. In other words, the policy should spend capacity on the intersection of "likely to matter" and "likely to come back."

## Design

ICARUS has two parts. The first is BHC, a branch-history-based criticality detector. The processor maintains a small Critical Instruction Table (CIT) with `512` entries, `2`-bit saturating counters, and a `9`-bit branch-history register. When an instruction fetch from L2/L3/DRAM leads to decode starvation and an empty issue queue, the line address is hashed with recent branch history and the corresponding counter is incremented. If the counter crosses a threshold of two, the fetch is treated as critical and a criticality signal is sent to L2. The table is flushed every million cycles so stale criticality does not accumulate forever.

This matters because branch history makes the signature far less ambiguous than PC alone. In the paper's analysis, about `24%` of PC signatures have mixed decode-starvation behavior, but using PC plus branch history reduces that ambiguous middle region to `5.5%`. A PC-only EMISSARY-style policy reduces decode-starvation cycles by `2.5%` over TPLRU, while the same idea with BHC reaches `6.5%`.

The second part is BRC, a bin-based replacement policy driven by two bits per L2 line: a criticality bit and a reuse bit. Lines are grouped into four bins: non-critical and not yet reused `[0,0]`, non-critical and reused `[0,1]`, critical and reused `[1,1]`, and critical and not yet reused `[1,0]`. Eviction proceeds in the reverse order of usefulness, from `[0,0]` upward, subject to per-bin watermarks of `2`, `4`, `6`, and `4`. The reuse bit flips on the first hit, which lets ICARUS distinguish lines still waiting for their first profitable reuse from lines that have already demonstrated temporal locality. Data lines participate only in the non-critical bins, so the policy still protects shared-L2 data traffic instead of turning instruction caching into unconditional instruction favoritism.

## Evaluation

The evaluation uses gem5 full-system simulation with FDIP on `12` datacenter applications, including `tpcc`, `wikipedia`, `finagle-http`, `kafka`, `tomcat`, `web-search`, and `verilator`, under a Granite Rapids-like hierarchy with `64KB` L1I and `2MB` private L2. Relative to TPLRU, EMISSARY improves runtime by `2.2%` on average, while full ICARUS reaches `5.6%` and up to `51%` on `verilator`. The paper also reports that ICARUS reduces L2 instruction MPKI from `4.72` to `1.94` on average and cuts normalized decode-starvation cycles per instruction from `0.97` to `0.86`.

The most convincing part of the evaluation is the reuse breakdown. BHC alone helps identify critical lines more accurately, but BRC is what materially lowers misses for mid- and long-reuse critical lines, which is the exact failure mode the paper set out to fix. For some workloads, such as `kafka`, long-reuse instruction MPKI drops from `0.8` to `0.02`. The sensitivity studies are also useful: ICARUS keeps outperforming EMISSARY across L1I sizes, L2 sizes, BTB sizes, and Granite Rapids-, EPYC 9005-, and AmpereOne-like hierarchies. The paper further shows that ICARUS composes with PDIP and IP-stride prefetchers, reaching `7.7%` speedup when both are enabled.

The evidence is strongest for the paper's target setting: large-code-footprint datacenter applications on shared private L2s where front-end stalls are still driven by instruction misses below L1I. It says less about regimes where code already fits comfortably in L2 or where instruction translation, rather than caching, is the dominant bottleneck.

## Novelty & Impact

Relative to _Nagendra et al. (ISCA '23)_, ICARUS's novelty is not merely "more protection for critical lines," but the claim that criticality itself must be path-sensitive and that replacement must separate first-reuse critical lines from already-reused ones. Relative to profile-guided work such as Ripple, it keeps the solution online and hardware-managed rather than relying on offline binary analysis. The paper is therefore a genuine mechanism paper: it introduces a new metadata path, a new detector, and a new eviction policy, all tied to a concrete microarchitectural bottleneck.

This should matter to architects working on server CPUs and front-end bottlenecks for warehouse-scale software. Even if future designs change the exact detector or the watermark policy, the broader idea is likely to persist: instruction-cache replacement for datacenter software needs context and reuse awareness, not just instruction priority.

## Limitations

ICARUS depends on a hand-designed criticality detector with several tuned parameters: CIT size, branch-history length, reset interval, bin watermarks, and in one special case a custom "costly fetch" threshold for `verilator` on a smaller L2. The paper shows sensitivity studies, but the design is still more parameterized than TPLRU or simple RRIP-style policies. That raises the usual concern about portability across microarchitectures and software mixes the paper did not test.

There is also a scope limit in how the evaluation is presented. Everything is simulation-based, and the paper studies only `12` applications over fixed regions of interest. The main wins come from instruction-side misses, while translation effects, multi-core interference, and interactions with other front-end structures are mostly argued to be orthogonal rather than evaluated jointly. Finally, the special handling for high-criticality workloads like `verilator` suggests the basic policy may need workload-aware adaptation in extreme regimes.

## Related Work

- _Nagendra et al. (ISCA '23)_ — EMISSARY is the closest prior L2 instruction-cache policy, but it treats criticality as too static and does not distinguish long-reuse critical lines from short-reuse ones.
- _Khan et al. (ISCA '21)_ — Ripple uses offline profile-guided binary rewriting for L1I management, whereas ICARUS is an online hardware policy for shared L2 instruction caching.
- _Ajorpaz et al. (ISCA '18)_ — GHRP uses PC and history to predict dead blocks in L1I and BTB; ICARUS instead uses branch history to predict decode-starvation-critical L2 instruction lines.
- _Godala et al. (ASPLOS '24)_ — PDIP is an instruction prefetcher that complements ICARUS rather than replacing it, since ICARUS improves L2 residency while PDIP pulls urgent lines into L1I.

## My Notes

<!-- empty; left for the human reader -->

---
title: "STRAW: Stress-Aware WL-Based Read Disturbance Management for High-Density NAND Flash Memory"
oneline: "Tracks per-wordline read-disturbance stress and scales pass-through voltage by wordline validity so SSDs reclaim only endangered data instead of whole blocks."
authors:
  - "Myoungjun Chun"
  - "Jaeyong Lee"
  - "Inhyuk Choi"
  - "Jisung Park"
  - "Myungsuk Kim"
  - "Jihong Kim"
affiliations:
  - "Soongsil University, Seoul, Republic of Korea"
  - "Seoul National University, Seoul, Republic of Korea"
  - "POSTECH, Pohang, Republic of Korea"
  - "Kyungpook National University, Daegu, Republic of Korea"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790228"
tags:
  - storage
  - hardware
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

STRAW argues that read reclaim in modern SSDs is too coarse and too late. Instead of waiting for a whole block to cross one conservative threshold, it tracks disturbance at wordline granularity and reclaims only the wordlines that are actually in danger. It also reduces disturbance during reads by raising pass-through voltage on invalid wordlines and lowering it on valid ones, which cuts reclaim traffic and read tail latency substantially.

## Problem

The paper targets a reliability/performance tension that gets worse as NAND density rises. Modern 3D NAND stores much more data per block and uses narrower threshold-voltage margins, so each read disturbs more neighboring data and the same disturbance causes errors sooner. The authors show that this is no longer a minor maintenance issue: on real SSDs, a 176-layer QLC device generates `8.7 TB` of internal writes after only `30 TB` of host reads, and at `50 MB/s` of sustained read traffic could exhaust a `200 TBW` budget in `144` days.

The core reason existing SSDs fare badly is that standard read reclaim (`RR`) is block-based and reactive. A controller keeps one read count per block, sets a single threshold `RC_MAX`, and once a block crosses it, copies all valid pages elsewhere. That policy is safe only if `RC_MAX` is chosen for the worst possible access pattern. In high-density 3D NAND, that worst case is much worse than the average case because disturbance is highly asymmetric: adjacent wordlines receive much higher stress than non-adjacent ones, and different wordlines have very different intrinsic tolerance. The paper shows one TLC block surviving only `54,560` reads when a single neighboring page is hammered, but `518,420` reads under a uniform read pattern. A block-level threshold must honor the first case, so it triggers huge amounts of premature reclaim in the second.

Reactive reclaim then compounds the problem. Because the SSD waits until disturbance-induced errors have already accumulated, every reclaim copies a large amount of still-valid data. As density keeps rising, that copy cost grows even if the policy were otherwise perfect. The paper's broader measurement across five flash-chip types shows that under the worst pattern, 3D QLC tolerates `88.2%` fewer reads than 2D MLC and `79%` fewer than 2D TLC. In other words, future SSDs cannot simply keep doing block-level RR more carefully; they need a different control granularity.

## Key Insight

The main claim is that read disturbance should be managed in units of wordlines, not blocks, and that the controller can estimate wordline risk accurately enough to do so safely. STRAW's model treats each read as adding different amounts of "effective reads" to neighboring wordlines depending on whether they are adjacent or non-adjacent and on how weak that wordline is. If the controller tracks those effective reads, it can reclaim only heavily disturbed wordlines while leaving the rest of the block in place.

The second insight is that pass-through voltage is not just a cause of disturbance but also a control knob. Lowering `Vpass` on valid non-target wordlines sharply reduces per-read disturbance, but doing so naively increases the target page's bit-error rate. STRAW's characterization finds a way around this trade-off: increasing `Vpass` on invalid wordlines reduces the target page's error count, creating margin that can be spent on lowering `Vpass` for valid wordlines. That lets the SSD reduce future disturbance without stretching read latency through ECC blowups or extra read-retry steps.

## Design

STRAW consists of two mechanisms integrated into `StrawFTL`. `WR2` is the reclaim policy. `SR2` is the per-read disturbance-reduction policy.

`WR2` models each wordline with two quantities learned from offline characterization: `ERC_MAX`, the maximum effective read count the wordline can tolerate, and `alpha`, the stress multiplier for reads to adjacent wordlines relative to non-adjacent ones. To keep the model practical, the paper groups wordlines inside a block into four reliability classes: Best, Good, Bad, and Worst. The controller maintains per-block and approximate per-wordline counters, then estimates each wordline's accumulated effective reads as adjacent reads weighted by `alpha` plus non-adjacent reads with unit weight. When a valid wordline is already beyond `ERC_MAX`, or will exceed it before the next checking interval, `WR2` copies only that wordline's valid pages out. The rest of the block stays put.

That design immediately creates a metadata problem: per-wordline counters are far more expensive than one counter per block. The paper's answer is `REC`, a Resource-Efficient Counter structure built with the Space-Saving streaming algorithm. It keeps only a bounded number of hot wordline counters per block and never underestimates a count; if it errs, it errs conservatively and may reclaim early rather than risk corruption. In their default design, a `32`-entry `REC` per `704`-wordline block dramatically cuts metadata cost while preserving most of the benefit.

`SR2` handles the proactive side. Before each read, `StrawFTL` consults a pass-through voltage table indexed by the block's P/E cycle count, the validity of the two adjacent wordlines, and the fraction of invalid non-adjacent wordlines. Invalid wordlines receive a `10%` higher-than-default `Vpass`, while valid non-adjacent wordlines may receive a reduced `Vpass` when the resulting error margin is safe. The controller then updates the reclaim counters in a `beta`-weighted way so that reads performed under reduced `Vpass` contribute less future disturbance stress. Operationally, the whole system relies on offline chip profiling, a few additional firmware tables, approximate counters, and the ability to program per-wordline `Vpass` modes through existing chip interfaces such as `SET FEATURES`.

## Evaluation

The evaluation combines device characterization and system-level SSD emulation. On the device side, the authors characterize `160` 3D TLC chips and `3,686,400` wordlines, then derive the `ERC_MAX`, `alpha`, and `beta` parameters used by STRAW. That study justifies both mechanisms: adjacent reads induce about `8.4x` more disturbance than non-adjacent reads on average, and reducing `Vpass` by `5%` can improve `ERC_MAX` by up to `59.1%`.

At the system level, the authors extend `NVMeVirt` with seven workloads spanning FIO, YCSB, Filebench, Lumos, and Llama. Compared with a baseline SSD that uses conservative block-level RR, full STRAW reduces RR-induced page copies by `90.0%`, `92.2%`, and `93.6%` on average at `0K`, `1K`, and `2K` P/E cycles. The tail-latency story tracks that improvement closely: `99.9th`-percentile read latency falls by `65.2%`, `71.1%`, and `75.6%` on average across the same conditions. Those are exactly the metrics the paper should win on, since reclaim traffic is the mechanism creating long stalls.

The rest of the evaluation addresses the obvious caveats. `STRAW+Cocktail`, which combines STRAW with a prior read-hotness redistribution scheme, cuts page copies by up to `31%` beyond STRAW alone on read-dominant workloads, suggesting the proposal composes rather than replaces all prior ideas. Under mixed read/write workloads, total block erasures still go down by `53.6%` on average despite the possibility that wordline-granular reclaim could force more garbage collection. The main overhead from `SR2` is tiny: even in the worst measured case, higher precharge raises overall read latency by at most `1.2%`. I found the evaluation persuasive for TLC SSDs whose controllers can implement the required voltage modes and profiling pipeline.

## Novelty & Impact

Relative to Cocktail and other RR optimizations, STRAW's novelty is not a better way to reshuffle hot pages after reclaim; it is the decision to stop treating the block as the irreducible unit of read-disturbance management. Relative to older `Vpass`-scaling work for 2D NAND, the new contribution is showing how to make voltage scaling safe in error-prone high-density 3D NAND by exploiting invalid wordlines as error-margin donors.

That makes the paper important for SSD-controller researchers and for practitioners building future high-density flash storage. It is a mechanism paper, but one with a clear deployment story: a modest amount of extra controller state and chip-control logic buys back both endurance and tail latency.

## Limitations

STRAW depends on extensive offline characterization and on tables parameterized by P/E cycle count and wordline quality, so portability across flash generations is not free. The implementation story also assumes commodity chips either already expose, or can be made to expose, enough per-wordline `Vpass` control through existing tuning paths. The authors argue this is feasible, but the prototype is still an emulator-backed design rather than a shipping SSD.

There is also an accuracy/overhead trade-off in the counter design. Approximate `REC` counters never undercount, which preserves safety, but they can trigger premature reclaim when the workload lacks stable hotspots. Finally, the detailed characterization is centered on one 3D TLC generation even though the broader motivation includes QLC and future denser parts, so the strongest claim is about the trend and the mechanism, not about a universal parameter set that can be reused unchanged.

## Related Work

- _Cai et al. (DSN '15)_ — This work characterizes read-disturb errors and `Vpass` mitigation in MLC NAND, while STRAW adapts the voltage-scaling idea to modern 3D NAND and couples it to SSD-level reclaim control.
- _Hong et al. (FAST '22)_ — GuardedErase exploits weak-wordline variation to improve SSD lifetime during erase management, whereas STRAW uses per-wordline variation to control read-disturbance reclaim.
- _Park et al. (ASPLOS '21)_ — This read-retry optimization paper reduces modern SSD read latency from another source; STRAW is complementary because it attacks reclaim-induced tail latency and disturbance growth instead.
- _Chun et al. (HPCA '24)_ — RiF accelerates read-retry inside NAND chips, while STRAW reduces how often disturbance pushes the SSD into the expensive regimes that make such retries and reclaim necessary.

## My Notes

<!-- empty; left for the human reader -->

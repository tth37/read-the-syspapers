---
title: "Characterizing and Emulating FDP SSDs with WARP"
oneline: "WARP shows that FDP approaches 1.0 WAF only when RUH tags match data lifetimes, then turns hidden controller choices into knobs for explaining and improving the gap."
authors:
  - "Inho Song"
  - "Shoaib Asif Qazi"
  - "Javier Gonzalez"
  - "Matias Bjørling"
  - "Sam H. Noh"
  - "Huaicheng Li"
affiliations:
  - "Virginia Tech"
  - "Samsung Electronics"
  - "Western Digital"
conference: fast-2026
category: flash-and-emerging-devices
code_url: "https://github.com/MoatLab/FEMU"
tags:
  - storage
  - hardware
  - observability
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

This paper argues that `FDP` is neither a guaranteed fix for SSD write amplification nor a gimmick: it works when `RUH` assignments align with data lifetimes and collapses when they do not. `WARP` makes that claim actionable by pairing a cross-device study of real FDP drives with an open emulator that exposes the hidden controller knobs behind `II`, `PI`, over-provisioning, RU size, and per-RUH garbage collection.

## Problem

Cloud operators care about write amplification (`WAF`) because it directly affects SSD lifetime, replacement cost, and storage-related carbon footprint. `FDP` was standardized to help: the host tags writes with reclaim unit handles (`RUHs`) so data with similar lifetimes can be reclaimed together. The attraction is that, unlike `OpenChannel` or `ZNS`, FDP preserves the ordinary block interface and does not force invasive application changes.

That convenience is also the problem. FDP is only a hinting interface; garbage collection remains inside opaque vendor firmware. Two SSDs can both advertise `NVMe FDP` and still behave very differently because they quietly choose different reclaim-unit sizes, over-provisioning budgets, lazy-GC thresholds, and isolation policies. The host cannot see whether GC copies preserve RUH identity, whether one RUH's invalidations inflate another RUH's WAF, or whether a long sequential stream is being reclaimed too early.

The practical question is therefore not just "does FDP help?" but "when does it help, why does it fail, and which hidden design choices control the answer?" That matters to `CacheLib`, `F2FS`, and future FDP-aware applications. Without a transparent model, the community gets isolated anecdotes from one device or one workload, but no principled way to reason about cross-device variation.

## Key Insight

The paper's central proposition is that FDP's benefit is an emergent property of two classifications matching each other: the host's lifetime classification into `RUHs`, and the device's hidden reclaim policy. FDP gets close to `1.0` WAF only when those two layers align. If the host mixes hot and cold data in one RUH, or if the device reintroduces interference during reclamation, the interface degenerates toward ordinary SSD behavior even though the command stream is "FDP-correct."

That is why `WARP` matters as much as the measurements. The emulator makes controller choices explicit: `II` versus `PI`, reclaim-unit size, over-provisioning ratio, victim selection, lazy-GC thresholds, and block remapping. Once those knobs are visible, the paper can explain hidden effects instead of only observing them. The memorable takeaway is that FDP is a best-effort contract whose success depends on controller slack and interference patterns, not a simple host-side API switch.

## Design

`WARP` extends `FEMU` so NVMe commands carrying FDP tags are mapped to reclaim units (`RUs`) and reclaim unit handles (`RUHs`). At the placement layer it supports both standard modes. In `II`, host writes enter the target RUH, but GC copies are redirected into a shared GC-RUH. In `PI`, GC copies stay inside the original RUH, preserving isolation but fragmenting the spare-space pool because each RUH now needs its own slack.

Garbage collection is factored into two decisions. First, WARP chooses which RUH to reclaim from using policies such as greedy or pressure-based selection. Second, it chooses the victim RU inside that RUH using either greedy selection or a cost-benefit score based on utilization and age. The emulator also implements lazy GC, separate background and foreground thresholds, and block remapping for fully valid blocks, turning FDP GC from opaque firmware behavior into a controllable design surface.

The other major contribution is visibility. WARP records device-level bytes and WAF, RUH-level counters such as host bytes, GC-copy bytes, remaps, allocations, and evictions, and per-GC-event logs naming the victim RUH, destination RUH, copied pages, and elapsed time. That telemetry exposes two pathologies the paper names explicitly: `Noisy RUH`, where invalidations in one handle raise amplification in others, and `Save Sequential`, where a large sequential stream is reclaimed prematurely and becomes a major source of WAF. WARP also makes RU size, over-provisioning ratio, and RUH count runtime parameters instead of fixed vendor choices.

## Evaluation

The real-device characterization already shows that FDP is conditional. Under single-stream `128 KB` random writes, the two commercial drives settle at very different steady-state WAFs: about `2.0` on `SSDA` and `3.5` on `SSDB`. With three streams and accurate RUH separation, FDP stays near ideal on strongly Zipfian workloads, but `80/20` rewrites and uniform-random invalidations quickly collapse the benefit. The paper's first conclusion is that accurate host tagging is necessary but not sufficient.

`CacheLib` provides the strongest end-to-end evidence. On `kvcache`, where `BigHash` and `BlockCache` naturally have different write behavior, FDP removes the usual endurance-versus-effectiveness tradeoff. At `40%` SOC, WAF falls from `1.85` to `1.27` while hit ratio remains about `82%`. In multi-tenant experiments, noisy neighbors drive the non-FDP case from `1.28` to almost `3.0`, whereas FDP keeps the worst case around `2.6`. By contrast, `cdn` and `twitter` traces were already close to `1.0` WAF, and FDP did not regress them. `F2FS` is the paper's negative result: eBPF tracing shows roughly `99%` of user writes carry the same generic hint, so almost everything lands in one RUH and the device behaves like `NoFDP`.

WARP then validates against those trends and adds new design insight. With calibrated settings, its random-write configurations span the same `2.0-3.5` WAF envelope as the real drives, and on the `CacheLib` trace at `40%` SOC it mirrors the improvement direction (`2.00 -> 1.37`). Its per-RUH logs reveal why some workloads fail: a small invalidation stream can make other RUHs more expensive to reclaim, while a capacity-dominant sequential RUH can become the main source of amplified writes. The `II` versus `PI` study is especially useful. With `256 MB` RUs, the paper reports `II` at `2.92` versus `PI` at `3.80` for `3%` OP, but `PI` improves to `1.181` versus `II` at `1.338` for `10%` OP. Finally, WARP is not just descriptive: assigning a smaller RU to `CacheLib`'s noisy small-object handle reduces WAF further from `1.37` to `1.16`.

## Novelty & Impact

Relative to _Allison et al. (EuroSys '25)_, which shows that one FDP-enabled application stack can benefit from RUH tagging, this paper asks the more foundational question of why the same interface behaves differently across devices and workloads. Relative to _Bjørling et al. (FAST '17)_ and _Bjørling et al. (ATC '21)_, it highlights FDP's middle-ground nature: easier to deploy than `OpenChannel` or `ZNS`, but correspondingly more opaque. Relative to _Li et al. (FAST '18)_, it turns `FEMU` into an FDP research platform with explicit isolation semantics and RUH-aware telemetry.

That combination makes the paper valuable to three groups. Firmware researchers get a transparent controller-policy playground. Systems researchers get evidence that RUH assignment accuracy and workload composition matter as much as the NVMe interface. Application and file-system designers get a warning that "supporting FDP" is not enough if their own classification policy collapses most writes into one class.

## Limitations

The paper is strongest on WAF and weaker on other dimensions. It does provide latency calibration for `WARP`, but the main evaluation target is write amplification rather than full performance realism, and the emulator still inherits `FEMU`'s abstractions instead of reproducing proprietary controllers exactly. That is reasonable for a first platform paper, but WARP explains trends better than it reconstructs every hardware mechanism.

The cross-device study is also broader than prior work but still limited. Only two commercial FDP drives are characterized, and the paper explicitly notes that `SSDB` results are partial because the device failed after heavy write stress. On the software side, `F2FS` shows how immature the ecosystem still is: the interface may exist, but if tagging remains too coarse, the device has no chance to help.

## Related Work

- _Allison et al. (EuroSys '25)_ - integrates `FDP` into `CacheLib` and shows cache-level gains, while `WARP` explains the device-policy variance behind those gains.
- _Bjørling et al. (FAST '17)_ - `LightNVM` gives the host direct control over placement and garbage collection, whereas `FDP` keeps GC inside the device and exposes only hints.
- _Bjørling et al. (ATC '21)_ - `ZNS` also attacks write amplification, but it requires host-visible sequential-write discipline that `FDP` avoids.
- _Li et al. (FAST '18)_ - `FEMU` is the emulator substrate `WARP` builds on, but it does not model `RUH` isolation semantics or per-RUH FDP telemetry.

## My Notes

<!-- empty; left for the human reader -->

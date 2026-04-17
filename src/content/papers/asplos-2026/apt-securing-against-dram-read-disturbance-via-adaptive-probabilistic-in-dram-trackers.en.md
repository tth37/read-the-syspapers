---
title: "APT: Securing Against DRAM Read Disturbance via Adaptive Probabilistic In-DRAM Trackers"
oneline: "Uses activation-adaptive reservoir sampling and step-shaped victim refreshes to block RowHammer and RowPress without depending on attacker-triggerable RFM."
authors:
  - "Runjin Wu"
  - "Meng Zhang"
  - "You Zhou"
  - "Changsheng Xie"
  - "Fei Wu"
affiliations:
  - "School of Computer Science and Technology, Huazhong University of Science and Technology, Wuhan, China"
  - "Wuhan National Laboratory for Optoelectronics, Huazhong University of Science and Technology, Wuhan, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790126"
tags:
  - memory
  - security
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

APT is a low-cost in-DRAM RowHammer/RowPress defense that replaces fixed-probability row sampling with activation-adaptive reservoir sampling. Its second move, Step Mitigation, shapes victim-refresh probabilities to match measured charge-loss distance, so the design can fit up to three secure mitigations inside ordinary refresh slack and optionally combine with fixed-rate `TB-RFM` for lower thresholds. The headline result is protection down to `TRH = 694` with no performance loss in the REF-only design, or down to `TRH = 228` with `1.6%` average slowdown when paired with `TB-RFM0.5`.

## Problem

The paper targets a growing mismatch between DRAM vulnerability and existing transparent defenses. Read disturbance is getting worse as density scales: classic `RowHammer` attacks flip bits through repeated activations, while `RowPress` shows that simply keeping a row open for long periods can reduce the number of required activations by orders of magnitude. Meanwhile, practical in-DRAM mitigations remain severely resource-constrained. They have only a few bytes of storage per bank to remember suspicious rows and only limited time, mostly borrowed from refresh operations, to repair nearby victims.

Recent low-cost proposals such as probabilistic row trackers look attractive because they avoid per-row counters, but the paper argues that they fail in exactly the patterns an attacker will exploit. If a design samples one slot from a fixed activation window, then low-activity windows create a real chance of sampling nothing at all. The paper calls this a row-sampling miss. That matters because RowPress and mixed RowPress/RowHammer attacks purposely reduce the number of visible activations while still inducing charge loss, so a fixed `1/WA` policy can let aggressors escape mitigation entirely.

The obvious way to increase mitigation rate is DDR5 `RFM`, but that creates a second problem. `RFM` stalls banks for a variable amount of time, and recent work shows those timing spikes can become side or covert channels. So the paper is not solving only "how do we sample rows cheaply?" It is solving a stricter problem: how do we build a transparent in-DRAM defense that still works under dynamic activation patterns, avoids attacker-triggerable timing leakage, and scales toward lower thresholds without enormous SRAM or latency cost?

## Key Insight

The central claim is that probabilistic tracking becomes much more robust if probability is tied to the actual number of activations already seen, not to a fixed window size chosen ahead of time. APT therefore borrows reservoir sampling: the first activation in a `tREFI` window is always selected, and the `i`th activation is selected with probability `1/i`. Because the selected row is also retained with the corresponding reservoir-sampling probability, every activation ends the window with the same mitigation probability `1/N`, where `N` is the real activation count. That removes the row-sampling miss pathology of fixed-window schemes.

The second insight is that victim refreshes should follow the physical charge-loss profile instead of a generic exponentially decaying rule. The authors cite recent characterization showing a step-like drop with aggressor-victim distance, so Step Mitigation samples distances with probabilities chosen to match that shape. This lets APT stay secure against transitive attacks while using only two victim refreshes per mitigation, which is small enough to fit multiple mitigations inside the unused portion of `tRFC`.

## Design

APT's base design is a single-entry in-DRAM tracker. Within each `tREFI`, an activation counter assigns each activation an index `i`. The first activation is written directly into a mitigation-address register. Later activations are sampled by comparing a random number against a modulo-`i` condition that approximates the `1/i` reservoir-sampling rule. The paper spends real effort on implementability here: instead of division, APT uses a staged subtractor whose operand width grows only at specific thresholds, letting the sampling logic overlap with `tRC`. At the next `REF`, the stored aggressor row triggers victim refreshes.

Those refreshes are not naive adjacent-row refreshes. Step Mitigation groups aggressor-victim distances into steps and assigns them decreasing but carefully chosen probabilities. For the paper's default blast radius of four, the closest neighbors at distance `1` get total probability `31/32`, distance `2` gets `1/64`, and distances `3` and `4` each get `1/128`. The point is not aesthetic elegance; it is matching measured disturbance while keeping the mitigation action to two victim refreshes. That is what creates room for multiple mitigations per normal `REF`.

From there, the design scales in two directions. `APT-3` instantiates three single-entry samplers in round-robin fashion so one `REF` can drain three sampled aggressors. `APT-P` expands that idea to 15 entries so the design can remain adaptive under refresh postponement. Finally, if a deployment needs to tolerate even lower thresholds, the paper combines APT with `Timing-Based RFM`, issued at fixed intervals rather than attack-triggered counts, so extra mitigation time does not leak information through variable timing.

## Evaluation

The evaluation combines analysis-driven security thresholds with gem5 performance experiments on a `32GB DDR5` system running `SPEC2017` rate and mixed workloads. For performance, the most important result is that the REF-only design is essentially free: `APT-P` incurs zero slowdown, and `APT-3+TB-RFM1` is also reported as negligible because benign workloads rarely need postponed refreshes. More aggressive fixed-rate support costs remain modest: `APT-2+TB-RFM0.5` slows workloads by `0.7%` on average, and `APT-3+TB-RFM0.5` by `1.6%`. Energy rises by `2.8%` for `APT-P` and up to `5.5%` for the most aggressive `TB-RFM` setting.

On the security side, the paper's key threshold numbers are easy to track. Without `TB-RFM`, `APT-3` tolerates devices down to `TRH = 694`; with `TB-RFM1`, the same structure reaches `490`; with `APT-2+TB-RFM0.5`, it reaches `349`; and with `APT-3+TB-RFM0.5`, it reaches `228`. The paper also compares directly against two important alternatives. Against `MINT` plus `ImPress`, APT avoids the large slowdowns that come from translating long row-open times into extra mitigation work; at `TRH = 256`, the baselines report roughly `28%` slowdown for `ImPress-N` and `12.7%` for `ImPress-P`, versus `1.6%` for APT. Against secure `TPRAC`, APT is even more compelling: at `TRH = 256`, `TPRAC` slows execution by `11%`, while APT stays at `1.6%`, about `0.15x` as much overhead.

I think the evaluation supports the main systems claim well: the paper is persuasive that adaptive sampling plus shaped victim refreshes buy a much better security/overhead point than prior transparent designs. The caveat is that much of the security evidence is analytical, not end-to-end silicon validation under real attacks, so the strongest claim is "the design is principled and low-overhead under the model the paper analyzes."

## Novelty & Impact

Relative to _Qureshi et al. (MICRO '24)_, APT's novelty is eliminating fixed-window row-sampling misses rather than merely shrinking tracker state. Relative to _Jaleel et al. (ISCA '24)_, it contributes a more adaptive sampling rule and a mitigation policy that is explicitly shaped by distance-dependent charge loss. Relative to _Woo et al. (ISCA '25)_, it argues that secure low-threshold mitigation does not require per-row counting and the corresponding timing/area cost of `PRAC`.

That makes the paper important for both DRAM architects and security researchers. It is not just another RowHammer tracker; it is an attempt to define a practical design point for future commodity DRAM where thresholds keep falling but industry still wants transparent, low-area defenses.

## Limitations

APT is still a hardware proposal with several assumptions hidden inside the phrase "low overhead." It needs a `TRNG`, new in-DRAM sampling logic, and vendor knowledge of the device's charge-loss profile to set the Step Mitigation probabilities. Its best low-threshold result also depends on controller cooperation for `TB-RFM`, and the overhead rises steadily as the fixed-rate `RFM` interval gets shorter.

The security analysis is also model-heavy. The paper treats any unmitigated sequence of `TRH` activations as failure and uses a `10K`-year per-bank target `MTTF`, which is sensible but still a design assumption. Some threats are out of scope, notably `ColumnDisturb`, and the paper acknowledges that future, even lower thresholds may need more mitigation budget. So the design looks strongest as a transparent protection mechanism for near-future DDR5-like systems, not as the final word on all memory disturbance phenomena.

## Related Work

- _Qureshi et al. (MICRO '24)_ — `MINT` uses a minimalist single-entry in-DRAM tracker, while APT replaces fixed-window sampling with activation-adaptive reservoir sampling to remove row-sampling misses.
- _Jaleel et al. (ISCA '24)_ — `PrIDE` also targets secure low-cost in-DRAM tracking, but APT pushes further on dynamic activation patterns and on fitting more secure victim refreshes inside normal `REF` slack.
- _Saxena et al. (MICRO '24)_ — `ImPress` converts `RowPress` into equivalent activations; APT instead tries to absorb `RowPress` into the tracker/mitigation design with lower runtime cost.
- _Woo et al. (ISCA '25)_ — `TPRAC` secures `PRAC`-based mitigation with `TB-RFM`, whereas APT argues for a probabilistic in-DRAM alternative with far smaller performance and storage overheads.

## My Notes

<!-- empty; left for the human reader -->

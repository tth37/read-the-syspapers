---
title: "DOGI: Data Placement with Oracle-Guided Insights for Log-Structured Systems"
oneline: "DOGI uses an oracle-inspired hot filter, lightweight ML, and adaptive group sizing to place log-structured data so GC copies less and WAF drops by 15.5% on average."
authors:
  - "Jeeyun Kim"
  - "Seonggyun Oh"
  - "Jungwoo Kim"
  - "Jisung Park"
  - "Jaeho Kim"
  - "Sungjin Lee"
  - "Sam H. Noh"
affiliations:
  - "POSTECH"
  - "DGIST"
  - "Gyeongsang National University"
  - "Virginia Tech"
conference: fast-2026
category: indexes-and-data-placement
code_url: "https://github.com/dgist-datalab/DOGI"
tags:
  - storage
  - hardware
  - databases
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`DOGI` starts from an unusually disciplined premise: before proposing a practical policy, the paper first builds `NoDaP`, a near-optimal oracle baseline that reveals where existing log-structured placement schemes lose efficiency. Guided by that oracle, DOGI combines a hot-block filter, a lightweight MLP for the remaining writes, a history-based relocator for GC-written blocks, and adaptive group sizing. Across six write-intensive workload families, it cuts WAF by `15.5%` on average versus the best baseline and raises prototype write throughput by `9.2%`.

## Problem

Log-structured systems turn small random updates into sequential appends, which is why they remain attractive across SSD firmware, LSM-based key-value stores, and distributed file systems. The hidden cost is garbage collection. Updates leave stale blocks behind, and once free space runs low the system must pick victim segments, copy their live blocks elsewhere, and reclaim the segment. That copying overhead shows up as write amplification factor, or `WAF`, which directly hurts throughput, endurance, and sometimes latency.

The ideal is obvious but unreachable. If the system knew every block's future invalidation time and had effectively unbounded spare space, it could keep blocks with nearly identical lifetimes together and reclaim only dead segments, driving WAF toward `1.0`. Real systems have neither property. Future lifetimes are unknown, over-provisioning is limited, and practical designs must keep making placement decisions online.

Prior work gets partway there by grouping blocks with similar predicted lifetimes. SepBIT and MiDAS use cheap heuristics such as latest invalidation time and age; PHFTL and ML-DT use heavier ML models; MiDAS also adapts group count. The paper's criticism is that these designs optimize one lever at a time. They predict user-written blocks imperfectly, relocate GC-written blocks using crude proxies, and often treat group configuration as fixed or only loosely connected to predictor accuracy. The result is a persistent and previously unquantified gap between state of the art and the best WAF that should be achievable under realistic capacity constraints.

## Key Insight

The memorable claim is that good data placement is not "use the most accurate lifetime predictor available." It is "reserve prediction effort for the hard cases, and size the placement granularity to the predictor you actually have." DOGI's oracle study shows three things. First, the hottest blocks are easy to identify with simple heuristics, so spending expensive ML on them is wasteful. Second, GC-written blocks are not uniformly cold; their remaining lifetimes are diverse, so age-based relocation systematically misplaces them. Third, finer-grained groups help only until prediction error starts to dominate, after which more groups increase WAF instead of reducing it.

That leads to a hybrid design. Cheap rules isolate the easiest extremes, lightweight ML handles the ambiguous middle, and group count is tuned around measured prediction accuracy rather than fixed in advance. The paper's use of `NoDaP` matters here: it turns vague intuition about "there must be room for improvement" into a concrete design target.

## Design

`NoDaP` is the paper's offline reference point. It assumes perfect future invalidation times, searches exhaustively for a near-optimal set of block-invalidation ranges (`BIR`s) and group sizes, and chooses victims in a way that approximates the best WAF achievable under finite capacity. DOGI then asks which parts of that oracle behavior can be imitated online.

The online layout contains one hot group `Ghot`, one frozen group `Gfrzn`, and `N` intermediate groups. For user-written blocks, a `Hot Filter` first checks the latest invalidation time and sends the hottest blocks directly to `Ghot`. Its threshold is not static: DOGI adjusts the upper bound of `BIR_Ghot` over time by observing whether recent WAF improved after widening or narrowing the hot range. Only non-hot blocks go to `ML-Alloc`, which uses a lightweight MLP classifier with six features, ten lifetime categories, batch inference over `128` blocks, and double buffering so prediction stays off the critical write path. The model is retrained online every `26M` user-written blocks.

The second major piece is adaptive group configuration. DOGI begins with ten intermediate categories, but it does not keep ten groups blindly. Instead, it records a prediction log `PLog` containing pairs of `<predicted category, actual invalidation time>` for sampled blocks. A Markov-chain model uses that empirical misprediction data to estimate WAF under every merge pattern of adjacent groups, a search space of `512` possible configurations. DOGI then picks the configuration with the lowest expected WAF and derives each merged group's `BIR` from the constituent categories.

GC-written blocks are handled separately. A `Frozen Filter` uses a one-bit update flag plus periodic clearing to detect blocks that appear effectively inactive and places them into `Gfrzn`. The remaining GC-written blocks go through `ML-Reloc`, which reuses `PLog` to estimate each category's average remaining invalidation time at GC time and relocates the block to the group whose `BIR` matches that remainder. If a relocated block survives again, DOGI falls back to the conservative age-based "move to the next group" policy. Victim selection mirrors `NoDaP`: prefer expired segments in hotter groups, and otherwise pick the segment with the fewest live blocks from the cold end.

## Evaluation

The evaluation combines a trace-driven simulator with a prototype on a Western Digital `ZN540` `2 TB` zoned SSD via `ZenFS`. Unless otherwise noted, the setup uses `128 GiB` logical capacity, `256 MiB` segments, `4 KiB` blocks, and `10%` over-provisioning. Workloads cover `FIO`, `YCSB-A`, `YCSB-F`, `Varmail`, six Alibaba cloud traces, and nine Exchange traces. Baselines are `SepBIT`, `MiDAS`, `PHFTL`, `ML-DT`, plus the oracle-like `NoDaP`.

The headline result is that DOGI lowers WAF by `25.1%` on average across all baselines and by `15.5%` versus the best-performing one, `MiDAS`. The effect is stronger on skewed, relatively stable workloads such as `FIO` and `YCSB`, where DOGI can maintain more intermediate groups and its user-write predictor reaches `78-84%` accuracy. On more dynamic workloads such as `Varmail`, Alibaba, and Exchange, the predictor is weaker, but DOGI compensates by collapsing to fewer groups and, if accuracy drops too far, falling back to a simpler baseline-like policy instead of persisting with a bad model.

The component studies support the paper's causal story. For user-written blocks, DOGI's hybrid policy beats both latest-invalidation heuristics and ML-DT's heavier ML-only policy in accuracy while requiring far less inference time. For GC-written blocks, `PLog`-guided relocation is more accurate than age-based relocation on every workload except Exchange and reduces WAF by `8.1%` over that policy on average. The group-configuration experiments are especially persuasive: the best number of groups shifts by workload, and WAF rises sharply when a fixed predictor is forced to discriminate too many categories.

The prototype results show the design is not merely a simulation artifact. DOGI improves write throughput by `19.4x`, `1.19x`, `1.17x`, and `1.09x` over `ML-DT`, `PHFTL`, `SepBIT`, and `MiDAS`, respectively, while keeping average inference latency to `0.39 us`. Read latency is similar to or slightly better than MiDAS, suggesting the compute cost is largely hidden. The main caveat is that the paper remains strongest on write-intensive workloads and WAF; it does not close the remaining gap to `NoDaP`, and that gap is still visibly nontrivial.

## Novelty & Impact

Relative to `MiDAS`, the novelty is not just adaptive group sizing, but tying group sizing to measured prediction error and extending the policy to GC-written blocks. Relative to `PHFTL` and `ML-DT`, the paper argues that better ML alone is the wrong objective; a hybrid design that removes easy cases before ML runs can be both faster and more accurate. The more subtle contribution is methodological: `NoDaP` gives the community a practical upper-bound baseline for decomposing WAF loss into user placement, GC relocation, and grouping effects.

That combination should make the paper useful to designers of SSD firmware, LSM-based storage engines, and zoned log-structured systems. It is a new mechanism, but also a stronger framing of what "oracle-guided" storage design should look like in practice.

## Limitations

DOGI is not magic. Its accuracy degrades on highly dynamic traces, and the fallback mechanism is evidence that the ML model is not robust enough to leave unattended under all workloads. Memory overhead is moderate at the paper's scale, `68 MiB` for a `128 GiB` device, but it scales linearly with capacity and the authors estimate it would reach `34 GiB` at `64 TiB`.

The evaluation also leaves some open questions. The workload suite is broad for write-intensive traces, but still mostly focused on WAF-heavy regimes rather than mixed production services with stronger read or latency sensitivity. The design depends on online retraining, per-block metadata, and several coupled control mechanisms, which means deployability is plausible but not free. Finally, because DOGI is measured against a near-optimal oracle and still remains above it, the paper is better read as a strong step toward the optimum than as a closed problem.

## Related Work

- _Oh et al. (FAST '24)_ — `MiDAS` adapts group count and size, but still relies on latest-invalidation and age-based policies that DOGI replaces with oracle-guided hybrid prediction and relocation.
- _Wang et al. (FAST '22)_ — `SepBIT` separates data by inferred invalidation time, yet its cascading GC groups cannot represent the wide lifetime diversity of GC-written blocks that DOGI exposes.
- _Chakraborttii and Litz (SYSTOR '21)_ — `ML-DT` uses a heavier TCN to predict death times for user writes, while DOGI argues that filtering easy cases first makes a lighter model both faster and more accurate.
- _Sun et al. (DAC '23)_ — `PHFTL` adds GRU-based prediction for user-written blocks, but it leaves GC relocation and group configuration much closer to traditional heuristics than DOGI does.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Ladon: High-Performance Multi-BFT Consensus via Dynamic Global Ordering"
oneline: "Ladon replaces fixed cross-instance slots with dynamic monotonic ranks, so straggling BFT instances stop delaying global confirmation for everyone else."
authors:
  - "Hanzheng Lyu"
  - "Shaokang Xie"
  - "Jianyu Niu"
  - "Chen Feng"
  - "Yinqian Zhang"
  - "Ivan Beschastnikh"
affiliations:
  - "University of British Columbia (Okanagan campus)"
  - "Southern University of Science and Technology"
  - "University of British Columbia (Vancouver campus)"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3696102"
code_url: "https://github.com/eurosys2024ladon/ladon"
tags:
  - consensus
  - fault-tolerance
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Ladon fixes the weakest part of Multi-BFT systems: globally ordering blocks from multiple parallel instances when one instance slows down. It assigns each block a certified monotonic rank at proposal time and confirms blocks dynamically from those ranks, so stragglers stop creating global holes that stall everyone else.

## Problem

Multi-BFT systems such as Mir, ISS, and RCC remove the single-leader bottleneck by running many BFT instances in parallel, but they still merge outputs with a pre-determined mapping from `(instance index, local sequence number)` to a global position. If one instance becomes a straggler, its missing outputs create holes in the global log, and faster instances cannot globally confirm blocks that are already partially committed. The authors show analytically that if one slow instance produces every `k` rounds while the other `m-1` instances produce every round, globally confirmed throughput falls to about `1/k` of the ideal case. Their ISS experiment in WAN shows the same effect: 1 and 3 stragglers cut peak throughput by 89.7% and 90.2% and raise latency by up to 12x and 18x. Fixed ordering also weakens cross-instance causality, because a later block on a slow instance can still receive an earlier global position and enable front-running.

## Key Insight

The central claim is that Multi-BFT should derive global order from certified current progress, not from static per-instance positions. Ladon does that by attaching a monotonic rank to each block when it is proposed. The rank must satisfy two invariants: all honest replicas agree on it, and any block generated after another partially committed block must receive a larger rank. Once those invariants hold, replicas can order blocks locally by `(rank, instance index)` without an extra consensus phase for the global merge. A straggling instance therefore stops reserving future positions in the global log, while rank monotonicity prevents later blocks from cutting ahead of already visible progress elsewhere.

## Design

Before proposing a block, the leader collects `2f+1` certified rank reports, each describing the highest rank known by one replica. It picks the maximum certified rank, increments it by one, caps it at the epoch's `maxRank`, and includes the proof in the pre-prepare. In Ladon-PBFT, backups validate the usual PBFT conditions plus the rank evidence, and when they commit the block they report their current highest certified rank for the next round. This pipelines rank collection with commit instead of adding another protocol round.

Global confirmation is local and deterministic. Each replica examines the latest partially confirmed block from every instance, finds the smallest one under `(rank, instance index)` order, and derives a confirmation bar from it. Any unconfirmed block below that bar is safe to globally confirm, because future blocks must have larger ordering positions. That removes the cross-instance waiting induced by holes. Two practical refinements matter. Epochs end with checkpoints so replicas advance only after every instance reaches the epoch's maximum rank. And the optimized variant `Ladon-opt` compresses the `2f+1` rank reports with aggregate signatures, restoring PBFT's pre-prepare communication from `O(n^2)` to `O(n)`.

## Evaluation

The evaluation uses AWS `c5a.2xlarge` instances with 8-128 replicas in LAN and across four WAN regions, 500-byte transactions, batch size 4096, and the same block-rate limits for all compared protocols. The baselines are ISS, RCC, Mir, and DQBFT under one shared configuration policy.

Without stragglers, Ladon is close to the best prior baselines: at 128 replicas in WAN its throughput is within about 1% of ISS and RCC, though its latency is 22.6% and 18.5% higher. With one honest straggler in WAN and 128 replicas, Ladon delivers 9.1x, 9.4x, and 9.6x the throughput of ISS, RCC, and Mir, respectively, and it has the lowest latency among all evaluated systems. Relative to its own no-straggler case, Ladon's throughput drops only 9.3%, while ISS, RCC, and Mir lose 89.9%, 90.1%, and 84.1%. With up to five Byzantine stragglers in a 16-replica WAN, Ladon retains about 90% of the throughput it had with the same number of honest stragglers, latency rises by 12.5% at five stragglers, and its inter-block causal strength remains `1.0` across all tested settings.

## Novelty & Impact

The novelty is not parallel BFT by itself, but the observation that Multi-BFT's real bottleneck is the fixed cross-instance merge rule. Ladon replaces that rule with certified monotonic ranks plus a deterministic confirmation bar. That is a real protocol mechanism, not a tuning change, and it composes with both PBFT and HotStuff.

## Limitations

Ladon improves inter-block causality, but it does not provide full client-side fairness. A Byzantine leader can still delay a proposal until timeout, and the optimized protocol adds complexity through multiple signing keys, rank certificates, and a deployment-dependent `K` parameter.

The evaluation is strong on protocol behavior but narrower on deployment realism. Most results use synthetic workloads on one AWS machine class, fixed total block rates, and a fixed epoch length of 64. The paper also shows a small no-straggler latency tax versus ISS and RCC, and it does not study application-level costs beyond consensus throughput, latency, CPU, bandwidth, and the causality metric.

## Related Work

- _Stathakopoulou et al. (JSys '22)_ - Mir-BFT parallelizes leaders but still uses a fixed cross-instance merge rule, which is the bottleneck Ladon replaces.
- _Stathakopoulou et al. (EuroSys '22)_ - ISS lets instances progress independently with `⊥` delivery, but global confirmation still stalls on holes; Ladon removes that dependency.
- _Gupta et al. (ICDE '21)_ - RCC uses concurrent consensus and wait-free handling of lagging leaders, whereas Ladon changes the merge rule itself.
- _Arun and Ravindran (PVLDB '22)_ - DQBFT adds a special ordering instance, while Ladon avoids that centralized bottleneck and better preserves generation-time causality.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Themis: Finding Imbalance Failures in Distributed File Systems via a Load Variance Model"
oneline: "Themis turns DFS requests and reconfiguration into one operation sequence, then fuzzes for maximal cross-node load variance to expose persistent imbalance failures."
authors:
  - "Yuanliang Chen"
  - "Fuchen Ma"
  - "Yuanhang Zhou"
  - "Zhen Yan"
  - "Qing Liao"
  - "Yu Jiang"
affiliations:
  - "KLISS, BNRist, School of Software, Tsinghua University"
  - "Harbin Institute of Technology"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696082"
code_url: "https://anonymous.4open.science/r/Themis-97C4"
tags:
  - filesystems
  - storage
  - fuzzing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Themis targets DFS load-balancing bugs that persist even after rebalancing should have repaired the skew. It fuzzes short request/reconfiguration sequences using cross-node load variance as feedback, then confirms candidates by forcing a rebalance pass. Across HDFS, CephFS, GlusterFS, and LeoFS, it finds 10 new imbalance failures.

## Problem

From 53 real-world bugs in HDFS, CephFS, GlusterFS, and LeoFS, the authors find that 82% cause system-wide or majority-node consequences such as outages, crashes, or data loss. Just as important for testing, 83% require both client requests and configuration changes. A file workload alone is usually insufficient, and fault injection alone is usually insufficient too.

That defeats the assumptions behind prior tools. Workload generators such as SmallFile and Filebench keep configuration fixed; distributed-system fuzzers such as CrashFuzz or Mallory vary faults and configuration but not the right workload dependencies; Janus and Hydra explore two dimensions but alternate them instead of modeling the short request/configuration interleavings that real imbalance failures need. Detection is the other problem: DFSes are meant to be approximately balanced, so the oracle has to separate transient skew from persistent imbalance.

## Key Insight

The paper's key claim is that imbalance failures accumulate through many small skews, so the fuzzer should maximize load variance rather than generic coverage. The matching abstraction is to collapse file operations and cluster reconfiguration into one interleaved operation sequence, because that is where the triggering dependencies actually live.

The oracle is persistence. If a DFS still violates the balance threshold after Themis explicitly requests rebalancing and waits for it to finish, the remaining skew is much more likely to reflect an implementation bug than a harmless temporary fluctuation.

## Design

Themis has a test-case generator and an imbalance detector. The input model covers 17 load-related operations across file, node, and volume classes. Test cases are sequences of length 1 to 8, matching the study that historical failures needed at most 8 steps. Filenames come from a maintained file tree, node IDs from management/storage-node lists, and file sizes are sampled with awareness of remaining free space so the generator can hit rebalance boundaries.

Fuzzing is sequence-based. Themis keeps a seed pool and mutates sequences with replace, delete, and insert, then repairs dangling file or node references. After each run it collects per-node CPU usage, network request/read/write activity, and storage occupancy, and sums pairwise differences into a load-variance model. Seeds that enlarge variance or trigger candidate failures are retained.

The detector runs separate compute, network, and storage oracles and checks whether the hottest node exceeds average load by a threshold `t`. To avoid false positives from DFS-specific rebalance timing, Themis explicitly calls the rebalance API, waits for rebalancing to finish, reruns the same test, and reports only if the imbalance remains. Porting to a new DFS mainly needs two hooks: `operation.send()` for system-specific control operations and `LoadMonitor()` for metric collection.

## Evaluation

The evaluation uses 10-node Docker clusters for HDFS v3.4, CephFS v18.0.0, GlusterFS v12.0, and LeoFS v1.4.4, with each run lasting 24 hours. Themis executes more than 60,000 operations and reports 10 new failures: 4 in GlusterFS, 3 in LeoFS, 1 in CephFS, and 2 in HDFS. The strongest baseline finds only 4. Historical replay tells the same story: Themis reproduces 48 of 53 known imbalance bugs, while the comparison methods reproduce only 9, 11, 16, 21, or 23.

The ablation is especially persuasive. Removing load-variance guidance drops new-bug finds from 10 to 5 and branch coverage by 11%. Against the four baseline testing strategies, Themis improves branch coverage by 10%-21%. Threshold tuning also matters: 25% eliminates false positives on the four tested DFSes without losing true positives, whereas 20% still over-reports and 30% starts missing real failures.

## Novelty & Impact

Themis is not a new balancing algorithm; it is a bug model and testing workflow specialized for DFS imbalance failures. Its novelty is the combination of sequence-level request/configuration modeling, load-variance-guided search, and post-rebalance persistence as the oracle.

That combination is useful both to DFS maintainers, who need production-relevant bug reports, and to testing researchers, because it shows how much leverage comes from matching the fuzzing objective to the target bug semantics.

## Limitations

The detector depends on two assumptions that may not generalize cleanly: nodes are roughly homogeneous, and a single threshold `t` can separate acceptable skew from real imbalance. The paper's best setting is 25% on four DFSes, but that number is empirical rather than derived.

Automation also stops at detection. Reproduction, root-cause analysis, and de-duplication are still manual, and the equal weighting of CPU, network, and storage variance is only a first approximation. Themis is also scoped to imbalance failures, not other DFS bug classes such as metadata inconsistency or fail-slow behavior.

## Related Work

- _Xu et al. (S&P '19)_ - Janus explores two-dimensional file-system inputs, but it alternates between dimensions instead of treating request and reconfiguration steps as one executable sequence.
- _Kim et al. (SOSP '19)_ - Hydra finds semantic file-system bugs through extensible fuzzing, whereas Themis targets distributed load-balancing failures and uses persistent cross-node skew as the oracle.
- _Gao et al. (ICSE '23)_ - CrashFuzz coverage-guides cluster fault injection for cloud systems, but assumes fixed workloads and therefore misses many request/configuration dependencies that drive imbalance failures.
- _Meng et al. (CCS '23)_ - Mallory fuzzes distributed systems via timeline-guided fault injection, while Themis optimizes for DFS-specific load variance and validates failures by forcing a rebalance pass.

## My Notes

<!-- empty; left for the human reader -->

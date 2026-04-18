---
title: "One-Size-Fits-None: Understanding and Enhancing Slow-Fault Tolerance in Modern Distributed Systems"
oneline: "The paper maps fail-slow danger zones across six systems, then replaces brittle timeout thresholds with ADR's runtime-adaptive slowness detector."
authors:
  - "Ruiming Lu"
  - "Yunchi Lu"
  - "Yuxuan Jiang"
  - "Guangtao Xue"
  - "Peng Huang"
affiliations:
  - "University of Michigan"
  - "Shanghai Jiao Tong University"
conference: nsdi-2025
code_url: "https://github.com/OrderLab/xinda"
tags:
  - fault-tolerance
  - datacenter
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

This paper argues that modern distributed systems do not have one stable fail-slow tolerance envelope. Small changes in fault type, severity, location, workload, or hardware budget can move a system from near-normal behavior to collapse, so static timeout thresholds usually fire too late or at the wrong time. The authors support that claim with a fault-injection study across six production systems and then propose ADR, a small library that replaces fixed thresholds with runtime-adaptive slow-fault detection.

## Problem

Crash fault tolerance is mature, but fail-slow behavior is common in disks, NICs, and networks deployed at scale. The hard part is that a slow component still participates in the protocol, just late enough to trigger queueing, retries, and cascading bottlenecks. Prior work such as Limplock established that worst-case limpware can stall an entire cluster, and several systems have since added slow-query, slow-sync, or slow-disk handlers. But those handlers are usually encoded as fixed warning and fatal timeouts.

The paper's complaint is that this model is too coarse for modern systems. The same delay can be harmless in one stack and catastrophic in another. Even inside one system, the harmful region can shift with workload mix, machine size, and whether the fault lands on a leader or follower. As a result, operators get one-size-fits-all alerts, while developers ship thresholds that were tuned in one environment and silently miss real slow faults elsewhere.

The paper also argues that current engineering practice reinforces the problem. In the studied codebases, slow-fault handlers are mostly validated with unit tests that sleep past a threshold and assert that a warning or restart fires. That checks functionality, but it does not tell developers whether those thresholds will trigger early enough, or at all, under realistic end-to-end deployments.

## Key Insight

The main proposition is that fail-slow tolerance should be treated as a dynamic control problem rather than a binary timeout problem. What matters is not only whether latency rises, but also how system behavior changes around that rise: how quickly requests are completing, whether the workload itself has shifted, and whether a fault is mild enough to stay on the critical path without triggering failover.

That perspective explains several counterintuitive results in the paper. Mild faults can hurt more than severe ones because severe faults may finally trigger leader re-election or connection failover. Adding CPU can make the same delay look worse because the baseline gets faster. The right detector therefore needs to adapt to recent local behavior and distinguish workload transitions from genuine slow faults, instead of comparing every event to one fixed timeout forever.

## Design

The study covers six systems: Cassandra, HBase, HDFS, etcd, CockroachDB, and Kafka. The pipeline initializes a small cluster, warms it up, injects one slow fault, and measures throughput and latency before, during, and after the injection. Faults are introduced at the network and filesystem interfaces rather than at a specific hardware device: packet loss at 1%, 10%, 40%, and 70%; network delay from 100 us to 1 s; and filesystem delay from 1 ms to 1 s. The authors also vary fault location, duration, workload, and, for etcd, CPU and memory limits. Their main metric is performance degradation, computed from the drop in average throughput during the slow period.

The paper then inspects existing slow-handling logic and finds a repeated pattern: systems monitor some latency-like metric, compare it to static warning and fatal thresholds, and trigger actions such as logging, leader re-election, log rolling, reconnecting, or fail-stop escalation. ADR is designed as a drop-in replacement for those static checks. It is a lightweight Java/Go library, about 400 lines of code, that wraps existing threshold comparisons such as HBase's `slowSyncNs` and `rollOnSyncNs`.

ADR tracks two things for a traced variable: its recent values and its update frequency. Once the value window is populated, ADR uses the recent p99 as an adaptive threshold. It then cross-validates with frequency: if updates suddenly become more frequent, ADR treats that as a workload increase and resets its windows to adapt; if updates become less frequent while values remain persistently high, ADR interprets that as a true slow fault. Two state checkers summarize recent value states and frequency states and output `slow` or `fatal`, which existing mitigation code can map to warnings, log rolls, restarts, or other actions.

## Evaluation

The empirical study shows that fail-slow behavior is highly unstable across systems. With injected network delay, Cassandra, HBase, and Kafka can exceed 25% degradation at only 1 ms, while CockroachDB and etcd need roughly 100 ms to show a comparable hit. Some systems approach 70% degradation at 10 ms, while others never get that bad even at 1 s. The relation is not monotonic either: etcd leaders can suffer less under harsher packet loss because severe loss finally breaks heartbeats and triggers re-election.

Location and workload matter just as much. In etcd, a slow follower is worse than a slow leader: under flaky networks the paper reports 45% degradation for a slow follower versus 31% for a slow leader. The root cause is a mismatch between server-side awareness and the gRPC client's balancer, which keeps sending traffic to a mildly slow follower until keepalives actually fail. Workload sensitivity is even sharper. Under a 10 ms network delay, etcd degrades by 85%, 18%, and 15% under read-only, mixed, and write-only workloads. The paper also identifies narrow "danger zones" where a tiny fault increase causes a sharp throughput cliff, such as 1-2 ms for read-only etcd.

Resource scaling does not rescue the problem. For etcd with 32 GB memory and a 10 ms network delay, degradation rises from 7% to 26% to 72% as CPU cores increase from 1 to 2 to 5, because the no-fault baseline becomes much faster. Tail latency is also an unreliable detector: slow periods produce fewer requests, so normal-period samples can dilute the tail statistics and hide serious slowdowns.

ADR is evaluated in HBase and CockroachDB against the original code, several static timeout schemes, and IASO. On HBase under a 100 ms network delay, ADR reduces degradation from 97% to 32%, beating the best static alternative at 37% and IASO variants at 38% and 54%. Across workloads, ADR cuts HBase degradation by 16-80% for mixed workloads and 43-90% for write-only workloads, while preserving availability where fine-tuned static settings sometimes crash the cluster. In CockroachDB, the evaluated case even turns into a slight 7% performance gain. Detection time is about 1.3 s for mixed workloads and 0.9 s for write-heavy workloads, and average runtime overhead is 2.8%.

The paper also evaluates recent fail-slow ideas directly and finds that each misses part of the problem. Perseus does not transfer cleanly because its device-level latency-throughput model is a poor fit for end-to-end distributed-system behavior. IASO inherits the conservative timeout signals already exposed by the underlying systems. Copilot helps most around the 10 ms regime it was tuned for, but it is still bounded by static fast-takeover and heartbeat timers. That comparison strengthens the paper's main claim that fail-slow handling fails not for lack of mechanisms, but because the triggering logic remains too rigid.

## Novelty & Impact

The paper's contribution is the combination of a broad measurement study and a practical in-code response. Earlier fail-slow work showed that slow components can be dangerous, but this paper explains why modern systems still miss them even after adding slow-fault handlers: the triggering logic is static while the fault surface is dynamic. ADR is therefore not a new consensus or replication protocol; it is a reusable way to retrofit adaptive slow-fault handling into existing storage, database, and control-plane software that already has timeout-based hooks.

## Limitations

The study injects one fault at a time and only through network and filesystem interfaces, so it does not cover compound gray failures or richer hardware-specific behavior. Most experiments use 3-6 node clusters, although several findings are validated again on 10- and 20-node deployments. The paper also studies six systems, which is broad but still not exhaustive.

ADR has its own limits. It assumes developers already know which variables are worth tracing, so it cannot help with uninstrumented slow paths. It cannot detect faults during system start-up, and it can misclassify faults that happen exactly during workload transitions because it uses frequency shifts to tell faults from load changes. The HBase results make that concrete: the traced variables are write-path signals, so ADR does not mitigate read-only slowdowns in that integration. The paper also does not provide a formal optimality or stability proof for the adaptive policy.

## Related Work

- _Do et al. (SoCC '13)_ - Limplock established that limpware can stall scale-out systems in worst-case scenarios; this paper revisits the problem with modern systems, realistic workloads, and a broader slow-fault space.
- _Panda et al. (USENIX ATC '19)_ - IASO detects fail-slow nodes from timeout signals across peers, while this paper argues those timeout signals are themselves too static and shows the resulting limits experimentally.
- _Lu et al. (FAST '23)_ - Perseus models fail-slow storage devices from telemetry, whereas this paper shows that such offline device-oriented modeling does not transfer cleanly to end-to-end distributed-system behavior.
- _Ngo et al. (OSDI '20)_ - Copilot tolerates one slow replica through protocol-level redundancy, while this paper shows that fixed takeover and heartbeat thresholds still leave blind spots and argues for adaptive in-system detection.

## My Notes

<!-- empty; left for the human reader -->

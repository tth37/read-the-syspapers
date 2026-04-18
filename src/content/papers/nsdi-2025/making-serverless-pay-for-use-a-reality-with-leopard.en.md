---
title: "Making Serverless Pay-For-Use a Reality with Leopard"
oneline: "Leopard exposes reserved/spot CPU and preemptible memory in serverless billing, then uses them in cgroups and scheduling to cut cost while raising throughput."
authors:
  - "Tingjia Cao"
  - "Andrea C. Arpaci-Dusseau"
  - "Remzi H. Arpaci-Dusseau"
  - "Tyler Caraza-Harter"
affiliations:
  - "University of Wisconsin–Madison"
conference: nsdi-2025
category: memory-serverless-and-storage
tags:
  - serverless
  - scheduling
  - datacenter
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mainstream serverless billing mostly sells a fixed memory-sized instance for wall-clock time, not actual CPU and memory use. Leopard introduces Nearly Pay-for-Use (NPFU) billing plus kernel and scheduler support for lending idle reserved resources, raising throughput by 2.3x on average while lowering user cost at equal provider revenue.

## Problem

Commercial FaaS platforms market "pay for use," but the paper shows they mostly implement SLIM: a static, linear, interactive-only model. Users pick one memory knob, CPU comes from a fixed ratio, billing is execution time times configured size, and every invocation pays for immediate service.

SLIM only approximates strict pay-for-use if four assumptions hold: usage is constant within an invocation, similar across invocations, CPU and memory scale linearly, and all invocations are latency-critical. The authors' 22-function suite across compilation, video, analytics, database, inference, and training breaks all four: CPU and memory vary within a run, larger inputs need different resources, most functions do not match a fixed CPU-memory ratio, and many have batch use cases. That mismatch overcharges users and strands cluster resources.

## Key Insight

The paper's key claim is that billing and resource management must be co-designed. A provider needs to know which resources are hard guarantees and which are opportunistic; otherwise it cannot safely resell idle reservation.

NPFU therefore exposes four knobs: `cpu-cap`, `spot-cores`, `mem-cap`, and `preemptible-mem`. They separate maximum demand from urgent demand for CPU, and protected memory from memory that can be reclaimed by killing and requeuing batch work. Once those distinctions exist, the system can credit a function for lending idle reserved capacity and charge another for borrowing it, removing SLIM's hidden assumption that every invocation is equally urgent and equally shaped.

## Design

NPFU uses a used-lent billing function. For CPU, a function pays for reserved CPU time, pays a lower rate for borrowed spot CPU time, and receives credit when its reserved cores were idle and used by others. For memory, non-preemptible functions pay for `mem-cap` but get credit for lent idle memory, while preemptible functions pay for average memory used; if preempted mid-invocation, they are requeued and not charged.

Leopard is the runtime support that makes those knobs enforceable. Built on OpenLambda, it adds a new cgroup interface, `cpu.resv_cpuset`, plus CFS changes so reserved tasks can immediately reclaim their reserved CPUs while idle reserved CPUs may still run spot work. This avoids the stock-Linux tradeoff the paper demonstrates: CPU pinning preserves reservations but wastes cores, while weighted sharing uses cores efficiently but fails to protect latency-sensitive work.

Leopard also adds billing-aware OOM handling. The default kernel OOM killer does not know which sandboxes are preemptible or which victim would lose the least revenue, so Leopard lets a user-space listener choose the victim, preferring cached sandboxes and then the cheapest active preemptible one. On top of that, Leopard changes admission control and load balancing: interactive invocations are admitted only when enough unreserved protected resources exist, batch invocations are admitted from currently idle resources when historical averages imply low preemption risk, and the cluster uses different load metrics for interactive and batch work.

## Evaluation

The evaluation uses BilliBench, which combines Azure serverless traces with the paper's detailed function suite so each invocation has realistic arrival patterns and realistic resource phases. Leopard implements four billing models for comparison: SLIM, SIM, SPFU, and NPFU.

For providers, NPFU improves throughput by 2.3x on average relative to SLIM. Removing the fixed CPU-memory ratio gives a 1.3x gain from SLIM to SIM, and adding spot CPU plus preemptible memory gives another 1.6x from SIM to NPFU. The utilization plots match that result: under SLIM, more than half of CPU and about three quarters of memory are wasted, whereas NPFU pushes memory utilization to about 90% and CPU utilization to about 80%.

For users, the paper adjusts price coefficients so provider revenue matches SLIM, then compares bills. NPFU reduces average interactive cost by 34% and batch cost by 59% relative to SLIM. Interactive job completion time also improves under high load because Leopard protects reserved resources better than stock Linux mechanisms. The downside is explicit: batch jobs can take up to 3x longer because they absorb opportunistic execution and preemption. Sensitivity studies and a 160-worker simulation preserve the same qualitative conclusion, with the largest gains when CPU utilization is well below reservation and more work is batchable.

## Novelty & Impact

The novelty is that billing is treated as a first-class systems interface, not a pricing afterthought. Leopard shows that a large share of serverless inefficiency comes from the billing contract itself, not just from poor scheduling inside that contract. That should matter to both serverless platform builders and researchers working on mixed-criticality scheduling and resource harvesting.

## Limitations

Leopard requires more user and provider cooperation than today's serverless services. Users must classify work as interactive or batch and set four knobs reasonably well. Providers must modify cgroups, CFS, and OOM handling, which raises deployment complexity.

The gains also depend on workload slack: if functions already use most of their reserved CPU, there is less spare capacity to resell. Batch work pays less because it accepts weaker guarantees, but it also pays the latency penalty through requeue and longer completion time. Finally, BilliBench is a synthetic combination of Azure traces and a 22-function suite, not a production deployment study.

## Related Work

- _Hendrickson et al. (HotCloud '16)_ - OpenLambda is Leopard's implementation base, but it assumes conventional serverless resource control rather than a billing model that differentiates reserved and opportunistic resources.
- _Kaffes et al. (SoCC '22)_ - Hermod improves serverless scheduling with runtime prediction, whereas Leopard argues that scheduling alone is insufficient if the billing contract still forces SLIM-style reservations.
- _Fuerst and Sharma (ASPLOS '21)_ - FaasCache studies sandbox eviction for warm reuse, while Leopard extends eviction into a billing-aware preemption mechanism for active preemptible sandboxes under OOM.
- _Ambati et al. (OSDI '20)_ - Harvest VMs also resell spare capacity, but at VM timescales; Leopard tackles the harder millisecond-scale case of serverless invocations with per-invocation QoS distinctions.

## My Notes

<!-- empty; left for the human reader -->

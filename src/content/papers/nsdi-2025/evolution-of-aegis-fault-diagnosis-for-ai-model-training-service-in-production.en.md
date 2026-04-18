---
title: "Evolution of Aegis: Fault Diagnosis for AI Model Training Service in Production"
oneline: "Aegis moves AI-training diagnosis to pluggable CCL instrumentation plus pre-delivery checks, localizing faults in runtime without changing customer code."
authors:
  - "Jianbo Dong"
  - "Kun Qian"
  - "Pengcheng Zhang"
  - "Zhilong Zheng"
  - "Liang Chen"
  - "Fei Feng"
  - "Yichi Xu"
  - "Yikai Zhu"
  - "Gang Lu"
  - "Xue Li"
  - "Zhihui Ren"
  - "Zhicheng Wang"
  - "Bin Luo"
  - "Peng Zhang"
  - "Yang Liu"
  - "Yanqing Chen"
  - "Yu Guan"
  - "Weicheng Wang"
  - "Chaojie Yang"
  - "Yang Zhang"
  - "Man Yuan"
  - "Hanyu Zhao"
  - "Yong Li"
  - "Zihan Zhao"
  - "Shan Li"
  - "Xianlong Zeng"
  - "Zhiping Yao"
  - "Binzhang Fu"
  - "Ennan Zhai"
  - "Wei Lin"
  - "Chao Wang"
  - "Dennis Cai"
affiliations:
  - "Alibaba Cloud"
conference: nsdi-2025
tags:
  - llm-training
  - observability
  - fault-tolerance
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Aegis is a production diagnosis stack for public AI training clouds that starts from log- and topology-based triage, then evolves to CCL-level runtime instrumentation so it can separate computation faults from communication faults without touching customer code. Across one year of deployment, that evolution raises runtime diagnosis coverage from 77% to nearly 100%, while also reducing diagnosis idle time, restarts, and performance degradation.

## Problem

The paper starts from a very specific operational mismatch: cloud diagnosis systems for RPC services assume failures stay close to a source-destination path, but synchronous model training smears one bad component across an entire job. A single faulty GPU, NIC, PCIe path, NVLink, or optical link can first surface as a cluster-wide CCL timeout, so the visible error is usually the fan-out, not the culprit.

The hardware environment makes this worse. Alibaba's training clusters use eight-GPU hosts, complex intra-host PCIe and NVLink fabrics, and rail-optimized networks with longer optical links. The paper reports that A100 GPUs fail after roughly 400 days on average and H100 GPUs after about 200 days, while 45.6% of production failures are GPU-related. Optics and fiber also fail 1.2x-10x more often than DAC links, depending on vendor and speed. Even when dual-ToR avoids a hard crash, one failed link can still halve available bandwidth and create severe slowdown.

Existing tools only solve slices of this problem. The authors' network monitors, RDMA Pingmesh, and in-band switch telemetry are effective for ordinary datacenter debugging, but they over-focus on the network and on single request-response paths. SuperBench is useful before deployment, yet too slow for runtime diagnosis. MegaScale gets closer to runtime localization, but it relies on monitoring CUDA events inside "critical code segments," which is not acceptable for a public cloud provider serving many customers with proprietary code.

## Key Insight

The paper's main claim is that the right diagnosis boundary for a public model-training cloud is the collective communication layer, not the application and not the raw network. CCL sits exactly between computation and communication, is already pluggable in mainstream training stacks, and can expose just enough synchronized runtime state to tell whether one worker failed before a collective or whether the collective itself is stalled by communication trouble.

That insight only works if the system is built in stages. Aegis first exhausts easy, high-confidence signals from logs and topology-aware procedures, because many failures can already be localized that way. Then Phase-2 adds lightweight CCL counters to close the remaining gap without modifying customer models or training frameworks. The result is not a single algorithm but a layered production workflow: fast critical-error isolation, topology-aware offline backstop, CCL-based runtime localization, and pre-delivery checking for faults that already exist before a job starts.

## Design

Aegis has three major pieces. Phase-1 augments existing infrastructure logs with training logs and a new diagnosis procedure. `CriticalError()` handles failures that directly identify a bad host, such as double-bit ECC errors, missing GPU/NIC/NVLink devices, power faults, or overheating. `DistError()` collects cluster-wide symptoms like "connection reset by peer." If only one or two hosts are implicated, the system isolates them immediately. Otherwise `RootDiag()` looks for a source/destination pattern in the first failed connections; if none appears, `ConfigCheck()` and `NetDiag()` test for configuration or network problems.

When runtime evidence is still insufficient, Aegis runs offline diagnosis as a parallel, topology-aware backstop instead of monopolizing a whole cluster for hours. Hosts first execute self-checks independently, then run representative training models on carefully chosen subsets that do not share the same Pods or ToR groups. That design both speeds localization and avoids false conclusions from diagnostic jobs contending on the same links. One failure case on a 1.5K-GPU task even revealed a blind spot: the parallel split hid a Tier-2 aggregation-switch bug that silently dropped packets larger than 1 KB, which then motivated longer RDMA Pingmesh probes.

Phase-2 moves the decisive instrumentation into a customized CCL. For each collective `Ci` on GPU `Gj`, Aegis records collective launches, work requests, and work completions. If one GPU stops launching the next collective while the others continue, the fault is in computation on that host. If all GPUs time out inside the same collective, but one participant shows abnormal work-request versus completion behavior, the fault is in communication and Aegis can hand the implicated endpoints back to `NetDiag()`. For performance degradation, Aegis first runs a simple cross-host Z-score detector over more than 20 host and network metrics, then adds CCL-side duration and throughput measurements to separate computation slowdowns from communication slowdowns. Finally, Check Before Delivery (CBD) runs a compact suite of configuration, single-host, and multi-host tests immediately before resources are handed to users; the full version finishes in under 10 minutes, while a lightweight version finishes in under 1 minute.

## Evaluation

The evaluation is an operational study over roughly 16 months of one in-house frontier-LLM training effort whose scale increased by more than 40x. That framing matters: the paper is not a clean A/B benchmark on a lab cluster, but a report on what happened as the diagnosis stack evolved under production pressure.

The biggest result is reduction in wasted idle time. After Aegis Phase-1 went online, diagnosis-related idle time fell by 71% in the next month even as training scale doubled. After Phase-2 was deployed in June 2024, the remaining idle time dropped by another 91% because most failures no longer needed offline localization. The runtime diagnosis rate improved from 77% to near 100%, which is the central claim the paper needs to support, and the deployment results do support it.

The other two outcome metrics also line up with the design. CBD attacks failures during initialization, where 73% of failed tasks happen within the first 10 minutes. After deployment, restart count dropped 44.8% in the next month and 84.6% after the checklist matured, while CBD consistently intercepted 1%-2% problematic hosts before delivery. For performance degradation, Aegis reports a 71% reduction after the correlation and procedure-aware mechanisms went live. The paper also includes a concrete case study where an ECN spike to 10K-30K events per second on one NIC coincided with a 26% iteration-time increase and led Aegis to a silently lossy link.

## Novelty & Impact

The closest named systems are SuperBench and MegaScale. SuperBench is an offline validation suite; Aegis keeps the pre-delivery idea, but adds runtime diagnosis and makes the offline path incremental and topology-aware. MegaScale also targets large-scale training faults, but it assumes deep visibility into model code. Aegis's novelty is the combination of public-cloud deployability and enough runtime specificity to distinguish computation-side and communication-side failures from CCL alone.

This is an operational paper more than a new theory paper, but it is a useful one. It shows how a provider can turn diagnosis from an ad hoc manual practice into a layered service capability, and it offers a concrete argument that collective communication is the practical observability boundary for multi-tenant training clouds.

## Limitations

The paper openly trades completeness for deployability. CCL instrumentation is only a "bridge": it identifies the culprit host or path well enough to isolate it, but the deeper root-cause analysis is still done offline and is explicitly out of scope. The system also has real maintenance cost, because Alibaba must ship customized CCL builds across many released versions and heterogeneous customer images.

The evaluation is also mostly outcome-based. The authors do not provide per-fault precision/recall tables, and several monitored metrics are withheld for confidentiality. Most quantitative results come from one internal LLM training project rather than a broad set of external workloads. Some fixes still require vendor cooperation, such as the congestion-control firmware bug discussed in the lessons section. Finally, CBD adds startup latency, which is why the paper needs a separate lightweight mode for latency-sensitive PaaS users.

## Related Work

- _Xiong et al. (USENIX ATC '24)_ - `SuperBench` validates AI infrastructure before deployment, whereas `Aegis` extends that philosophy into runtime localization and a lighter pre-delivery check path.
- _Jiang et al. (NSDI '24)_ - `MegaScale` diagnoses large-scale training by watching CUDA events in model-defined critical sections, while `Aegis` avoids any dependence on customer-code instrumentation.
- _Liu et al. (SIGCOMM '24)_ - `R-Pingmesh` is a service-aware RoCE monitoring system for networks, but `Aegis` argues that network-only visibility is not enough once collective-training failures fan out across the whole job.
- _Harsh et al. (SIGCOMM '23)_ - `Murphy` diagnoses distributed cloud applications from correlated observability data, whereas `Aegis` tailors correlation logic to synchronized collective training and multi-tenant cloud constraints.

## My Notes

<!-- empty; left for the human reader -->

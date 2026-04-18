---
title: "Mitigating Scalability Walls of RDMA-based Container Networks"
oneline: "ScalaCN infers hidden RNIC bottlenecks with combinatorial causal testing and reorganizes offloaded flow tables before RDMA container networks hit scale-induced cliffs."
authors:
  - "Wei Liu"
  - "Kun Qian"
  - "Zhenhua Li"
  - "Feng Qian"
  - "Tianyin Xu"
  - "Yunhao Liu"
  - "Yu Guan"
  - "Shuhong Zhu"
  - "Hongfei Xu"
  - "Lanlan Xi"
  - "Chao Qin"
  - "Ennan Zhai"
affiliations:
  - "Tsinghua University"
  - "Alibaba Cloud"
  - "University of Southern California"
  - "UIUC"
conference: nsdi-2025
pdf_url: "https://www.usenix.org/system/files/nsdi25-liu-wei.pdf"
project_url: "https://scala-cn.github.io"
tags:
  - rdma
  - networking
  - datacenter
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ScalaCN is a greybox-like system for RDMA-offloaded container networks: it infers likely RNIC bottlenecks from common datapath abstractions, predicts when performance is about to fall off a scalability cliff, and rewrites the offloaded flow-table layout before that happens. On the authors' production workloads, it resolves 82% of inferred causes, lifting bandwidth by 1.4x and cutting packet-forwarding latency by 31%.

## Problem

The paper studies a deployment regime that earlier container-network papers mostly sidestep: a production RDMA-offloaded container network with about 8K hosts, about 40K RNICs, roughly 0.5 million active containers on average, and roughly 1 million at peak. In that environment, the advertised value proposition of an RDMA-based container network is real at moderate scale, but it stops being stable at very large scale. The paper reports that when active containers grow from 0.4 million to 0.8 million, end-to-end bandwidth can drop by 87% and packet-forwarding latency can rise by 34x.

The difficult part is that the failures do not look like one clean bug. Continuous monitoring over a year found 13,396 RNIC-related performance issues that mostly manifested as eight symptoms: repeated flow re-offloading in OVS, driver stagnation or crashes, slow flow-state maintenance, intermittent software forwarding, specific flows becoming permanently slow after new masks are added, PCIe failures when unbinding VFs, and RNIC unresponsiveness when too many VXLAN contexts are offloaded. Those symptoms span the virtual switch, the kernel driver, and hardware.

The obvious response would be "find the RNIC root cause and fix it," but the paper's premise is that cloud operators do not have enough visibility for that. Commodity RNIC internals are largely closed, vendors cannot easily reproduce million-container production workloads, and the operator cannot just hand production traces to the vendor. So the real problem is not only that large RDMA container networks hit scalability walls; it is that they hit them inside a device the operator cannot directly inspect.

## Key Insight

The central insight is that full white-box visibility is not required to do useful diagnosis and mitigation. Even for a closed RNIC, operators still know the common abstractions the device must expose in this environment: queue pairs for RDMA verbs, embedded match-action switching tables for offloaded packet processing, matching masks that partition flow entries, and action lists such as forwarding and VXLAN operations. If ScalaCN builds candidate architecture models from those abstractions, filters impossible ones using topology and reachability constraints, and then perturbs workloads dimension by dimension, it can infer which components are likely on the critical packet-processing path.

That process leads to one durable conclusion across the studied RNICs: performance cliffs are strongly tied to flow-table organization, especially the number of matching masks that queued in-flight packets must query. In other words, the bottleneck is not merely "too many flows" in the abstract. It is that new flow patterns force the RNIC to walk more mask groups in the packet-switching path, and that extra query depth interacts with queue contention to hurt throughput and latency. Once that is understood, mitigation can target the offloading schedule rather than waiting for hardware redesign.

## Design

ScalaCN has an offline reasoning phase and a runtime control phase. Offline, it performs combinatorial causal testing. It first abstracts the RNIC datapath into queue pairs, eSwitch flow tables, matching masks, and actions. Naively, the number of possible component combinations is enormous, but ScalaCN prunes the search space using topological restrictions: candidate combinations that create packet loops or unreachable destinations are invalid, so only those that still deliver packets correctly are tested. The paper says this cuts the search magnitude down to a quadratic-polynomial scale relative to subnet and container structure instead of the original combinatorial blow-up.

For each valid architecture model, ScalaCN runs real and synthetic workloads, looks for symptoms resembling the production failures, and then applies local sensitivity analysis plus permutation removal. The sensitivity analysis varies one configuration dimension at a time, such as the number of matching masks, to see whether the symptom gets better or worse. Permutation removal then eliminates dimensions that do not materially change the outcome, leaving a more concrete critical path. This is how the system infers, for example, that matching-mask growth is a likely cause of S6-style persistent slowdown, while delayed flow deletion or stale counters explain S1, S4, and S5.

Runtime prediction uses the inferred performance model rather than opaque ML features alone. ScalaCN tracks the average number of matching-mask queries performed by queued in-flight packets on the local and remote hosts. It fits bandwidth with a radial basis function over those two query counts and fits latency with a linear model. The reported runtime prediction accuracy is high enough to drive proactive control: 98.9% for bandwidth and 98.5% for latency.

When predicted degradation exceeds an empirical 5% threshold, ScalaCN reorganizes offloaded flow tables. Its main mechanism is to split masks into one exact-match hyper mask at the front and a set of more general cascading masks behind it. Newly observed packet patterns first land in cascading masks, but hot concrete flows are activated into the hyper mask so later packets pay only one fast exact-match query. Cascading masks are reprioritized by a locality score based on mask specificity and recent packet volume, aged entries are evicted with LRU, and likely future flows can be pre-warmed from a Gaussian-mixture traffic model. The system therefore changes the query structure of offloaded rules without changing network semantics.

## Evaluation

The evaluation covers both a 50-host experimental RCN and real production workloads across six RNIC models: NVIDIA ConnectX-4/5/6/7, BlueField-3, and Intel E810. The microbenchmarks show why the mechanism works. Under the default offloading strategy, bandwidth drops sharply as flow count grows; at 15K offloaded flows, ScalaCN improves average aggregated bandwidth by 40.4% and reduces average packet-forwarding latency by 30.5%. The paper also shows thresholds where collapse accelerates, such as around 8K flows on CX-6, which matches the earlier diagnosis that mask/query depth produces nonlinear cliffs.

The prediction results are important because ScalaCN is supposed to act before collapse, not after. Packet-queue utilization prediction has at most +2.82% bias, and the derived bandwidth and latency predictions achieve 98.9% and 98.5% accuracy. A baseline ML predictor built from generic flow features performs much worse, with very large positive and negative biases. That matters because the paper's thesis is about explainable, control-oriented prediction rather than passive correlation.

The operational costs are present but bounded. Startup delay rises with scale, yet most of that delay is still attributed to OVS in user space; ScalaCN adds about 18% of the startup-delay breakdown, versus 12% for the driver. CPU overhead grows roughly linearly with offloaded flows and converges to about 5% of one core. On production workloads, average bandwidth improves by 17% and average latency falls by 15%, with larger gains on some RNIC families. The paper also notes a narrow losing regime: computation-heavy tasks with little communication can see trivial performance drops below 5%, and this happens on fewer than 0.03% of RNICs in their fleet.

## Novelty & Impact

The paper's novelty is not another faster container datapath in isolation. It is a production-driven workflow that connects symptoms, inferred RNIC architecture, runtime prediction, and a concrete mitigation policy for commodity closed RNICs. Earlier work studied container overlays, RDMA container networking, or black-box RNIC behavior, but ScalaCN turns that understanding into a closed loop that both explains and avoids large-scale failures.

Its practical impact is credible because the loop extends beyond the paper's own measurements. Vendors confirmed the reported issues and likely causes, and the authors state that fixes for several causes already landed in driver or firmware updates, while others are still being addressed collaboratively. That makes ScalaCN look less like a lab-only optimizer and more like an operator technique for surviving today's hardware while feeding evidence back into tomorrow's RNIC designs.

## Limitations

ScalaCN infers likely causes; it does not prove full internal root cause in the formal sense. The authors are explicit that they approximate architecture and performance models from common abstractions because the real RNIC implementation is closed. That means the method is only as good as the abstractions and the validation loop. It worked well in this paper, but it is still a greybox argument rather than a source-level explanation.

The optimization target is also limited. ScalaCN is strongest when performance loss comes from configurable packet-processing structure, especially flow-table queries and mask organization. If the real bottleneck is inherent on-chip SRAM contention or another hard capacity limit, the paper says hardware redesign may still be necessary. Operationally, ScalaCN also requires continuous monitoring, modifications around OVS offload behavior, and enough traffic locality to make its hyper-mask scheme pay off.

## Related Work

- _Kim et al. (NSDI '19)_ - `FreeFlow` builds software-based virtual RDMA networking for containers, whereas ScalaCN studies failures in hardware-offloaded RDMA container networks that already exist at production scale.
- _Kong et al. (NSDI '23)_ - `Understanding RDMA Microarchitecture Resources for Performance Isolation` characterizes black-box RNIC resource behavior in controlled settings, while ScalaCN infers packet-processing critical paths and uses them to drive online mitigation in a live RCN.
- _Yu et al. (SIGCOMM '23)_ - `Lumina` reveals micro-behaviors of hardware-offloaded network stacks through black-box measurement, while ScalaCN adds RNIC-specific abstractions and converts the resulting explanations into prediction and flow-table reorganization.
- _Wang et al. (NSDI '23)_ - `SRNIC` proposes a new scalable RNIC architecture, whereas ScalaCN improves today's commodity RNIC deployments without re-architecting the hardware.

## My Notes

<!-- empty; left for the human reader -->

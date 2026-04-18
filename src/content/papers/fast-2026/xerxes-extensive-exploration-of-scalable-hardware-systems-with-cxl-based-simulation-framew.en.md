---
title: "Xerxes: Extensive Exploration of Scalable Hardware Systems with CXL-Based Simulation Framework"
oneline: "Xerxes simulates CXL 3.1 fabrics with graph routing and device-managed coherence, letting researchers study topology, DMC, and full-duplex PCIe tradeoffs before hardware exists."
authors:
  - "Yuda An"
  - "Shushu Yi"
  - "Bo Mao"
  - "Qiao Li"
  - "Mingzhe Zhang"
  - "Diyu Zhou"
  - "Ke Zhou"
  - "Nong Xiao"
  - "Guangyu Sun"
  - "Yingwei Luo"
  - "Jie Zhang"
affiliations:
  - "Computer Hardware and System Evolution Laboratory"
  - "Peking University"
  - "Xiamen University"
  - "Mohamed bin Zayed University of Artificial Intelligence"
  - "Institute of Information Engineering, Chinese Academy of Sciences"
  - "Huazhong University of Science and Technology"
  - "Sun Yat-sen University"
conference: fast-2026
category: flash-and-emerging-devices
code_url: "https://github.com/ChaseLab-PKU/Xerxes"
tags:
  - hardware
  - memory
  - disaggregation
  - networking
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Xerxes is a CXL simulation framework built for features that current hardware and most prior tools cannot expose yet, especially port-based routing, device-managed coherence, and detailed PCIe full-duplex behavior. Its main move is to model the fabric as a graph and every endpoint as an active peer, so topology, coherence, and link-level effects emerge from first-principles interactions instead of being injected as a pre-fit latency curve.

## Problem

The paper starts from a sharp mismatch between where CXL is headed and what researchers can actually study. CXL 3.x is supposed to support rack-scale pools of compute and memory, direct peer-to-peer traffic, and device-side coherence management. But available platforms are still early-generation, mostly host-centric, and too small to reveal how a future fabric with many switches and many intelligent devices will behave.

Existing methodologies fail for different reasons. NUMA-based emulation can mimic some remote-memory latency, but it inherits socket-count limits and misses protocol behavior that distinguishes CXL from UPI-style NUMA. Behavioral simulators such as MESS and CXLMemSim are faster and convenient, yet they depend on pre-characterized latency-bandwidth curves, so they can reproduce a known device but cannot predict the performance of a topology or coherence scheme that has never been built. Traditional architectural simulators split the problem in the wrong place: computation-centric simulators assume a centralized host-managed memory hierarchy, while network simulators understand flexible fabrics but not memory semantics and coherence traffic. The result is that the design questions introduced by CXL 3.1, such as whether a tree topology collapses at the root, how a device-managed snoop filter should evict entries, or when PCIe full duplex actually helps, are still hard to answer quantitatively.

## Key Insight

The central proposition is that predictive CXL simulation needs two independent but tightly coupled abstractions: a fabric model that treats connectivity and routing as a graph problem, and a device model that treats hosts, accelerators, and memory devices as peer agents rather than passive peripherals. Once those two pieces are explicit, new CXL features stop looking like awkward exceptions to a host-centric memory simulator and instead become natural consequences of packet routing, endpoint behavior, and coherence state transitions.

That framing matters because the paper is not just claiming "more detail is better." It is claiming that the missing fidelity sits at the interaction boundaries. Port-based routing changes which paths congest. Device-managed coherence changes who initiates coherence traffic and where invalidation latency appears. PCIe full duplex changes how mixed read/write traffic uses the link. A simulator that only injects average delay cannot capture those cross-effects, but a simulator with graph-level routing, explicit buses and switches, and device-side coherence components can.

## Design

Xerxes is organized into an interconnect layer and a device layer. The interconnect layer builds a graph of the system topology at initialization time and provides routing information to all components. Its default routing is shortest-path based, while switch components can query the graph and build their own forwarding tables. This is the piece that makes arbitrary non-tree fabrics practical: chain, tree, ring, spine-leaf, and fully connected layouts all become configuration choices rather than hard-coded simulator structure.

The device layer models all participants as active agents. A requester encapsulates a request queue, an address-translation/interleaving unit, and cache-coherence management. That is enough for hosts or accelerators to generate synthetic traffic, replay traces, keep private cache state, and answer back-invalidation snoops. On the interconnect side, Xerxes provides a detailed bus model that tracks simultaneous traffic in both directions and allocates bandwidth independently per direction, plus a switch model that implements port-based routing rather than PCIe-style hierarchical forwarding.

For device-managed coherence, Xerxes includes a concrete device-side snoop filter that acts as a DCOH-like component. The snoop filter tracks owners and sharers for cached lines, allocates and evicts entries, and issues `BISnp` requests when ownership conflicts require back-invalidation. Because that logic is modular, the simulator can sweep victim-selection policies and protocol choices such as `InvBlk` length instead of baking in one fixed coherence controller. The framework is also designed to cooperate with existing simulators rather than replacing them wholesale: the paper shows wrappers for gem5, DRAMsim3, and SimpleSSD so Xerxes can supply CXL-specific fabric behavior while other tools provide detailed endpoint models.

## Evaluation

The validation story is stronger than most simulation papers because the baselines are given generous treatment. Xerxes is calibrated against a dual-socket Xeon Gold 6416H platform with a Montage CXL 2.0 memory expander, while MESS and CXLMemSim are also fed ground-truth latency-bandwidth data from that same hardware. Even under that favorable setup for the behavioral simulators, Xerxes matches loaded-latency curves with an average error of `4.3%`, predicts PBR path latency with `10.4%` average error, and matches the extra dirty-write latency of a DMC back-invalidation round-trip within `1.4%`. For end-to-end SPEC CPU2017 experiments, Xerxes reports CXL-induced execution-time overheads within `0.7%` of hardware on `gcc`, while the paper reports larger deviations for NUMA emulation, gem5-garnet, and the behavioral tools.

The design-space experiments are the more interesting result. On topology, chain and tree fabrics saturate at a single critical bridge path, ring reaches about `2x` port capacity, spine-leaf reaches about `N/2` times per-port bandwidth, and fully connected reaches `N` times because every requester can use a direct path. On traced real workloads, ring improves throughput by up to `1.72x` over chain, while spine-leaf and fully connected improve it by up to `3.63x`. On DMC policy, a `LIFO` snoop-filter victim policy improves bandwidth by `5%`, reduces average latency by `15%`, and cuts invalidation count by `16%` compared with `FIFO`, because most requests reaching the snoop filter are misses on colder lines rather than reuse of hot ones. On protocol tuning, `InvBlk` of length `2` is the sweet spot: clearing more than one line per snoop helps, but longer blocks lose the gain to extra cache-touch overhead and bandwidth competition within the invalidation flow. Finally, the full-duplex study shows why physical-layer modeling matters. With zero header overhead, a `1:1` read/write mix nearly doubles bandwidth; when header size grows to match payload size, that benefit disappears. The workloads support the paper's core claim well because they exercise exactly the mechanisms Xerxes exposes: critical-path congestion, snoop-filter pressure, and bidirectional link utilization.

## Novelty & Impact

The novelty is not that Xerxes simulates "CXL memory" in the abstract. The paper's contribution is a predictive simulator for future CXL fabrics whose behavior emerges from explicit models of topology, switching, coherence, and bus transmission. Relative to behavioral CXL simulators, Xerxes models the reasons performance changes, not just the final delay curve. Relative to NUMA emulation or current hardware studies, it explores CXL 3.1 capabilities that do not yet exist in shipping systems. Relative to host-centric architectural simulators, it treats coherence as distributed and peer-driven.

That makes the work useful to multiple communities. CXL architects can use it to compare topologies and coherence mechanisms before silicon exists. Systems researchers working on disaggregated memory or accelerator pools can plug in endpoint simulators and ask end-to-end questions about bottlenecks. The paper is therefore both a mechanism paper and an infrastructure paper: the mechanism is the two-layer graph-plus-peer modeling approach, and the impact is that it turns future-fabric questions into experiments rather than speculation.

## Limitations

The largest limitation is that the most interesting CXL 3.1 features still cannot be validated against real hardware. Xerxes is calibrated on a real CXL 2.0 memory-expander platform, but its claims about PBR and DMC correctness are checked against theoretical latency models rather than silicon measurements. That is a reasonable interim step, but it means the strongest evidence for future-fabric accuracy is consistency with the authors' component model, not external ground truth.

The abstraction level is also selective. Xerxes is detailed where the paper's questions live, namely switches, buses, requester behavior, and snoop-filter state, but it still relies on integrated backends or trace replay for much of the endpoint microarchitecture. Some policy studies are deliberately stylized, such as the skewed hot/cold workload for snoop-filter eviction or synthetic read/write mixes for duplex analysis. The paper also does not study adaptive routing, failures, or software complexity on a real large-scale stack. Those omissions do not undermine the current results, but they narrow the scope from "complete rack-scale CXL system model" to "accurate exploration framework for a chosen set of architectural questions."

## Related Work

- _Esmaili-Dokht et al. (MICRO '24)_ - MESS uses calibrated latency-bandwidth behavior for application profiling, while Xerxes models switches, buses, and coherence transactions to predict unseen fabrics.
- _Sun et al. (MICRO '23)_ - _Demystifying CXL Memory_ characterizes genuine CXL-ready systems; Xerxes uses real hardware for validation but pushes beyond currently available topologies and coherence modes.
- _Gouk et al. (USENIX ATC '22)_ - _DirectCXL_ studies memory disaggregation on available CXL hardware, whereas Xerxes targets the design space of future PBR- and DMC-enabled systems.
- _Tang et al. (EuroSys '24)_ - ASIC-based CXL-memory optimization explores one hardware design point, while Xerxes provides the simulation substrate for comparing broader topology and protocol alternatives.

## My Notes

<!-- empty; left for the human reader -->

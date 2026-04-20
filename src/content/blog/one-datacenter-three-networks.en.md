---
title: "One Datacenter, Three Networks"
oneline: "A 2026 datacenter is no longer one folded Clos — general-purpose DCs still ride a single IP fabric, but AI DCs layer a scale-up fabric, a scale-out backend, a frontend, and a WAN, each with a specific topology recipe."
topic: datacenter-networking
tags:
  - networking
  - datacenter
  - gpu
  - rdma
  - ml-systems
total_words: 2960
reading_time_minutes: 14
written_by: "Claude Opus 4.7 (Claude Code)"
publish_date: 2026-04-20
draft: false
---

## Thesis

The textbook picture of a datacenter network is a single fat-tree Clos: commodity switches arranged in a folded topology that looks non-blocking to every server. That picture is still accurate for the general-purpose datacenters that run EC2, S3, Aurora, Spanner, and every other non-AI workload. It is badly misleading for the GPU datacenters where the hyperscalers actually spend their 2026 capex. An AI datacenter is no longer one network; it is three, plus a fourth that leaves the building. A scale-up fabric (NVLink or TPU ICI) behaves like memory, a scale-out backend (InfiniBand, RoCE, or AWS SRD) carries collectives, a frontend Ethernet carries storage and control, and a wide-area SDN carries cross-DC training. The interesting industrial question has stopped being "what topology do you use?" and become "how do you build four topologies that stay out of each other's way?"

## The setup

For about a decade, the dominant mental model of "a datacenter network" was Google's Jupiter. That model — IP fabric, folded Clos, ECMP on 5-tuple, merchant silicon — is now the baseline everyone inherits. The rest of this post is a spec-level tour of (a) what that baseline actually looks like today in a general-purpose DC and (b) what an AI DC layers on top of it. We give concrete topology recipes where we can, so a reader can trace which node connects to which through which fabric.

## Part 1 — The industrial playbook

### General-purpose DC: folded Clos, specified

The unit of construction is a **rack**. A hyperscaler rack holds 20–48 servers connected to a single **Top-of-Rack (ToR)** switch. Typical southbound pattern: 48 server ports at 25/50/100 Gbps. Typical northbound pattern: 4–8 uplinks at 400 Gbps to the next tier. Oversubscription at the ToR is 1:1 for production hyperscaler pods and 2:1–3:1 for enterprise. Above the ToR sit two more tiers: **leaf** switches aggregate ~32 ToRs into a pod, **spine** switches interconnect pods. The whole shape is a folded Clos with BGP-to-the-ToR and ECMP hashing on 5-tuple.

Three concrete instantiations:

- **Meta F16.** Every pod is wired as 16 parallel 100 G planes. Each rack's ToR has 16 northbound uplinks — one per plane — landing on 16 fabric switches (FSWs) built from Minipack ASICs (128×100 G each). FSWs uplink to spine. The 16×100 G choice was explicit: 400 G optics were not yet practical at fleet volume. See [F16 / Minipack](https://engineering.fb.com/2019/03/14/data-center-engineering/f16-minipack/).
- **Google Jupiter (current).** No longer a pure Clos at the top: aggregation blocks (512×400 Gbps client ports, 204.8 Tb/s per block) are cross-connected by MEMS Optical Circuit Switches, and SDN traffic engineering sets link capacities between blocks. 64 blocks × 400 Gbps = ~13 Pb/s bisection per fabric. See [Jupiter Evolving](https://dl.acm.org/doi/pdf/10.1145/3544216.3544265) and [Speed, scale, reliability: 25 years of datacenter networking](https://cloud.google.com/blog/products/networking/speed-scale-reliability-25-years-of-data-center-networking).
- **AWS EC2.** Servers carry an ENA NIC at 25/50/100/200 Gbps (instance-type dependent). ENA implements [AWS SRD](https://www.amazon.science/publications/a-cloud-optimized-transport-protocol-for-elastic-and-scalable-hpc), which sprays packets across up to 64 ECMP paths on a standard Ethernet Clos and reorders in Nitro silicon. No RoCE, no PFC, no InfiniBand.

### DBMS, storage, and search clusters ride the same Clos

Workloads differ; the physical topology mostly doesn't. The variation shows up in oversubscription, replica placement, and transport choice — not in wiring.

- **Distributed OLTP (Spanner, CockroachDB, Aurora).** Replicas intentionally span racks and availability zones for fault isolation, so every Paxos round pays leaf-spine hops. AWS Aurora splits compute and storage into different tiers of the same Clos, with storage shards replicated 6-way across 3 AZs. Cross-AZ latency (~1–2 ms) is the dominant term in commit latency; the topology itself is an ordinary Clos.
- **Object storage (S3, Colossus).** Racks of storage servers hang off the Clos just like compute racks. The traffic pattern is asymmetric — reads aggregate toward compute racks — so ToR-to-spine uplinks on storage racks are sized for egress. Oversubscription on the storage side is usually higher than on the compute side because aggregate throughput, not tail latency, is the SLA.
- **Search / OLAP (Bigtable, BigQuery, F1).** Fan-out traffic: a leaf query node broadcasts to hundreds of worker shards and waits on the slowest. Tail latency dominates. This is the single largest reason modern Ethernet fabrics optimize p99 over raw throughput.

### Traditional DC, remaining design details

- **Routing is L3 to the ToR.** VLANs are used sparingly. Tenant isolation is an overlay (VXLAN or Geneve) on top of an IP fabric. AWS VPC, Azure VFP, and Google Andromeda all fit this pattern — the overlay is software on top of the physical Clos.
- **The NIC is the tenant/datacenter boundary.** AWS Nitro, Azure SmartNIC, Google Titanium terminate the overlay, enforce security groups, and offload the TCP stack. On AWS, the host's Linux kernel sees an SR-IOV vNIC; Nitro owns everything below.
- **Traffic is ~80% east-west.** North-south egress exits through separate edge routing layers; this is why Meta, Google, and AWS all run distinct WAN backbones for DC-to-DC vs DC-to-Internet (see the WAN subsection).

### GPU DC: scale-up fabric (inside one rack)

AI racks break the single-Clos picture starting at the rack.

**GB200 NVL72 (NVIDIA).** 18 compute trays per rack; each tray = 2 Grace CPUs + 4 Blackwell GPUs, so 36 Grace + 72 Blackwell per rack. Each B200 GPU has 18 NVLink ports × 100 GB/s = 1.8 TB/s bidirectional per GPU. 9 NVLink-Switch trays per rack (each tray is a 144-port non-blocking switch at 100 GB/s per port) cross-connect all 72 GPUs into a single NVLink domain — every GPU reaches every other GPU in the rack through exactly one NVLink-Switch hop, at ~130 TB/s aggregate. External NVLink-Switch extensions push the domain to 576 GPUs at >1 PB/s. See the [GB200 NVL72 product page](https://www.nvidia.com/en-us/data-center/gb200-nvl72/) and the [NVIDIA technical blog](https://developer.nvidia.com/blog/nvidia-gb200-nvl72-delivers-trillion-parameter-llm-training-and-real-time-inference/).

**TPU v4 pod (Google).** 4096 chips organized as a 3D torus. The building block is a 4×4×4 = 64-chip cube; each chip has 6 ICI links (one per ±X/±Y/±Z neighbor) at ~50 GB/s per direction. 64 cubes are stitched by 48 Palomar 3D-MEMS OCSes (136-port each), which reconfigure the inter-cube topology — including twisted-torus shapes that buy 1.3–1.6× all-to-all throughput over a plain torus. TPU v5p scales this pattern to 8,960 chips/pod with 4,800 Gb/s per-chip ICI. See [TPU v4 (ISCA '23)](https://arxiv.org/abs/2304.01433) and the [v5p docs](https://docs.cloud.google.com/tpu/docs/v5p).

The number to internalize is the asymmetry. A B200 sees 1.8 TB/s over NVLink but ~50 GB/s per ConnectX-7 NIC. A parallelism axis (TP, CP) that fits inside the NVLink domain runs at near-memory speed; an axis that spills out drops by 30×+.

### GPU DC: scale-out backend (across racks)

Outside the NVLink or ICI domain, GPUs talk over a dedicated NIC fabric.

**DGX SuperPOD H100 (NVIDIA reference).** The unit is a **Scalable Unit (SU)** of 32 nodes. Each node has 8 H100 GPUs and 8 ConnectX-7 NICs at 400 Gbps. The fabric is **rail-optimized**: for rail `k` ∈ {1..8}, the k-th NIC of every node in the SU attaches to exactly two rail-`k` leaf switches (one "left" one "right" for redundancy). So for rail `k` on node A to reach rail `k` on node B, traffic passes through exactly one leaf hop. Cross-rail traffic (e.g., GPU 1 of node A to GPU 3 of node B) must cross a spine. Four SUs (128 nodes, 1024 GPUs) form a SuperPOD; larger deployments add a spine layer. The upcoming [B300 / Quantum-X800](https://docs.nvidia.com/dgx-superpod/reference-architecture/scalable-infrastructure-b300-xdr/latest/network-fabrics.html) grows the rail-aligned unit to 72 nodes at 800 Gbps. See [SuperPOD H100 fabric](https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-h100/latest/network-fabrics.html).

**Meta GenAI clusters (24,576 GPUs, 2024).** Grand Teton servers, 8 GPUs + 8×400 Gbps NICs per server. Two variants share the rack hardware: one uses Arista 7800 + Minipack2 switches running RoCEv2, the other uses NVIDIA Quantum-2 InfiniBand. Both are rail-aligned fat-trees, **physically separate** from Meta's general-purpose DC fabric. On the RoCE variant, flows are split across 16 QPs per node-pair and ECMP hashes on destination QP (via UDF) — this "Enhanced-ECMP" gives up to 40% AllReduce improvement over plain 5-tuple ECMP. See the [SIGCOMM '24 paper](https://engineering.fb.com/wp-content/uploads/2024/08/sigcomm24-final246.pdf) and the [engineering post](https://engineering.fb.com/2024/08/05/data-center-engineering/roce-network-distributed-ai-training-at-scale/).

**xAI Colossus (100K+ H100s, Memphis).** Spectrum-X platform: SN5600 Spectrum-4 switches at 800 Gbps + BlueField-3 SuperNICs. Three-tier fabric (ToR → leaf → spine). NVIDIA reports 95% effective throughput at this scale, vs ~60% for plain Ethernet. See [NVIDIA's Colossus announcement](https://nvidianews.nvidia.com/news/spectrum-x-ethernet-networking-xai-colossus).

### GPU DC: explicit frontend/backend split

A modern AI rack runs at least two physical networks per node, with assignment enforced at the NIC. On a **GB200 compute tray**:

- **Compute (backend) plane.** 4× ConnectX-7 NICs (one per two GPUs via PCIe Gen5), attached to the InfiniBand or Spectrum-X compute fabric. Carries AllReduce, AllGather, P2P collective traffic.
- **Storage + in-band management plane.** 2× BlueField-3 DPUs, attached to a separate Ethernet storage/management fabric. Carries checkpoint I/O, dataset ingest, VPC overlay, orchestration (Slurm, K8s).
- **Out-of-band management.** A third, isolated Ethernet for IPMI/BMC.

See the [GB200 SuperPOD fabric doc](https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-gb200/latest/network-fabrics.html). The separation is architectural: the two planes have different transports, different congestion-control regimes, and often different switch vendors.

### Cross-DC: SDN WANs, split by traffic class

Every hyperscaler runs at least two WANs, separated by traffic class. Cross-DC training rides the internal (DC-to-DC) one, not the Internet-facing one.

- **Google B4** (internal WAN): OpenFlow + SDN on merchant silicon, centralized TE pushes links to ~100% utilization at peak. [B4-After](https://research.google/pubs/b4-and-after-managing-hierarchy-partitioning-and-asymmetry-for-availability-and-scale-in-googles-software-defined-wan/) scaled it to 33 sites with hierarchical TE and two-phase flow matching (8× more TE rules fit the same silicon). Separate from B2, Google's Internet-facing WAN. See [B4 (SIGCOMM '13)](https://conferences.sigcomm.org/sigcomm/2013/papers/sigcomm/p3.pdf).
- **Meta Express Backbone (EBB).** MPLS-based, multi-plane, carries 100% of DC-to-DC traffic since ~2015. Hybrid control: centralized MPLS-TE for gold/silver/bronze LSPs, distributed Open/R agents install backup paths for fast local failover. Separate from Meta's Classic Backbone (CBB) which handles DC-to-POP. See [EBB (SIGCOMM '23)](https://dl.acm.org/doi/pdf/10.1145/3603269.3604860) and the [2025 10X Backbone post](https://engineering.fb.com/2025/10/16/data-center-engineering/10x-backbone-how-meta-is-scaling-backbone-connectivity-for-ai/).
- **AWS Global Network.** ~20M km of fiber, 400 GbE internal standard, custom optical transport, physical-layer encryption on all inter-facility traffic. See the [AWS Global Network page](https://aws.amazon.com/about-aws/global-infrastructure/global-network/).

**AI-on-WAN.** [Pathways](https://arxiv.org/pdf/2203.12533) plus [PaLM](https://arxiv.org/pdf/2204.02311) trained 540B parameters across two TPU v4 pods (3,072 chips each, 768 hosts each): within-pod SPMD over ICI, cross-pod gradient exchange over the ordinary DCN, orchestrated by a single-controller runtime. [Gemini's technical report](https://storage.googleapis.com/deepmind-media/gemini/gemini_v2_5_report.pdf) confirms multi-pod and multi-DC training is now routine at frontier scale. The WAN has become a fourth tier of the training fabric.

### Summary: what connects to what, by tier

| Tier | Who it connects | Fabric / transport | Example at 2026 scale |
|---|---|---|---|
| Scale-up | GPUs inside a rack | NVLink + NVSwitch, or TPU ICI torus | GB200 NVL72 (72 GPUs, 1.8 TB/s/GPU); TPU v5p pod (8,960 chips) |
| Scale-out backend | GPU NICs across racks | InfiniBand NDR/XDR, RoCEv2, or AWS SRD | DGX SuperPOD, Meta 24K RoCE, xAI Colossus, AWS EFA |
| Frontend (DC) | Everything else — storage, ingest, VPC, mgmt | L3 Ethernet Clos + overlay | EC2, S3, Lambda, all CPU workloads |
| Cross-DC WAN | DCs to DCs | MPLS + centralized SDN TE | Google B4, Meta EBB, AWS Global Network |

### Lossless-Ethernet congestion control (the tax you pay for RoCE)

RoCEv2 needs a lossless fabric, which means PFC, which means a congestion-control protocol that keeps queues short enough that PFC doesn't fire cascades.

- **DCQCN** (Microsoft): ECN-based rate control, co-designed with PFC. See [DCQCN](https://conferences.sigcomm.org/sigcomm/2015/pdf/papers/p523.pdf) and [RDMA over Commodity Ethernet at Scale](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/11/rdma_sigcomm2016.pdf).
- **HPCC** (Alibaba): INT-based precise rate update. Up to 95% FCT reduction vs DCQCN. See [HPCC](https://liyuliang001.github.io/publications/hpcc.pdf).
- **E-ECMP** (Meta): ECMP hashes on QP, 16 QPs per pair. Up to 40% AllReduce improvement. See the [Meta RoCE paper](https://engineering.fb.com/wp-content/uploads/2024/08/sigcomm24-final246.pdf).

PFC deadlock is the constant tail risk: paused links forming a directed cycle will deadlock the fabric. See [Microsoft HotNets '16](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/11/rdmahotnets16.pdf).

### Ultra Ethernet Consortium (the re-convergence bet)

[UEC Specification 1.0](https://ultraethernet.org/uec-2025-in-review-preparing-for-what-comes-next-a-letter-from-uecs-chair/) shipped 11 June 2025 — 562 pages, centered on Ultra Ethernet Transport (UET). Backers: [AMD, Arista, Broadcom, Cisco, HPE, Intel, Meta, Microsoft](https://www.prnewswire.com/news-releases/ultra-ethernet-consortium-uec-launches-specification-1-0-transforming-ethernet-for-ai-and-hpc-at-scale-302478685.html). Roadmap: congestion management, small-message performance, scale-up transport, in-network collectives. If it succeeds, the scale-up/backend/frontend separation collapses back into traffic-class boundaries on one fabric.

### Optical Circuit Switches (OCS)

Hyperscalers have normalized MEMS-based OCS as a first-class fabric primitive.

- **Palomar 3D-MEMS OCS** (Google): 136×136 ports, ~108 W per switch vs ~3 kW for a comparable-radix packet switch. In production since 2013. See [Mission Apollo](https://arxiv.org/abs/2208.10041) and [Lightwave Fabrics](https://dl.acm.org/doi/10.1145/3603269.3604836).
- **Jupiter aggregation layer** uses Palomar at the spine.
- **TPU v4** uses 48 Palomar OCSes for 3D-torus inter-cube links, <5% of system cost and <3% of system power.

## Part 2 — Where research is pushing the topology question

If Part 1 is the deployed consensus, Part 2 is the open front. Recent papers share one move: they stop treating topology as a deployment-time given and start treating it as a runtime variable.

### Synthesis: topology and collectives, co-designed

[Efficient Direct-Connect Topologies for Collective Communications](../papers/nsdi-2025/efficient-direct-connect-topologies-for-collective-communications.md) (NSDI '25) rejects the premise that you pick a topology and then pick a collective schedule to run on it. It searches the Pareto frontier of (topology, schedule) pairs using property-preserving graph expansions and a polynomial-time BFB schedule generator, and shows up to 56× AllReduce improvement over ShiftedRing at near-1000-node scale — in a regime where NCCL's default schedulers fall off the table. The framing fits optical ML clusters, TPU-style tori, and any fabric where port count is scarce: the right unit of optimization is topology-plus-schedule, not either alone.

### Reconfigurable torus fabrics

[Morphlux](../papers/asplos-2026/reconfigurable-torus-fabrics-for-multi-tenant-ml.md) (ASPLOS '26) pushes photonic programmability down to server scale. It inserts an optical interposer under each 4-accelerator server, then lets a software controller redirect sub-rack bandwidth, stitch non-contiguous free servers into a logical torus, and patch around failed accelerators without evacuating the whole job. On a TPU-cluster simulator driven by public TPU v4 slice distributions, Morphlux reclaims up to 50% of stranded `Y`-dimension bandwidth, successfully serves 32-TPU requests that default TPU/SiPAC allocators reject ~75% of the time, and recovers from single-chip failures in ~1.2 s. The claim is that the torus-vs-flexibility tradeoff dissolves once bandwidth assignment becomes programmable.

### The intra-server fabric is part of the inter-server path

[FuseLink](../papers/osdi-2025/enabling-efficient-gpu-communication-over-multiple-nics-with-fuselink.md) (OSDI '25) attacks a different corner of the same problem: when inter-server traffic is skewed, a GPU can borrow a peer GPU's idle NIC by relaying through NVLink. The mechanism is virtual-memory remapping (the NCCL buffer physically lives on a relay GPU) plus priority-aware scheduling so the NIC's real owner always wins. On 8-GPU servers with 8×400 Gbps NICs, point-to-point inter-server bandwidth goes from 49 GB/s (baseline NCCL+PXN) to 212 GB/s. The paper is the clearest statement of a new idea: NVLink fabric and RDMA fabric are two halves of one path, and runtime systems should treat them as such.

### Transport, still under relentless pressure

Nearly every top-venue networking track publishes several papers redesigning the RoCE/InfiniBand transport. [SIRD](../papers/nsdi-2025/sird-a-sender-informed-receiver-driven-datacenter-transport-protocol.md) and [Pyrrha](../papers/nsdi-2025/pyrrha-congestion-root-based-flow-control-to-eliminate-head-of-line-blocking-in-datacenter.md) (NSDI '25) attack HOL blocking from sender and receiver sides respectively; [Fork](../papers/eurosys-2025/fork-a-dual-congestion-control-loop-for-small-and-large-flows-in-datacenters.md) (EuroSys '25) runs a dual loop — sender-driven for small flows, receiver credits for elephants. [PrioPlus](../papers/eurosys-2025/enabling-virtual-priority-in-data-center-congestion-control.md) emulates many strict priority queues inside one physical queue using delay channels, avoiding switch changes. [White-boxing RDMA](../papers/nsdi-2025/white-boxing-rdma-with-packet-granular-software-control.md) and [ScalaCN](../papers/nsdi-2025/mitigating-scalability-walls-of-rdma-based-container-networks.md) expose RNIC-internal controls so software can steer packet-granular behavior and detect the "scale-induced cliff" that RDMA container fabrics hit. [Söze](../papers/osdi-2025/s-ze-one-network-telemetry-is-all-you-need-for-per-flow-weighted-bandwidth-allocation-at.md) (OSDI '25) shows that one per-packet max queueing-delay signal is enough for decentralized weighted max-min allocation — a minimalist answer to HPCC's heavier telemetry. Uniting theme: the topology is not done, so the transport is not done.

### Collective tuning and training observability

If topology is variable, the collective library must discover it. [AutoCCL](../papers/nsdi-2025/autoccl-automated-collective-communication-tuning-for-accelerating-distributed-and.md) (NSDI '25) tunes NCCL online per collective task; [MSCCL](../papers/asplos-2026/msccl-rethinking-gpu-communication-abstractions-for-ai-inference.md) (ASPLOS '26) builds collectives from hardware-near channels plus a DSL, so inference gets near-custom comms without vendor-specific stacks. Observability has become a first-class topology problem: [Holmes](../papers/nsdi-2025/holmes-localizing-irregularities-in-llm-training-with-mega-scale-gpu-clusters.md), [Mycroft](../papers/sosp-2025/mycroft-tracing-dependencies-in-collective-communication-towards-reliable-llm-training.md), and [ByteRobust](../papers/sosp-2025/robust-llm-training-infrastructure-at-bytedance.md) all start from the same observation — a 10K-GPU training job's failure signal first shows up as an odd collective-dependency pattern. [SimAI](../papers/nsdi-2025/simai-unifying-architecture-design-and-performance-tuning-for-large-scale-large-language.md) goes the other direction, reusing real frameworks and NCCL to simulate LLM training at packet granularity with 98.1% alignment to real runs — a tool for reasoning about topologies that don't exist yet.

### Production pressure valves

Two papers attack the edges that the ideal rail-optimized fat-tree story ignores. [OptiReduce](../papers/nsdi-2025/optireduce-resilient-and-tail-optimal-allreduce-for-distributed-deep-learning-in-the-cloud.md) (NSDI '25) delivers tail-bounded AllReduce in the public cloud where you cannot assume a dedicated backend. Google's [hotspot-aware placement paper](../papers/nsdi-2025/preventing-network-bottlenecks-accelerating-datacenter-services-with-hotspot-aware.md) (NSDI '25) cuts persistent ToR hotspots by 90% and Colossus p95 network latency by 50–80%, simply by placing tasks and storage on colder racks. Both are reminders that most workloads still live in the "one network, one topology" world, and even there, topology-aware scheduling is the untapped lever.

## The counter-evidence

The three-network thesis is not unchallenged. AWS's [SRD](https://aws.amazon.com/blogs/hpc/in-the-search-for-performance-theres-more-than-one-way-to-build-a-network/) is the loudest counter-example: a single Ethernet fabric with a custom transport spread across 64 paths, rather than a separate InfiniBand or RoCE backend. If SRD generalizes to collectives at GB200-class scale, the "separate backend" assumption collapses into "one fabric, one smarter transport."

Ultra Ethernet is the second pressure. [UET](https://arxiv.org/html/2508.08906v1) explicitly targets making backend and general-purpose Ethernet the same network. If it works, frontend/backend becomes a traffic-class boundary, not a physical one.

A quieter pushback comes from scale-up. NVLink domains have grown from 8 to 72 to a planned 576 GPUs. Each jump eats territory that used to belong to scale-out: if the model fits in the NVLink domain, the backend only sees data-parallel replicas and its requirements relax. "Scale-up subsumes scale-out" is a plausible future — the counter-evidence is that model sizes keep growing too.

None of these objections are strong enough to retire the three-network picture for 2026 designs. Each is a live debate, and an architect choosing a topology today should assume the boundaries will move.

## What this means

For the platform builder, you cannot pick "a network" anymore. You pick four, and you design how they share resources at the NIC and at the switch — which NIC sits on which plane, which switches are allowed to deadlock under which pause mechanism, which flows belong on which transport. NVIDIA's SuperPOD reference architectures are valuable precisely because they specify these choices at connector granularity.

For the researcher, the interesting topology work has moved up the stack. Graph-and-schedule co-design, programmable photonics, runtime-adaptive path selection — all are asking the same question: if topology is a variable, what is the control loop? The Clos-vs-fat-tree argument is over for CPU fleets; the AI-fleet argument is about reconfigurability.

For the field, the next two years decide whether the industry keeps four networks or collapses them back into one. Ultra Ethernet is the loudest re-convergence bet; NVLink's expansion is a quieter one. Whichever wins, the datacenter-network topology of 2028 will not look like the 2015 Jupiter picture — it will either be four tiers that finally agree on a shared transport, or one tier that finally agrees on everything.

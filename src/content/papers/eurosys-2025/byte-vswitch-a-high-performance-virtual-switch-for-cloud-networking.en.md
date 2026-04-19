---
title: "Byte vSwitch: A High-Performance Virtual Switch for Cloud Networking"
oneline: "BVS replaces OVS's generic switch stack with a fixed VPC pipeline, in-data-plane VM-location learning, and vendor-agnostic offload hooks to raise cloud throughput."
authors:
  - "Xin Wang"
  - "Deguo Li"
  - "Zhihong Wang"
  - "Lidong Jiang"
  - "Shubo Wen"
  - "Daxiang Kang"
  - "Engin Arslan"
  - "Peng He"
  - "Xinyu Qian"
  - "Bin Niu"
  - "Jianwen Pi"
  - "Xiaoning Ding"
  - "Ke Lin"
  - "Hao Luo"
affiliations:
  - "ByteDance Inc."
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3717479"
tags:
  - networking
  - virtualization
  - datacenter
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

BVS is ByteDance's production virtual switch for public-cloud VPC networking. The paper's core move is to give up OVS-style generality, keep policy resolution on a slow path, and specialize the fast path around a lean flow/session pipeline, compact routing and ACL structures, and in-data-plane VM-location learning. On the authors' testbed, that yields up to 3.3x higher PPS, 17% higher CPS, and 25% lower latency than OVS-DPDK.

## Problem

The paper starts from an operator's complaint about Open vSwitch: in a hyperscale public cloud, most of OVS's flexibility is unused, but its complexity is still paid for on every host. ByteDance mainly needs VPC functions such as virtual interfaces, rate limiting, routing, security groups, and observability. OVS, by contrast, carries a generic OpenFlow-oriented architecture, a deep classifier stack, and connection-tracking machinery whose cost becomes painful when public-cloud tenants create millions of flows and security groups are mandatory.

The authors point to two concrete scaling failures. First, OVS's fast caches are too small for public-cloud working sets. Even after the community replaced Exact Match Cache with Signature Match Cache, the cache still tops out at about 1 million entries, so misses fall through to `dpcls`, whose wildcard matching increases forwarding latency and hurts connection setup rate. Second, connection tracking is expensive enough that security-group support can degrade performance by up to 50%, and simply assigning more CPU cores to the switch is unattractive in a cost-sensitive cloud.

Performance is not the only problem. A host switch in this setting also has to track VM locations across huge VPCs, survive frequent software rollouts, support live migration, and remain debuggable for operators. The paper's real target is therefore not a better packet-processing microbenchmark. It is a virtual switch that is specialized enough to be fast, but also serviceable enough to run for years in a production cloud.

## Key Insight

The paper's key claim is that a cloud VPC switch should be designed around the small set of abstractions that a cloud actually uses, not around a general programmable dataplane. If the switch pipeline is fixed around VPC objects such as ENIs, routes, security groups, VM locations, and sessions, the implementation can simplify its code paths, choose data structures for those exact objects, and keep the fast path narrow enough to optimize aggressively.

That specialization also changes how distributed state should be handled. The authors observe that a BVS instance usually touches far fewer VM-location entries than exist in the whole VPC, often under 30% and closer to 20% in large VPCs. That means the right model is not to pre-program every host with every VM location. Instead, BVS can learn active locations in the dataplane and retain only what current traffic actually needs. The broader insight is that cloud-scale switching gets easier once the system optimizes for working-set state rather than full control-plane state.

## Design

BVS uses a hierarchical architecture. The VPC control plane remains the global source of truth for ENIs, subnets, routing, ACLs, and related policy. On each compute host, a `BVS-Controller` watches ETCD updates and turns them into host-local actions, while `BVS-Agent` exposes gRPC APIs, persists configuration in SQLite, and provides operational tooling. The dataplane itself is split into a slow path and a fast path. Protocol packets and first packets of new flows go through the slow path, which evaluates ACLs, security groups, routes, rate limits, and destination location. Once the decision is known, BVS installs a session-backed exact-match rule so later packets stay on the fast path.

The fast path is implemented atop Byteflow, a DPDK-based framework that standardizes NIC differences and lets BVS focus on switching logic. Several data-structure choices are central. For LPM, Byteflow replaces DPDK's memory-heavy DIR-24-8 table with Tree Bitmap, cutting memory to 0.1% of DIR-24-8 for a 1K-entry table and still about 3x lower on a 769K-entry table. For ACLs, it chooses HyperSplit instead of DPDK's Multi-Bit Tries, accepting 2-3x slower lookup in exchange for 8-21x lower memory and much faster build time. For the flow table, it adds per-thread local caches so insertion and deletion do not constantly fight over the global ring; that optimization alone raises CPS by up to 39.6%.

State management is equally specialized. Session reconciliation uses ENI-version checks instead of eagerly rewriting all flow entries after every policy change. Session aging removes idle flow state in batches. Orca, the VM-location mechanism, moves learning into the dataplane: the first packet to an unknown VM is sent through an Orca gateway, which both forwards it and sends the sender a sync message with the destination's location; later packets go directly host to host. BVS also exposes a vendor-agnostic offload layer so policies such as full-flow, elephant-flow, protocol-specific, or threshold-based offload can target different SmartNIC or DPU implementations. On top of this core, the system adds cloud-facing features such as Service Load Balancer Bypass, hitless upgrades with vhost-user state migration, and session-aware live migration.

## Evaluation

The main head-to-head comparison uses four servers with Intel Xeon 8336C CPUs, Mellanox ConnectX-6 2x100Gbps NICs, identical networking features enabled on both systems, and four hyper-threads allocated to dataplane forwarding. Under that setup, BVS-Byteflow reaches up to 3.3x the packet throughput of OVS-DPDK, improves connection setup rate by 17%, and lowers forwarding latency by 25%. The paper attributes most of this to simpler code paths, cheaper session handling, and the optimized hash-table design. In hardware-offload mode, BVS and OVS look similar until NIC SRAM fills up after about 10K flows, after which both degrade toward host-memory performance.

The other evaluations matter because they test the paper's full systems claim rather than only the forwarding path. Orca learns VM locations at 4.39 million entries per second with 16 vCPUs in a single-VPC case and 13.9 million entries per second in a 16-VPC case; update throughput reaches 2.58 million entries per second, versus about 10K entries per second for the old control-plane-driven approach. Service Load Balancer Bypass cuts load on the centralized SLB cluster from roughly 20 Tbps to a little over 4 Tbps, an 80% reduction. For hitless upgrade, the newer VSM mode drops downtime from 2400 ms to 5 ms with 16 four-queue VMs and from 5130 ms to 22 ms with 255 such VMs. For live migration, production measurements keep downtime under 300 ms and total migration time under 10 seconds even for the largest tested instance.

Taken together, the evidence supports the paper's practical thesis: most of BVS's gains come from cloud-specific specialization across dataplane, control interaction, and serviceability. The main caveat is external validity. The comparison is mostly against one OVS version and one deployment style, so the results say more about the value of a tailored public-cloud switch than about a universally dominant architecture for all virtual switching workloads.

## Novelty & Impact

BVS is not a paper about one clever forwarding primitive. Its novelty is the package: a fixed VPC-oriented pipeline, compact lookup structures, in-dataplane VM-location learning, a vendor-neutral offload abstraction, and operational mechanisms such as hitless upgrades and migration-aware session sync. Relative to prior cloud virtual switches, it emphasizes that host switching in production is an operations problem as much as a dataplane problem.

That makes the paper useful in two ways. For practitioners, it is a strong case that a hyperscale cloud should consider replacing a generic switch stack with a narrower one if the workload envelope is well understood. For researchers, it is a reminder that the right unit of comparison is often the whole service. BVS's biggest contribution may be the argument that performance, scalability, and operability should be designed together rather than treated as separate layers.

## Limitations

The paper's biggest strength is also its biggest limit: BVS wins by giving up generality. It removes OpenFlow programmability and many features that OVS supports, so the design is compelling only if the deployment really is dominated by VPC-style cloud networking. If an operator needs arbitrary middlebox behavior or a more open SDN programming model, BVS is not trying to serve that use case.

Several mechanisms also depend on assumptions that may not transfer cleanly. Orca relies on active VM-location working sets being much smaller than total VPC size and still depends on an Orca gateway cluster for first-packet learning and synchronization. Hardware offload remains constrained by vendor memory limits and weak observability; the paper explicitly notes debugging pain and performance degradation once NIC SRAM overflows. More broadly, the evaluation is almost entirely inside ByteDance's environment, so claims about cost, maintainability, and fairness of the OVS comparison should be read as production evidence rather than as a fully general benchmark study.

## Related Work

- _Dalton et al. (NSDI '18)_ - Andromeda also builds a cloud virtual networking stack with hierarchical control and host dataplanes, but BVS pushes VM-location learning into the dataplane instead of relying on control-plane identification and programming of large flows.
- _Firestone (NSDI '17)_ - VFP keeps a programmable, multi-layer match-action model under external controllers, whereas BVS deliberately narrows the switch to a fixed VPC object pipeline to simplify host-side execution.
- _Yang et al. (SIGCOMM '23)_ - Achelous also targets hyperscale VPC networking, but BVS focuses more heavily on dataplane-specialized location learning, hitless upgrades, and live-migration serviceability on the host switch.
- _He et al. (EuroSys '24)_ - Hoda specializes OVS with multiple optimized datapaths, while BVS takes the more radical step of replacing OVS's general architecture with a cloud-specific switch implementation.

## My Notes

<!-- empty; left for the human reader -->

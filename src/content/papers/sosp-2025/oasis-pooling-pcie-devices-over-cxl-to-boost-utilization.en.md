---
title: "Oasis: Pooling PCIe Devices Over CXL to Boost Utilization"
oneline: "Oasis turns a CXL memory pod into a software PCIe pool, routing remote NIC traffic through shared buffers and message channels to double NIC utilization."
authors:
  - "Yuhong Zhong"
  - "Daniel S. Berger"
  - "Pantea Zardoshti"
  - "Enrique Saurez"
  - "Jacob Nelson"
  - "Dan R. K. Ports"
  - "Antonis Psistakis"
  - "Joshua Fried"
  - "Asaf Cidon"
affiliations:
  - "Columbia University"
  - "Microsoft Azure"
  - "University of Washington"
  - "Microsoft Research"
  - "University of Illinois Urbana-Champaign"
  - "MIT CSAIL"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764812"
code_url: "https://bitbucket.org/yuhong_zhong/oasis"
tags:
  - disaggregation
  - networking
  - storage
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Oasis uses a shared CXL memory pool as both the data path and the signaling substrate that lets one host use PCIe devices attached to another host. The key move is to make this work on today's non-coherent CXL 2.0 hardware: keep device DMA off CPU caches, and build message channels whose invalidation and prefetch rules restore throughput on non-coherent memory. With that substrate, Oasis multiplexes two hosts onto one NIC with negligible interference, adds only 4-7 us per packet, and fails over to a backup NIC in 38 ms.

## Problem

The paper starts from a simple cloud-economics observation: NICs and SSDs are expensive, power-hungry, and still badly underutilized. The authors cite roughly $2,000 each for a NIC and a set of SSDs in a server, with NICs and SSDs each contributing about 13% of server power at Azure. Yet Azure traces show that 27% of NIC bandwidth and 33% of SSD capacity are stranded on average because hosts fill up on some other dimension first. Even allocated NIC bandwidth is bursty: in the rack study, P99.99 utilization is only 20%.

The paper identifies three causes: multidimensional bin packing strands resources, peak-oriented allocation leaves devices mostly idle, and redundant NICs for failover further cut average utilization. Pooling devices across hosts would attack all three problems at once, but today's options are unattractive. PCIe switches can do it, but the paper argues they are expensive and inflexible, quoting up to $80,000 of added rack cost. RDMA disaggregation helps in some storage cases, but it cannot pool NICs and excludes many devices that lack the needed peer-to-peer DMA path.

## Key Insight

Oasis's core claim is that once a rack already has a CXL memory pod for memory pooling, that same shared memory can become a cheap low-latency fabric for PCIe pooling too. The hard part is that current CXL 2.0 pools are shared but not cross-host cache-coherent.

The design works because Oasis avoids coherence where possible and pays for it only where necessary. For I/O buffers, the sender writes back before handoff, while the backend avoids touching packet or block buffers so the NIC or SSD DMA engine reads directly from CXL memory. For signaling, Oasis uses a custom message channel that invalidates consumed and stale prefetched lines so prefetching works again on non-coherent memory. The claim is that near-native remote device access is possible in software on commodity CXL 2.0 hardware if the software is explicitly designed around non-coherence.

## Design

Oasis is organized around reusable engines. Each device class gets a frontend driver on every host and a backend driver only on hosts that own the devices. Frontends expose local interfaces to containers or VMs; backends speak to native drivers such as DPDK's MLX5 or, in the storage design, SPDK's NVMe driver. A pod-wide allocator tracks device load, assigns resources, and handles rebalancing and failover. It stays off the data path, stores state in shared CXL memory, receives telemetry every 100 ms, and uses renewable leases; the paper says it can be replicated with Raft.

The common datapath places both I/O buffers and request/completion channels in shared CXL memory. The message channel is a single-producer single-consumer circular buffer with 8192 slots, an epoch bit per message, and an 8-byte consumed counter. The microbenchmarks justify these details: bypassing caches reaches only 3.0 MOp/s, naive prefetching reaches 8.6 MOp/s, and invalidating consumed plus stale prefetched lines raises throughput to 87.0 MOp/s while keeping 0.6 us latency at the 14.0 MOp/s target needed for end-to-end I/O.

The implemented network engine uses this substrate in a direct TX/RX split. On TX, an instance writes to its shared CXL TX area, the frontend flushes the buffer, and a 16-byte message hands the buffer pointer and metadata to the backend, which posts a NIC work queue entry without reading the payload. On RX, the backend posts descriptors into a per-NIC RX area in CXL memory, the NIC DMA-writes packets there, and flow tagging lets the backend identify the destination instance without parsing payloads. The frontend then copies the packet into local memory for isolation. The storage engine mirrors this structure with 64-byte NVMe-like messages, but it is only designed, not implemented.

## Evaluation

The evaluation uses two AMD hosts connected to one CXL 2.0 memory device via x8 links, with 100 Gbit Mellanox ConnectX-5 NICs. Across four web applications plus memcached, Oasis adds a fairly uniform 4-7 us latency penalty at P50, P90, and P99 versus the same stack using a local NIC. A UDP echo test shows the overhead is largely packet-size independent. The breakdown matters: placing packet buffers in CXL memory is almost free; most of the extra latency comes from cross-host message passing between the frontend and backend.

The utilization result is the paper's main payoff. Replaying production packet traces from two Azure hosts, the authors compare dedicated NICs with a multiplexed setup where both hosts share one NIC through Oasis. Host 1's P99 is unchanged and host 2 sees about 1 us extra latency, while aggregated NIC utilization at P99.99 rises from 18% to 37%, which is the prototype-level evidence behind the paper's 2x utilization claim.

Failover is also practical. Because each instance is pre-registered with a reserved backup NIC, Oasis can reroute TX immediately after failure and have the backup NIC borrow the failed NIC's MAC address so the switch steers RX traffic to the new port. The interruption is about 38 ms for UDP and about 133 ms P99 recovery for memcached over TCP, with the longer TCP tail coming from retransmission backlog rather than slower control-plane action.

## Novelty & Impact

The paper's main contribution is a full software substrate for PCIe pooling over non-coherent CXL 2.0, not just the observation that CXL is fast. It should matter to CXL systems work, cloud resource management, and I/O virtualization because it shows how a CXL pod justified for memory pooling can also amortize NIC and SSD costs, and because its message-channel design is reusable beyond this one prototype.

## Limitations

The paper is strongest as a feasibility argument, and its limits follow from that. Only the network engine is implemented; the datapath is single-threaded per frontend and backend driver; the system assumes DDIO is disabled and trusts the frontend, backend, and NIC; and RX still needs a copy for isolation. The evaluation covers only two hosts, one CXL device, and 100 Gbit NICs. Load balancing happens only at startup or failure, failover requires a reserved backup NIC, and CXL link failures or VIP-to-DIP cloud deployments need extra infrastructure not built here.

## Related Work

- _Zhong et al. (HotOS '25)_ — The earlier "My CXL Pool Obviates Your PCIe Switch" position paper motivates the idea, while Oasis supplies the full design, prototype, and evaluation.
- _Li et al. (ASPLOS '23)_ — Pond justifies CXL memory pools for cloud memory utilization; Oasis reuses the same CXL pod investment to pool PCIe devices instead of only DRAM capacity.
- _Ma et al. (ATC '24)_ — HydraRPC also uses shared CXL memory for host-to-host communication, but Oasis turns that substrate into a non-coherent datapath for remote device access and failover.
- _Hayakawa et al. (NSDI '21)_ — Prism migrates TCP flows with programmable network support, whereas Oasis moves traffic across pooled NICs inside a pod without requiring special network hardware for the migration itself.

## My Notes

<!-- empty; left for the human reader -->

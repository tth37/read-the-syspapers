---
title: "Enabling Efficient GPU Communication over Multiple NICs with FuseLink"
oneline: "FuseLink turns idle NICs into usable bandwidth by routing GPU traffic over NVLink to relay GPUs and scheduling sends across direct and indirect NICs at runtime."
authors:
  - "Zhenghang Ren"
  - "Yuxuan Li"
  - "Zilong Wang"
  - "Xinyang Huang"
  - "Wenxue Li"
  - "Kaiqiang Xu"
  - "Xudong Liao"
  - "Yijun Sun"
  - "Bowen Liu"
  - "Han Tian"
  - "Junxue Zhang"
  - "Mingfei Wang"
  - "Zhizhen Zhong"
  - "Guyue Liu"
  - "Ying Zhang"
  - "Kai Chen"
affiliations:
  - "iSINGLab, Hong Kong University of Science and Technology"
  - "University of Science and Technology of China"
  - "MetaX Integrated Circuits"
  - "Massachusetts Institute of Technology"
  - "Peking University"
  - "Meta"
conference: osdi-2025
tags:
  - gpu
  - networking
  - rdma
  - ml-systems
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

FuseLink lets a GPU use multiple NICs by relaying traffic over NVLink to peer GPUs that own idle direct NICs. It remaps NCCL buffers onto relay GPUs and schedules borrowed NICs by worker priority, so extra bandwidth does not preempt the GPU that normally uses that NIC. On 8-GPU servers with 8x400 Gbps NICs, it reaches 212 GB/s between two inter-server GPUs.

## Problem

GPU servers may have one good NIC per GPU and several worse indirect paths through PCIe or NUMA. NCCL and similar stacks therefore keep a mostly static GPU-NIC binding. That wastes bandwidth when traffic is skewed: disaggregated LLM serving has variable request sizes and arrivals, expert-parallel MoE has uneven token routing, and DLRM has uneven embedding traffic. The paper measures only 13%-53% average NIC utilization in disaggregated serving and 29%-65% in MoE.

Simply striping traffic over all NICs is unsafe. The sender GPU cannot efficiently drive all NICs through PCIe alone, and borrowing a peer GPU's NIC can steal its bandwidth or memory. FuseLink's problem is therefore to turn idle NICs into usable bandwidth without changing ML applications and without hurting the direct-NIC owner.

## Key Insight

The paper's core claim is that the intra-server GPU fabric should be treated as part of the inter-server path. If a busy GPU can first move data over NVLink to a peer GPU with an idle direct NIC, the node can aggregate bandwidth across NICs that are otherwise stranded behind bad PCIe paths.

What makes that practical is not a new transport protocol but a pairing of path redirection and isolation. Virtual-memory remapping lets existing NCCL buffers physically reside on relay GPUs, and priority-aware scheduling ensures the owner of a direct NIC can reclaim it quickly.

## Design

FuseLink is an NCCL networking layer. It intercepts proxy-thread connect, register, send, and receive calls, inspects topology at startup, and chooses a direct path or a router GPU for each GPU-NIC pair.

Its key data-path mechanism is relay-by-remapping. Instead of copying data through the CPU or host memory, FuseLink remaps a network buffer's virtual address onto memory on a relay GPU. When the application fills the buffer, the writes travel over NVLink directly into relay memory, removing an extra copy and a synchronization point before RDMA. On the receiver, FuseLink can likewise stage data on the GPU with the best NIC path and remap the final destination if the consumer lives elsewhere.

The control path is credit driven. Receivers encode idle NICs in credits; senders combine remote idleness with local NIC status to pick a direct NIC, an idle indirect NIC, or a fallback direct NIC. Each GPU keeps highest priority on its own direct NIC, indirect NICs accept only bounded outstanding requests, relay memory is capped, and relay traffic backs off during higher-priority intra-server GPU communication.

## Evaluation

The testbed uses eight Hopper GPUs, NVSwitch plus eight-lane NVLink, and eight ConnectX-7 400 Gbps NICs. The baseline is NCCL with PXN enabled. FuseLink raises point-to-point inter-server bandwidth from 49.27 GB/s to 212.35 GB/s when up to six NICs are usable. The ablation is informative: efficient relaying alone gets 78.39 GB/s, contention mitigation lifts that to 178.59 GB/s, and the full scheduler reaches 212.35 GB/s.

Control overhead is modest for the target regime. Querying NIC load costs 0.9-1.6 us per batch of operations, and remapping during route changes costs roughly 95-193 us, which the paper argues is amortized over 512 KB pipelined chunks.

End-to-end results line up with the thesis. For disaggregated OPT-30B serving, FuseLink improves TTFT by 1.04x-2.73x; with eight colocated instances, median TTFT falls from 684.54 ms to 308.48 ms. It improves expert-parallel Mixtral 8x22B training throughput by about 1.3x and speeds DLRM training by up to 1.2x. The evidence is strongest for skewed point-to-point workloads, exactly the case the paper targets.

## Novelty & Impact

Relative to NCCL's PXN mechanism, FuseLink is not just a better fixed path selector. PXN improves one path through an intermediate GPU, while FuseLink dynamically pools server NICs and borrows idle ones on both send and receive sides. Relative to multi-path transports such as _Lu et al. (NSDI '18)_, it multiplexes across NIC attachment points inside a GPU server rather than across network fabric paths. Relative to schedulers such as _Rajasekaran et al. (NSDI '24)_, it acts inside the communication runtime at chunk time.

That makes FuseLink a reusable systems mechanism rather than a workload-specific trick. The paper shows that clusters with fast intra-server GPU fabrics and multiple NICs per node can convert that topology into bandwidth for LLM serving, MoE training, and recommendation workloads without application changes.

## Limitations

FuseLink works best for large, imbalanced point-to-point traffic. The paper explicitly says balanced collectives such as ring all-reduce are not a natural fit unless worker placement is also changed to create skew within a node.

The scheduler is approximate by design. Idleness is inferred from recent completions rather than exact instantaneous state, route changes can permit one bounded suboptimal send, and relay-memory management is only best effort. The design also assumes standard GPU peer addressing and RDMA access to remapped buffers.

## Related Work

- _Hwang et al. (NSDI '23)_ — ARK improves GPU-driven communication execution, while FuseLink focuses on dynamically selecting and relaying across multiple NICs.
- _Lu et al. (NSDI '18)_ — MP-RDMA exploits multiple paths in the datacenter fabric, whereas FuseLink aggregates multiple NIC endpoints within one GPU server.
- _Hidayetoglu et al. (ICS '24)_ — CommBench characterizes multi-GPU, multi-NIC topology behavior; FuseLink builds the runtime mechanism that exploits such topology asymmetry.
- _Patel et al. (ISCA '24)_ — Splitwise exposes the disaggregated serving pattern whose skewed inter-stage traffic FuseLink accelerates, but it does not solve the underlying multi-NIC GPU communication problem.

## My Notes

<!-- empty; left for the human reader -->

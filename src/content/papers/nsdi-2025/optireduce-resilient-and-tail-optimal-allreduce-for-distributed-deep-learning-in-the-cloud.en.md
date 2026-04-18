---
title: "OptiReduce: Resilient and Tail-Optimal AllReduce for Distributed Deep Learning in the Cloud"
oneline: "OptiReduce makes cloud AllReduce tail-bounded with colocated-PS shard exchange, adaptive best-effort transport, and Hadamard coding so DDP keeps training through stragglers."
authors:
  - "Ertza Warraich"
  - "Omer Shabtai"
  - "Khalid Manaa"
  - "Shay Vargaftik"
  - "Yonatan Piasetzky"
  - "Matty Kadosh"
  - "Lalith Suresh"
  - "Muhammad Shahbaz"
affiliations:
  - "Purdue University"
  - "Nvidia"
  - "VMware Research"
  - "Feldera"
  - "University of Michigan"
conference: nsdi-2025
category: llm-and-ml-training-serving
code_url: "https://github.com/OptiReduce"
project_url: "https://optireduce.github.io"
tags:
  - ml-systems
  - networking
  - gpu
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

OptiReduce treats cloud AllReduce as a tail-tolerance problem instead of a reliable-delivery problem. It combines a colocated-parameter-server-style Transpose AllReduce, an adaptive best-effort transport that cuts off slow paths, and Hadamard coding that turns missing shards into small distributed noise. In the paper's GPT-2 runs, that is enough to reach the same 98% convergence accuracy faster than Gloo, NCCL, and reliable TAR on both emulated high-tail clusters and CloudLab.

## Problem

The paper starts from a simple observation: in synchronous DDP, the GPUs are not usually the unpredictable part. Forward and backward passes run on accelerators with bounded and fairly repeatable latency; gradient aggregation is the phase that inherits congestion, retransmissions, incast, slow workers, noisy virtualization, and cross-rack delay. Because workers cannot start the next batch until aggregation completes, long-tail communication directly becomes training stall time.

The cloud setting makes the mismatch worse. The authors measure gradient-aggregation tails on CloudLab, Hyperstack, AWS EC2, and Runpod, and report `P99/P50` ratios up to 3.2x. They also note prior reports of gradient aggregation taking as much as half of end-to-end DDP time. Existing collectives do not handle this regime well. Parameter servers can create heavy incast at the receiver. Ring AllReduce is bandwidth-efficient, but one slow hop delays the entire reduction, and missing data can contaminate later ring stages because each step depends on the previous partial aggregate.

The authors argue that making the transport ever more reliable is the wrong target. SGD-based training already tolerates approximation, quantization, and some missing information. So the right objective in a shared cloud is not "deliver every gradient entry eventually," but "finish aggregation within a predictable time budget while keeping the induced gradient error small enough that convergence and final accuracy do not move."

## Key Insight

OptiReduce's core claim is that a tail-optimal collective for cloud DDP should spend a little exactness to buy bounded completion time. Once the system accepts small, approximately unbiased gradient error, it no longer needs to wait for every retransmission or the slowest sender. It can stop on time, use the gradients that did arrive, and engineer the communication path so the missing information does the least possible damage.

That produces three coupled moves. First, use a topology where a missing shard harms one node-pair interaction instead of propagating through a ring. Second, use best-effort transport with explicit time bounds, so the collective can cut off stragglers rather than inherit their full latency. Third, encode the bucket before sharding, so tail drops become small perturbations spread across many coordinates instead of wiping out one contiguous slice of the model update.

## Design

The collective itself is Transpose AllReduce (TAR), a colocated-PS-inspired design. Each node is both a worker and a parameter server. A bucket is split into `N` shards; node `i` keeps the shard it is currently responsible for, sends the others directly to peers, aggregates the shards it receives into one reduced shard, then broadcasts that reduced shard back so all workers can reconstruct the bucket. TAR still uses the same overall bandwidth as Ring, but it changes the failure surface: a dropped shard affects one pairwise interaction in one phase instead of being re-amplified by later ring stages. The appendix adds a hierarchical 2D TAR that reduces rounds from `2(N-1)` to `2(N/G-1) + (G-1)` when nodes are grouped.

Transport is Unreliable Bounded Transport (UBT), a userspace protocol over UDP. UBT adds a 9-byte header carrying bucket id, byte offset, timeout, incast, and a `Last%ile` marker so receivers can place out-of-order packets into the correct bucket while multiple gradient aggregations overlap. Its main control variable is a timeout `tB` that bounds the send/receive stages. The paper computes `tB` during initialization by running TAR over TCP on the largest bucket for 20 iterations and taking the 95th-percentile completion time. To avoid waiting for the full bound every round, UBT also maintains a moving-average completion estimate `tC`; when the receive buffer is empty and the marked tail packets from every sender have arrived, the receiver waits only a dynamically chosen fraction of `tC` before expiring the stage.

UBT also manages contention directly. Its dynamic-incast mechanism lets each receiver increase or decrease the number of simultaneous senders according to observed loss and timeout behavior, rather than pinning the collective to a conservative fixed incast level. A lightweight TIMELY-like controller is used only to avoid congestion collapse; the design goal is still bounded useful delivery, not reliable in-order completion.

To make those drops survivable, OptiReduce applies a randomized Hadamard Transform before sharding and decodes after reconstruction. This is not for compression; it is for error dispersion. If tail drops remove part of a bucket, the transform spreads the loss across the decoded vector instead of zeroing one slice. The paper illustrates this with a toy example whose MSE drops from 2.53 without HT to 0.01 with HT. Finally, OptiReduce monitors loss during each round and can skip an update or halt training if the loss becomes too large.

## Evaluation

The prototype extends Gloo 0.5.0, integrates with PyTorch Distributed 1.12, and is evaluated on an eight-worker local virtualized cluster with controlled `P99/P50 = 1.5` and `3.0`, plus an eight-node CloudLab deployment with A30 GPUs on 10 Gbps networking. Baselines are Gloo Ring, Gloo BCube, NCCL Ring, NCCL Tree, and a reliable `TAR+TCP`.

The headline GPT-2 numbers support the central claim well. At `P99/P50 = 1.5`, OptiReduce reaches the same 98% convergence accuracy in 96 minutes, versus 105 for NCCL Tree, 118 for NCCL Ring, 154 for Gloo Ring, and 148 for reliable `TAR+TCP`. At `P99/P50 = 3.0`, OptiReduce still finishes in 97 minutes, while NCCL Tree rises to 135 minutes and Gloo Ring to 186 minutes. On CloudLab, it converges in 60 minutes, versus 71 for NCCL Ring, 79 for NCCL Tree, and 88 for Gloo Ring. The corresponding dropped-gradient rates are only 0.07%, 0.18%, and 0.05% of entries.

The microbenchmarks explain why. Under best-effort transport, TAR produces much lower gradient error than the alternatives: MSE is 2.47 for TAR, versus 9.92 for PS-style P2P and 14.55 for Ring on a 500M-tensor workload. Dynamic incast lowers average latency by about 21%. Early timeout reduces VGG-19 convergence time from 130 to 112 minutes at the same 0.02% drop rate. Hadamard coding adds overhead when drops are only 1%, but once drops reach 5-10%, it keeps time-to-accuracy nearly flat while the non-Hadamard version degrades sharply. The evaluation also shows where the design is not magic: in low-tail settings with in-network aggregation, SwitchML can still be faster.

## Novelty & Impact

The novelty is not a faster ideal-cluster collective; it is a different optimization target. OptiReduce asks what AllReduce should optimize when the deployment is shared, tail-heavy, and tenant-controlled. Its answer is to make bounded completion time the first-class goal and spend a small amount of gradient exactness to get there. That is different from static compression schemes, which decide how much information to remove before the network has shown its current behavior, and from in-network aggregation work, which assumes access to switches or provider infrastructure that cloud tenants rarely control.

This makes the paper relevant to training and fine-tuning stacks built on rented infrastructure, where the real metric is time-to-accuracy rather than clean-lab collective latency. It is also likely to matter to future cloud training runtimes because it shows that tail resilience can be engineered inside the collective itself rather than delegated entirely to schedulers, backup workers, or specialized fabrics.

## Limitations

The paper is clear that OptiReduce only bounds the communication-heavy stages. The actual reduction still runs on CPUs, so as buckets grow, the bottleneck can shift from networking to local aggregation. Likewise, the transport is still a software path inside Gloo over UDP/TCP; RDMA-style unreliable offload and SmartNIC support are explicitly future work, not part of the evaluated system.

The benefits are strongest in the regime the paper targets. In a low-tail setting with in-network aggregation, SwitchML can be 52% faster. OptiReduce wins when tail variability rises because it bypasses stragglers instead of waiting for them. A second concern is scale realism: the strongest end-to-end evidence uses eight workers, while the larger-node results are synthetic or simulated. That is enough to make the scaling story plausible, but not enough to fully close the gap to very large production deployments.

## Related Work

- _Lao et al. (NSDI '21)_ - `ATP` also exploits approximate aggregation for multi-tenant learning, but it relies on in-network support instead of an end-host collective.
- _Sapio et al. (NSDI '21)_ - `SwitchML` accelerates DDL with programmable-switch aggregation, while `OptiReduce` targets tenants who cannot change the provider network.
- _Fei et al. (SIGCOMM '21)_ - `OmniReduce` reduces bytes for sparse gradients, whereas `OptiReduce` keeps full buckets and optimizes bounded completion under tails.
- _Wang et al. (NSDI '24)_ - `MLT` also treats some gradient drops as tolerable, but it implements that policy inside the network rather than in the collective topology, transport, and coding at the hosts.

## My Notes

<!-- empty; left for the human reader -->

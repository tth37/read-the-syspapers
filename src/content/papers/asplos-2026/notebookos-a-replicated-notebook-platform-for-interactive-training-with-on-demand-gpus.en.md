---
title: "NotebookOS: A Replicated Notebook Platform for Interactive Training with On-Demand GPUs"
oneline: "Replicates notebook kernels across GPU servers, oversubscribes idle capacity, and binds GPUs only during cell execution to keep training interactive at lower cost."
authors:
  - "Benjamin Carver"
  - "Jingyuan Zhang"
  - "Haoliang Wang"
  - "Kanak Mahadik"
  - "Yue Cheng"
affiliations:
  - "George Mason University, Fairfax, Virginia, USA"
  - "Adobe Research, San Jose, California, USA"
  - "Adobe Inc, San Jose, California, USA"
  - "University of Virginia, Charlottesville, Virginia, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3760250.3762230"
code_url: "https://github.com/ds2-lab/NotebookOS"
tags:
  - gpu
  - scheduling
  - ml-systems
  - datacenter
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

NotebookOS treats the notebook session as long-lived state but treats GPU ownership as short-lived and elastic. It replicates each Jupyter kernel across three GPU servers, synchronizes small state with Raft, persists large objects asynchronously, and binds GPUs only when a cell actually runs. On the Adobe production trace excerpt, that design saves 1,187.66 GPU-hours in 17.5 hours while keeping interactivity close to a fully reserved notebook deployment.

## Problem

The paper starts from a mismatch between notebook usage and notebook resource allocation. In Jupyter-style interactive deep learning training (`IDLT`), users keep a session alive for a long time, but GPU work arrives only in short bursts while they debug code, inspect outputs, or tune hyperparameters. Current notebook services reserve GPUs for the full session lifetime just to preserve responsiveness, which is very wasteful on the Adobe trace: reserved GPUs are idle more than 81% of the time, nearly 70% are unused for an entire session lifetime, and roughly three quarters of sessions actively use their GPUs for at most 5% of session time.

This workload also differs from ordinary batch deep learning. In AdobeTrace, 50% of training tasks last at most 2 minutes and 75% finish within 5 minutes, while the median per-session inter-arrival time is 5 minutes. So the system is serving long-lived, stateful notebook sessions that occasionally issue very short training cells, not a dense stream of continuously running jobs. A batch scheduler would recover GPUs more efficiently, but it would also add startup, queueing, and state-restoration delays exactly when the user expects immediate feedback.

## Key Insight

The central claim is that notebook state and GPU reservation do not need to be coupled. NotebookOS keeps a kernel logically alive by replicating it across GPU servers and oversubscribing those servers under the assumption that `IDLT` arrivals are sparse. When a user submits a cell, only one replica needs to acquire GPUs quickly; the others preserve state, improve fault tolerance, and raise the odds that some host already has spare capacity. Small CPU-resident state is synchronized continuously, while large objects such as models and datasets are persisted asynchronously outside the critical path. The long inter-arrival times in the target workload make that split workable.

## Design

NotebookOS inserts a resource-management layer underneath normal Jupyter clients. Its main components are the Jupyter Server, a Global Scheduler, a Local Scheduler on each GPU server, a three-replica Distributed Kernel per notebook, and a Distributed Data Store. When a notebook kernel is created, the Global Scheduler selects three candidate servers and launches one replica on each. Importantly, those replicas subscribe to resources rather than owning them exclusively, which lets the cluster oversubscribe idle capacity.

When a user sends an `execute_request`, NotebookOS picks an executor replica. If the schedulers already know which host has enough GPUs, they can short-circuit the process; otherwise the replicas use Raft-backed `LEAD` and `YIELD` proposals, and the first committed `LEAD` wins. Only that executor runs the cell while the other replicas remain standby. If all replicas yield because no host can satisfy the request, the system migrates one replica to a better server and retries, using pre-warmed containers when possible.

The main mechanism is state handling. After a cell executes, NotebookOS converts the code to a Python AST, identifies state that should be preserved, and replicates small state through Raft state-machine replication. For large objects, it stores only a pointer in the Raft log while writing the real data to a pluggable distributed store such as Redis, S3, or HDFS. That keeps multi-GB models off the consensus path. The paper is explicit that this currently covers Python-level state and native state referenced in the kernel namespace, but not external process state or libc state.

GPU management is deliberately simple: NotebookOS binds GPUs only right before execution, loads parameters from host memory to the allocated devices, runs the cell, and copies relevant GPU state back before replying. Placement and autoscaling are then driven by a subscription-ratio model: the cluster expands when rising active demand makes it unlikely that at least one replica per notebook can find room immediately.

## Evaluation

The evaluation uses both a full prototype and a simulator. The prototype runs on 30 AWS EC2 GPU VMs, each with 8 GPUs, and replays a 17.5-hour excerpt from AdobeTrace using models and datasets from computer vision, NLP, and speech workloads. The baselines are a reservation system that mimics today's notebook platforms, a batch scheduler that provisions a fresh kernel container per request, and `NotebookOS (LCP)`, a variant with a larger warm-container pool that trades more interactivity for lower cost.

The headline result is resource efficiency without a major responsiveness collapse. Relative to Reservation, NotebookOS saves 1,187.66 GPU-hours over 17.5 hours of replay; `NotebookOS (LCP)` saves 1,662.53 GPU-hours but sacrifices more latency. NotebookOS can commit GPUs to a replica immediately for 89.6% of requests and reuse the same executor on consecutive requests 89.45% of the time, which explains why its interactivity stays close to Reservation. Its task completion time is somewhat worse between the 38th and 90th percentiles because oversubscription occasionally forces migration or cold container creation, but it remains much closer to Reservation than to the batch baseline.

The state-replication overheads are small enough for the target workload. For small objects synchronized through Raft, the 90th, 95th, and 99th percentile latencies are 54.79 ms, 66.69 ms, and 268.25 ms. For large objects, 99% of reads and writes to the distributed store complete within about 3.95 seconds and 7.07 seconds. The paper argues that AdobeTrace's workload gaps hide this cost because the shortest observed event inter-arrival time is 240 seconds.

The simulation study extends the story to the full summer trace. Under the paper's billing model, NotebookOS reduces provider-side cost by up to 69.87% relative to Reservation while also improving profit margin, because it reclaims idle GPU time yet still charges lightly for standby replicas.

## Novelty & Impact

Relative to classic GPU cluster schedulers such as _Xiao et al. (OSDI '18)_ and _Gu et al. (NSDI '19)_, NotebookOS is novel because it treats the notebook session, not the training job, as the primary unit of design. Relative to existing notebook platforms, its key move is not a timeout tweak or a batch-queue bridge, but a clean split between persistent notebook state and on-demand GPU attachment. The Raft-replicated kernel abstraction is the main idea; dynamic binding, oversubscription, migration, and autoscaling all serve that abstraction.

The paper should matter to managed notebook platform builders and to researchers interested in stateful interactive ML infrastructure. Its contribution is less a new scheduling objective than a new systems decomposition.

## Limitations

NotebookOS does not currently support GPU sharing, fractional GPU allocation, or multi-server training, and its AST-based synchronization does not capture external process state or libc state. The design also depends on workload shape: long inter-arrival times help hide asynchronous model and dataset movement, so denser edit-run loops could expose those costs more directly. Finally, the system deliberately keeps extra replicas and warm containers in memory, so it is not trying to beat a pure batch system on absolute standing cost in every regime.

## Related Work

- _Xiao et al. (OSDI '18)_ — Gandiva improves batch deep learning cluster efficiency through introspective scheduling and time-slicing, whereas NotebookOS is built around long-lived notebook sessions and per-cell responsiveness.
- _Gu et al. (NSDI '19)_ — Tiresias optimizes job completion under partial information for distributed deep learning jobs, but it does not preserve interactive notebook state or treat sessions as first-class objects.
- _Mahajan et al. (NSDI '20)_ — Themis focuses on fairness and efficiency for multi-tenant GPU clusters; NotebookOS instead spends extra replication effort to preserve interactivity for notebook users.
- _Wu et al. (NSDI '23)_ — Transparent GPU sharing in container clouds provides the kind of fine-grained GPU sharing that NotebookOS explicitly leaves to future integration.

## My Notes

<!-- empty; left for the human reader -->

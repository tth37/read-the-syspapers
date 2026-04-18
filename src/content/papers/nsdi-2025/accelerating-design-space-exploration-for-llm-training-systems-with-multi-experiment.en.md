---
title: "Accelerating Design Space Exploration for LLM Training Systems with Multi-experiment Parallel Simulation"
oneline: "Multiverse batches many LLM-training simulations into one GPU-resident ECS pipeline, cutting exploration time by up to 73.2x while staying within 3% of real training."
authors:
  - "Fei Gui"
  - "Kaihui Gao"
  - "Li Chen"
  - "Dan Li"
  - "Vincent Liu"
  - "Ran Zhang"
  - "Hongbing Yang"
  - "Dian Xiong"
affiliations:
  - "Tsinghua University"
  - "Zhongguancun Laboratory"
  - "University of Pennsylvania"
  - "BNRist"
  - "Tsinghua Shenzhen International Graduate School"
conference: nsdi-2025
category: llm-and-ml-training-serving
code_url: "https://github.com/NASP-THU/multiverse"
tags:
  - llm-training
  - gpu
  - networking
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Multiverse starts from the observation that LLM-training design-space exploration usually needs hundreds to tens of thousands of independent simulation runs, and that treating those runs as unrelated CPU jobs wastes structure. It instead runs many experiments inside one single-process, multi-experiment simulator laid out with ECS/DOD abstractions and executed on a GPU. That combination lets it preserve packet-level network fidelity where needed, replace slow intra-server modeling with calibrated analytical models, and deliver 43.1-73.2x speedups over prior CPU-based simulators while keeping end-to-end iteration time within 3% of real 128- and 1,024-GPU H100 training clusters.

## Problem

The paper addresses a bottleneck that appears before any LLM training system is deployed: choosing a good point in an enormous design space. Modern training stacks must decide on tensor/pipeline/data parallel group sizes, collective-communication algorithms, congestion-control parameters, and even the network topology itself. The authors give concrete scales for this search: optimizing a parallel-group configuration can require about 100 experiments, while topology search can exceed 10,000. Missing the best point is expensive; the paper cites prior work showing that a bad topology can lengthen iteration time by 3.4x.

The obvious answer is to parallelize those experiments by launching many simulator instances on CPU cores. The paper argues this is the wrong granularity. Separate processes duplicate simulator state, compete for cache and memory, and pay synchronization or scheduling overhead when multi-process techniques are used. Even strong CPU baselines such as ASTRA-sim accelerated by UNISON or DONS therefore scale sublinearly when the real task is "run many independent experiments." The paper's motivating claim is that exploration speed is now a systems problem in its own right, not just a property of any single simulator run.

## Key Insight

The central insight is that multi-experiment exploration should be treated as a SIMD-style workload. Different experiments execute the same simulation logic over different state, so the best execution model is not "many simulators" but "one simulator applying the same systems over many experiment states at once." The paper calls this single-process multi-experiment execution, or SPME.

That idea only becomes powerful when paired with a data-oriented representation. Multiverse models AI-training systems with ECS abstractions so that the same logic, such as task scheduling, packet forwarding, or ACK handling, can operate over homogeneous columns of component data across all experiments. Once the simulator is written that way, a GPU becomes a natural backend: the work already looks like repeated execution of identical kernels over wide arrays of state. In other words, the contribution is not merely porting a CPU simulator to CUDA, but restructuring the simulator so cross-experiment coherence becomes exploitable parallelism.

## Design

Multiverse consists of four main pieces. The system simulator consumes a workload graph similar to ASTRA-sim inputs, where each per-GPU node is either computation or collective communication. It supports training-parallelism choices such as TP and DP, and for inter-server collective operations it expands collectives into point-to-point flows whose timing is later simulated in the network. A separate GPU-memory simulator checks whether a chosen configuration would exceed device memory and raises OOM during exploration if so.

The interesting architectural split is between intra-server and inter-server communication. For inter-server traffic, Multiverse keeps a packet-level discrete-event network simulator so congestion control and topology effects remain explicit. For intra-server communication, the authors conclude that packet-level simulation is both unnecessary and inaccurate because NVIDIA's local communication stack is closed and heavily shaped by NCCL runtime overheads. Multiverse therefore profiles NCCL behavior and uses a calibrated linear model `y = alpha + comm_size / beta`, with parameters specialized by collective type, GPU type, and server configuration. It also adjusts computation time when communication overlaps with compute, again via empirical models.

The simulator's internal state is represented with ECS entities such as `Task`, `Flow`, `Sender`, `IngressPort`, `EgressPort`, and `Receiver`. Components are stored as columnar tables shared across all experiments, with an implicit experiment identifier per row. Systems then query matching archetypes and operate on those columns. The paper's key point is that this shared storage improves coherence: neighboring GPU threads can read adjacent component values even when they belong to different experiments, instead of bouncing across per-experiment heaps or processes.

Each simulation step executes a fixed system graph: scheduling task dependencies, analytically simulating intra-server collectives, injecting point-to-point flows, pushing packets through NIC and switch entities, and finally generating ACKs. To make this GPU-friendly, the runtime compiles system functions plus their wrapper logic into one megakernel rather than launching a separate CUDA kernel for every ECS stage. That avoids repeated CPU-GPU launch overhead and lets the GPU traverse the whole task graph for a batch of simulation work before returning.

The paper adds three implementation techniques that matter more than they first appear. First, pull-based synchronization turns many-to-one writes into a lock-free two-phase protocol: producers record intent, and the destination port later pulls the pending data. Second, the calibrated intra-server model avoids wasting GPU cycles on fake packet simulation for NVLink or PCIe traffic. Third, the megakernel preserves enough work per stage that large multi-experiment batches can saturate the GPU instead of stalling on launch overhead.

## Evaluation

The evaluation compares Multiverse against ASTRA-sim paired with UNISON or DONS, plus a SPSE version of Multiverse, on a server with one H100 GPU, an 80-core CPU, and 256 GB memory. The explored scenarios are practical rather than synthetic: 10,000 topology-search experiments for a 128-GPU GPT-3 13B cluster, 500 collective-communication tuning experiments for a 1,024-GPU LLaMA 65B cluster, 100 TP/DP/PP-group searches for an 8,192-GPU GPT-3 175B cluster, and congestion-control comparisons for a simulated 54,000-GPU GPT-dense cluster.

The headline result is exploration throughput. Across the first three use cases, Multiverse is 57.4-73.2x faster than the other simulators and still 1.7-7.3x faster than a single-experiment version of itself. The paper's explanation is credible: SPME cuts duplicate memory and scheduling costs, ECS reduces cache misses, and the GPU backend exposes far more parallelism than CPU-only batching. The maximum-scale result is also notable: a single H100 can simulate one 54k-GPU training cluster and still beats prior methods by 28.6-43.1x.

Accuracy is the second pillar. For intra-server collectives on 8 A100 GPUs, ASTRA-sim's default analytical model can be off by 20%-72%, especially for small messages, while Multiverse's calibrated model stays around 0.7%-1.2% error. End to end, the simulated iteration time for LLaMA 65B and GPT-3 175B differs from real H100 clusters by less than 3% at both 128 and 1,024 GPUs. The paper therefore does support its main claim: its speedups are not purchased by turning the simulator into a low-fidelity estimator.

That said, the evaluation is strongest on throughput and iteration-time fidelity, weaker on breadth of deployment evidence. The hardware target is NVIDIA-centric, and most comparisons focus on one-node simulation hosts rather than distributed simulation backends. Still, for the stated goal of accelerating exploratory search, the numbers are convincing.

## Novelty & Impact

The novelty is the combination of three decisions that earlier work treated separately: run many experiments inside one simulator process, structure the simulator as ECS/DOD so logic can batch across experiments, and map that structure directly onto a GPU. ASTRA-sim models distributed training systems, DONS shows the value of DOD for network simulation, and UNISON improves CPU-side parallel network simulation, but Multiverse is the first system here to treat design-space exploration itself as the unit of optimization.

That matters to anyone building or tuning large AI clusters. Training-system researchers can use the paper as evidence that simulator throughput has become a first-order bottleneck. Network designers can use it to explore topology and congestion-control choices more aggressively. More broadly, the paper is a good example of a systems move that changes the question from "how do we speed up one run?" to "what structure exists across the whole search procedure?".

## Limitations

Multiverse's fidelity depends on several empirical calibrations rather than fully open models. The intra-server communication model is derived from measured NCCL behavior and specialized to GPU/operator combinations, so new hardware generations or runtime versions may require repeated profiling. Similarly, compute/communication overlap is captured with fitted models, not first-principles simulation.

The release scope is also narrower than the motivating design space. The implementation section says the current code base supports TP and DP plus a limited set of collectives and congestion-control algorithms; that leaves some ambiguity about how fully pipeline parallelism and broader training features are represented in the artifact. Finally, the evaluation validates iteration time against real 128- and 1,024-GPU H100 clusters, but the largest 54k-GPU study is necessarily simulation only. So the paper convincingly shows faster exploration, while real-world confidence at the extreme scale still rests on extrapolation.

## Related Work

- _Rashidi et al. (ISPASS '20)_ - ASTRA-sim models the software and hardware stack of distributed-training systems, while Multiverse targets the neglected question of how to run large numbers of those simulations quickly.
- _Won et al. (ISPASS '23)_ - ASTRA-sim 2.0 extends modeling to hierarchical networks and disaggregated systems, whereas Multiverse contributes a different execution architecture centered on exploration throughput.
- _Gao et al. (SIGCOMM '23)_ - DONS shows that DOD/ECS can make network simulation faster on CPUs; Multiverse adapts that style to AI-training entities and pushes it onto GPUs across many experiments.
- _Bai et al. (EuroSys '24)_ - UNISON improves ns-3 with efficient CPU multithreading, but Multiverse argues that single-process multi-experiment execution fits LLM-training exploration better than spinning up many CPU-side runs.

## My Notes

<!-- empty; left for the human reader -->

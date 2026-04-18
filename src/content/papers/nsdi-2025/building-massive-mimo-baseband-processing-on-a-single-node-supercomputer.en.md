---
title: "Building Massive MIMO Baseband Processing on a Single-Node Supercomputer"
oneline: "MegaStation treats a single-node GPU pool as a scoreboarded processor, reshaping massive-MIMO baseband work at runtime to cut tail latency by up to 66.2%."
authors:
  - "Xincheng Xie"
  - "Wentao Hou"
  - "Zerui Guo"
  - "Ming Liu"
affiliations:
  - "University of Wisconsin-Madison"
conference: nsdi-2025
code_url: "https://github.com/netlab-wisconsin/MegaStation"
tags:
  - gpu
  - scheduling
  - hardware
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

MegaStation rejects a fixed frame-, symbol-, or task-level schedule for massive-MIMO baseband on a single-node GPU pool. It treats stages as instructions, uses a scoreboard to track GPU availability, and changes granularity on the fly, cutting tail latency by up to 66.2% while keeping 1 ms frames under the paper's 4 ms bound.

## Problem

Massive MIMO baseband is both compute-heavy and deadline-driven. Every frame must run FFT/IFFT, zero forcing, equalization or precoding, modulation or demodulation, and LDPC en(de)coding in only a few milliseconds. Those stages do not share one natural parallel dimension: FFT tracks antennas, equalization and precoding track subcarriers, and coding tracks users. A fixed schedule therefore fits one stage and misfits another.

That misfit is worse on a single-node supercomputer, where one host sees a GPU pool through a routable PCIe fabric. Compute is abundant, but usable parallelism is irregular at runtime: work may encounter full, fragmented, partial, or delayed parallelism depending on how SMs are distributed and queued. The paper shows that frame-, symbol-, and task-level scheduling each lose in different regimes, causing extra shuffles, queueing, deadline misses, or idle GPUs.

## Key Insight

The key idea is to treat baseband stages as instructions, not as a fixed pipeline schedule. Once stages have explicit dependencies, the runtime can choose placement and order from predicted GPU state rather than from a static decomposition. Scoreboarding then answers the real questions: will enough SMs be free during a task's lifetime, are its inputs already local, is waiting cheaper than copying, and can low-priority work be overcommitted without hurting urgent frames.

## Design

MegaStation has four pieces. The instruction unit parses frames, emits opcodes such as `PilotFFT`, `ZF`, `EqDemodul`, `Decode`, `Precode`, and `Encode`, and builds a per-frame DAG from read-after-write dependencies. The executor layer models each GPU task as a logical resource tuple over CTAs, warps, registers, and shared memory, then uses a first-fit planner to place executors onto the fewest GPUs that can hold them.

The scoreboard keeps per-opcode execution/resource metadata, per-instruction issue/execute/commit timestamps, and per-GPU occupancy estimates. From those tables, MegaStation classifies a placement as full, fragmented, partial, or delayed parallelism and uses a profiled threshold `α` to decide when partial occupancy is still acceptable. Execution is then driven by the LROC scheduler: least-slack-time-first for urgent frames, reordering to fill SM holes, low-priority overcommit to avoid idle GPUs, and coalescing of dependent instructions on the same CUDA stream to cut launch gaps. The runtime therefore stays coarse when possible and drops to symbol- or instruction-level execution when fragmentation or contention makes that better.

## Evaluation

The evaluation is persuasive because it first explains why fixed granularity fails, then shows end-to-end wins on the real target. MegaStation runs on a GigaIO FabreX/SuperNODE SNC with NVIDIA A100 and V100 GPUs and is compared with three GPU baselines patterned after LuMaMi, Hydra, and BigStation.

Section 3 supports the scheduler design: symbol-level splitting helps at low fragment degrees but loses when copy cost dominates, and coarse jobs sometimes win under delay because GPU queues are FCFS. End to end, MegaStation keeps 1 ms uplink and downlink frames within the cited 4 ms processing bound across `64x32` through `256x128` MIMO settings, with P9999 latency between 1.2 and 3.6 ms. Across the five tested configurations, it lowers uplink tail latency by 58.9%, 46.9%, and 66.2% on average versus LuMaMi-GPU, Hydra-GPU, and BigStation-GPU, and improves throughput as well. It also scales to 8 RUs under `128x64` MIMO on 6 GPUs, reaching up to 4x the alternatives' throughput. That supports the paper's core claim that adaptive scheduling, not just more GPUs, unlocks the SNC.

## Novelty & Impact

This is a mechanism paper. `Agora` and `Hydra` already showed that software massive-MIMO processing is feasible, but they largely commit to static execution structure. MegaStation's novelty is to combine composable GPU infrastructure with processor-style scoreboarding, deadline-aware issue logic, and adaptive granularity for radio pipelines. That matters both to vRAN builders looking for a more upgradeable software path and to systems researchers studying deadline-aware GPU scheduling on composable hardware.

## Limitations

The paper's claim is strongest for large, busy MIMO deployments on this specific kind of platform. All end-to-end results are on one GigaIO SNC design, and the baselines are reimplemented by the authors because the original systems were not built for GPU pooling. That is reasonable for comparing execution strategies on an SNC, but it is not the same as evaluating each prior system in its native environment.

The appendix also shows that MegaStation is not universally best: on small `32x8` and `64x16` MIMOs, Hydra-GPU has lower average and tail latency because static symbol scheduling has less overhead. RU scaling is ultimately capped by host-to-chassis fabric bandwidth, obsolete frames are dropped on overload or failure, and the paper does not quantify energy efficiency or real carrier deployment cost.

## Related Work

- _Ding et al. (CoNEXT '20)_ - `Agora` proved that software massive-MIMO baseband can run in real time on CPUs, and MegaStation inherits its stage structure while replacing static CPU parallelism with adaptive GPU scheduling.
- _Gong et al. (NSDI '23)_ - `Hydra` distributes symbol pipelines across multiple servers, whereas MegaStation keeps the workload inside one composable node and changes granularity per instruction based on scoreboard state.
- _Malkowsky et al. (IEEE Access '17)_ - `LuMaMi` demonstrates a fixed FPGA-based massive-MIMO testbed, while MegaStation argues for a more programmable path on commodity GPUs.
- _Yang et al. (SIGCOMM '13)_ - `BigStation` pioneered distributed real-time signal processing for MU-MIMO, but MegaStation focuses on single-node GPU pooling and finer-grained resource accounting.

## My Notes

<!-- empty; left for the human reader -->

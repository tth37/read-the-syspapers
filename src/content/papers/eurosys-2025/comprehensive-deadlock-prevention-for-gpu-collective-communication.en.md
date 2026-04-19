---
title: "Comprehensive Deadlock Prevention for GPU Collective Communication"
oneline: "DFCCL turns collective deadlock prevention into a preemptive GPU daemon-kernel problem, replacing global ordering constraints with adaptive on-GPU scheduling."
authors:
  - "Lichen Pan"
  - "Juncheng Liu"
  - "Yongquan Fu"
  - "Jinhui Yuan"
  - "Rongkai Zhang"
  - "Pengze Li"
  - "Zhen Xiao"
affiliations:
  - "School of Computer Science, Peking University"
  - "OneFlow Research"
  - "National Key Laboratory of Parallel and Distributed Computing, College of Computer Science and Technology, National University of Defense Technology"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717466"
code_url: "https://github.com/Oneflow-Inc/dfccl"
tags:
  - gpu
  - ml-systems
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

DFCCL treats a collective primitive's wait loop as a preemption point. A daemon kernel on each GPU aborts stuck primitives, saves state, and reschedules work so circular dependencies no longer deadlock. In the paper's experiments it eliminates the synthetic NCCL deadlocks while usually staying near NCCL performance.

## Problem

Distributed DNN training stacks data, tensor, and pipeline parallelism on top of NCCL-like collectives, but those collectives hold GPU resources while busy-waiting and practical GPU preemption is absent. Once different GPUs issue collectives in different orders, circular waiting can freeze progress.

The paper identifies three library-level deadlock modes: single-queue, resource-depletion, and GPU-synchronization-related deadlock. The last one matters because explicit or implicit synchronization can block later collectives from using otherwise idle resources. In the simulator, disorder and synchronization probabilities of only 0.004% each already produce a 6.94% deadlock ratio.

Existing fixes stay at the application layer. Horovod, BytePS, KungFu, OneFlow, and manual Megatron-style orchestration all try to impose a global collective order with extra CPU logic. That becomes brittle as grouping grows irregular or synchronization is not fully controlled.

## Key Insight

Common GPU collectives are preemptible even without hardware support for collective preemption. All-reduce, all-gather, reduce-scatter, reduce, and broadcast are built from send, recv, reduce, and copy primitives that already poll explicit readiness conditions, so prolonged waiting can be reinterpreted as a safe yield point.

Connector writes remain visible after preemption. A GPU can write data for one primitive, switch away, and later continue without a new global agreement step. That is what makes decentralized per-GPU context switching possible.

## Design

DFCCL exposes asynchronous `dfcclRun*` APIs on top of per-GPU submission/completion queues and a persistent daemon kernel. The daemon fetches requests, keeps a task queue plus context buffer, schedules one collective, and executes its primitive sequence.

Execution is two-phase blocking. Each primitive spins up to a threshold for send/receive readiness; if it succeeds, execution continues, and if it fails, DFCCL saves only dynamic context such as chunk ID and aborted primitive ID, then switches away. Static metadata stays in place, so a later retry resumes instead of replaying the whole collective.

Scheduling uses stickiness, encoded by queue position and spin thresholds. The front collective gets the largest initial threshold, later collectives get smaller ones, and a successful primitive raises the thresholds of later primitives for that same collective. Across GPUs this approximates decentralized gang-scheduling: peers drift toward the same collective without an explicit coordinator. To break synchronization-related deadlocks, the daemon can also quit voluntarily when idle or blocked, let `cudaDeviceSynchronize()`-like operations finish, and restart on demand.

## Evaluation

Deadlock prevention is clear. On an 8x RTX 3090 server, eight GPUs invoking the same eight all-reduces in different random orders finish 200 iterations under DFCCL with no deadlock despite about 18,000 preemptions per block on average. When explicit GPU synchronizations are inserted between differently ordered all-reduces, DFCCL still finishes 200 iterations and the daemon kernel quits about 360 times per GPU. The corresponding NCCL tests deadlock 100% of the time.

Overheads are small. For 1,000 collectives DFCCL uses 13 KB of shared memory and 4 MB of global memory per block, plus 11 KB of global memory for shared counters and metadata. Queue optimization cuts CQE write time from about 6.9 us to 2.0 us; context load and save are about 0.45 us and 0.05 us.

Performance stays close to NCCL. On 8x RTX 3090, a 4 KB all-gather is slower end to end under DFCCL, 49.4 us versus 45.1 us, because I/O overhead dominates. At 4 MB, DFCCL becomes slightly faster, 851.8 us versus 855.2 us, with lower core execution time, 828.0 us versus 847.9 us. In training, DFCCL stays within about ±1.2% of OneFlow's statically sorted NCCL on ResNet50 while beating KungFu and Horovod by 20.4%-22.3%, reaches an 8.6% best-case gain on ViT, and remains within ±4% of manually orchestrated NCCL on GPT-2.

## Novelty & Impact

Prior systems either optimize collectives assuming applications already avoid circular dependencies, or preempt single GPU kernels for latency control. DFCCL combines state-preserving collective preemption, adaptive decentralized scheduling, and a persistent daemon kernel so that deadlock handling happens inside the communication library. If this generalizes, frameworks need much less DP/TP/PP-specific orchestration logic.

## Limitations

DFCCL pays extra queueing and I/O overhead on small messages, which is why the 4 KB all-gather is a few microseconds slower than NCCL. It also depends on profiled parameters such as the initial spin threshold and voluntary-quitting period; the paper's own case study shows that a naive fixed threshold can create long queues and many context switches.

The prototype is narrower than the claim. It targets NVIDIA GPUs, common collectives, and primitive sequences generated with the Simple protocol and Ring algorithm, and the largest training result is 32 GPUs across four servers. The paper argues correctness informally through context preservation and connector ownership rather than with fairness or starvation proofs.

## Related Work

- _Bao et al. (INFOCOM '20)_ - PACE preemptively schedules segmented all-reduce kernels from a DNN dependency graph, while DFCCL adds library-level preemption that survives arbitrary circular collective dependencies.
- _Han et al. (OSDI '22)_ - REEF gives microsecond-scale GPU preemption for DNN inference kernels, but it does not preserve and reschedule multi-GPU collective state.
- _Yuan et al. (arXiv '21)_ - OneFlow statically sorts collectives through compiler-generated task graphs, whereas DFCCL tries to remove the need for globally consistent invocation order.
- _Barham et al. (arXiv '22)_ - Pathways motivates the irregular multi-group training regimes where manual collective orchestration becomes brittle, which is exactly the setting DFCCL is designed for.

## My Notes

<!-- empty; left for the human reader -->

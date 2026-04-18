---
title: "PhoenixOS: Concurrent OS-level GPU Checkpoint and Restore with Validated Speculation"
oneline: "PhoenixOS speculates GPU kernel access sets from launch arguments, validates them at runtime, and uses that signal to checkpoint or restore GPU processes with much shorter stalls."
authors:
  - "Xingda Wei"
  - "Zhuobin Huang"
  - "Tianle Sun"
  - "Yingyi Hao"
  - "Rong Chen"
  - "Mingcong Han"
  - "Jinyu Gu"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "National University of Singapore"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764813"
code_url: "https://github.com/SJTU-IPADS/PhoenixOS"
tags:
  - gpu
  - fault-tolerance
  - kernel
  - serverless
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PhoenixOS brings concurrent OS-level checkpoint/restore to GPU processes by inferring which GPU buffers each kernel may read or write from its launch arguments, then validating that inference with lightweight binary instrumentation. That access information lets it reuse CPU-style copy-on-write, recopy, and on-demand restore protocols in software, cutting checkpoint and restore stalls for fault tolerance, live migration, and GPU serverless cold starts.

## Problem

OS-level checkpoint/restore is attractive because it is transparent: cloud operators can migrate black-box jobs, recover from failures, or relaunch warm GPU processes without asking frameworks to add bespoke recovery code. The problem is that existing GPU checkpoint systems are effectively stop-the-world. They quiesce CPU and GPU execution, copy CPU state plus tens of gigabytes of GPU buffers, and then rebuild GPU contexts before anything can run again.

That stall is already painful for inference and even worse for training. The paper reports that restoring a Llama2-13B inference process with prior OS-level GPU C/R can take 6.2 seconds, far above its time-to-first-token, and that checkpointing in training can consume 46-87% of an iteration. Traditional CPU solutions do not transfer cleanly because CPUs have page-table machinery such as dirty or present bits and OS-mediated data paths, while GPUs bypass the OS and expose neither cheap dirty tracking nor copy-on-write support. To make concurrent checkpointing correct, the OS must know which bytes concurrent execution reads and writes. Without that information, a running kernel can overwrite data that has not yet been checkpointed or read a buffer that has not yet been restored.

## Key Insight

The paper's central claim is that GPU execution is opaque at the instruction level but not at the control boundary where work is submitted. A GPU process reaches the device through fine-grained API calls, and the launch arguments to those calls usually encode the buffers a kernel will touch. That makes it possible to speculate about each kernel's read and write sets from API semantics and argument types, instead of requiring hardware dirty bits or full static analysis of arbitrary GPU code.

Speculation alone would be too risky, so PhoenixOS pairs it with runtime validation. For opaque kernels, it generates an instrumented twin kernel that checks every memory write against the speculated buffers and reports mis-speculation. Once the system has mostly-correct access sets, it can retrofit classic concurrent CPU protocols to GPUs in software: isolate writes with soft copy-on-write when a checkpoint may be stale, track dirty buffers and recopy them when freshness matters, and block only on not-yet-restored buffers during restore. The insight is not just "guess and check," but that buffer-level speculation is good enough for modern GPU workloads because frameworks allocate data fairly finely and kernels usually operate on whole buffers or tensors.

## Design

PhoenixOS has three main pieces: a command-line interface for checkpoint, restore, and migration; a frontend library inserted into the GPU stack with `LD_PRELOAD` to intercept GPU APIs; and a backend that uses `CRIU` for CPU state while managing GPU buffers and contexts itself. It can store checkpoints in local memory or storage, or move them over RDMA for migration.

For tracing writes, PhoenixOS divides GPU APIs into four groups. Memory-copy APIs, communication kernels, and vendor libraries such as cuBLAS have known semantics, so the system can derive their write sets directly. Opaque kernels launched through `cudaLaunchKernel` are handled by comparing launch arguments against the process's allocated GPU buffers and filtering arguments using the kernel signature, focusing on mutable pointers. Struct arguments are treated conservatively by scanning each 8-byte chunk as a possible buffer pointer. Validation is inserted at PTX level, and mis-speculation triggers a safe fallback.

Concurrent checkpointing then uses two protocols. Soft copy-on-write first briefly quiesces CPU and GPU execution, then starts copying state. If a later kernel would write an uncheckpointed buffer, PhoenixOS copies that buffer to spare GPU memory and makes the checkpoint read from the preserved version while execution continues on the new one. If spare memory is tight, it can briefly block or spill the copy through host memory. Soft recopy instead marks buffers that were written after being copied, re-quiesces when the main copy finishes, and recopies only the dirty set so the final checkpoint matches the latest state. To make recopy practical, PhoenixOS copies CPU data before GPU data, shrinking the GPU dirty window, and it chunks checkpoint traffic into 4 MB pieces so application DMA transfers can preempt checkpoint copies rather than starving on shared DMA engines.

Restore uses the same speculative tracing idea, extended to immutable pointer arguments so PhoenixOS knows which buffers a kernel may read. If execution touches an unrestored buffer, the kernel waits while PhoenixOS fetches that buffer on demand. The remaining bottleneck is GPU context creation, which the paper shows can be as expensive as data copy. PhoenixOS therefore maintains a daemon-side pool of pre-created CUDA, cuBLAS, and NCCL contexts and hands them to restored processes, avoiding most of that barrier.

## Evaluation

The evaluation runs on eight-GPU NVIDIA A800 servers with dual Xeon Gold 6348 CPUs, 1 TB DRAM, NVLink inside a node, and 100 Gbps RDMA between nodes. The workloads are mostly AI jobs, covering ResNet-152M, PPO-336M, Stable Diffusion 1B, Llama2-13B, and Llama3.3-70B in both single- and multi-GPU settings. The main baseline is the authors' tuned reimplementation of Singularity, with `cuda-checkpoint` included as a slower stop-the-world reference.

The headline numbers support the paper's claim. In fault-tolerance scenarios, PhoenixOS cuts checkpoint stall substantially; on Llama2-13B training, the checkpoint overhead falls from 3.2 seconds to 185 ms even though the job uses 72 GB of GPU state. Under the paper's assumed one-failure-per-hour model, that lower overhead lets PhoenixOS checkpoint 279 times per hour rather than 67, cutting wasted GPU time by 22-86% across training workloads. For live migration, downtime drops to 3.3 seconds for Llama2-13B training and 3.7 seconds for Llama3.3-70B inference, versus 10.2 and 12.35 seconds for Singularity. For serverless cold starts, the paper reports a 622 ms launch for Llama2-13B inference and average end-to-end speedups of 24x over `cuda-checkpoint` and 16x over Singularity.

The microanalysis also matters. Validator overhead is only 1-12%, and in the evaluated AI workloads only a minority of kernels need instrumented validation. In a broader feasibility study over Rodinia, Parboil, vLLM, TVM, and FlashInfer, PhoenixOS encountered no speculation failures in the modern AI workloads and only one failing kernel in Rodinia, though that older benchmark still produced 20 failing instances. That evidence makes the approach look convincing for current ML-style GPU software, but less universal for arbitrary legacy CUDA code.

## Novelty & Impact

PhoenixOS differs from prior GPU checkpoint work by aiming for both concurrent checkpoint and concurrent restore on production GPUs without application rewrites. Relative to hardware-assisted proposals such as GPU Snapshot, it replaces hardware dirty tracking with software speculation plus validation. Relative to startup-oriented restore-only systems, it solves the harder checkpoint side as well. The contribution is therefore a new systems mechanism: validated speculation as the missing observability layer that lets CPU-era C/R protocols work for GPUs.

If adopted, the immediate beneficiaries are infrastructure teams that manage GPU clusters, training jobs, and cold-start-sensitive inference services. The paper also contributes a broader design lesson: when accelerators do not expose the hardware hooks an OS wants, API-level semantics plus runtime validation can sometimes recover enough structure to re-enable classic OS techniques.

## Limitations

The main limitation is that correctness still depends on speculation rarely being wrong. PhoenixOS validates writes and can fall back safely, but the fallback is blunt: a failed checkpoint retries with stop-the-world execution, and a failed restore rolls back and performs stop-the-world restore. That preserves correctness, but it means the best-case fast path depends on workload regularity.

The tracing granularity is also only at buffer level for opaque kernels, so kernels that touch small regions of large buffers can cause over-tracing and extra copy-on-write or recopy work. The evaluation argues that AI frameworks usually allocate one tensor per buffer, which helps, but the paper's own Rodinia result shows the assumption is not universal. Finally, the implementation is tied to NVIDIA's software stack and evaluated almost entirely on AI workloads. Multi-process global quiescence still relies on user hints, and fast restore through the daemon-side context pool can introduce IPC overhead after restore; the paper reports up to 9% overhead in that mode.

## Related Work

- _Lee et al. (ICS '19)_ — _GPU Snapshot_ assumes hardware support for dirty tracking and checkpoint offloading, whereas PhoenixOS works on current production GPUs with software speculation and validation.
- _Bai et al. (OSDI '20)_ — _PipeSwitch_ accelerates deep-learning job switching with pipelined context switching, while PhoenixOS provides transparent OS-level checkpoint and restore for unmodified GPU processes.
- _Du et al. (ASPLOS '20)_ — _Catalyzer_ makes CPU-side serverless startup fast via initialization-less booting, whereas PhoenixOS restores full GPU process state and overlaps restore with GPU execution.
- _Yang et al. (SoCC '24)_ — _gCROP_ focuses on on-demand and parallel GPU restore, but PhoenixOS adds concurrent checkpointing too and is designed to work without application rewrites on NVIDIA GPUs.

## My Notes

<!-- empty; left for the human reader -->

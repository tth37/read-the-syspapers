---
title: "AlloyStack: A Library Operating System for Serverless Workflow Applications"
oneline: "AlloyStack runs a whole serverless workflow inside one MPK-partitioned LibOS, loading modules on demand and passing references instead of copying intermediate data."
authors:
  - "Jianing You"
  - "Kang Chen"
  - "Laiping Zhao"
  - "Yiming Li"
  - "Yichi Chen"
  - "Yuxuan Du"
  - "Yanjie Wang"
  - "Luhang Wen"
  - "Keyang Hu"
  - "Keqiu Li"
affiliations:
  - "College of Intelligence & Computing, Tianjin University, Tianjin Key Lab. of Advanced Networking, China"
  - "Tsinghua University, China"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717490"
code_url: "https://github.com/tanksys/AlloyStack"
tags:
  - serverless
  - kernel
  - isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

AlloyStack treats one serverless workflow as the unit of execution: all functions run inside one workflow domain with a shared address space, MPK between user and system code, on-demand LibOS loading, and slot-based zero-copy buffers. That cuts cold start to 1.3 ms and delivers 7.3x-38.7x Rust and 4.8x-78.3x C/Python end-to-end speedups on intermediate-data-heavy workflows.

## Problem

The paper studies serverless workflows rather than single functions. Prior measurements say 31% of serverless applications use workflows, and the five most popular Azure Durable Functions workflows account for 46% of total invocations. Because these workflows are composed of many short functions, platform overhead dominates user computation.

The two main costs are repeated cold start and intermediate-data movement. In the authors' OpenFaaS deployment of `ParallelSorting` with a 50 MB input, cold start accounts for 45% of end-to-end latency and data transfer for another 48%. Existing systems usually optimize only one side: warm starts and snapshots hide startup but need prediction and extra memory; specialization still leaves too much guest OS for tiny functions; thread-level runtimes remove copies but weaken isolation and often expose the host kernel more directly. The missing substrate is one that reduces both startup and communication without giving up strong isolation between workflows.

## Key Insight

The key claim is that the natural isolation boundary is usually the workflow, not each function. A tenant-owned DAG can often share one execution domain, while different workflows still need strong isolation. If that boundary is chosen correctly, a single LibOS can serve the whole workflow and intermediate objects can move by reference.

AlloyStack calls this abstraction a workflow domain (WFD): one address space, one LibOS instance, shared buffers for handoff, and optional stronger MPK partitions for sensitive stages. The important point is that sharing happens inside a LibOS boundary, so user code still cannot invoke the host kernel directly.

## Design

Each WFD is one process containing user functions, heap, runtime metadata, and `as-libos`. Intel MPK splits the address space into user and system partitions. `as-visor` creates and destroys WFDs, while `as-std` replaces Rust's `std`, intercepts would-be syscalls, and uses trampoline code to switch PKRU permissions before entering modular `as-libos`.

Startup is reduced by on-demand loading. A fresh WFD begins with no `as-libos` modules instantiated; the first `open()` or similar call causes `as-visor` to load the needed module and cache its entry. Data transfer uses `AsBuffer`: the sender allocates a buffer under a slot name and writes into it, while the receiver acquires the same slot and gets a reference. Because slots are namespaced inside the WFD, the mechanism supports chains, fan-out, and fan-in. C and Python support come through AOT-compiled WASM via Wasmtime plus a WASI adaptation layer.

## Evaluation

The evaluation uses microbenchmarks plus three real workflows: `WordCount`, `ParallelSorting`, and `FunctionChain`. Baselines include Unikraft, gVisor, Wasmer, Virtines, OpenFaaS, Faastlane, and Faasm.

Cold start is the clearest result. AlloyStack reaches 1.3 ms, while the same system without on-demand loading takes 89.4 ms. For 16 MB transfers, AlloyStack needs 951 us in Rust, 697 us in C, and 9631 us in Python, which the paper reports as 2.6x, 13.2x, and 1.8x improvements. Turning on stricter inter-function isolation increases transfer latency by only 0.8%-33.7%.

The end-to-end results mostly support the mechanism claim. Gains are largest when repeated startup and handoff dominate: the paper reports 7.3x-38.7x speedups for Rust and 4.8x-78.3x for C/Python on intermediate-data-intensive cases. But the paper is careful about where AlloyStack loses. `rust-fatfs` reads are 4.4x slower than ext4, so file-heavy `WordCount` settings narrow the advantage, and C `ParallelSorting` can fall behind Faasm because Wasmtime is slower than WAVM. The win is real, but concentrated in the workload regime the system targets.

## Novelty & Impact

AlloyStack combines two ideas usually studied separately: LibOS specialization for fast startup and workflow-local address-space sharing for fast handoff. The result is a workflow-scoped OS abstraction that cuts both costs while preserving a software boundary between user functions and the host kernel.

This matters most for DAG runtimes where one tenant owns the whole workflow and stages exchange substantial intermediate data. Within that slice, the paper is a strong argument that per-function heavyweight sandboxing is the wrong granularity.

## Limitations

The design depends on a trust model in which functions inside one workflow usually belong to the same tenant. AlloyStack can add stricter MPK separation between functions, but that reduces some of the efficiency it is trying to capture. The threat model also assumes the platform can reject or rewrite binaries containing instructions such as `wrpkru`, `syscall`, and `sysenter`.

The system is also limited operationally. It does not automatically split oversized workflows across nodes, fault tolerance for stateful functions is deferred to external systems such as Boki or Halfmoon, and `rust-fatfs`, `smoltcp`, and Wasmtime all help explain cases where AlloyStack loses. AlloyStack is strongest as a design for single-node, intermediate-data-heavy workflows, not as a complete answer for general serverless computing.

## Related Work

- _Kotni et al. (USENIX ATC '21)_ - Faastlane also runs workflow functions with in-process sharing and MPK, but AlloyStack adds a workflow-local LibOS and on-demand module loading so it keeps a stronger kernel boundary while still avoiding copies.
- _Mahgoub et al. (OSDI '22)_ - ORION reduces workflow latency through sizing, bundling, and prewarming of serverless DAGs, whereas AlloyStack attacks the same problem by changing the execution substrate inside each workflow instance.
- _Mahgoub et al. (USENIX ATC '21)_ - SONIC chooses efficient storage-backed data-passing methods for chained serverless applications; AlloyStack instead removes the storage hop by keeping communicating functions in one address space.
- _Kuenzer et al. (EuroSys '21)_ - Unikraft demonstrates that specialized library operating systems can cut startup cost, but it does not target workflow-wide module reuse and zero-copy function-to-function transfer inside one domain.

## My Notes

<!-- empty; left for the human reader -->

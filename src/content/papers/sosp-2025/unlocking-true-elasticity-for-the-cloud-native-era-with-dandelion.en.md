---
title: "Unlocking True Elasticity for the Cloud-Native Era with Dandelion"
oneline: "Dandelion replaces per-function POSIX sandboxes with DAGs of pure compute and communication functions, making secure per-request cold starts practical in 100s of microseconds."
authors:
  - "Tom Kuchler"
  - "Pinghe Li"
  - "Yazhuo Zhang"
  - "Lazar Cvetković"
  - "Boris Goranov"
  - "Tobias Stocker"
  - "Leon Thomm"
  - "Simone Kalbermatter"
  - "Tim Notter"
  - "Andrea Lattuada"
  - "Ana Klimovic"
affiliations:
  - "ETH Zurich"
  - "MPI-SWS"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764803"
code_url: "https://github.com/eth-easl/dandelion"
tags:
  - serverless
  - datacenter
  - isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Dandelion argues that serverless is still inelastic because each function boots a POSIX-like sandbox with guest-OS and networking state. It instead executes applications as DAGs of pure compute functions and trusted communication functions, letting compute sandboxes cold-start in 100s of microseconds and be created per request.

## Problem

The paper starts from a contradiction in current FaaS systems. Providers advertise elasticity, but still pre-provision many idle sandboxes because cold starts are too expensive for short requests. On the Azure Functions trace, Knative keeps 97% of requests warm, but commits about 16x more memory than the active sandboxes actually need.

The authors argue this is structural, not a tuning issue. A POSIX-like function sandbox must boot or restore OS state and networking before user code can run. Even snapshot-based Firecracker still spends more than 8 ms loading guest state and rebuilding the guest-host connection. Providers therefore choose between bad tail latency and large warm pools.

## Key Insight

The core proposition is that many cloud-native applications already separate naturally into local computation plus calls to remote services exposed over HTTP or similar APIs. If the platform makes that split explicit, user code no longer needs direct syscalls, sockets, or a guest kernel.

Dandelion therefore moves all external I/O into trusted communication functions and leaves untrusted code as pure compute functions with declared inputs and outputs. Once compute becomes pure, the platform can isolate it with much lighter sandboxes, run it to completion on dedicated cores, and independently multiplex I/O-heavy work.

## Design

A composition is a DAG of compute functions, communication functions, or nested compositions. Edges specify both data dependencies and distribution semantics: `all`, `each`, or `key`.

Compute functions use `dlibc`/`dlibc++`, which expose inputs and outputs as an in-memory virtual filesystem. Code can still do familiar file and memory operations, but syscalls such as `socket`, `mmap`, and thread creation are rejected.

Execution is centered on a dispatcher that tracks dependencies, prepares isolated memory contexts, and queues ready tasks to compute or communication engines. Compute engines run one task to completion; communication engines are trusted and use cooperative green threads. A control plane samples queue growth every 30 ms and uses a PI controller to shift cores between compute and communication. The prototype implements four compute backends: minimal KVM VMs without guest kernels, separate Linux processes plus `ptrace`, CHERI-based isolation, and an rWasm pipeline that compiles Wasm to safe Rust/native code. Data transfer between stages is currently copy-based.

## Evaluation

The headline microbenchmark result is that Dandelion makes per-request cold starts practical. Sandbox creation averages 89 us with the CHERI backend on Morello and 218 us with KVM on a standard Linux 5.15 setup, far below the millisecond-scale startup of Firecracker snapshots or gVisor. On 128x128 integer matrix multiplication, Dandelion KVM reaches about 4800 RPS, while Firecracker with 97% hot requests saturates near 3000 RPS because hot VMs and VM creation contend for CPU.

The end-to-end results matter more. Under bursty mixed workloads, Dandelion beats both Firecracker and Wasmtime on latency and variance because it does not depend on warm pools and can rebalance cores between compute and I/O. On the Azure Functions trace, it commits 109 MB on average versus 2619 MB for Firecracker plus Knative, a 96% reduction, while also lowering p99 end-to-end latency by 46%. The application studies show the model is broader than toy kernels: on roughly 700 MB Star Schema Benchmark queries over S3, Dandelion-as-QaaS reduces latency by 40% and cost by 67% relative to Athena for short queries. That Athena comparison is not same-hardware, so it is suggestive rather than definitive.

## Novelty & Impact

The novelty is the joint redesign of the programming model and execution substrate. Prior work often speeds up sandboxing or improves serverless orchestration, but Dandelion argues that serverless remains inelastic because it preserves the wrong interface. By making communication explicit and forbidding syscalls in compute functions, it reduces startup cost and narrows the attack surface at the same time.

The design is a plausible base for elastic query processing with untrusted UDFs, bursty data pipelines, and agentic workflows that alternate custom logic with remote services.

## Limitations

Dandelion only fits applications that can be cleanly split into pure compute and external communication. The paper explicitly excludes workloads with large shared state, OLTP, online gaming, AI training, and fine-grained multithreaded algorithms. Existing software may require manual decomposition around every I/O boundary, since automatic extraction is future work.

The current system is also narrower than the thesis. Communication support is mainly HTTP, data movement between stages is copy-based, and some isolation backends rely on special hardware or stronger trust assumptions than KVM. The security discussion is mostly attack-surface reasoning; denial of service and side channels are out of scope.

## Related Work

- _Agache et al. (NSDI '20)_ - Firecracker keeps the FaaS model centered on POSIX-like MicroVMs, while Dandelion removes guest-OS and network-stack responsibilities from compute sandboxes so cold-starting every request becomes feasible.
- _Yu et al. (NSDI '23)_ - Pheromone also makes data dependencies explicit for serverless orchestration, but Dandelion additionally turns external I/O into trusted communication functions and redesigns the runtime around that split.
- _Ruan et al. (NSDI '23)_ - Nu achieves microsecond-scale resource fungibility with logical processes, whereas Dandelion focuses on secure multi-tenant execution of untrusted code with stronger isolation boundaries.
- _Szekely et al. (SOSP '24)_ - SigmaOS adopts a cloud-centric interface for serverless and microservices, but still lets user code invoke many host syscalls; Dandelion narrows the interface further by blocking syscalls in compute functions entirely.

## My Notes

<!-- empty; left for the human reader -->

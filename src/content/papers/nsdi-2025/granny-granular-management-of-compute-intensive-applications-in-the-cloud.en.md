---
title: "GRANNY: Granular Management of Compute-Intensive Applications in the Cloud"
oneline: "GRANNY runs OpenMP and MPI applications as WebAssembly Granules, then scales threads and migrates processes at barrier points to reclaim idle cloud CPUs and reduce fragmentation."
authors:
  - "Carlos Segarra"
  - "Simon Shillaker"
  - "Guo Li"
  - "Eleftheria Mappoura"
  - "Rodrigo Bruno"
  - "Lluís Vilanova"
  - "Peter Pietzuch"
affiliations:
  - "Imperial College London"
  - "INESC-ID, Instituto Superior Técnico, University of Lisbon"
conference: nsdi-2025
category: memory-serverless-and-storage
code_url: "https://github.com/faasm/faasm/"
tags:
  - datacenter
  - scheduling
  - isolation
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

GRANNY is a cloud runtime that runs unmodified OpenMP and MPI programs as small WebAssembly execution units called Granules. Because each Granule can be snapshotted and controlled only at semantically safe barrier points, the scheduler can add threads to OpenMP jobs or migrate MPI ranks between VMs at vCPU granularity. That yields higher utilization for multithreaded jobs and lower fragmentation for distributed jobs than today's batch schedulers.

## Problem

The paper starts from a concrete mismatch between cloud schedulers and parallel applications. OpenMP and MPI jobs express their desired degree of parallelism when they are launched, and mainstream cloud schedulers largely freeze that allocation for the rest of execution. For multithreaded jobs, that means newly freed CPU cores inside a VM stay idle even when queued jobs exist. For multi-process jobs, schedulers face the opposite tension: allocating at VM granularity preserves locality but wastes spare vCPUs, while allocating at vCPU granularity improves utilization but can scatter one MPI job across many VMs and increase communication cost.

The paper argues that this is not mainly a bin-packing failure. Even a good scheduler cannot react once a job has started because the runtimes underneath OpenMP and MPI do not support safe, low-overhead reconfiguration. Adding threads dynamically risks violating shared-memory consistency, and migrating processes with existing checkpoint tools is too heavyweight and too entangled with kernel and network state to be used routinely during execution. The consequence is visible in the paper's experiments: Azure Batch and Slurm leave large fractions of CPU capacity idle for OpenMP workloads, while fine-grained scheduling of MPI jobs drives fragmentation and hurts job completion time.

## Key Insight

GRANNY's core claim is that cloud schedulers need a smaller, self-contained execution unit than a process or VM, together with precise semantic points where that unit can be manipulated safely. That unit is the Granule: one thread of execution that can run with thread semantics for OpenMP or process semantics for MPI.

WebAssembly makes this practical because it gives each Granule a memory-safe sandbox with a compact linear-memory state, while GRANNY's runtime backends intercept OpenMP, MPI, and POSIX calls and keep the relevant runtime metadata outside the guest code. The second half of the insight is equally important: GRANNY only performs scaling or migration at barrier control points where shared-memory updates or in-flight messages are known to be consistent. Once those two conditions hold, the same abstraction can support both vertical scale-up and horizontal migration for unmodified applications, requiring only recompilation to WebAssembly instead of source rewrites.

## Design

Each VM runs one GRANNY runtime instance, and the cluster has a centralized scheduler. Within a VM, multiple Granules execute side by side inside one host process. The system exposes three backends. The MPI backend implements `MPI_*` calls with per-Granule mailboxes and TCP for cross-VM traffic. The OpenMP backend implements the expanded `__kmpc_*` and `omp*` interfaces from LLVM's runtime. The POSIX backend implements the subset of WASI and filesystem calls needed by the applications, while tracking the mapping between WebAssembly and host file descriptors so snapshots remain meaningful.

The crucial representation detail is that Granules executing with process semantics have separate linear memories, while Granules executing with thread semantics share one linear memory but keep separate stacks. When an OpenMP region forks, GRANNY allocates the child stack in the parent's heap, adds guard pages, and starts a new Granule at the right WebAssembly function-table entry. For MPI, sends and receives are captured by the backend, delivered through mailboxes, and forwarded over TCP only when the peer lives on another VM.

Snapshots combine the Granule's linear memory with runtime state such as stack pointers, function tables, message queues, and file-descriptor tables. GRANNY distinguishes regular control points from barrier control points. Regular points are enough for ordinary I/O and messaging, but management actions happen only at barriers, such as `MPI_Barrier` or an OpenMP barrier, when the runtime can assume there are no outstanding messages or unsynchronized shared-memory updates. Vertical scaling then becomes "spawn another thread-style Granule on the same shared memory." Horizontal migration pauses an MPI job at a barrier, has the root rank query the scheduler, snapshots the selected Granule at the source VM, rebuilds its mailbox and descriptor state at the destination, and finally resumes everyone with updated routing. On top of those mechanisms, the paper implements three policies: compaction for MPI locality, elastic scale-up for OpenMP utilization, and pre-eviction migration for spot VMs.

## Evaluation

The prototype is substantial enough to be credible: 24,000 lines of C++20 built on Faasm and WAMR, evaluated on Azure with up to 32 `Standard_D8_v5` VMs. The paper uses traces of unmodified MPI and OpenMP applications compiled to WebAssembly, plus isolated microbenchmarks for the runtime mechanisms.

For MPI workloads, the compaction policy is the clearest end-to-end result. On a 100-job LAMMPS trace, GRANNY improves makespan by up to 20% and keeps fragmentation about 25% lower than Slurm while intentionally leaving only 5% of vCPUs idle. Azure Batch gets good locality too, but only by leaving about 30% of vCPUs unused. The payoff appears in job completion times: median and tail JCT improve by up to 20% over the baselines.

For OpenMP workloads, the elastic policy delivers the paper's biggest headline number. GRANNY reduces makespan by up to 60%, cuts aggregate idle CPU-seconds by up to 30%, and improves median and tail JCT by up to 50% on a 200-job ParRes trace. The reason is straightforward and convincing: while pending work remains, Azure Batch and Slurm still leave about 60% and 40% of vCPUs idle, whereas GRANNY keeps idle capacity closer to 20% by adding Granules when barriers are reached. The spot-VM policy is also meaningful rather than a footnote: under a 25% eviction rate, native baselines suffer 50%-100% slowdown and sometimes nearly 2x, while GRANNY caps slowdown at 25%, which preserves the cost advantage of spot instances.

The microbenchmarks show the mechanism is not prohibitively expensive. The MPI backend usually stays within 10% of OpenMPI, most OpenMP kernels match `libomp`, a 4 MB migration takes about 30 ms with only about 3 ms spent creating the snapshot, and elastic scale-up gives up to 60% speedup when increasing from 1 to 6 threads. The evaluation supports the main claim, although it is still a controlled 32-VM study with homogeneous traces rather than production deployment evidence.

## Novelty & Impact

GRANNY's novelty is not just "another better scheduler." The deeper contribution is a runtime abstraction that makes cloud schedulers able to act on the real unit of parallelism in MPI and OpenMP programs: a thread- or process-like Granule mapped to one vCPU, snapshottable in user space, and safe to manipulate at barrier points. Compared with prior elasticity work such as CloudScale, GRANNY operates inside the parallel runtime rather than only at a coarser resource-management layer. Compared with Nu, it preserves existing OpenMP and MPI programming models instead of asking developers to rewrite applications around a new messaging abstraction.

That combination makes the paper useful to several communities: cloud batch schedulers, HPC-on-cloud runtimes, WebAssembly systems, and researchers working on transparent migration or spot-instance resilience. It is a new mechanism plus a credible demonstration that the mechanism unlocks practical scheduling policies.

## Limitations

The design depends on recompiling applications and their dependencies to WebAssembly, which is a meaningful deployment constraint even if source changes are unnecessary. The current system is CPU-only, so GPU-intensive workloads are out of scope. GRANNY's cooperative control model also relies on applications reaching barrier control points frequently enough; if barriers are sparse, opportunities for scale-up or migration become limited.

The paper is also candid about WebAssembly costs. Most kernels are close to native speed, but floating-point-heavy `dgemm` slows down by about 80%, and large sandboxes above 4 GB still incur higher overheads. Finally, the evaluation uses one application family per trace on a 32-VM testbed, so the claimed gains under more heterogeneous or production workloads remain an inference rather than a demonstrated fact.

## Related Work

- _Ruan et al. (NSDI '23)_ - Nu also pursues resource fungibility through migration, but it requires applications to be rewritten around Proclets and message passing, whereas GRANNY keeps OpenMP and MPI semantics for existing code.
- _Shen et al. (SoCC '11)_ - CloudScale automates elastic scaling in multi-tenant clouds, while GRANNY focuses on much finer thread/process-granularity control inside running parallel jobs.
- _Planeta et al. (USENIX ATC '21)_ - MigrOS supports live migration for containerized RDMA applications, but it relies on heavier protocol support, whereas GRANNY uses self-contained WebAssembly snapshots and barrier-aware runtime semantics.
- _Wang et al. (SC '08)_ - Proactive process-level live migration for MPI systems moves whole processes at higher checkpointing cost; GRANNY instead migrates per-vCPU Granules at semantically safe barriers.

## My Notes

<!-- empty; left for the human reader -->

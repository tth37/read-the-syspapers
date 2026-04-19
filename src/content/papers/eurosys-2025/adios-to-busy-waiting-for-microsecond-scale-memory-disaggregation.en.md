---
title: "Adios to Busy-Waiting for Microsecond-scale Memory Disaggregation"
oneline: "Adios replaces busy-waiting page faults in memory disaggregation with yield-based handlers, tiny unithreads, and PF-aware dispatching inside one unikernel."
authors:
  - "Wonsup Yoon"
  - "Jisu Ok"
  - "Sue Moon"
  - "Youngjin Kwon"
affiliations:
  - "KAIST"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717475"
code_url: "https://github.com/ANLAB-KAIST/adios"
tags:
  - memory
  - disaggregation
  - rdma
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Adios replaces busy-waiting page faults in memory disaggregation with a yield-based path inside one OSv unikernel. A fault issues RDMA, yields to another `unithread`, and resumes on completion; the result is less queueing, higher RDMA utilization, and better tail latency than DiLOS, Hermit, and a preemptive DiLOS variant.

## Problem

Recent paging-based MD systems busy-wait because classic interrupt-and-wakeup paths can cost more than a 2-3 us RDMA fetch. That shortens one fault, but it damages the loaded system: a worker spinning on remote memory blocks later requests, and the NIC sees too few in-flight fetches. The paper's DiLOS study shows the failure mode clearly: around 1.3-1.4 MRPS, P99 latency explodes while RDMA utilization is still only about 50%. The limiting resource is therefore not the link, but the control path around page faults.

## Key Insight

Yielding can work again if the page-fault handler and scheduler are no longer separated by an expensive protection boundary. By putting the fault handler, scheduler, and request contexts in the same address space, Adios makes a page fault cheap to suspend and resume. The paper's lasting claim is that microsecond-scale MD needs scheduler/kernel co-design, not just a faster busy-wait loop.

## Design

Adios runs on OSv so the memory manager, scheduler, and applications share one protection domain. Each request gets a lightweight `unithread` whose buffer contains packet payload, saved context, and a universal stack used by both application code and kernel exception handling. The saved context is only 80 B, the minimum per-request footprint is 4 KB, and context switching is 4.7x faster than Shinjuku's `ucontext_t`, according to the paper.

When a request faults, the handler issues a one-sided RDMA fetch and yields immediately instead of spinning. The worker returns to the dispatcher, takes another request, and later resumes the faulted path when the completion is polled; only then is the page mapped and the original request continued. Adios also keeps a pinned reclaimer thread so yielded faults do not stall behind delayed page reclamation.

Yielding increases concurrency, which can skew outstanding faults across workers and RDMA queue pairs. Adios therefore adds `PF-aware dispatching`: the dispatcher ranks idle workers by outstanding page-fault count and sends new requests to the least congested ones. It also uses polling delegation so workers do not busy-wait on reply completions.

## Evaluation

The evaluation uses separate compute, memory, and load-generator nodes with 100 GbE NICs. In the main microbenchmark, a 40 GB array is served with only 8 GB of local cache, so 80% of accesses are remote. At 1.3 MRPS, Adios cuts queueing delay relative to DiLOS by 16.3x at P99 and 36.8x at P99.9. Peak throughput rises to about 2.5 MRPS, 1.58x DiLOS, while RDMA utilization climbs to 82% instead of stalling near 50%.

The application results are similarly consistent. Against DiLOS, Adios improves Memcached P99.9 latency by up to 10.89x, RocksDB GET P99.9 latency by 7.61x, Silo P99.9 latency by 2.24x, and Faiss P99.9 latency by 1.99x; throughput gains range from 1.07x to 1.64x. RocksDB is the strongest validation because the paper also compares against `DiLOS-P`, a preemptive scheduler variant, and Adios still wins on GET tail latency and throughput. The evaluation is careful with paging-style baselines, though it does not give a direct apples-to-apples comparison against library systems such as AIFM.

## Novelty & Impact

Compared with _Gu et al. (NSDI '17)_ on Infiniswap, Adios brings yielding back to paging-based MD without paying old scheduler costs. Compared with _Qiao et al. (NSDI '23)_ on Hermit and _Yoon et al. (EuroSys '23)_ on DiLOS, it argues that spinning is not inevitable if the execution substrate is redesigned. The paper will likely matter to far-memory systems, microsecond schedulers, and unikernel research because it shifts attention from the fault fast path to the scheduler/kernel boundary.

## Limitations

The deployment cost is substantial. Adios is an OSv-based prototype rather than a drop-in Linux mechanism, and the evaluation still uses small application changes plus 100-300 LoC adapters per application. Its benefits are strongest for highly concurrent, memory-intensive services; compute-heavy or lightly threaded programs have little other work to run during a fault. The scheduler is still cooperative and single-queue, which the authors say scales to only about ten worker cores, and the system dedicates pinned dispatcher and reclaimer threads. The prototype also targets UDP-style microsecond networking, not a full production TCP stack.

## Related Work

- _Gu et al. (NSDI '17)_ - Infiniswap introduced paging-based MD with yield-style faults, but later systems abandoned that path because conventional schedulers were too expensive.
- _Qiao et al. (NSDI '23)_ - Hermit overlaps useful work with fault latency, yet still leaves busy-waiting in the page-fault path.
- _Yoon et al. (EuroSys '23)_ - DiLOS shows the best busy-waiting transparent MD baseline; Adios keeps the same goal but changes the cooperation model.
- _Ruan et al. (OSDI '20)_ - AIFM also avoids busy-waiting, but as an application-integrated library rather than a paging-based system.

## My Notes

<!-- empty; left for the human reader -->

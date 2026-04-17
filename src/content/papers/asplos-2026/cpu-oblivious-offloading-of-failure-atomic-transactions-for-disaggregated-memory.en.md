---
title: "CPU-Oblivious Offloading of Failure-Atomic Transactions for Disaggregated Memory"
oneline: "Offloads transaction-log durability for disaggregated memory to the CXL switch, replacing synchronous remote fences with asynchronous completion checks and no CPU changes."
authors:
  - "Cheng Chen"
  - "Chencheng Ye"
  - "Yuanchao Xu"
  - "Xipeng Shen"
  - "Xiaofei Liao"
  - "Hai Jin"
  - "Wenbin Jiang"
  - "Yan Solihin"
affiliations:
  - "Huazhong University of Science and Technology, Wuhan, Hubei, China"
  - "University of California, Santa Cruz, Santa Cruz, California, USA"
  - "North Carolina State University, Raleigh, North Carolina, USA"
  - "University of Central Florida, Orlando, Florida, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790146"
tags:
  - disaggregation
  - persistent-memory
  - transactions
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Fanmem targets the worst part of persistent transactions on disaggregated memory: the last synchronous fence that still forces the CPU to wait for remote durability. Its move is to let the CXL switch acknowledge log writes early, track durability progress itself, and let software poll for completion later. That preserves failure atomicity while avoiding CPU modifications.

## Problem

The paper starts from a simple mismatch. Persistent-memory transactions were designed for machines where persistence is close enough that a `clwb` plus `sfence` is expensive but still tolerable. In CXL-style disaggregated memory, that assumption breaks down because the log write must cross the switch, reach a remote memory server, and persist there before the fence can retire. The paper cites CMM-H access latency around `728.9ns`, and argues that this stretches the cost of each persist barrier into a dominant execution bottleneck.

Existing approaches miss the target in different ways. Software systems such as SpecPMT reduce the number of fences, but they still pay synchronously for the remaining one. Hardware schemes such as HOOP or ASAP can overlap persistence more aggressively, yet they require CPU-side architectural support and therefore conflict with the vendor-agnostic, heterogeneous deployment model that makes CXL attractive in the first place. The problem is therefore not merely "make transactions faster," but "provide failure-atomic transactions across compute-server, switch, and memory-server failures without tying the solution to one CPU design."

## Key Insight

The central claim is that a transaction system for disaggregated memory does not need the CPU to know exactly when each remote log write becomes durable. It only needs a cheap way to determine whether the log prefix for a transaction has definitely reached persistent memory before commit.

That observation lets Fanmem move durability tracking into the CXL switch. If each thread writes log records into an append-only sequential log area, the switch can maintain a cursor that marks the highest contiguous durable byte. Software no longer waits for remote persistence on the critical path; it waits only long enough for the switch to receive the log writes, proceeds with unrelated work, and later commits once a cursor check shows that its log tail is durable. The proposition to remember is that sequential logging plus switch-side durability cursors is enough to decouple execution from persistence while keeping the commit rule simple.

## Design

Fanmem is built around a three-stage transaction lifecycle: execution, offloading, and commit. During execution, software modifies data normally and records speculative log entries containing new values, as in SpecPMT. During offloading, it flushes those log writes with `clwb` and executes `sfence`, but Fanmem changes the meaning of that fence: the CPU only waits until the Fanmem-enabled switch has received and buffered the log writes, not until the remote memory server has persisted them. The transaction then ends execution with `tx_end()`, and the application can run more work before checking persistence.

The design relies on per-thread sequential log areas in disaggregated memory. Because each area is append-only and physically contiguous, persistence can be summarized by one switch-maintained cursor per log area. Software remembers the address of the last byte in a transaction's final log record and later issues a memory-mapped load to read the cursor. If the cursor has advanced past that address, the transaction's logs are durable.

Inside the switch, two structures make this work. The Log Area Table (LAT) identifies whether an incoming write belongs to a registered log area. To scale, the LAT is partitioned by source port into smaller pLATs rather than one large associative structure. The Log Write Status Table (LWST) then tracks in-flight log writes for each log area using a cursor plus a sliding-window bit vector, instead of storing full addresses for every pending write. When the memory server confirms persistence, the switch marks that entry durable and advances the cursor across the contiguous durable prefix.

Correctness is enforced by CPU-side commit logic rather than switch-side transaction semantics. Fanmem timestamps transactions at the end of execution and commits them in execution order once their logs are persistent, conservatively treating earlier finished transactions as dependencies. Recovery reads the latest persisted per-process commit timestamp and replays only the committed logs. The switch therefore remains lightweight and CPU-oblivious, while software retains the ordering policy. When switch metadata tables overflow, Fanmem falls back to synchronous persistence for that transaction, so the worst case is the baseline behavior rather than deadlock or silent loss of durability.

## Evaluation

The evaluation is strong on the paper's stated bottleneck. The authors test Fanmem in gem5 on two disaggregated architectures, `CXL-F` and the higher-latency `CXL-S`, with STAMP and TPC-C workloads, and they compare against SpecPMT, Crafty, SPHT, DudeTM, PMNet, and a no-log execution baseline. They also build an FPGA prototype to estimate switch resource cost.

The headline numbers support the core claim. Relative to SpecPMT, Fanmem improves average throughput by `1.2x` on `CXL-F` and `1.7x` on `CXL-S`, with the larger win on `CXL-S` matching the paper's intuition that more remote latency leaves more to hide. On individual workloads, `ssca2` reaches up to `3.1x` because its transactions are short and persistence-heavy, while `labyrinth` benefits much less because its long computation dominates. That regime split is actually reassuring: the optimization helps most when remote durability is truly the bottleneck.

The scaling and sensitivity studies are also useful. At 32 threads on `CXL-S`, Fanmem continues scaling while the other schemes flatten earlier, and the paper attributes that mostly to lower write amplification. Increasing the switch-to-memory latency raises Fanmem's relative benefit from about `1.1x` to `2.0x`, and larger log sizes also help its advantage grow. The hardware cost is modest for a switch-side mechanism: the FPGA prototype uses `2,590` flip-flops, `3,361` LUTs, and `594KB` BRAM, with an ASIC estimate of `1.4 mm²` and `479.2 mW`.

I found the evaluation convincing for the narrow claim that remote log persistence dominates many disaggregated-memory transactions and that early switch acknowledgment removes much of that cost. It is less broad as an end-to-end systems study: the default setup is single-threaded, the workloads are classic transactional benchmarks rather than modern cloud applications, and the win is clearly weaker once application compute dwarfs persist latency. Still, the baselines are appropriate and the experiments directly exercise the mechanism the paper proposes.

## Novelty & Impact

Relative to _Ye et al. (ASPLOS '23)_, Fanmem's novelty is not speculative logging itself, but removing the last synchronous remote stall that SpecPMT still pays. Relative to _Seemakhupt et al. (ISCA '21)_, it does not extend persistence into a NIC-resident domain; instead, it turns the switch into a lightweight durability tracker while keeping logs in remote memory. Relative to CPU-assisted transaction designs such as _Castro et al. (FAST '21)_ or _Cai et al. (ISCA '20)_, its most important contribution is architectural placement: the acceleration point sits in the CXL fabric, not in the processor.

That makes the paper likely to matter to architects working on CXL memory pools, persistent-memory researchers looking for post-Optane designs, and system builders who want crash consistency without standardizing on one CPU vendor. This is mainly a new mechanism and placement argument, not a new transaction model from first principles.

## Limitations

Fanmem depends on a fairly disciplined logging structure. Each thread needs a sequential, append-only log area, and the cursor mechanism becomes less natural if a transaction system wants scattered log records or more dynamic log reuse. The paper argues the approach extends to other logging protocols, but it also admits that undo logging would require more hardware dependency tracking and would move away from the switch's deliberately simple design.

The performance story is also conditional. Fanmem hides log-persistence latency; it does not reduce the intrinsic latency of disaggregated memory accesses, so workloads with large working sets or long compute phases gain much less. The overflow policy is safe but revealing: if the LAT or LWST runs out of entries, the system falls back to the baseline synchronous path, which means capacity planning for switch metadata matters. Finally, the implementation treats each process independently and focuses on correctness under component failures, not on cluster-level software concerns such as admission control, replication, or interoperability with higher-level distributed transactions.

## Related Work

- _Ye et al. (ASPLOS '23)_ — SpecPMT removes one fence with speculative logging, but still waits synchronously for remote durability; Fanmem offloads that remaining stall into the CXL switch.
- _Seemakhupt et al. (ISCA '21)_ — PMNet pushes persistence into the network using persistent memory near the NIC, whereas Fanmem keeps remote memory as the durable store and uses switch-side metadata to track progress.
- _Castro et al. (FAST '21)_ — SPHT is a hardware-assisted persistent transaction design based on redo-style mechanisms and CPU cooperation; Fanmem instead avoids processor changes by moving acceleration into the fabric.
- _Cai et al. (ISCA '20)_ — HOOP shows that hardware can overlap persistence effectively, but it does so with CPU-side architectural support rather than a CPU-oblivious switch.

## My Notes

<!-- empty; left for the human reader -->

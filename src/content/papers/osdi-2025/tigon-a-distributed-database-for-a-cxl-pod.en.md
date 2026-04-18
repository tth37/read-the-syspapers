---
title: "Tigon: A Distributed Database for a CXL Pod"
oneline: "Tigon keeps only cross-host active tuples in shared CXL memory, adds DB-aware software coherence, and lets one host commit multi-partition transactions without 2PC."
authors:
  - "Yibo Huang"
  - "Haowei Chen"
  - "Newton Ni"
  - "Yan Sun"
  - "Vijay Chidambaram"
  - "Dixin Tang"
  - "Emmett Witchel"
affiliations:
  - "The University of Texas at Austin"
  - "University of Illinois Urbana-Champaign"
conference: osdi-2025
code_url: "https://github.com/ut-datasys/tigon"
tags:
  - databases
  - transactions
  - disaggregation
  - memory
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Tigon is the first distributed in-memory database built for a small CXL pod, where multiple hosts share a CXL memory device. Its main move is to keep only the cross-host active tuples in CXL memory, store synchronization-heavy metadata in the limited hardware-coherent region, and use database-aware software coherence for the rest. That lets one host execute and log a multi-partition transaction without 2PC, yielding up to 2.5x higher throughput than optimized shared-nothing baselines and up to 18.5x over an RDMA-based disaggregated-memory database.

## Problem

The paper targets the classic bottleneck in distributed OLTP: once a transaction touches more than one partition, the system pays for remote message exchanges, distributed locking, and usually two-phase commit. Shared-nothing engines such as Sundial or DS2PL therefore lose throughput rapidly as the fraction of multi-partition transactions rises. RDMA-based designs avoid some message overhead, but tuple access and synchronization still happen over microsecond-scale network round trips, so the cost remains high.

CXL pods create a new opportunity because several hosts can directly load, store, and atomically update a shared memory region. But the paper is careful not to treat CXL as "cheap remote DRAM." Measured CXL latency is about 1.6x-3.5x higher than local DRAM, bandwidth is much lower, and only a small fraction of the physical address space is expected to remain hardware cache-coherent across hosts. A naive design that simply places the database in CXL memory would saturate bandwidth and burn scarce coherence metadata. Tigon therefore has to answer a narrower question: which data really must be shared at memory speed, and how can that subset be synchronized without making the whole database live in CXL?

## Key Insight

Tigon's central claim is that a transactional database does not need to share all database state across hosts; it only needs to share the tuples that are actively being accessed by transactions running on different hosts. The paper calls this set the Cross-host Active Tuples, or CAT. Because each transaction usually touches only a small number of tuples, the CAT is much smaller than the full database. In the paper's TPC-C example, 1,000 concurrent transactions imply only about 39K active tuples, roughly 7 MB of data.

Once the CAT is the unit of sharing, the rest of the design follows. Synchronization-heavy metadata such as locks, latches, and the CXL index can fit in the limited hardware cache-coherent region. Tuple payloads and less synchronization-intensive metadata can live in the larger non-coherent CXL region, with coherence maintained in software and tied to the database's own locking discipline. That gives Tigon a way to replace many network messages with atomic memory operations, while still keeping most data in fast local DRAM.

## Design

Tigon starts from a partitioned architecture: each host owns a disjoint partition in local DRAM, and owner-local accesses stay local. When another host needs a tuple, it asks the owner to move that tuple into shared CXL memory. A tuple moved to CXL is split into an 8-byte hardware-coherent record and a software-coherent row. The HWcc record stores the latch, 2PL lock bits, a `has-next-key` flag for range locking, a dirty bit, a CLOCK bit for eviction, a per-host software-coherence bitmap, and a pointer to the SWcc row. The SWcc row stores the tuple payload, validity flag, and epoch-version metadata.

Two indexing paths make this workable. Each host has a local DRAM index for its own partition. Tigon also maintains a CXL index, in hardware-coherent memory, for tuples currently resident in CXL. The owner host keeps a shortcut pointer from its local row to the tuple's HWcc record, so it can avoid searching the CXL index when its own tuple has been moved out. That shortcut matters because owners still frequently read or write their own tuples after remote sharing begins.

The software cache-coherence protocol is co-designed with database latching. A host reading an SWcc row checks its bit in the `SWcc-bitmap`: if the bit is set, it can use cacheable loads; otherwise it flushes the relevant cachelines, fetches the row, and sets its bit. Writers clear the bits of other hosts. This is narrower than general-purpose coherence, but the paper's point is that a database already serializes tuple access through latches, so coherence metadata can piggyback on those critical sections.

Tigon then adapts transaction processing around this layout. It uses strong strict 2PL with `NO_WAIT` deadlock prevention and extends next-key locking so range queries remain serializable even when the CXL index contains only a subset of a partition's tuples. The `has-next-key` bit tells a worker whether the next key in the CXL index is also the next key in the owner's local index; otherwise it requests more tuples be moved into CXL.

The most important systems consequence is that Tigon can avoid 2PC. Once the needed remote tuples are in CXL memory, one transaction worker can execute all tuple updates itself, and only tuple changes need to be logged locally because index updates can be reconstructed during recovery. Tigon adapts SiloR's epoch-based group commit so each worker logs value changes, logger threads flush them to local SSD, and committed epochs are replayed in parallel during recovery. To keep scarce HWcc memory from filling permanently, owners evict tuples back to local DRAM on demand using CLOCK rather than LRU, and clean tuples can often still be read from local DRAM via the `is-dirty` bit.

## Evaluation

The evaluation uses an emulated 8-host CXL pod built from 8 VMs on one physical machine with a 128 GB CXL 1.1 device, capping the hardware-coherent region at 200 MB. The baselines are not strawmen: the authors add next-key locking and the same logging protocol to Sundial and DS2PL, replace their network transport with CXL-memory queues, and repurpose an I/O thread into a worker, producing Sundial+ and DS2PL+. Motor represents an RDMA-based shared disaggregated-memory design.

The results support the paper's main claim that CXL shared memory is valuable not just as a faster transport, but as a place to synchronize shared tuples directly. On TPC-C, Tigon is slower when there are no multi-partition transactions, trailing Sundial+ by 37% and DS2PL+ by 8.5%; that is an honest sign that the design pays overhead when sharing is unnecessary. But as the workload shifts to 60% remote `NewOrder` and 90% remote `Payment`, Tigon becomes 75% faster than Sundial+, 2.5x faster than DS2PL+, and 15.9x-18.5x faster than Motor. For YCSB, at 100% multi-partition transactions Tigon is 2.0x-2.3x faster than Sundial+ on read-heavy mixes, and 5.4x-14.3x faster than Motor across the tested workloads.

The scaling experiment shows similar behavior: from 1 to 8 hosts, Tigon improves throughput by 5.7x on TPC-C and 3.5x on YCSB, versus only 2.4x/2.1x and 1.4x/1.5x for Sundial+/DS2PL+. The hardware-coherence budget study is also important. Tigon is only 5.8% slower with 50 MB of HWcc memory than with 200 MB, which suggests the CAT really is small enough to fit the intended pod regime. The main caveat is that the pod is emulated on one machine, so real inter-host hardware coherence will likely be slower. The authors estimate that even if back-invalidations were 4x more expensive than local invalidations, Tigon would still beat DS2PL+ by 45% and Motor by 9.6x on their TPC-C setting.

## Novelty & Impact

Compared with _Huang et al. (CIDR '25)_, which outlines the Pasha architecture for CXL pods, Tigon is the first end-to-end transactional database actually designed, implemented, and evaluated around that hardware model. Compared with shared-nothing systems such as _Yu et al. (VLDB '18)_, it does not try to optimize around network coordination; it changes the execution model so many multi-partition transactions become single-host executions over shared memory. Compared with _Zhang et al. (OSDI '24)_, it argues that within a small pod, CXL memory can beat RDMA-based disaggregated memory by eliminating microsecond-scale remote synchronization from the hot path.

The broader impact is a new systems decomposition for databases on emerging shared-memory fabrics. Tigon does not claim that CXL turns a pod into a giant SMP. Instead, it shows that if the system isolates the actively shared subset, uses the tiny coherent region for metadata, and lets the database own coherence policy, then limited inter-host CXL memory is enough to remove 2PC from an important slice of distributed OLTP.

## Limitations

The failure model is narrow. Tigon assumes fail-stop behavior, writes logs to local SSDs, and treats any component failure as a failure of the entire system followed by recovery. That sidesteps the partial-failure and independently failing-host problems that a real CXL pod will have to face. The paper also depends on some hardware cache-coherent CXL memory; it explicitly leaves a design for fully non-coherent CXL devices to future work.

There are also scope limits in workload and protocol coverage. Tigon is built for small pods, roughly 8-16 hosts, not datacenter-scale clusters. It implements SS2PL and next-key locking, but not OCC or MVCC, so it may give up performance on read-heavy workloads. The evaluation is strong on throughput and fairness, but it is still an emulation whose coherence behavior is likely more favorable than future hardware. Finally, the system wins only when the CAT stays modest; if too much of the database is shared concurrently, HWcc capacity, atomic contention, or coherence traffic could become the next bottleneck.

## Related Work

- _Huang et al. (CIDR '25)_ — Pasha proposes a CXL-pod database architecture, while Tigon turns that architectural direction into a concrete transactional engine with coherence, locking, and recovery.
- _Yu et al. (VLDB '18)_ — Sundial improves distributed OLTP within a shared-nothing architecture, whereas Tigon avoids much of that architecture's network coordination by sharing only the active cross-host tuples.
- _Zhang et al. (OSDI '24)_ — Motor also avoids classic partition-local execution, but it relies on RDMA-based disaggregated memory and replication; Tigon instead uses CXL memory inside a pod to make synchronization itself cheaper.
- _Zhang et al. (SOSP '23)_ — CXL-SHM studies distributed shared memory management and partial failures over CXL, while Tigon is database-specific and co-designs software coherence with tuple locks and indexes.

## My Notes

<!-- empty; left for the human reader -->

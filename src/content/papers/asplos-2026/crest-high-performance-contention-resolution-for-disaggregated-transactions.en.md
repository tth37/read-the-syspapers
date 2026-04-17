---
title: "CREST: High-Performance Contention Resolution for Disaggregated Transactions"
oneline: "Uses cell-level locking, localized execution, and dependency-aware parallel commits to cut false aborts and blocking in RDMA disaggregated transactions."
authors:
  - "Qihan Kang"
  - "Mi Zhang"
  - "Patrick P. C. Lee"
  - "Yongkang Hu"
affiliations:
  - "State Key Lab of Processors, Institute of Computing Technology, Chinese Academy of Sciences, University of Chinese Academy of Sciences, Beijing, China"
  - "State Key Lab of Processors, Institute of Computing Technology, Chinese Academy of Sciences, Beijing, China"
  - "Department of Computer Science and Engineering, The Chinese University of Hong Kong, Hong Kong, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790148"
code_url: "https://github.com/adslabcuhk/crest"
tags:
  - transactions
  - disaggregation
  - rdma
  - databases
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CREST targets the failure mode that appears when disaggregated OLTP systems meet hot records: record-level locking turns many benign overlaps into aborts, while strict visibility makes real conflicts wait through multiple RDMA round-trips. It answers with cell-level concurrency control, localized execution inside a compute node, and dependency-aware parallel commits. On high-contention workloads, that is enough to beat Motor by up to `1.92x`.

## Problem

FORD and Motor already show that RDMA-connected compute pools and memory pools can process transactions efficiently under ordinary loads, but high-contention OLTP workloads remain common and disaggregation makes their failure mode worse.

The authors isolate two root causes. First, state-of-the-art systems use record-level concurrency control, so transactions that touch different columns of the same row still conflict. Under TPC-C at 20 warehouses, FORD and Motor reach abort rates of `75.9%` and `85.2%`, and about `40-44%` of those aborts are false conflicts. Second, strict locking makes true conflicts expensive: a coordinator must hold locks through validation, logging, remote updates, and release, so each conflict inherits multiple RDMA round-trips of blocking.

## Key Insight

The paper's central proposition is that high-contention disaggregated transactions become cheaper once the system separates "what must be serialized" from "what merely shares a record container." In modern schemas, many transactions access only a subset of a row's fields, so conflicts should be tracked at cell granularity.

That finer granularity only matters if conflicting work also becomes visible sooner. CREST therefore exposes uncommitted results inside a compute node and pipelines execution blocks so later local transactions can continue from fresh local versions instead of stalling on remote commit completion. Commits then proceed in parallel as long as dependencies are tracked and only the last valid writer updates the memory pool.

## Design

CREST has three tightly coupled mechanisms. The first is cell-level concurrency control. Each record is divided into cells, each cell carries its own epoch number and commit timestamp, and the record header aggregates lock bits plus an epoch-number array. That layout lets a coordinator lock multiple cells with one masked `CAS`, validate multiple cells with one `READ`, and test whether it saw a consistent multi-cell view. If the 2-byte epoch numbers might have wrapped, the system falls back to whole-record validation.

The second mechanism is localized execution. Each compute node keeps a record cache with fetched records, reference counters, epoch arrays, and uncommitted version lists. Transactions that read another local transaction's tentative version record that dependency explicitly. To reduce lock hold time, CREST uses pipelined execution with `2PL` inside each block and execution timestamps across blocks.

The third mechanism is parallel commit. Validation checks that read epochs still match remote state and that dependent transactions did not abort. A committable transaction gets a commit timestamp, writes a redo log with its updates and dependencies, and participates in a last-writer-wins protocol. The coordinator whose `writers` count drops to zero becomes the last writer for that record and pushes the final version to memory. Recovery rolls the system forward from redo logs.

## Evaluation

The authors implement `14 K` lines of C++, run on a five-machine `100 Gbps` RDMA cluster, and compare directly against the open-source FORD and Motor systems on TPC-C, SmallBank, and a hot-record transactional YCSB variant.

The headline result is that CREST consistently leads under high skew. At 240 coordinators, it improves throughput over Motor by `1.92x` on TPC-C, `1.46x` on SmallBank, and `1.85x` on YCSB; over FORD the gains are even larger. On TPC-C, CREST reaches `743.7 KOPS`, `72.4%` above Motor's peak. Average latency also falls by `17.7-44.4%` relative to Motor and `41.1-62.6%` relative to FORD, which supports the claim that localized execution cuts blocking rather than merely shifting work elsewhere.

The factor analysis is especially persuasive. Under high skew, cell-level concurrency control alone raises throughput by `65.9%` on TPC-C and `46.6%` on YCSB, showing that false conflicts are real. Adding localized execution plus parallel commits then raises throughput by another `48.9-104.6%`, which matches the paper's second thesis about blocking time.

## Novelty & Impact

Relative to _Zhang et al. (TOS '23)_, CREST's main contribution is not another batched RDMA transaction path, but moving conflict detection from records to cells while keeping RDMA metadata costs controlled. Relative to _Zhang et al. (OSDI '24)_, it does not use MVCC to let readers bypass writers; instead, it targets false conflicts and long lock holding inside update-heavy workloads. Relative to _Li et al. (VLDB '24)_, it chooses fine-grained cell locking and early local visibility instead of page ownership.

That makes CREST useful to researchers and builders working on RDMA-backed disaggregated databases, especially when they expect hot keys and multi-attribute schemas.

## Limitations

CREST depends on several assumptions that narrow its deployment story. It targets stored procedures so the system can know accessed columns and determine which records will be updated. Its record header can only aggregate a bounded number of cells; for tables wider than 20 cells, CREST collapses excess columns into a larger cell, which partially reintroduces false conflicts. Reverse-order conflicts across execution blocks are detected and aborted, not repaired. Cross-node conflicts also remain expensive, which is why YCSB tail latency under high skew stays close to the baselines. The epoch-number rollover defense relies on a conservative timing assumption, and localized execution adds cache-management overhead that can hurt in low-contention or read-heavy regimes.

## Related Work

- _Zhang et al. (TOS '23)_ — FORD batches lock and read operations for disaggregated memory, but keeps record-level conflicts and strict commit visibility that CREST targets directly.
- _Zhang et al. (OSDI '24)_ — Motor adds MVCC to reduce read-write interference, while CREST instead attacks false conflicts within multi-column records and shortens local blocking.
- _Li et al. (VLDB '24)_ — GaussDB uses page-level ownership for disaggregated database execution; CREST keeps data in shared memory and extracts finer concurrency at the cell level.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Fast and Synchronous Crash Consistency with Metadata Write-Once File System"
oneline: "WOFS writes one checksum-protected metadata package per file operation and rebuilds file-system objects from packages to get synchronous PM crash consistency near raw bandwidth."
authors:
  - "Yanqi Pan"
  - "Wen Xia"
  - "Yifeng Zhang"
  - "Xiangyu Zou"
  - "Hao Huang"
  - "Zhenhua Li"
  - "Chentao Wu"
affiliations:
  - "Harbin Institute of Technology, Shenzhen"
  - "Tsinghua University"
  - "Shanghai Jiao Tong University"
conference: osdi-2025
code_url: "https://github.com/WOFS-for-PM/"
tags:
  - filesystems
  - crash-consistency
  - persistent-memory
  - storage
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

WOFS replaces scattered PM metadata updates with one checksum-protected package per file operation. WOLVES reconstructs normal file-system objects from those packages and reaches 2.20-2.24 GiB/s sequential writes on Optane PM, or 97.3%-99.1% of raw bandwidth.

## Problem

PM makes synchronous durability cheap because a file system only needs to flush data to the PM interface and fence, so "durable on return" semantics become realistic again. But existing PM crash-consistency schemes still force many small, random, ordered metadata I/Os. PMFS duplicates metadata through journaling, NOVA appends log entries and tails and later pays GC, and soft-update-style designs preserve correctness by ordering writes across multiple objects. Across six workloads, PMFS, SplitFS, and NOVA spend 22.9%-76.5%, 63.8%-97.4%, and 11.3%-75.5% of total I/O time on metadata. The paper attributes that waste to PM flush-granularity amplification, ordering-induced stalls, and log-maintenance overhead. On the paper's machine, sequential writes use under half of the roughly 2.26 GiB/s PM bandwidth.

## Key Insight

The key claim is that crash consistency should be organized around one file operation, not around a set of preexisting metadata structures. WOFS therefore emits exactly one package containing the metadata for that operation, protects it with type, timestamp, magic number, and CRC32, and writes it once. Metadata-only operations become `JM|JC`; data operations remain `D -> JM|JC`. Recovery then checks package validity and causal dependencies instead of replaying scattered updates. A missing or corrupt package is discarded, and data blocks with no valid package reference are simply treated as free.

## Design

WOFS uses four atomic packages: 256-byte `create`, and 64-byte `write`, `attr`, and `unlink`. Complex operations such as rename are compound packages linked by forward pointers so recovery can verify that all pieces arrived. Because this package layout replaces conventional on-media metadata, WOFS adds a Package Translation Layer. PTL parses C-nodes, A-nodes, and W-nodes from packages and reconstructs the inode table, per-file data lists, and directory contents, so VFS still sees normal files and directories.

WOFS also rejects a log layout. Packages and data blocks are allocated across PM and reclaimed by causal invalidation: newer unlink, attr, truncate, or overwrite operations invalidate older packages. For recovery, WOFS introduces coarse persistence: it allocates 4 KiB package groups and records group addresses in a bitmap, so recovery scans only marked groups rather than the entire device. WOLVES implements this in Linux 5.1.0 with per-core allocators and PTL shards, copy-on-write for overlapping writes, huge allocation for append-heavy writes, and 256-byte-stride read-ahead.

## Evaluation

On a 16-core Xeon Gold 5218 machine with 2x256 GiB Optane PM, the authors compare WOLVES against PMFS, NOVA, NOVA-RELAX, SplitFS, MadFS, EXT4-DAX, and XFS-DAX. Their crash test traces PM writes at instruction level, reorders writes between fences, injects 1,000 random crash points for three representative workloads, and always recovers the latest consistent pre-crash state. Performance-wise, WOLVES reaches 2.20-2.24 GiB/s sequential write throughput, or 97.3%-99.1% of raw PM bandwidth, and beats the baselines by 1.65x-9.44x on random writes. It leads the Filebench workloads and beats MadFS by 9.14x-61.4x in single-thread tests; on RocksDB it improves throughput by 1.20x-6.73x. Recovery is practical too: 2.61-3.99 s on common workloads, and about 21.6 s in a worst-case full 256 GiB PM image while scanning only about 10.9% of space.

## Novelty & Impact

Compared with PMFS, WOFS does not optimize journaling; it removes the "journal then in-place metadata update" pattern entirely. Compared with NOVA, it is not a faster log-structured design; it abandons log-structured metadata and immediate tail maintenance. Compared with SplitFS, the key step is not transactional checksum alone but redefining what gets persisted as a single object. Compared with SquirrelFS, it argues that even correct synchronous soft updates still leave too much PM bandwidth on the floor. The lasting contribution is therefore a new metadata model for byte-addressable storage: aggregate metadata by operation, then reconstruct abstractions in memory.

## Limitations

WOFS still depends on data-before-package ordering; the authors tried the idea of eliminating that with data checksums and report about 40.1% overhead for CRC32 and 32.3% for xxHash, so they leave full `D|JM|JC` to future work. Some wins are workload-sensitive: huge allocation helps sequential appends but not random writes, aging lowers throughput to 1.70-1.82 GiB/s for sequential writes and 1.31-1.44 GiB/s for random writes, and throughput drops once concurrency reaches nine or more threads because PM contention becomes the bottleneck. Recovery is fast but still scan-based, and WOLVES keeps a few MiB of PTL metadata resident even for closed files.

## Related Work

- _Dulloor et al. (EuroSys '14)_ - PMFS uses journaling for PM crash consistency, while WOFS collapses each operation's metadata into one checksummed package and avoids the later in-place metadata update phase.
- _Xu and Swanson (FAST '16)_ - NOVA appends separate log entries and tail updates and eventually pays GC costs; WOFS instead uses a non-log package layout with immediate reuse of invalidated space.
- _Kadekodi et al. (SOSP '19)_ - SplitFS accelerates journaling with transactional checksums, but it still maintains conventional metadata structures; WOFS changes the durable metadata unit itself.
- _LeBlanc et al. (OSDI '24)_ - SquirrelFS verifies synchronous soft updates in Rust, whereas WOFS argues that ordering-heavy metadata protocols still leave substantial PM bandwidth unused.

## My Notes

<!-- empty; left for the human reader -->

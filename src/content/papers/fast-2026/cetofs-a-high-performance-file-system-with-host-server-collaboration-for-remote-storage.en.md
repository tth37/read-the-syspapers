---
title: "CEtoFS: A High-Performance File System with Host-Server Collaboration for Remote Storage"
oneline: "CEtoFS moves the remote-SSD data path into userspace and offloads permission checks, concurrency control, and atomic-write logging to the storage server."
authors:
  - "Wenqing Jia"
  - "Dejun Jiang"
  - "Jin Xiong"
affiliations:
  - "State Key Lab of Processors, Institute of Computing Technology, Chinese Academy of Sciences"
  - "University of Chinese Academy of Sciences"
conference: fast-2026
category: cloud-and-distributed-storage
tags:
  - filesystems
  - storage
  - rdma
  - disaggregation
  - crash-consistency
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`CEtoFS` is a file system for disaggregated NVMe SSDs accessed over `NVMe-over-RDMA`. It keeps metadata management in the kernel, but moves the data path into userspace and lets the target storage server enforce per-block permissions, serialize conflicting requests, and execute redo logging for atomic writes. That split removes much of the initiator-side kernel overhead and turns network latency from a lock-serialization tax into work that overlaps at the target.

## Problem

The paper starts from a simple observation: disaggregated NVMe SSDs are no longer slow enough that the file-system software stack can hide behind device latency. With Optane-class SSDs and RDMA, both the network round trip and the SSD access itself are around single-digit microseconds, so the kernel stack becomes a first-order bottleneck. The authors measure Ext4 on remote Optane storage and show that the software stack accounts for about `65%` to `66%` of end-to-end read/write latency, with the `NVMe-over-RDMA` driver alone taking `36.1%` of a 4 KB write.

Remote storage also amplifies two problems that local file systems tolerate more easily. First, inode-level locking serializes concurrent accesses on the host, so each conflicting request waits through command transmission, SSD service, and completion notification; the network stretch makes that serialization far more expensive, and the paper shows remote write throughput can even fall as thread count rises. Second, conventional failure-atomic writes rely on journaling or copy-on-write. On remote media, both imply extra cross-network data movement: journaling writes log records remotely and later rereads them for checkpointing, while copy-on-write triggers repeated metadata updates. The target problem is therefore not just "support remote SSDs," but "build a file system whose control, permission, concurrency, and atomicity mechanisms respect microsecond-scale remote storage."

## Key Insight

The central claim is that once storage is disaggregated, the host should stop doing work whose correctness can be checked at the storage server. `CEtoFS` therefore splits the file system into a kernel control plane and a userspace data plane, then moves three latency-sensitive responsibilities to the target: permission checking, concurrency ordering, and redo-log-based atomic writes.

This works because those responsibilities only need narrow pieces of state. The kernel still owns authoritative metadata such as directory trees, extent mappings, and ACLs. But once a file is opened, the target can validate each data request using a reverse permission table indexed by block owner, can serialize only those request groups whose ordering matters, and can persist writes atomically by logging at the target instead of bouncing data back and forth over the network. In other words, `CEtoFS` treats the storage server as a trusted execution point for data-plane correctness, not just a passive NVMe target.

## Design

`CEtoFS` has three components. `K-FS` is an ordinary kernel file system, `Ext4` in the prototype, that continues to handle metadata operations such as `open`, `mkdir`, inode management, extent maps, and permission checks at file-open time. `U-Lib` is a userspace shim linked with applications; it intercepts file syscalls, serves `read` and `write` directly in userspace, and consults an in-memory extent tree to translate file offsets into device block addresses. When that cache misses, it asks `K-FS` for extent information via `fiemap` and fills the userspace table lazily. `T-Handler` is a userspace process on the target server that receives RDMA requests and talks to the SSD directly.

The data path is organized around a per-file request queue created when a file is opened. Each opened file gets two ring buffers in RDMA memory: `server_rb` for host-to-target requests and `host_rb` for target-to-host completions. `U-Lib` submits requests with `RDMA_WRITE_WITH_IMM`, embedding the request location so the target does not have to poll every queue. The design supports up to `64K` request queues in the prototype.

Permission checking is offloaded through a reverse permission table stored at block granularity. Metadata blocks and free blocks are owned by `K-FS`; data blocks are owned by the inode number of their file. On every request, `T-Handler` checks two conditions: whether the submitting queue belongs to the same file that owns the requested block, and whether the queue's read/write permission matches the operation type. This lets `CEtoFS` keep the fast data path in userspace without allowing arbitrary block accesses. Appends are handled in two stages: `K-FS` first allocates blocks with `fallocate`, then userspace writes into those blocks directly.

For concurrency, `CEtoFS` creates request groups at the initiator. The basic policy groups adjacent reads together and puts each write in its own group; those groups can be transmitted in parallel, while the target enforces inter-group ordering. The stronger "merging group" policy uses separate red-black trees for read and write ranges so non-conflicting adjacent groups can be merged, allowing disjoint parts of the same file to execute concurrently at the SSD. The target tracks group state with current group IDs, first-request tables, completed-request counts, and request-to-queue mappings so it can submit newly unblocked groups in order.

For failure-atomic I/O, `CEtoFS` exposes `atomic_write_start`, `atomic_write_commit`, and `atomic_write_abort`. The target performs redo logging: writes land first in a target-side log area, transaction metadata is persisted in a recovery table, and checkpointing to home locations runs in the background. Because the logging happens at the target, the host sends the data only once across the network.

## Evaluation

The prototype runs on two servers with dual 24-core Xeon Platinum 8260 CPUs, Mellanox ConnectX-5 RDMA NICs, and a target-side Intel Optane P4800X SSD. The baselines are `Ext4`, `F2FS`, and `uFS`, and the experiments use `O_DIRECT` to focus on the storage path rather than page cache effects.

Single-thread microbenchmarks show the basic userspace split is worthwhile. On reads, `CEtoFS` beats `Ext4` by `10%` to `1.12x` and `F2FS` by `9%` to `1.23x`, while staying close to `uFS`. A 4 KB random read takes about `19 us`, versus `42.34 us` for remote `Ext4`. On overwrites, `CEtoFS` improves throughput by about `74%` over `Ext4`, `65%` over `F2FS`, and `24%` over `uFS`; on appends the gains are `52%`, `50%`, and `12%`, respectively.

The stronger result is scalability under shared-file contention. In `FxMark`'s `DWOM` workload, where threads overwrite a shared file, the paper reports up to `19x` throughput improvement because `CEtoFS` avoids host-side reader-writer lock serialization and lets the target merge non-conflicting ranges. Macrobenchmarks tell a similar story: `Fileserver` improves by roughly `64%` to `75%` over the baselines, while metadata-heavy `Varmail` narrows the gap because `CEtoFS` must still interact with the kernel for metadata work. In `LevelDB`, write-sync latency drops by `57%` versus `Ext4` and `30%` versus `F2FS`. For atomic writes, target-side offloading outperforms initiator-side undo journaling by `1.8x` and redo journaling by `58%`. The evaluation supports the main claim, though it is mostly confined to one RDMA/Optane setup and direct-I/O workloads.

## Novelty & Impact

Compared with _ReFlex_ and related remote-storage work, `CEtoFS` is not trying to build a better block path alone; it asks what a file system should look like once the block path is already low-latency remote storage. Compared with local userspace file systems such as `uFS`, its novelty is the target-side collaboration model: permission checks, concurrency control, and redo logging move to the remote server because that is where the network penalty can be hidden or eliminated.

That makes the paper interesting to designers of disaggregated storage appliances, RDMA file systems, and kernel-bypass storage stacks. The contribution is mainly a new mechanism combination rather than a new abstract problem statement, but it is a useful one: it identifies exactly which file-system functions become pathological over remote NVMe and shows they can be re-partitioned cleanly.

## Limitations

The design assumes the target storage server is trusted and programmable. That is reasonable for vendor-controlled storage appliances, but it is a deployment assumption, not a universal property of remote storage. The prototype also relies on one request queue per opened file and currently supports `64K` queues; the paper suggests grouping files with identical permissions to scale further, but does not evaluate that path.

The best results come from data-heavy workloads with direct I/O. Metadata-intensive workloads such as `Varmail` benefit less because `K-FS` still owns metadata operations. The atomic-write mechanism also introduces a non-POSIX API, so applications must call explicit transaction boundaries to get the strongest guarantee. Finally, the experiments are limited to a single-initiator, single-target setup with one Optane SSD, so the paper leaves multi-target scaling, clustered coordination, and DPU deployment to future work.

## Related Work

- _Klimovic et al. (ASPLOS '17)_ — `ReFlex` gives remote flash a kernel-bypass data path, while `CEtoFS` builds a full file-system stack that additionally offloads permissions, concurrency, and atomicity decisions to the target.
- _Kadekodi et al. (SOSP '19)_ — `SplitFS` also separates control and data paths, but it targets persistent memory and uses page-table-based permission enforcement rather than remote block ownership checks.
- _Liu et al. (SOSP '21)_ — `uFS` is a high-performance userspace file system for local SSDs; `CEtoFS` adapts the userspace idea to disaggregated NVMe and pays special attention to network-amplified serialization.
- _Ren et al. (OSDI '20)_ — `CrossFS` improves scalable file access on fast local storage, whereas `CEtoFS` uses request grouping and target-side ordering to preserve correctness under remote-access latency.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Lockify: Understanding Linux Distributed Lock Management Overheads in Shared Storage"
oneline: "Lockify lets creators of new files and directories declare themselves the initial lock owner and confirm ownership asynchronously, removing DLM lookups from the create path."
authors:
  - "Taeyoung Park"
  - "Yunjae Jo"
  - "Daegyu Han"
  - "Beomseok Nam"
  - "Jaehyun Hwang"
affiliations:
  - "Sungkyunkwan University"
conference: fast-2026
category: os-and-io-paths
code_url: "https://github.com/skku-syslab/lockify"
tags:
  - filesystems
  - kernel
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`Lockify` is a Linux-kernel distributed lock manager for shared-disk file systems that removes a round trip from the create path for new files and directories. Because a newly created object has no existing owner, the creator can claim ownership immediately and let directory-node bookkeeping finish asynchronously, yielding up to `6.4x` higher throughput than the vanilla kernel DLM.

## Problem

The paper studies shared-disk file systems such as `GFS2` and `OCFS2`, which use a distributed lock manager (`DLM`) so multiple clients can share one block device safely. Target deployments are often low-contention: prior work cited by the paper says `76.1%` to `97.1%` of files are rarely touched by more than one client, and HA setups often have one active node plus idle backups.

Even so, create-heavy metadata paths scale badly. With one active client and up to five mounted clients, reads and writes stay stable, but file and directory creation drops sharply; in `GFS2`, the 5-client case loses up to `86%` throughput versus one client. The bottleneck is remote owner discovery: before locking a new object, the requester hashes to a directory node, asks who owns the lock, and waits for the reply. `OCFS2` shows the same pattern, and `O2CB` is worse because it may query all clients.

## Key Insight

Creation is different from access to an existing object. If a file already exists, the DLM must discover the current owner. If a file or directory does not exist yet, there is no previous owner to find. The synchronous owner-discovery round trip on the create path is therefore unnecessary work.

Lockify's proposition is that correctness only requires the directory node to eventually record the creator as owner; the creator does not need to block until that bookkeeping completes. By declaring self-ownership immediately and reconciling metadata asynchronously, Lockify turns create-time lock acquisition back into a local fast path.

## Design

Lockify adds three pieces to the kernel DLM. `dlm_lock(..., NOTIFY)` lets the file system mark requests that create new objects. For those requests, the local node sends a self-owner notification to the directory node, inserts a wait-list entry, and acquires the lock locally without waiting. The directory node updates its lock-owner table and later confirms the notification.

If confirmation times out or recovery reassigns directory nodes, pending notifications are resent from the wait-list. Existing-object operations keep the standard path. For concurrent creates under one parent, Lockify still requires the parent directory lock, but overlaps the ownership update with the create operation and releases the parent only after both complete. The prototype is implemented in Linux `6.6.23` with small `GFS2` and `OCFS2` changes.

## Evaluation

The evaluation uses five servers with dual `Xeon Gold 5115` CPUs, `64 GB` RAM, local NVMe SSDs, and `56 Gbps` links. Shared storage is exported over `NVMe-over-TCP`. The main metadata microbenchmark is `mdtest`, which creates `35,000` files and directories.

The strongest result is the low-contention case. With five clients mounted but only one active, Lockify improves throughput by about `2.9x` on `OCFS2` and `6.4x` on `GFS2` relative to the vanilla kernel DLM. On `GFS2`, DLM overhead rises from `4.4%` of end-to-end latency in the 1-client bound to `46.7%` in the standard 5-client case, then falls to `8%` with Lockify. That strongly supports the claim that remote owner discovery, not local create logic, is the main bottleneck.

The gains are smaller when existing-object contention dominates. In a 5-client high-contention workload where all clients create children under the same parent directory, `OCFS2` improves by only `1.09x` to `1.11x` because the parent-directory lock remains the bottleneck. `GFS2` still improves by `5.2x` and `5.4x` because its own request queueing reduces that parent-lock pressure.

Real workloads follow the same pattern: `Postmark` improves by `1.7x` on `OCFS2` and `2.0x` on `GFS2`, `Filebench` fileserver by `1.07x` to `1.14x`, and `webproxy` by `1.08x` on `OCFS2` versus `2.5x` on `GFS2`. The paper also reports unchanged `xfstests` pass counts (`70/75` for `GFS2`, `67/75` for `OCFS2`). An indirect RDMA comparison reaches `87%` to `88%` of an emulated RDMA DLM, though that is only a rough upper bound because no actual RDMA kernel DLM is implemented.

## Novelty & Impact

Compared with `SeqDLM` and `Citron`, Lockify is much narrower: it neither redesigns lock management for all workloads nor relies on RDMA. Its novelty is a deployable mechanism inside existing Linux shared-disk stacks: self-owner notification plus asynchronous ownership reconciliation for new-object creation.

The paper also sharpens the diagnosis of a low-contention bottleneck that conventional DLM discussions often miss.

## Limitations

Lockify only helps when the system is creating a lock object with no previous owner. It does not accelerate operations on existing files, and it does not remove serialization on a contended parent-directory lock. The weak `OCFS2` gains under high contention make that boundary explicit.

The design also introduces asynchronous protocol state: wait-lists, timeouts, retransmissions, and recovery-time resends. The `xfstests` results are encouraging, but they are not a full proof that every corner case is benign. The evaluation is also narrow: most of the biggest wins come from 5-node, one-active-client metadata workloads, and the RDMA result is emulated rather than measured against a real RDMA DLM.

## Related Work

- _Chen et al. (SC '22)_ — `SeqDLM` targets high-contention shared-file access in parallel file systems, whereas Lockify removes owner-discovery latency for new-object creation in shared-disk file systems.
- _Gao et al. (FAST '23)_ — `Citron` uses one-sided RDMA for distributed range locks, while Lockify works over ordinary TCP and focuses on metadata creation.
- _Yoon et al. (SIGMOD '18)_ — this RDMA-based decentralized DLM is more general; Lockify is narrower but easier to integrate into existing kernel DLM stacks.

## My Notes

<!-- empty; left for the human reader -->

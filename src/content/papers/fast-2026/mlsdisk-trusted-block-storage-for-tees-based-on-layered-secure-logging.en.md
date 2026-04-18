---
title: "MlsDisk: Trusted Block Storage for TEEs Based on Layered Secure Logging"
oneline: "MlsDisk replaces SGX-PFS's disk-wide Merkle-tree updates with layered secure logging, turning random secure overwrites into sequential appends while preserving CIFC."
authors:
  - "Erci Xu"
  - "Xinyi Yu"
  - "Lujia Yin"
  - "Xinyuan Luo"
  - "Shaowei Song"
  - "Qingsong Chen"
  - "Shoumeng Yan"
  - "Jiwu Shu"
  - "Hongliang Tian"
  - "Yiming Zhang"
affiliations:
  - "SJTU"
  - "Ant Group"
  - "NICE Lab, XMU"
  - "THU"
conference: fast-2026
category: reliability-and-integrity
code_url: "http://github.com/asterinas/mlsdisk"
tags:
  - storage
  - confidential-computing
  - security
  - crash-consistency
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`MlsDisk` is a secure virtual disk for `TEEs` that replaces SGX-PFS's whole-disk Merkle-tree update path with a four-layer log-structured design. The key move is to keep user data, indexes, logs, and journal metadata in separate secure abstractions so that only small metadata structures pay Merkle-tree costs. That preserves confidentiality, integrity, freshness, and consistency (`CIFC`) while improving write-heavy performance by `7.3x-21.1x` over `PfsDisk` and trace-driven performance by `1.4x-3.6x`.

## Problem

TEEs protect memory, not the host disk underneath them. A practical TEE deployment still needs a trusted block device so unmodified file systems, databases, and other applications can persist data without exposing it to a malicious host. The security target in this paper is stronger than plain encryption: the disk must resist snooping, tampering, rollback of individual blocks, and crash-induced inconsistency, which the paper groups as `CIFC`.

The problem is that the state-of-the-art `SGX-PFS` gets those guarantees through a Merkle Hash Tree over in-place data, and every overwrite triggers a cascade of updates from the changed leaf back to the root. For a tree of height `H`, the paper argues that a single write can cost `H` extra updates, or about `2H` once the recovery journal is included. That design makes secure storage behave like a metadata-heavy random-write workload. Their motivating experiments show that `CryptDisk`, which only provides confidentiality and integrity, already runs about `4.1x` faster than `SGX-PFS` on a trace-driven benchmark and `2.5x` faster on 4 KiB random writes.

An append-only log looks like an obvious escape hatch because it converts overwrites into sequential writes and naturally retains old versions for recovery. But the paper's `NaiveLog` strawman shows why that is not enough: without an index, reads require backward scans through the entire history, and without garbage collection, space usage is unbounded. Reusing a mature storage engine is also unsatisfying because correctness and security arguments become tangled. The paper therefore asks a narrower but more useful question: can a secure virtual disk keep the performance upside of logging without giving up formal control over freshness and crash consistency?

## Key Insight

The paper's central proposition is that secure logging becomes manageable once storage responsibilities are separated by layer rather than forced into one monolithic on-disk format. `MlsDisk` does not try to protect user blocks, indexes, file metadata, and journal state with one universal mechanism. Instead, each layer secures its own payload and delegates persistence of its metadata to the layer below, which already offers `CIFC`-compliant storage.

That decomposition changes the cost structure. User blocks at the top layer can be written out-of-place in large sequential batches because their encryption keys, MACs, and physical addresses live in an index rather than in a disk-wide Merkle tree. The index itself can use an `LSM-tree` because its WALs and `SSTables` are stored as transactional secure logs. Only those relatively small logs carry Merkle-tree overhead, and the tiny root metadata for those logs is pushed one level lower into a journal optimized for append and recovery. The memorable takeaway is that `CIFC` is preserved by composition: a layer is secure because its metadata is secured below it, not because every byte on disk participates in the same update chain.

## Design

`MlsDisk` has four layers. `L3` is the block I/O layer exposed to the application. It batches 4 KiB logical blocks, allocates fresh contiguous host block addresses (`HBAs`), encrypts each block with a fresh key, computes its `AES-GCM` MAC, writes ciphertext sequentially, and records each mapping as `LBA -> (HBA, key, MAC)`. Those mappings live in the `Logical Block Table`, while a `Reverse Index Table` tracks `HBA -> LBA` for garbage collection. A `Block Validity Table` records whether each physical block is free, used, or invalid.

`L2` implements that index as a transactional `LSM-tree` called `TxKV`. Every insert first goes to a `WAL`, then to a `MemTable`, and later becomes an `SSTable`. Crucially, flushes and compactions are not ad hoc background work: they execute as transactions through the layer below so index evolution stays crash-consistent. `L1` provides that lower abstraction, `TxLogStore`, which manages append-only secure logs with transactional create, append, read, delete, and commit. Each `TxLog` protects its content with a Merkle tree, but the corresponding metadata lives in an in-memory `TxLogTable`.

`L0` secures that table through `EditJournal`, which combines `CryptoChain` for append-only edits and `CryptoBlob` for periodic authenticated snapshots. This is where the paper deliberately keeps a chained structure similar to `NaiveLog`, but only for a few megabytes of metadata rather than for all user data. Recovery proceeds bottom-up: restore the latest valid `L0` snapshot and replay later edits, rebuild `L1` logs to valid lengths, reconstruct `L2` from `WALs` and `SSTables`, then expose a consistent `L3` index. Garbage collection operates at 16 MiB segment granularity and stays safe because updates to the logical index, reverse index, validity bitmap, and allocation logs commit as one transaction; stale data is reclaimed only after the metadata commit succeeds. The paper further improves the hot path with delayed reclamation, which piggybacks old-block cleanup on `LSM` compaction, and with two-level caching so Merkle nodes do not compete with user data.

## Evaluation

The evaluation uses an Intel SGX machine and an AMD SEV machine, both with `100 GB` user-visible virtual disks and `1.5 GB` of cache. `MlsDisk` is compared with `CryptDisk` and `PfsDisk`, and it reserves about `2%` extra metadata space plus another `10%` as over-provisioned space for delayed reclamation. That setup is fair to the paper's goal: it compares against the main secure virtual-disk design points, not against unrelated user-space file systems.

The headline numbers support the main claim. In `FIO`, `MlsDisk` beats `PfsDisk` by `7.3x-21.1x` on writes and `1.4x-2.4x` on reads. Against `CryptDisk`, it is specifically strong on random writes, with `1.1x-8.9x` speedups in SGX and `1.1x-6.8x` in SEV, while paying only modest overheads on sequential writes and reads. On five trace-driven datacenter workloads, it outperforms `PfsDisk` by `1.4x-3.6x` and exceeds `CryptDisk` by about `2.5x` on the write-dominant `wdev` trace. Filebench results show another `1.4x-2.3x` over `PfsDisk`, and the database study is appropriately nuanced: `BoltDB` improves by `4.2x-5.5x`, `PostgreSQL` by `1.3x-4x`, while `SQLite` and `RocksDB` stay roughly comparable because their own write paths are already log-structured.

The sensitivity studies make the mechanism believable rather than merely fast in one regime. As the disk fills, write amplification rises only from `1.025` to `1.115`, and `MlsDisk` still beats `CryptDisk` by `8.2x` in the nearly full case. Cleaning matters because contiguous free space eventually disappears without it, and the optimizations are measurable: delayed reclamation adds `31%` throughput on 4 KiB random writes, and two-level caching adds `18%` on random reads. The main caveat is that the evaluation disables the optional extensions in Section 8, so the reported system is strong on baseline `CIFC` but not yet demonstrating the paper's proposed defenses for entire-disk rollback or eviction attacks.

## Novelty & Impact

The novelty is not just "use a log in secure storage." The contribution is a compositional storage architecture that makes the security argument tractable while still exploiting the usual benefits of log structuring. Compared with `SGX-PFS` and `SecureFS`, `MlsDisk` shifts the main secure data path away from global in-place Merkle maintenance. Compared with secure `LSM` efforts such as `Speicher`, it does not retrofit one large storage engine and hope the interactions work out; it deliberately places each mechanism at the layer where its invariants are simplest.

That makes the paper interesting to both confidential-computing researchers and storage-system builders. Anyone designing persistent services over `SGX`, `SEV`, or similar TEEs can cite it as evidence that secure virtual disks do not have to choose between strong rollback protection and useful throughput. More broadly, it argues that layered composition is not just a proof trick: it is a performance technique for reducing where expensive cryptographic metadata maintenance actually happens.

## Limitations

`MlsDisk` is still best suited to workloads where secure random overwrites dominate. Its margin over `CryptDisk` shrinks on sequential workloads, and databases such as `SQLite` and `RocksDB` that already convert writes into logs see little improvement. The design also depends on operational slack: the paper explicitly reserves another `10%` of disk space for delayed reclamation, and cleaning becomes necessary once contiguous free space is exhausted.

There are also security and concurrency limits. The base evaluation does not enable the paper's extensions for irreversibility and sync atomicity, so whole-disk rollback and eviction attacks are addressed as future-facing add-ons rather than fully demonstrated properties of the measured system. `TxLogStore` likewise does not provide full general-purpose isolation; instead it reduces conflict probability through restricted write sharing, lazy deletion, and random log IDs. Those choices are reasonable, but they mean the design is specialized rather than a drop-in secure replacement for any transactional storage stack.

## Related Work

- _Kumar and Sarangi (RAID '21)_ — `SecureFS` adds freshness on top of a `CryptDisk`-style design, but it still relies on in-place metadata management rather than `MlsDisk`'s layered log-structured composition.
- _Bailleu et al. (FAST '19)_ — `SPEICHER` secures an `LSM` key-value store inside `SGX`, whereas `MlsDisk` uses custom layered primitives to provide a transparent secure block device with explicit cross-layer recovery.
- _Angel et al. (OSDI '23)_ — `Nimble` supplies rollback-resistant trusted storage, which `MlsDisk` can build on for irreversibility, but `MlsDisk`'s core contribution is the `CIFC` virtual-disk architecture itself.
- _Tian et al. (FAST '25)_ — `AtomicDisk` focuses on eviction attacks and sync atomicity for TEE storage, while `MlsDisk` centers on layered secure logging and treats sync atomicity as an extension.

## My Notes

<!-- empty; left for the human reader -->

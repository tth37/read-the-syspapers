---
title: "Advancing Data Integrity in Linux"
oneline: "Extends Linux PI support with flexible placement, an io_uring metadata path, and filesystem-managed PI that shrinks BTRFS checksum overhead and gives XFS data checksums."
authors:
  - "Anuj Gupta"
  - "Christoph Hellwig"
  - "Kanchan Joshi"
  - "Vikash Kumar"
  - "Javier González"
  - "Roshan R Nair"
  - "Jinyoung CHOI"
affiliations:
  - "Samsung Semiconductor"
  - "EPFL"
conference: fast-2026
category: reliability-and-integrity
tags:
  - storage
  - filesystems
  - kernel
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Linux already had PI-capable drives and a block-layer integrity framework, but not a complete end-to-end path. This paper adds flexible PI placement, an `io_uring` interface for data plus protection metadata, and `FS-PI`, which lets `BTRFS` replace checksum trees and lets `XFS` add data checksums with modest overhead.

## Problem

Device ECC protects media, not the whole host software path. Corruption can still occur in memory, between kernel layers, or during software transformations before a request reaches the drive. End-to-end data protection addresses that by carrying per-block protection information, including checksums and tags, alongside the data itself.

Linux still had three practical holes. Block-integrity assumed PI sat at the beginning of each metadata tuple, which excluded valid NVMe layouts where PI appears at another offset. Linux also lacked a normal read/write interface that could move data and protection metadata together, so user-space databases and storage stacks could not use PI without private out-of-tree code. Finally, integrity policy stopped at the block layer instead of at the filesystem, where data layout and visibility are decided. That left `BTRFS` paying checksum-tree overhead and `XFS` without data checksums at all.

## Key Insight

The core claim is that PI becomes much more valuable once the filesystem owns it. If Linux can carry protection metadata from user space to the device, and if the filesystem generates and verifies that metadata where it maps, caches, writes back, and exposes file data, then PI stops being a narrow block-layer feature and becomes an end-to-end integrity mechanism.

That also makes `Type 0` PI useful: the reserved per-block metadata bytes still travel with the block, so the filesystem can store its own policy there, such as `CRC32c`, instead of maintaining a checksum tree.

## Design

The implementation has three layers. First, block-integrity gains a `pi_offset` so drivers can tell Linux where PI lives inside each metadata tuple; the same helpers then work whether PI appears at the beginning or end. The paper says this was upstreamed in Linux `6.9`.

Second, the paper extends existing `io_uring` read/write requests with an attribute pointer to `io_uring_attr_pi`, which carries a metadata-buffer address, length, application tag, integrity-check flags, and reftag seed. The block layer is taught to accept user-generated PI, remap reftags, and split metadata correctly when bios split. The authors also add a capability-query `ioctl`. This path is direct-I/O only; buffered I/O is excluded because page cache, byte-granular writes, and `mmap` stores would make PI coherence much harder.

Third, `FS-PI` moves PI generation and verification into the filesystem. `BTRFS` gets a `dev_pi` mount option that replaces checksum-tree updates with per-I/O PI generation and verification; in `Type 0`, it stores `CRC32c` in the PI bytes instead of in a separate tree. `XFS` gets an `IOMAP_F_INTEGRITY` flag so the generic `iomap` layer allocates PI buffers and invokes shared helpers across direct and buffered I/O paths. A new `REQ_NOINTEGRITY` flag lets metadata I/O that already has strong filesystem-level protection skip redundant integrity work.

## Evaluation

The evaluation runs on Linux `6.15` on a Ryzen `9 5900X` with `16 GB` RAM and a `1.88 TB` Samsung `PM9D3` SSD. For `BTRFS`, the results strongly support the main claim. On direct random writes, `FS-PI` cuts host writes from `813.66 GiB` to `391.14 GiB`, NAND writes from `839.91 GiB` to `403.76 GiB`, and FS write amplification from `3.39` to `1.62`. Buffered random writes also improve. Filebench is mostly flat except for `varmail`, which improves about `13%` (`83K` to `94K` ops/s). For rate-matched direct random writes, idle CPU rises from about `12%` to about `70%`. In the endurance experiment, estimated `DWPD` falls from `27.33` to `22.15`, corresponding to about `23%` longer SSD lifetime.

The `XFS` story is different: the win is new functionality, not higher throughput. Direct I/O overhead is small, with random writes down about `4%`, sequential writes about `1-2%`, and reads close to baseline. Buffered sequential writes are the main weak point at roughly `20%` overhead. Still, Filebench results are essentially unchanged, so the evidence suggests that `XFS` can gain data checksumming at acceptable cost.

## Novelty & Impact

The novelty is that the paper connects three layers that Linux previously treated separately: device PI layout, user-space read/write interfaces, and filesystem integrity policy. Compared with raw NVMe passthrough or `SPDK`, this is a protocol-independent path that fits normal Linux I/O. Compared with `BTRFS` checksum trees, it keeps integrity metadata with each block instead of in extra metadata structures. Compared with historical `XFS`, it offers a realistic route to data checksumming without a new on-disk format.

## Limitations

The approach is not universal. The new user-space PI path supports only direct I/O, and the whole design depends on PI-capable devices and compatible device formats. `FS-PI` also protects data blocks, not all metadata, and in `BTRFS` the paper leaves redundant-profile repair to future work; in the evaluated single-profile mode, a PI mismatch simply becomes an I/O error. Finally, the evaluation uses one hardware setup and shows that buffered write-heavy `XFS` paths can still pay a noticeable penalty.

## Related Work

- _Bairavasundaram et al. (FAST '08)_ — showed that data corruption appears throughout the storage stack in practice; this paper turns that diagnosis into Linux mechanisms for catching more of those failures end to end.
- _Joshi et al. (FAST '24)_ — upstreamed flexible `io_uring` passthrough for storage devices, while this paper adds protocol-independent PI exchange to ordinary read/write I/O.
- _Rodeh et al. (TOS '13)_ — `BTRFS` uses out-of-place checksum metadata and pays recursive-update costs; `FS-PI` keeps per-block integrity information with the block and removes the checksum tree from the data path.

## My Notes

<!-- empty; left for the human reader -->

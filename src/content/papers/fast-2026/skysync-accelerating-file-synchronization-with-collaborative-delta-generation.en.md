---
title: "SkySync: Accelerating File Synchronization with Collaborative Delta Generation"
oneline: "SkySync reuses storage-layer checksums and combines them algebraically so rsync- and dsync-style sync spend less CPU on delta generation without sending more data."
authors:
  - "Zhihao Zhang"
  - "Huiba Li"
  - "Lu Tang"
  - "Guangtao Xue"
  - "Jiwu Shu"
  - "Yiming Zhang"
affiliations:
  - "NICE Lab, XMU"
  - "SJTU"
  - "Alibaba Cloud"
  - "Tsinghua University"
conference: fast-2026
category: cloud-and-distributed-storage
code_url: "https://github.com/skysync-project/skysync"
tags:
  - storage
  - filesystems
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`SkySync` accelerates `rsync`-style and `dsync`-style file synchronization by reusing checksums the storage stack already computed for integrity, deduplication, or management. Its two key moves are algebraic checksum combination and a flatter hash-based search structure, which cut delta-generation CPU work enough to improve end-to-end sync by about `1.1x-2x` without materially changing network traffic.

## Problem

As cloud storage and "Sky computing" spread across regions and providers, moving whole files across WANs is wasteful; delta sync is the natural answer. The problem is that existing delta sync spends much of its time not on sending data but on discovering which bytes changed. In `rsync`, the server chunks the old file and computes `Adler32` plus `MD5`, then the client slides a KB-sized window byte by byte across the new file, recalculating weak checksums and probing a hash table until it finds matches. In `dsync`, CDC reduces some redundancy, but both sides still compute weak checksums across all file bytes and then run nontrivial matching.

The paper measures this overhead directly on inter-cloud-like VMs: client and server computation takes `71.2%-93.7%` of total sync time, and checksum calculation plus searching account for up to `95%`. Even with AVX-512 and SHA intrinsics, the amount of hashing is so large, and the access pattern so irregular, that hardware acceleration only modestly improves the overall picture. The obvious systems question is whether sync should keep recomputing metadata that the storage layer already maintains for integrity, deduplication, and verification.

## Key Insight

The central claim is that delta sync should treat storage metadata as part of the synchronization algorithm, not as a separate layer. Modern block devices, file systems, deduplication systems, and distributed storage services already keep per-block or per-chunk checksums and digests. If the sync protocol can negotiate chunk size and checksum type, those existing checksums can often be reused directly, or combined algebraically, to produce the weak and strong chunk identifiers needed for delta generation.

That changes the cost structure. Instead of recalculating checksums over all bytes and then searching through pointer-heavy hash tables, SkySync mostly reads existing metadata, computes checksums only for the boundary fragments that do not align cleanly, and searches using a flatter bucketed structure. The result is not a new sync semantic; it is a cheaper way to realize the old one.

## Design

`SkySync` has two variants. `SkySync-F` targets FSC-based sync and plugs into the `rsync` workflow. `SkySync-C` targets CDC-based sync and plugs into `dsync`. The architecture is deliberately conservative: client and server still exchange checksum lists, matching tokens, and literal bytes, but the checksum-calculation and chunk-searching modules now collaborate with the storage layer.

For FSC, the simplest case is direct reuse: if the storage layer already exposes fixed-size chunk checksums, SkySync can use them as the server's checksum list. For CDC, the paper's main technical move is checksum combination. Suppose the storage layer exposes `4 KB` `CRC32C` values but CDC produces variable-sized chunks. SkySync derives the variable-chunk checksum by combining the checksums of overlapping fixed chunks with XOR and "append zeros" operations, computing fresh CRC only for the misaligned boundary bytes. The paper argues that these differing bytes are typically less than half of the average chunk size, so the expensive part of weak-checksum generation mostly disappears. The same framework generalizes to other polynomial checksums with similar algebraic structure.

The second design piece is chunk search. Instead of `rsync`'s traversal from a `16-bit` hash index to `32-bit` weak checksums and then to strong checksums, SkySync uses a flat array of preallocated buckets and a streamlined Cuckoo-hashing scheme. It derives the two candidate buckets directly from the chunk's existing `CRC32C` value, stores either weak-only or weak-plus-strong entries depending on the sync mode, and keeps four entries per bucket. This reduces pointer chasing, lowers collision costs, and makes the search path more CPU-friendly.

Because client and server may sit atop different storage stacks, SkySync also adds protocol negotiation. In FSC mode the client aligns to the server's chunk size because the server sends the checksum list first; in CDC mode the server aligns to the client's chunking policy. For checksum type, SkySync prefers `CRC32C` as the weak checksum when either side provides it, and adopts the server's cryptographic hash type as the strong checksum to avoid extra recomputation. The paper implements these ideas with HTTP(S) messaging, roughly `1100` lines of C++ on top of `librsync` for `SkySync-F`, and about `1600` additional lines on top of the authors' `dsync` reimplementation for `SkySync-C`.

## Evaluation

The evaluation is thorough and mostly fair. The authors compare against `rsync` and `dsync` on two Alibaba Cloud VMs in separate data centers, using the same multithreading policy across systems, plus both software-only and hardware-accelerated variants. That setup is well matched to the paper's claim that inter-cloud sync is computation-bound before it is bandwidth-bound.

On microbenchmarks, the client-side results show the expected split. `SkySync-F` is `1.2x-2.0x` faster than `rsync`, cutting client computation by `32.1%-64.9%`; `SkySync-C` is `1.3x-1.7x` faster than `dsync`, cutting `25.7%-42.3%`. On the server side, where SkySync largely reads metadata instead of recalculating and searching from scratch, the paper reports up to `89.3%` computational-overhead reduction versus the baselines. Breakdown figures strengthen the causal claim: compared with `rsync`, `SkySync-F` reduces checksum-calculation time by `23.4%-88.3%` and chunk-search time by up to `61.3%`; compared with `dsync`, `SkySync-C` reduces checksum time by `24.5%-33.6%` and chunk-search time by `65.7%`.

The real-world datasets matter more. Across chat logs, Ubuntu images, snapshots, Wikipedia dumps, and Linux kernel trees, SkySync improves sync performance by about `1.2x-1.5x` and cuts combined client/server sync time by `19.2%-43.7%`. Just as importantly, the network story does not undermine the result: sync traffic remains close to `rsync` and `dsync`, with only slight growth from carrying additional strong-checksum bits. Metadata extraction is also cheap enough not to erase the win, ranging from `1.8` to `119.2` seconds and accounting for only `0.11%-7.14%` of total SkySync time on `BTRFS`. The main limitation of the evaluation is scope, not consistency: most experiments run on `BTRFS`-backed cloud VMs, so the cross-storage generality is argued more than exhaustively validated.

## Novelty & Impact

The paper's novelty is not a new delta-sync semantic or a new chunking rule. It is the decision to move delta generation across the storage boundary and exploit metadata that already exists for unrelated reasons. Relative to `dsync`, `WebR2sync+`, `PandaSync`, and similar systems, SkySync attacks the dominant checksum-generation and search costs rather than only shifting work between client and server or changing when delta sync is chosen.

That is a useful systems contribution because the optimization surface is broader than file sync itself. Any storage stack that already computes digests for integrity or deduplication becomes a better sync substrate almost for free, and the paper shows how to bridge heterogeneous chunk sizes and checksum types without rewriting the whole protocol. If this idea lands in production sync tools, the likely impact is lower CPU contention on cloud nodes rather than lower WAN bytes.

## Limitations

SkySync depends on the storage layer exposing usable metadata. When checksums are unavailable, poorly aligned, or expensive to retrieve, the system falls back toward conventional sync behavior. The paper acknowledges this indirectly through its three extraction paths: user-space tools require per-filesystem configuration, API-based extraction can pay remote metadata latency, and custom parsers create long-term maintenance burden.

The design also does not solve every sync bottleneck. It leaves chunking itself in place, keeps network traffic roughly unchanged, and helps most when computation dominates bandwidth. The evaluation supports that regime on `100-500 Mbps` WANs, but it does not show whether the same gains matter on much slower links or on storage systems whose metadata interfaces are weaker than `BTRFS` or `MeGA`. Finally, the implementation story for `SkySync-C` relies on the authors' own `dsync` reimplementation, so interoperability with other production CDC sync tools remains more of an argument than a deployment study.

## Related Work

- _Muthitacharoen et al. (SOSP '01)_ - `LBFS` established chunk-based low-bandwidth synchronization, while SkySync focuses on cutting the CPU cost of generating those deltas in modern cloud settings.
- _He et al. (MSST '20)_ - `dsync` simplifies CDC-based matching, but SkySync further avoids recalculating weak checksums across all bytes by reusing storage metadata.
- _Xiao et al. (FAST '18)_ - `WebR2sync+` pushes chunk search to the server and exploits locality, whereas SkySync reduces the need to compute and search so many fresh checksums in the first place.
- _Wu et al. (ICDCS '19)_ - `PandaSync` decides when to use full sync versus delta sync, while SkySync assumes delta sync is the right abstraction and makes its hot path cheaper.

## My Notes

<!-- empty; left for the human reader -->

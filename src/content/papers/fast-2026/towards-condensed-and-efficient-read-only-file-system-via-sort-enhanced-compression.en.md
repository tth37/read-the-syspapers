---
title: "Towards Condensed and Efficient Read-Only File System via Sort-Enhanced Compression"
oneline: "RubikFS sorts similar chunks and groups hot data before block compression, pushing read-only file-system images toward direct-compression density with less read amplification."
authors:
  - "Hao Huang"
  - "Yifeng Zhang"
  - "Yanqi Pan"
  - "Wen Xia"
  - "Xiangyu Zou"
  - "Darong Yang"
  - "Jubin Zhong"
  - "Hua Liao"
affiliations:
  - "Harbin Institute of Technology, Shenzhen"
  - "Huawei Technologies Co., Ltd"
conference: fast-2026
category: os-and-io-paths
tags:
  - filesystems
  - storage
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`RubikFS` is a read-only compressed file system that attacks the core weakness of block compression: similar bytes get split across blocks while unrelated bytes get packed together. It sorts fixed-size chunks by measured similarity before block formation, then groups hot chunks separately so large compressed blocks approach, and sometimes exceed, the density of direct compression without suffering the same level of read amplification as naive large-block layouts.

## Problem

The paper studies read-only images such as IoT kernels, embedded root filesystems, and container images, where image size directly affects hardware cost, pull latency, and deployment friction. Existing read-only compressed file systems like `Squashfs` and `EROFS` already compress data in blocks, but the authors show that simply increasing block size does not close the gap to direct compression. Even at `1 MB` blocks, both systems remain well below the compression ratio of compressing the whole image as one stream.

The reason is what the paper calls the data mixture problem. Dictionary compressors gain most when similar strings stay within the same search window. File-system block division does the opposite: it mixes dissimilar data inside one block and scatters similar data across different blocks. Larger blocks help somewhat, but they also worsen read amplification because a small access may force the system to fetch and decompress a much larger compressed block. Prior similarity-detection and sorting techniques from backup systems are also a bad fit: they focus on binary duplicate detection or coarse grouping, not on producing a layout that is both compression-friendly and efficient to read back through a file-system interface.

## Key Insight

The paper's central claim is that read-only file-system compression should not treat block boundaries as fixed and similarity as an afterthought. Instead, it should sort data before compression so that each compressed block becomes a cluster of similar chunks. That lets ordinary block compressors recover redundancy that was previously lost to the storage layout.

What makes this insight nontrivial is that a file system cannot sort arbitrarily. It still needs page-friendly reads, bounded metadata, predictable reconstruction of original files, and tolerable startup performance. `RubikFS` therefore combines similarity sorting with three constraints: use fixed-size chunks rather than fully content-defined chunking, separate hot and cold data so sorting does not explode read amplification, and generate chunk-level indexes that can recreate original files after the physical layout has been reordered.

## Design

`RubikFS` has four main pieces. First, a `data grouper` splits the image into coarse file-type groups such as `ELF Code`, `ELF Data`, `Binary`, `Text`, and `Others`. This reduces the search space because data from the same type are more likely to share redundancy. Second, a `data chunker` divides each group into fixed-size chunks, deduplicates exact duplicates, and keeps chunk size tied to block size with a `4 KB` floor so page locality is not destroyed. The paper deliberately chooses fixed-size chunking and full deduplication as the default because content-defined chunking and tail deduplication can create awkward unaligned reads.

Third, a `hotness grouper` uses an offline trace to split each type group into hot and cold subgroups. Hot data are defined as data touched during startup. This matters because similarity sorting alone preserves locality only within a chunk; once chunks are permuted by similarity, read amplification becomes hard to predict. Grouping startup-hot chunks together keeps the performance-critical working set compact even when the global layout has been reordered.

Fourth, a `similarity sorter` turns chunk ordering into a graph problem. `RubikFS` extracts many per-chunk features by sampling maximum `gear hash` values across the chunk, rather than using only a few super-features as prior backup-oriented schemes do. It then constructs a weighted similarity graph whose edge weights range from `0` to `1`, partitions that graph with `METIS` so each subgraph contains mutually similar chunks, and sorts both within and across subgraphs by similarity. The packed chunk stream is finally compressed with ordinary fixed-size blocks. To make the reordered layout readable, `RubikFS` stores chunk-level indexes containing original offset, packed offset, and chunk size; the paper reports only `0.018%` to `2.93%` storage overhead from this metadata. The implementation is built on `EROFS`, with a userspace image builder plus a kernel file system and about `3.5K` modified lines of code.

## Evaluation

The evaluation covers six open-source images, including embedded images and one container image, and three compressors: `LZ4`, `ZSTD`, and `LZMA`. The comparisons are against `EROFS`, `Squashfs`, and `Direct`, where `Direct` compresses the whole image without file-system block division. Across these settings, `RubikFS` consistently improves compression ratio over the two existing read-only file systems, with gains up to `42.60%`.

The most interesting result is that `RubikFS` sometimes beats `Direct`, especially on several embedded images. That is possible because direct compression is still limited by dictionary size; sorting can pull physically distant but semantically similar regions close enough that the compressor sees redundancy it would otherwise miss. The paper's breakdown also shows that exact deduplication alone is not enough: most of the improvement comes from the similarity sorter rather than from chunk deduplication by itself.

Performance results are narrower but still convincing for the target setting. On `openEuler` with `1 MB` blocks, grouping hot data cuts unnecessary reads by up to `70.70%` and reduces runtime by up to `65.03%` relative to the unsorted baselines. Build-time overhead from sorting is real, but it is offline, and the proposed grouping and graph optimizations reduce that extra build time by `21.97%` to `74.39%`.

## Novelty & Impact

Relative to `EROFS` and `Squashfs`, the novelty is not another tweak to block size, alignment, or metadata layout. `RubikFS` changes the unit of reasoning from "compress whatever lands in a block" to "shape blocks so they contain similar chunks." Relative to backup-oriented techniques such as `Finesse`, `Odess`, and `Palantir`, the paper argues that file systems need graded similarity values, similarity-aware ordering, and efficient online reconstruction, not just duplicate detection or yes/no similarity tests.

This makes the paper relevant for embedded Linux builders, mobile and IoT firmware pipelines, and potentially container-image tooling. The contribution is both a mechanism and a framing: similarity sorting becomes a first-class file-system design tool rather than a background storage optimization.

## Limitations

The design is tightly scoped to read-only images built offline. If the workload is mutable, highly dynamic, or multi-tenant, the paper offers no migration path. Even within the read-only setting, hotness grouping assumes a trace that is representative of startup behavior, which is realistic for embedded systems but weaker for general-purpose machines and unpredictable container workloads.

The evaluation is also strongest on embedded-style images and an emulated device setup. That is enough to support the paper's thesis, but it leaves open how much the results transfer to larger server images, different storage hardware, or access patterns dominated by post-startup random reads. The container-image case is notably less favorable to the `data grouper` because tar packages mix many data types. Finally, the build pipeline is more complex than ordinary `mkfs`: grouping, chunking, feature extraction, graph partitioning, and indexing all have to work correctly, so the system buys space savings with extra offline machinery.

## Related Work

- _Gao et al. (USENIX ATC '19)_ — `EROFS` is the direct baseline for compressed read-only file systems; `RubikFS` keeps the same deployment model but reorders data before block compression to attack data mixture.
- _Lin et al. (FAST '14)_ — `Migratory Compression` also reorders data to improve compressibility, but it targets backup storage and does not optimize for file-system read performance or transparent file reconstruction.
- _Zhang et al. (FAST '19)_ — `Finesse` extracts a few super-features for resemblance detection in post-dedup compression, whereas `RubikFS` needs richer similarity values to sort partially similar chunks, not just identify near duplicates.
- _Huang et al. (ASPLOS '24)_ — `Palantir` improves hierarchical similarity detection for delta compression, but `RubikFS` goes further by turning similarity into weighted graph partitioning and a file-system layout policy.

## My Notes

<!-- empty; left for the human reader -->

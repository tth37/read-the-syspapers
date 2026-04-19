---
title: "Solid State Drive Targeted Memory-Efficient Indexing for Universal I/O Patterns and Fragmentation Degrees"
oneline: "AppL turns arbitrary SSD writes into sorted append-only runs, then uses FP and PLR indices to hold L2P state at 6∼8 bits per entry despite poor locality and fragmentation."
authors:
  - "Junsu Im"
  - "Jeonggyun Kim"
  - "Seonggyun Oh"
  - "Jinhyung Koo"
  - "Juhyung Park"
  - "Hoon Sung Chwa"
  - "Sam H. Noh"
  - "Sungjin Lee"
affiliations:
  - "POSTECH"
  - "DGIST"
  - "Virginia Tech"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717478"
code_url: "https://github.com/dgist-datalab/AppL/"
tags:
  - storage
  - databases
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

AppL is an SSD FTL index that stops relying on workload locality. It writes updates through an `LSM-tree`, then uses `FP` in upper levels and `PLR` in lower levels so the logical-to-physical map stays compact even when I/O is random and the device is fragmented.

## Problem

Page mapping scales poorly because the L2P table grows linearly with capacity: the paper uses the usual estimate of `0.1%` of SSD size, or `16 GB` of DRAM for a `16 TB` device. DFTL, SFTL, and LeaFTL reduce that cost, but each depends on temporal reuse, spatial locality, or regular enough `<LBA, PSA>` pairs for learned approximation. Real SSD workloads often violate all three. In the paper's motivation study, giving SFTL and LeaFTL only `20%` of OFTL's DRAM makes their entry sizes grow to `24.9∼62.7` bits on fragmented Varmail and CacheLib, pushing read latency to `1.3∼6.9x` that of full-DRAM OFTL. The problem is therefore not just smaller metadata, but metadata whose compression ratio survives bad locality and fragmentation.

## Key Insight

AppL's core idea is to regularize the mapping before compressing it. Writes first flow through an `LSM-tree`, which turns arbitrary update order into runs that are sorted by LBA and laid out over physically consecutive sectors. Once each run has that monotone append-only structure, AppL can use approximate indices safely: `FP` in upper levels and `PLR` in lower ones. The approximation problem becomes much easier because the index is modeling already regularized runs, not raw fragmented placement.

## Design

AppL buffers writes in a memtable, flushes to `L0`, and compacts downward into sorted runs. Exact `<x_i, y_i>` pairs remain on flash in each run's metadata area, but DRAM holds only lightweight lookup structures. The key one is a shortcut table that maps each LBA directly to the owning run, so AppL avoids the multi-run search that would make a normal `LSM-tree` unusable for flash translation. In the paper's balanced `16 TB` design, `L0` uses an `RB-tree`, the upper level uses `FP`, and the lowest level uses `PLR`.

`FP` becomes compact because PSA is implicit inside a run: AppL stores the first exact LBA of each group, then only short fingerprints for later entries. With target approximation error `E_appx = 0.1`, the paper derives a `7`-bit fingerprint and `28`-entry groups, giving `7.89` bits per entry instead of naive FP's `40.3`. `PLR` becomes compact because AppL exploits flash geometry. Since one `16 KB` NAND page contains four `4 KB` host blocks, a prediction can be wrong within a four-sector window without causing extra flash reads. That widens `δ` from `0.55` to `2.2`, raising average entries per line segment to `25.76`, while quantization and delta encoding cut a segment description to `47.4` bits from the conventional `192`.

To bound write cost, the tree height is fixed and tuned rather than left to grow arbitrarily. The chosen point, `T = 14` and `|L0| = 84.7 GB`, needs `29.1%` of OFTL's DRAM budget at peak while keeping WAF around `3.0∼3.5`.

## Evaluation

The authors implement AppL on an FPGA-based SSD prototype with `256 GB` flash and compare it against OFTL, DFTL, SFTL, and LeaFTL. All non-OFTL designs receive the same `51.2 MB` DRAM budget, or `20%` of the full page-mapping requirement, plus the same `4 MB` write buffer.

The main result is that AppL's entry size stays small where the baselines expand. Across Filebench, TPC-C, YCSB-on-Redis, and CacheLib, AppL remains at `5.82∼6.3` bits per entry, so the full approximate index fits in `46.6∼50.4 MB`. On those workloads, it reduces read latency by `72.4%`, `62.7%`, and `33.6%` versus DFTL, SFTL, and LeaFTL on average, while improving throughput by `48.5%`, `28.4%`, and `83.4%`. RR/RW microbenchmarks show the same pattern: AppL cuts average latency by `33∼44%` and raises throughput by `10∼79%` because its entry size stays near `9.3` bits even when SFTL and LeaFTL grow to `32` and `62.7` bits.

The paper also measures the cost side honestly. If DRAM is too small even for the shortcut table, performance drops. And on faster SSDs the background compute becomes visible: sorting alone accounts for `28.4%∼51.7%` of compaction time, and on a simulated GEN4 SSD with only a `1.2 GHz` CPU, AppL can lose to DFTL and SFTL on random writes.

## Novelty & Impact

The novelty is the integration, not the ingredients. AppL combines `LSM-tree` regularization, shortcut-table lookup, FP with implicit PSA, and page-aware PLR relaxation into an FTL that keeps approximate indexing stable under the exact workloads that break prior locality-based schemes. The broader lesson is useful beyond SSDs: if a learned or approximate index struggles on messy input, redesigning the write path may matter more than designing a fancier model.

## Limitations

AppL buys robustness with background work. The chosen hierarchy still has WAF around `3.0∼3.5`, and update-heavy, high-utilization workloads trigger frequent compaction and last-level GC. It also needs nontrivial controller resources: the shortcut table alone consumes `15.6%` of OFTL's DRAM, and on faster SSDs the compaction compute becomes a real bottleneck. The authors explicitly leave parallel sorting or hardware acceleration as future work.

## Related Work

- _Jiang et al. (MSST '11)_ - SFTL compresses mappings by exploiting spatial locality inside translation chunks, whereas AppL is built for the regime where fragmentation and random writes destroy that locality.
- _Zhou et al. (EuroSys '15)_ - TPFTL also tries to compact page mappings with page-level structure, but AppL instead rewrites the mapping path with an LSM-tree so regularity is created rather than merely detected.
- _Sun et al. (ASPLOS '23)_ - LeaFTL uses PLR for flash translation, while AppL moves learned approximation under an LSM-tree so the modeled runs are larger, more regular, and less sensitive to fragmentation.
- _Dayan et al. (SIGMOD '17)_ - Monkey optimizes LSM-tree memory allocation for navigational metadata, and AppL adapts that style of hierarchy tuning to a flash-translation setting with shortcut-table lookups and bounded WAF.

## My Notes

<!-- empty; left for the human reader -->

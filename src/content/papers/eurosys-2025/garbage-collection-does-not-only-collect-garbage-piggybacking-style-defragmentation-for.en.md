---
title: "Garbage Collection Does Not Only Collect Garbage: Piggybacking-Style Defragmentation for Deduplicated Backup Storage"
oneline: "GCCDF piggybacks ownership-aware chunk reordering onto mark-sweep GC, improving restore locality for deduplicated backups without extra migration or deduplication loss."
authors:
  - "Dingbang Liu"
  - "Xiangyu Zou"
  - "Tao Lu"
  - "Philip Shilane"
  - "Wen Xia"
  - "Wenxuan Huang"
  - "Yanqi Pan"
  - "Hao Huang"
affiliations:
  - "Harbin Institute of Technology, Shenzhen, China"
  - "DapuStor, Shenzhen, China"
  - "Dell Technologies, Boston, USA"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717493"
code_url: "https://github.com/Borelset/GCCDF"
tags:
  - storage
  - filesystems
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

GCCDF starts from a simple observation: mark-sweep garbage collection and deduplication-aware defragmentation both pay for the same expensive step, namely copying live chunks out of partially invalid containers. Instead of running a separate reordering pass or retaining extra duplicates, GCCDF reorders those live chunks during GC, grouping chunks by the set of backups that reference them. Across four backup datasets, it keeps the same deduplication ratio as naive deduplication while improving restore throughput by 2.1x-3.1x and often reducing GC write traffic as well.

## Problem

Deduplicated backup appliances save space by storing each unique chunk once and letting later backups point to it. That is good for capacity and bad for restore locality. A backup image that was logically sequential before deduplication turns into a recipe that jumps across many containers, so restoring it requires extra container reads and suffers read amplification. The paper reports that deduplicated backups can lose up to 80% of restore speed because of this fragmentation.

Existing fixes split into two unsatisfying camps. Rewriting schemes keep some duplicate chunks around so restore becomes more local again, but that spends away the very space savings that justified deduplication. In the paper's experiments, representative rewriting methods lose 11%-56% of deduplication ratio depending on dataset. Reordering schemes preserve deduplication ratio by copying chunks into a better layout, but they introduce a separate migration phase that may copy 50%-80% of the dataset and usually assume consecutive versions from the same source. On mixed-source workloads, the representative MFDedup baseline almost degenerates into non-dedup storage. The real problem is therefore not merely fragmentation, but fragmentation under three coupled constraints: preserve deduplication, avoid a second large migration pass, and work when backups share chunks across unrelated sources.

## Key Insight

The paper's main claim is that defragmentation should not be scheduled as an extra maintenance job at all. Deduplicated backup systems already run garbage collection periodically because immutable containers accumulate invalid chunks after old backups are deleted. GC's sweep stage must identify the valid chunks in reclaimable containers and copy them forward into new ones. GCCDF uses that unavoidable data movement as the place to repair layout.

That still leaves the harder question of what layout is globally good when chunks are shared by many backups. GCCDF answers with chunk ownership: the ownership of a chunk is the set of backups that reference it. If a container holds chunks with the same ownership, then any restore either needs all of them or none of them. That turns a per-backup layout problem into a compatibility problem across all backups. When ownership-sized groups do not align with fixed 4 MB containers, GCCDF mixes the groups whose ownerships are most similar, with a bias toward longer matching suffixes so recent backups get better locality.

## Design

GCCDF is inserted between the mark and sweep stages of mark-sweep GC. The mark stage already produces the valid-chunk table and can also emit an RRT table that maps GC-involved containers to the backups whose recipes reference them. GCCDF then runs three modules.

The Preprocessor first segments the containers that GC will touch, with a default segment size of 100 containers. Segmentation matters because reordering itself can suffer from scattered reads, and caching every to-be-migrated chunk at once would be too expensive. For each segment, the Preprocessor checks the valid-chunk table, loads only valid chunks into an in-memory GC cache, and gathers the subset of backup recipes involved in that segment.

The Analyzer then performs locality-promoting chunk clustering. Its job is to determine each chunk's ownership efficiently. Rather than scanning every recipe for every chunk, it builds Bloom filters for the involved backups and uses a binary tree to split chunk groups backup by backup: referenced chunks go right, unreferenced chunks go left. After all relevant backups are checked, each leaf node contains chunks with identical ownership. The implementation includes two practical controls the paper emphasizes: it checks backups in reverse chronological order so nearby leaves naturally favor recent backups, and it stops splitting very small leaves so clustering does not become more fragmented than the data it is trying to fix.

The Planner turns those ownership clusters into a migration order. Conceptually, the paper's container-adaptable packing chooses the next cluster whose ownership is most similar to the current one; ties are broken by the longest matching suffix in backup indices, because later backups are both more fragmented and live through more turnover cycles. In the implementation, left-to-right traversal of the Analyzer's leaf list approximates that order directly. The sweep stage then writes valid chunks from the GC cache into new containers according to this sequence. The result is that GC reclaims space and improves restore locality in the same pass.

## Evaluation

The prototype runs on an Intel Xeon Platinum 8468V server with 128 GB of memory, two Intel S4610 SSDs as RAID-0 backup storage, and an Intel P4610 SSD for source data. Chunking uses FastCDC with 1 KB minimum, 4 KB average, and 32 KB maximum chunk sizes; containers are 4 MB. The workloads are broad for this niche: WIKI (1.2 TB), CODE (394 GB), MIX (809 GB), and SYN (1.1 TB). The system always retains the 100 most recent backups, probabilistically deletes the earliest 20, runs GC, and restores the remaining backups.

The headline result is that GCCDF improves restore throughput over naive deduplication by 2.7x on WIKI, 3.1x on CODE, 2.1x on MIX, and 2.3x on SYN, while preserving the same deduplication ratio. The abstract's more deployment-facing comparison is against SMR: GCCDF achieves 2.1x faster restoration and avoids the deduplication loss that SMR incurs, reported up to 34.5% in typical scenarios. Against MFDedup, the paper reports a 6.45x higher deduplication ratio in typical scenarios because GCCDF still deduplicates mixed-source workloads instead of giving up on chunk sharing.

The fragmentation evidence is stronger than just throughput. GCCDF's average read-amplification factors are 1.3x on WIKI, 2.2x on CODE, 1.4x on MIX, and 3.6x on SYN, versus 5.9x, 4.3x, 3.4x, and 8.2x for SMR. The GC story is also important: after the initial round, GCCDF sharply reduces involved, reclaimed, and produced containers, and the paper says produced containers are almost one third of those in the other approaches. Its extra Analyze stage is a small fraction of total GC time, and the lower sweep-read and sweep-write costs usually more than pay for it. Sensitivity results also support the mechanism: smaller segments hurt defragmentation, and replacing the ownership-aware packing rule with random packing raises read amplification by about 20% on average.

Overall, the evaluation supports the paper's central thesis. The baselines are appropriate, the workloads include both same-source and mixed-source cases, and the paper measures both restore speed and GC overhead. The main caveat is that MFDedup is structurally mismatched to the mixed-source setting, so GCCDF's strongest comparison is really against rewriting schemes plus naive GC rather than against a fully general prior reordering design.

## Novelty & Impact

GCCDF's novelty is not only that it proposes another deduplication layout heuristic. The deeper contribution is a systems move: recognize that GC and defragmentation are paying for nearly identical data migration, then collapse them into one maintenance path. On top of that, the paper identifies chunk ownership as the right abstraction for locality that remains compatible across many backups, and shows how to reconcile that abstraction with fixed-size containers.

This should matter to people building deduplicated backup appliances, immutable-container stores, and GC-heavy storage systems. Future work may replace ownership inference, the binary-tree implementation, or the packing heuristic, but the paper has already shifted the framing. It makes restore locality a GC-time layout question rather than a separate post-processing problem, which is a reusable idea. I would classify it as a new mechanism built around a sharp reframing of where defragmentation cost should be paid.

## Limitations

GCCDF only reorders data that GC is already touching. If live but fragmented data sits in containers that are not yet on the GC list, the system cannot repair that layout immediately; it must wait until turnover makes those containers reclaimable. The paper argues that backup systems run GC frequently enough for this to be acceptable, but the design still couples defragmentation progress to retention churn.

The segmentation mechanism is also a real tradeoff, not a mere implementation detail. Small segments cap memory overhead, but the paper's own sensitivity study shows they miss useful cross-container grouping opportunities and create more read amplification. Large segments improve layout quality but increase GC-cache size and ownership-analysis complexity. More broadly, the evaluation is on one SSD-based prototype and four datasets. The paper does not quantify foreground backup-ingest interference while GCCDF runs, nor does it show whether the same gains hold under different container sizes, media mixes, or backup-retention policies.

## Related Work

- _Lillibridge et al. (FAST '13)_ - Capping-style rewriting improves restore locality by retaining selected duplicates, whereas GCCDF preserves deduplication ratio and repairs layout only while GC is already migrating valid chunks.
- _Douglis et al. (FAST '17)_ - This work explains the mechanics and cost structure of physical GC in deduplicated storage; GCCDF builds directly on that sweep-time migration path and repurposes it for defragmentation.
- _Zou et al. (FAST '21)_ - MFDedup performs explicit chunk reordering in a dedicated migration stage and assumes locality across consecutive backups, while GCCDF clusters by ownership and remains effective on mixed-source datasets.
- _Zou et al. (USENIX ATC '22)_ - Their fine-grained deduplication framework targets high-ratio, high-performance backup storage broadly, whereas GCCDF focuses on restore locality and GC-time layout repair after deduplication has already happened.

## My Notes

<!-- empty; left for the human reader -->

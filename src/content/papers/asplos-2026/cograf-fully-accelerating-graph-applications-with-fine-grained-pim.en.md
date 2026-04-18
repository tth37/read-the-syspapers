---
title: "CoGraf: Fully Accelerating Graph Applications with Fine-Grained PIM"
oneline: "CoGraf combines tuple-based cache coalescing, multi-column FGPIM updates, and bank-parallel predicates to accelerate both graph update and apply phases."
authors:
  - "Ali Semi Yenimol"
  - "Anirban Nag"
  - "Chang Hyun Park"
  - "David Black-Schaffer"
affiliations:
  - "Uppsala University, Uppsala, Sweden"
  - "Huawei Technologies, Zurich, Switzerland"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790142"
code_url: "https://github.com/alisemi/CoGraf"
tags:
  - graph-processing
  - hardware
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CoGraf argues that fine-grained PIM is not enough for graph processing if it only accelerates irregular scatter updates. Its key move is to co-design cache coalescing, multi-column DRAM-side execution, and bank-parallel predicated instructions so that both the irregular update phase and the regular-but-conditional apply phase run inside or near DRAM. Across GAP-style push-based graph workloads, that turns PIM from a partial optimization into an end-to-end graph accelerator.

## Problem

The paper starts from a mismatch between where fine-grained PIM is strongest and where graph applications are hardest. FGPIM gets its efficiency from row-level locality and SIMD-style column processing inside DRAM, but vertex-centric push-based graph codes generate highly irregular read-modify-write traffic in their update phase. Prior PIM work therefore either offloads individual atomic updates directly to memory or coalesces only within a cache line before issuing one PIM command per column. Both reduce CPU-side traffic, but neither uses the full row-level structure of DRAM effectively.

That is only half of the problem anyway. Push-based synchronous graph algorithms also have an apply phase that scans vertices regularly, but those scans are not just bulk arithmetic. They include conditionals such as "only commit the new value if the delta is large enough" and hybrid reductions such as generating a frontier or summing error terms for convergence. Earlier FGPIM proposals largely ignore this phase, which means that once the update path is accelerated, apply becomes the new bottleneck. The paper's claim is therefore stronger than "do graph atomics in memory": to fully accelerate PageRank-like workloads, PIM must handle irregular update coalescing and conditional apply-side computation together.

## Key Insight

CoGraf's central insight is that graph updates should be coalesced at the granularity that best matches DRAM row behavior, not at the granularity of an ordinary cache line. If multiple sparse updates land in the same DRAM row, keeping them together in the LLC lets one row activation feed much more useful work. That improves cache utilization, cuts row activations, and creates update batches that are large enough for FGPIM to matter.

But larger coalescing granularity creates a second requirement: the PIM side must understand that a single evicted cache line may target multiple DRAM columns within one open row. CoGraf therefore sends tuple-encoded updates to FGPIM, lets the memory controller statically schedule the resulting variable-latency multi-column operations, and then adds bank-parallel predication so the apply phase can execute conditionally in DRAM as well. The memorable proposition is that graph irregularity is manageable if the cache, memory controller, and PIM units all agree on the same row-oriented representation of work.

## Design

The first piece is a tuple-based LLC. In CoGraf, cache lines used for update coalescing switch into a tuple mode that stores `{offset, update}` pairs rather than assuming every value belongs to one contiguous 64 B region. The set index and tag are derived from the DRAM row address, while the tuple metadata carries column and word offsets within that row. For 32-bit updates, that reduces entries per cache line from `16` at 64 B granularity to `12` at 1 KB granularity and `11` at 8 KB granularity, but the tradeoff is that those entries can now absorb updates from a much larger address range. The paper reports that fixed cache-line coalescing sends cache lines that are on average `88%` zeros, so this larger-granularity packing is mainly about wasting less space and less bandwidth.

The second piece is multi-column update execution in FGPIM. A row-granular tuple line often spans more than one DRAM column, so sending one FGPIM command per column would throw away much of the benefit. CoGraf instead ships the tuple cache line directly to FGPIM, where the hardware identifies the distinct target columns in parallel and then processes them sequentially under a single command while the row stays open. The memory controller inspects the tuple line ahead of time to determine how many columns will be touched, which lets it statically schedule the variable-latency command without waiting for a completion signal back from the PIM engine. The paper says this cuts FGPIM update commands by `79%` on average relative to separate per-column commands.

The third piece addresses the apply phase. CoGraf adds bank-parallel instructions such as `BP_FGPIM_mov`, `BP_FGPIM_add`, `BP_FGPIM_mul`, `BP_FGPIM_mad`, plus predicate-setting and conditional-move operations backed by temporary storage inside the FGPIM unit. Data structures such as `scores`, `next_scores`, and `deltas` are laid out so corresponding chunks live in the same bank but parallel rows. That lets the machine evaluate conditions like `delta > e * score`, update scores only when the predicate is true, and compute most of the regular apply-phase arithmetic across all banks in parallel.

Two remaining tasks still need CPU help, but the interface is narrow. For frontier generation, CoGraf writes predicate outcomes as compact bitmaps and lets the CPU read those bitmaps back to assemble the next frontier. For convergence error, each bank accumulates a partial reduction, then the CPU reads one DRAM column per bank and finishes the final sum. The design therefore does not claim to eliminate the host; it claims that the host should only handle the small cross-bank reductions and control decisions that do not map well to in-bank SIMD execution.

## Evaluation

The methodology is simulation-based but fairly detailed. The authors extend Ramulator with an HBM-PIM-like model, use a 32 MB shared LLC, model both `HBM2` (`1024 GB/s`, `1 KB` rows) and `DDR4` (`137 GB/s`, `8 KB` rows), and evaluate five push-based graph applications: `BFS`, `CC`, `PR`, `PRD`, and `RD`. Inputs come from GAP-style graphs including Twitter (`TW`), sk-2005 (`SK`), USA-road (`RO`), and generated Kronecker/uniform graphs (`k27`, `u27`). Baselines are well chosen for the paper's argument: `PHI` as the state-of-the-art CPU cache-coalescing design, naive `FGPIM`, `AIM` with fixed column-granularity coalescing, then CoGraf's own incremental variants `Optimal`, `Multi`, and `Bank-parallel`.

The top-line result is that the full design reaches `4.4x` speedup on HBM and `9.8x` on DDR over `PHI`, with DRAM energy reductions of `88%` and `94%`, respectively. Compared with naive FGPIM, it is still `1.8x` and `3.0x` faster while reducing DRAM energy by `67%` and `86%`. The breakdown matters. Moving from `AIM` to `Optimal` substantially reduces energy, `22%` on HBM and `57%` on DDR, because larger-granularity coalescing cuts row activations, but it barely helps performance on its own and even slows HBM by `2%`. Only after multi-column commands are added does the update phase benefit materially from that extra coalescing. Then the bank-parallel apply support adds another `1.5x/1.6x` improvement over `Multi`, which is exactly the paper's point that update-only acceleration is incomplete.

The per-graph analysis is also informative rather than decorative. On low-locality graphs such as `TW`, `k27`, and especially `u27`, the gains mostly come from fixing the update phase; on high-locality `SK` and low-edge-ratio `RO`, the biggest gains come from bank-parallel apply execution. For `PRD`, the full design improves performance over `PHI` by as little as `1.7x/1.8x` on `SK` and as much as `12.1x/57.5x` on `u27`, with corresponding energy savings up to `97%/98%`. That supports the paper's central claim well: CoGraf is not just a constant-factor micro-optimization, but a design whose value depends on graph locality and on whether the bottleneck sits in update or apply. The baselines are also implemented in the same simulation framework, which makes the comparison cleaner than a cross-paper mashup.

## Novelty & Impact

Relative to _Mukkara et al. (MICRO '19)_, CoGraf takes the cache-coalescing intuition of `PHI` and marries it to FGPIM rather than leaving apply-side computation on the CPU. Relative to _Ahn et al. (ISCA '15)_ and _Nai et al. (HPCA '17)_, its novelty is not merely moving graph atomics toward memory, but matching cache representation, command structure, and bank-parallel execution to the row/column organization of DRAM. Relative to recent graph-PIM work such as _Shin et al. (MICRO '25)_, its most distinctive move is to treat conditional apply logic as a first-class target instead of focusing only on better gather/scatter locality.

That makes the paper likely to matter to two audiences. Hardware architects working on practical PIM interfaces get a concrete example of when "fine-grained" PIM still needs system-level co-design above the DRAM primitive. Graph-systems researchers get a sharper explanation of why partial acceleration keeps moving the bottleneck around. The paper is therefore most convincing as a mechanism paper with a strong end-to-end argument, not as an isolated instruction-set extension.

## Limitations

The results come with clear boundaries. The evaluation is entirely simulation-based and focuses on the largest iterations, where the region of interest exceeds LLC capacity and better coalescing matters most; the paper itself notes that small iterations can be better handled by CPU implementations that skip untouched vertices. The programming model is also not automatic: the update phase only needs atomic operations replaced with FGPIM updates, but the apply phase requires explicit algorithmic rewrites, custom data layout, pinned pages, and library support for bank-parallel allocation. CoGraf also inherits the classic PIM cost of reduced DRAM capacity, about `25%` in the authors' accounting, and the paper suggests CXL memory or graph tiling for larger-than-memory graphs rather than demonstrating such deployments directly. Finally, its strongest evidence is for synchronous push-based graph workloads; the paper explicitly does not claim that pull-style algorithms or arbitrary graph software will map as cleanly.

## Related Work

- _Ahn et al. (ISCA '15)_ — PEI shows how to offload fine-grained operations into memory, but CoGraf goes further by matching cache coalescing granularity and apply-phase execution to FGPIM's row/column structure.
- _Nai et al. (HPCA '17)_ — GraphPIM offloads graph updates to PIM and is conceptually closest to CoGraf's naive-FGPIM baseline, but it does not provide CoGraf's tuple coalescing or apply-phase predication.
- _Mukkara et al. (MICRO '19)_ — PHI coalesces commutative graph updates in CPU caches; CoGraf preserves that idea while pushing the merged work into FGPIM and accelerating the follow-on apply phase.
- _Shin et al. (MICRO '25)_ — FALA improves graph processing through locality-aware PIM-host cooperation and fine-grained column access, whereas CoGraf emphasizes larger-granularity cache coalescing plus bank-parallel conditional execution.

## My Notes

<!-- empty; left for the human reader -->

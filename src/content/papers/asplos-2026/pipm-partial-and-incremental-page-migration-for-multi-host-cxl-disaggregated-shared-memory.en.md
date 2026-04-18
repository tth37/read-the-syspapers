---
title: "PIPM: Partial and Incremental Page Migration for Multi-host CXL Disaggregated Shared Memory"
oneline: "Migrates only hot cache lines, not whole pages, in multi-host CXL shared memory and piggybacks movement on coherence traffic to avoid harmful remote slowdowns."
authors:
  - "Gangqi Huang"
  - "Heiner Litz"
  - "Yuanchao Xu"
affiliations:
  - "Computer Science Engineering, University of California, Santa Cruz, Santa Cruz, California, USA"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790203"
tags:
  - memory
  - disaggregation
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PIPM argues that whole-page migration is the wrong abstraction for multi-host CXL shared memory. It migrates only the hot cache lines of a page, moves them incrementally during ordinary coherence events instead of explicit copy operations, and extends the coherence protocol so locally migrated data remains usable without paying the full CXL round trip. In simulation, that combination reaches up to `2.54x` speedup and `1.86x` on average over the native multi-host CXL-DSM baseline.

## Problem

The paper starts from a tension in CXL 3.x systems. Multi-host CXL-DSM makes a large shared memory pool cache-coherent across hosts, which is attractive for databases, analytics, and AI systems, but a remote CXL access is still much slower than a local DRAM access after an LLC miss. In single-host tiered-memory designs, the obvious answer is page migration: move hot pages into local DRAM and keep cold pages in the shared pool.

That logic breaks once multiple hosts share the same data. A page that is hot for one host may still be useful to other hosts. If the page is migrated into one host's local memory, those other hosts no longer access it as an ordinary cacheable CXL line; they now pay extra hops, round trips, and address-remapping overhead for non-cacheable inter-host accesses. The paper calls this "local gain, global pain." Migration itself also becomes much more expensive. Updating a page's unified physical address requires cross-host coordination, page-table edits, TLB invalidations, and CXL RPCs instead of a mostly local kernel operation.

The authors quantify both failure modes before proposing a fix. In their four-host setup, existing single-host policies such as Nomad and Memtis produce harmful migrations for `34%` and `29%` of migrated pages on average. Shorter migration intervals help them react to multi-host access patterns, but at `1 ms` intervals their management and transfer overheads dominate and performance falls below the no-migration baseline. So the real problem is not merely "make migration smarter," but "avoid turning a shared-memory optimization into a coherence and control-path tax for everyone else."

## Key Insight

The key claim is that multi-host CXL-DSM needs two different granularities at once. Migration decisions should still be made with page-level context, because contention and ownership are page-scale phenomena, but the actual data movement should happen at cache-line granularity and only when normal memory traffic already touches the data. That split lets the system respect cross-host sharing patterns without paying whole-page migration costs.

PIPM therefore separates identifying a likely owner from physically moving data. A majority-vote policy tracks whether one host accesses a page enough more often than all other hosts combined to justify migration. But when that threshold is crossed, PIPM does not copy the whole page or rewrite page tables. It only marks the page as partially migrated and allocates local backing space. Individual cache blocks then drift into that host's DRAM through ordinary fills, evictions, and writebacks. If another host later becomes the accessor that matters, those lines can drift back toward CXL memory instead.

What makes this work is that the design matches the asymmetry of multi-host sharing. Many pages are not uniformly private or uniformly shared. Some lines inside the page are strongly local to one host, while others are rarely touched or are touched by many hosts. The paper's main contribution is recognizing that this mixed-access structure is common enough that "partial page ownership" is the right primitive.

## Design

PIPM adds three pieces of hardware support: a migration policy, remapping tables, and a new coherence design. The migration policy uses a Boyer-Moore-style majority vote over per-page accesses. The global remapping table, stored with CXL memory, tracks for each shared page a current host ID, a candidate host ID, and a small global counter. When one host accesses a page enough more often than the rest by a configurable threshold, PIPM starts partial migration for that page. A per-host local remapping table then stores the local PFN that will hold migrated cache lines plus a local counter used to revoke migration when inter-host sharing rises again. Importantly, starting or revoking partial migration only updates these tables; it does not trigger page-table rewrites or TLB shootdowns.

Actual movement is incremental. PIPM piggybacks migration onto coherence events rather than issuing explicit page-copy operations. If the local host was the most recent accessor of a line, a local writeback can migrate that line from CXL memory into host DRAM. If another host later reads or writes the line, the coherence path can move the latest data back toward CXL memory. The design therefore reuses intrinsic memory traffic as the transport mechanism and avoids the extra bulk-transfer overhead that dominates short-interval page migration in prior work.

To make partial migration coherent, the paper extends the default CXL-DSM MESI-style protocol. It introduces a new `ME` state in the local coherence directory, an `I'` state encoded using existing invalid states plus a 1-bit in-memory marker, and corresponding in-memory bits in both local DRAM and CXL memory. The effect is that a host can tell whether a partially migrated cache line's newest copy is in its local memory without always asking the CXL device directory first. Local accesses to migrated lines therefore become cheap, while inter-host accesses still remain coherent by routing through the owning host when needed. The authors also model-check the protocol with Murphi for deadlock freedom, SWMR, and sequential consistency.

The space cost is modest by the paper's accounting: about `4 B` per local remapping-table entry, `2 B` per global entry, a `1 MB` local remapping cache per host, and a `16 KB` global remapping cache on the CXL device. The authors frame this as roughly `0.1%` of RSS for local tables and `0.05%` of total CXL-DSM size for the global table.

## Evaluation

The evaluation uses a cycle-level simulator configured as four hosts with one single-socket CPU each, `128 GB` of CXL-DSM, and `32 GB` of local DRAM per host. Workloads span GAPBS graph analytics, PARSEC applications, XSBench, and Silo running TPC-C and YCSB. The baselines include Native CXL-DSM with no migration, Nomad, Memtis, HeMem, and two ablations: `OS-skew`, which keeps PIPM's policy but uses conventional OS page migration, and `HW-static`, which keeps incremental line migration but uses a static mapping similar to Flat-Mode-style hardware tiering.

The main result is strong and consistent. PIPM achieves `1.86x` average performance over Native CXL-DSM, with a maximum of `2.54x`, and it beats all baselines on every workload the paper reports. The biggest wins appear on graph workloads such as SSSP and PageRank, where independent workers repeatedly revisit localized regions and speedups reach roughly `142%-151%`. Database workloads gain less, but still improve by about `36%-53%`. The ablations matter: `OS-skew` improves performance by only `31.5%` on average over Native CXL-DSM, and `HW-static` by `15.7%`, which supports the paper's argument that PIPM needs both its policy and its incremental mechanism.

The microarchitectural evidence lines up with that story. PIPM raises average local-memory hit rate to `56.1%`, versus `26.5%` for Nomad, `31.0%` for Memtis, and `28.1%` for HeMem. It also cuts inter-host memory stall time to just `1.5%` of total execution time on average, compared with roughly `16%-19%` for the single-host-derived baselines. Memory footprint in local DRAM stays restrained: the page-level mapping footprint averages `7.3%` of total memory and actual migrated cache lines about `5.5%`, which is much smaller than a static 25% host-local partition. Sensitivity studies further show that PIPM becomes even more valuable when CXL latency rises, and that modest remapping caches capture almost all of the benefit. Overall, the evaluation supports the central claim well, though it does so entirely in simulation rather than on CXL 3.x hardware.

## Novelty & Impact

Relative to _Xiang et al. (OSDI '24)_ on Nomad and _Lee et al. (SOSP '23)_ on Memtis, PIPM's novelty is not better hot-page prediction inside the same software migration model. Its contribution is changing the abstraction altogether: migration is partially page-scoped, line-granular in execution, and co-designed with cache coherence. Relative to Flat-Mode-style hardware tiering, its key advance is that placement is dynamic and multi-host-aware instead of a fixed swap relationship between one CXL region and one local-memory region.

That makes the paper important for architects and systems researchers thinking about CXL as more than a remote NUMA pool. It shows that once multiple hosts share coherent remote memory, the right unit of management is neither an untouched page nor a simple DRAM cache line. The work is likely to be cited by later CXL memory-management, coherence, and shared-database papers because it offers a concrete mechanism for reconciling locality with cross-host sharing.

## Limitations

The biggest limitation is deployment realism. PIPM is evaluated in a detailed simulator, and the paper does not provide a hardware prototype or kernel implementation on actual multi-host CXL 3.x machines. The mechanism also assumes nontrivial hardware changes: remapping tables, remapping caches, extra in-memory state bits, and coherence-protocol extensions in both host and CXL memory nodes. That is reasonable for an architecture paper, but it raises the integration bar.

The evaluation scope is also narrower than the ambition of the idea. The system is modeled as four hosts and a single-socket CPU per host, with all shared heap data initially placed in CXL memory and code, stacks, and kernel data treated as private local memory. Those choices are sensible for analysis, but they leave open how PIPM behaves under larger fabrics, more heterogeneous host roles, or software stacks that already perform application-level placement. Finally, the majority-vote threshold is shown to be robust over a modest range, but the paper still relies on a thresholded policy rather than proving optimal behavior across all sharing patterns.

## Related Work

- _Xiang et al. (OSDI '24)_ — Nomad performs transactional page migration for CXL tiering, but it assumes the whole-page move itself is reasonable; PIPM shows that assumption breaks in multi-host shared memory.
- _Lee et al. (SOSP '23)_ — Memtis improves hotness classification and page-size choice for tiered memory, whereas PIPM focuses on coherence-aware partial migration under multi-host sharing.
- _Vuppalapati and Agarwal (SOSP '24)_ — Colloid optimizes tiered-memory placement around access latency, while PIPM centers the side effects of coherence and inter-host non-cacheable accesses.
- _Chou et al. (MICRO '16)_ — CANDY studies coherent DRAM caches for multi-node systems; PIPM instead targets CXL-disaggregated shared memory with explicit migration control and remapping metadata.

## My Notes

<!-- empty; left for the human reader -->

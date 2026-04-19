---
title: "PET: Proactive Demotion for Efficient Tiered Memory Management"
oneline: "PET derives P-blocks from anonymous mmap regions and demotes them in phases, cutting fast-memory use well beyond page-based schemes without large slow-tier stalls."
authors:
  - "Wanju Doh"
  - "Yaebin Moon"
  - "Seoyoung Ko"
  - "Seunghwan Chung"
  - "Kwanhee Kyung"
  - "Eojin Lee"
  - "Jung Ho Ahn"
affiliations:
  - "Seoul National University, South Korea"
  - "Samsung Electronics, South Korea"
  - "Inha University, South Korea"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717471"
tags:
  - memory
  - kernel
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PET argues that page-granularity proactive demotion leaves too much money on the table for tiered memory. It captures larger allocation-shaped regions called P-blocks from anonymous `mmap` VMAs, demotes them through a multi-phase coldness test, and promotes them with canary-fault signals before slow-tier accesses pile up. On the authors' Linux 6.1.44 prototype with DRAM plus Optane, PET reports 39.8% average fast-memory savings with 1.7% slowdown when the workload fits in fast memory, and 31% less slowdown than the stock kernel when it does not.

## Problem

Most OS-level tiered-memory systems still behave reactively. They keep cold pages in DRAM until free fast memory falls below a tight threshold such as the Linux watermark, then demote pages only after hot allocations and promotions are already competing for the same scarce space. That is acceptable when the whole working set fits in fast memory, but it hurts exactly when tiered memory matters most: once demand spikes, promotion or allocation can fail or be coupled with extra demotion work on the critical path.

Prior proactive schemes improve on that, but the usual page-sized management unit is a bad match for aggressive demotion. Datacenter applications have lots of cold data, yet scanning and moving 4 KB pages independently adds tracking overhead and makes it easy to miss larger logical regions that are cold together. The authors' PMU study suggests that many benchmarks show hot/cold locality at the allocation-unit scale instead. The challenge is how to exploit that locality from inside the OS, without application annotations and without paying large mis-demotion costs when access patterns shift.

## Key Insight

PET's core claim is that the right management unit for proactive demotion is often not the page, but a coarse region that approximates how applications allocate memory. Linux cannot see high-level objects directly, but newly created anonymous `mmap` VMAs are a good proxy for large allocation units; in the evaluated workloads, the captured P-blocks overlap `malloc()` objects by more than 97%.

That proxy only works if the system stays conservative near the demotion boundary. PET therefore combines coarse regions with progressively more expensive checks. It first samples a single page per P-block, then subdivides suspicious blocks into temporary regions, and finally uses a small fraction of canary pages that deliberately fault on access. The paper's real insight is the combination: allocation-scale regions make aggressive demotion worthwhile, and phased validation keeps region-scale mistakes from becoming performance disasters.

## Design

PET introduces a new kernel metadata object, the P-block. When Linux creates a new anonymous `mmap` VMA, PET captures that range before later VMA merges erase the original boundary. Very large captured blocks are split initially, with a default maximum P-block size of 1 GB, because a giant allocation may still contain both hot and cold subregions.

`kdemoted` is the background thread that maintains P-block state and chooses demotion candidates. PET samples one page per P-block during each sampling interval, clears that sampled page's access bit, and after several such intervals aggregates the observations over a scan interval. A never-touched block is not demoted immediately. Instead, PET moves blocks through four states: `NORMAL`, `PHASE1`, `PHASE2`, and `DEMOTED`.

The multi-phase logic is the paper's main mechanism. In `PHASE1`, PET splits a cold-looking P-block into temporary blocks and tracks those more finely, because a large region may mix hot and cold data. If cold temporary blocks dominate, the P-block enters `PHASE2`. There PET demotes 10% of each temporary block as canary pages, marks them `PROT_NONE`, and uses resulting fake faults to measure whether supposedly cold regions are actually being touched. If cold temporary blocks still dominate, PET merges adjacent cold subregions, demotes those merged regions to slow memory, and turns surviving hot subregions back into `NORMAL` P-blocks. This is much more elaborate than a single page-hotness threshold, but it is what lets PET demote aggressively while still correcting coarse mistakes before full demotion.

Promotion is handled separately by `kpromoted`. A fake fault on a canary page increments the containing demoted P-block's counter, but the fault path does not migrate the whole block immediately. PET derives a system-wide promotion budget from a 3% tolerable slowdown and an 8.3 microsecond mis-demotion penalty, giving a target of 360 faults per second. Each demoted block gets a proportional threshold `th_block`; once either that local threshold or the interval-wide global threshold is exceeded, `kpromoted` migrates the whole P-block back. PET also adds a file-page policy: files with `open_count == 0` are treated as cold and demoted in the background.

## Evaluation

The evaluation runs on a dual-socket Xeon Platinum 8260 machine with 64 GB of DRAM as fast memory and 256 GB of Intel Optane DC Persistent Memory as slow memory. The workload mix is broad for a kernel paper: Graph500, SPECspeed 2017, GAPBS, liblinear, Redis with YCSB, XSBench, a phase-change microbenchmark, and a Java H2 adversarial case. The baseline set is also strong, including AutoTiering, TPP, Thermostat, DAMON-based tiering, and MGLRU-based proactive demotion.

When the aggregate working set exceeds fast-memory capacity, PET's case is persuasive. On workloads tuned to about 1.5x the fast-memory size, it averages only 5.7% slowdown versus the fast-only ideal while using 28.4 GB of fast memory on average, more than 21 GB less than non-proactive schemes. The phase-change experiment makes the story clearer: PET proactively strips 90.7% of `imagick_s` from fast memory before `XSBench` ramps up, so the two jobs run with only 2.3% and 1.9% slowdown respectively, whereas the stock kernel and AutoTiering incur 17.2% slowdown on `XSBench`.

When the whole workload already fits in fast memory, PET still finds savings rather than waiting for pressure. Without file-page demotion, it saves 30.7% of fast memory with only 1.40% average slowdown relative to the Linux base system. With file-page demotion enabled, the headline number becomes 39.8% average fast-memory savings, up to 80.4%, at 1.7% average slowdown; for `liblinear` and GAPBS specifically, the paper reports 49.3% savings with 1.6% slowdown. The reactiveness experiment is also important: PET reaches the same peak throughput as page-granular MGLRU-based proactive demotion with only a 1-second longer reaction time while scanning only 0.87% as many pages.

The evidence mostly supports the thesis. The main caveat is that the gains come from a whole policy bundle - region capture, phased demotion, canary faults, and a file-page rule - so the paper is proving the value of this combined design rather than isolating one simple primitive.

## Novelty & Impact

Relative to Thermostat, TPP, and MEMTIS, PET's novelty is not merely that it demotes proactively or samples hotness differently. The paper changes the granularity of OS-level tiered-memory management from pages to VMA-derived allocation regions, then adds a demotion and promotion pipeline tailored to that coarser unit. That is a more structural idea than just adjusting thresholds or using a different fault signal.

The likely impact is on future kernel and hypervisor tiered-memory work for Optane-like or CXL-attached slow tiers. PET gives a concrete recipe for when aggressive demotion is worth attempting: only if the management unit matches logical allocation boundaries closely enough that coldness clusters. Even if later systems replace VMAs with better region extractors, this paper makes the case that region formation is a first-class design problem, not just an implementation detail behind page migration.

## Limitations

PET depends heavily on an assumption that is true for many native workloads and weak for others: access locality should line up with anonymous allocation regions. The H2 Java experiment exposes the boundary. There, PET still beats DAMON by nearly 2x, but page-granular MGLRU-based proactive demotion is 7% faster because JVM-managed heaps do not preserve the same allocation-locality signal.

The system also has several deployment costs. It adds new kernel metadata, two background threads, multiple tunable parameters, and a promotion budget derived from an assumed tolerable slowdown. The evaluated file-page policy is conservative, demoting only files no process still has open. PET also assumes the hot working set can fit in fast memory; the authors explicitly leave feedback-based thrashing detection and suspension of PET as future work. Finally, the evaluation is on one Intel-plus-Optane platform, so the absolute thresholds may need retuning on different slow-memory technologies.

## Related Work

- _Agarwal and Wenisch (ASPLOS '17)_ - Thermostat also does proactive demotion, but it reasons at huge-page granularity with sampled page faults, whereas PET builds larger allocation-shaped regions and uses canary faults only at the last validation stage.
- _Al Maruf et al. (ASPLOS '23)_ - TPP proactively demotes cold pages to preserve a small free fast-memory reserve, while PET demotes regardless of current free-space pressure in order to lower the steady-state fast-memory footprint itself.
- _Lee et al. (SOSP '23)_ - MEMTIS improves page classification and page-size decisions for tiered memory with THP enabled, while PET's main contribution is switching the management unit from pages to VMA-derived regions.
- _Moon et al. (IEEE CAL '23)_ - ADT is the authors' preliminary argument for allocation-unit proactive demotion; PET turns that idea into a full kernel design with dynamic P-block capture, block splitting, and prompt region-granularity promotion.

## My Notes

<!-- empty; left for the human reader -->

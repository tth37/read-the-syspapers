---
title: "Chrono: Meticulous Hotness Measurement and Flexible Page Migration for Memory Tiering"
oneline: "Chrono uses timer-captured idle time instead of coarse counters, then auto-tunes promotion and demotion so Linux moves truly hot pages across DRAM and slow memory."
authors:
  - "Zhenlin Qi"
  - "Shengan Zheng"
  - "Ying Huang"
  - "Yifeng Hui"
  - "Bowen Zhang"
  - "Linpeng Huang"
  - "Hong Mei"
affiliations:
  - "Department of Computer Science and Engineering, Shanghai Jiao Tong University"
  - "MoE Key Lab of Artificial Intelligence, AI Institute, Shanghai Jiao Tong University"
  - "Intel"
  - "Shanghai Jiao Tong University"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717462"
code_url: "https://github.com/SJTU-DDST/chrono-project"
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

Chrono measures page hotness with Captured Idle Time (CIT), the delay between when Linux scans and poisons a page and when that page faults next. Because CIT is timer-based, Chrono can separate hot from warm pages, auto-tune migration policy, and migrate pages across DRAM and slow memory with modest overhead. On DRAM plus Optane PMem, it improves Pmbench throughput by up to 216% over Linux NUMA balancing and cuts average and P99 latency by up to 68% and 79%.

## Problem

Tiered memory combines DRAM with slower byte-addressable memory, so the kernel must reserve the fast tier for hot pages. Linux's stock NUMA balancing is a poor fit: when the slow tier is exposed as a CPU-less NUMA node, any access to a poisoned slow-tier page looks like a reason to promote it, which is closer to MRU than to frequency-aware placement.

Prior tiering systems still measure the wrong signal. Auto-Tiering and TPP count page faults over minute-scale windows, Multi-Clock tracks accessed-bit recency, and PEBS-based Memtis is more quantitative but becomes sparse on base-page workloads. The authors' experiment shows why this matters: average NVM pages already see 20-40 accesses per minute, and the hottest 10% are 5.5x above average. Coarse counters cannot separate those cases well enough.

## Key Insight

Chrono's core claim is that page hotness should be estimated from idle time, not access counts. If the kernel records when a page was scanned and subtracts that from the timestamp of the page's next fault, the result is a negative proxy for access frequency: short CIT means hot, long CIT means cold. Because this signal comes from timers, its resolution is decoupled from scan intensity. Chrono can keep a minute-scale scan cadence and still recover sub-second hotness differences.

That finer signal makes adaptive control possible: Chrono filters candidates across rounds, rate-limits migration, and tunes both the threshold and the migration rate online. Precise measurement and flexible control have to be designed together.

## Design

Chrono is implemented inside Linux's NUMA-tiering framework and has three main pieces. First, Ticking-scan periodically marks pages `PROT_NONE`, stores scan timestamps for slow-tier pages, and computes CIT on the next fault. The metadata cost is 4 bytes per page, and millisecond timers let Chrono represent hotness up to 1000 accesses per second. A system-wide CIT threshold decides which pages are hot enough to promote.

Second, Chrono uses conditional promotion instead of promoting on one sample. Pages below threshold enter an XArray-backed candidate set; only pages that remain below threshold on the next scan are queued for asynchronous promotion. Promotion is also rate-limited.

Third, Chrono turns tiering into a feedback loop. In semi-auto mode, the operator sets a target promotion rate and Chrono adjusts the CIT threshold to match it. In the default fully automatic mode, Dynamic CIT Statistic Collection (DCSC) samples 0.003% of pages from both tiers, builds 28-bucket heat maps, compares hot slow-tier pages with cold fast-tier pages, and uses the resulting misplacement signal to retune both the threshold and the promotion rate. On the demotion side, it adds a promotion-aware `pro` watermark above Linux's high watermark, proactively demotes cold DRAM pages, and halves the next promotion rate if recently demoted pages bounce back too quickly. The paper also extends the scheme to huge pages.

## Evaluation

Chrono is implemented in Linux 5.18 with about 1.9k SLOC and evaluated on a Xeon Gold 6348 with 64 GB DRAM and 256 GB Optane PMem. Against Linux-NB, Auto-Tiering, Multi-Clock, TPP, and Memtis, the clearest result is on 50-process Pmbench with 5 GB per-process working sets: Chrono improves throughput by 216% over Linux-NB, 152% over Auto-Tiering, 92% over Multi-Clock, 90% over TPP, and 102% over Memtis. It also raises the fast-tier memory access ratio from 49% to 77% and cuts average and P99 latency by up to 68% and 79%.

The control overhead is modest relative to the gain. Chrono adds 2.1 percentage points of kernel time over Linux-NB, with 1.8 points attributable to DCSC. On Graph500 it reports 2.49x, 2.29x, and 2.05x speedups over Linux-NB. In a multi-cgroup hotness-gradient test, it gives nearly all DRAM to the hottest process, and its tuned CIT threshold settles near 200 ms, which the authors interpret as about 300 accesses per minute. Under huge-page settings Memtis can still beat Chrono by 1.03x.

## Novelty & Impact

Chrono is novel because it changes the measurement primitive, not just the migration rule. Earlier systems still build on counting, recency, or hardware sampling; Chrono instead asks how long a page stayed idle before its next observed access and then drives a closed-loop controller from that signal. This is most relevant for base-page workloads, where the paper argues that PEBS-style huge-page schemes lose precision or inflate hot regions.

## Limitations

Chrono still relies on page-fault-based observation, so it cannot avoid scan/fault overhead or instantly react to abrupt phase changes. The evaluation platform is Optane PMem exposed as NUMA, not an actual CXL pool, so the paper argues portability to future slow tiers more than it proves it. It also does not dominate every regime: Memtis has a slight advantage under huge-page settings.

## Related Work

- _Kim et al. (USENIX ATC '21)_ - Auto-Tiering counts faults over minute-scale windows, so it misses truly hot base pages.
- _Al Maruf et al. (ASPLOS '23)_ - TPP combines page-fault information with LRU recency for CXL-style tiering, but its rule is far coarser than Chrono's CIT threshold.
- _Lee et al. (SOSP '23)_ - Memtis uses PEBS counters and dynamic page sizing, but it works best with huge pages and fragments hotness on base-page workloads.

## My Notes

<!-- empty; left for the human reader -->

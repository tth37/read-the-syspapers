---
title: "Hey Hey, My My, Skewness Is Here to Stay: Challenges and Opportunities in Cloud Block Store Traffic"
oneline: "A 60k-VM EBS study shows cloud block-store skew is structural, pushing balancing, throttling, migration, and cache design toward prediction and larger persistent caches."
authors:
  - "Haonan Wu"
  - "Erci Xu"
  - "Ligang Wang"
  - "Yuandong Hong"
  - "Changsheng Niu"
  - "Bo Shi"
  - "Lingjun Zhu"
  - "Jinnian He"
  - "Dong Wu"
  - "Weidong Zhang"
  - "Qiuping Wang"
  - "Changhong Wang"
  - "Xinqi Chen"
  - "Guangtao Xue"
  - "Yi-Chao Chen"
  - "Dian Ding"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Alibaba Cloud, Hangzhou, China"
  - "Shanghai Key Laboratory of Trusted Data Circulation, Governance and Web3, Shanghai, China"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696068"
project_url: "https://tianchi.aliyun.com/dataset/185310"
tags:
  - storage
  - caching
  - datacenter
  - disaggregation
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

This paper shows that skewness in a hyperscale cloud block store is persistent, not exceptional. From 310 million traced IOs and full second-level metrics for roughly 60k VMs and 140k virtual disks, the authors connect four symptoms, bad worker balance, wasteful hard throttles, churny segment migration, and missed cache opportunities, to the same root cause: concentrated, read-heavy, bursty demand.

## Problem

Alibaba Cloud's EBS already employs the usual defenses: round-robin QP-to-worker binding in the hypervisor, segment migration across block servers, VM page cache, and server-side read prefetching. Yet the hottest worker thread still sees 2.6x the load of the coldest, and in one data center 1% of VMs generate 75.4% of reads and 42.6% of writes. Temporal bursts are harsher still: the 50th-percentile peak-to-average ratio of VM read traffic reaches 30,649.

The practical problem is that average-case control logic is being applied to traffic that is neither average nor symmetric. Prior work either studied much smaller populations or only one layer, so operators still lacked an end-to-end explanation of how skew propagates from VM and QP behavior to storage-server hotspots.

## Key Insight

Skew should be treated as the governing structure of the workload. If traffic is already concentrated across VM-to-VD, VD-to-QP, segment-to-BS, and LBA hotspots, then controllers based on current averages will misplace work, waste bandwidth, and churn data.

The paper's four case studies are all instances of that same failure. Round-robin assumes comparable QPs, hard per-VD caps ignore slack elsewhere, importer selection trusts current minima, and read-prefetch assumes read locality is what matters. The measurements instead point toward dispatch, prediction, and persistent hot-set management.

## Design

This is a measurement paper with simulation-backed design exploration. The system is a compute-storage-disaggregated EBS stack: VDs expose up to eight queue pairs, hypervisor worker threads poll them, BlockServers map 32 GiB segments to files, and ChunkServers persist to SSDs. The authors collect a 1/3200-sampled per-IO trace plus full second-level metrics over a 12-hour window.

They use cumulative contribution rate for spatial skew, peak-to-average ratio for bursts, coefficient of variation for imbalance, and write-to-read ratio for asymmetry. Those metrics drive four studies. For hypervisor balancing, the authors separate hotspots caused by too few QPs, single-QP hot VMs, and multi-QP VMs whose traffic still collapses onto a few QPs because VM-to-VD skew and Linux `blk-mq` underuse queue parallelism. For throttling, they measure how much purchased throughput and IOPS remain idle when one VD hits its cap. For storage balancing, they simulate importer-selection rules and read-aware migration. For caching, they quantify LBA hotspots, compare FIFO, LRU, and FrozenHot-style frozen cache, and reason about compute-node versus block-server placement.

## Evaluation

The dataset shows stronger skew than prior work and more read skew than write skew. At the hypervisor, median 1-minute worker-thread CoV is 0.7 for reads and 0.5 for writes, and 42.6% of nodes have a single QP carrying more than 80% of read traffic. A 10 ms rebinding simulation helps only 29.9% of nodes, which supports the claim that periodic rebinding is too coarse for bursty QP hotspots.

The throttle analysis is equally concrete. When a VD inside a multi-VD VM is throttled, median resource-available rate is 61.6% for throughput and 74.7% for IOPS, so hard caps strand paid-for capacity. Limited lending helps in most simulations; with lending rate 0.8, 85.9% of multi-VD-VM samples see shorter throttle time. But some cases regress because lenders can become hot again, so prediction and isolation are part of the mechanism, not optional extras.

On the storage side, the current importer heuristic is almost random: its normalized migration interval median is 0.24, versus 0.48 for an oracle importer. Read imbalance also remains under-addressed: 96.8% of clusters have read CoV at least as high as write CoV, while 85.2% have median segment `|wr_ratio| > 0.9`, meaning segments are typically read- or write-dominant. For caching, a 64 MiB hottest block occupies only 3.0% of a VD's LBA space but accounts for 18.2% of accesses, and 93.9% of hottest blocks are write-dominant. Frozen cache becomes competitive only with large cache capacity. The measurements strongly justify the diagnosis, while the remedies are mostly supported by trace-driven simulation rather than deployment.

## Novelty & Impact

This is a strong measurement study rather than a new algorithm paper. Its contribution is scale, end-to-end coverage, and the unification of four operational problems under one explanation: persistent spatio-temporal concentration of demand. That gives a concrete agenda for skew-aware dispatch, prediction, and persistent caching in disaggregated block stores.

## Limitations

The study covers one provider, only 12 daytime hours, inferred application labels, and a 1/3200 trace sample, so provider-specific effects and short-lived behaviors may be missed.

More importantly, the proposed fixes are not production deployments. Rebinding, lending, migration, and caching are mostly validated by simulation on production traces, and the open issues around prediction cost, fairness, isolation, cache consistency, and live-migration overhead remain real blockers.

## Related Work

- _Lee et al. (SYSTOR '17)_ - Lee et al. characterize storage traffic for enterprise virtual desktops, while this paper studies a much broader workload mix and finds far stronger read skew and burstiness.
- _Li et al. (TOS '23)_ - Li et al. compare cloud block-storage workloads at the storage side; this paper extends the analysis into hypervisor worker threads, queue pairs, and throttling behavior.
- _Mao et al. (ICPADS '22)_ - Mao et al. study traffic imbalance optimization in cloud block storage, whereas this paper uses larger production traces to show why prediction-driven balancing is attractive but operationally hard.
- _Qiu et al. (EuroSys '23)_ - FrozenHot Cache proposes eviction-free caching for modern hardware, and this paper evaluates that idea against EBS block hotspots and persistent-cache deployment tradeoffs.

## My Notes

<!-- empty; left for the human reader -->

---
title: "Cost-efficient Archive Cloud Storage with Tape: Design and Deployment"
oneline: "TapeOBS turns tape into a cloud archive backend by staging through HDDs, batching EC and restore work, and tape-aware scheduling to cut modeled 10-year TCO by 4.95x."
authors:
  - "Qing Wang"
  - "Fan Yang"
  - "Qiang Liu"
  - "Geng Xiao"
  - "Yongpeng Chen"
  - "Hao Lan"
  - "Leiming Chen"
  - "Bangzhu Chen"
  - "Chenrui Liu"
  - "Pingchang Bai"
  - "Bin Huang"
  - "Zigan Luo"
  - "Mingyu Xie"
  - "Yu Wang"
  - "Youyou Lu"
  - "Huatao Wu"
  - "Jiwu Shu"
affiliations:
  - "Tsinghua University"
  - "Huawei Cloud"
  - "Minjiang University"
conference: fast-2026
category: reliability-and-integrity
tags:
  - storage
  - datacenter
  - fault-tolerance
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

TapeOBS is Huawei Cloud's archive object service built on tape, with a small HDD pool in front of the tape pool. The central move is to treat tape as a fully asynchronous, batch-scheduled backend rather than as a synchronous object store: writes land in HDD first, restores are reordered before reaching tape, and each tape library uses SSD metadata, dedicated drives, and drive-aware scheduling to avoid the worst tape pathologies. In the paper's 10-year model, that reduces TCO by `4.95x` versus an HDD-based archive service, and the deployed system has already stored hundreds of petabytes of raw user data.

## Problem

Archive cloud storage has an unusual operating point: data is massive, retention is long, and reads are rare, but users still expect object APIs and strong durability. Tape is attractive because it is cheaper than HDD, lasts longer, uses less power, and has a clearer long-term density roadmap. The problem is that a tape library is not just a slower disk shelf. In TapeOBS, one library holds about `1000` tapes but only `4` drives, each mount takes around `80` seconds, and random reads inside a tape are expensive because the medium must wind and rewind.

That means a naive "swap HDD for tape" design breaks quickly. Synchronous user reads and writes would expose the tape pool's limited aggregate bandwidth. Object-level erasure coding would scatter one object across many libraries and consume many drives during restore. Metadata lookups on tape would create random seeks. And if drives bounce among unrelated tapes, drive thrashing dominates transfer time. The paper's goal is therefore not merely to use tape, but to build a cloud archive service whose software stack reshapes requests so tape can operate near its natural strengths.

## Key Insight

The paper's key proposition is that tape becomes practical in cloud archive storage only when the service boundary moves up: user-visible object operations must be decoupled from tape operations, and tape access must be scheduled in bulk. Once the system inserts that asynchronous boundary, it can optimize for tape's real constraints instead of pretending tape is an online random-access tier.

That boundary unlocks three linked advantages. First, writes can be grouped by expected lifetime so garbage collection later rewrites less live data. Second, multiple objects can be packed into one erasure-coded append, so a small object usually resides on one tape rather than spanning many. Third, restore requests can be grouped by partition and ordered by offset, turning a random request stream into one with physical locality. The rest of the design follows from making those bulk decisions executable inside each library.

## Design

TapeOBS is organized into a service layer, an index layer, a persistence layer, and a control plane called DataBrain. The service layer exposes OBS APIs and translates object operations into append-only `PLog`s. The index layer maps object IDs to triples such as `⟨plog-id, offset, size⟩`. The persistence layer contains both the tape pool and an HDD pool whose capacity is about `4%` of the tape capacity in production. MDC assigns `plog-id`s and maintains the partition view that maps each partition to a cross-library EC group.

The first major design choice is the fully asynchronous tape pool. User writes are absorbed by the HDD pool and only later flushed to tape. Restore requests also stage data through HDD after DataBrain schedules them. This lets TapeOBS use the hour-level restore SLA and the HDD pool's higher aggregate bandwidth to smooth bursts while avoiding direct exposure of tape latency.

The second key idea is batched erasure coding. Instead of erasure-coding each object independently, the service layer aggregates multiple objects into one `PLog append`, then EC-encodes that batch across libraries. In the paper's example, four smaller objects each end up on a single tape and only the fifth spans two tapes, so restore usually needs fewer drives. In production, TapeOBS uses Huawei's `12+2` LDEC scheme.

The third piece is library-local optimization. Drives are statically split into `2` write drives, `1` read drive, and `1` internal drive for GC, repair, and checking, which reduces interference-driven remounts. Each head server also has two NVMe SSDs. `MetaStore` keeps `256B` metadata records for sub-PLogs so the system can locate data without touching tape; `DataStore` buffers data persistently before flush. Metadata partitions on tape and a per-`4KB` DIF make recovery possible if SSD metadata is lost. Finally, the tape library scheduler uses a wrap-aware SCAN policy for grouped reads and a feedback-based flow-control mechanism that stabilized one write-drive anomaly from roughly `168.65 MB/s` average degraded bandwidth to `336.53 MB/s`.

## Evaluation

The evaluation is a mix of economic modeling, production characterization, and a few focused microbenchmarks. The paper models a `10`-year deployment starting at `100 PB` with `50%` annual growth and reports `2.68x` lower CapEx, `16.11x` lower OpEx, and `4.95x` lower total TCO for tape versus HDD. The deployed service is single-AZ today, organized into tape pools of `14` racks each, for `140 PB` per tape pool, and it had already stored hundreds of petabytes of raw user data when the paper was written.

The workload data supports the authors' design target. Objects smaller than `500 MB` account for `93.81%` of occupied capacity, and the largest customers are overwhelmingly write-heavy: the highest read ratio in Table 4 is only `0.674776%`. Over a representative day, the HDD pool stays tightly around `71.625%-71.675%` utilization under a `75%` watermark, while the tape pool digests staged data at a fairly steady rate. The tape pool averages `118.81K` append ops per minute, and reads are rare, peaking at `5.85K` ops per minute.

The most concrete latency result is for admitting a stripe into the tape pool's SSD-resident buffer: median write latency is `18.51 ms` and `P99` is `27.75 ms`. That supports the central claim that the software path can make tape-backed archive storage operationally usable. What the paper does not show is an end-to-end restore-latency distribution or a direct production A/B comparison against the earlier HDD-based archive service, so the evidence is stronger on feasibility and economics than on customer-visible latency under diverse restore mixes.

## Novelty & Impact

The novelty is not a new tape format or a new erasure code in isolation. The contribution is a cloud-service design that composes several tape-aware mechanisms across layers: asynchronous staging, lifetime-based batching, service-layer batched EC, dedicated drives, SSD-resident metadata, and drive-aware local scheduling. That is a systems-and-deployment paper in the strongest sense: the paper explains what architectural concessions are required before tape can behave like a practical cloud archive tier.

This should matter to cloud storage architects, operators of cold-storage fleets, and researchers working on post-HDD archival media. It also provides a useful counterpoint to colder-media papers that stop at the device or file-system abstraction; TapeOBS shows where the real pain appears once a service has to meet object-storage semantics at production scale.

## Limitations

The paper is candid about several constraints, and a few more are visible from the design. TapeOBS is currently a single-AZ service. Dedicated drives are static, so dynamic workload shifts can leave some drive capacity underused; the authors mention coarse-grained reallocation as future work. Batched EC lowers restore fan-out in the normal case, but it makes degraded reads more expensive: reconstructing an object on a failed tape can require `S × m` data rather than `S`.

The design also leans on operational headroom. The HDD pool is only about `4%` of tape capacity, yet `25%` of HDD space is intentionally kept free to absorb bursts and outages. The paper does not support deduplication, and it does not use tape's built-in compression because much customer data is already encrypted. Finally, the evaluation focuses on internal metrics; the paper does not quantify restore tail latency across the advertised multi-hour SLA tiers or compare directly against other cloud archive services.

## Related Work

- _Pease et al. (MSST '10)_ — LTFS makes tape look like a file system with hardware partitions and XML metadata, while TapeOBS keeps metadata on SSDs and exposes an asynchronous object service.
- _Koltsidas et al. (ICDE '15)_ — GLUFS integrates disk and tape inside a distributed file system, whereas TapeOBS centers on cloud object semantics, cross-library batched EC, and restore scheduling.
- _Gharaibeh et al. (MSST '14)_ — DeduT studies deduplication for tape systems; TapeOBS instead spends its design budget on batching, placement, and drive-level execution.
- _Zhou et al. (FAST '23)_ — SMRSTORE shows an archival object store on HM-SMR drives; TapeOBS targets a cheaper but operationally trickier point in the design space where mount cost and drive contention dominate.

## My Notes

<!-- empty; left for the human reader -->

---
title: "An Efficient Cloud Storage Model with Compacted Metadata Management for Performance Monitoring Timeseries Systems"
oneline: "CloudTS separates metadata from chunks, deduplicates tags globally, and uses compressed TTMappings plus TSObjects to speed up production queries by 1.43x over Cortex."
authors:
  - "Kai Zhang"
  - "Tianyu Wang"
  - "Zili Shao"
affiliations:
  - "The Chinese University of Hong Kong, China"
  - "Shenzhen University, China"
conference: fast-2026
category: indexes-and-data-placement
tags:
  - storage
  - databases
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CloudTS rebuilds a cloud-backed monitoring TSDB around global metadata rather than per-block files. It deduplicates tags across time partitions in a global `TagDict`, resolves tag filters through compressed `TTMapping` bitmaps, and stores chunks in grouped `TSObjects` so queries fetch only the relevant objects in parallel. Integrated into Cortex on EC2 plus S3, the paper reports a `1.43x` production-query speedup over baseline Cortex on its selected workloads.

## Problem

The paper starts from a simple but important mismatch: mainstream monitoring TSDBs such as Prometheus and Cortex were designed around local time-partitioned files, while cloud object stores expose high-latency object access rather than cheap in-place block reads. In a conventional block layout, each time partition bundles metadata and chunks together. Once that bundle is moved to S3, even a query that needs only a few series often has to retrieve a much larger object, parse the index, and then discard most of the payload. That is classic read amplification, but here it is made worse by metadata-heavy queries.

The workload makes the problem harder. Performance-monitoring deployments now track huge fleets of containers and microservices whose timeseries appear and disappear quickly. The paper cites ByteDance as handling more than ten billion distinct timeseries per day. In that setting, tags dominate metadata volume: the paper states that tags can account for more than `80%` of metadata size and that about `73%` of tags are repeated. Existing systems compress data points well, but they do not fundamentally attack redundant tags or the cost of repeatedly re-reading them across partitions.

Naive cloud-native alternatives also fall short. Directly storing Cortex-style blocks in cloud objects keeps the same read amplification. Apache Parquet shrinks files, but querying one series over one time range can still require fetching irrelevant rows or columns. JSON Time Series avoids some of that by storing each series separately, yet then tag-based search degenerates into scanning many objects. CloudTS therefore asks a sharper question: how should a monitoring TSDB reorganize metadata and chunk layout so that tag-filtered historical queries become object-store friendly?

## Key Insight

The paper's central claim is that cloud query latency is dominated less by raw chunk decoding than by the path used to discover which chunks matter. If metadata stays duplicated inside every time-partitioned block, the system keeps paying remote-access cost before it even knows what data to fetch. The right move is therefore to globalize metadata and localize data access.

CloudTS does that in three layers. First, tags are deduplicated globally rather than recopied into every block. Second, each time partition stores a compact, queryable mapping from tags to timeseries IDs, so a query can prune the search space before touching data objects. Third, actual chunk data is grouped into objects that preserve chronological locality while avoiding "one object per whole block" and "one object per series" extremes. Once those pieces are in place, the query path becomes metadata-first and object-selective, which is exactly what a cloud object store needs.

## Design

CloudTS separates the storage model into global metadata and partition-local data objects. The first metadata structure is `TagDict`, a Patricia-trie-like dictionary over metric names, tag keys, and tag values. Each tag pair gets a globally unique encoding at a leaf, and bidirectional pointers support both directions: tag pair to encoding during query planning, and encoding back to a human-readable tag during result reconstruction. For each time partition, CloudTS also keeps a local tag array containing only the tags that actually appear in that partition, which trims search space and avoids carrying dead vocabulary forward forever.

The second metadata structure is `TTMapping`, a two-dimensional bitmap for one time partition. Rows are timeseries IDs, columns are tag encodings, and a `1` marks membership. This replaces the traditional split among symbol table, postings, and series metadata with one compact incidence structure that can answer both "which tags describe this series?" and "which series match this tag set?" The paper then compresses `TTMapping` with `TMMC`, a CSR-like scheme that stores only set-bit positions and per-row offsets in `ind` and `ptr` arrays. Because monitoring metadata is sparse, this substantially shrinks the structure while keeping lookups simple.

CloudTS adds another optimization on top of that bitmap: timeseries grouping. In the ideal case, mutually exclusive tags would split the matrix into independent diagonal blocks, but real monitoring data is messier. The paper therefore uses tag frequency and shared tag names to build practical groups that still shrink the search space and, importantly, let queries probe multiple groups in parallel. This is one of the less elegant parts of the paper, but it is also realistic: the authors are explicitly optimizing around observed metadata distributions rather than insisting on a perfect schema.

Data lives in `TSObjects`. For one time partition and one timeseries group, CloudTS stores compressed chunks ordered by timeseries ID and time. This layout tries to hit the middle ground between tiny objects with too much metadata overhead and giant objects with too much read amplification. A background daemon called `CloudWriter` wakes when a local block becomes immutable, updates `TagDict`, builds `TTMapping`, streams chunks in chronological order into `TSObjects`, and uploads the converted representation without blocking the front-end monitoring service. Queries are handled by `CloudQuerier`: it caches local tag arrays and `TTMapping`s, resolves tag predicates to timeseries IDs, and then issues parallel object requests only for the relevant `TSObjects` and time windows.

## Evaluation

The evaluation is reasonably broad for a storage-format paper. The prototype is implemented in Go and integrated into Cortex `1.16.0`, running on an EC2 Ubuntu server with Amazon S3 as the backing store. In the production-style deployment, one EC2 node monitors ten Debian servers, with ten Node Exporter instances per server for `100` total targets. After collecting data for `48` hours, the authors issue recent-history queries for `cpu_avg` and `memory_usage_avg`. CloudTS delivers an average `1.43x` speedup over baseline Cortex on those end-to-end queries, and the throughput traces show that the `CloudWriter` uploads every two hours without visibly perturbing concurrent queries.

The synthetic study is larger and more diagnostic. The authors collect `500K` timeseries over `24` hours and run eight TSBS query patterns ranging from low-cardinality interval queries to threshold scans and whole-host aggregations. CloudTS is consistently fastest in Table 4: for example, `1-8-1` drops from `0.1452s` in baseline Cortex to `0.1258s`, `high-all` drops from `0.2351s` to `0.1884s`, and `cpu-all-8` drops from `0.2549s` to `0.2331s`. The more convincing result is data reduction: on `high-all`, accessed data volume falls from `626.29 MB` to `305.73 MB`; on `cpu-all-8`, it falls from `695.65 MB` to `352.49 MB`. Those numbers support the paper's claim that the main win comes from avoiding unnecessary object reads, not from faster decompression.

The later experiments mostly reinforce the same story. Increasing parallel cloud requests improves latency, especially for broader scans, and CloudTS reaches `230.735 MB/s` average network throughput on `high-all` versus `102.472 MB/s` for the baseline. CPU and memory overhead are also lower on the shown workloads (`45.7%` CPU and `3.35 GB` memory for CloudTS on `high-all`, versus `60.4%` and `5.21 GB` for Cortex). The paper additionally reports modest gains over InfluxDB `3.x` on harder historical queries and shows that metadata memory stays manageable under long retention and high label churn, with average per-partition metadata around `21 MB` in the long-retention experiment and under `30 MB` in the churn-heavy one.

## Novelty & Impact

The contribution is not a new chunk compression algorithm and not merely "store time series in the cloud." The paper's novelty is the end-to-end storage model that couples four decisions: globally deduplicated tag metadata, partition-local compressed tag-to-series bitmaps, group-aware chunk objects, and a query path that consults metadata before touching cloud data. That is a tighter systems argument than simply swapping in Parquet or pushing Cortex blocks to S3.

This should matter to builders of long-retention monitoring stacks, cloud-native TSDBs, and systems researchers studying metadata-heavy storage workloads. The paper is especially useful because it frames metadata redundancy, not only chunk layout, as the dominant design problem for historical monitoring queries in object storage. Even if a production system adopts only part of CloudTS, the paper gives a concrete blueprint for where the big wins are likely to come from.

## Limitations

The paper is strongest on read-path structure and weaker on the rest of the lifecycle. `CloudWriter` is described as a background daemon, but the paper does not deeply quantify write-path overhead, failure recovery cost, or how expensive it is to rebuild `TagDict` or `TTMapping` after corruption or cache loss. The core data model also assumes immutable partitions, so CloudTS fits Prometheus/Cortex-style block pipelines better than systems with heavier update semantics.

The evaluation has some boundary conditions too. Parquet and JTS are compared as formats integrated into Cortex rather than as independently engineered full systems, so those results are informative but not decisive. The InfluxDB comparison is more realistic, yet it still centers on historical scan-heavy queries where CloudTS is designed to win. Finally, the heavy-label-churn experiment shows that query latency and metadata memory do rise when millions of short-lived timeseries are injected per partition, and the mitigation is to use finer `15`-minute partitions plus frequent flushing. That suggests the design remains sensitive to workload tuning even if its per-partition memory stays bounded.

## Related Work

- _Shi et al. (SoCC '20)_ — ByteSeries compresses metadata and datapoints inside an in-memory monitoring TSDB, while CloudTS targets cloud object storage and global tag deduplication across time partitions.
- _Jensen et al. (ICDE '21)_ — ModelarDB+ groups correlated series for model-based compression; CloudTS instead reorganizes metadata and object layout to accelerate tag-filtered cloud queries.
- _An et al. (FAST '22)_ — TVStore bounds storage with time-varying compression, whereas CloudTS focuses on metadata redundancy and remote read amplification.
- _Xue et al. (IPDPS '22)_ — TagTree builds a global tagging index for time-series databases; CloudTS applies a related global-index idea inside a partitioned cloud-object layout with `TSObjects`.

## My Notes

<!-- empty; left for the human reader -->

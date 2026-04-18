---
title: "Loom: Efficient Capture and Querying of High-Frequency Telemetry"
oneline: "Loom 用 hybrid log 和按 chunk 的稀疏摘要承接 HFT，在不丢数的情况下支撑 9M records/s，并把常见 observability 查询维持在交互式延迟。"
authors:
  - "Franco Solleza"
  - "Shihang Li"
  - "William Sun"
  - "Richard Tang"
  - "Malte Schwarzkopf"
  - "Andrew Crotty"
  - "David Cohen"
  - "Nesime Tatbul"
  - "Stan Zdonik"
affiliations:
  - "Brown University"
  - "University of Washington"
  - "Northwestern University"
  - "Intel"
  - "MIT"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764853"
code_url: "https://github.com/fsolleza/loom"
tags:
  - observability
  - storage
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Loom 瞄准的是现有 telemetry backend 很难同时做到的三件事：完整捕获 high-frequency telemetry、把查询延迟压到交互式范围、并且不明显扰动被观测主机。它的做法是在 hybrid log 上追加原始记录，再给固定大小的 chunk 建轻量级 histogram 摘要和粗粒度 timestamp index，而不是为每条记录维护精确索引。结果是在不丢数的前提下达到最高 `9M` records/s 的 ingest，并把常见 observability 查询控制在秒级。

## 问题背景

论文从一个非常实际的排障流程出发。工程师在追查尾延迟问题时，往往必须同时看应用事件、syscall、packet 和硬件计数器。每个 source 都可能每秒产生数百万条记录，而真正重要的异常既稀有，又事先不知道长什么样。文中的 Redis 例子里，`9M` 个请求里只有 6 个慢请求，`35M` 个包里只有 6 个被篡改的包；uniform sampling 既保不住足够多的慢请求，也抓不到根因包。

这就形成了一个三难困境。像 InfluxDB 这样的 TSDB 通过在写路径上维护读优化索引来换取查询速度，但在 HFT 负载下，这些索引维护要么带来明显 probe effect，要么迫使系统丢数。纯 log 系统和 raw file 能吃下写入速率，但查询会退化成长时间扫描或临时脚本。FishStore 用精确的 PSF 索引保住了 ingest，但它并不自然支持任意 lookback window、percentile，或其他数据依赖型 observability 查询。

## 核心洞察

Loom 的核心判断是：observability 查询在写入时通常不需要“记录级精确索引”，只需要便宜的 chunk 级过滤。如果系统能为每个固定大小的 chunk 维护每个 bin 的 count、min/max/sum 和时间范围，那么查询时就能跳过绝大多数无关数据，同时让写路径继续接近 raw append 的成本。

与之配套的关键设计是，把 ingest 和 query 尽量解耦。Loom 不会把尚未构建完成的 chunk summary 暴露给 reader。查询可能需要额外扫描当前 active chunk，但 writer 也因此不必在热点元数据上与 reader 同步，这正是它能承受 HFT ingest 的原因。

## 设计

Loom 以 library 形式运行在 monitoring daemon 中，例如 OpenTelemetry Collector。内部有三个跨越内存和持久化存储的 append-only hybrid log：保存原始遥测的 record log、保存数值摘要的 chunk index，以及按时间粗粒度导航的 timestamp index。

record log 会把多个 source 的记录交错写入，并用 back-pointer 把同一 source 的记录串起来。写入先落到固定大小的内存块中，例如 `64 MiB`；一个块写满后，Loom 在后台 flush 它，并切换到第二个块继续写。索引单位则是更小的固定 chunk，例如 `64 KiB`。对启用索引的 source，Loom 在 chunk 填充期间增量维护 histogram-based summary，并在用户指定的 bins 之外自动补两个 outlier bins，以保持 tail 查询效率。

timestamp index 始终开启，周期性记录“记录到达”和“chunk 完成”这两类时间点，让查询能先跳到大致位置，再查看 chunk index 或 record log。查询接口刻意保持得很窄：`raw_scan` 按时间扫描 source 链，`indexed_scan` 按时间范围和数值范围过滤记录，`indexed_aggregate` 则结合 chunk summary 与少量回扫来回答 min/max/count/sum 和 percentile。reader 通过 lock-free snapshot 复制 in-memory block 的 immutable 前缀；如果复制过程中 block 已被 flush 并复用，Loom 会检测到这个 race，然后改从持久化存储继续读，而不是阻塞 writer。

## 实验评估

评估使用两个贴近真实调试流程的 case study。Redis 工作负载在三个阶段中从 `865k` records/s 增长到大约 `7M` records/s，覆盖 percentile、correlation 和 time-window scan。RocksDB 工作负载运行在 `4.7M` 到 `8M` records/s，重点是 max、percentile 和 selective-count 查询。在这两组负载上，Loom 与 FishStore 都能完整 ingest，而 InfluxDB 会丢掉 `38%` 到 `93%` 的记录。

查询延迟是 Loom 的主要优势。Redis 负载中，前两个阶段 Loom 比理想化预加载的 InfluxDB 快 `14x` 到 `97x`，比 FishStore 快 `1.5x` 到 `10x`。最难的第三阶段里，最大延迟请求查询在 Loom 上只需 `0.4 s`，而 InfluxDB-idealized 为 `4.3 s`，FishStore 为 `18.3 s`。在 RocksDB 上，Loom 把主要的 max 和 tail-latency 查询压到 `0.5` 到 `3.2 s`，而 InfluxDB-idealized 需要 `23` 到 `380 s`，FishStore 需要 `38` 到 `48 s`。

资源占用同样关键。RocksDB Phase 3 中，Loom 的 probe effect 为 `4.83%`，非常接近直接写 raw file 的 `4.10%`，明显低于带索引的 FishStore 的 `9.94%` 和 InfluxDB 的 `14.08%`。消融实验还表明，两类索引缺一不可；少了它们，查询延迟会迅速升到数百秒。

## 创新性与影响

Loom 的创新点既不是“更快的日志”，也不是“更好的 TSDB”，而是在两者之间找到一个面向 observability 的设计点：用 append-only ingest 保证 HFT 写入能力，再用 chunk 级稀疏索引覆盖 range scan、aggregate、percentile 和 time-based correlation 这些真实排障查询，同时不把高昂的精确索引成本放回写路径。

这很重要，因为很多 observability 工具今天要么过早聚合并丢弃事件，要么虽然保住了原始数据，却难以查询。Loom 证明，单机上的调试后端也可以同时做到“完整保留近期遥测”和“交互式查询”。

## 局限性

Loom 的边界是明确收窄的。它面向近期、ad hoc、单机分析，而不是长期 telemetry warehouse。它的 durability 语义也弱于传统数据库：已经向客户端确认的记录，如果在 active in-memory block flush 之前机器或 monitoring daemon 故障，仍会丢失；损失被限制在最新的 active block，大约 `64 MiB` 或几百毫秒的数据。

此外，histogram 仍然需要操作者凭领域知识配置，新建索引只作用于未来数据，而对非常短 lookback 的精确查询，FishStore 仍可能更快，因为 Loom 本来就允许 chunk 级 false positive。最后，Loom 故意把 operator 集合限制得较小；joins 和更重的分析必须放到 Loom 之外执行，分布式版本也只在 discussion 里给出了草图。

## 相关工作

- _Xie et al. (SIGMOD '19)_ - FishStore 同样面向高吞吐 observability ingest，但它的 PSF 索引是精确且刚性的；Loom 用 chunk summary 加 time index 支持 percentile 和灵活的 lookback 查询。
- _Lockerman et al. (OSDI '18)_ - FuzzyLog 证明了 append-only log 的高写入优势，而 Loom 在此基础上加入面向 observability 的稀疏索引，使日志仍能在主机本地高效查询。
- _Solleza et al. (CIDR '22)_ - Mach 强调 observability 需要专门的数据管理系统，但它更偏向 metrics storage；Loom 聚焦的是近期单机 HFT 的完整捕获与 drill-down。
- _Zhang et al. (NSDI '23)_ - Hindsight 追踪分布式系统中的稀有边缘事件，而 Loom 是单机上的本地存储与查询底座，用于保留并关联原始 HFT。

## 我的笔记

<!-- 留空；由人工补充 -->

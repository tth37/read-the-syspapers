---
title: "Towards Efficient Flash Caches with Emerging NVMe Flexible Data Placement SSDs"
oneline: "论文把 CacheLib 的小对象热写和大对象冷写分到不同 FDP reclaim units，在不改缓存架构的前提下把 Flash cache 的 DLWA 压到约 1。"
authors:
  - "Michael Allison"
  - "Arun George"
  - "Javier Gonzalez"
  - "Dan Helmick"
  - "Vikash Kumar"
  - "Roshan R Nair"
  - "Vivek Shah"
affiliations:
  - "Samsung Electronics"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696091"
code_url: "https://github.com/SamsungDS/cachelib-devops"
tags:
  - storage
  - caching
  - datacenter
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文指出，CacheLib 的 device-level write amplification 主要来自两类完全不同的写流被混在同一批 SSD block 里：小对象缓存的写入又热又随机，大对象缓存的写入则更冷、更顺序。作者用 `FDP` 的 reclaim-unit handle 把它们分开，让 Flash cache 在不重写缓存架构的前提下，把 `DLWA` 压到接近 `1`。

## 问题背景

大规模在线服务越来越依赖 Flash cache，因为 SSD 的容量成本远优于 DRAM，但 Flash endurance 仍然是硬约束。论文认为，缓存系统过去更关注命中率和 application-level write amplification，却低估了 `DLWA` 的系统意义。`DLWA` 一高，SSD 更快报废，替换成本和 embodied carbon 都会上升。

CacheLib 是最典型的例子。它把 Flash cache 分成 `SOC` 和 `LOC`：`SOC` 以 set-associative 方式重写整个 `4 KB` bucket，形成高频随机写；`LOC` 则按大 region 做 log-structured 写入，更接近顺序冷数据。两类流一旦共享 erase block，垃圾回收就会把还活着的 `LOC` 数据和已经高度失效的 `SOC` 数据一起搬走。论文给出的生产经验是，Meta 需要拿出大约 `50%` 的 Flash 容量做 host overprovisioning，才能把 `DLWA` 控在约 `1.3`。传统 SSD 不暴露 placement，而 `Open-Channel SSD` 和 `ZNS` 又太重，所以作者想要的是一种只开放 data placement、但不把整套 Flash 管理交给 host 的中间方案。

## 核心洞察

论文最重要的判断是，CacheLib 其实已经知道该怎么分流，因为 `SOC` 和 `LOC` 在架构上本来就是分开的，而且寿命与失效模式也明显不同。只要 SSD 提供一个足够轻量的物理隔离手段，`LOC` 就能基本靠顺序覆盖来自我失效，而设备内部的 overprovisioned 空间则主要拿去缓冲 `SOC` 的垃圾回收。

这正是 `FDP` 适合它的原因。`FDP` 不要求 host 直接管理 Flash block，只要求写入时附带 reclaim-unit handle (`RUH`)。因此收益不是来自构建 host FTL，而是来自避免一个明确的坏模式：让顺序的 `LOC` 数据为随机、高失效率的 `SOC` 数据买单。论文的理论模型也沿着这个思路展开，把隔离后的 `LOC` 视为 `DLWA` 接近 `1`，把剩余开销集中到 `SOC` 的 live migration 上。

## 设计

实现从 CacheLib 现有的 I/O 分层出发。作者在 SSD 写路径里加入了一个抽象层叫 `placement handle`。初始化时，allocator 先探测底层设备；如果支持 `FDP`，就给 `SOC` 和 `LOC` 分不同 handle；如果不支持，就全部退回默认 handle，原有行为不变。随后，`FDP`-aware I/O layer 把 handle 翻译成 NVMe placement directive 字段，并通过 Linux `io_uring` passthrough 发给内核。

最终策略非常克制。作者试过更动态的 data placement，以及按 reclaim-unit 边界感知的 `LOC` eviction policy，但复杂度上去了，收益并不明显。因此评测版本只做静态分流：`SOC` 和 `LOC` 各用一个 handle；设备提供 `8` 个 initially isolated `RUH`，每个 reclaim unit 约 `6 GB`。论文认为这已经足够，因为隔离后真正会产生显著 live migration 的主要只剩 `SOC`。

## 实验评估

实验平台用了两台服务器，都是双路 `24` 核 Intel Xeon Gold `6432`、约 `528 GB` DRAM，外加一块支持 `FDP` 的 `1.88 TB` Samsung `PM9D3` SSD。工作负载来自公开的 Meta KV cache trace、Twitter `cluster12`，以及一个 write-only KV 变体。

主结果很清楚。在默认的 Meta KV cache 配置下，系统使用约 `42 GB` DRAM、`930 GB` SSD cache，`SOC` 为 SSD 容量的 `4%`。运行超过 `60` 小时后，把 `SOC` 和 `LOC` 分到不同 reclaim units，可以把 `DLWA` 从约 `1.3` 降到 `1.03`。更关键的是，当 SSD 利用率从 `50%` 拉到 `100%` 时，非 `FDP` 方案的 `DLWA` 会从约 `1.3` 升到 `3.5`，而 `FDP` 版本仍稳定在 `1.03` 左右；throughput、DRAM hit ratio、NVM hit ratio 和 `ALWA` 基本不变。在 `100%` 利用率下，p99 read latency 和 p99 write latency 还分别改善了 `1.75x` 与 `10x`。

同样的趋势也出现在 Twitter `cluster12` 和 write-only KV trace 上：只要 `SOC` 维持在 `4%`，`DLWA` 在 `50%` 与 `100%` 利用率下都能逼近 `1`。被释放出来的容量还可以直接拿来做部署重构：在一块共享 `1.88 TB` SSD 的双租户 write-only KV cache 实验里，每个 tenant 各拿约 `930 GB` Flash cache，`FDP` 版本仍能把 `DLWA` 控在接近 `1`，而非 `FDP` 方案依旧在 `3.5` 左右。边界也很明确。当 `SOC` 从 `4%` 增长到 `64%` 时，`DLWA` 会从 `1.03` 升到 `2.5`；到 `90%` 和 `96%` 时，收益基本消失。论文据此进一步估算，定向 data placement 能把 SSD device cost 降低 `2x`、embodied carbon footprint 降低 `4x`，并让相同 host writes 下的 garbage-collection events 减少约 `3.6x`。

## 创新性与影响

这篇论文的创新点，不是重新发明 Flash cache，也不是提出新的 host-managed SSD 接口，而是证明了一个更克制的判断：对生产缓存来说，只要把 placement 这一步开放出来，很多原本要靠 `Open-Channel SSD` 或 `ZNS` 才能拿到的收益，其实已经可以拿到大半。它保留 CacheLib 现有的 `SOC`/`LOC` 架构，只增加一层通用的 placement handle，而且实现已经 upstream 到 CacheLib，所以说服力比一次性的研究原型更强。

## 局限性

局限主要在范围和泛化性上。论文只评测了一类 Samsung `FDP` SSD，设备提供 `8` 个 initially isolated `RUH`，所以还看不出不同 controller policy 和 reclaim-unit 几何形状会不会改变结论。收益也很依赖 workload 形状：`SOC` 必须既小又高 churn，而 `LOC` 需要保持顺序、偏冷。再加上 `FDP` 仍是新接口，host 也无法直接控制垃圾回收，operational carbon 主要还是通过 GC event 数量间接推断，因此论文给出的更像是一类 production flash cache 的强结论，而不是所有 Flash 工作负载的通用结论。

## 相关工作

- _Berg et al. (OSDI '20)_ - `CacheLib` 定义了这篇论文所依托的生产级混合缓存架构；本文的新意在于不改 `SOC`/`LOC` 组织，而是在其下层加入 `FDP` placement。
- _McAllister et al. (SOSP '21)_ - `Kangaroo` 通过重组 tiny-object cache 的内部结构来降低 Flash 开销，而本文保留现有缓存组织，改从设备侧 placement 减少 `DLWA`。
- _McAllister et al. (OSDI '24)_ - `FairyWREN` 把 `Kangaroo` 推向 `ZNS` 等新型 write-read-erase 接口；本文追求相近的耐久性收益，但选择更轻量的 `FDP`，也不要求 host 接手垃圾回收。
- _Kang et al. (HotStorage '14)_ - Multi-streamed SSD 早就提出按数据寿命给 host hint 的思路；本文可以看作是在更现代的 NVMe `FDP` 接口上，把这套想法真正落到 CacheLib 上。

## 我的笔记

<!-- 留空；由人工补充 -->

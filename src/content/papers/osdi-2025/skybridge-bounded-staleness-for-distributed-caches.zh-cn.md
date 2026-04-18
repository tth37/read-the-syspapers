---
title: "Skybridge: Bounded Staleness for Distributed Caches"
oneline: "Skybridge 以带缺口检测的写元数据复制旁路主复制流，再配合 bloom filter 与按键查询，把 TAO 缓存在 2 秒陈旧度目标内尽量留在本地命中。"
authors:
  - "Robert Lyerly"
  - "Scott Pruett"
  - "Kevin Doherty"
  - "Greg Rogers"
  - "Nathan Bronson"
  - "John Hugg"
affiliations:
  - "Meta Platforms Inc."
  - "OpenAI"
conference: osdi-2025
tags:
  - caching
  - datacenter
  - fault-tolerance
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Skybridge 是一个旁路主复制流、只复制元数据的系统，用来在 Wormhole 落后时判断 TAO 里某个具体 cache entry 是否真的过期。它把复制语义放宽为“带缺口检测的复制”，从而避免把整个落后 shard 都当成 stale。

## 问题背景

Meta 的 serving stack 横跨多个地理区域、数百万个 MySQL shards，以及大量 TAO caches。它依赖异步复制来守住延迟和可用性，但副作用是写入何时在 replica 和 cache 上可见没有硬界。论文既举了用户层面的陈旧读，也举了异步治理流程因为看不到刚写入的数据而反复重试、最终诱发 outage 的例子。

TAO 已经保存 item HLC 和 per-shard watermark，所以理论上可以做 2 秒 bounded staleness；问题在于，一旦某个 shard 的复制落后超过阈值，这个粗粒度信号就会把整个 shard 都判成“可能过期”。而 Meta 的负载高度偏读，真正最近改过的 key 只占很小一部分，于是系统会出现大量误报，带来跨区域回源和上游拥塞。更强的默认一致性语义又太贵，因此缺的是一个细粒度的 stale-key 预言机。

## 核心洞察

Skybridge 的核心主张是：给 cache 提供 bounded staleness，并不需要再造一条完整数据复制流。TAO 只需要知道某个 key 最近有没有被写过，并不需要 Skybridge 自己携带新值。因此 Skybridge 只复制 `<key, HLC>` 元数据，把数据回填继续留给现有 upstream path。

这就允许复制契约显著放宽。论文把这种语义称为 replication with gap detection（RGD）。Skybridge 可以丢数据，但必须知道自己何时有缺口，因为一旦返回“不完整”，TAO 保守回源即可；它也可以乱序复制，因为查询真正需要的只是某个 key 在区间内的最大 HLC。也就是说，系统用较弱的传输保证换来了对单个 cache entry 是否可能过期的精确信息。

## 设计

在读路径上，TAO 先计算 `HLCcache = max(HLCitem, HLCwatermark)`；若仍在 2 秒阈值内就直接返回。否则，TAO 用 lag interval 去问 Skybridge：这个 key 最近有没有写过？Skybridge 先通过预加载到本机的 bloom filter 过滤；若不足以证明新鲜，再调用 `getWrites`，拿到最新 HLC 和完整性标志。若发现更新写入，TAO 就带着条件 HLC 回源；若数据不完整，也回源，但影响范围只剩这个 key。

“完整性”来自写路径上的 Skylease。TAO writer 为 shard 打开非独占 lease，并从尚未发布的 heartbeat 槽位派生 HLC 边界附到 MySQL 事务上；若 MySQL 铸造的 HLC 落在区间外，事务会 abort。提交成功后，client 再把 `<key, HLC>` 记入 heartbeat。Skybridge 把 heartbeat 聚合成 write window，只有在 lease-holder 集合已被 seal 且相关 heartbeat 齐全时才标记为 complete；否则可以先发布 incomplete window，后续再补 complete 版本。跨区域复制层则采用拉取式短流，优先抓最新 window，并容忍重复和乱序，因为承载的只是 CRDT 兼容元数据。

## 实验评估

这篇论文最有说服力的地方，是它直接测量“写入发生 2 秒后，读能否看到它”。作者实现了一个 checker：TAO writer 把采样到的写发给 checker，checker 等到 2 秒截止点后，再对所有 region 的 TAO tiers 发起三类请求。结果显示，只依赖 Wormhole 时，TAO 的 2 秒一致性是 99.993%；接入 Skybridge 后，普通 best-effort 路径升到 99.9993%；fail-closed 更达到 99.99998%。这基本直接证明了旁路元数据通道足以消掉绝大多数长尾不一致。

流量分析同样关键。仅靠 Wormhole watermark，TAO 已能证明 99.96% 的读是新鲜的；加上本机 bloom filter 后升到 99.98%；再加上权威的 in-region Skybridge 查询，最终 99.9996% 的读都能被证明 fresh，只剩 0.0004% 必须去上游取值。与此同时，Skybridge 的 P99 replication lag 约为 700ms，P99.99 在少数尖峰外也约 1.5 秒；整个系统只占 TAO footprint 的 0.54%，并能在内存中保留 93 到 109 秒的近期写入。主要盲区是超过 retention 的长尾 lag。

## 创新性与影响

相对于 _Shi et al. (OSDI '20)_ 的 FlightTracker，Skybridge 不是 per-user 的 read-your-writes 机制；相对于 _Yang et al. (PVLDB '23)_ 这类方案，它面向的是数据库前面的缓存层而不是副本读。真正新的地方在于它把复制问题拆成“回答 freshness 需要什么”：只复制必要元数据，允许乱序与可检测丢失，再把这个弱语义通道和已有回填路径组合起来。

## 局限性

Skybridge 并没有在默认模式下把 bounded staleness 变成绝对保证。TAO 仍会对高成本检查做 rate limit，并在压力下 fail open；最强保证只在 fail-closed 请求下成立。另一个核心限制是 retention 只有大约一到两分钟，多分钟级别的长尾 lag 和没有复制订阅的低负载 shards 仍然只能回源。

实现上，它还依赖较好的时钟同步、依赖 MySQL 支持带 HLC 边界的写入，以及一个不算简单的 lease control plane。动态 resharding 和 global secondary index 仍未解决，因此当前设计更适合 shard 映射相对稳定的缓存体系。

## 相关工作

- _Shi et al. (OSDI '20)_ - FlightTracker 用 per-user ticket 提供 read-your-writes，而 Skybridge 用更弱但可默认开启的时间界限覆盖所有写入。
- _Yang et al. (PVLDB '23)_ - PolarDB-SCC 也利用细粒度陈旧度信息，但目标是单个数据库的强一致副本读，而不是全球分布式缓存层级。
- _An and Cao (PVLDB '22)_ - MCC 通过 eviction 和 version selection 策略改善 cache consistency；Skybridge 则新增一条旁路元数据流来处理 invalidation lag。
- _Loff et al. (SOSP '23)_ - Antipode 传播 causal lineage 来实现跨服务因果一致性；Skybridge 刻意退到 bounded staleness，以换取在 Meta 默认规模上的可部署性。

## 我的笔记

<!-- 留空；由人工补充 -->

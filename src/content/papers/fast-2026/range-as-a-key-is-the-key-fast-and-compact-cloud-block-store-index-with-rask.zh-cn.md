---
title: '"Range as a Key" is the Key! Fast and Compact Cloud Block Store Index with RASK'
oneline: "RASK 直接索引连续块区间，并用 log-structured leaf 与 range-aware 维护机制，把云块存储索引内存占用最高降到 98.9%。"
authors:
  - "Haoru Zhao"
  - "Mingkai Dong"
  - "Erci Xu"
  - "Zhongyu Wang"
  - "Haibo Chen"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Alibaba Group"
conference: fast-2026
category: indexes-and-data-placement
tags:
  - storage
  - datacenter
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`RASK` 是一个面向云块存储的内存有序索引，它把“连续块区间”而不是“单个块”当作 key。它把 `ART` 内部节点与 log-structured leaf 结合起来，再用 ablation-based search、two-stage garbage collection 和 range-conscious split/merge 处理重叠与碎片化。基于真实生产 trace，论文报告它能把索引内存占用最高降低 `98.9%`，并把吞吐提升到最多 `31.0x`。

## 问题背景

Alibaba Cloud EBS 把活跃块存储索引放在 DRAM 中，而这个索引已经成了主要内存消费者：论文报告大约占用节点内存的 `57.1%`，部分集群甚至会因为没有足够内存为新数据建立索引，而让约 `35%` 的物理存储实际上无法使用。问题在于粒度错了。现有设计按单个 LBA 或很小的写请求片段建索引，但对 Alibaba Cloud trace 做 compact 之后，`65.0%` 到 `81.5%` 的写请求都属于更长的 consecutive write 序列，Tencent、Google、Meta 的 trace 也类似。直接改成 range key 虽然能省 entry，却会带来新区间覆盖旧区间，以及叶子边界把长写入切碎这两个问题。

## 核心洞察

这篇论文最重要的洞察是：把叶子节点看成“区间版本的小型 append-only log”，而不是“每次写入都要立刻整理干净的集合”。系统先廉价 append，再在叶子满了时批量回收那些已经被新版本完全覆盖的旧区间；读路径则优先检查新条目，并持续删去目标区间中已经找到最新值的部分，所以 overlap 变成了“读时容易容忍、写时容易延后清理”的状态。另一个关键点是 split 和 merge 必须对区间边界敏感，否则 range index 很快又会退化回大量碎片。

## 设计

`RASK` 的上层骨架使用 `ART`，真正承担区间管理工作的则是定制的 log-structured leaf。每个 leaf 用一个 anchor key 标识，也就是该叶子负责区间里最小的 left bound；叶子内部的 range/value 按 append 顺序保存。读请求先找到“anchor 不大于目标 left bound 的最后一个叶子”，若目标范围跨越多个叶子，再沿 doubly linked leaf list 继续向右扫描。

读路径的关键是 ablation-based search。每次查询都会维护一个有序的 `Unfound List`，表示目标区间里尚未找到最新值的子区间。系统按从新到旧的顺序扫描叶子条目；一旦某个条目和 `Unfound List` 相交，RASK 就把交集加入结果，并从列表里删掉对应部分，因此目标范围一旦重建完整，搜索就能提前结束。

写入时，新 range 会直接 append 到目标 leaf。若 leaf 已满，RASK 先执行 lightweight GC，用一个 left-bound map 快速清理那些“明显被同 left bound 的更新完全覆盖”的旧条目；论文重放结果显示，这类情况平均占所有可回收条目的 `73.8%`。如果还不够，就进入 normal GC：它从后往前扫描叶子，同时维护 `NonOverlap List` 来识别那些被多个后续写共同覆盖的旧条目。需要 split 时，RASK 会优先从非重叠边界里挑 split point；若 workload 持续让用户写入跨越相邻叶子并形成碎片，系统就通过 `Nfrag` 触发 merge/resplit。对于 value 本身也编码连续物理位置的系统，上层还要提供 `MergeRange` 和 `DivideValue` 回调。并发控制采用 optimistic locking，但跨叶子读并不是完全全局原子的 snapshot，实验中观测到的不一致比例约为 `0.0394%`。

## 实验评估

主评测使用了来自 Alibaba Cloud 四个集群、`1.8k` 个虚拟盘的 post-compaction trace，对比对象除了原始 EBS index，还包括九种有序索引。在完整 Alibaba 数据集上，RASK 的吞吐达到这些 baseline 的 `2.76x` 到 `37.8x`，相对原始 EBS index 也有 `1.15x` 到 `1.82x` 的提升。更核心的是内存结果：RASK 只需要原始 EBS index 大约 `19.9%` 的内存，也只占各类 baseline 内存的 `1.15%` 到 `54.7%`。尾延迟也明显改善：相对这些 baseline，RASK 可将 `P99` 延迟降低 `23.9%` 到 `97.6%`，把 `P99.999` 延迟降低 `34.2%` 到 `99.7%`。

机制拆解也支持作者的解释。以一个 `ART` 起点为基线，log-structured leaf 单独就把吞吐提升 `1.50x`、把内存降低 `90.3%`；normal GC 再带来 `70.6%` 的吞吐提升；lightweight GC 额外贡献 `24.1%`；ablation-based search 再增加 `12.6%`；range-conscious split 可把内存再降 `26.0%`；merge/resplit 还能继续节省 `7.70%` 的内存。敏感性分析也相对诚实：当平均写入长度不超过 `2` 时，RASK 虽然仍比其他 ordered index 至少快 `1.56x`，但会比原始 EBS index 慢 `6.64%`。

这套思路并不只适用于 Alibaba。对 Tencent EBS trace，RASK 相对 baseline 带来 `2.35x` 到 `49.21x` 的吞吐提升；把 RocksDB 的 MemTable 换成 RASK，在 Meta Tectonic trace 上可获得最高 `7.46x` 的吞吐提升；在 Google flash-cache 场景模拟里，吞吐也提高 `1.52x` 到 `37.52x`。这些结果基本支持论文主张：只要存储元数据天然是 range-heavy 的，原生理解区间的索引就能同时更省内存、也更快。

## 创新性与影响

RASK 的创新并不只是“把点换成区间”。真正有价值的是一整套让 range key 能站上 hot path 的维护机制：用 log-structured leaf 延后 overlap 清理，用 ablation-based read 高效恢复每个子区间的最新值，再用面向 range 边界的 split/merge 尽量保持整段区间不被碎片化。相对于 ordered point index，论文说明 eager 或 lazy overlap handling 的额外成本仍然太高；相对于 interval-style index，RASK 则会主动回收被覆盖的旧区间。

因此，这篇论文很可能会影响那些需要管理“长物理 extent 元数据”的系统：云块存储、flash cache，以及把逻辑块映射到文件的 metadata service。更广义的启发是，一旦 workload 天然以 range 为单位运行，就没有必要再把 point granularity 一路强行保留到内存索引层。

## 局限性

论文最强的胜利区间仍然是 range-write-heavy workload。如果写入主要是非常小、非常稀疏的随机块，RASK 相对通用 ordered index 仍然有优势，但相对一个高度手工优化、面向 point update 的 incumbent 设计，收益会缩小甚至消失。换句话说，这篇论文证明的是“利用 workload 结构取胜”，而不是给所有 point index 提供一个无条件替代品。

此外，它也有集成成本和语义成本。RASK 目前只是 in-memory index，持久化仍由上层系统负责。若 value 本身编码了区间信息，应用还必须正确实现 `DivideValue` 和 `MergeRange` 回调，并发控制也只保证 per-leaf 一致性，而不是完全原子的跨叶子 snapshot。

## 相关工作

- _Zhang et al. (FAST '24)_ — Alibaba Cloud EBS 的论文描述了当前按 LBA 建索引的体系；RASK 则把它改造成原生的 range-key 设计。
- _Leis et al. (ICDE '13)_ — `ART` 提供了 RASK 所依赖的紧凑 trie-style 内部节点，但并不处理区间 overlap、covered-range 回收或碎片化问题。
- _Wu et al. (EuroSys '19)_ — `Wormhole` 是高性能 ordered point index；RASK 说明一旦 workload 需要处理区间重叠，再强的 point index 也会在 eager 或 lazy overlap handling 上付出高成本。
- _Christodoulou et al. (SIGMOD '22)_ — `HINT` 是面向 interval query 的现代内存区间索引，而 RASK 关心的是覆盖式写入场景，在这种场景里被覆盖的旧区间应该被回收，以节省内存并加速查询。

## 我的笔记

<!-- 留空；由人工补充 -->

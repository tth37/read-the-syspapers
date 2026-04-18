---
title: "Cache-Centric Multi-Resource Allocation for Storage Services"
oneline: "HARE 把 cache 与其能节省的 I/O、网络和 RU 一起分配，用“先收割后再分配”把 cache 敏感性变成兼顾公平与吞吐的系统增益。"
authors:
  - "Chenhao Ye"
  - "Shawn (Wanxiang) Zhong"
  - "Andrea C. Arpaci-Dusseau"
  - "Remzi H. Arpaci-Dusseau"
affiliations:
  - "University of Wisconsin–Madison"
conference: fast-2026
category: cloud-and-distributed-storage
tags:
  - storage
  - caching
  - datacenter
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`HARE` 把多租户存储里的 cache 当成“能改变其他资源需求的控制杆”，而不是一个单独分区的内存池。它先把额外 cache 带来的 I/O、网络或后端读额度节省量“收割”出来，再把这些资源重新分给所有租户，同时保证每个租户至少不低于等分基线。论文分别在基于 Redis+DynamoDB 的 `HopperKV` 和基于 NVMe 的 `BunnyFS` 上验证了这个思路，报告了最高 `1.9x` 与 `1.4x` 的性能提升。

## 问题背景

论文要解决的是一个很现实但长期被拆开处理的问题。现代多租户存储服务共享的并不只是单一瓶颈：云端 KV 服务可能同时共享 cache、虚机网络带宽、DynamoDB 的读写额度，本地文件系统则可能同时共享 page cache、SSD I/O 带宽和工作线程 CPU 周期。经典的 `DRF` 只适用于“资源线性、彼此独立”的场景，但 cache 不满足这两个前提。cache 的收益曲线天然是非线性的，而且 cache 变大后，一个租户对 I/O、网络或后端读配额的需求会跟着下降。

这使几类常见做法都不理想。把所有资源都均分，公平性没问题，但不同租户的 working set 和 miss penalty 差异很大，系统效率会被压低。把 `DRF` 用在非 cache 资源上，再额外跑一个 `Memshare` 之类的 cache 分配器，也还是不够，因为它无法把“更多 cache 带来的 I/O 或网络节省”继续回流给其他租户。至于完全共享的全局 cache，看起来最省事，却会让 miss ratio 受到邻居干扰，从而破坏 sharing incentive。

## 核心洞察

这篇论文最重要的观点是：cache 的价值不只是“命中率更高”，而是“能释放别的稀缺资源”。如果把更多 cache 给一个更敏感的租户，它对 I/O、网络或数据库读额度的需求可能下降到足以腾出一部分资源；系统再把这部分节省量重新分配给其他租户，就能在不低于基线公平性的前提下让所有租户一起变快。

`HARE` 用一个很清晰的目标来表达这件事：最大化所有租户中最小的 normalized throughput。这里的 normalized throughput 指的是某个租户当前吞吐除以它在“所有资源平均分配”时的吞吐。因此，系统必须先保证最小 normalized throughput 不低于 `1`，即任何租户都不比均分基线更差；然后再尽可能把这个最小值往上推。若所有租户对 cache 的敏感度都差不多、没有可做的有利交易，`HARE` 会自然退化成 `DRF`；若敏感度不同，cache 就会成为可以“收割”额外资源的来源。

## 设计

`HARE` 对每个租户需要三类输入：一条 cache 大小到 miss ratio 的曲线，也就是 `MRC`；一个非 cache 资源的 demand vector；以及每种资源对应的 `alpha_i`，表示 cache hit 能省下这类资源的比例。

算法分成两个阶段。第一阶段是 harvest。系统考虑把一小块 cache 从租户 A 挪给租户 B，然后计算两件事：A 为了维持基线吞吐，需要多少额外资源补偿；B 因为拿到更多 cache，又能释放多少资源。若只有一种 cache-correlated resource，释放量大于补偿量就是一笔可做的交易。若存在多种相关资源，论文增加了一个关键规则：优先围绕“当前最稀缺、最难收割到的系统级资源”来选交易，因为它最终会决定第二阶段的整体提升上限。第二阶段是 redistribute，把收割到的资源按各租户当前持有量加权分回去，让所有租户按相同比例增吞吐。

真正让设计落地的是两个系统实现。`HopperKV` 给每个租户一个独立 Redis 实例，并用自定义 Redis module 管理四类资源：cache、网络、DynamoDB 读额度和写额度。它用 ghost cache 在线构造 `MRC`，再用 `1/32` 的 spatial sampling 把开销压到每次 key 访问 `25 ns` 以下、误差低于 `1%`。控制面每 `20` 秒基于最近一分钟统计重新运行一次 `HARE`。为了增强鲁棒性，分配器只在预测收益超过 `5%` 时才应用新分配，用 `16 MB` 粒度迁移 cache，并给低 miss ratio 的 `MRC` 额外加上 `1%` 的保底值。`BunnyFS` 则把同样的控制逻辑搬到 `uFS` 风格的本地文件系统里，管理 page cache、SSD 带宽和 worker CPU 周期。

## 实验评估

论文的评测覆盖面足够大，能真正检验核心主张。`HopperKV` 的默认 AWS 配置是 `2 GB` cache、`50 MB/s` 网络，以及每秒 `1K` 的 DynamoDB 读写额度。在双租户微基准里，`HARE` 的行为与其理论描述一致：没有合适 cache 交易时，它就和 `DRF` 一样；一旦 working set 差异变大，它在某一组实验里把最小 normalized throughput 提升了 `56%`，整体最高能比基线高 `63%`。在改变热点分布的实验中，当 `Memshare+DRF` 过度偏向 cache 梯度更陡的租户时，`HARE` 仍能在保持公平的同时把吞吐再提高最多 `38%`。

更关键的是大规模实验。`16` 租户的 YCSB scaling benchmark 中，纯 `DRF` 相对基线能做到 `1.2x-1.9x` 的 normalized throughput，而 `HARE` 达到 `1.6x-2.7x`，且 `16` 个租户里有 `13` 个在 `HARE` 下拿到自己的最佳吞吐。动态实验也很说明问题：`DRF` 因为只调无状态资源，所以反应更快；但 `HARE` 借助分块 cache 迁移，仍能平滑收敛，并把提升推到最高 `1.9x`。在六条 Twitter 生产 cache trace 上，除去一个已经把客户端虚机打满的租户外，`HARE` 至少带来 `38%` 提升；对应地，`DRF` 只有 `16%`，而 `Memshare+DRF` 还会让其中一个工作负载下降 `4%`。

`BunnyFS` 说明这个思路不只适用于云 KV。其 `32` 租户 Optane 文件系统实验里，`DRF` 只带来 `10%` 提升，而 `HARE` 让大多数租户提升约 `40%`。在动态文件系统实验中，`HARE` 始终优于另外两种公平方案，也避免了“共享 LRU + DRF”导致的公平性崩塌。整体来看，这些结果较好地支持了论文的中心论点：把 cache 与其相关资源联合分配，确实优于简单均分和 cache-oblivious 的公平分配。

## 创新性与影响

相对于经典 `DRF`，这篇论文的新意不是简单把 cache 填进 demand vector，而是提出了一套面向 cache-correlated demand 的公平性目标和收割/再分配机制。相对于只看 miss ratio 的 cache allocator，它真正补上的则是“从 cache 优化走向端到端多资源分配”的那座桥。

因此，这篇论文并不只是 `Redis` 或 `uFS` 的个案优化。它更像是一种可复用的控制面思路，适合云缓存、文件系统，以及同时管理硬件资源和按量计费后端资源的存储服务。

## 局限性

作者明确承认 `HARE` 是 greedy algorithm，并不保证全局最优。因为 `MRC` 的形状可以很复杂，论文只证明了算法会收敛，并且不会比等分基线或“等分 cache 的 `DRF`”更差，而没有声称求解了最优分配问题。

部署层面也有限制。本文里的 `HopperKV` 只处理单机多租户，多节点版本仍是未来工作。`BunnyFS` 主要面向读路径，写负载基本被当成“不可缓存的读”处理。适应过程也是周期性的而非瞬时完成，所以一旦涉及 cache quota 迁移，`HARE` 的反应速度必然慢于纯 `DRF`。最后，虽然论文用两个风格差异很大的系统证明了方法的普适性，但毕竟也只有两个系统，因而“通用性”更多体现在模式层面，而不是已经被许多生产实现验证。

## 相关工作

- _Ghodsi et al. (NSDI '11)_ - `DRF` 处理的是彼此独立的资源主导份额公平，而 `HARE` 面向的是非线性、受 cache 影响的相关资源需求。
- _Cidon et al. (USENIX ATC '17)_ - `Memshare` 只按 cache utility 重分配 cache，`HARE` 还会把 cache 节省下来的后端资源一起重新分配。
- _Park et al. (EuroSys '19)_ - `CoPart` 只协调 LLC 与内存带宽这一组相关资源，`HARE` 则把这个思路扩展到多种 cache-correlated 的存储资源。
- _Lee et al. (SOSP '25)_ - `Spirit` 也联合分配相互依赖的资源，但它关注的是 remote memory 场景下的 cache 与网络，而不是带有多类相关资源的存储服务。

## 我的笔记

<!-- 留空；由人工补充 -->

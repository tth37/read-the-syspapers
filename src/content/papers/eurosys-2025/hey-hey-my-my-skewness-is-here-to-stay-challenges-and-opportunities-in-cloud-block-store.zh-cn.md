---
title: "Hey Hey, My My, Skewness Is Here to Stay: Challenges and Opportunities in Cloud Block Store Traffic"
oneline: "这篇覆盖 6 万 VM 的 EBS 实测表明，云块存储里的偏斜不是暂态噪声，而是长期结构性现象；均衡、限流、迁移和缓存都得围着热点重新设计。"
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

这篇论文的核心判断很直接：在超大规模云块存储里，流量偏斜不是偶发长尾，而是系统常态。作者基于约 6 万台 VM、14 万块虚拟盘的生产流量，把四类症状连到了一起：hypervisor 里的 worker 失衡、硬阈值限流浪费带宽、segment 迁移抖动，以及缓存没有真正抓住热点。

## 问题背景

Alibaba Cloud 的 EBS 并不是没有防护。hypervisor 里，虚拟盘的 queue pair 会按 round-robin 绑定到 worker thread；存储集群里，BlockServer 会周期性迁移 segment；VM 有 page cache，服务端还有 read prefetch。即便如此，生产环境里仍然能看到很重的失衡。论文给出的例子是，最热 worker thread 平均要承受最冷线程 2.6 倍的流量；在一个数据中心里，1% 的 VM 贡献了 75.4% 的读流量和 42.6% 的写流量；VM 读流量的 50%ile peak-to-average ratio 甚至达到 30,649。

真正的问题在于，现有控制逻辑默认工作负载大致平稳、读写差不多、各层局部优化就够了。过去相关研究要么规模较小，要么只看 compute 侧或 storage 侧，所以没有把热点如何从 VM、VD、QP 一路传到 storage cluster 和 LBA 空间讲透。

## 核心洞察

论文最重要的判断是：云块存储里的 skewness 必须被当成结构性约束，而不是靠周期性 heuristic 慢慢抹平的噪声。一旦流量同时在 VM 到 VD、VD 到 QP、segment 到 BS，以及 LBA 热点这些层级聚集，只看当前平均值的控制回路就会持续做错决策。

四个案例其实都在犯同一种错。round-robin 默认 QP 之间差不多热；硬阈值 throttle 默认其他 VD 的闲置资源无关紧要；importer 选择默认当前最闲的 BS 下一轮还会闲；read prefetch 默认热点主要来自读。论文的数据逐项推翻了这些前提，所以更合理的方向是更细粒度的 dispatch、面向未来的预测，以及围绕持久热点的缓存管理。

## 设计

这是一篇大规模测量研究，加上一组基于 trace 的设计推演。作者研究的 EBS 采用 compute-storage disaggregation：VD 暴露最多 8 个 queue pair，hypervisor 的 worker thread 轮询处理，BlockServer 把 32 GiB 的 segment 映射成文件偏移，ChunkServer 再把数据落到 SSD。论文采了两类主数据：一类是 1/3200 采样的 per-IO trace，另一类是完整的 second-level metric。

作者用 cumulative contribution rate 看空间偏斜，用 peak-to-average ratio 看突发，用 coefficient of variation 看失衡，再用 write-to-read ratio 看读写主导关系。基于这些指标，论文依次研究四条控制链。hypervisor 负载均衡部分，把热点节点分成 QP 太少、单 QP 热 VM、以及多 QP 但仍集中到少数 QP 三类；第三类最常见，根源是 VM 到 VD 的流量本就不均匀，加上 Linux `blk-mq` 没把多队列并行真正用起来。throttle 部分量化某个 VD 被限流时，兄弟 VD 还剩多少买来的带宽和 IOPS 没用掉。storage balance 部分模拟不同 importer 选择策略，并重新审视只按写流量迁移的做法。缓存部分则量化 LBA 热点，再比较 FIFO、LRU 和 FrozenHot 式 frozen cache。

## 实验评估

这篇论文最有说服力的地方，是它把问题诊断得很透。基础统计已经说明 skewness 既严重又偏向读流量。某个数据中心里，1% 的 VM 就拿走了 75.4% 的读流量。到 hypervisor 这一层，1 分钟粒度下 worker-thread CoV 的中位数读写分别达到 0.7 和 0.5；42.6% 的节点里，单个 QP 就吃掉了超过 80% 的读流量。作者还模拟了每 10 ms 做一次 QP-to-worker rebinding，但只有 29.9% 的节点真正受益，这说明周期性 rebinding 太粗了。

throttle 部分也很扎实。当多 VD VM 里的某个虚拟盘被 throttled 时，剩余可用资源的中位数对 throughput 是 61.6%，对 IOPS 是 74.7%，说明硬阈值确实会把买下来的能力闲置掉。limited lending 在大多数模拟里能带来收益，lending rate 取 0.8 时，85.9% 的 multi-VD-VM 样本都能缩短 throttle 时间；但也存在反例，因为借出资源的 VD 自己可能重新变热，所以预测和隔离不是锦上添花，而是方案本身的一部分。

存储侧结果说明现有 heuristic 很脆弱。当前 importer 选择策略的 normalized migration interval 中位数是 0.24，几乎和随机选择一致，而理想化 oracle 能把它拉到 0.48。与此同时，96.8% 的存储集群都满足 read CoV 不低于 write CoV；85.2% 的集群里，segment 的中位数 `|wr_ratio|` 大于 0.9，说明 segment 往往天然偏读或偏写。缓存部分则表明，64 MiB 的 hottest block 在中位数情况下只占 VD LBA 空间的 3.0%，却能承载 18.2% 的访问，而且 93.9% 的 hottest block 是 write-dominant。Frozen cache 只有在缓存足够大时才真正接近 FIFO 和 LRU。整体上，论文对问题的证据很强，但对解法的证据主要还是 trace-driven simulation。

## 创新性与影响

它的创新点不在某个单独算法，而在于把一整套 EBS 控制问题放进同一个观测框架里。和以往的 storage trace 研究相比，这篇论文覆盖更完整、粒度更细，也把负载均衡、限流、迁移和缓存四件事收束到同一个解释上：需求在空间和时间上的集中，正在系统性地击穿平均化设计。

它给出的价值也很明确：现有 control loop 需要按热点而不是按平均值重写，下一步的重点是更低开销的 dispatch、带预测能力的 balancing 和 lending，以及默认承认热点长期存在的持久缓存。

## 局限性

作者明确承认了边界条件。这是单一云厂商的 EBS，观测窗口只有白天 12 小时，应用类型是推断出来的，细粒度 trace 也只采了 1/3200，因此仍可能漏掉更短时的行为，或者混入平台特有因素。

更重要的限制在于验证方式。论文提出的 rebinding、limited lending、prediction-based migration 和 cache placement，大多只在生产 trace 上做了模拟，没有真正在线上闭环部署。预测精度和训练成本、公平性和隔离、缓存一致性以及 live migration 开销，都是实打实的落地障碍。

## 相关工作

- _Lee et al. (SYSTOR '17)_ - Lee 等人分析的是企业虚拟桌面场景下的存储流量，而这篇论文覆盖的工作负载更杂、规模更大，也因此看到了更强的读偏斜和突发性。
- _Li et al. (TOS '23)_ - Li 等人的 comparative study 主要落在 cloud block storage 的存储侧，这篇论文则把分析继续推进到 hypervisor 的 worker thread、queue pair 和 throttle 行为。
- _Mao et al. (ICPADS '22)_ - Mao 等人研究大规模云块存储里的 traffic imbalance 优化，这篇论文进一步用更大规模的生产 trace 说明了 prediction-based balancing 为什么值得做、又为什么难做。
- _Qiu et al. (EuroSys '23)_ - FrozenHot Cache 提出无淘汰式缓存管理，而这篇论文把这个想法放到 EBS 的 LBA 热点和持久缓存部署权衡里重新检验。

## 我的笔记

<!-- 留空；由人工补充 -->

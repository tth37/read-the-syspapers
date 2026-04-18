---
title: "PRED: Performance-oriented Random Early Detection for Consistently Stable Performance in Datacenters"
oneline: "PRED 一边按并发流数缩放 RED 标记斜率，一边用保守的 A/B 试探调整队列目标，让交换机在动态流量下保持稳定低时延。"
authors:
  - "Xinle Du"
  - "Tong Li"
  - "Guangmeng Zhou"
  - "Zhuotao Liu"
  - "Hanlin Huang"
  - "Xiangyu Gao"
  - "Mowei Wang"
  - "Kun Tan"
  - "Ke Xu"
affiliations:
  - "Huawei Technologies"
  - "Renmin University of China"
  - "Tsinghua University"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - networking
  - datacenter
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

PRED 不换掉标准 RED/ECN，而是让它以可控方式自适应。它先按交换机测得的并发流数缩放 RED 标记斜率，再用保守的 A/B 试探把队列推向当前工作负载真正想要的稳态位置。这样既优于静态 RED，也避开了 DRL 调参带来的尾部不稳定。

## 问题背景

论文抓住的是数据中心拥塞控制里的一个现实矛盾：很多新方案效果很好，但需要改主机协议栈、NIC 或交换机，部署周期很长；而 RED 加 ECN 已经广泛存在于现网里。如果能把现有 RED 调好，收益会更容易落地。

静态 RED 之所以不够用，是因为它隐含地只选了一个稳态队列长度，而真实流量一直在变。第一，并发流数增大时，瓶颈队列会随之变长，所以固定参数要么在低并发时过早标记、掉利用率，要么在高并发时留太多队列。第二，不同流大小分布偏好的队列目标不同。短流占主导的工作负载更希望别太早打 ECN，避免瞬时突发被惩罚；大流占主导的工作负载则更希望把站立队列压低。ECNsharp 这类方法只是在少数状态上换固定阈值，ACC 虽然用 DRL 自动调参，但论文认为它既跟不上并发流数的快速变化，也无法避免偶尔选到糟糕参数，于是尾部 FCT 变差。

## 核心洞察

核心洞察是把 RED 从传统的 `(minK, maxK, maxP)` 两点式写法，改写成点斜式 `(minK, lambda)`，其中 `lambda = maxP / (maxK - minK)`。这样一来，`lambda` 的含义就很直接：它单调地控制最终收敛到的队列长度。

一旦这么看，问题就自然拆成两部分。并发流数变化是快而且结构明确的，所以应当显式建模：交换机只要估出 `N`，就可以按 `N` 去缩放 `lambda`。至于当前工作负载到底偏好更长还是更短的队列，这件事难以预先建模，适合在线用小步验证去试。PRED 因此分成两个模块：Flow Concurrent Stabilizer（FCS）解决并发度问题，Queue Length Adjuster（QLA）解决工作负载偏好的问题。

## 设计

FCS 直接在交换机里数流。对于每个端口和每个 `T_FCS` 时间窗口，PRED 把包的五元组加上窗口序号哈希到 bitmap 中，统计新出现的流数，并用 `N = max(n_last, n)` 作为当前并发流估计。随后，它用一个单调函数 `f(N)` 去乘 RED 的斜率 `lambda`。理论上 `f(N)` 只要随 `N` 增大即可，但作者发现 `f(N) = N` 比 `sqrt(N)` 或 `N^2` 更适合真实流量，因为分析模型里的理想同步假设并不完全成立。

QLA 则在并发度之外继续微调队列目标。它把归一化 goodput 和平均队列长度组合成 utility function，比较 `lambda + delta` 与 `lambda - delta` 两个相邻设置。为了降低噪声影响，QLA 会做两轮受控试验，只有两轮都支持同一方向时才更新参数。作者刻意选择 AIAD，而不是 binary search 或学习式预测，因为他们更看重稳定性。当 `lambda` 已接近下限时，QLA 转而调 `minK`，让短流突发型工作负载可以容忍稍大的瞬时队列。

原型实现也遵循这个划分。FCS 运行在 Tofino 数据平面，QLA 因为 Tofino 1 的 stage 不够而放在控制平面。整个原型大约用了 350 行 P4 和 300 行 Python。

## 实验评估

实验包括真实 Tofino 测试床和 NS-3 大规模仿真。测试床结果表明，PRED 在吞吐接近线速的同时，压住了“并发流数越多、队列越长”的趋势。相对静态阈值基线，它把交换机队列从大约 25 个包降到 15 个包，约降低 66%，短流 FCT 最多降低 80%。在 WebSearch 风格流量里，由于 QLA 位于控制平面，PRED 需要大约 10 秒收敛，但过程是稳定的。

128 主机 leaf-spine 仿真更能说明设计本身。在 WebSearch 工作负载、90% 负载下，PRED 相对 ECN、ECNsharp、CoDel 把小流 99th FCT 降低了 68% 到 80%，而大流平均 FCT 只增加不多。消融实验显示，FCS 已经抓住了相对静态 RED 的主要收益，但要适应不同流大小分布，还需要 QLA。与 ACC 的对比更关键：即使让 ACC 在训练和测试时使用同一条 trace，PRED 仍把 99th FCT 降低了 34%，同时显著缩短了队列长度分布的尾部。到 100 Gbps、数千并发流时，PRED 依然优于 ECN 系列基线，只是无法像 HPCC 那样把队列压到近零。

## 创新性与影响

PRED 的新意不在于提出新的拥塞信号，而在于重新组织旧机制的控制逻辑。相对 _Yan et al. (SIGCOMM '21)_ 的 ACC，它把 DRL 换成了显式并发度稳定器加小步验证式搜索。相对 _Zhang et al. (CoNEXT '19)_ 的 ECNsharp，它不是再多加几组固定阈值，而是让 RED 参数连续自适应。相对 _Li et al. (SIGCOMM '19)_ 的 HPCC，它接受更高一些的队列，以换取只改交换机即可部署。

这也是论文最可能留下影响的地方：它把 RED 调参重新表述为稳态队列控制问题，并证明在静态阈值和黑盒学习控制器之间，存在一条更可解释、更容易落地的路线。

## 局限性

最重要的限制是调节范围。作者实验显示，当同一瓶颈上长期并发的大流超过约 32 条时，PRED 无法继续把队列稳定在理想区间内。作者认为这种场景不常见，但这说明 PRED 不是万能解。另一个现实限制是原型实现：由于 Tofino 1 的 stage 不够，QLA 被放到了控制平面，因此收敛速度慢于论文真正想要的全数据平面实现。

FCS 本身也仍然带有启发式性质。`f(N) = N` 虽然实验上有效，但它是基于简化流体模型再经实验选择出来的，论文没有给出 FCS 和 QLA 组合后的严格稳定性证明。评估重点也集中在队列和 FCT，对多租户公平性、极端流数估计误差等上线问题讨论较少。

## 相关工作

- _Yan et al. (SIGCOMM '21)_ — ACC 也试图自动调 RED，但它依赖 DRL 处理队列和速率特征；PRED 则用直接的并发流测量和保守的 A/B 控制来降低尾部不稳定性。
- _Zhang et al. (CoNEXT '19)_ — ECNsharp 在 ECN 上叠加瞬时和持续拥塞阈值，而 PRED 保持标准 RED 语义，只让参数连续自适应。
- _Zhang et al. (SIGCOMM '21)_ — TCD 为无损网络设计了新的拥塞检测逻辑；PRED 则选择挽救已经广泛部署的 RED/ECN 机制。
- _Li et al. (SIGCOMM '19)_ — HPCC 借助 INT 和主机侧速率控制把队列压得更低，而 PRED 用交换机侧增量改造换取更强的可部署性。

## 我的笔记

<!-- 留空；由人工补充 -->

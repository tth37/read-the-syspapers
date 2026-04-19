---
title: "SuperFE: A Scalable and Flexible Feature Extractor for ML-based Traffic Analysis Applications"
oneline: "SuperFE把特征提取策略拆成交换机侧元数据聚合和SmartNIC侧流式计算，让ML流量分析在不绑死某个模型的前提下跟上 multi-100Gbps 链路。"
authors:
  - "Menghao Zhang"
  - "Guanyu Li"
  - "Cheng Guo"
  - "Renyu Yang"
  - "Shicheng Wang"
  - "Han Bao"
  - "Xiao Li"
  - "Mingwei Xu"
  - "Tianyu Wo"
  - "Chunming Hu"
affiliations:
  - "Beihang University"
  - "Tsinghua University"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696081"
tags:
  - networking
  - smartnic
  - ml-systems
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SuperFE 把 feature extraction 编译成交换机侧分组加 SmartNIC 侧流式归约。它的 MGPV 格式让每个 packet 的 metadata 只在最粗粒度上保存一次，再用索引挂到更细粒度的 group key 上，因此多粒度 extractor 不必复制交换机状态。原型能用 9-101 行策略代码复现 10 个已有提取器，把送往 SmartNIC 的流量压低 80% 以上，让 Kitsune 的特征误差控制在 4% 以下，并把吞吐提升到接近软件方案的两个数量级。

## 问题背景

论文指出，ML-based traffic analysis 前面的 feature extractor 已经比 detector 更像瓶颈。很多现有系统仍依赖端口镜像、后端落盘和服务器侧重组统计量来生成 feature vector。这样做够灵活，但在 multi-100Gbps 链路上会同时耗掉带宽、存储和 CPU。

只靠硬件加速也不够，因为已有 switch 或 SmartNIC 方案往往只支持一类 feature 或一个固定模型。可真实应用横跨 website fingerprinting、botnet detection、covert channel detection 和 intrusion detection，分组方式与统计量差异很大。问题不只是把一个 detector 加速，而是做出一个既有硬件规模又有应用通用性的 feature extractor。

## 核心洞察

SuperFE 的核心判断是，feature extraction 最适合被写成分组流处理，再按硬件能力拆开。`groupby` 和 `filter` 简单、固定，而且能明显缩小后续数据量，适合放在 switch；`map`、`reduce`、`synthesize`、`collect` 需要更丰富的计算和状态管理，适合放在 SmartNIC。

真正关键的是边界怎么画。把 raw traffic 继续送给 SmartNIC，会把原来的瓶颈原样搬过去；要求 switch 直接算完整 feature，又超出它的计算和内存能力。SuperFE 只在交换机上批处理最小必要的 packet metadata，并保留多粒度分组关系，再让 SmartNIC 用省内存的 streaming algorithms 完成剩余统计。

## 设计

SuperFE 给用户的是一套高层 policy interface，而不是 P4 或 Micro-C 细节。packet 被抽象成 tuple，里面既有 header fields，也有交换机补上的 metadata，比如 packet size 和 arrival timestamp。同一套 `groupby`、`filter`、`map`、`reduce`、`synthesize`、`collect` 既能表示每流统计量，也能表示 histogram 或方向序列。

交换机侧的核心机制是 MGPV。若沿用 `*Flow` 式 grouped packet vector，每多一种 grouping granularity，就要多复制一份 packet metadata；像 Kitsune 这种需要 host、channel、socket 三层粒度的场景会迅速失控。MGPV 只按最粗粒度分组，每个 packet 的 metadata 只存一次，再附一个索引指向和 SmartNIC 同步的 finest-granularity key table。这样 SmartNIC 收到数据后还能切回更细的 group，却不必接收重复记录。系统再用 short/long buffer 适配流长尾分布，并通过碰撞、buffer 填满和超时触发 eviction；aging 则由 recirculated internal packets 在数据平面里完成。

SmartNIC 负责收尾计算。SuperFE 用 Micro-C 实现剩余算子，但用的是 streaming algorithms，而不是精确多遍统计：均值和方差采用 Welford 单遍更新，基数估计采用 HyperLogLog 风格方法，`ft_hist`、`ft_percent`、`f_cdf` 这类分布特征则建立在按组维护的 histogram 上。为了适配 Netronome NFP，系统还复用了交换机算好的 hash，用硬件线程隐藏访存延迟，尽量消掉昂贵的 division，并通过 ILP 在 CLS、CTM、IMEM、EMEM 之间布置 group table。

## 实验评估

原型部署在一台 3.3 Tb/s Intel Tofino 交换机和两张 40Gbps Netronome NFP-4000 SmartNIC 上，工作负载来自真实的 MAWI、enterprise、campus trace，再加上 4 个公开应用数据集。对 TF、N-BaIoT、NPOD、Kitsune 这几类系统，论文报告它能够处理 multi-100Gbps 原始流量，并以约 Gbps 的速率输出 feature vector；作者把整体收益概括为相较软件提取器接近两个数量级的吞吐提升。

这些结果和机制基本对得上。policy 改写能控制在 9-101 行，说明接口不只是单点 demo。MGPV 把送往 SmartNIC 的包率和带宽都降到原来的 20% 以下，而且不会像 GPV 那样随着 grouping granularity 增多而线性膨胀。SmartNIC 侧的 streaming algorithms 把内存占用压在设备能力范围内，性能还能近似线性扩展到两张卡共 120 个 cores；所有底层优化开启后，吞吐最多再提升 4x。精度方面，Kitsune 的特征误差低于 4%，下游检测准确率依然较高。

## 创新性与影响

SuperFE 的新意不在于单独使用 programmable switch 或 SmartNIC，而在于把两者连成一条完整的 feature extraction pipeline：上层是可编译到两端的 policy language，中间是支持多粒度分组却不复制元数据的 MGPV，下层是一套围绕 streaming reduction 设计的 SmartNIC runtime。它给 traffic-analysis 系统提供的不是单个加速点，而是一种可复用的切分方式。

## 局限性

MGPV 建立在粒度关系能排成 dependency chain 的前提上；若未来应用需要更一般的 dependency graph，论文目前还没有直接方案。系统加速的也只是 feature extractor，不包含后面的 detector，因此真正部署时后端仍要有足够算力消费输出向量。

实验很扎实，但还不是完整生产环境。作者的真实测试床最高回放到 40Gbps，更大的流量主要靠 switch 侧 packet amplification 研究，所以 multi-100Gbps 结论并不是原生多百 G 端到端链路上的直接展示。与此同时，SuperFE 接受了近似：histogram、cardinality 和单遍统计都不是严格精确算法，只是论文证明它们把误差压在了可接受范围内。

## 相关工作

- _Barradas et al. (NDSS '21)_ - FlowLens 在数据平面里加速 packet distribution 特征；SuperFE 覆盖的特征空间更广。
- _Siracusano et al. (NSDI '22)_ - N3IC 围绕 Neural Network Interface Cards 重构 learned pipeline；SuperFE 则把 detector 保持开放，重点做可复用 extractor。
- _Dong et al. (USENIX Security '23)_ - HorusEye 是面向 IoT 恶意流量检测的专用框架；SuperFE 是更通用的 feature-extraction substrate。
- _Yan et al. (NSDI '24)_ - Brain-on-Switch 把 learned analysis 压得更靠近 switch；SuperFE 通过 switch 与 SmartNIC 分工换取更高灵活性。

## 我的笔记

<!-- 留空；由人工补充 -->

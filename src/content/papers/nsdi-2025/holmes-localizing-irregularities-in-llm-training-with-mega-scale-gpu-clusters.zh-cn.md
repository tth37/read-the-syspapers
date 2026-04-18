---
title: "Holmes: Localizing Irregularities in LLM Training with Mega-scale GPU Clusters"
oneline: "Holmes 只看通信算子日志，用自动调参的随机森林和并行组图搜索，在几十秒内定位拖慢 LLM 训练但不触发失败的异常设备。"
authors:
  - "Zhiyi Yao"
  - "Pengbo Hu"
  - "Congcong Miao"
  - "Xuya Jia"
  - "Zuning Liang"
  - "Yuedong Xu"
  - "Chunzhi He"
  - "Hao Lu"
  - "Mingzhuo Chen"
  - "Xiang Li"
  - "Zekun He"
  - "Yachen Wang"
  - "Xianneng Zou"
  - "Juncheng Jiang"
affiliations:
  - "Fudan University"
  - "Tencent"
  - "University of Chicago"
conference: nsdi-2025
tags:
  - llm-training
  - gpu
  - observability
  - networking
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Holmes 处理的是一种不会让训练直接崩掉、却会持续烧掉 GPU 时间的故障形态：迭代还在继续，但某些 step 会无声地变慢。它只记录通信算子，用自动调参的随机森林找出异常算子，再结合通信算子图和跨迭代证据定位最可能出问题的 GPU 或网络设备。在生产 trace 和 production-style testbed 上，Holmes 报告了最高 97.21% 的定位准确率，以及 30.3 秒的端到端定位时间。

## 问题背景

这篇论文的出发点，是大规模 LLM 训练里一个比“训练失败”更常见、但以往工作很少认真处理的现象。训练任务在 352-8192 GPUs 上运行时，并不只是偶尔因为硬故障而中断；更常见的是训练还在继续，但某些 iteration 明显比参考值更慢。作者把这种现象定义为 irregularity。它没有 error log，不会触发传统 failure pipeline，却会在几个月的训练周期里不断累计额外时间。

论文给出的生产数据说明，这不是边缘问题。在一个包含超过 10,000 张 H800 的集群中，irregularity 的出现频率比 failure 高出几个数量级；当训练规模达到 8192 GPUs 时，仅一个月里由 irregularity 引入的额外训练时间就达到 32.38 小时。更麻烦的是，人工定位它往往比处理 failure 更慢，86.2% 的 irregularity 定位时间超过 4 小时。

难点在于，真正异常的往往只是一个设备，但症状会沿着训练同步关系传播。一个 GPU 在某次 `All-Reduce` 前算慢了，整个 DP 组里其他 GPU 都会一起等它，于是很多健康 GPU 也会表现出“这一轮很慢”。因此，系统不能只回答“哪些 GPU 看起来慢”，而必须回答“哪一个 GPU、NIC、链路或交换机最可能是真正根因”。如果误判并隔离了一台正常机器，代价就是直接损失宝贵的训练算力。

## 核心洞察

Holmes 的核心判断是：通信算子正好处在一个非常合适的观测边界上。只看 iteration time 太粗，看全量 operator trace 又太贵；而通信算子既足够稀疏，能低开销持续记录，又足够有信息量，能把计算侧和网络侧的异常都折射出来。如果某个 GPU 在 collective 之前计算变慢，通信算子的开始时间会被推迟；如果是网络异常，通信算子的持续时间和 peer 行为也会一起变化。

第二个关键洞察是，异常算子不能孤立地看。它们的意义取决于训练并行结构：data parallel、tensor parallel、expert parallel、pipeline parallel 会决定谁与谁同步、谁与谁成对通信。Holmes 因此不是做一个通用 anomaly detector，而是把这些结构编码成 communication operator graph，再针对 collective communication 和 point-to-point communication 分别采用 BFS 与 DFS 进行回溯，最后跨多个 iteration 聚合证据。

## 设计

Holmes 的第一步是 `CommOps` logger。它不记录所有计算算子，而只记录 `All-Reduce`、`All-Gather`、`All-to-All`、`Send`、`Recv` 等通信算子，并为每条记录保存通信模式、执行时长、时间戳、communicator、rank、数据量等字段。论文的论点是，这已经足够保留 irregularity 的传播结构，同时避免全量 profiling 带来的训练扰动。

第二步是异常算子检测。当 iteration monitor 发现一个 `delta`-irregular iteration 之后，Holmes 会对其中相关通信算子做异常检测。作者使用的是随机森林，而不是简单的 3-sigma 规则，因为不同算子的绝对时长差异极大，只看倍率或离群程度很容易误判。输入特征除了单个算子的 mean、std、z-score、quartiles、IQR、rank、消息大小和通信模式，还包含 iteration time 与时间窗口内平均算子时长等全局信息。考虑到长时间训练会出现分布漂移，Holmes 不是反复重新标注并训练模型，而是检测诸如平均 iteration time 的漂移，再直接平移树模型里相关 feature 的阈值。

第三步是根因定位。Holmes 构建了 communication operator graph，把算子与参与它的 GPU 连接起来；为了避免图规模爆炸，它进一步利用训练并行中天然存在的 communication group，把 GPU 压缩成 DP/TP/EP 等组。对于 collective communication，Holmes 在组内做 BFS：如果一组里的同一个 collective operator 全都异常，更可能是通信本身有问题；如果其中有一份是正常的，就沿着那台 GPU 往前回溯，推断其他 GPU 其实是在等它之前的慢操作。对于 pipeline 中的 P2P 通信，Holmes 则沿 peer operator 做 DFS，不断跨 stage 追溯到更早的异常点，或者确认问题出在这条 P2P 网络路径本身。

最后一步是跨迭代分析。Holmes 用异常算子持续时间与端到端 iteration time 的相关性来定义 irregularity rate，再把这份证据累积到候选 GPU、NIC、链路与交换机上。为了避免“中心设备因为被很多路径共享而总被冤枉”，系统引入了 MAP 估计和 topology-aware decay factor，对网络设备的分数做先验和衰减修正。最终输出的是一个按概率排序的设备列表，而不是一次性给出一个没有置信度的硬判断。

## 实验评估

论文的评估基础比较扎实：一部分来自为期三个月、覆盖超过 10,000 GPUs 的生产训练 trace，硬件包括 H800 和 ConnectX-7 Dx，软件栈包括 Megatron-LM、DeepSpeed 与 NCCL；另一部分来自 production-style testbed，用于评估检测和定位时延。先看检测器本身，Holmes 的随机森林在不同规模下 F1 都高于 0.89，在 4096 GPUs 上达到 0.93，明显优于 3-sigma、KNN 和文中的 SVM 基线。自动调参也确实有价值：在一个持续一个月的 3072-GPU 训练中，Holmes 的 F1 始终高于 0.917，而未经调参的 RF 从 0.922 逐步下降到 0.906。

真正关键的是端到端定位。Holmes 在 2048 GPUs 时达到 97.2% 的定位准确率；即便扩展到 8192 GPUs，准确率仍有 88.2%，而改造自微服务异常定位的 RW 和 Seer 只有 78.0% 与 80.7%。在更复杂的混合并行场景下，它在 3D、4D、6D parallelism 上的 median accuracy 分别是 94.6%、89.6% 和 86.0%，说明这套方法并不依赖某一种特定并行配置。

在实时性方面，结果也支撑论文主张。单个 GPU log 的检测延迟始终低于 400 ms；progressive fetching 把每次定位需要传输的数据量从 24.36 GB 压到 0.84 GB，下降 96.6%。端到端定位时间随集群规模从 2048 GPUs 到 8192 GPUs 增长时，只从 15.5 秒上升到 30.3 秒；3072 GPUs 的平均值是 21.2 秒。案例分析也很直观：在一个 3072-GPU 训练里，Holmes 只访问了 106 台相关 GPU 的日志，就把根因收敛到 GPU 2574；隔离其所在节点后，平均训练吞吐从 85.43 提高到 90.62 samples/s。

## 创新性与影响

这篇论文的新意不在于“随机森林”本身，也不在于“图搜索”本身，而在于它把两者都放在了 LLM 训练的通信算子边界上，并把并行训练结构直接编码进定位流程。Holmes 处理的不是一般意义上的性能异常，而是训练系统里一种非常具体、非常昂贵、却又没有 error signal 的 irregularity；它把这个问题从“依赖资深工程师经验”变成了一个可在线运行的系统问题。

这使它对大规模训练平台运维、训练系统研究者和可靠性工程师都有价值。此前关于训练可靠性的讨论更偏向 crash、checkpoint 和 recovery，而 Holmes 提醒人们：在超大规模 GPU 集群里，“不中断但持续变慢”的训练也可能是更大的资源浪费来源。

## 局限性

Holmes 依赖为每个训练任务单独准备的随机森林模型，而训练数据来自人工标注的 `CommOps` 日志。自动调参能减少频繁重训，但不能消除初始标注成本；论文也没有证明模型在不同集群、不同通信库版本或不同训练框架之间能否直接迁移。

另外，实时性实验虽然运行在 production network 上，但原型采用的是 CPU-based log writer 来模拟 GPU training process，而不是完整地在线部署到真实训练任务中。这足以说明 analytics path 很快，但说服力仍弱于完全 in-situ 的线上验证。论文也承认，随着 GPU 数量和并行维度上升，准确率会下降；当 `delta` 小于大约 1.04 时，正常 iteration fluctuation 已经足以淹没信号，系统难以区分“正常波动”和“真正 irregular”。最后，作者在 discussion 中也明确指出，若想进一步利用 operator implementation 差异、resource metrics 或更细粒度的网络 telemetry，日志开销会迅速变大，这条 trade-off 还没有被彻底解决。

## 相关工作

- _Jiang et al. (NSDI '24)_ - `MegaScale` 研究的是超过 10,000-GPU LLM 训练的扩展与失败诊断，而 `Holmes` 关注的是不会触发 failure log 的 silent irregularity。
- _Hu et al. (NSDI '24)_ - `Characterization of Large Language Model Development in the Datacenter` 刻画了数据中心中 LLM 开发与训练的行为特征，而 `Holmes` 把其中被忽视的 step-time irregularity 进一步做成在线定位问题。
- _Gan et al. (ASPLOS '19)_ - `Seer` 用神经网络分析云微服务中的 QoS 异常，`Holmes` 则利用通信算子结构和训练并行语义，在大规模 GPU 集群里获得更强的可解释性与扩展性。
- _Liu et al. (ICSE-SEIP '21)_ - `MicroHECL` 通过应用图定位微服务故障；`Holmes` 延续了图定位思路，但把图的节点和边重建为混合并行训练里的 collective/P2P 通信关系。

## 我的笔记

<!-- 留空；由人工补充 -->

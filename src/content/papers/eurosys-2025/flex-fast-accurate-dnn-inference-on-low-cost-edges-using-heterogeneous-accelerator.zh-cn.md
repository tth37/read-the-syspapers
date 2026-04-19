---
title: "Flex: Fast, Accurate DNN Inference on Low-Cost Edges Using Heterogeneous Accelerator Execution"
oneline: "Flex 先离线学会每层在 CPU 与低成本加速器上的时间、精度和输出匹配规律，再按输入动态切分 DNN，兼顾时延、精度与能耗。"
authors:
  - "Tanmoy Sen"
  - "Haiying Shen"
  - "Anand Padmanabha Iyer"
affiliations:
  - "University of Virginia"
  - "Georgia Institute of Technology"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696067"
tags:
  - ml-systems
  - hardware
  - energy
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

低成本加速器能把推理跑快，但低精度也会改变模型输出，而且最合适的 CPU/LCA 切分会随输入变化。Flex 先离线学习时间、精度和输出匹配关系，再在线用启发式或 SAC 强化学习为每个输入挑选层放置方案或单一切分点。论文在三台 Android 手机上报告，相比已有方法平均推理时间最高可降 39%，精度最高可升 22%，能耗最高可降 61%；`Flex-RL+` 与 Oracle 的推理时间只差约 4.2%。

## 问题背景

论文面对的是低成本边缘设备，而不是高端加速卡。很多手机和端侧设备虽然带有 GPU、TPU、DSP 或 NPU，但为了省电和控成本，这些加速器常常采用更低精度算术。于是问题很直接：整网放到加速器上虽然快，却可能把答案算偏；全部留在 CPU 上虽然稳，却把时延和能耗收益都让掉了。作者测得，整网跑在 LCA 上时，相比纯 CPU 最多会损失 7.3% 精度。

作者认为，前作 MLMP 的静态分区前提本身就不成立。论文穷举多个模型的层分配后发现，即便输入分布仍与训练数据相近，Oracle 切分也会随输入变化；在 ImageNet、HAR、SQuAD 上，不同类别输入偏好的 CPU/LCA 切分差异也很明显。再加上不同层迁移到 LCA 后带来的时间收益与精度损失并不均匀，而 CPU/LCA 边界的数据传输有时比邻近层计算还贵，真正要解决的是一个受精度、deadline 和内存约束的逐输入切分问题。

## 核心洞察

Flex 的关键判断是：逐输入异构执行不必在线穷举，只要先学会几个便宜但够用的预测信号。它关注三件事：某个层分配会带来多少时间变化、多少精度变化，以及 CPU 和 LCA 的执行结果在单层或整网层面是否大概率一致。

有了这些信号，在线策略就能很轻。那些预测为输出一致的层更适合迁移，网络尾部的重层通常更能换来时延收益；但因为 CPU/LCA 往返通信不便宜，最优方案常常不是任意交错的逐层摆放，而是选择一个通信更便宜的切分点做连续划分。Flex 的核心不是更激进地搜索，而是把搜索改写成学习驱动的打分问题。

## 设计

Flex 先做离线 profiling。作者随机生成层分配方案，测量真实推理时间和精度，再训练两个随机森林回归器：`RF-T` 预测时间，`RF-A` 预测精度。它们的输入包括模型结构特征、候选分配和当前输入样本；时间标签里已经计入 CPU/LCA 之间的通信开销。随后，Flex 再训练两个轻量分类器：`layer-classifier` 预测在单层迁移到 LCA 时输出是否还能和纯 CPU 一致，`model-classifier` 则预测整网纯 CPU 和纯 LCA 的结果是否一致。

启发式路径分成三种。`Flex-L` 优先迁移那些预测为输出一致、且更省时间、更少伤精度的层；必要时也会继续迁移不一致的层。`Flex-D` 为了减少 CPU/LCA 往返，只找一个切分点：若用户更看重精度，它会先移动前部较浅的层；若更看重时延，它就从尾部重层开始，结合 `model-classifier`、`RF-T`、`RF-A` 和内存约束去找最划算的切分点。`Flex-B` 再把层分组，先做组级二分，再在线性扫描组内位置，以进一步压低搜索开销。

`Flex-RL` 和 `Flex-RL+` 则用 soft actor-critic 取代启发式。状态由 deadline、accuracy target 和可用内存组成，动作就是层分配；违反约束时给大负奖励，否则按论文的精度/时延目标给奖励。`Flex-RL` 用估计值训练，`Flex-RL+` 用真实值训练。作者还使用 curriculum learning，让 RL 先学简单模型，再迁移到结构相近但更复杂的模型；同时把所有层同时驻留在 CPU 和 LCA 上，避免在线搬运模型权重。

## 实验评估

实验覆盖八个模型，横跨视觉、NLP 和时间序列任务，硬件是三台 Android 手机：一台 Snapdragon 778G 设备、一台 Pixel 6 TPU 手机，以及一台 Snapdragon 888G 手机。每个模型处理 100 到 500 个输入，deadline 在 0.5 到 5 秒之间，精度要求在 80% 到 95% 之间变化。

主要结论是：输入感知切分明显优于静态切分和模型选择式 baseline。相对 ALERT-T、Mistify、AMPT、ALERT-A、MLMP-T、MLMP-A 和一个简单的后缀迁移 strawman，`Flex-D` 的 timeliness guarantee ratio 提高了 11% 到 35%，inference time 降低了 11% 到 34%。`Flex-L` 和 `Flex-RL` 在 `Flex-D` 之上还能再拿到 2% 到 3% 的 timeliness 收益，而 `Flex-B` 在更低搜索开销下，又比 `Flex-D` 多出 2% timeliness 与 3% 推理时间收益。

最强版本是 `Flex-RL+`。相对 `Flex-RL` 和 `Flex-L`，它的 timeliness guarantee 分别高 2.5% 和 2.8%，推理时间分别低 3% 和 4%，因为训练时直接使用了真实时间和真实精度。论文还给出它与 Oracle 的差距：精度和 accuracy guarantee 大约低 2.5%，推理时间慢约 4.2%。决策开销同样亮眼：`Flex-D` 比 `Flex-L` 低 48%，`Flex-B` 比 `Flex-D` 再低 41%，`Flex-RL+` 比 `Flex-B` 再低约 90%。能耗排序基本和推理时间一致，摘要把整体收益概括为相对已有方法最高可降 61%。

## 创新性与影响

Flex 的新意不在于「把模型切到异构处理器上跑」这件事本身，而在于把输入感知、精度建模、通信感知切分和低开销学习型控制器合成到同一个运行时里。MLMP 会静态切 CPU/NPU，ALERT 和 Mistify 更偏向多模型选择，`μLayer` 这类工作主要优化时延；Flex 关心的是低成本加速器会改变模型语义输出这件事。

这让论文对移动端 ML runtime 和嵌入式 AI 部署都很有参考价值。它给出的核心经验是：低精度加速器不是单纯更快的协处理器，调度器必须同时考虑输出保真度与吞吐。

## 局限性

Flex 的准备成本并不低。离线阶段里，回归器大约要 5 到 6 小时，`layer-classifier` 需要 2.45 小时，`model-classifier` 需要 4.2 小时，RL 训练大约 7 小时。虽然这些代价发生在线下，但它更像按设备、按模型家族定制的部署流程，而不是即插即用方案。

系统效果也明显受估计器质量影响。`RF-T` 和 `RF-A` 的 MAPE 分别是 7.14% 和 9.56%，`layer-classifier` 准确率在 87% 到 93% 之间，`model-classifier` 在 84% 到 92% 之间。作者明确指出，这些误差解释了 Flex 和 Oracle 之间的一部分差距；如果 `model-classifier` 判断失误，`Flex-RL+` 可能比 Oracle 慢 9%，精度低 4.6%。另外，RL 版本本质上仍是 best effort，而不是硬实时保证。

最后，最干净的 baseline 其实是 MLMP。其他一些对照需要把模型选择类系统强行改造成带随机切分的 CPU/LCA 方案，因此可比性没有那么强。论文也只覆盖三台 Android 设备，跨更多加速器栈的可迁移性仍待验证。

## 相关工作

- _Tan and Cao (IPSN '21)_ - MLMP 也研究 CPU 与 NPU 之间的 DNN 切分，但它使用静态分配和有限搜索；Flex 把切分改成逐输入、并把通信代价显式纳入决策。
- _Wan et al. (ATC '20)_ - ALERT 通过在多模型之间做选择来满足时延、精度和能耗目标；Flex 不换模型，而是对同一个模型动态改变 CPU/LCA 执行计划。
- _Guo et al. (NSDI '21)_ - Mistify 面向资源受限设备选择压缩模型变体；Flex 则试图在不更换模型的前提下，仅通过改变层放置位置拿到更好的时延/精度折中。
- _Kim et al. (EuroSys '19)_ - `μLayer` 研究 CPU/GPU 协同的端侧推理加速，但 Flex 额外建模了低成本加速器引入的精度变化，并围绕用户给定的约束做逐输入调度。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "FailureMiner: A Joint Key Decision Mining Scheme for Practical SSD Failure Prediction and Analysis"
oneline: "FailureMiner 保留靠近分类边界的健康 SSD，再从随机森林中挖出可解释的联合阈值规则，在生产环境里比既有 RF 与 LSTM 基线更准确地预测并分析失效模式。"
authors:
  - "Shuyang Wang"
  - "Yuqi Zhang"
  - "Haonan Luo"
  - "Kangkang Liu"
  - "Gil Kim"
  - "JongSung Na"
  - "Claude Kim"
  - "Geunrok Oh"
  - "Kyle Choi"
  - "Ni Xue"
  - "Xing He"
affiliations:
  - "Samsung R&D Institute China Xi'an, Samsung Electronics"
  - "Tencent"
  - "Samsung Electronics"
conference: fast-2026
category: flash-and-emerging-devices
tags:
  - storage
  - observability
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

FailureMiner 把 boundary-preserving downsampling 和联合决策挖掘结合起来。它不直接交付完整随机森林，而是提炼出少量既能预测 SSD 失效、又能解释原因的阈值组合。基于腾讯生产 Telemetry 数据，这些规则达到 `82.2%` precision 和 `29.6%` recall，优于 RF、CNN-LSTM、WEFR 与 MVTRF。

## 问题背景

企业 SSD 失效预测同时受两类现实约束。第一，故障极少，粗暴 downsampling 会删掉最接近 failure pattern 的健康样本，让模型失去学习分类边界最关键的例子。第二，运维真正需要的不是“哪个属性重要”，而是具体哪组阈值对应什么故障、是否紧急。既有 feature selection 还可能把只在组合中有用的辅助属性一起删掉，于是模型在边界上既不稳，也不够可解释。

## 核心洞察

论文最核心的判断是：真正该被压缩的单位不是 feature，而是 decision set。FailureMiner 为每种失效模式保留相似的健康样本，让模型学会细边界，再从 true positive 路径里挖出既高影响、又经常共同出现的阈值判断。这样既能保留单独看起来偏弱、但组合后很强的信号，又能过滤掉频繁出现却没什么价值的分裂，并自然落到 NAND `UECC`、DRAM ECC 与 `CapHealth` 异常这类可命名模式上。

## 设计

FailureMiner 先构造 `3`、`7`、`15` 天窗口的 `Delta_w A` 时间特征。随后它只对 failed 样本聚类，使用 JIC 选出的失效敏感属性做归一化后再跑 K-means，默认 `N = 50`。每个 cluster 的 boundary 定义为该簇 failed 样本到质心的最大距离。healthy 样本只有落在这个 boundary 之内才会被分到该 cluster，另外再加入少量随机 healthy 样本防止过拟合。之后系统在每个 cluster 上用全部原始属性和时间特征分别训练随机森林。

接着它只检查能正确识别 failed SSD 的树路径。每个 split 都会得到一个基于 SHAP 改造的 decision-level impact score，超过阈值的 split 成为候选 key decision。系统再用类似 Apriori 的方式扩展共现决策集，按“平均 impact × 共现次数”给集合打分，留下少量真正有联合贡献的规则。在腾讯数据上，`117,404` 个原始树决策最终被压缩成 `3` 条 strong rules。

## 实验评估

主要评估使用腾讯生产 Telemetry：两年左右、超过 `350,000` 块 Samsung PM9A3 SSD、`70` 多百万条日志，以及 `788` 条失效记录；训练用第 `1-13` 个月，测试用第 `14-23` 个月。论文还在阿里巴巴公开 SMART 数据集上验证泛化性，该数据集包含 `20,000` 块 SSD 的 `10` 多百万条日志。基线包括 RF、CNN-LSTM、WEFR 和 MVTRF。

在腾讯数据上，FailureMiner 达到 `82.2%` precision、`29.6%` recall 和 `0.61` `F0.5`，而 RF 为 `55.4%` / `20.4%` / `0.41`，MVTRF 为 `68.1%` / `19.6%` / `0.46`。论文把整体收益总结为 precision 平均提升 `38.6%`、recall 平均提升 `80.5%`。ablation 也说明两个组件都必要：单独的 boundary-preserving downsampling 相比 RF 提升 `21.7%` precision 和 `13.7%` recall，单独的 joint key extraction 则提升 `20.4%` 和 `25.5%`。此外，规则运行代价很低，报告的 prediction time 只有 `6` 秒，而 RF 为 `167` 秒；腾讯线上部署一年多，提前识别出一百多块故障 SSD。

## 创新性与影响

它的创新不在更复杂的分类器，而在把“可部署、可读的联合规则”当成主要产物。相较 RF 或 LSTM 预测器，FailureMiner 把解释性前置，而不是事后补图。相较 WEFR 这类特征筛选，它强调应该删的是坏决策，不一定是坏特征。最终得到的规则可以直接对应 NAND 缺陷、DRAM 缺陷，以及 capacitor 或 `PLP` 退化，对运维比一个黑盒分数更可操作。

## 局限性

这套方法依赖丰富且语义清晰的 Telemetry。它在腾讯的 Samsung 属性上最有解释力，而在阿里 SMART 数据上，规则退化成 `r198`、`r174` 这类泛化字段，可读性明显下降。另一个限制是 recall 仍然有限；`29.6%` 在 precision-first 场景里已经很强，但 strong rules 仍会漏掉大部分故障。阈值也只在两个数据集、且主要是一类 SSD 家族上验证，换设备或换站点仍需重新训练和校验。

## 相关工作

- _Alter et al. (SC '19)_ - 研究现场 SSD 失效并使用 RF 风格模型做预测，而 FailureMiner 保留 RF 框架但把输出压缩成运维可读的联合规则。
- _Lu et al. (FAST '20)_ - SMARTer 侧重时间特征与深度模型，FailureMiner 则把 boundary-preserving sampling 和决策级可解释性放在中心位置。
- _Xu et al. (DSN '21)_ - WEFR 通过集成特征排序去掉噪声属性；FailureMiner 认为更好的做法是在决策级保留辅助信号、再筛除无效阈值。
- _Zhang et al. (FAST '23)_ - MVTRF 使用多视角时间特征解释故障的 what/when/why，而 FailureMiner 更强调把共现阈值组合直接抽成 failure pattern。

## 我的笔记

<!-- 留空；由人工补充 -->

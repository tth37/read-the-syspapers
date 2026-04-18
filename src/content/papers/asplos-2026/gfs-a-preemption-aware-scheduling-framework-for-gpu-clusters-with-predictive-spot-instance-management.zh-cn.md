---
title: "GFS: A Preemption-aware Scheduling Framework for GPU Clusters with Predictive Spot Instance Management"
oneline: "GFS 先预测各租户 HP GPU 需求，再动态收放 spot 配额，并按 checkpoint 损失做抢占，来同时压低驱逐率和排队时间。"
authors:
  - "Jiaang Duan"
  - "Shenglin Xu"
  - "Shiyou Qian"
  - "Dingyu Yang"
  - "Kangjin Wang"
  - "Chenzhi Liao"
  - "Yinghao Yu"
  - "Qin Hua"
  - "Hanwen Hu"
  - "Qi Wang"
  - "Wenchao Wu"
  - "Dongqing Bao"
  - "Tianyu Lu"
  - "Jian Cao"
  - "Guangtao Xue"
  - "Guodong Yang"
  - "Liping Zhang"
  - "Gang Chen"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "The State Key Laboratory of Blockchain and Data Security, Zhejiang University, Hangzhou, China"
  - "Alibaba Group, Hangzhou, China"
  - "Zhejiang University, Hangzhou, China"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3760250.3762231"
code_url: "https://github.com/Sjtucitlab/Spot"
tags:
  - scheduling
  - gpu
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

GFS 解决的是一个很现实的 GPU 集群运营问题：云厂商想把空闲 GPU 作为 spot 容量卖出去，但静态配额加被动调度会让 spot 任务既不稳定，也无法真正把昂贵 GPU 吃满。论文给出的办法是做一个闭环：先预测高优先级任务的未来需求分布，再把预测变成随时间变化的 spot 配额，最后只有在 checkpoint 感知的代价模型判断损失最小时才执行抢占。

## 问题背景

这篇论文的出发点是，LLM 兴起之后，生产 GPU 集群的负载形态已经明显变了。作者对比 2020 和 2024 的集群轨迹后发现，2024 年几乎都是整卡甚至整机请求，任务运行时间也长得多，8 卡 gang-scheduled 任务的排队尤为明显。在这种环境里，“先给高优先级任务预留足够 GPU，剩余部分再卖给 spot” 这套老办法会迅速失效，因为需求峰值更尖、更持久，而且不同组织的模式差异很大。

失效主要体现在两头都亏。若 provider 把静态 spot 配额放得太大，高优先级任务一来就会大规模驱逐 spot 任务；论文报告 spot 驱逐率四周平均约为 49.5%，繁忙时段峰值超过 93%。若 provider 过于保守，A100、A800、H800 这些高端 GPU 池的分配率又长期低于 80%，昂贵资源被白白浪费。再加上 first-fit 会造成节点碎片化，并把不同类型任务混放到一起，后续高优先级任务更容易触发代价更高的抢占。因此，真正的系统问题不是“把一个队列排得更快”，而是怎样把预测、配额控制和放置决策统一起来，让 HP 任务守住 SLO，同时让 spot 任务得到真正可用的保证窗口。

## 核心洞察

论文最核心的判断是，GPU 集群里 spot 不稳定，本质上更像一个控制回路问题，而不只是局部放置策略问题。只要调度器拿到的是未来 HP 需求的分布，而不是单个点估计，它就能在给定保证率下先留出安全容量，再把剩余库存暴露给 spot 任务，并在抢占时显式考虑 checkpoint 损失和节点历史驱逐情况。

这样做有效，是因为每一层都在修补不同的损失来源。预测解决的是高峰期过度承诺 spot 配额的问题；动态配额解决的是“预测虽然保守，但现实里驱逐已经很低、spot 队列却越积越长”的问题；带代价意识的放置和抢占则把抽象配额真正落到节点选择上，既保留未来 HP 任务可用的打包空间，又避免反复伤害同一批 spot 任务。GFS 的贡献不在某个单点技巧，而在把这三层合成一个可运行的闭环系统。

## 设计

GFS 由三个模块组成。`GDE` 负责预测各组织的 HP GPU 需求。它的模型 OrgLinear 会把每个组织的历史需求拆成 trend 和 cyclical 两部分，再加入 hour、weekday、holiday 等时间特征，以及 cluster、GPU model 等业务上下文特征。更关键的是，它不只输出均值，还输出方差，因此 GFS 可以直接取某个高分位作为安全需求上界，用来做配额规划。

`SQA` 把这些预测变成具体的 spot 配额。它先把各组织在目标保证率下的高分位需求上界聚合到集群层面，算出未来几个小时内可保证的空闲 GPU 库存；然后再乘上一个安全系数 `eta`。但 `eta` 不是常数：如果最近的真实驱逐率明显高于目标，GFS 就缩小 `eta`；如果驱逐率已经很低，但 spot 最大排队时间依然很长，GFS 就放大 `eta`。这一步把长时间尺度的预测和短时间尺度的运行反馈接了起来。

`PTS` 是运行时调度器。对非抢占式放置，它按三个维度给候选节点打分：GPU packing、同类任务共置，以及短期和长期驱逐历史感知。若 HP 任务仍然无法放下，GFS 才考虑抢占。这里的关键启发式是，先按“自上次 checkpoint 以来会浪费多少工作”给 spot 候选受害者排序，再挑选综合驱逐影响和浪费 GPU 时间最小的节点执行抢占。spot 任务自身永远不会通过抢占方式获得资源，只有 HP 任务能触发抢占。

## 实验评估

论文的评估同时包含生产部署和基于真实轨迹的仿真，这一点很重要，因为 forecasting 和 quota control 只有放到真实集群动态中才有意义。在生产环境里，GFS 部署到最大集群后，各类 GPU 上的 spot 驱逐率都降到 10% 以下，其中 A100 的驱逐率下降了 67.81%。分配率也明显提升：A800 提升 22.79%，A100 提升 14.03%，论文据此估算每月可带来约 459,715 美元收益。

在一个含 2,296 张 A100 的仿真集群上，作者把 GFS 与 YARN-CS、Chronus、Lyra、FGD 做了低、中、高三档 spot 负载比较。对 HP 任务，最稳的结论是排队时间：在保持 p99 JCT 不变且都为 29,304.5 秒的前提下，GFS 把平均 HP JQT 降低了 60.17%-70.81%。对 spot 任务，平均来看，JCT 降低 14.24%，JQT 降低 44.10%，驱逐率降低 33.01%。以中等负载为例，GFS 把 spot JQT 压到 575.4 秒，而各基线仍在 1,211.7 到 5,450.5 秒之间。

我觉得最有说服力的是消融实验，因为它能说明每个模块都不是装饰。若把 OrgLinear 换成“用上周峰值做预测”的朴素方法，spot JQT 会从 575.4 秒暴涨到 10,502.4 秒，驱逐率也从 1.21% 升到 8.08%。若关闭 SQA 的反馈调节，只保留静态安全系数，spot JQT 也会上升到 2,174.3 秒。再把调度器的非抢占和抢占逻辑分别简化，spot 性能还会继续恶化。相比只看总表里的 headline number，这组消融更直接支持了论文的核心主张。

## 创新性与影响

和 _Gao et al. (SoCC '21)_ 相比，GFS 不只是又一个 deadline-aware scheduler；它把需求分布预测和 spot 配额自适应引入了 GPU 集群的 provider 侧控制面。和 _Bai et al. (OSDI '20)_ 相比，它的新意不在于让上下文切换更快，而在于先决定“该不该抢占、该抢占谁、放到哪里”。和 _Athlur et al. (EuroSys '22)_ 这类从应用端适配 spot 的系统相比，GFS 把优化目标从单个训练作业，提升到了整集群的资源效率和 spot 可靠性。

因此，这篇论文对多租户 GPU 云的研究者和工程团队都会有参考价值。它本质上是一篇运营控制类系统论文：先预留对的容量，再放出对的 spot 配额，最后在 HP 回收 GPU 时付出尽量小的代价。

## 局限性

GFS 依赖相对准确的需求预测，也依赖组织、集群、GPU 类型等元数据，所以如果这些信号噪声很大，或者业务模式突然改变，它的效果可能下降。它的抢占代价模型还默认任务有 checkpoint，因此对那些 checkpoint 很稀疏、或者真实恢复代价远大于“自上次 checkpoint 以来已执行时间”的工作负载，收益可能没有论文里那么理想。

论文在作者环境中的评估很扎实，但覆盖面仍比标题暗示的范围更窄。细致仿真主要集中在一个 2,296 张 A100 的集群上，核心效率指标也是 GPU allocation rate，而不是更直接的 SM utilization。论文也没有说明这个方案在多集群路由或跨集群配额协同下会如何表现，所以这部分仍然是开放的部署问题。

## 相关工作

- _Gao et al. (SoCC '21)_ — Chronus 面向 DL training 做 deadline-aware 与 lease-based 调度，而 GFS 额外加入了概率需求预测、动态 spot 配额控制，以及 checkpoint 损失感知的抢占。
- _Bai et al. (OSDI '20)_ — PipeSwitch 关注的是抢占发生后如何降低运行时上下文切换开销；GFS 关注的是集群层面何时应该抢占、以及谁来承担这次抢占。
- _Athlur et al. (EuroSys '22)_ — Varuna 从应用侧适配 distributed training 到 spot instance；GFS 则从云平台调度层管理整个平台上的 spot 可靠性。

## 我的笔记

<!-- 留空；由人工补充 -->

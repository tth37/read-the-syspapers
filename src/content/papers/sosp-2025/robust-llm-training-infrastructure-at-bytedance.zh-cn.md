---
title: "Robust LLM Training Infrastructure at ByteDance"
oneline: "ByteRobust 用“先隔离后精诊”的故障处理、stack-trace 驱动的 over-eviction、warm standby 和恢复感知 checkpoint，把万卡级 LLM 训练维持在高 ETTR。"
authors:
  - "Borui Wan"
  - "Gaohong Liu"
  - "Zuquan Song"
  - "Jun Wang"
  - "Yun Zhang"
  - "Guangming Sheng"
  - "Shuguang Wang"
  - "Houmin Wei"
  - "Chenyuan Wang"
  - "Weiqiang Lou"
  - "Xi Yang"
  - "Mofan Zhang"
  - "Kaihua Jiang"
  - "Cheng Ren"
  - "Xiaoyun Zhi"
  - "Menghan Yu"
  - "Zhe Nan"
  - "Zhuolin Zheng"
  - "Baoquan Zhong"
  - "Qinlong Wang"
  - "Huan Yu"
  - "Jinxin Chi"
  - "Wang Zhang"
  - "Yuhan Li"
  - "Zixian Du"
  - "Sida Zhao"
  - "Yongqiang Zhang"
  - "Jingzhe Tang"
  - "Zherui Liu"
  - "Chuan Wu"
  - "Yanghua Peng"
  - "Haibin Lin"
  - "Wencong Xiao"
  - "Xin Liu"
  - "Liang Xiang"
affiliations:
  - "The University of Hong Kong"
  - "ByteDance Seed"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764838"
tags:
  - llm-training
  - fault-tolerance
  - observability
  - gpu
  - datacenter
category: llm-training-infra
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ByteRobust 把大规模 LLM 训练视为一个会持续发生故障的生产系统，而不是偶尔崩溃一次的批处理任务。它把实时巡检、分层 stop-time 诊断、基于 stack trace 的 over-eviction、hot update、warm standby 和感知故障域的 checkpoint 备份串成一条恢复链路，因此训练可以在不等待“完美根因证明”的情况下快速恢复。在 9,600 GPU 的生产训练任务上，系统把 ETTR 维持到最高 97%，而多种恢复机制相对传统 requeue 都能带来 10x 以上的提速。

## 问题背景

这篇论文的起点非常务实：当 LLM 预训练跨越上千张 GPU、持续数月后，故障就不再是例外事件。作者统计了 ByteDance 生产平台三个月内的 778,135 个 LLM 训练作业，其中出现了 38,236 次显式故障、5,948 次隐式故障，以及 9,582 次人工重启。现有流程大多仍是典型的 fail-stop 模式：等日志或 timeout 暴露异常，再做压力测试、重调度资源，并从远端存储回灌 TB 级 checkpoint。这个流程往往要耗掉数小时甚至数天，直接压低有效训练时间比例，也就是 ETTR。

难点还不只在于故障多，而在于故障来源经常说不清。大模型训练同时混合 TP、PP、DP、ZeRO、长上下文阶段，以及持续演化的优化代码。同一种症状，比如 hang、NaN loss、illegal memory access，既可能来自用户代码，也可能来自网络、存储、GPU 硬件，或者 silent data corruption。尤其是隐式故障，很多时候根本没有明确日志信号；如果还坚持用 timeout 之后再精确定位根因的思路，就会让大量 GPU 在排障过程中白白闲置。

## 核心洞察

ByteRobust 的核心判断是：在万卡规模上，快速隔离通常比精确定位更有价值。鲁棒性系统应该按照训练作业本身的结构来思考问题，也就是以机器、并行组、代码版本和 checkpoint 故障域为基本单位。只要运行时信号足以尽快区分“可以继续训练”和“应当隔离驱逐”的对象，即使系统暂时无法严格证明最深层根因，也能显著减少整作业的空转时间。

与之配套的另一条洞察，是恢复流程必须尽量减少环境漂移。如果代码升级可以原地完成，替换机器来自已经自检通过的 standby 池，而 checkpoint 又提前备份到了潜在故障域之外，那么一次失败就不需要演变成整作业重新提交。它会变成一次边界清晰的 repair operation：尽量保留原始运行环境，既缩短停机时间，也减少排障时引入新的变量。

## 设计

ByteRobust 分成 control plane 和 data plane。control plane 包含负责检测、驱逐、回滚和恢复的 Robust Controller，以及专门处理 hang 和 MFU 下降的 Runtime Analyzer。每个训练 pod 内都运行一个 Robust Agent，下挂四个模块：Monitor 负责收集系统与训练指标，Diagnoser 负责在停机后执行 EUD、NCCL 等诊断测试，On-Demand Tracer 负责抓取进程 stack，CKPT Manager 负责异步 checkpoint 与备份。

它的自动容错链路是分层的。对于 GPU unavailable、磁盘故障这类高置信显式故障，系统直接驱逐机器。若无法从实时巡检中得到足够结论，ByteRobust 就暂停训练并进入 stop-time 诊断：若判断为瞬时故障则直接重试；若怀疑最近代码更新引入问题，则用原地 hot update 回滚代码，而不是销毁 pod 重建；对于更难的情况，例如 SDC，则执行 dual-phase replay，在保持 TP 和 PP 不变的前提下只调整 DP 分组，通过横向分组与纵向分组的交集找出嫌疑机器。

隐式故障则走另一条路径。面对 hang 或 MFU decline，ByteRobust 会抓取训练、数据加载和 checkpoint 子进程的 stack trace，把主流健康栈和离群栈聚类出来，再根据离群栈共享的 PP、DP 或 TP 组做 over-eviction。这个策略本来就故意偏保守，宁可多驱逐一些健康机器，也要换取更快恢复。恢复阶段则依赖两件事：一是按 P99 故障数量预留的 warm standby 机器池，二是放在 3D 并行组之外的 checkpoint 副本，这样即使整组被 over-evict，也不会把最后可用的 checkpoint 一起驱逐掉。

## 实验评估

对于目标场景，这套评估是有说服力的。ByteRobust 已经在超过 200,000 张 GPU 的生产集群上运行了一年多。论文重点报告了两个 9,600 GPU 的生产预训练任务，一个是 70B+ 的 dense 模型，一个是 200B+ 的 MoE 模型。在这两个任务上，累计 ETTR 最高维持在 97%，而滑动窗口下的非生产性时间即使到了训练后期也大致控制在 50 分钟以内。与此同时，相对 MFU 仍持续提升，dense 任务达到 1.25x，MoE 任务达到 1.58x，说明 hot update 让工程团队可以持续上线优化版本，而不必承受 full requeue 的代价。

组件级结果解释了这些收益的来源。实时巡检能在 30 秒内发现 NIC crash，而不是等到大约 10 分钟的分布式 timeout；GPU lost 或 GPU memory error 也能在 10 秒内识别。生产环境里，自动 eviction-and-restart 解决了大多数显式故障，而 analyzer 还能通过 machine over-eviction 自动处理 24 个隐式故障。在恢复微基准中，hot update 相比 requeue 快 11.04x，warm standby 相比 requeue 把加权恢复时间缩短 10.87x，且距离“无限备用机”的 oracle 只差 5.19%；每步 checkpoint 则把 blocking time 相对 Megatron save 降低 99.69%，同时把 MFU 损失控制在 0.71%。这些证据大多来自内部系统，但整体上确实支撑了论文的中心论点：真正重要的是把检测、诊断与恢复闭环集成起来。

## 创新性与影响

相对 MegaScale，ByteRobust 不只是一个面向 LLM 训练的监控和 stop-time 诊断系统，它把自动隔离、代码回滚和恢复流程也闭环了起来。相对 Gemini 以及其他 checkpoint 工作，它把备份布局和恢复策略绑定起来，明确假设“整个并行组都可能被 over-evict”。相对 SuperBench 这类压力测试方案，它强调保留原始 TP/PP/DP 拓扑，用运行时 stack 聚类来处理那些在合成测试里无法稳定复现的静默故障。

因此，这篇论文更像是一张系统蓝图，而不是单点机制论文。它最重要的贡献，是把 LLM 训练鲁棒性重新定义成一个横跨诊断、代码演化、重启策略、standby 容量和 checkpoint 放置的统一管理问题。任何在搭建生产级 LLM 训练平台或 GPU 集群 SRE 工具链的人，都会直接从这套设计里受益。

## 局限性

这个系统明显深受 ByteDance 内部环境塑造。它假设有类似 Kubernetes 的控制面、驻留在每个 pod 中的自定义 agent、额外的 warm standby 容量，以及对 NVIDIA 诊断工具和运行时指标的充分访问权限。很多设计也刻意以“粗粒度但快”为优先。例如驱逐整条 PP group 在 9,600 GPU 任务里会带来 6 到 7 个 false positive；在万卡规模上这个代价可以接受，但在更小的集群中就会显得昂贵。

最难的故障模式也仍未真正解决。论文明确指出，NVIDIA EUD 在生产环境中对 SDC 的召回率只有大约 70%，而回退到 MiniGPT 校验和 dual-phase replay 时，开销依旧很高。系统的外部可泛化性也有限：大部分部署证据来自 ByteDance 自身的作业和基础设施，许多比较对象也是 prior practice 或简化 baseline，而非与完整竞品系统做 artifact-identical 的对照。

## 相关工作

- _Jiang et al. (NSDI '24)_ — MegaScale 用 heartbeat 和 RDMA 指标监控 LLM 训练，而 ByteRobust 进一步补上了自动隔离、回滚以及面向恢复策略的 checkpoint 放置。
- _Wang et al. (SOSP '23)_ — Gemini 用内存 checkpoint 加速恢复，而 ByteRobust 进一步把备份与训练重叠执行，并把副本放到不容易被一起 over-evict 的并行域之外。
- _Xiong et al. (ATC '24)_ — SuperBench 通过主动压力测试定位 GPU 节点问题，但 ByteRobust 认为保留原始训练拓扑更忠实，因此更依赖运行时 stack 聚类来诊断静默故障。
- _Dong et al. (NSDI '25)_ — Evolution of Aegis 主要从日志和启发式规则改进 AI 训练故障诊断，而 ByteRobust 更依赖运行时指标与作业内进程状态聚合来处理 hang 和 gray failure。

## 我的笔记

<!-- 留空；由人工补充 -->

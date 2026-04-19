---
title: "HybridFlow: A Flexible and Efficient RLHF Framework"
oneline: "HybridFlow 把 RLHF 的跨模型编排交给单控制器、模型内部执行交给多控制器，再用零冗余的 actor resharding 把生成和训练衔接起来。"
authors:
  - "Guangming Sheng"
  - "Chi Zhang"
  - "Zilingfeng Ye"
  - "Xibin Wu"
  - "Wang Zhang"
  - "Ru Zhang"
  - "Yanghua Peng"
  - "Haibin Lin"
  - "Chuan Wu"
affiliations:
  - "The University of Hong Kong"
  - "ByteDance"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696075"
code_url: "https://github.com/volcengine/verl"
tags:
  - llm-training
  - gpu
  - datacenter
  - scheduling
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HybridFlow 把 RLHF 写成跨模型的单控制器数据流，同时把每个模型内部的执行留给多控制器。它的 `3D-HybridEngine` 能在同一组 GPU 上切换 actor 的生成并行与训练并行，而且不保留冗余权重副本；论文报告的整体吞吐提升范围是 1.53x-20.57x。

## 问题背景

RLHF 把一个本来不大的 RL DAG 变成了由重型分布式 LLM 程序组成的流水线。以 PPO 为例，actor、critic、reference、reward 都有各自的计算模式与切分方式，节点之间的边也不再是简单张量传递，而是 many-to-many 的 resharding。

这让两种直觉实现都失效。若把控制一路集中到模型内部，LLM 训练和生成中的巨大算子图会放大调度开销；若完全改用多控制器，虽然单模型执行够快，但数据传输、模型放置和算法逻辑会被写死在每卡程序里。论文的判断是，这既让 Safe-RLHF、ReMax 这类变体难做，也让 actor 在生成和训练之间切换并行度时非常昂贵。

## 核心洞察

论文的核心洞察是，控制边界应该画在模型之间。每轮 RLHF 真正跨模型的依赖边很少，所以单控制器完全可以廉价地负责执行顺序、设备放置和数据传输；模型内部依旧沿用 Megatron-LM、DeepSpeed、FSDP、vLLM 这一类多控制器执行方式即可。

这也顺手改写了 actor 的问题。如果训练和生成共用同一组 GPU，系统就可以允许两阶段采用不同的 3D 并行布局，并把优化重点放在布局切换本身，而不是维护两份 actor 或强迫两阶段共享同一个并不合适的切分方式。

## 设计

HybridFlow 先给出一套分层 API。`ActorWorker`、`CriticWorker`、`RewardWorker` 这类模型类建立在 `3DParallelWorker`、`FSDPWorker`、`ZeROWorker` 之上，把 `generate_sequences`、`compute_values`、`compute_reward`、模型更新等操作封装成原语。于是 PPO 在控制器侧只是一串原语调用；论文借此说明灵活性，PPO 只要 8 行，Safe-RLHF 只多 5 行，ReMax 主要只是改动调用组合。

跨模型的数据移动由 transfer protocol 负责。每个操作都绑定 collect 和 distribute 函数，因此不同切分方式的模型可以交换数据，而不用把彼此内部布局写死。`ResourcePool` 决定模型落在哪组 GPU 上；不同 pool 的模型在输入就绪后可以异步推进，同一 pool 上的模型则时间分片执行。

真正的核心优化在 actor 的 `3D-HybridEngine`。训练和生成共用同一组 GPU，但两阶段允许不同 3D 布局。生成阶段通过把训练阶段的每个 DP replica 拆成多个 micro-DP replica，来缩小 tensor parallel、放大有效 data parallel。阶段切换时，系统只在每个 micro-DP group 内收集所需权重，完成生成后再汇聚 responses 并切回训练布局。更关键的是，它重新设计了生成阶段的分组方式，让训练分片与生成分片在单卡上尽量重叠，因此 actor resharding 可以做到零内存冗余。

在这之上，auto-mapper 会枚举放置方案与 GPU 分配，用模拟器估计各模型候选并行度的延迟，再选出 RLHF DAG 的端到端最优映射。

## 实验评估

实验在 16 台机器、共 128 张 A100-80GB 上完成；机器内是 600GB/s NVLink，机器间带宽 200Gbps。作者评估 PPO、ReMax 和 Safe-RLHF，模型规模覆盖 7B 到 70B，并使用 `Dahoas/ful-hh-rlhf`。为了和不支持 continuous batching 的基线公平比较，prompt 与 response 都固定为 1024 token。

主结果很稳定：HybridFlow 相比 DeepSpeed-Chat、OpenRLHF、NeMo-Aligner 的吞吐提升范围是 1.53x-20.57x。若只看 PPO，平均提升分别是 3.67x、3.25x 和 12.52x，最好一次达到 20.57x；70B 模型上的平均加速最高，为 9.64x。

更细的实验直接支撑了 actor 侧机制。与 OpenRLHF、DeepSpeed-Chat 和 HybridFlow-V 相比，HybridFlow 把训练到生成的切换时间平均降低了 55.2%，也就是 11.7 秒；在 70B 上最多能减少 78.2 秒，降幅 89.1%。在 16 张 GPU 上，把生成 TP 调成 7B 用 2、13B 用 4，又能分别把生成延迟降低 60.3% 和 36.4%。放置实验也说明 auto-mapper 不是装饰：小集群里 colocate 通常最好，规模继续增大后 split 或 standalone 会占优。保留意见同样明显：评测主要回答吞吐问题，而且工作负载长度固定。

## 创新性与影响

HybridFlow 的贡献不在 RLHF 目标函数，而在系统架构。它把分层控制、跨切分协议、零冗余 actor resharding 和自动设备映射放进同一个框架里，因此比只针对单一算法或单一部署方式调参出来的 RLHF baseline 更通用。受益最大的会是做 RLHF 基础设施的人，因为他们终于可以分别替换算法、执行引擎和模型放置，而不是整套分布式堆栈一起改。

## 局限性

auto-mapper 的搜索过程假设 GPU 同构，实验也只在 A100 集群上验证。对于 colocate 的模型，HybridFlow 主要还是顺序执行，而不是做更细粒度的 GPU 复用。与此同时，论文讨论的几乎都是系统吞吐，对最终对齐质量、收敛速度和更不规则真实 trace 的覆盖都不够。

## 相关工作

- _Liang et al. (NeurIPS '21)_ - RLlib Flow 同样把 RL 视为 dataflow，但它面对的是轻得多的节点；HybridFlow 处理的是 RLHF 中每个节点都是分布式 LLM 程序的情形。
- _Barham et al. (MLSys '22)_ - Pathways 提供大规模 ML 程序的异步分布式 dataflow，而 HybridFlow 把这种思想专门落到多模型 RLHF pipeline，并补上显式的跨模型传输协议。
- _Yao et al. (arXiv '23)_ - DeepSpeed-Chat 是最直接的系统基线，它基本写死了一种 RLHF 执行模式；HybridFlow 则把模型放置和训练/生成并行度都做成了一等配置。
- _Rajbhandari et al. (SC '20)_ - ZeRO 解决的是数据并行训练的内存问题，HybridFlow 则把它当成构件，重点处理多模型 RLHF 编排与 actor 阶段切换时的 resharding。

## 我的笔记

<!-- 留空；由人工补充 -->

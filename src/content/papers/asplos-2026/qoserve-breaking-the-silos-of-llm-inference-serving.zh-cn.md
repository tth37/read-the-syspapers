---
title: "QoServe: Breaking the Silos of LLM Inference Serving"
oneline: "QoServe 在共享 GPU 上联合调度不同 SLO 的 LLM 请求，用松弛感知分块、混合优先级和主动降级同时提升吞吐并稳住延迟。"
authors:
  - "Kanishk Goel"
  - "Jayashree Mohan"
  - "Nipun Kwatra"
  - "Ravi Shreyas Anupindi"
  - "Ramachandran Ramjee"
affiliations:
  - "Microsoft Research, Bengaluru, India"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790206"
tags:
  - llm-inference
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

QoServe 试图回答一个很现实的生产问题：既然不同 LLM 应用本来就有不同延迟目标，为什么我们还要把它们硬拆成独立的“interactive 集群”和“batch 集群”？论文给出的答案是，把 deadline slack 变成可调度资源：在线调整 prefill chunk 大小，用介于 `EDF` 和 `SRPF` 之间的混合优先级来挑选请求，并把已经注定 miss deadline 的请求主动降到 relegated 队列。这样做既提高了 GPU 利用率，也避免了过载时整套服务一起雪崩。

## 问题背景

论文的出发点是当前 LLM 服务里非常常见的一种部署方式。交互式请求因为要保证 `TTFT` 和 `TBT`，通常被放到使用小 chunk 的独立副本上；离线或宽松延迟任务则被放到另一个使用大 chunk 的集群，以追求更高吞吐。这个做法实现简单，但代价也很明显：不同业务的负载波动不会同步，于是总会有一部分 GPU 被闲置；而一旦服务从粗粒度的“两类业务”扩展到更细的多个 QoS 桶，运维上几乎等于要不断新增隔离部署。

更糟的是，简单把这些请求合并到同一个集群里也行不通。若统一采用最小 chunk，大部分宽松任务都会为最严格的那一档买单；`FCFS` 会出现严重 head-of-line blocking；`EDF` 在低负载时看起来合理，但一旦系统接近饱和，排队会导致近乎级联式的 deadline 违约；`SJF` 或 `SRPF` 虽然能把中位数延迟压住，却是以牺牲长请求为代价。于是，真正的系统问题不是“怎样调度 LLM 请求”，而是“怎样在一个共享集群里同时满足多种延迟合同，并且在过载时有控制地退化，而不是整体崩盘”。

## 核心洞察

论文最重要的洞察是：chunked-prefill 的 LLM serving 已经暴露出足够稳定的结构，可以做真正的 QoS 感知调度。具体说，prefill 阶段的执行时间相对可预测，因此系统可以估计当前 decode 阶段请求距离下一个 token 截止时间还剩多少 slack。只要把这部分 slack 花在当前批次的更大 prefill chunk 上，就能在不伤害正在 decode 的严格请求的前提下，为宽松请求换取更多吞吐。

但单靠“动态调 chunk”还不够，因为 chunk 选择和请求选择必须互相配合。QoServe 因此把 slack-aware dynamic chunking 和一个混合优先级规则绑在一起：低负载时更像 `EDF`，负载升高后逐渐引入 `SRPF` 对剩余工作量的偏好。与此同时，它还引入 eager relegation。一旦某个请求已经 miss deadline，或者在当前迭代里无论如何都会 miss，就不要再让它继续拖累整个系统，而是把它移到 relegated 队列，等负载回落后再补做。这个设计的本质是承认“不是所有请求都还能被救回来”，从而防止少数 doomed 请求把全局排队一起带崩。

## 设计

QoServe 的运行时结构由三个队列组成：prefill、decode 和 relegated。每一轮调度都会构造一个混合 batch，其中包含所有正在 decode 的请求，以及从 prefill 队列里选出的一个 prefill chunk。interactive 请求携带 `TTFT` 与 `TBT` 目标，non-interactive 请求携带 `TTLT` 目标；系统先根据这些 SLO 计算 deadline，再围绕 deadline 做后续调度决策。

第一个关键机制是 hybrid prioritization。对 interactive 请求，优先级由到达时间、`TTFT` deadline，以及一个可调参数 `alpha` 乘以剩余 prefill 工作量共同决定；对 non-interactive 请求，则在此基础上再加上剩余 decode 工作量的估计。这样一来，QoServe 并不是在 `EDF` 和 `SRPF` 之间做硬切换，而是提供一个连续调节旋钮：低负载时偏 deadline，高负载时适度偏短作业。论文在固定负载实验中使用 `alpha = 8 ms/token`，在轻负载时则采用更小的值。

第二个关键机制是 dynamic chunking。QoServe 不把 chunk size 固定为“严格 QoS 桶所要求的最小值”，而是先观察当前 decode 队列里的 slack，再调用一个轻量级预测器，找出在不违约前提下可用的最大 prefill budget。这个预测器是基于 Vidur 采样得到的延迟 profile 训练的 random forest，输入包括 decode 请求数、上下文长度等统计量。作者特意把它调成略偏保守的 under-predictor，宁可少吃一点吞吐，也不让 chunk 选得过大而击穿延迟预算。

第三个关键机制是过载控制。QoServe 只允许 selective preemption，而且只发生在 prefill 阶段，并且前提是“被抢占一轮也不会因此违约”；decode 阶段绝不抢占，因为 `TBT` 预算太紧。若系统判断某个请求已经 miss，或本轮之后必 miss，就立即把它 relegated。论文还允许应用提供优先级 hint，例如免费层与付费层，从而在过载时优先牺牲低优先级请求。

实现上，QoServe 不是重写一个全新的推理系统，而是在 Sarathi 调度器和 vLLM 之上扩展：底层仍然复用 tensor parallelism 与 PagedAttention，变化集中在调度策略和请求接口。

## 实验评估

这篇论文的实验面算比较宽。作者测试了三种模型与硬件组合：Llama3-8B on `A100-80GB (TP1)`、Qwen-7B on `A100-80GB (TP2)`、以及 Llama3-70B on `H100-80GB (TP4)`；工作负载则来自 ShareGPT、Azure conversation trace 和 Azure code trace。默认设置把请求均分到三个 QoS 桶：一个 interactive 桶，目标是 `6s TTFT` 与 `50ms TBT`；另外两个是 `600s` 和 `1800s TTLT` 的 non-interactive 桶。

在集群级实验里，作者用 Azure-Code trace 的 35 QPS 负载做测试。传统 siloed Sarathi 需要 13 张 GPU 才能扛住，而 QoServe 只用 10 个混合副本就能把各层 p99 延迟压在目标内，相当于减少 `23%` GPU。若把 siloed 方案也压到 10 张 GPU，deadline violation 会立刻升到 `60.4%`。在单副本共享集群实验中，QoServe 相比 Sarathi-FCFS 的 goodput 提升达到 `1.5x-2.4x`，相对 Sarathi-EDF 也有 `20-40%` 的提升。dynamic chunking 单独拿出来看也很有说服力：作者观察到 chunk size 可以从严格桶要求的 `256` 拉高到大约 `2500`，对应接近 `2x` 的该点吞吐提升，以及 `20%` 的端到端吞吐收益。

过载实验更能体现系统设计是否真的成立。论文显示，QoServe 能在比 Sarathi-EDF 高 `30%` 的负载下仍保持零 deadline violation，并且在更高负载下依然比基线多承受约 `40%` 的压力而保持 tail-latency SLO。动态负载实验中，作者把 20% 请求标成低优先级；在这种设置下，QoServe 对 important 请求的违约率是 `0%`，总体违约率为 `8.75%`，而基线会在突发到来后快速进入级联排队失控状态。换句话说，QoServe 的改进不只是“峰值吞吐更高”，更重要的是它把失败模式从“全局队列一起炸掉”变成“按策略牺牲少数请求，保住大多数请求”。

我认为这组实验对论文主张的支持度是比较高的，尤其是在单模型共享 serving 集群这个目标场景里。它同时比较了多种调度基线，并且刻意在同一个 vLLM/Sarathi 代码基础上实现，减少了“系统工程差异”带来的偏差。不过边界也很清楚：PD disaggregation 的实验只覆盖 prefill 端，decode 侧的多 `TBT` 支持被明确留到未来工作；另外，interactive 桶的 `TTFT` 目标是 `6s`，所以这些结果更直接说明系统能稳住持续输出与总吞吐，而不是已经证明它适合亚秒级首 token 的强交互场景。后半句是我根据实验设置做出的推断，不是论文的原话。

## 创新性与影响

和 _Agrawal et al. (OSDI '24)_ 相比，QoServe 的新意不在于发明 chunked prefill，而在于把 deadline slack 提升为一等调度信号，再配上混合优先级与 eager relegation。和 PolyServe 这类按 QoS 分桶再独立部署的思路相比，它最重要的一步是拒绝继续把不同 SLO 的请求拆到互不共享的 fleet 里，从而能回收负载波动下被浪费的容量。和 SLOs-Serve 相比，QoServe 强调的是更轻量、更可扩展的调度面：用 priority queue 做选择，而不是周期性地对所有活跃请求做更重的全局优化。

因此，这篇论文最可能影响的是两类人：一类是云端 LLM serving 平台的工程团队，另一类是研究多租户 LLM 调度与资源管理的系统研究者。它更像一篇“面向生产现实的调度器设计”论文，而不是单点内核优化论文。

## 局限性

QoServe 依赖针对具体模型、硬件和并行配置做离线 profiling，并训练对应的预测器，所以可移植性不是零成本的。对 non-interactive 请求，它对剩余 decode 长度的估计也主要基于历史统计，因此在应用行为突然漂移时可能不稳。论文的 disaggregated 结果只覆盖 prefill 端，decode 端如何支持异构 `TBT` 目标被明确留作未来工作。更广义地说，作者的实现与实验基本都围绕 vLLM/Sarathi 上的单模型服务展开，因此没有真正处理多模型路由、autoscaling 或跨 fleet admission control。

## 相关工作

- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve 奠定了 chunked-prefill serving 的基础，而 QoServe 在其之上增加了多 QoS 联合调度、松弛感知 chunk 选择和过载降级。
- _Kwon et al. (SOSP '23)_ — PagedAttention 解决的是连续 serving 下的 KV-cache 内存管理问题；QoServe 默认建立在这类底座之上，关注点是调度策略而不是内存布局。
- _Agrawal et al. (MLSys '24)_ — Vidur 提供了 QoServe 训练 chunk-size predictor 所依赖的 profiling / simulation 基础设施，因此两者关系更像“测量支撑”而不是直接竞争。

## 我的笔记

<!-- 留空；由人工补充 -->

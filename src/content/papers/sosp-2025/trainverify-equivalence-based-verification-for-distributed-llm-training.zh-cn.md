---
title: "TrainVerify: Equivalence-Based Verification for Distributed LLM Training"
oneline: "TrainVerify把分布式LLM训练计划化成与逻辑模型的等价性证明，并用分阶段符号验证与形状缩减把验证扩展到前沿大模型。"
authors:
  - "Yunchi Lu"
  - "Youshan Miao"
  - "Cheng Tan"
  - "Peng Huang"
  - "Yi Zhu"
  - "Xian Zhang"
  - "Fan Yang"
affiliations:
  - "University of Michigan"
  - "Microsoft Research Asia"
  - "Northeastern University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764850"
code_url: "https://github.com/verify-llm/TrainVerify"
tags:
  - llm-training
  - verification
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

TrainVerify不去验证整个训练软件栈，而是把目标收缩到“分布式执行计划是否与逻辑模型等价”。它用符号化数据流图、分阶段验证和形状缩减，把这件事扩展到Llama3 405B和DeepSeek-V3 671B这一级别的训练计划。

## 问题背景

这篇论文盯住的是前沿模型训练里最昂贵也最隐蔽的一类错误: 并行化错误。今天的大模型训练往往要用上千到上万张GPU，连续跑数周甚至数月；如果张量切分、通信组配置、梯度缩放或流水线调度有一处出错，训练表面上仍可能继续推进，但最终更新的是错误参数，代价是大量GPU时间被静默浪费。作者梳理MegatronLM、DeepSpeed和nnScaler后，发现这类错误反复出现在算子变换、调度和通信逻辑里。

传统测试并不能很好解决这个问题。浮点运算顺序、混合精度和不同kernel实现本来就会带来数值漂移，使得差分测试很难分清“正常噪声”和“真实错误”；而超大模型的单卡完整真值几乎不可获得。把规模缩小后再测，也可能漏掉只在生产级并行度下出现的问题。另一方面，如果想直接验证整个训练软件栈，又会立刻撞上编译器、通信库、GPU kernel和硬件相关代码的复杂度墙。论文因此把目标改成一个更具体的问题: 生成出来的执行计划，是否真的保留了逻辑模型的语义。

## 核心洞察

论文最重要的命题是，绝大多数与并行化相关的正确性问题，都可以收敛为一个等价性判断: 对任意合法输入，分布式数据流图产出的结果，必须与逻辑模型数据流图的结果等价。作者把这个性质称为 parallelization equivalence。

这个抽象的好处在于，执行计划已经包含了切分、通信和调度决策，却仍然足够结构化，适合做符号推理。只要能证明执行计划与逻辑图在一次完整训练迭代上等价，就能说明这个分布式训练过程在功能上没有偏离开发者定义的模型。作者还观察到，深度学习算子大多是规则的SIMD式计算，因此可以把张量缩到代表性最小形状，而不破坏证明成立。

## 设计

TrainVerify接收两份输入: 逻辑模型的代码，以及分布式训练代码或框架生成的执行计划。系统先把两者都转成数据流图，再把图中的张量和算子符号化，得到 symbolic data flow graph。这里的张量元素不再是具体的FP16或BF16数值，而是 symbolic real；这样验证器推理的是代数语义，而不是某一次样本运行的数值结果。论文还强调，图中不能只含前向计算，必须补全反向传播、优化器步骤和梯度范数等度量逻辑，因为这些正是分布式训练常见的出错点。

连接逻辑图与并行图的核心结构是 lineage metadata。对每个逻辑张量，TrainVerify都保留它在并行执行计划里如何被切分、复制或聚合的信息。于是系统就能表达并检查“这些分片应当拼成原张量”或“这些副本求和后应当还原逻辑值”之类的约束；缺失通信、错误通信组或不一致切片，最后都会表现为lineage约束不成立。

为了解决可扩展性，TrainVerify使用 staged verification。它利用lineage感知的 backward slicing，把逻辑图和并行图切成一对一对齐的阶段，每个阶段只证明局部输入输出等价，再把阶段边界串成端到端证明。另一项关键技术是 shape reduction: 系统为每个张量维度求满足语义约束和形状对齐约束的最小缩减形状。实现上，TrainVerify大约有6000行Python代码，构建在nnScaler之上，底层求解器使用Z3，并为大约40个算子编写了符号执行适配。

## 实验评估

这篇论文的实验重点不是训练吞吐，而是“能不能把证明做完”和“能不能覆盖真实错误”。作者验证了Llama3 8B、70B、405B，以及DeepSeek-V3 16B、236B、671B的执行计划。最大规模的配置接近真实生产设置: Llama3最高到8192张GPU，DeepSeek-V3最高到2048张GPU。验证运行在一台32核Xeon Platinum 8473C、1.34 TB内存的机器上。

结果支持了论文的可扩展性主张。中等规模计划在一小时内完成: Llama3-8B只需0.2小时，DeepSeek-V3-16B为0.4小时；最大规模计划Llama3-405B和DeepSeek-V3-671B分别为8.0小时和9.0小时。由于shape reduction的存在，验证时间对原始batch size、hidden size、sequence length和attention heads大多不敏感；在一个较小的Llama3-8B设置上，关闭阶段级并行求解会把时间从18秒以内拉长到90多秒，约慢5倍。错误检测方面，作者复现了14个来自MegatronLM、DeepSpeed和nnScaler错误类别的不平凡错误执行计划，TrainVerify全部在1分钟内发现。弱一点的地方在于，论文没有直接的验证器基线，因此实验更多是在证明“能扩展、能抓错”，而不是证明“比别人更快”。

## 创新性与影响

这篇论文的创新点不只是“把SMT搬到ML系统里”。真正重要的是它选中了 execution plan equivalence 这个验证边界，然后用lineage对齐、分阶段求解和形状缩减把这个边界做到了可扩展。此前关于神经网络等价性的工作，大多停留在局部图重写或小模型验证；TrainVerify把这种形式化思路推进到了完整的分布式训练计划上。

这对训练框架作者很有启发: 只要系统能暴露SSA风格的图和lineage信息，就有机会在昂贵训练之前先验证计划是否保语义。对形式化方法社区来说，它也证明了符号推理并不只能处理玩具规模的问题。

## 局限性

作者对系统边界讲得很清楚，而这些限制必须认真看待。首先，TrainVerify把逻辑模型当作规范，因此它并不证明原始模型定义本身没有语义错误。其次，它也不验证CUDA kernel、NCCL、内存布局约束或真实硬件上的浮点行为；symbolic real 会主动抽象掉这些数值细节。

其次是落地约束。当前原型依赖图形式的执行计划和tensor lineage，这让它很适合nnScaler一类框架，却不容易直接套到MegatronLM这种代码中心的系统上。新模型架构只要引入新算子，就仍然需要人工补写符号执行和形状缩减规则；当前支持的优化器空间也仍然有限，主要集中在ZeRO Stage 1。

## 相关工作

- _Lin et al. (OSDI '24)_ - nnScaler负责生成高效的分布式训练计划，而TrainVerify在此之上补上语义等价性证明，检查这些计划是否真的保留了逻辑模型含义。
- _Jia et al. (SOSP '19)_ - TASO验证的是局部神经网络图重写的正确性，TrainVerify则验证包含通信与调度结构的完整分布式训练执行计划。
- _Arora et al. (POPL '25)_ - TensorRight同样面向tensor graph rewrite verification，但目标是图重写规则本身，而不是多设备训练计划的端到端等价性。
- _Jiang et al. (OSDI '25)_ - Training with Confidence通过运行时检查捕获静默训练错误，而TrainVerify提供的是并行化逻辑的离线符号保证，可与长时间训练前后的监测手段互补。

## 我的笔记

<!-- empty; left for the human reader -->

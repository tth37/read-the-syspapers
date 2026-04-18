---
title: "It Takes Two to Entangle"
oneline: "Entangle 用逐算子重写证明分布式模型输出可被“干净地”还原为顺序模型输出，从而在 TP/SP/EP 实现里静态定位语义错误。"
authors:
  - "Zhanghan Wang"
  - "Ding Ding"
  - "Hang Zhu"
  - "Haibin Lin"
  - "Aurojit Panda"
affiliations:
  - "New York University, New York, NY, United States"
  - "ByteDance Seed, Bellevue, WA, United States"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790178"
tags:
  - verification
  - formal-methods
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Entangle 检查的不是分布式 ML 实现是否和顺序模型逐值完全相同，而是顺序模型的输出能否仅通过张量重排与归约等“clean”操作，从分布式输出中还原出来。它的关键做法是沿着顺序图的拓扑序逐个算子证明 refinement，并在每一步用迭代重写搜索可行的输出关系。这样既保留了 soundness，又把错误定位压缩到具体算子；在 GPT、Qwen2、Llama-3 等模型上，作者复现了 9 个真实 bug，验证时间保持在几十到数百秒量级。

## 问题背景

这篇论文抓住的是分布式大模型实现里一个非常常见、但又很难提前发现的问题。真实工作流通常是：模型设计者先写出单机、顺序的 `G_s`；实现者再把它改写成支持 tensor parallelism、sequence parallelism、expert parallelism 等策略的 `G_d`。在这个过程中，会额外插入 slicing、padding、通信、聚合、layout 转换等操作。只要其中某个 offset、scale factor、聚合步骤或复制/分片策略写错，分布式实现就会偏离原始语义。

论文给出的例子都很有代表性。一个是 MoE 训练里 auxiliary loss 在 TP 下忘记除以并行度 `T`，导致后续 reduce-scatter 之后梯度被放大 `T` 倍；另一个是在从 TP 切到 SP 时，专家权重本应在 SP rank 之间复制，但实现里仍然沿用 shard，于是只算出了矩阵乘法的对角块，缺失了交叉块。这类 bug 往往不会直接 crash，shape 和 type 也完全可能正常，因此通常要到训练不收敛、指标异常、甚至部署后行为不对时才暴露出来。

现有检查办法各有明显缺陷。动态测试和 fuzzing 能覆盖大模型，但不能给出形式化正确性保证；而直接做整图等价性证明又过强，因为很多正确的分布式实现本来就不会生成与顺序模型完全同形的输出，而是需要再做拼接、转置或归约才能得到顺序结果。通用 SMT / EGraph 方案在整图规模上也很难撑住今天的模型。因此，论文要解决的核心问题是：能否在允许“合理通信与重排”的前提下，静态地证明分布式实现仍然实现了顺序模型的语义？

## 核心洞察

论文最重要的洞察是，分布式 ML 的正确性应该被表述成 **model refinement**，而不是严格的张量相等。只要 `G_s` 的输出能够从 `G_d` 的输出中，通过 `slice`、`concat`、`transpose`、`reduce-sum` 这类 clean 操作还原出来，那么这个分布式实现就算是正确的；如果要额外做新的语义计算，说明分发过程中丢失了本该保留的信息。

这个表述之所以强，是因为它把问题从“证明两个大图完全一样”降成了“证明顺序输出可被干净重构”。而程序员在把 `G_s` 改成 `G_d` 时，通常仍然保持原有算子顺序，只是在每个算子附近插入并行化带来的额外操作。于是 Entangle 可以按 `G_s` 的拓扑序逐算子推进：先证明当前顺序算子的输出如何由 `G_d` 中某些张量 clean 地表达，再把这个关系传给后续算子。论文的论点是，这种逐步验证保住了 soundness，同时把搜索空间和报错位置都压缩到了工程上可用的程度。

## 设计

Entangle 的输入有三部分：顺序模型计算图 `G_s`、分布式实现计算图 `G_d`，以及一个由用户提供的 clean input relation，用来说明顺序输入如何映射到分布式输入。系统的目标是合成一个 complete clean output relation：对于 `G_s` 的每个输出张量，都找到一个只依赖 `G_d` 输出张量的 clean 表达式来重构它。

核心算法是迭代式的。对 `G_s` 中每个算子 `v`，Entangle 先利用当前已知关系，把 `v` 的输出表达成 `G_d` 张量上的表达式；然后应用 rewrite lemmas 去枚举等价表达式；最后再把这些表达式中的子式尽量重写回 `G_d` 中实际存在的张量，并筛掉所有不属于 clean 范畴的候选，得到当前算子的输出关系 `R_v`。如果某个顺序输出无法找到 clean 映射，Entangle 就在这里停止，并返回这个算子以及相关输入关系，作为 bug localization 的主要线索。

真正让系统可扩展的是它对重写空间的控制。Entangle 用 `egg` 的 EGraphs 做 saturation，但不会把整张 `G_d` 都丢进去盲搜；它只围绕“与当前顺序算子的输入或输出相关”的那部分张量做增量扩展。也就是说，它维护一个 `T_rel` 集合，逐步把可能参与当前证明的 `G_d` 子图扩出去，而不是提前构造全局关系。对于 `reshape`、`slice`/`concat` 这类容易爆炸的 lemma，系统还会加约束，并在等价表达式中只保留最简单的代表。代价是它明确放弃 completeness：如果 `G_d` 做了 `G_s` 没有的 fused kernel、算子重排，或者两边优化不一致，Entangle 可能会误报；但一旦它证明成功，返回的 relation 本身就是 soundness certificate。

实现上，论文提到 Entangle 由大约 `9000` 行 Python 与 `7800` 行 Rust 组成，其中约 `4100` 行 Rust 用于定义和验证 PyTorch ATen 的 lemmas。PyTorch 模型通过 TorchDynamo 抓图；NeuronX/HLO 则通过额外翻译工具接入。作者还支持一种扩展用法：用户不只是问“是否存在某种 refinement”，还可以指定自己期望的 refinement 形式，Entangle 再去验证这个特定关系是否成立。

## 实验评估

实验主要回答四个问题：Entangle 能否有效找 bug 并帮助定位、验证需要多久、随模型层数和并行度如何扩展、以及支持新算子时需要多少人工补充。实验平台是 CloudLab 上的 `c6525-25g` 节点，配有 16 核 AMD EPYC 7302P CPU 和 128 GB 内存。工作负载覆盖了使用 TP/SP/EP 的 ByteDance 内部模型、Megatron-LM 的 GPT2、vLLM 的 Qwen2、一个使用 gradient accumulation 的 HuggingFace 回归模型，以及基于 NeuronX/HLO 的 Llama-3。

在 bug 发现能力上，论文复现了 9 个真实世界问题，其中 5 个来自 ByteDance，4 个来自开源系统；ByteDance 的 5 个里有 1 个是 Entangle 自己发现的。被覆盖的问题包括 SP 下错误的 RoPE offset、TP 下 auxiliary loss 缩放错误、layernorm 权重缺少聚合、Megatron-LM 与 TransformerEngine 中缺失 all-reduce 等。更重要的是，Entangle 不是只返回一个抽象的“验证失败”，而是停在第一个无法 clean 映射的顺序算子上，连同相关输入关系一起交给用户，因此调试范围通常会被压缩到一个很具体的局部。

在验证时间上，论文报告 HuggingFace 的小测试用例不到 1 秒，其余模型在并行度设为 `2`、只检查单层时都能在 2 分钟内完成；摘要和扩展实验则给出大约 `10` 到 `245` 秒的范围。作者进一步在 GPT 和 Llama-3 上系统地改变层数与并行度，发现并行度增大比层数增加更伤，因为它主要拉宽图宽度、提高每一步重写成本；但即便到 `8` 路并行，整体时间仍然保持在开发者可以接受的量级，而不是必须离线跑一整夜。

论文对“要补多少 lemma”也给了比较可信的答案。对于超出内建 ATen 集合的算子，确实需要用户手写新 lemma，但数量不多，而且大多数 lemma 都很简单，通常不到 `40` 行代码。热度最高的 lemma 恰恰是 `slice`、`concat` 这类 clean 操作对应的规则，这和论文的整体论点是一致的：分布式实现的正确性，很多时候不是败在复杂数值算子本身，而是败在分片、重排和聚合这些边界操作上。

## 创新性与影响

和 _Jia et al. (SOSP '19)_ 相比，Entangle 不是拿重写去做 tensor graph 优化，而是把这套 machinery 转向分布式实现验证。和 _Yang et al. (POPL '21)_ 相比，它的贡献不是一般性的 equality saturation，而是提出了 clean reconstruction 这一 refinement 目标，并把它落成逐算子的迭代证明流程。和 _Arora et al. (POPL '25)_ 相比，它不专注于证明某个局部图改写规则本身是正确的，而是关注 TP、SP、EP 这类并行化策略把整段实现改坏的问题。和 _Zulkifli et al. (EuroMLSys '25)_ 相比，它强调 soundness，并采用了更贴近部署现实的等价定义：分布式输出不必逐值等于顺序输出，只要能够被 clean 地还原回来即可。

因此，这篇论文最可能影响两类人：一类是做形式化验证和程序分析的研究者，另一类是维护分布式训练/推理框架的工程团队。它最有价值的地方不是某个单独技巧，而是提出了一个工程上可落地的验证契约：把正确性定义成 clean reconstructability，按算子顺序逐步证明，并在失败时把信息组织成程序员能用的调试线索。

## 局限性

作者非常明确地承认，Entangle 是 sound 但不 complete。只要它证明 refinement 成立，返回的 relation 就可视为证书；但如果相关假设不满足，它也可能把正确实现误判为 buggy。最关键的假设包括：`G_s` 与 `G_d` 使用相同优化、两边保持相同算子顺序、以及与某个顺序算子相关的分布式算子，其输入能够映射回这个顺序算子的输入或输出。遇到 fused kernel、算子重排、或只在 `G_d` 一侧做了特殊优化时，这套方法就容易失效。

另外还有一些落地层面的限制。用户必须提供 clean input relation；遇到自定义算子或硬件特化算子时，还需要额外补 lemma。Data parallelism 和 pipeline parallelism 没有被实验覆盖，主要原因不是理论不支持，而是 TorchDynamo 抓不到论文所需的完整图结构。除了 ByteDance 内部模型外，大多数实验也只验证了 forward pass，因为要把 forward 和 backward 正确关联起来还需要额外人工工作。所以这篇论文已经证明了它很适合做部署前检查，但距离“任何训练栈一键验证”仍有一段工程距离。

## 相关工作

- _Jia et al. (SOSP '19)_ — TASO 用重写搜索更优 tensor graph，而 Entangle 用重写去验证分布式实现是否仍然 refinement 原始顺序模型。
- _Yang et al. (POPL '21)_ — Tensat 提供 EGraph-based equality saturation；Entangle 在此基础上加入 clean reconstruction 目标和逐算子迭代搜索。
- _Arora et al. (POPL '25)_ — TensorRight 证明 tensor graph rewrites 的正确性，而 Entangle 关注 TP、SP、EP 等并行化策略在真实实现里引入的错误。
- _Zulkifli et al. (EuroMLSys '25)_ — Aerify 与本文最接近，但它追求语义相等；Entangle 则允许布局不同，只要求最终能 clean 地映射回顺序输出。

## 我的笔记

<!-- 留空；由人工补充 -->

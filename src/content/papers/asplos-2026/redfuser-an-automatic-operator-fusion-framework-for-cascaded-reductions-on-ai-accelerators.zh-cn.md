---
title: "RedFuser: An Automatic Operator Fusion Framework for Cascaded Reductions on AI Accelerators"
oneline: "RedFuser 用符号分析识别可融合的级联归约，推导增量融合公式，并自动生成接近手写 attention 内核性能的 GPU 代码。"
authors:
  - "Xinsheng Tang"
  - "Yangcheng Li"
  - "Nan Wang"
  - "Zhiyi Shu"
  - "Xingyu Ling"
  - "Junna Xing"
  - "Peng Zhou"
  - "Qiang Liu"
affiliations:
  - "Alibaba Cloud Computing, Shanghai, China"
  - "Alibaba Cloud Computing, Sunnyvale, USA"
  - "Alibaba Cloud Computing, Shenzhen, China"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790209"
tags:
  - compilers
  - gpu
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

RedFuser 处理的是当前 AI 编译器仍然很不擅长的一类模式：多个归约阶段首尾相接、彼此依赖的 cascaded reductions，例如 safe softmax、attention、MoE routing，以及 FP8 quantization 后接 GEMM。论文的关键做法是先把这类链式归约写成符号表达式，判断它们何时能够跨归约边界融合，再推导出一种可流式执行的增量形式，让融合后的计算能真正落到 GPU 上。对支持的工作负载，作者报告生成内核相对通用编译器栈有 `2x-5x` 提升，并且已经接近甚至略微超过手写 attention 内核。

## 问题背景

只要一个归约的结果会喂给下一个归约，就会出现 cascaded reductions：safe softmax 先做 `max` 再做 `sum`，attention 是 softmax 后接 GEMM，MoE routing 是 softmax 再接 top-k，FP8 逐 token 量化则是先做 abs-max 再做 GEMM。它们在现代 AI 模型里非常常见，但对编译器很棘手，因为每一级归约都依赖前一级 reduction tree 的根节点。这样的串行依赖会带来两个直接问题。第一，每一级都会重复读取输入或中间结果，内存流量被反复支付。第二，后一阶段必须等前一阶段彻底完成，难以并行，也难以把访存与计算重叠起来。

现有 AI 编译器当然会做 operator fusion，但论文指出，它们大多只能把一个 reduction 和周围的 elementwise 或 compute-intensive 算子融合起来，而不是把“一个归约阶段”继续融合进“下一个归约阶段”。因此，编译器通常得不到覆盖整条 reduction chain 的单一 loop-level kernel。FlashAttention、FlashDecoding 这类手写内核确实解决了重要特例，但代价是需要专家为某一种模式手工推导 online update 公式。RedFuser 试图回答的问题不是“能不能再写一个 attention 特化 kernel”，而是“编译器能不能把 reduction chain 识别成一类结构化计算，并自动恢复出同样的代数技巧”。

## 核心洞察

论文最核心的主张是：如果每个归约阶段都能拆成“只依赖当前输入元素”的一部分和“只依赖前序归约结果”的一部分，那么很多 cascaded reductions 就可以被系统性地融合。更具体地说，作者要求第 `i` 个归约能写成 `G_i(X[l]) ⊗ H_i(D_i)`，其中 `⊗` 需要构成交换幺半群，而归约算子本身还要对 `⊗` 满足分配律。只要这些条件成立，RedFuser 就能把原本“必须等前面所有 reduction tree 都归并到根节点后才能开始”的计算，改写成“在同一层级上依赖前面几个归约输出”的融合归约。

这个改写真正重要的地方，在于它切断了原程序里最贵的那条依赖链。融合后的形式允许编译器只加载一次输入，在多个归约阶段之间重用片上结果，并把多棵 reduction tree 合并成一棵按层对齐的 fused reduction tree。论文的第二个关键点是，光有 fusion 还不够，因为融合后若仍需缓存完整上一层输出，长序列依旧会被片上容量卡死。于是 RedFuser 继续推导增量更新公式：每来一个新的 segment，就对当前 running result 做一次校正并立刻并入。这样把存储复杂度从 `O(L_{k-1})` 降到 `O(1)`，也正因为如此，这套方法才不只是数学上可写，而是工程上可落地。

## 设计

RedFuser 构建在 TVM 之上。它先从降低到 Relax 的模型中识别 cascaded-reduction subgraph，再把这些子图降低到 TIR，并通过函数内联和循环重排把结构规范化。随后，一个面向 TIR AST 的 visitor 会恢复出每一级归约的数学表达式，包括它如何依赖更早的归约结果。这个符号表达式就是论文里 Automatic Cascaded Reductions Fusion（`ACRF`）算法的输入。

`ACRF` 是论文最有新意的机制。它先利用 AI 工作负载里的领域约束缩小搜索空间：常见归约大多是 `sum`、`product`、`max`、`min` 等，因此兼容的二元算子 `⊗` 可以直接从表里查到。接着，算法用一个 fixed-point 恒等式来测试可分解性：如果 `F_i(x, d) ⊗ F_i(x_0, d_0) = F_i(x, d_0) ⊗ F_i(x_0, d)` 成立，就说明该函数能被拆成只依赖输入和只依赖依赖项的两部分。之后，RedFuser 会实例化三组公式：第一层融合归约、高层融合归约，以及对应的增量更新规则。附录还补了一个 non-invertible 情况下的修正方法：当 `H_i` 没有逆元时，用单位元替代，保证公式仍然可计算。

拿到 fused expression 之后，RedFuser 提供两种 GPU 执行策略。`Single-Segment` 使用增量更新，因此单个 CTA 就能在不缓存完整前一层结果的前提下处理很长的 reduction stream，从而避开跨 block 同步。`Multi-Segment` 则把输入切给多个 CTA 并行处理，最后再用高层融合规则把部分结果合并起来。后续的 lowering pipeline 同样很完整：blockization、buffer scope 推断、TileOp 转换、TileLang code generation，以及围绕 tile size、线程数、software pipeline 深度和 segment 数的 auto-tuning。生成代码会显式利用 `cp.async`、`TMA`、`MMA`、`WGMMA` 之类硬件特性。

## 实验评估

主实验运行在两种 NVIDIA GPU 上：`A10-24GB` 与 `H800-80GB`。作者选了四类代表性子图：MHA、MLA、MoE routing，以及 FP8 PerToken Quant + GEMM。基线包含 PyTorch Eager、PyTorch Dynamo/Inductor、TVM Relax，以及在可比场景下的手写库 FlashAttention2 和 FlashMLA。这个基线组合是合理的，因为它同时检验了 RedFuser 相对“通用编译器”与“模式专用专家内核”的位置。

主要结果很强。对 MHA，RedFuser 平均达到 FlashAttention2 的 `1.09x`，并且在一个 LLaMA-65B 配置上相对 PyTorch Dynamo 和 TVM 分别得到 `2.8x` 与 `2.6x` 加速。对 MLA，它达到 FlashMLA 的 `102%`，同时比 Dynamo 快 `2.4x`、比 TVM 快 `8.7x`。对没有标准手写基线的工作负载，收益也很明显：MoE routing 相对 Dynamo 提升 `1.7x`、相对 TVM 提升 `6.6x`；Quant + GEMM 相对 Dynamo 提升 `3.4x`、相对 TVM 提升 `12.1x`。

论文里更有诊断价值的实验也做得不错。safe softmax 的层级融合实验比较了 intra-thread、intra-warp、intra-block 和 inter-block 四种策略，结果表明 intra-block 最优，因为它既能提供足够深的计算链来隐藏访存延迟，又没有承担最强的依赖代价。incremental 与 non-incremental 的对比也很诚实：若两者都能放进同样的硬件预算里，non-incremental 会更快；但它必须把完整前一层结果留在片上，所以只适合短 segment。incremental 虽然要额外做 correction，反而能打开一些 non-incremental 根本放不下的配置空间；文中最优配置出现在 `Waves per SM = 3`，相对基线能达到 `1.25x`。

我认为这些实验基本支撑了论文的主张：RedFuser 不只是“又一个 attention kernel”，而是一种能在多类 reduction-chain 模式上恢复专用优化效果的编译方法。不过它的证据边界也很清晰。论文评估的对象仍然以 subgraph 为主，而不是完整模型训练或 serving，所以图划分开销、全应用编译代价、以及与更大 runtime 的交互，这些系统层问题都还不在本文的证据范围内。

## 创新性与影响

相对 _Dao et al. (NeurIPS '22)_，RedFuser 的创新点不在于提出更快的 attention tiling，而在于声称 FlashAttention 式的 online update 可以从符号化的 reduction-chain 分析里自动推导出来。相对 _Zheng et al. (ASPLOS '22)_，它的贡献更聚焦也更形式化：不是把各种算子融合都扔进一个大搜索空间，而是把 cascaded reductions 单独抽成一类，并给出清晰的代数可融合条件。相对 _Xia et al. (ASPLOS '24)_ 这类编译系统，RedFuser 的独特之处在于“跨多个归约阶段做表达式级融合”，而不是只在某一个 reduction 周围做激进融合。

因此，这篇论文对至少两类读者都有价值。对编译器研究者来说，它展示了如何把符号代数与 GPU code generation 直接连起来，专门服务于 AI 工作负载。对 GPU 内核和系统工程实践者来说，它的意义在于说明：许多过去看起来像“专家手艺”的 attention/normalization 优化，其实可以被统一成编译器可推导的模板。

## 局限性

论文明确承认，RedFuser 并不适用于任意 operator chain。它依赖可分解性、代数结构和分配律；只要这些条件不成立，整套推导就无法使用。即便融合在语义上合法，也未必总是划算，因为 correction 会增加额外算术开销，并提升寄存器与片上存储压力。作者也因此明确把“建立 cost model 来决定何时不该融合”列为未来工作。

实现范围同样比标题显得更窄一些。当前系统主要围绕 TVM、TileLang 和 GPU 展开，最强证据也集中在 NVIDIA 硬件上。附录虽然补充了 non-ML workload 和一些跨平台结果，但论文主体依然是在 AI 子图层面验证方法，而不是在完整 accelerator stack 或完整应用流水线上做端到端证明。最后，RedFuser 之所以能保持轻量，也是因为它严格限制了自己处理的算子家族；更宽松的 reduction 语义仍然留待后续工作。

## 相关工作

- _Dao et al. (NeurIPS '22)_ — FlashAttention 为 attention 手工推导了 tiled online softmax，而 RedFuser 试图从符号化归约方程里自动导出同类增量更新。
- _Zheng et al. (ASPLOS '22)_ — AStitch 扩大了机器学习工作负载中的算子融合机会，但没有把依赖式 reduction chain 形式化为一个带显式代数判定条件的类别。
- _Xia et al. (ASPLOS '24)_ — SOUFFLE 擅长把 reduction 周边的 tensor operator 激进融合，而 RedFuser 的重点是把一个归约阶段继续融合进下一个归约阶段，并生成带校正项的增量形式。
- _Zhang et al. (SC '24)_ — MCFuser 优化的是 memory-bound、compute-intensive 的算子链；RedFuser 则直接针对 cascaded reductions 本身更棘手的依赖结构。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "FuseFlow: A Fusion-Centric Compilation Framework for Sparse Deep Learning on Streaming Dataflow"
oneline: "FuseFlow 把稀疏 PyTorch 模型编译成融合后的 SAMML 图，并把 fusion granularity 与 dataflow order 变成显式调度选择。"
authors:
  - "Rubens Lacouture"
  - "Nathan Zhang"
  - "Ritvik Sharma"
  - "Marco Siracusa"
  - "Fredrik Kjolstad"
  - "Kunle Olukotun"
  - "Olivia Hsu"
affiliations:
  - "Stanford University, Stanford, USA"
  - "SambaNova Systems, Inc., Palo Alto, USA"
  - "Barcelona Supercomputing Center, Barcelona, Spain"
  - "Carnegie Mellon University, Pittsburgh, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790165"
tags:
  - compilers
  - hardware
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

FuseFlow 是一套面向可重构 streaming-dataflow accelerator 的稀疏深度学习编译器。它最关键的做法，是把跨表达式融合从“单个 kernel lowering 的副产物”提升为显式可调度的编译决策，并用基于 partial order graph 的融合算法和新的 fusion table IR 生成 factored-iteration 的 SAMML 图。论文在 GCN、GraphSAGE、sparse autoencoder 和带 BigBird attention 的 GPT-3 上都展示了收益，同时也明确说明：对稀疏模型来说，端到端 full fusion 并不总是最优。

## 问题背景

这篇论文的出发点，是新型硬件和现有编译支持之间的明显脱节。稀疏深度学习越来越依赖专用加速器与 dataflow 架构，因为 sparsity 虽然能减少算术与内存需求，却会带来很不规则的访问模式，而 GPU 往往处理得并不好。作者给了一个很直观的例子：在 RTX 5090 上跑 PyTorch Geometric 的 GCN inference，平均 SM 利用率只有 16.7%，内存利用率大约 1%，说明传统架构并没有把这些稀疏工作负载的潜力真正吃干净。

之前的 sparse-dataflow compiler，尤其是 SAM/Custard，已经能把单个 sparse tensor algebra expression lowering 成 dataflow graph，但这离“能编译完整 ML 模型”还差得很远。现代模型包含连续的 kernels、nonlinearity、masking，以及各种会改变“该不该继续融合”的边界操作。已有稀疏编译器通常只做单表达式 lowering、只支持少量手写模式的 operator fusion，或者默认“融合越多越好”。但对 sparse ML 来说，这个默认前提并不成立：融合过深会把 coordinate-processing 成本和 nested recomputation 放大，融合过浅又会把中间结果频繁落回内存，增加数据搬运。

因此，真正的系统问题有两个。第一，编译器怎样才能跨多个 sparse expressions 做融合，同时不违反每个 tensor 自己的存储顺序约束？第二，就算逻辑上能融合，怎样把它 lowering 到 streaming dataflow machine 上，而不是退化成一个低效的 global iteration space？FuseFlow 的定位，就是第一个同时把这两个问题都纳入端到端 sparse DL inference 编译流程的稀疏编译器。

## 核心洞察

论文最重要的洞察是：稀疏融合不应该被看成“把表达式硬拼在一起”，而应该被建模为一个带约束的全局排序问题；随后再把这个排序 lowering 成 factored iteration，而不是一个完全展开的 global loop nest。多个 sparse expressions 被融合之后，每个 tensor view 都会因为自己的存储格式而要求某种遍历顺序，每个局部 kernel 还可能因为用户指定的 dataflow order 施加额外约束。FuseFlow 用 partial order graph（POG）统一表达这些限制，于是“这几个 kernels 能不能融合”就变成了“是否存在一个同时满足 mode-order 与 producer-consumer 约束的 concordant topological order”。

这个洞察的价值，在于它把“正确性”和“激进程度”分开了。只要 POG 保持无环，FuseFlow 就能跨表达式融合、合并等价 tensor views，并且只在不同 views 的顺序要求确实冲突时，才退回去 materialize 一个 permuted copy。接下来，它并不生成一个全局稀疏迭代空间，而是把程序 lowering 成多个 factored subspaces，让 input iteration 和 computation 交错出现。读完六个月后最该记住的一句话是：对 sparse ML 来说，fusion 真正有效的前提，不是盲目把更多层塞进同一个 kernel，而是既保住 sparse-format 约束，又把 coordinate processing 尽量限制在局部。

## 设计

FuseFlow 的输入来自 PyTorch 经过 Torch-MLIR 或 MPACT lowering 到 MLIR 的 `Linalg + SparseTensor` dialects。模型里的 sparse tensors 可以来自 graph adjacency、pruned weights、masked activations 等不同来源，只要 sparse structure type 在编译时已知即可。用户可以显式标注 sparse formats，也可以用 `Fuse{}` schedule 标出希望融合的区域，并进一步控制 dataflow order、parallelization 等参数。

第一个核心机制是 cross-expression fusion algorithm。对 fusion region 里的每个 expression，FuseFlow 会先重命名局部 reduction indices，把同一个 tensor 的多次使用拆成不同 tensor views，再把 mode-order 约束和 dataflow-order 约束都加进 POG。之后，producer 的输出会被内联到 consumer 里。如果多个 views 等价，它们会被合并；如果它们引入了环，就通过 materialize 一个转置视图来打破冲突。最后，对 POG 做 topological sort，就能得到合法的 fused dataflow orders。

第二个核心机制是 fusion table IR，这也是论文最有辨识度的 lowering 设计。它的 rows 表示 fused iteration order，columns 表示 tensor views 与中间表达式，cells 则要么实例化一个 SAMML primitive，要么用名字引用一个未来才会物化的 stream。这个间接层非常关键，因为 dataflow graph 需要的是空间上的连线关系，而不仅仅是 loop transformation：后续计算经常需要引用“还没被真正创建出来”的 stream。Fusion table 让编译器能够延迟图构建、通过移动 cells 来创建 intersect/union 和高阶 reduction，最后生成 input-iteration 区域与 compute 区域交错的 factored SAMML graph。

围绕这两个机制，论文还实现了几个让系统真正可用的优化：通过复制与合并 streams 实现用户可控的 parallelization；对 BigBird 这类 block-sparse tensors 的 sparsity blocking；枚举合法 dataflow orders；以及一个快速 heuristic，用 FLOPs 和 bytes 的近似值先剪掉明显差的 schedules，再决定是否做 cycle-accurate simulation。

## 实验评估

实验覆盖四类 sparse models：3 层 sparse autoencoder、2 层 GCN、2 层 GraphSAGE，以及带 BigBird attention 的 GPT-3 Small，序列长度为 1024。数据集的 sparsity 从 50% 到 99.9% 不等，既包含 lossless 的输入稀疏性，也包含 lossy 的权重或 mask 稀疏性。实现上，所有模型编译时间都低于 750 ms，然后被送到 Comal 这个 cycle-accurate simulator 上执行，内存模型则由 Ramulator 2.0 提供 HBM2 模拟。为了说明结果不只是 simulator artifact，作者还把若干 kernels 和通过 Vitis HLS 生成的 FPGA RTL 做对比，得到 `R^2 = 0.991` 的高一致性。

最有说服力的是 fusion 结果本身很“有条件”，因此显得可信。GPT-3 with BigBird 从 full fusion 中获益最多，最高达到约 `2.7x`。GCN 和 GraphSAGE 则不是这样：对它们来说，partial fusion 才是最佳方案，最高分别达到 `2.6x`（OGB-Collab）和 `3.9x`（OGB-MAG）；full fusion 反而因为 nested sparse matrix multiplication 带来的额外 recomputation 而掉速。Sparse autoencoder 又是另一种形态：full fusion 可以到 `1.94x`，但 partial fusion 几乎没什么帮助，因为每层里主导成本的大型 sparse matmul 已经压过了后面的几个小算子。这组结果非常直接地支撑了论文的核心论点：fusion granularity 必须按模型来选。

与 prior sparse dataflow compilers 的比较也设计得很到位。在 OGB-Collab 上的 GCN 实验中，Custard/Stardust 风格、带手工改写的方案相对 unfused baseline 能做到 `1.97x`，而 FuseFlow 达到 `2.63x`，也就是比这个人工重写版本再多 `1.33x`。论文把收益归因于两点：自动 cross-expression fusion 避免了更多中间结果 materialization；而 factored iteration 降低了 coordinate overhead。Heuristic 的精度也还不错，在报告的工作负载上，FLOP 误差为 `1.8%-2.8%`，byte 误差为 `5.7%-11.5%`，足以承担 pruning 的角色。我认为这套实验对论文主张的支撑度较高，不过边界也很清楚：它覆盖了多类 inference-oriented 稀疏模型，但依旧主要是 simulator-backed evaluation，而不是完整部署到真实端到端硬件系统。

## 创新性与影响

相对于 _Hsu et al. (ASPLOS '23)_，FuseFlow 最核心的新意，是把 SAM 的单表达式 lowering 扩展成面向 sparse ML 程序的一般化 cross-expression fusion，并配套一个明确生成 factored iteration、而不是 global iteration 的 lowering 策略。相对于 ReACT 这类 CPU/GPU 稀疏编译器，它不仅提出了新的受约束融合表述，还把目标落在 streaming dataflow hardware 上。相对于 accelerator modeling 工作，它给出的不是“如何估算性能”，而是“如何编译出能跑的程序图”。

因此，这篇论文对两个社区都很重要。对稀疏编译器研究者来说，它把 fusion granularity 提升成 sparse dataflow program 的一等调度维度。对 accelerator architect 来说，它说明真正决定 sparse fusion 是否硬件友好的，不只是新 functional units，还有编译器能否处理 tensor-view ordering。它更像一篇提出新机制的论文，而不是测量论文，也不是把已有 fusion 技巧重新包装一下。

## 局限性

FuseFlow 要求 sparse structure type 在编译前已知，所以它并不能处理那种 sparsity format 本身会在运行时不可预测变化的工作负载。它还需要用户显式标记 fusion regions 并表达调度意图；作者提到 autoscheduling 仍属于未来工作，这意味着当前接口虽然强大，但明显更适合专家用户。

从性能角度看，论文也很诚实地承认 full fusion 可能有害。这在科学上是优点，但也意味着实际部署时不能期待一个统一默认配置，而必须做 schedule exploration。Heuristic 能帮忙剪枝，可即便是加了约束后的 dataflow-order 空间，仍可能很大。最后，真实硬件落地仍然不完整：simulator 验证做得很认真，但真正支持端到端 sparse ML 的 accelerator 生态仍在发展中，尤其是支持 nonlinear 与 masking 的 backend 还不成熟。

## 相关工作

- _Hsu et al. (ASPLOS '23)_ — SAM/Custard 能把单个 sparse tensor expression lowering 到 dataflow graph；FuseFlow 保留这套底座，但增加了跨表达式融合和面向 ML 的算子支持。
- _Hsu et al. (CGO '25)_ — Stardust 也面向 sparse dataflow hardware，但仍停留在单表达式层面，而不是完整 sparse ML pipeline。
- _Zhou et al. (PACT '22)_ — ReACT 同样生成 factored iteration code，并消除 sparse tensor algebra 中的冗余；但它面向 CPU/GPU 风格执行，也不处理 dataflow hardware 上的独立表达式融合。
- _Nayak et al. (MICRO '23)_ — TeAAL 用声明式方式描述 cascaded Einsums 与 sparse accelerators；FuseFlow 则把这些融合计算真正编译成可执行的 SAMML graphs。

## 我的笔记

<!-- 留空；由人工补充 -->

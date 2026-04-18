---
title: "Trinity: Three-Dimensional Tensor Program Optimization via Tile-level Equality Saturation"
oneline: "Trinity 把代数改写、内存访问与内核结构统一到 tile 级 IR 里做 equality saturation，让编译器能联合发现跨算子的高性能 Transformer 内核。"
authors:
  - "Jaehyeong Park"
  - "Youngchan Kim"
  - "Haechan An"
  - "Gieun Jeong"
  - "Jeehoon Kang"
  - "Dongsu Han"
affiliations:
  - "Korea Advanced Institute of Science and Technology, Daejeon, Republic of Korea"
  - "FuriosaAI, Seoul, Republic of Korea"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790240"
tags:
  - compilers
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Trinity 是一个把优化下推到 tile 粒度的 tensor compiler，然后在这个表示上运行 equality saturation。它的关键做法，是把代数改写、显式 load/store，以及 kernel 结构选择都变成同一个 IR 里的可重写项，因此编译器不仅能重新发现 FlashAttention 一类的调度，还能进一步融合手写内核通常覆盖不到的前后算子。论文在多种 dense Transformer 变体上报告，相比 TensorRT 最多快 `2.09x`，相比 Mirage 最多快 `3.07x`，在 Vanilla attention 上相比 FlashInfer 最多快 `1.35x`。

## 问题背景

论文针对的是一个很典型的编译器分层问题。图级优化器负责改写 tensor operator、做相邻算子融合；算子级编译器再分别决定 tiling、循环顺序、内存放置和并行化。这样的分工对普通 kernel 生成够用，但它恰好挡住了 FlashAttention 这类优化真正依赖的东西：代数形式要改、tile 要留在片上、执行顺序也要重排，而且这三件事必须一起发生。

作者认为这已经不是少数特例。Transformer 变体还在持续增加，GPU/NPU 的内存层次与 tensor core 行为也在变化。为每个模型和硬件手工写特化 kernel 已经不可持续，但现有分离式编译流水线在图级把算子内部当黑盒，在调度级又把图结构当常量，于是大量跨算子、tile 级的程序变体根本没有进入搜索空间。

如果直接说“那就联合穷举搜索”也不行。论文声称，即便是一个基础的 Vanilla Transformer block，也会产生超过 `10^17` 个等价程序。像 Mirage 这样的多层联合搜索一旦做穷举，就要么超时，要么被迫先把程序切成小碎片，而这又正好破坏了 Trinity 想抓住的跨边界优化机会。所以真正的问题是：怎样在不牺牲 stateful memory operation 正确性的前提下，搜索这个强耦合空间，而不是被组合爆炸直接压垮。

## 核心洞察

这篇论文最重要的命题是：tile 粒度正好是 tensor program 性能三大维度第一次同时显式出现的层次，也就是 algebraic equivalence、memory I/O 和 compute orchestration。若停留在 tensor operator 粒度，内存与循环结构是隐藏的；若继续下钻到更低层实现细节，搜索空间又会变得过于语法化且过大。tile 是一个刚好的中间层，编译器还能做符号推理，同时又已经在使用 GPU/NPU 真正执行的单位思考。

一旦程序被写成这种形式，equality saturation 就很有吸引力，因为它能把许多等价候选同时保留下来，而不是过早贪心地选定一条路径。但要让这件事成立，IR 必须能安全表达 sequence、loop、load、store，提取阶段也必须处理依赖上下文的代价。于是 Trinity 真正的洞察其实是两层：先用 tile 级 stateful IR 把“正确的优化选择”表达出来，再围绕 equality saturation 加上一套机制，让这种 stateful 表示不会把 e-graph 直接拖垮。

## 设计

Trinity IR 里有三类一等公民。对 memory I/O，它区分 `input`、`output`、`variable` tensor，并把 `load` 和 `store` 显式化。对 compute orchestration，它暴露 `seq` 与 `loop`，于是 kernel boundary、顺序依赖和并行 loop nest 都可以被重写。对 algebra，它把每个 tile 当作一个小 tensor，支持常见的逐元素运算、reduction、reshape 与 `matmul`。这是联合优化的表示基础。

在这个 IR 之上，Trinity 应用两大类 rewrite rule。循环类规则负责 fusion、fission、loop-invariant code motion、loop insertion 与 reindexing。代数类规则则包括常见 tensor 恒等式，以及能把除法或乘法从内层循环提出来、从而消掉 loop-carried dependence 的 loop-body factoring 规则。论文里最能说明问题的是 fully fused attention 案例：Trinity 从一个朴素的 QKV projection 加 attention 程序出发，先融合 attention 内层循环，再利用 distributivity 与 algebraic factoring 去掉 accumulator 依赖，重新发现 FlashAttention 的 online-softmax 结构，随后继续把前面的 QKV projection 和 reshape 也融合到同一个最终 kernel 中。

有三套机制让 saturation 在这个 stateful IR 上真正可用。第一，expression propagation 会记录一次 `store` 实际写入的符号表达式，并把后续对同一 tile 的 `load` 重写成该表达式，从而让代数规则能跨越 memory boundary 继续匹配。第二，Trinity 把所有 sequence 规范化成右结合的 `seq` 形式，避免因为等价括号化方式太多而导致 e-graph 指数膨胀。第三，它使用 `egg` 的 e-class analysis 跟踪读写区域、别名关系、循环变量依赖与 shape；只有当语义依赖检查证明重排安全时，相关 rewrite 才允许触发。

提取阶段也做了定制。由于一个操作的代价取决于它是否留在片上、是否跨 kernel boundary、以及是在并行还是顺序上下文里执行，Trinity 不能像传统 equality saturation 那样只跑一遍固定代价提取。它采用两阶段提取：第一阶段先按最小 kernel 数枚举 loop structure，把 kernel launch 和跨 kernel 内存流量当作主导的粗粒度成本；第二阶段在 loop structure 固定后，再贪心选择使每个计算单元 FLOPs 最小的 loop body。随后系统把候选 lowering 到 Triton，让最外层并行 loop 成为 kernel，在尽量把中间结果留在片上的前提下决定 tile placement，并在 profiling 时再确定具体 tile size。

## 实验评估

实验覆盖六种 dense Transformer 风格工作负载：Vanilla、Pre-Norm、QK-Norm、RoCo、KeyFormer 和 SwiGLU FFN。作者使用 LLaMA3 8B 与 Falcon 7B 配置，在 speculative decoding 场景下评测，具体是 `1008` 个前缀 token 加上 `16` 个待验证 token；硬件包括 `H100`、`A100`、`RTX 4090` 和 `RTX 5090`。基线则包含 TorchInductor、TensorRT、FlashTensor、Relax、Mirage，以及适用时的 FlashInfer。

核心延迟结果相当强。在 H100 上、LLaMA3 8B 配置下，Trinity 相比 TensorRT 在 Vanilla 上快 `1.71x`，Pre-Norm 快 `1.43x`，QK-Norm 快 `1.63x`，KeyFormer 快 `1.29x`，RoCo 快 `1.37x`，SwiGLU FFN 快 `1.10x`。相对 Mirage，论文报告的最大收益达到 `3.07x`。在 Vanilla attention 上，Trinity 相比 FlashInfer 快 `1.35x`，原因是它不只优化 attention 核心，还把前面的 QKV projection 与 reshape 一起并进单个 kernel。Pre-Norm 的结果尤其能说明方法论：通过把 RMS 计算插入 projection loop，再用代数改写把程序改造成可融合形式，Trinity 在 H100 上比 Mirage 快 `1.40x`。

论文的自动硬件适配故事也比较有说服力。对 KeyFormer，Trinity 在 H100 和 RTX 4090 上选出的最优 kernel 不一样。对于带宽更高的 H100，最优方案会把部分中间结果临时 spill 到片外，以换取更大的 tile 和更少的迭代次数；对于带宽受限的 RTX 4090，最优方案则把中间值尽量留在片上，即便这意味着更小的 tile。这个结果很好地支撑了作者的主张：memory placement 和 kernel structure 必须留在搜索空间里，不能在表示层被提前折叠掉。

编译成本不低，但对 ahead-of-time kernel generation 仍然算可接受。Trinity 声称搜索空间可以大到 `10^21` 个等价程序，但仍能在 `710` 秒和 `1459` 秒内分别完成 RoCo 与 KeyFormer 这类完整组件的优化。作者还报告，在同样需要先分块的前提下，Mirage 在这些基准上需要 `7.5x-38.1x` 更久。我认为这组实验整体上是支持论文主张的：工作负载确实覆盖了优化器主打的 fused attention 和 fused feed-forward 结构，而且比较对象也是真正有代表性的编译器基线，而不是弱化后的自制实现。

## 创新性与影响

和 _Yang et al. (MLSys '21)_ 相比，Trinity 的新意不只是把 equality saturation 用到 tensor algebra 上，而是把它扩展到了一个 stateful 的 tile 级 IR，让 memory traffic 与 loop structure 也能被重写。和 _Shi et al. (OSDI '23)_、_Park et al. (NeurIPS '23)_ 相比，它的贡献不只是更好的 tiling 或固定计算上的并行化，而是先用代数改写把“原本不可融合”的计算改造成可融合形式。和 _Wu et al. (OSDI '25)_ 相比，它最重要的进步是可扩展性，因为 Trinity 不需要像 Mirage 那样靠穷举 µGraph 并强行切分小片段来维持可运行。

因此，这篇论文对两类人都很重要。对 tensor compiler 研究者来说，它是少数真正试图把 graph rewriting、scheduling 和 memory placement 放进同一个优化回路的工作。对 kernel 工程师来说，fully fused attention 这个案例说明，一些过去看起来“只能手写”的优化，其实可能只是因为编译器之前站错了抽象层次。

## 局限性

论文当前仍然聚焦于推理阶段的 dense tensor program，尤其是 Transformer block。训练图和 backpropagation 只是未来工作，不在当前系统与实验范围内。Trinity 还依赖 Triton 做代码生成，因此暂时无法利用 Hopper 上的 warp specialization 或 TMA 这类特性，而作者也明确指出这些特性对 FlashAttention-3 等级的 kernel 很重要。

编译开销同样不能忽视。即使 e-graph 已经足够紧凑，提取阶段仍可能耗费数分钟，之后还要对最多 `512` 个候选做 profiling；论文评测里甚至使用了八张 GPU 来并行完成 profiling。这对离线编译可以接受，但显然不适合快速 JIT 部署路径。最后，作者也承认，像 attention 加 FFN 这样的更大组合程序仍会让当前“固定轮数套用所有规则”的策略吃力，而且生成结果只是数值上等价于原程序，不能保证 bit-identical，因为其中包含浮点重排。

## 相关工作

- _Yang et al. (MLSys '21)_ — TENSAT 用 equality saturation 做 tensor graph superoptimization，但它停留在 tensor-operator 粒度，无法推理 tile placement 或 kernel boundary。
- _Shi et al. (OSDI '23)_ — Welder 强调通过 tile graph 改善深度学习的内存调度，而 Trinity 把 algebraic rewrite、memory I/O 与 loop structure 放进同一个联合搜索空间。
- _Wu et al. (OSDI '25)_ — Mirage 是 Trinity 最接近的直接基线，但它的穷举式多层搜索必须先切分小片段，因此会错过跨分区的融合机会。
- _Dao et al. (NeurIPS '22)_ — FlashAttention 是经典的手工 online-softmax 调度，而 Trinity 能自动重新发现它，并继续扩展到 fully fused attention。

## 我的笔记

<!-- 留空；由人工补充 -->

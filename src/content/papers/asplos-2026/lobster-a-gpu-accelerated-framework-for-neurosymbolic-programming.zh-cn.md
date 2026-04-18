---
title: "Lobster: A GPU-Accelerated Framework for Neurosymbolic Programming"
oneline: "Lobster 把基于 Datalog 的 neurosymbolic 程序编译到面向 GPU 的 APM IR，让 join、provenance 标签和不动点求解都能在 GPU 上执行。"
authors:
  - "Paul Biberstein"
  - "Ziyang Li"
  - "Joseph Devietti"
  - "Mayur Naik"
affiliations:
  - "University of Pennsylvania, Philadelphia, Pennsylvania, USA"
  - "Johns Hopkins University, Baltimore, Maryland, USA"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3760250.3762232"
code_url: "https://github.com/P-bibs/Lobster"
tags:
  - gpu
  - compilers
  - ml-systems
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Lobster 是一个面向 Datalog-based neurosymbolic 程序的 GPU 原生执行框架。它的关键做法是把关系代数计划编译成一个受约束的中间表示 `APM`，让列式表、显式分配、SIMD 友好的算子和 semiring 标签传播天然匹配 GPU。这样一来，离散、概率和可微推理都可以在不改写用户程序的前提下迁移到 GPU 上执行。

## 问题背景

这篇论文抓住的是现代 neurosymbolic 系统里的一个明显失衡：神经网络部分早已充分利用 GPU/TPU，而符号推理部分往往还停留在 CPU 上。这个失衡在 Scallop 一类系统中尤其严重，因为符号执行不是一个训练后的附加步骤，而是嵌在训练和推理环路中的核心部分；更麻烦的是，它还要随着元组一起携带概率或可微 provenance。随着推理链变长，系统不仅要处理更多派生事实，还要处理更复杂的标签，因此时间和空间复杂度会一起膨胀。

现有工作都只覆盖了问题的一部分。Souffle 这类高性能 Datalog 引擎擅长 CPU 执行，但不支持 neurosymbolic 学习所需的 provenance 语义；FVLog 这类 GPU Datalog 工作能加速离散关系执行，却不支持概率或可微推理。理论上，专家可以为单一任务手写 CUDA kernel，但那不是一个可复用的编程模型。于是，论文真正要回答的是：能否把一个通用的、基于 Datalog 的 neurosymbolic 语言映射到 GPU 上，同时保留让 neurosymbolic 编程有价值的丰富语义？

## 核心洞察

论文的核心判断是，正确的抽象边界不是“把 Datalog 直接编译成 CUDA”，而是“先把 Datalog 编译成一个长得像 GPU 的关系型 IR，再让高效执行几乎成为必然结果”。这个 IR 就是 `APM`（Abstract Parallel Machine）。`APM` 被有意设计得很克制：没有通用控制流，寄存器分配显式化，缓冲区遵循 SSA 风格，表采用列式布局。这些限制恰好对齐了 GPU 真正擅长的执行模式，尤其适合 join、project、scan、sort 和去重。

更重要的是，这个抽象层也为 provenance 提供了统一落点。Lobster 不是把概率或可微推理当成离散 Datalog 之上的补丁，而是把 semiring 标签和普通列一起存进寄存器包里，并在运行时定义对应的 `⊕` 与 `⊗`。换句话说，`APM` 同时承担了两件事：一方面显式暴露数据并行性，另一方面系统化地保留 tagged semantics。

## 设计

Lobster 的编译流程从 Datalog 程序开始，先借助已有前端把它降到 relational algebra machine（`RAM`），再把 `RAM` 表达式 DAG 展平成顺序的 `APM` 指令。关系被表示为一组等长寄存器：每一列一个寄存器，外加一个 provenance 标签寄存器。Projection 很直接，因为每一行都能独立变换；join 才是关键难点，因此系统把 join 编译成一条面向 GPU 的哈希流水线，核心算子包括 `build`、`count`、`scan`、`join` 和 `gather`。连接结果的 provenance 则在 `gather` 时通过对输入标签做乘法来合成。

执行层面，Lobster 使用 least-fixpoint iteration 加 semi-naive evaluation。运行时把事实划分为 `stable`、`recent` 和 `delta` 三类，只对 frontier 应用递归规则，而不是每轮都对全量关系重复求值。论文很强调，这不是外加在执行器外面的“小技巧”，而是直接编码进 `APM` 的语义里，所以排序、去重、frontier 维护和 merge 同样都在 GPU 上完成。

Provenance 框架也不是只为单个 benchmark 服务。Lobster 实现了七种 semiring，覆盖离散、概率和可微三种模式，包括 `unit`、`max-min-prob`、`add-mult-prob`、`top-1-proof` 以及对应的可微版本。作者做出的关键工程折中是：它不支持完全一般的 `top-k-proofs`，而只实现 `top-1-proof`，也就是每个事实只跟踪一条 proof，并要求最大 proof 大小可提前给定。论文实验里把这个上限设为 300。

系统优化部分同样重要。由于 `APM` 的分配点显式、循环结构固定，Lobster 在内存允许时可以使用 arena allocation，在内存紧张时则退回 buffer reuse。若 join 的一个输入来自在不动点迭代中保持不变的 EDB，编译器会把对应哈希表标成 static register，从而跨迭代复用。对批量训练，系统通过在每个表前面加一个 sample-id 寄存器来编码 batch，既阻止不同样本之间发生错误 join，又保留原有求值语义。实现上，Lobster 复用了 Scallop 的前端和 query planner，再增加约 2,000 行 Rust 与 9,000 行 CUDA/C++ 代码来构建新的编译器和运行时。

## 实验评估

实验足够宽，能够支撑“通用框架”这一主张。Lobster 被用于十个任务，覆盖图像推理、自然语言推理、程序分析、生物信息、规划和图计算，同时横跨 differentiable、probabilistic 和 discrete 三种模式。带标签的 neurosymbolic 工作负载主要与 Scallop 比较，另外在不同子问题上还和 ProbLog、Souffle、FVLog 对照。

最醒目的结果是，Lobster 相对 Scallop 的平均加速为 `3.9x`，而个别任务远高于此。端到端训练时间提升范围是 `1.2x` 到 `16.46x`，其中 PacMan-Maze 收益最大，因为该任务里符号计算占比最高。推理任务上，CLUTRR 达到 `3.69x` 加速，Pathfinder 为 `1.55x`，PacMan 为 `2.11x`。在 probabilistic static analysis 中，多个程序相对 Scallop 提升到 `12x-19x`。RNA secondary structure prediction 也很有说服力：在最短的 28-base 序列上 Lobster 反而比 Scallop 慢，但对更长序列它经常快两个数量级，而长序列恰恰是符号扩展性真正重要的区间。

离散任务的结果同样值得注意，因为它说明 Lobster 不只是“为了通用性勉强可用”。在 transitive closure 上，它稳定击败仅运行在 CPU 上的 Souffle，也经常能与 FVLog 这样的专用 GPU Datalog 系统竞争甚至更快。在 Same Generation 上，只要两边都能跑完，Lobster 在每个数据集上都至少比 FVLog 快 `2x`，当然两者也都会在部分图上遇到 OOM。总体来看，这组实验较好地支持了论文的主论点：Lobster 不是某一种 provenance 的单点加速器，而是一个可复用的 tagged Datalog GPU 执行底座。

## 创新性与影响

相较于 _Li et al. (PLDI '23)_，Lobster 的关键进展不是改进 Scallop 的语言表面，而是把 Scallop 风格的 neurosymbolic 语义整体迁移到 GPU。相较于 _Shovon et al. (USENIX ATC '23)_ 以及后续 FVLog 工作，Lobster 的新意在于把 provenance-aware 的概率和可微执行也纳入 GPU 加速，而不是只做离散 Datalog。相较于 _Manhaeve et al. (NeurIPS '18)_，它把 symbolic execution 视为需要编译和优化的系统瓶颈，而不只是一个推理抽象。

因此，这篇论文对两个群体都重要。对 neurosymbolic 研究者来说，它扩大了基于 Datalog 的方法能够实际覆盖的问题规模。对系统研究者来说，它证明了：即便逻辑执行中携带复杂 provenance，也仍然可以在不放弃编译器结构的前提下映射到 GPU。

## 局限性

论文也很清楚地承认 Lobster 不是完全一般的系统。最明显的语义限制是它不支持完整的 `top-k-proofs`，而只支持更窄但更高效的 `top-1-proof`。同时，proof 大小必须提前设上界，实验里设为 300。最有效的 join 优化之一，即通过 static register 复用哈希表，也依赖于线性递归结构，也就是 join 的某个输入在跨轮次时保持不变，因此收益会受工作负载特征影响。

系统层面同样存在边界。Lobster 的并行性主要发生在单个关系算子内部，而不是算子之间；论文也明确说，由于 CPU-GPU 传输本来就很少，算子级流水化并没有带来额外收益。一些离散 benchmark 仍然会 OOM，这说明通用性与 provenance 跟踪确实要付出额外存储代价。最后，Lobster 复用了 Scallop 的前端与 query planner，所以更准确的定位是“新的执行底座”，而不是一套从语言到运行时全部重写的 neurosymbolic 栈。

## 相关工作

- _Li et al. (PLDI '23)_ — Scallop 提供了 Lobster 所加速的 Datalog-based neurosymbolic 语言；Lobster 基本保留其语义，但用面向 GPU 的 IR 与运行时替换了 CPU 执行。
- _Shovon et al. (USENIX ATC '23)_ — 这类 GPU 上的 iterative relational algebra 工作启发了 Lobster 的 hash-join 设计，但 Lobster 进一步加入了 provenance 标签传播以及可微/概率语义。
- _Sun et al. (2025 arXiv)_ — FVLog 是最接近的离散 GPU Datalog 系统；Lobster 更通用且性能常常不落下风，但也因此承担了更高的内存开销。
- _Manhaeve et al. (NeurIPS '18)_ — DeepProbLog 把神经与符号推理结合起来，而 Lobster 的重点是让符号内核本身快到不再成为瓶颈。

## 我的笔记

<!-- 留空；由人工补充 -->

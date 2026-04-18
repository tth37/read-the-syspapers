---
title: "Streaming Tensor Programs: A Streaming Abstraction for Dynamic Parallelism"
oneline: "STeP 把动态张量形状与数据相关控制流变成 SDA 的一等公民，从而支持动态分块、专家时分复用与负载均衡 attention。"
authors:
  - "Gina Sohn"
  - "Genghan Zhang"
  - "Konstantin Hossfeld"
  - "Jungwoo Kim"
  - "Nathan Sobotka"
  - "Nathan Zhang"
  - "Olivia Hsu"
  - "Kunle Olukotun"
affiliations:
  - "Stanford University"
  - "SambaNova Systems"
  - "Carnegie Mellon University"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790229"
tags:
  - hardware
  - compilers
  - pl-systems
  - ml-systems
reading_status: read
star: true
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

STeP 是一个面向 spatial dataflow accelerators 的编程抽象，它把动态张量形状和数据相关控制流显式放进抽象里，而不是继续依赖静态 padding 或标量化控制。借助符号化的 stream-shape 语义、显式内存操作符以及动态 routing / merging 操作符，STeP 能原生表达 dynamic tiling、configuration time-multiplexing 和 dynamic parallelization；在模拟实验里，这些能力带来了 `1.33x-2.11x` 的 Pareto 改进和最高 `1.27x` 的端到端加速。

## 问题背景

这篇论文抓住的是一个越来越明显的错位：现代 ML 工作负载已经高度动态，但现有 SDA 编程抽象大多仍按“静态张量程序”来设计。MoE 的 expert 路由、attention 的可变 KV-cache 长度，以及 batch 组成的 runtime 波动，都会带来动态张量形状和数据相关控制流。硬件层面上，SDA 其实很适合这种工作负载，因为它本来就是由异步运行的计算单元、存储单元和 FIFO 通信组成；真正跟不上的是软件抽象。

现有方案各缺一块。Spatial、Revet 这类 imperative 抽象让程序员看见内存层次，但动态行为受限、静态化严重，或者只能落到标量动态原语上。StreamIt、SAM、Ripple 这类 streaming 抽象更贴近 dataflow 执行，但它们分别有固定 data rate、只适合 sparse tensor algebra、或把 memory hierarchy 留成隐式细节的问题。结果是，真正重要的 schedule 决策，例如按 expert 实际 token 数决定 tile 大小、把一套配置在多个 expert 之间时分复用、或把 attention 工作发给先空出来的流水线，都很难在抽象层被清楚表达和分析。

## 核心洞察

论文的核心判断是：动态张量程序依然可以用 stream 来表示，而且不必因此牺牲可分析性，前提是抽象必须同时显式表达三件事：符号化 shape、内存放置和控制流路由。STeP 保留了 SDA 异步 dataflow 的基本精神，但不再把 runtime 变化当成黑盒，而是用 stop token 与符号 shape 把这些变化直接编码进 stream 语义。

这样一来，“动态性”就从实现细节变成了可推理对象。STeP 里的 stream 具有编译期已知的 rank 和 data type，但维度可以是 static、dynamic-regular 或 ragged。程序员因此可以在抽象层直接追问：这个 schedule 要多少 on-chip memory？这种 control-flow 模式会增加多少 off-chip traffic？runtime 应该形成什么 tile？论文真正的洞察是，SDA 不缺 stream abstraction，缺的是足够丰富的 stream semantics。

## 设计

STeP 的 stream data type 可以是 tile、selector、on-chip memory reference，或这些值的 tuple。操作符分成五类：`LinearOffChipLoad`、`RandomOffChipLoad` 这类 off-chip memory operator；`Bufferize`、`Streamify` 这类 on-chip operator；`Partition`、`Reassemble`、`EagerMerge` 这类 routing / merging operator；`Accum`、`Map`、`FlatMap` 这类 higher-order operator；以及 `Flatten`、`Reshape`、`Promote`、`Expand`、`Zip` 这类只改写结构的 shape operator。

简化 MoE 例子很好地说明了这些部件如何配合。`Partition` 先把 token 行路由到不同 expert，得到符号化 stream size `[D_i, 1]`。随后，`Flatten`、`Reshape` 和 `Accum` 把多个 `[1,64]` tile 打包成 `[4,64]`，把 expert 计算变成更高效的 matrix-matrix。`LinearOffChipLoadRef` 再依据 `ceil(D_i / 4)` 这个符号计数加载对应次数的权重 tile，最后由 `Reassemble` 按原顺序收回结果。围绕这个抽象，作者还实现了 symbolic Python frontend 和 Rust simulator：前者基于 SymPy 推导 off-chip traffic 与 on-chip memory 的符号表达式，后者结合 Roofline 风格模型与 Ramulator 2.0 的 HBM 时序来估计周期数，并在一个 SwiGLU layer 上与 cycle-accurate Bluespec HDL 模型取得 `0.99` 的 Pearson correlation。

## 实验评估

实验聚焦于 LLM inference 中两个最典型的动态热点：带有 SwiGLU expert 的 MoE layer，以及 decoding 阶段的 attention。作者使用 Qwen3-30B-A3B 和 Mixtral-8x7B，KV-cache 长度来自 AzureLLMInference trace，expert routing 来自 HH-RLHF 驱动出的真实分布。基线也比较克制：作者先用 STeP 实现所有 Revet 能表达的 schedule，再与只有 STeP 才能表达的新 schedule 对比。

dynamic tiling 是最清楚的一组结果。batch=`64` 时，Mixtral-8x7B 在与静态 `tile=16` 相同 on-chip memory 下获得 `1.65x` 加速；Qwen3-30B-A3B 则在比静态 `tile=8` 少用 `2.1x` 内存的同时获得 `1.69x` 加速。按可比性能点看，dynamic tiling 还能把内存分别降到静态方案的 `1/1.33` 和 `1/5.05`。batch=`1024` 时，静态 tiling 已接近饱和，而 dynamic tiling 仍能给 Mixtral 和 Qwen 分别带来 `1.86x` 与 `1.87x` 的加速；对 Qwen，它甚至能在提升 `1.12x` 性能的同时把 on-chip memory 压低 `12.5x`。这说明动态 tile 改变的是 Pareto frontier 本身。

configuration time-multiplexing 主要利用 MoE 的 expert sparsity。对 Qwen3-30B-A3B，它在静态 tiling 下把 compute utilization 提升 `2.64x`，性能开销低于 `1%`；在 dynamic tiling 下利用率仍可提升 `2.51x`，代价约 `5%`。按可比性能点看，它释放了 `62%` 的 on-chip compute 和 `46%` 的 memory 资源。dynamic parallelization 则作用在 attention 上：相对 static interleaved parallelization，当 KV 长度差异较小时可获得 `1.14x-1.26x` 加速，差异较大时可获得 `1.47x-1.57x`；相对 coarse-grained static parallelization，在 batch=`16` 时达到 `2.72x`，batch=`64` 时仍有 `1.43x`。

端到端上，完整的 Mixtral-8x7B 与 Qwen3-30B-A3B STeP 实现，相对 memory-matched static 实现分别达到 `1.27x` 和 `1.15x` 加速；其中 Qwen 还同时少用了 `69%` 的 on-chip memory 和 `54%` 的 compute resource。即便与 performance-matched static MoE 实现相比，动态版本依然分别有 `1.05x` 和 `1.14x` 的优势，主要因为 dynamic parallelization 继续改善了 attention。需要注意的是，这些结果仍然来自模拟器，因此更像“相对 schedule 优劣”的强证据，而不是已经完成上硅验证。

## 创新性与影响

相对于 _Hsu et al. (ASPLOS '23)_，STeP 把异步 streaming 从 sparse tensor algebra 推广到了 dense、dynamic tensor 程序，并补上了显式内存层次。相对于 _Rucker et al. (HPCA '24)_，它的关键增量不只是更多动态控制流，而是能保留数据复用的 dynamic tiled dataflow。相对于 _Ghosh et al. (PLDI '25)_，它则把 symbolic rate 与 scratchpad placement 提升为抽象层的一等语义。

因此，这篇论文最可能影响 accelerator / compiler 研究者，以及设计未来 ML accelerator 的系统团队。它的贡献更像新的编程模型与调度表面，而不是单点 kernel 优化。

## 局限性

最大的局限是结果还停留在抽象、符号前端和模拟器层面。论文虽然用代表性的 SwiGLU layer 把 STeP simulator 和 cycle-accurate HDL 模型做了对照，但并没有实现支持全部动态特性的完整硬件后端，也没有给出真实芯片上的端到端测量。stop token、动态路由、内存虚拟化和 mapping cache 的硬件支持都仍属于未来工作。

另一个边界是工作负载范围。论文聚焦于 LLM inference 的 MoE 与 attention，也没有实现从 PyTorch 到 STeP 的完整自动编译器。这些选择对首篇论文来说很合理，但也意味着它证明的是“抽象可行且调度有价值”，而不是“工具链已经成熟可部署”。

## 相关工作

- _Hsu et al. (ASPLOS '23)_ — SAM 首次把异步 streaming tensor abstraction 用于 sparse tensor algebra，而 STeP 进一步覆盖 dense dynamic tensor，并显式暴露内存放置。
- _Rucker et al. (HPCA '24)_ — Revet 支持 SDA 上的动态 dataflow thread，但其面向标量的动态原语很难表达动态 tiled reuse；STeP 正是补这个缺口。
- _Ghosh et al. (PLDI '25)_ — Ripple 同样面向 spatial dataflow architecture 的异步编程，但它把 memory hierarchy 留成隐式细节；STeP 则把它提升为调度层的一等接口。
- _Koeplinger et al. (PLDI '18)_ — Spatial 为 accelerator programming 提供了显式 memory hierarchy，而 STeP 贡献的是带符号 shape 与 routing 语义的 stream-first 动态抽象。

## 我的笔记

<!-- 留空；由人工补充 -->

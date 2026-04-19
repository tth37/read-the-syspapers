---
title: "SpaceFusion: Advanced Deep Learning Operator Fusion via Space-Mapping Graph"
oneline: "SpaceFusion 把算子间与算子内的复杂依赖统一成 SMG，再沿空间和时间两个方向切分融合空间，自动生成接近手写 kernel 的 GPU 融合调度。"
authors:
  - "Liang Zhu"
  - "Jianguo Yao"
  - "Haibing Guan"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696087"
tags:
  - ml-systems
  - compilers
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SpaceFusion 盯上的不是「要不要把两个算子 fuse」这种浅层问题，而是像 MHA 这类带深层 reduction 依赖的计算，怎么在不破坏正确性的前提下，真正排出一个吃到 GPU 存储层级优势的融合调度。它提出 Space-Mapping Graph（SMG）作为中间粒度抽象，再配上 spatial slicer 和 temporal slicer，把一个大的融合依赖空间切成可并行的 block 和可串行复用片上存储的 intra-block。论文在 V100、A100、H100 上报告，子图级最高加速 10.35x，端到端相对 HuggingFace PyTorch 最高 8.79x；对接入 FlashAttention 的手工优化栈，最高也还有 2.21x 提升。

## 问题背景

作者想解决的是深度学习编译器里一个很顽固的断层。图级抽象擅长把 element-wise 算子揉进去，却很少真正看见 GEMM、Softmax、LayerNorm 这类算子内部的依赖结构；Halide IR 或 polyhedral 这类低层表示虽然保留了细节，但搜索空间一下子膨胀到不适合拿来做 operator fusion 自动调度。

这个断层在 MHA 里尤其明显。论文给出的例子里，一个输出元素会依赖八个 tensor 中的 `(2LK + 4K + 2)` 个元素，依赖链一共六层，里面有 6 个 One-to-All 和 4 个 All-to-One。若只是把中间 tile 形状对齐后硬拼起来，要么 block 内局部性很差，要么 shared memory 根本放不下。于是问题不只是「哪些算子能 fuse」，而是怎样保留恰到好处的依赖信息，让系统既能改写依赖、又不会把调度搜索空间做炸。

## 核心洞察

SpaceFusion 的核心判断是，operator fusion 需要一个夹在 dataflow graph 和 loop nest 之间的抽象层。这个抽象既要能表达依赖方向、broadcast 和 reduction 结构，又不能细到把每个循环和 statement 都拖进来。SMG 的做法是把 data space 和 iteration space 都当成带维度信息的几何节点，再把边分成 One-to-One、One-to-All、All-to-One 三类，并显式记录方向。

一旦依赖被改写成这种几何关系，调度问题就能从笼统搜索改成「沿哪些维度切」。能安全切开的维度走 spatial slicing，生成彼此独立的 SMG blocks；更适合在 block 内串行推进的维度走 temporal slicing，把片上存储反复复用起来。论文真正补上的不是更暴力的 autotuning，而是一个能告诉系统「哪些依赖变换合法、哪些切法值得尝试」的表示方法。

## 设计

SpaceFusion 先给每个算子构建自己的 SMG，再通过中间空间的维度对齐把多个算子连成一个 fused SMG。这样做的结果是，GEMM、Softmax、GEMM 这样的链条不再是几次局部拼接，而是一个统一的优化空间。相较普通 DFG，SMG 多了三样关键东西：节点里带维度信息，iteration space 被显式建模，输入输出之间的复杂依赖被拆成带类型和方向的映射。

spatial slicer 负责找那些切完之后不会产生跨 block 数据流依赖的维度。它愿意切 input One-to-All，是因为 kernel 输入本来就在 global memory 里，所有 thread block 都能看见；但会避开那些一切就会让 block 彼此依赖的映射。这样切出来的结果是一组独立 SMG blocks，可以直接映射到 GPU thread blocks。

temporal slicer 处理的是另一面：把一个 SMG block 再拆成多个串行执行的 intra-block，好让 shared memory 和寄存器在阶段之间复用。独立 reduction 还算直接，麻烦在于 MHA 这种链式依赖的 reduction。论文给出的办法是 `Update then Aggregate`（UTA）：先做 broadcast postposition，把 reduction 之间最短的依赖路径显露出来，再自动生成诸如 `updateSum`、`updateOut` 这样的更新函数，让旧的 partial result 先被修正，再与当前切片的结果聚合。调度器会先尝试 spatial slicing，再尝试 temporal slicing，用 shared memory 和 register 预算裁掉不可能的 block size；如果整个 fused SMG 还是太大，就把它拆成更小的 sub-SMG 继续调度。intra-block code generation 则交给 Triton。

## 实验评估

实验平台覆盖三代 NVIDIA GPU：V100、A100、H100，软件栈是 CUDA 12.2，计算精度是 FP16 Tensor Core。子图实验说明这套方法不只会加速 attention。对 fused MLP，SpaceFusion 相对 cuBLASLt 最高 3.15x、平均 2.35x；对简化版 LSTM cell，相对 cuBLAS 最高 2.87x、平均 2.29x；对 LayerNorm，相对 PyTorch 平均 7.25x，对手写 Triton 版本最高还能快 4.03x；对 MHA，相对 PyTorch 最高 10.35x、平均 5.40x，性能已经能和 FlashAttention 2 打平一个量级。

端到端结果更说明问题，因为比较对象不只是 baseline 框架，还有手工优化库和其他 DL compiler。对 Bert、Albert、T5、ViT、Llama2-7B 推理，SpaceFusion 相对 HuggingFace PyTorch 最高 8.79x、平均 3.54x；相对 TensorRT 和 Kernl 的平均加速分别是 1.27x 和 1.34x；相对 BladeDISC 是 2.27x；在 Volta 上相对 NNFusion 也有 1.21x。机制层面的证据也对得上：论文报告最多可减少 83.0% 的 L1 cache miss、94.1% 的 L2 cache miss，以及 96.45% 的 device-memory 数据搬运。整体上看，评测覆盖了子图和整模型、也跨了三代 GPU，支撑力度不错；不过部分编译器 baseline 在某些架构上没有完整结果，最强对手也会随 workload 改变。

## 创新性与影响

这篇论文的新意不只是又发明了一种 schedule 搜索策略。Welder 的 tile-graph 能做细粒度的 inter-operator tile stitching，但 intra-operator dependency 还是不够显式；AStitch 主要针对 memory-intensive fusion；Chimera 更偏 compute-intensive fusion。SpaceFusion 则试图用同一套抽象把 CI 和 MI 两类融合一起兜住，并把依赖变换本身纳入 scheduler，而不是交给专家手写。

这让它对 DL compiler 很有现实意义。如果目标是扩大 fusion 覆盖面，而不是为每个 workload 单独造一个 handcrafted kernel，那么 SMG 这种中间层就很有价值。论文统计自己在实验工作负载里识别出 50 种不同 fusion pattern，而 NNFusion 是 30 种，BladeDISC 是 14 种。编译代价也没有失控，例如 MHA 的 auto-scheduling 只是毫秒级，`MHA(32,1024)` 的完整 tuning 需要 33.04 秒，整模型编译时间则是 Bert 68.4 秒、ViT 76.9 秒、T5 131.7 秒。

## 局限性

不过，SpaceFusion 的适用边界并不小。论文明确只讨论 globally ranged mappings，不处理 2D convolution fusion 这类 partially ranged 情况，所以它还谈不上通用算子融合抽象。实现和实验也都压在 NVIDIA GPU 与 FP16 上，换到别的加速器或别的精度设置，这套 slicing 逻辑能否同样成立，论文没有给出答案。

另外，这套方法很依赖代数化简空间。UTA 要先靠 broadcast postposition 把 reduction 关系摊开，但作者也承认，并不是所有 Dependent All-to-One 链都能在这些规则下被化简出来。再者，虽然分析阶段很轻，编译总时间的大头仍然在 tuning；对 Llama2 这类 attention head 多、权重张量大的模型，baseline 自身就已经有很强并行度和绕不过去的权重搬运，因此 SpaceFusion 的收益也会更有限。

## 相关工作

- _Shi et al. (OSDI '23)_ - Welder 用 tile-graph 在算子之间拼接中间 tile，但它没有把 intra-operator dependency 建模到足以支撑 SpaceFusion 那种 reduction 级依赖变换。
- _Zheng et al. (ASPLOS '22)_ - AStitch 扩展了 memory-intensive operator fusion 的搜索空间；SpaceFusion 则进一步覆盖 compute-intensive 算子以及 CI 和 MI 混合的融合子图。
- _Zheng et al. (HPCA '23)_ - Chimera 面向 compute-intensive operator fusion 做解析式优化，而 SpaceFusion 的目标是覆盖像 MHA 这样依赖结构更复杂的混合型 pipeline。
- _Dao et al. (NeurIPS '22)_ - FlashAttention 是为 MHA 手工设计的等价 fused kernel；SpaceFusion 则试图把这种接近手写优化的调度自动综合到更广泛的模式里。

## 我的笔记

<!-- 留空；由人工补充 -->

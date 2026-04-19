---
title: "SpInfer: Leveraging Low-Level Sparsity for Efficient Large Language Model Inference on GPUs"
oneline: "SpInfer 让 30%-70% 的非结构化 LLM 稀疏真正换来 GPU 速度与显存收益：索引改成贴合 Tensor Core 的位图，并在 shared memory 中低开销解码。"
authors:
  - "Ruibo Fan"
  - "Xiangrui Yu"
  - "Peijie Dong"
  - "Zeyu Li"
  - "Gu Gong"
  - "Qiang Wang"
  - "Wei Wang"
  - "Xiaowen Chu"
affiliations:
  - "The Hong Kong University of Science and Technology (Guangzhou), China"
  - "Harbin Institute of Technology, Shenzhen, China"
  - "The Hong Kong University of Science and Technology, Hong Kong SAR"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717481"
code_url: "https://github.com/HPMLL/SpInfer_EuroSys25.git"
tags:
  - llm-inference
  - gpu
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SpInfer 的核心判断是：30%-70% 的非结构化稀疏之所以在 GPU 上经常不划算，主要不是算子本身的问题，而是索引把压缩率和 compute intensity 一起拖垮了。它用贴合 Tensor Core 的位图格式加上 shared-memory 解码，让 pruned LLM 在 dense cuBLAS 之上真正拿到收益，端到端推理最高加速 1.58x，同时显著降低模型显存占用。

## 问题背景

论文先把靶子钉住。以 2 张 RTX4090 上的 OPT-13B 为例，模型权重占总内存的 87.6%，GEMM 又吃掉 61.6% 的执行时间，所以线性层显然是最该优化的部分。但 LLM 很难像一些较小模型那样被安全地剪到 70%-90% 稀疏；现有非结构化 pruning 方法通常在 50% 左右就开始明显碰到精度问题。

偏偏在这个稀疏区间，已有 sparse format 反而最尴尬。CSR 和 Flash-LLM 的 Tiled-CSL 仍要为大量位置元数据付费，导致 50% 以下时压缩率可能低于 1；在 GPU 上，这些索引还会继续消耗带宽，把 kernel 留在 memory-bound 区间里。于是 Flash-LLM、SparTA 一类系统在实践里经常只是和 dense cuBLAS 打平，甚至还会落后。

## 核心洞察

作者最重要的洞察是：低稀疏度场景里的优化单位不该是单个 non-zero，而应该是 Tensor Core fragment。只要 sparse format 从一开始就按 `mma` 执行单元来摆，索引成本就能按整块 tile 摊薄，compute intensity 也能一起上升。

所以 SpInfer 用 8x8 tile 上的 64-bit bitmap 取代逐元素显式坐标。位图只记录位置，非零值单独紧凑存放；再把 tile 排布和 Tensor Core fragment 对齐，就能在 shared memory 里靠几次 popcount 把寄存器内容恢复出来，而不必把 16-bit 或 32-bit 索引一路拖过 global memory、cache 和寄存器。

## 设计

SpInfer 把格式和 kernel 一起设计。TCA-BME 中，最小的 8x8 `BitmapTile` 用 64-bit 掩码加一段压紧的 FP16 非零值表示；4 个 `BitmapTile` 组成和 `mma.m16n8k16` 对齐的 16x16 `TCTile`；多个 `TCTile` 再组成由 thread block 处理的 `GroupTile`。矩阵只保留 `GTileOffset`、`Bitmap`、`Values` 三组数组，而 `TCTile` 内部采用列优先布局，让解码后的值能直接落到 Tensor Core 需要的寄存器排布上。这就是它在低稀疏度下仍能把压缩率维持在 1 以上的原因。

执行时，每轮先加载一个稀疏 `GroupTile` 和对应的 dense `XTile`，再把前者解到寄存器、把后者排成 Tensor Core 需要的形式，最后发出乘法。论文特别强调数据通路：`LDGSTS.128` 让稀疏权重和 dense 激活尽量直接从 global memory 进 shared memory，避免 Flash-LLM 那种要先绕过 register file 的路径。

最关键的实现点是 SMBD。warp 用 `__popcll` 和 masked popcount 在线算 packed non-zero 的 offset，然后分两阶段填满每个 32-bit 寄存器里的两个 FP16 槽位。再配上双缓冲异步流水线，以及分离的 `cp.async` group，SpInfer 可以把下一轮的加载、当前轮的 Tensor Core 计算和位图解码尽量重叠起来。

## 实验评估

kernel 级实验覆盖 OPT、Llama 2/3、Qwen2、Mixtral 的权重形状，平台包括 RTX4090 和 A6000，baseline 有 cuSPARSE、Sputnik、SparTA、Flash-LLM、dense cuBLAS 以及 SMaT。结果正好落在论文声称的目标区间。RTX4090 上，SpInfer 相对 cuBLAS 平均加速 1.79x，相对 Flash-LLM 平均加速 1.56x；A6000 上，相对 cuBLAS 平均加速 1.51x。更关键的是，在 40% 稀疏度时，它是唯一能稳定跑赢 cuBLAS 的方法，平均 1.46x，获胜比例 94.44%；50% 稀疏度时达到 1.66x，领先 96.30% 的测试矩阵；70% 时则达到 1.90x，并在全部测试中取胜。它在 50% 稀疏度下也比 SMaT 快 2.12x。

端到端部分使用 Wanda 剪到 60% 稀疏的 OPT-13B/30B/66B，对比 Flash-LLM、FasterTransformer 和 DeepSpeed。RTX4090 上，平均加速分别为 1.35x、1.42x、1.49x；A6000 上分别为 1.29x、1.36x、1.55x。最佳案例是 1 张 GPU、batch size 32 时，相对 Flash-LLM 达到 1.58x，吞吐 1817.02 tokens/s，对手为 1183.58 tokens/s。显存方面，OPT-13B 在 batch size 16、sequence length 256 时只占 14.4 GB，而 dense baseline 需要 27.4 GB，下降 47.5%。这些节省还让 SpInfer 能跑通一些 Flash-LLM 会 OOM 的配置。整体证据是有说服力的，不过端到端范围仍主要限于 OPT 系列，精度也基本沿用 pruning pipeline 的保证。

## 创新性与影响

SpInfer 的新意，不是重新发明 unstructured pruning，也不只是又做了一个更快的 sparse kernel，而是把格式和 Tensor Core kernel 一起按 30%-70% 这段低到中等稀疏度区间重新设计。Flash-LLM 仍要承担较重的逐值索引成本，SparTA 依赖结构化加残余混合方案，而极高稀疏度 kernel 优化的又是另一种工作区间。SpInfer 证明了低稀疏度的非结构化 pruning 可以成为真实可部署的系统优化，而不只是纸面上的 FLOP 节省。

这对 sparse-LLM 研究者和 inference engine 工程实现者都重要，因为它能和 pruning、quantization 以及 serving 层优化继续叠加。论文的价值更像是一套新机制加扎实系统落地，而不只是性能测量。

## 局限性

作者对短板写得很明白。SpInfer 最适合 decode 这类仍偏 memory-bound 的场景；一旦 batch size 和 sequence length 都很大，prefill 会更接近 compute-bound，此时它相对 dense cuBLAS 最多会慢 11.8%。同时，它只支持静态 weight sparsity，不支持 dynamic activation sparsity。

评估范围也比 kernel 结果本身更窄一些：端到端只覆盖 OPT，跨硬件可移植性仍停留在讨论层面，而且当稀疏度超过 90% 时，bitmap 会因为表示零过多而失去优势，CSR 风格或其他极高稀疏度 kernel 会重新变得更合适。

## 相关工作

- _Xia et al. (VLDB '23)_ - Flash-LLM 同样研究 Tensor Core 上的 sparse LLM inference，但 SpInfer 认为它的 Tiled-CSL 和经由寄存器展开的执行路径，在 50% 左右稀疏度下仍然承担了过高的索引带宽成本。
- _Zheng et al. (OSDI '22)_ - SparTA 通过把矩阵拆成 2:4 结构化部分和剩余稀疏部分来利用硬件，而 SpInfer 保持完全非结构化，并直接围绕索引开销做格式设计。
- _Gale et al. (SC '20)_ - Sputnik 是深度学习 sparse GPU kernel 的重要基线，但它主要立足 CUDA cores；SpInfer 则把优化目标转到 Tensor Core fragment 对齐和 LLM 低稀疏度矩阵上。
- _Fan et al. (ASPLOS '24)_ - DTC-SpMM 展示了通用 sparse matrix multiplication 如何使用 Tensor Cores，SpInfer 则把这条思路专门推进到 pruned LLM inference 中偏 decode、低到中等稀疏度的工作区间。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "Mirage: A Multi-Level Superoptimizer for Tensor Programs"
oneline: "Mirage 在 GPU kernel、block、thread 三层联合搜索 tensor program，再用剪枝与概率验证自动合成更快的自定义 kernels。"
authors:
  - "Mengdi Wu"
  - "Xinhao Cheng"
  - "Shengyu Liu"
  - "Chunan Shi"
  - "Jianan Ji"
  - "Man Kit Ao"
  - "Praveen Velliengiri"
  - "Xupeng Miao"
  - "Oded Padon"
  - "Zhihao Jia"
affiliations:
  - "Carnegie Mellon University"
  - "Peking University"
  - "Pennsylvania State University"
  - "Purdue University"
  - "Weizmann Institute of Science"
conference: osdi-2025
code_url: "https://github.com/mirage-project/mirage"
tags:
  - compilers
  - gpu
  - ml-systems
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Mirage 是一个面向 tensor program 的 superoptimizer，它搜索的不是固定 kernel 库上的局部改写，而是覆盖 GPU kernel、thread block 和 thread 三层的分层空间。借助 `µGraphs`、abstract expression 剪枝和概率式等价验证，它能够自动合成新的 fused kernels，并在强基线之上拿到最高 3.3x 的加速。

## 问题背景

这篇论文抓住的是现有 ML compiler 栈里的一个结构性缺口。Halide、TVM、Ansor、Triton 这类 schedule optimizer 擅长搜索“固定算法该怎么执行”，而 TASO、PET 这类 algebraic optimizer 擅长改写 computation graph，但仍然依赖专家提前写好的 kernels。现代 GPU 的关键收益往往要求三件事一起变：代数结构、kernel 边界、block/thread 映射。

FlashAttention 就是典型例子。它的收益来自新的 kernel 结构，而不只是给旧算子换一个更好的 schedule。现有自动化工具发现不了这种联合变换空间，所以工程师仍然要为常见 DNN 和 LLM 算子手写大量 Triton 或 CUDA 代码。

## 核心洞察

Mirage 的核心主张是，tensor program 应该围绕一个统一的分层对象来优化，而不是把 kernel-level rewrite、schedule search 和 kernel fusion 分成几套流程。`µGraph` 把同一份计算同时表示在 kernel、block 和 thread 三个层次上，于是 algebraic rewrite、schedule choice 和 custom-kernel synthesis 都变成了对同一个图的变换。

这个想法之所以可行，是因为 Mirage 同时解决了“可搜”和“可证对”两个问题。它用 abstract expression 提前剪掉不可能通向目标计算的前缀，用 `LAX` 片段上的有限域随机测试来获得带理论支撑的等价性保证。

## 设计

在最高层，tensor program 被表示成 kernel graph，tensor 放在 device memory 中。节点既可以是 library kernels，也可以是继续向下展开的 graph-defined kernels。block graph 位于 shared memory 层，使用 `imap`、`omap`、`fmap`、loop dimensions 和 accumulators 来描述切分、拼接和跨迭代归约；thread graph 位于 registers 层，负责 fuse 短小的 elementwise operator 序列。

RMSNorm 加 MatMul 的案例最能体现这种表示的价值。Mirage 自动发现了一个 custom kernel：重排 RMSNorm 中的除法与 MatMul，重叠 RMS 和 MatMul 的累计，再把最后的 elementwise 处理留在 registers 中。论文报告这个自动生成的 `µGraph` 在 A100 上比现有手写 kernels 快 1.5x，在 H100 上快 1.9x。

Mirage 在 kernel 和 block 层做有界穷举，在 thread 层改用基于规则的构造。最关键的剪枝机制是 abstract expression：它把每条边映射成由 `sum`、`mul`、`div`、`exp`、`sqrt` 等函数组成的抽象表达式，再让 Z3 判断当前前缀是否仍可能成为目标计算的 subexpression。这里故意不加入 cancellation rules，否则剪枝强度会大幅下降。

通过剪枝的候选再进入概率式 verifier。对于 `LAX` 程序，Mirage 在两个 finite fields 上比较参考程序和候选程序，其中一个用于 exponentiation 内部，另一个用于外部算术。等价性确认后，它还会继续做性能优化：用 ILP 选 tensor layouts，按 graph depth 排 operator 以减少 `__syncthreads()`，再搜索 memory plans 提高 buffer 复用率。

## 实验评估

实现层面，Mirage 大约用了 30K 行 C++、CUDA 和 Python，构建在 cuDNN、cuBLAS、CUTLASS、PTX 和 Z3 之上。实验在 A100 和 H100 上进行，对比 TASO/PET、开启 `torch.compile` 和 FlashAttention 的 PyTorch、TensorRT/TensorRT-LLM、FlashAttention/FlashDecoding，以及 Triton。总体 headline result 是：相对最佳基线最高 3.3x。

更重要的是各个 case study。对 GQA，Mirage 会搜索更好的 grid dimensions 和 tensor-dimension 并行方式，最高快 2.2x。对 QKNorm，它把 normalization 融进 attention，最高提升 1.4x。对 LoRA，它通过 `(W || B) x (X || (A x X))` 这类 algebraic rewrite 把多个小 MatMul 和 Add 变成一个 fused kernel，提升 1.1-2.4x。对 GatedMLP，它在一个 block graph 里并行执行两个 MatMul，再 fuse SiLU 和乘法路径，达到 1.5-3.3x。主要例外是 nTrans：TensorRT 仍然更快，因为 Mirage 现在的 graph-defined kernels 总要走 shared memory staging，这对轻量 kernel 太贵。

论文也展示了系统层面的意义。把 Mirage 生成的 kernels 接入 PyTorch 后，Chameleon-7B、LLaMA-3-8B、GPT-3-7B-LoRA 和 nGPT-1B 的端到端推理延迟最高可改善 1.9x，不过 GPT-3-7B-LoRA 有一个点略差于基线。搜索是 offline 的，完整运行最多约 4 小时；而在 RMSNorm 这个需要 11-operator block graph 的例子里，abstract expression 剪枝把搜索时间从超过 10 小时降到了 28 秒。

## 创新性与影响

相对于 _Jia et al. (SOSP '19)_ 和 _Wang et al. (OSDI '21)_，Mirage 把 superoptimization 从 kernel-level graph rewrite 扩展到了真正的分层搜索空间。相对于 Triton 这类 schedule search 以及 _Shi et al. (OSDI '23)_，它把 scheduling 明确放进一个更大的层次化优化问题里。它的贡献因此不是“更强的 benchmark”，而是一种新的自动化 kernel 发现机制。

这对 tensor compiler 和 LLM runtime 的影响会比较直接。Mirage 传递的结论是：下一代系统不该只是继续堆积手写 fused kernels，而应该从分层 IR 出发，在可验证的搜索空间里自动合成这些 kernels。

## 局限性

Mirage 最强的 verifier 只覆盖 `LAX` 片段，而搜索过程中使用的实现也弱于理论最强版本：它采用较小的 primes（`p=227`、`q=113`）和单次随机测试，更强的最终验证仍是未来工作。与此同时，abstract-expression axioms 故意不包含 cancellation rules，所以一部分真实等价的 `µGraphs` 不会被探索到。

搜索成本依旧可能高达数小时；支持新 operator 还需要补 floating-point、modular-arithmetic 和抽象公理三套实现。最后，shared-memory-first 的 code generation 并不总占优，nTrans 已经说明轻量 kernel 会被这套机制的搬运与 bookkeeping 开销拖慢。

## 相关工作

- _Jia et al. (SOSP '19)_ - TASO 在 kernel level 做 algebraic substitution，而 Mirage 在 kernel、block、thread 三层联合搜索，并且能够合成新的 custom kernels。
- _Wang et al. (OSDI '21)_ - PET 把 partially equivalent transformation 和自动修正结合起来，但依然停留在 kernel level，没有进入分层 GPU 表示。
- _Tillet et al. (MAPL '19)_ - Triton 是非常强的 schedule optimizer，但它优化的是用户给定的 kernel；Mirage 还会搜索 algebraic structure 和 kernel boundaries。
- _Shi et al. (OSDI '23)_ - Welder 使用 multi-level representation 改进 scheduling 和 memory access，而 Mirage 把这个思路进一步推进到了 superoptimization 与 correctness verification。

## 我的笔记

<!-- 留空；由人工补充 -->

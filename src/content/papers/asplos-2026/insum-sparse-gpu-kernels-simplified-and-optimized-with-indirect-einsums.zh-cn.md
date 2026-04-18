---
title: "Insum: Sparse GPU Kernels Simplified and Optimized with Indirect Einsums"
oneline: "Insum 把稀疏 GPU kernel 改写成固定长度格式上的 indirect einsum，让 PyTorch/Triton 生成融合的 Tensor Core 代码。"
authors:
  - "Jaeyeon Won"
  - "Willow Ahrens"
  - "Saman Amarasinghe"
  - "Joel S. Emer"
affiliations:
  - "Massachusetts Institute of Technology, CSAIL, Cambridge, MA, USA"
  - "Georgia Institute of Technology, Atlanta, GA, USA"
  - "NVIDIA Architecture Research Group, Westford, MA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790176"
code_url: "https://github.com/nullplay/IndirectEinsum"
tags:
  - compilers
  - gpu
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Insum 把稀疏 GPU kernel 改写成固定长度稀疏格式上的 indirect einsum，让后端看到的是 gather、稠密张量代数和 scatter，而不是专门的稀疏控制流。作者随后扩展 TorchInductor，把这条流水线融合并映射到 Tensor Core。论文在四类稀疏 ML kernel 上报告了相对手写基线 `1.14x-3.81x` 的加速，同时把实现缩成一条表达式。

## 问题背景

论文针对的是一个长期存在的错位：稀疏编程抽象和 GPU 喜欢执行的程序形态并不一致。TACO 这一类 sparse tensor compiler 往往把格式无关的 Einsum 和存储格式分开，再生成稀疏专用控制流去处理交并集或可变长行遍历。这更像是 CPU 友好的 sparse-sparse 模型，而很多 ML 场景里的 GPU kernel 实际上是 sparse-dense：关键成本在“不规则 gather 之后的稠密计算”。

这也是为什么高性能 sparse GPU kernel 仍然高度依赖手写代码。论文引用了 Sputnik 近两千行、TorchSparse 四千多行的实现规模。像 CSR 这样的格式还会暴露数据相关的循环边界，与 dense compiler 偏好的固定循环巢冲突。真正的问题因此是：怎样在保留稀疏语义的前提下，把 kernel 改写成足够规整、可以被稠密 GPU 编译器融合和 tensorize 的形式。

## 核心洞察

论文的核心主张是：只要把稀疏格式元数据通过 indirect indexing 直接编码进 Einsum，稀疏 GPU kernel 就会突然变得“对编译器友好”。换句话说，不再把格式当成编译后期才展开的外部描述，而是把原始稀疏计算重写成 format-conscious 的 indirect Einsum；它的操作数仍然是稠密张量，只是其中一部分存非零值，另一部分存坐标元数据。

这样一来，后端要优化的对象就变了。以 COO SpMM 为例，程序变成：从 `B` 中 gather，用 `AV` 做稠密乘加，再 scatter 回 `C`。如果格式进一步使用固定长度分组，而不是每行可变长遍历，整个 kernel 就会落进现有 dense GPU compiler 已经擅长处理的规则循环巢里。论文真正有力的结论因此是：选对表示以后，编译器可以重用完整的稠密优化栈，而不必再单独造一套 sparse code generator。

## 设计

设计由两部分组成：固定长度稀疏格式，以及把这些 indirect einsum 经由 PyTorch 降到 Triton 的编译路径。

格式侧从 COO 出发，但要解决 COO 的两个问题：重复坐标太多、scatter 太频繁。GroupCOO 沿某个维度把非零项分组，共享坐标只存一次，再用 padding 把组内循环变成固定长度。BlockGroupCOO 则在此基础上加入 dense block，使内部核心计算变成适合 Tensor Core 的 block matmul。作者选择组大小时，不是最小化格式体积，而是最小化 indirect access 次数，因为实验显示运行时间与 gather/scatter 数更相关。

编译器侧，Insum 把字符串形式的 indirect Einsum 变成 PyTorch FX graph，逻辑上分三步：gather、执行 dense Einsum、scatter 回输出。难点在于 TorchInductor 默认把 matmul 当成特殊模板 kernel，这会阻断与 gather、scatter 的融合。为此作者加入 `ops.dot` IR 节点，直接 lower 到 Triton 的 `tl.dot`，再引入 “Lazy Broadcasting”，把广播延迟到变量真正被消费时再做。这样可以去掉 `tl.dot` 周围多余的 reshape / transpose，并最终生成一个融合的 gather-matmul-scatter Triton kernel。

## 实验评估

实验覆盖四类工作负载：structured block-sparse SpMM、unstructured SpMM、point-cloud sparse convolution，以及 equivariant tensor product。实现大约是 500 行 Insum 代码加 1600 行 TorchInductor 修改。Table 1 的 headline 很集中：相对 TorchBSR 提升 `1.95x`，相对 Sputnik 提升 `1.20x`，相对 TorchSparse 提升 `1.14x`，相对 e3nn 提升 `3.81x`；代码量则缩减 `202x-4491x`。

其中 structured SpMM 最能说明问题。相对 dense matmul，稀疏开始划算的交叉点从约 `40%` sparsity 前移到 `25%`，而 grouped COO 风格格式还能避免 BCSR 在 hypersparse 场景下的 row-pointer 开销。unstructured SpMM 的结果更克制：论文并不声称每个矩阵都赢，但在几何平均上，Insum 在 FP32 下约比 cuSPARSE 快 `1.2x`，在 FP16 下约快 `1.18x`。

另外两组实验说明这不是只适用于 SpMM 的技巧。Insum 在 point-cloud convolution 上超过 TorchSparse 的两套算法，并且因为 Triton 能重新 autotune，在 H100 上优势更明显。对 equivariant tensor product，它在所有报告设置里至少比 e3nn 快 `2x`，相对 cuequivariance 最多快 `8.3x`。

消融实验也支撑了机制本身。仅仅做 grouping，就能相对未融合的 COO 带来约 `8x` 提升；加上 block 后可启用 Tensor Core；native matmul 和 lazy broadcasting 又能相对默认 PyTorch codegen 再带来 `2.6x`。主要代价是编译时间：point-cloud 例子需要 `9.9s` 编译和 `4.9s` autotune。

## 创新性与影响

相对 _Kjolstad et al. (OOPSLA '17)_，Insum 的新意不在于再提一个格式抽象，而在于把稀疏元数据重新编码回 indirect tensor program。相对 _Ye et al. (ASPLOS '23)_，它同样复用稠密编译基础设施，但更强调自动化：用户只写一条 indirect einsum，而不是维护大段手工 schedule。相对 _Won et al. (MLSys '23)_，它则把 sparse convolution 的编译思路推广到了一小类 sparse-dense GPU kernel。

## 局限性

论文的适用范围明显窄于“所有稀疏张量程序”。它最适合 sparse-dense kernel；像 CSR 这种可变长格式不能直接落进 fixed-length indirect-Einsum 模型，往往要先转成 grouped 或 padded 表示。若组大小选得不好，padding 浪费仍然存在。

此外，这个方案依赖对 TorchInductor 的特定改造，包括原生 `tl.dot` lowering 和 lazy broadcasting，因此移植到别的编译栈并不是零成本。实验主体也仍然集中在 NVIDIA GPU 上的 ML 风格 kernel。

## 相关工作

- _Kjolstad et al. (OOPSLA '17)_ — TACO 把计算与稀疏存储分离，而 Insum 把元数据推入 indirect einsum。
- _Ye et al. (ASPLOS '23)_ — SparseTIR 也复用稠密编译基础设施，但更依赖手工 schedule。
- _Won et al. (MLSys '23)_ — Unified Convolution Framework 面向 sparse convolution；Insum 进一步覆盖 SpMM 与 tensor product。
- _Ahrens et al. (OOPSLA '25)_ — Finch 扩展 sparse tensor programming，而 Insum 专注 Tensor-Core-friendly 的稀疏 GPU kernel。

## 我的笔记

<!-- 留空；由人工补充 -->

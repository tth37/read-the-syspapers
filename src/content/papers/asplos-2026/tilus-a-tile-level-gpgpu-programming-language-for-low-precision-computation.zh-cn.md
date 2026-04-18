---
title: "Tilus: A Tile-Level GPGPU Programming Language for Low-Precision Computation"
oneline: "Tilus 用 tile 级布局代数、显式层次内存控制和零开销寄存器重解释，把 1-8 bit 低精度 GPU kernel 做成既可编程又高效的实现。"
authors:
  - "Yaoyao Ding"
  - "Bohan Hou"
  - "Xiao Zhang"
  - "Allan Lin"
  - "Tianqi Chen"
  - "Cody Hao Yu"
  - "Yida Wang"
  - "Gennady Pekhimenko"
affiliations:
  - "University of Toronto, Toronto, ON, Canada"
  - "Carnegie Mellon University, Pittsburgh, PA, USA"
  - "University of Waterloo, Waterloo, ON, Canada"
  - "Independent Researcher, Santa Clara, CA, USA"
  - "Amazon Web Services, Santa Clara, CA, USA"
  - "NVIDIA"
  - "Vector Institute"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3760250.3762219"
code_url: "https://github.com/NVIDIA/tilus"
tags:
  - gpu
  - compilers
  - pl-systems
  - llm-inference
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Tilus 是一门面向低精度 GPU kernel 的 tile 级语言与编译栈，针对的正是 LLM 推理里那类“4 bit 精度不够、8 bit 成本太高”的量化场景。它最关键的一步，是把 layout 与内存放置显式化到足够细的程度，使 packed bytes 可以先正常加载、再在寄存器里零开销重解释，最后才转换成计算所需的数据类型。

## 问题背景

矩阵乘法主导了 LLM serving 的带宽和算力成本，4 bit 量化虽然收益很大，但作者指出，当前最强的 4 bit 方法仍会带来不可忽略的精度损失；5-7 bit 往往能缓解这个问题，却没有高效 GPU kernel 可用。

现有方案各自卡在不同地方。QuantLLM、Marlin 这类手写 kernel 很快，但覆盖面窄，每换一种 bit width、格式或 GPU 架构都要重新投入专家工程。Triton 可编程性更强，但没有原生 sub-byte 支持，而且把内存层次抽象得过深，用户最后还是要手写 unpack 并承受昂贵的 layout conversion。Ladder 确实往低精度推进了一步，但它的 packing 模型更适合 power-of-two bit width，也不容易表达 software pipelining 等关键优化。缺失的其实是一种把任意 bit 宽低精度当作一等编译目标的 GPU 编程模型。

## 核心洞察

这篇论文的核心观点是：只要编译器能在线程块粒度显式推理 tile、layout 和 memory scope，任意 bit 宽低精度 kernel 就会从一堆难维护的特殊情况，变成一个可系统处理的问题。Tilus 把 kernel 视作运行在抽象 GPGPU 虚拟机上的程序，基本对象不是线程内标量，而是寄存器、shared memory、global memory 里的张量。

随后，Tilus 给 layout 一个小而够用的代数体系。它用 `local` 与 `spatial` 原语，再加上 Kronecker product 组合，来判断两个寄存器张量虽然元素类型和逻辑形状不同，但在底层 bit 分布上是否兼容。这样 packed bytes 就可以被零开销重解释成低精度 tensor tile，而不必搬运数据。论文最重要的洞察因此是：任意 bit 宽支持首先是 layout 问题，而不是无穷无尽的 unpack 特判。

## 设计

Tilus 的设计有三个核心部分。第一部分是 algebraic layout system。论文把分布式寄存器布局形式化为一个映射：输入是线程索引与线程内局部索引，输出是逻辑张量坐标。`local(...)` 表示数据留在单线程内部，`spatial(...)` 表示数据跨线程分布，复杂布局通过组合得到。

第二部分是编程模型。Tilus 在作者称为 `SIMB` 的线程块粒度上工作，而不是要求用户直接写 SIMT 风格代码。程序由 block-level 张量指令构成，例如 `LoadGlobal`、`LoadShared`、`StoreGlobal`、`CopyAsync`、`View`、`Cast` 和 `Dot`。因为低精度 kernel 往往首先受限于数据搬运，这种直接暴露 registers、shared memory 和 global memory 的方式，使 pipelining 与 placement 成为显式可控的优化对象。

第三部分是低精度数据通路。小于 8 bit 的值会被紧凑地装进 `uint8` 容器，但高性能路径尽量避免重复位操作。执行前，权重会先在 global memory 中重排成硬件友好的 packed layout；执行时，kernel 读入这些 bytes，再用 `View` 把它们零开销重解释成低精度 tensor tile，最后 cast 成 `float16` 等标准类型送入 tensor core。论文里的 `int6` 例子最清楚：每个线程持有 3 个 `uint8`，因为总共都是 24 bit，所以可以直接重解释成 4 个 `int6`。

## 实验评估

实验聚焦在 LLM 推理里的量化矩阵乘法。作者测试了 Gemma-2-9B、Qwen2.5-32B 和 Llama-3.3-70B-Instruct，主要硬件是 NVIDIA L40S，并额外覆盖 A100 与 H100。基线包括 cuBLAS、Triton、Ladder、QuantLLM、Marlin，以及集成到 vLLM 的端到端对比。

在算子层面，Tilus 覆盖了论文中最完整的精度范围：`uint1-uint8`、`int2-int8`、`float3-float8`。摘要报告，在这些系统各自支持的 kernel 上，Tilus 相比 Triton、Ladder、QuantLLM、Marlin 分别达到 `1.75x`、`2.61x`、`1.29x`、`1.03x` 的性能提升。最有说服力的一点，是整套低精度类型谱系都来自同一个参数化 Tilus 模板，而不是一堆格式特化的独立 kernel。

端到端结果也支持相同结论。Tilus 集成进 vLLM 后，在三种模型的 decode 与 prefill 阶段都优于 Ladder，尤其在更大的 decode batch 下更明显。某些 baseline 失败本身也很能说明问题：大模型在 L40S 上会让 vLLM 触发 OOM，而 Ladder 在 H100 上有实验直接遇到 illegal instruction。这不能证明 Tilus 在所有环境都稳健，但确实加强了它对近代 NVIDIA 架构适应性更好的说法。

## 创新性与影响

相对 _Tillet et al. (MAPL '19)_，Tilus 的新意不是再造一门 tile 语言，而是把显式低精度 layout control 放到语言中心。相对 _Wang et al. (OSDI '24)_，它不是把低精度当作 packed type 上的调度扩展，而是把 reinterpretation 与 layout algebra 作为主设计原则。相对 _Hagedorn et al. (ASPLOS '23)_ 和 _Ding et al. (ASPLOS '23)_，它比通用 tensor compiler 更窄，但在任意 bit 宽 kernel 所需的编译器-硬件接口上更深入。

## 局限性

最大的局限是覆盖范围。虽然语言设计本身较一般化，实验几乎全部集中在 LLM 推理里的量化矩阵乘法上；卷积、attention kernel 或非 LLM 工作负载都没有被充分展示。实现也明显偏向 NVIDIA，高性能路径依赖 CUDA 专用指令、`nvcc` 和近代 NVIDIA 的内存搬运原语。再加上离线权重布局转换与不低的调参/编译成本，Tilus 目前更像是一个很强的 NVIDIA 低精度 kernel 方案，而不是已经跨平台成熟的通用系统。

## 相关工作

- _Tillet et al. (MAPL '19)_ — Triton 奠定了 tile 级 GPU 编程的基础，而 Tilus 在此之上加入了 Triton 缺少的显式布局代数与任意 bit 宽原生支持。
- _Wang et al. (OSDI '24)_ — Ladder 通过 tensor transformation 支持低精度深度学习，而 Tilus 暴露出更底层的线程块编程模型，更自然地表达 pipelining 与非 power-of-two bit width。
- _Hagedorn et al. (ASPLOS '23)_ — Graphene 提供了面向 GPU 优化张量计算的 IR，Tilus 则更聚焦 tile 元素如何跨线程分布，以及如何在不同数据类型之间重解释。
- _Ding et al. (ASPLOS '23)_ — Hidet 提供了底层编译后端与 task-mapping 风格的基础，而 Tilus 在这一类 GPU 编译思路上进一步叠加了专门面向低精度的语言与 layout system。

## 我的笔记

<!-- empty; left for the human reader -->

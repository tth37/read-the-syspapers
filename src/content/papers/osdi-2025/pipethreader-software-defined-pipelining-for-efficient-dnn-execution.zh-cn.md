---
title: "PipeThreader: Software-Defined Pipelining for Efficient DNN Execution"
oneline: "PipeThreader 把 fused DNN kernel 表示成 sTask-graph，在软件层联合调度 TMA、TensorCore 和 CUDA core 的流水线，自动逼近或超过手写 kernel。"
authors:
  - "Yu Cheng"
  - "Lei Wang"
  - "Yining Shi"
  - "Yuqing Xia"
  - "Lingxiao Ma"
  - "Jilong Xue"
  - "Yang Wang"
  - "Zhiwen Mo"
  - "Feiyang Chen"
  - "Fan Yang"
  - "Mao Yang"
  - "Zhi Yang"
affiliations:
  - "School of Computer Science, Peking University"
  - "Microsoft Research"
  - "Imperial College London"
  - "Shanghai Jiao Tong University"
conference: osdi-2025
code_url: "https://github.com/tile-ai/tilelang"
tags:
  - ml-systems
  - gpu
  - compilers
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

PipeThreader 把 fused DNN kernel 的流水线调度从 GPU 内部隐式的硬件行为，搬到编译器显式控制的软件层。它把 kernel 表示成由 specialized tile task 组成的 sTask-graph，再把这些任务映射到 TMA、TensorCore 和 CUDA core 上，并联合搜索 tiling 与执行顺序。因此，它既能自动恢复类似 FlashAttention 的流水线，也能在若干 Mamba2 与 attention 工作负载上超过现有编译器或手写实现。

## 问题背景

现代 GPU 已经不再是“很多等价核心的集合”。在一颗 H100 的 SM 里，TensorCore、CUDA core 和 TMA engine 的职责、异步能力与瓶颈都不同。与此同时，高性能 DNN kernel 越来越依赖 operator fusion，因此性能不再只是选一个好 tile size，而是取决于 load、matrix multiply、reduction、rescale 与数据搬运能否正确重叠。现有 DNN compiler 大多只暴露 homogeneous execution unit 和 spatial tiling，于是它们能表达跨 SM 的 data parallelism，却难以表达单个 SM 内部的细粒度 pipeline order。结果就是现代硬件上的利用率不足，而且越来越依赖 FlashAttention 这类庞大、强硬件绑定的手写 kernel。

## 核心洞察

论文的核心判断是：tile-level 的 GPU 执行已经足够可预测，pipeline 不应该继续交给隐式硬件启发式去“碰运气”，而应当由编译器在软件层显式调度。PipeThreader 为此引入两个抽象。sTask-graph 把一个 fused operator 拆成细粒度任务，例如 tile 上的 `load`、`mma`、`softmax`、`exp` 或 `rescale`；specialized execution unit，简称 sEU，则刻画 SM 内部异构的执行引擎。只要编译器同时看见任务依赖与硬件异构性，它就可以把 reduction tiling 和 pipeline order 放在同一个优化问题里，而不是分别处理。

## 设计

PipeThreader 从 DNN operator graph 或一个很小的 sTask IR 出发，把计算转换成 sTask-graph。它最关键的选择是：除了像以往 tile compiler 那样切 spatial dimension，还主动切 reduction dimension。额外切出来的 partial task 会暴露相邻 loop iteration 之间可以重叠的工作。以 Mamba2 的 ChunkScan 为例，编译器会把一个 fused loop body 拆成 `load_cb`、`load_dA`、`load_dt`、`exp`、`load_x` 和 `mma` 等 sTask，然后探索这些任务怎样交错执行。

硬件侧的建模同样是显式的。PipeThreader 把每个类似 SM 的单元抽象成 EU，把其中异构的执行引擎抽象成 sEU。在 H100 上，关键 sEU 分别是负责 bulk copy 的 TMA、负责 matrix multiply-accumulate 的 TensorCore，以及负责标量或 reduction 风格工作的 CUDA core。一个候选调度会被编码成 sProgram，本质上是“按 sEU 分组的任务顺序表”，再加上一组保持依赖关系的 barrier task。

调度机制由三个 primitive 组成。`Append` 把某个 sTask 放到指定 sEU 上；`Wait` 在任务前插入同步；`Propagate` 则从选定的 output tile 反向推导整张图里合法的 tile shape。有了这些基础之后，PipeThreader 采用两层调度。inter-EU 调度以 SPMD 的方式把工作切到多个 homogeneous EU 上；intra-EU 调度则借助 profiler，在 heterogeneous sEU 上对 ready task 做贪心排序。这个过程会优先选择能尽快解锁后续工作的异步任务，检查 local memory 是否足够，并在“大 tile 带来更高 data reuse”与“更深 pipeline 带来更高 overlap”之间做权衡。论文里的 Mamba2 例子很能说明这点：解耦优化的变体选了更大的 tile，运行时间是 12.150 ms；PipeThreader 的联合优化则选了更小的 64x64 tile，使流水线更顺畅，把延迟降到 6.981 ms。

实现层面，设备细节也大多由系统自动补齐。它会做 layout inference，让相邻 sTask 的内存布局与 thread binding 保持兼容；在 H100 上使用 `cp.async.bulk` 与 `wgmma.mma_async`；并采用 warp specialization，让 producer warp 负责 TMA load，consumer warp 负责计算阶段。作者特别强调，这能显著降低手写成本：他们的 FlashAttention kernel 只需要 68 行 Python，而 FlashAttention-3 的手写 CUDA kernel 需要 840 行。

## 实验评估

实验覆盖了 NVIDIA H100 与 AMD MI300X 上的 operator microbenchmark 和端到端推理。整体规律很清楚：pipeline 越深，PipeThreader 的收益越明显。在 H100 上，标准 MatMul 相对 PyTorch、Triton 与 Ladder 分别提升 1.24x、1.13x 与 2.07x，这些结果不错，但还不是最亮眼的部分。更大的优势出现在多阶段 kernel 上。low-bit MatMul 相对 PyTorch+bitsandbytes 提升 3.92x、相对 Ladder 提升 2.48x；FlashAttention 平均比 Triton 快 1.36x，比 FlashAttention-3 快 1.07x；对 Mamba2，ChunkScan 与 ChunkState 相对 Triton 平均加速 1.71x 和 1.98x，而且 Triton 在部分长序列配置上直接失败。

端到端结果也很强。对 H100 上的 FP16 LLaMA3-8B 和 LLaMA3-70B，PipeThreader 平均比 Ladder 快 2.17x、比 ONNXRuntime 快 2.45x，同时也分别比 PyTorch-Inductor、TensorRT 和 vLLM 快 1.79x、1.28x 和 1.10x。对 Mamba2-1.3B，它相对 PyTorch-Inductor 快 1.92x，相对 Ladder 快 45.93x，主要原因是后者对 fused linear attention 的支持明显不足。可移植性结果也值得注意：在 MI300X 上，PipeThreader 在 operator 级别相对 Triton 仍有 1.16x 到 5.42x 的提升，在端到端上也继续领先于 PyTorch-Inductor、ONNXRuntime 与 Ladder。这说明论文的中心论点并不只适用于某一条 NVIDIA 特例，而是对跨厂商 GPU 都有意义。

不过，这里的证据也有边界。大模型 LLM 的端到端结果由于显存限制，只能用 single decoder layer 近似整模型推理；而 Mamba2 上一些最大的提升，部分来自 baseline 直接失败，而不是两个同样成熟的实现之间进行纯粹的一对一比较。

## 创新性与影响

相较于 _Ma et al. (OSDI '20)_ 和 _Zhu et al. (OSDI '22)_，PipeThreader 不再只是追求更好的 homogeneous tiling，而是把 heterogeneous pipeline stage 本身变成编译器的一等对象。相较于 _Shi et al. (OSDI '23)_ 与 _Wang et al. (OSDI '24)_，它把 tile-centric compilation 从 memory optimization 和 low-precision transformation 进一步推进到 TMA、TensorCore 与 CUDA-core 之间的联合调度。这也是这篇论文最重要的贡献：它不是提出某一个孤立的 kernel trick，而是给出了一套编译器抽象，使系统能以远少于手写实现的工程成本，自动合成专家级流水线。

## 局限性

论文最有说服力的证据仍然集中在 single-GPU inference。multi-GPU overlap、TPU-like device，以及 MoE 的 grouped MatMul 都只是被讨论为自然扩展方向，还没有在本文中落地。部分 headline result 也受益于现有系统对新型 operator 的支持不足，尤其是 Mamba2，因此性能差距并不完全等于“纯调度质量差距”。另外，联合搜索并非没有代价：在 H100 上，一个 FlashAttention 配置的编译时间是 5.26 分钟，而 Triton 在文中报告的是 0.74 分钟。

## 相关工作

- _Ma et al. (OSDI '20)_ — Rammer 用 rTask 支持更整体的 DNN compilation，但仍然默认 execution unit 是同构的，没有把异构子单元之间的流水线调度显式化。
- _Zhu et al. (OSDI '22)_ — Roller 主要优化 tensor compilation 的 tile-level spatial mapping，而 PipeThreader 额外把 reduction tiling 和按执行单元划分的 pipeline order 变成优化对象。
- _Shi et al. (OSDI '23)_ — Welder 关注的是 tile graph 与 vertical fusion 下的 memory-access 优化；PipeThreader 则继续追问这些 fused stage 应该怎样在 TMA、TensorCore 与 CUDA core 上重叠执行。
- _Wang et al. (OSDI '24)_ — Ladder 通过 tensor transformation 优化 low-precision execution，而 PipeThreader 把 scheduling 本身当成主要优化目标，直接在 sProgram 空间里搜索。

## 我的笔记

<!-- 留空；由人工补充 -->

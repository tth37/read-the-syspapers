---
title: "BitRed: Taming Non-Uniform Bit-Level Sparsity with a Programmable RISC-V ISA for DNN Acceleration"
oneline: "BitRed 把位稀疏 DNN 加速拆成三条可流水的 RISC-V 指令，让编译器能隐藏预处理、重分配失衡比特通道，并优化归约阶段。"
authors:
  - "Yanhuan Liu"
  - "Wenming Li"
  - "Kunming Zhang"
  - "Yuqun Liu"
  - "Siao Wen"
  - "Lexin Wang"
  - "Tianyu Liu"
  - "Haibin Wu"
  - "Zhihua Fan"
  - "Xiaochun Ye"
  - "Dongrui Fan"
  - "Xuejun An"
affiliations:
  - "State Key Lab of Processors, Institute of Computing Technology, Chinese Academy of Sciences, Beijing, China"
  - "University of Chinese Academy of Sciences, Beijing, China"
  - "Ricore IC Technologies Ltd., Beijing, China"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790132"
tags:
  - hardware
  - compilers
  - ml-systems
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

BitRed 的核心观点是，位级稀疏 DNN 加速不该被做成一条封闭的数据通路，而应拆成三条可流水的 RISC-V ISA 扩展指令。这样一来，编译器可以把预处理与归约隐藏到流水线里，硬件则把过载的比特通道任务动态拆分并路由到空闲通道。论文报告它相对 Bitlet 最多快 `9.4x`，相对 BitWave 最多快 `5.6x`，在 GPT-2 上对 A100 的能效优势最高达到 `18.95x`。

## 问题背景

论文抓住了一个对 CNN 和 LLM 都成立的事实：绝大多数计算最终都落在向量点积上，而点积中的权重又普遍包含大量 bit-level sparsity。现有三类稀疏加速器各有短板。像 SCNN 这样的 bit-parallel 设计能跳过零值操作数，但只要一个数整体非零，它里面的零 bit 仍然会被白做。像 Stripes、Laconic 这样的 bit-serial 设计能直接利用 bit-level sparsity，却要付出同步、移位控制和大规模 PE 阵列低利用率的代价。

Bit-interleaving，尤其是 Bitlet，看起来更接近正确方向，因为它让不同 bit significance 走不同并行通道。但作者认为 Bitlet 依旧是“僵硬专用硬件”的思路。对浮点数而言，bit unpacking、指数对齐和 mantissa shifting 本身就是很重的前端开销。更关键的是，每个通道只处理自己绑定的 bit 位置，于是低有效位通道因为 `1` 比特更密集而变成长尾瓶颈，高有效位通道则常常空转。后端 reduction tree 也同时带来延迟和功耗问题。换句话说，Bitlet 看得见位稀疏，却无法处理论文用 ResNet-50 和 GPT-2 展示出来的那种“不同 bit 位置稀疏度高度不均匀”的现实分布。

## 核心洞察

这篇论文最重要的判断是：这里真正需要解决的是调度问题，而不只是 datapath 问题。如果把预处理、稀疏蒸馏和归约三个阶段都显式暴露成 ISA 可见的阶段，编译器就能重叠它们的执行，硬件也能把真正的失衡点暴露出来。

原因在于瓶颈并不只是“有些 bit 为 0”，而是 effectual `1` bit 会非常不均匀地聚集在某些 bit position 上。一旦通道和 bit 位置被静态绑定，总时延就会被最慢的那个通道决定。BitRed 的做法是把非零 bit 对应的工作看成可拆分任务：某个通道一旦超过阈值，就把一部分任务裂解出来，转发给邻近空闲通道继续做。于是，bit position 和执行资源不再被硬绑定。正是 ISA 级拆分让这种动态平衡可以和编译器调度结合起来，而不是继续藏在一个不可见的硬件黑盒里。

## 设计

BitRed 采用 `K x H` 的 PE 网格。每个 PE 都由标准 RISC-V 核心、Adaptive-sparse Processing Unit（ASPU）和路由器组成。ASPU 通过三条自定义流水指令对外暴露。

`cal.pre` 负责预处理。它完成 bit partition、指数对齐和 bit recombination。对浮点输入，它会拆出 sign、exponent 和 mantissa，用 `Emax` 对齐所有操作数，再把对齐后的 mantissa 重新转置成按 bit significance 组织的流，送入后续稀疏执行引擎。对定点输入，昂贵的浮点对齐逻辑会被绕过，这也是总功耗能从 `fp32` 的 `550.43 mW` 下降到 `16b` 的 `495.12 mW` 和 `8b` 的 `457.90 mW` 的原因之一。

`cal.adis` 是全篇最核心的机制。它是一条 variable-latency 指令，内部被做成 multi-group 的流水 datapath，因此多条 distillation 指令可以重叠执行。每个通道接收的 packet 中包含非零 bit 的索引以及原始列坐标。Binary fission node 会先判断这份工作是否超过阈值，论文把阈值设为平均通道负载；若超过，就把任务拆开。之后 bidirectional router 会把多出来的部分向左右空闲邻居转发，边界路由器则负责翻转方向，保证任务不会跑出阵列。真正执行时，distilling node 用 round-robin 方式挑出下一个 effectual bit，shifting and accumulation node 再通过 `col_idx` 恢复它的数值权重，并累加到该通道的 partial sum register 里。

`cal.red` 负责最后的归约。作者没有手工固定 adder tree，而是提出 Candidate-Based Integrated Search Algorithm（CISA），联合搜索 compressor tree 的拓扑和 pipeline cut，目标是最小化 Power-Delay Product。对文中报告的 24 路 partial sums，CISA 找到的结果比面向速度优化的 Wallace tree 低 `17.2%` PDP，比面向面积的 ripple-carry chain 低 `18.6%`。

软件侧同样重要。作者基于 LLVM 实现编译器，从 DNN 图生成 `cal.pre`、`cal.adis` 和 `cal.red`，把前后端工作与相邻向量的核心计算重叠执行，并按每层权重稀疏统计来选择向量长度 `L`。由于 `cal.adis` 具有可变时延，编译器还会插入 `fence` 指令，只在依赖真的出现时才等待它完成。

## 实验评估

实验覆盖 12 个模型，横跨 `fp32`、`16b` 和 `8b`，包括 ResNet-50、DenseNet-161、FCOS、MobileNetV2、DCPDNet 和 GPT-2。BitRed 以 SystemVerilog 实现，在 `28nm` 工艺下综合，评估配置是 `8 x 4` PE 阵列、`1.3 GHz` 主频，并用 FPGA 原型验证关键模块。基线包括 SCNN、Stripes、Laconic、BitWave、Bitlet，以及两款 NVIDIA GPU。

最有说服力的结果是，BitRed 持续消除了 Bitlet 的长尾通道瓶颈。在 DCPDNet（`16b`）上，它比 Bitlet 快 `9.4x`；在 ResNet-50（`8b`）上，它比 BitWave 快 `5.6x`。即使把 BitRed 缩到 `1.51 mm2`、接近 Bitlet 的 `1.54 mm2`，它仍然能在 DCPDNet 上取得 `2.46x` 加速，并带来 `2.57x` 更高的 efficiency-area density。论文的 Figure 10 也很关键：Bitlet 的通道执行周期分布有明显长尾，而 BitRed 通过动态路由把它压成了更紧凑的簇状分布。

能效结果也和这个故事一致。在 DenseNet-161（`16b`）上，BitRed 的归一化能效是 `85.0x`，而 Bitlet 只有 `11.17x`，差距达到 `7.6x`。在 YoloV3（`8b`）上，BitRed 的 `68.3x` 能效又比 BitWave 高 `4.3x`。和 GPU 对比时，论文给出的最高数字是：在 `fp32` 工作负载上，BitRed 对 A100 的能效优势最多 `18.95x`，对 Jetson AGX Orin 32GB 最多 `13.5x`。

我认为这组实验对中心论点的支撑是充分的，因为作者做了比较完整的 ablation。`OPT1` 通过流水化前后端获得 `1.7x-2.4x` 提升；`OPT2` 解决通道失衡，带来最大一跳；`OPT3` 再把 `cal.adis` 自身做成深流水，使 DCPDNet（`fp32`）达到 `13.14x`。需要保留的一点审慎是，很多基线比较依赖统一的仿真和归一化成本模型，而不是所有系统都做了同条件硬件复现，所以趋势判断很强，绝对数值则应更偏向架构论文语境来理解。

## 创新性与影响

和 _Lu et al. (MICRO '21)_ 相比，BitRed 的新意不在 bit interleaving 本身，而在于把 bit-interleaving pipeline 变成 ISA 可见对象，并给它加上动态负载均衡。和 _Shi et al. (HPCA '24)_ 相比，它最关键的一步是把细粒度工作项在运行时拆分并路由，而不是依赖某种固定结构去承接位稀疏模式。和经典 bit-serial 加速器相比，它试图保留位级稀疏利用能力，同时摆脱重同步、重控制的硬件风格。

因此，这篇论文的意义不只是又快了一些。它更像是在主张：某些 accelerator bottleneck 应该被暴露给软件层，让编译器参与调度。做稀疏 ML 加速器、可编程 NPU、或者 RISC-V AI 协处理器的人，都会很容易从中看到后续空间。

## 局限性

BitRed 并不便宜。完整设计面积是 `5.072 mm2`，约为 Bitlet 的 `3.3x`，而且接近 `30%` 的面积都花在 adaptive distillation logic 上。论文用 density 指标说明这笔投入是值得的，但面积开销本身仍然是部署时必须面对的代价。另一方面，variable-latency 的 `cal.adis` 也把一部分复杂性转移到了编译器，并要求显式 `fence` 来保证依赖正确。

实验最强的适用范围是 sparse inference，这也是作者自己明确声明的目标。训练支持、activation sparsity 和 structured sparsity 都还在未来工作里。敏感性分析还显示，像 GPT-2 这类更 dense 的 `fp32` 工作负载在大约 `35.2 GB/s` 时会转为 memory-bound，所以它的优势主要还是集中在稀疏和量化模型上，而不是无差别覆盖所有模型。最后，很多基线结论依赖统一成本模型而非产品级直接对打，因此更适合把它读成一篇很强的架构论证，而不是现成产品胜负表。

## 相关工作

- _Lu et al. (MICRO '21)_ — Bitlet 奠定了 bit-interleaving 利用 bit-level sparsity 的思路，而 BitRed 直接针对它的刚性通道、阻塞式预处理和低效归约树下手。
- _Shi et al. (HPCA '24)_ — BitWave 同样利用位级稀疏，但仍保留较强的结构化映射；BitRed 的贡献是把任务裂解与跨通道路由做成运行时动态机制。
- _Sharify et al. (ISCA '19)_ — Laconic 是代表性的 bit-serial 基线，能跳过无效 bit；BitRed 则希望在保留位级利用能力的同时，避免同样重同步的执行风格。
- _Judd et al. (MICRO '16)_ — Stripes 展示了 bit-level execution 的早期潜力，而 BitRed 的论点是：当负载失衡成为主导瓶颈后，可编程 bit-interleaving 会比传统 bit-serial 更合适。

## 我的笔记

<!-- 留空；由人工补充 -->

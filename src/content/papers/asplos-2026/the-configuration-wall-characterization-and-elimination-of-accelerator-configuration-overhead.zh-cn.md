---
title: "The Configuration Wall: Characterization and Elimination of Accelerator Configuration Overhead"
oneline: "论文把加速器配置开销建模为一等性能瓶颈，并用 MLIR 方言加两类编译器优化来删掉冗余配置、隐藏剩余配置时间。"
authors:
  - "Josse Van Delm"
  - "Anton Lydike"
  - "Joren Dumoulin"
  - "Jonas Crols"
  - "Xiaoling Yi"
  - "Ryan Antonio"
  - "Jackson Woodruff"
  - "Tobias Grosser"
  - "Marian Verhelst"
affiliations:
  - "KU Leuven, Leuven, Belgium"
  - "The University of Edinburgh, Edinburgh, United Kingdom"
  - "University of Cambridge, Cambridge, United Kingdom"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3760250.3762225"
code_url: "https://github.com/kuleuven-micas/snax-mlir"
tags:
  - hardware
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文认为，很多加速器首先撞上的不是算力墙，也不是内存墙，而是主机 CPU 为配置和启动加速器付出的控制开销。作者把这种现象形式化为 configuration wall，并提出一个 roofline 风格模型，再配上一个 MLIR 方言 `accfg` 与两类编译器优化：删除冗余寄存器写入，以及在硬件允许时把配置与执行重叠。实验表明，这套方法在 Gemmini 上已有可见收益，在 OpenGeMM 上达到 `2x` 的几何平均加速。

## 问题背景

论文抓住了一个在很多加速器系统里都存在、但常被当成“实现细节”带过的问题。现代加速器往往不是靠一条简单指令就能启动，而是需要主机先写入一长串配置参数，里面还常常包含位打包、严格顺序和同步逻辑。这段时间里，CPU 没有做真正的应用计算，加速器也还没开始产生有效结果，因此它既不是“有用的主机工作”，也不是“有用的加速器工作”。

更关键的是，这个问题不会因为硬件变快而自动消失。配置项越多、语义越复杂，加速器虽然更灵活，但每次调用前需要搬运和计算的配置数据也越多。这样一来，加速器本体越快，配置路径占总时间的比例反而越高。作者把这种现象称为 configuration wall：当配置时间已经长于有用计算时间时，再继续提高峰值算力，对端到端性能的帮助就会明显变小。

现有工具很难自动修复这个问题。传统 roofline 只讨论 compute-bound 和 memory-bound，却没有把 host-to-accelerator configuration 看成独立瓶颈。通用编译器也几乎看不懂这类代码，因为现实中的配置逻辑常写成 volatile inline assembly，或者依赖外部寄存器状态。配置顺序不能乱，启动语义可能绑在最后一条指令上，寄存器状态又不在普通 SSA 变量里，所以现成优化器既不敢删，也不敢挪。

## 核心洞察

论文最重要的洞察是：配置开销应该像内存带宽一样，被建模成一等性能约束。为此，作者引入了 operation-to-configuration intensity `IOC`，表示每字节配置可支撑多少有效操作；以及 configuration bandwidth `BWConfig`，表示主机向加速器灌入配置数据的能力。对于支持并发配置的系统，可达性能会被配置项限制；对于只能顺序配置的系统，限制更严，因为配置与执行不能重叠。

这个视角一旦建立，优化目标就很清楚了。要么提高 `IOC`，也就是减少完成同样工作所需的配置量；要么把配置动作隐藏在前一轮加速器执行期间。要做到这一点，关键不是再写更多手工技巧，而是给编译器一个足够精确的配置状态抽象。

## 设计

设计由模型和编译器抽象两部分组成。模型部分把配置瓶颈放进 roofline 体系，并额外提出 effective configuration bandwidth，用来把主机端为了生成配置参数而执行的额外计算也算进去，例如运行时位打包。这样一来，配置成本不再只等于“写了多少寄存器”，而是更接近真实控制路径。

编译器部分则提出了基于 MLIR/xDSL 的 `accfg` 方言，核心操作只有三个：`setup`、`launch` 和 `await`。`setup` 产出一个代表“当前加速器配置状态”的 SSA 值；`launch` 消费这个状态；`await` 用来等待执行完成。这个设计的本质，是把原来藏在外部寄存器里的状态显式搬进编译器 IR。论文还定义了 effect 标注，让未知操作默认被看作可能破坏状态，而被标注的调用可声明自己保持状态不变。

在这个抽象之上，作者实现了两类核心优化。第一类是 configuration deduplication：沿着状态链回溯，删掉那些把同一个值再次写入同一个字段的 setup，同时配合循环外提和分支重组，提高去重命中率。第二类是 configuration-computation overlap，只对支持并发配置的硬件启用。这里编译器把循环改写成软件流水形式，把下一次调用的纯 setup 工作提前到前一次 `await` 之前，从而把控制路径隐藏在加速器执行期间。

## 实验评估

实验围绕两个开放平台展开。Gemmini 是顺序配置的矩阵加速器，主要用来检验抽象能否暴露并消除冗余 setup。作者用 Spike 统计配置字节数、寄存器写入指令数，以及生成参数所需的额外主机指令数。对一个 `64x64` 的矩阵乘内核，论文估算：若只看理论配置带宽，可达利用率只有 `41.49%`；若把参数计算时间也算进 effective configuration bandwidth，上限进一步降到 `26.78%`。这很好地说明了传统 processor roofline 为什么会低估真实瓶颈。

在实测性能上，Gemmini 采用 weight-stationary tiled matrix multiplication，并与 `GCC -O2` 的基线实现比较。最终几何平均提升为 `11%`，在矩阵尺寸 `128` 左右收益最大。这个数字不夸张，但它说明即便是顺序配置平台，只要编译器能理解配置语义，也能拿到稳定收益。

OpenGeMM 的结果更能体现论文主张，因为它支持并发配置。作者在一个 `1024 ops/cycle` 的 Verilator 周期级模型上运行 tiled matrix multiplication，对比基础 MLIR 流水线、只做 deduplication、只做 overlap，以及两者都做的版本。完整优化带来 `2x` 的几何平均提升，具体尺寸上的加速范围为 `1.86x` 到 `2.71x`。而且这些测量点画回 roofline 后，与理论预测高度一致：deduplication 会让点向右上移动，因为 `IOC` 增加；overlap 则主要把点往上抬，逼近并发配置的 roofline。整体上，这组实验很好地支持了论文主张，不过两个案例都还是矩阵加速器，且软件栈较轻，所以外推范围仍有限。

## 创新性与影响

相对以往的 roofline 思路，这篇论文的创新在于把 configuration 作为独立性能边界，而不是含糊地并入 compute 或 memory。相对 _Agostini et al. (CGO '24)_ 这类 accelerator compilation 工作，以及 _Suresh et al. (PACT '24)_ 这类接口/硬件协同工作，它更偏向编译器一侧：显式表示 accelerator state，用 SSA 风格结构去推理，再据此删除或隐藏 setup 成本。正因为如此，它的价值不只在单一后端，而是可能影响硬件设计者、编译器研究者，以及整个 MLIR 加速器生态。

## 局限性

论文也明确留下了不少边界。首先，评测平台虽然风格不同，但都还是矩阵乘类加速器，所以“普适性”更多由抽象和模型来论证，而不是由跨领域 workload 来证明。其次，overlap 优化要求硬件支持并发配置，而且 setup 相关计算必须足够纯净，能被安全前移；对那些带复杂副作用或更重软件协议的加速器，这套改写未必同样直接。

此外，当前抽象对函数调用和复杂控制流仍然偏保守。未知调用默认可能破坏状态，条件分支也会让编译器失去一部分可证实的配置信息，而 fault handling 与 OS 驱动路径则不在论文讨论范围内。因此，这些结果目前最适用于裸机或编译器强控制的加速器软件栈。

## 相关工作

- _Cardwell and Song (HPCAsia '19)_ — 他们的扩展 roofline 关注分布式系统中的通信代价，而本文把 configuration 提升为 host-controlled accelerator 的独立瓶颈。
- _Agostini et al. (CGO '24)_ — AXI4MLIR 关注为定制 AXI 加速器自动生成主机侧代码，`accfg` 则进一步把配置状态显式化，使其可被编译器优化。
- _Wei et al. (ASPLOS '23)_ — Cohort 研究面向异构 SoC 的软件化加速流水线；本文主要面对寄存器配置型加速器，但也把 Cohort 一类队列化流水作为未来扩展方向。
- _Suresh et al. (PACT '24)_ — Mozart 通过新的共享内存接口减少 accelerator taxes，而 The Configuration Wall 提供的是一套解释并削减配置开销的模型与编译器方法。

## 我的笔记

<!-- empty; left for the human reader -->

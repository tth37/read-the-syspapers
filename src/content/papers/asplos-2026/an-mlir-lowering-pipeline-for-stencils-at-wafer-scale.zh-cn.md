---
title: "An MLIR Lowering Pipeline for Stencils at Wafer-Scale"
oneline: "把 stencil 语义保留到 MLIR lowering 的后段，再自动合成面向 Cerebras WSE 的分块、actor 风格 CSL，性能可追平甚至超过手写实现。"
authors:
  - "Nicolai Stawinoga"
  - "David Katz"
  - "Anton Lydike"
  - "Justs Zarins"
  - "Nick Brown"
  - "George Bisbas"
  - "Tobias Grosser"
affiliations:
  - "Technische Universität Berlin, Berlin, Germany"
  - "EPCC, University of Edinburgh, Edinburgh, United Kingdom"
  - "School of Informatics, University of Edinburgh, Edinburgh, United Kingdom"
  - "Imperial College London, London, United Kingdom"
  - "University of Cambridge, Cambridge, United Kingdom"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790124"
code_url: "https://github.com/xdslproject/wse-stencil"
tags:
  - compilers
  - hardware
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文把 stencil 语义一直保留到 MLIR lowering 的后段，再把它们变成适合 Cerebras WSE 的分块通信、actor 风格回调和 CSL。结果是：现有的 Fortran 与 Python stencil 前端无需改写，就能生成接近甚至超过手写 WSE kernel 的代码。

## 问题背景

论文针对的是 Cerebras Wafer-Scale Engine 在 HPC 采用中的核心障碍。WSE 拥有海量处理单元、巨大的片上分布式 SRAM 和极高的片上带宽，看起来非常适合 stencil；但它的编程模型很不友好。一个在 Fortran 中只是普通时间步循环的 stencil，到 WSE 上就会因为异步邻域交换、每个 PE 只有 `48 KB` 本地内存，以及缺乏包围通信的同步控制流，而被迫改写成任务与回调。

这直接损害了可移植性和性能工程。用户必须把已有代码手工重写成 Cerebras 专用的 CSL，并亲自决定几何划分、分块 halo 交换、buffer 使用和通信/计算交叠。其实 PSyclone、Devito 和 Flang 已经掌握了 stencil 的形状和依赖信息，但在这篇论文之前，没有一条 MLIR 路径能把这些语义一直保留下来并自动生成高效的 WSE 程序。

## 核心洞察

论文最关键的观点是：面对 WSE 这种架构，stencil 的高层语义必须保留得更久，因为高效代码生成真正依赖的，恰恰是通用低层 IR 很容易过早抹掉的信息，比如邻域形状、远端与本地访问、归约结构，以及常数系数能否与通信融合。只要这些信息还在，编译器就能把同步 stencil 机械地改写成 actor 风格程序。

因此，作者没有直接把 `stencil` dialect 早早降成普通 loop，而是通过分阶段 dialect 逐步桥接语义模型：先显式化通信，再拆开远端数据处理和本地计算，最后把它们降成在 chunk 到达或通信完成时触发的任务。把 processing element 看成 hardware actor、把 CSL task 看成 software actor，也让 callback 和任务图有了统一的编译目标。

## 设计

整条 pipeline 从 PSyclone、Devito 和 Flang 出发，它们都会生成或接入 MLIR/xDSL 的 `stencil` dialect。第一组变换先把三维 stencil 映到 WSE 的二维 PE 网格：`x`、`y` 维分布到网格上，`z` 维 tensorize，使每个 PE 保存一列值，并通过 `dmp.swap` 显式标注 halo 交换。

第二组变换把这种表示降到新引入的 `csl-stencil` dialect，核心是 `prefetch`、`apply` 和 `access`。其中 `csl-stencil.apply` 被拆成两个 region：一个在远端 chunk 到达时逐步处理并归约，另一个在远端数据准备好后执行本地计算。这个设计非常贴合 WSE 的小内存现实，因为系统不需要一次缓存整个 halo，而是可以边收边算；若条件合适，编译器还会把系数乘法前推到通信路径中。

之后的 lowering 负责把语义一步步落实成可执行程序。`csl-wrapper` 打包 PE 程序与 layout metaprogram，`csl-ir` 足够接近 CSL，可以直接打印源码。MLIR 的 bufferization 与 `linalg` 先把 tensor 变成 destination-passing 的内存操作；接着，每个异步 stencil.apply 会被拆成 actor 式任务，一个按 chunk 触发，另一个在通信结束后触发。顶层循环也会改写成任务图，最后算术被降成使用 Cerebras Data Structure Descriptor 的 `csl-ir` 操作，配套运行时库负责 star-shaped stencil 的分块交换和 callback 接线。

## 实验评估

实验覆盖五个 benchmark：Flang 的 Jacobian、Devito 的 Diffusion 与 Acoustic、PSyclone 的 UVKBE，以及一个从 Cerebras 手写 CSL 转来的 25-point seismic kernel。实验在 WSE2 与 WSE3 上进行，使用单精度浮点，并覆盖多种问题规模。

最扎实的结果是对手写 WSE 代码的比较。在 25-point seismic benchmark 上，编译器生成的 WSE2 代码最多比人工调优的 CSL 快 `7.9%`。原因也很具体：生成代码只通信真正需要的列，更省内存，所以一次交换只需一个 chunk，同时把 task 数量减少了约 `50%`。同一条 pipeline 还能直接生成 WSE3 代码，而 WSE3 相比 WSE2 最高再快 `38.1%`。

更大的系统级结论来自 Acoustic benchmark。论文报告 WSE3 的 time-to-solution 约比 `128` 张 Nvidia A100 快 `14x`，比 `128` 个 ARCHER2 CPU 节点快 `20x`。作者也明确承认这不是完全 apples-to-apples 的比较，因为 CPU/GPU 运行采用了更大的问题规模，GPU 基线还是 OpenACC。不过 roofline 结果仍然支持论文的中心论点：在 WSE3 上，这些 stencil kernel 大多是 compute-bound，而 A100 上的 Acoustic 仍然受 memory-bound 限制。

## 创新性与影响

相对 _Bisbas et al. (ASPLOS '24)_，这篇论文的新意不在于再造一个 stencil dialect，而在于把原本面向 MPI 分布式内存的共享编译栈转向异步的 Cerebras WSE。相对 _Jacquelin et al. (SC '22)_，它的贡献不是更强的手写 kernel，而是把 chunking 和通信技巧自动化。相对 _Sai et al. (SC '24)_，它最重要的差异在于前端解耦。

这让它的意义超出了“又多一个 MLIR backend”。论文证明了，当目标架构的执行模型和源程序差异非常大时，保留领域语义是获得可移植性和高质量代码生成的必要条件。

## 局限性

最明显的限制是覆盖范围。论文里的运行时通信库主要支持最多三维的 star-shaped stencil，当前划分也默认每个 PE 承载一整列 `z` 值；更一般的通信模式或映射还需要额外工作。

这套方法仍然依赖较强的领域假设。论文没有自动综合任意硬件路由，跨平台 headline 数据也要谨慎解读，因为 GPU 基线使用的是 OpenACC，问题规模也不同。最后，生产力收益主要来自代码行数对比，而不是严格的开发时间研究。

## 相关工作

- _Bisbas et al. (ASPLOS '24)_ — 提供了共享的 MLIR/xDSL stencil 编译底座，而本文把它从 MPI 风格分布式系统扩展到了 Cerebras WSE。
- _Jacquelin et al. (SC '22)_ — 展示了手写 25-point stencil 与分块通信策略，本文相当于把这些优化技巧内化进编译器。
- _Rodriguez-Canal et al. (SC-W '23)_ — 同样把 stencil 抽象 lowering 到 FPGA，而本文处理的是执行模型更异步的 wafer-scale machine。
- _Sai et al. (SC '24)_ — 也为 Cerebras 风格数据流架构生成 stencil 代码，但走的是 bespoke frontend/compiler 路线，而不是可被现有 DSL 复用的 MLIR backend。

## 我的笔记

<!-- 留空；由人工补充 -->

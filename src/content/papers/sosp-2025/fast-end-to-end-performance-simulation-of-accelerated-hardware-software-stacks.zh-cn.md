---
title: "Fast End-to-End Performance Simulation of Accelerated Hardware–Software Stacks"
oneline: "NEX 原生运行宿主软件，DSim 将加速器时序与功能分离，让全栈仿真在保持约 7% 平均误差的同时从数小时降到数秒。"
authors:
  - "Jiacheng Ma"
  - "Jonas Kaufmann"
  - "Emilien Guandalino"
  - "Rishabh Iyer"
  - "Thomas Bourgeat"
  - "George Candea"
affiliations:
  - "EPFL"
  - "MPI-SWS"
  - "UC Berkeley"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764825"
tags:
  - hardware
  - observability
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

NEX+DSim 通过让宿主软件栈原生执行、只模拟不可获得且性能关键的部分，显著加速了全栈加速器仿真。NEX 在加速器边界处同步，DSim 则把时序与功能拆开处理，因此相对 gem5+RTL 可获得 `6x-879x` 加速，同时在 CPU 核数不短缺时把端到端时间误差控制在平均 `7%`、最大 `14%`。

## 问题背景

全栈仿真的需求越来越强，因为软件团队经常在拿不到真实加速器时先写软件，或者在 tapeout 之前做软硬件协同设计。但主流的 gem5+RTL 方案会把 CPU、内存、互连和加速器都做成细粒度仿真，所以模拟 `1` 秒真实执行可能要花几个小时。这样一来，驱动、运行时和硬件参数的调优就只能走批处理流程。更快的替代方案，比如分析模型或 API 级拦截，往往又丢掉了系统开发者最关心的交互：OS 行为、DMA 时序，以及宿主执行与加速器工作的重叠关系。

## 核心洞察

论文给出的 minimality principle 很直接：只模拟不可获得的部件，而在这些部件内部也只模拟性能关键的方面。如果目标 CPU 已经存在，而且不需要 CPU 微架构可见性，那么宿主就应该原生运行，模拟器只在 MMIO、共享缓冲区和 DMA 边界介入。加速器内部也可以做同样的拆分：一个模型决定“发生什么请求和结果”，另一个模型决定“这些事件何时发生”。只在外部可见事件处同步，就能保住系统开发者关心的时间关系，同时丢掉昂贵的内部细节。

## 设计

NEX 是宿主侧 orchestrator。它的 Linux `sched-ext`/eBPF 调度器按固定 epoch 推进虚拟时间，并保证线程和同步事件都完成 epoch `i` 后，系统才进入 epoch `i+1`。runtime 则负责真正的边界跨越：驱动把 MMIO 区域或任务缓冲区映射到受保护内存上，访问这些页时会借助 `ptrace` 陷入 NEX；NEX 把对应加速器推进到当前 epoch，执行读写，再恢复应用。默认是 lazy synchronization；若要处理中断，则叠加 hybrid synchronization，tick mode 则允许驱动把多次访问合并成一次显式 trap。

DSim 是加速器侧 di-simulator。它的性能轨是一个 LPN，用来描述阶段、流水线、背压、资源争用和 DMA 发射时间；功能轨则是常规 functional simulator，负责算出正确输出并记录当前任务需要的 DMA 请求。DSim 先用 zero-cost DMA 运行功能轨、按 tag 排队请求，再让 LPN 发出带时间戳的 DMA 事件，并把每个事件与对应请求配对。这样一来，对宿主接口而言 DSim 看起来像 RTL 模拟器，但内部工作量小得多。

NEX 还提供 `CompressT`、`SlipStream` 和 `JumpT`，让开发者可以做 what-if 加速分析或快速跳过不重要代码，这进一步说明它的目标是交互式设计探索。

## 实验评估

实验使用三类带真实软件栈的开源加速器：Apache VTA、Protoacc 的 serializer，以及 JPEG decoder。基线是 SimBricks 上的 gem5 + Verilator RTL；对 VTA，作者还额外与两个 FPGA testbed 对比。相对 FPGA 执行，NEX+DSim 在单 VTA workload 上达到平均 `6%`、最坏 `12%` 的误差；相对 gem5+RTL，在全部加速器和基准上达到平均 `7%`、最大 `14%` 的误差。

最重要的结果是速度：相对 gem5+RTL 达到 `6x-879x` 加速。分解结果也很有解释力：单独使用 NEX 就能通过去掉 CPU 时序仿真带来 `2x-157x` 加速；单独使用 DSim 则在加速器模拟占主导时最有效；两者结合时，相比最佳单组件方案还能再快最多 `92x`。交互式 case study 则说明这种速度为什么有价值：以 VTA 上的 ResNet-50 为例，初始设计延迟是 `677 ms`；开发者可以在每次不到一分钟的运行里，把设计逐步探索到 `292 ms`、`162 ms` 和 `146 ms`。

## 创新性与影响

相对 SimBricks 或 gem5-RTL，这篇论文最大的贡献是定义了一个新的速度/可见性折中点：用 epoch 协调的 native host execution，配合只在外部可见事件处重新汇合时序与功能的 accelerator di-simulation。相对 _Ma et al. (OSDI '24)_ 提出的 LPN 工作，本文进一步说明了 LPN 只有在与功能轨和宿主同步器结合之后，才会真正变成实用的全栈工具。更重要的影响是方法论层面的：全栈加速器仿真不再只是最后阶段的验证瓶颈，而可以成为日常、可交互的系统开发工具。

## 局限性

论文对自身遗漏点说得很清楚。NEX 不模拟 host 与 accelerator 之间的内存争用，也没有计入 accelerator DMA 的 I/O TLB 地址转换开销，因为这两者都需要更细的宿主内存模拟。准确性也会在物理核数不足或 oversubscribed workload 强依赖 Linux 调度细节时下降，OpenMP 的 SP 和 LU 就是明显例子。最后，评估对象限于开源加速器且大多是单机场景，因此它在这些范围内很有说服力，但超出这些范围的泛化能力还没有被完全证实。

## 相关工作

- _Reinhardt et al. (SIGMETRICS '93)_ — Wisconsin Wind Tunnel 已经展示过“现成部件原生执行”的思路，但 NEX 把它扩展到了包含 MMIO、DMA 和中断边界的现代加速器全栈系统。
- _Li et al. (SIGCOMM '22)_ — SimBricks 提供模块化的全系统组合能力，而本文通过 native host execution 加上 di-simulated accelerator，把速度与可见性的折中点大幅向前推进。
- _Karandikar et al. (ISCA '18)_ — FireSim 提供 cycle-exact 的 FPGA 系统仿真，而 NEX+DSim 完全保持在软件内运行，更强调交互式设计迭代，而不是要求整个 SoC RTL 都可获得。
- _Ma et al. (OSDI '24)_ — Performance Interfaces 提出了 LPN 这种加速器性能模型；本文则把它和 functional simulation 及宿主侧 orchestration 结合起来，做成了实用的端到端仿真系统。

## 我的笔记

<!-- empty; left for the human reader -->

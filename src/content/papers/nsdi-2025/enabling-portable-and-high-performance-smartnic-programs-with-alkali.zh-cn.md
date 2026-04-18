---
title: "Enabling Portable and High-Performance SmartNIC Programs with Alkali"
oneline: "Alkali 把单线程 SmartNIC 程序编译成面向目标 NIC 的流水线代码，并自动选择切分点、副本数和状态放置策略。"
authors:
  - "Jiaxin Lin"
  - "Zhiyuan Guo"
  - "Mihir Shah"
  - "Tao Ji"
  - "Yiying Zhang"
  - "Daehyeok Kim"
  - "Aditya Akella"
affiliations:
  - "UT Austin"
  - "UCSD"
  - "NVIDIA"
  - "Microsoft"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
tags:
  - smartnic
  - compilers
  - hardware
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文的核心观点是，SmartNIC 程序员不该为每一代 DPU、FPGA NIC 或专用 ASIC NIC 手工重写同一份逻辑。Alkali 的做法是提供一个面向 NIC 的中间表示 `αIR`，再用一个迭代式优化器自动把单线程程序切成流水线阶段、决定哪些阶段可以安全复制，以及把状态放到目标硬件合适的内存层级里。跨四类差异很大的 NIC，生成代码与专家手工调优版本的性能差距控制在 9.8% 以内。

## 问题背景

论文切中的是真实工程痛点：今天的 SmartNIC 编程同时受制于“架构绑定”和“性能绑定”。不同厂商分别暴露紧耦合底层硬件的 SDK 或语言，例如 Agilio 的 Micro-C、BlueField 的 DOCA，或 FPGA NIC 直接用 HDL。开发者即便先把一个版本写出来，移植到另一张 NIC 时仍然要重新翻译底层原语、重做流水线划分、修改副本数、再把状态重新摆到另一套内存层级里。

FlexTOE 的例子把这个问题说明得很具体。对 BlueField-2 来说，非流水线版本反而最好；而在 Agilio 和 FPGA 上，三阶段流水线表现最佳。阶段复制数同样显著影响吞吐，而状态放置甚至能带来超过 8 倍的性能差异。Floem、ClickNP、P4 系工具链等既有框架都能在某一类架构内提供帮助，但它们并没有给出一套可复用的编译基础设施，让同一份程序自动适配异构 SmartNIC。随着数据中心不断更换 NIC 厂商和代际，这种缺口会越来越明显。

## 核心洞察

Alkali 的关键判断是：SmartNIC 的硬件差异确实很大，但 SmartNIC 程序的结构远比底层接口看起来更规律。论文认为，跨这些设备，大部分程序都可以用两类并行性来描述，即 pipeline parallelism 和 data parallelism；状态也大致可以归纳为三类，即局部值、持久表状态，以及阶段之间传递的 context state。只要编译器先直接表示这些“共同语义”，就能把硬件相关决策推迟到优化与后端生成阶段。

因此论文提出了 stateful handler graph 形式的 `αIR`。一个 handler 表示运行在一个计算单元上的代码块；handler 之间的边表示流水线式事件流；副本数表示数据并行；显式状态对象则暴露哪些状态可以切分、哪些可能共享。程序一旦进入这种表示，编译器就可以“搜索并行化方案”，而不是逼程序员手工设计整套并行结构。

## 设计

前端接受一套 C 子集和一个 architecture specification header，后者用来声明目标 NIC 支持哪些硬件事件。开发者只需要写单线程、run-to-completion 的处理函数。Alkali 再把代码降到基于 SSA 的 `αIR`，让 handlers、event controllers 和程序状态全部显式化。

优化循环分成两个阶段。第一阶段是 mapping engine，它决定每个 handler 应该复制多少份，以及每个持久表和 context 对象该放在哪一层内存里。这个决策被编码成 SMT 问题，并同时受限于计算单元数量、内存容量、可达范围以及状态一致性规则。只有当可变状态能按 key 安全切分时，handler 才允许复制；例如某张可写表的所有访问都使用同一个 key，而且 event controller 能保证相同 key 始终被转发到同一个副本。其性能模型刻意保持简单：每个 handler 的吞吐由指令时间、内存访问时间以及阶段间通信时间组成，这些参数都来自厂商提供的一小份 performance specification。

第二阶段是 cut engine，它接过当前瓶颈 handler，尝试把它切成两个阶段。做法是先根据 SSA 语句和数据依赖构造流网络，再用 weighted balanced min-cut 找切分点。权重函数对应三种提速来源：减小单个 handler 的状态体积，使其能进入更快内存；减少每个阶段的指令数；或者把使用不同 key 的持久表拆到不同阶段，为下一轮复制创造条件。为了保证正确性，Alkali 还引入 UNCUT 节点，阻止一次 table lookup 被切到与后续 update 不一致的另一阶段里。

在 mapping-then-cut 循环结束后，Alkali 还会做一批较小的优化，例如 common-subexpression elimination、event controller generation、context conversion，以及 context memory reuse。原型目前能为 Agilio、BlueField-2、Alveo FPGA NIC 和 PANIC 的 RISC-V 原型 NIC 生成代码。

## 实验评估

评估覆盖五个应用：L2 forwarding、FlexTOE transport RX、一个 NF chain、RPC message reassembly，以及 JSQ RSS。第一个重要结果是可编程性：Alkali 版本的代码行数相比厂商特定实现减少了 5 到 10 倍，而且同一份 Alkali-C 源码无需修改就能编译到所有目标 NIC 上。

性能最好的场景，是应用状态可以安全分区且目标硬件确实能提供足够并行度的时候。L2 forwarding 在所有平台上都能跑满线速。FlexTOE 也在除 PANIC 之外的所有平台上达到线速；PANIC 的瓶颈来自较低频率的 RISC-V 核。NF chain 在 FPGA 和 Agilio 上达到线速。Message reassembly 在 Agilio、BlueField-2 和 PANIC 上都低于线速，因为把 payload 拷入重组缓冲区这一步在 SoC 风格路径上代价很高。JSQ RSS 在多个平台上受限，是因为其表查找和更新使用不同 key，导致 handler 无法被安全复制。

与手工调优基线相比，Alkali 的表现可以称得上“可信”，但不是完全追平。在 Agilio 上，FlexTOE 与专家实现的差距约为 10%。在 FPGA 上，生成出来的 JSQ RSS 吞吐与 Ringleader 持平，但因为后端为了满足 timing 插入了更保守的寄存器，延迟高出 30%，LUT 使用量高出 18%。在 BlueField-2 上，专家手写的 message reassembly 和 JSQ RSS 代码只比 Alkali 快 0.6% 到 9.8%，而专家为这些版本花了大约 14 小时做目标相关调优。

编译器本身的评估同样关键。迭代式 mapping-then-cut 搜索会随着阶段数增加逐步找到更好的方案，并在少量额外切分后趋于收敛。在一个缩小后的 Agilio 搜索空间里，mapping engine 找到的是第二优复制方案，只比暴力搜索最优解低 8.4%。状态放置逻辑相比“全部放进 EMEM”或“全部放进 CLS”的朴素策略，带来 1.32 倍到 6 倍的吞吐提升。

## 创新性与影响

这篇论文的创新点不是发明了新的 SmartNIC 硬件原语，而是把“面向 stateful NIC 执行的可复用 IR”与“联合考虑流水线切分、复制和内存放置的优化循环”组合到了一起。既有系统通常只覆盖其中某一部分，而且只针对某一种 NIC 架构。Alkali 则把这些能力包装成一套跨多类 SmartNIC 的可移植编译框架。

这对构建 NIC-side transport、network function、storage offload 或请求调度系统的团队很重要，因为应用逻辑的变化速度通常慢于 NIC 硬件的更替速度。如果厂商愿意暴露 Alkali 所需的那一小份架构与性能描述，整个系统就能显著降低 vendor lock-in，也能减少跨代迁移时的人肉调参成本。

## 局限性

论文明确承认，Alkali 不是一个能保证全局最优的自动调优器。它的性能模型有意保持简单，没有细致建模更复杂的竞争、缓存行为和乱序执行。前端也只支持 C 的一个子集，不支持无界循环、重度依赖指针的代码和并发原语。

更关键的是，Alkali 当前回避了锁。只有当可变状态可以按 key 安全分区时，它才允许复制 handler，因此一些本质上依赖共享状态的程序无法直接受益。它对 workload 的感知也还比较弱：开发者需要提前手工标注 branch probability 或 replication limit，而系统不会在运行时流量变化后自动重编译或自适应。最后，剩余的性能差距中有一部分来自后端尚未掌握的目标相关技巧，例如 BlueField 上的 buffer reuse，或 FPGA 上更激进的 timing 优化。

## 相关工作

- _Phothilimthana et al. (OSDI '18)_ — Floem 为 NIC-accelerated applications 提供了编程系统，但其编译结构和优化假设主要围绕 on-path SoC NIC，而不是异构 SmartNIC 集群。
- _Li et al. (SIGCOMM '16)_ — ClickNP 提高了 FPGA NIC packet processing 的抽象层级，而 Alkali 试图在 FPGA、DPU、SoC 和类 ASIC NIC 之间维持同一套优化框架。
- _Qiu et al. (SOSP '21)_ — Clara 关注 SoC NIC 上 SmartNIC offloading 的性能预测，可与 Alkali 的跨目标性能模型互补，但并不提供对应的代码变换和自动并行化能力。
- _Xing et al. (SIGCOMM '23)_ — Pipeleon 优化的是 SmartNIC 上的 P4 packet processing，而 Alkali 面向更丰富的 C-like stateful program，并联合搜索 stage cut、replication 和 memory placement。

## 我的笔记

<!-- 留空；由人工补充 -->

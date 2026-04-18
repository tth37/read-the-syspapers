---
title: "Co-Exploration of RISC-V Processor Microarchitectures and FreeRTOS Extensions for Lower Context-Switch Latency"
oneline: "通过在 RISC-V 内加入可配置 RTOSUnit，并把 FreeRTOS 的上下文保存、恢复与部分调度搬到硬件里，这篇论文同时压低了切换延迟和抖动。"
authors:
  - "Markus Scheck"
  - "Tammo Mürmann"
  - "Andreas Koch"
affiliations:
  - "Technical University of Darmstadt, Darmstadt, Hesse, Germany"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790141"
code_url: "https://github.com/esa-tu-darmstadt/RTOSUnit_Integration"
tags:
  - scheduling
  - kernel
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文的核心判断是：FreeRTOS 的上下文切换之所以慢，不是某一条指令特别贵，而是“保存现场、选下一个任务、恢复现场”这三步在软件里被串行执行了。RTOSUnit 用一个可配置硬件单元把这条串行路径拆开，可按需把上下文保存、上下文恢复和调度分别下沉到硬件。作者在三种 RISC-V 核上展示，最强配置可把平均上下文切换延迟最多降低 `76%`，并在最简单的核上把抖动降到零。

## 问题背景

在嵌入式实时系统里，外部中断触发后，真正复杂的处理逻辑通常不能全部留在 ISR 中完成，而要切换到某个任务去做 deferred handling。于是，中断响应时间里就包含了完整的 RTOS 上下文切换。对 FreeRTOS 来说，这条路径要保存 29 个会变化的通用寄存器，再加上 `mstatus` 和 `mepc`，然后运行调度器扫描 ready list 与 delay list，最后把下一个任务的状态恢复回来。论文把“从中断触发到执行 `mret`”定义为上下文切换延迟，把最好和最坏情况之间的差值定义为 jitter。

问题不只是平均值高，而是可预测性差。控制回路和安全关键软件需要稳定的上界来做 WCET 分析，但 FreeRTOS 的软件调度路径会随着队列内容、延迟任务数量以及底层微架构行为而变化。最直接的回答当然是退回 bare metal，可那会失去 RTOS 带来的任务抽象、同步原语和工程可维护性。论文真正要回答的是：能否保留 FreeRTOS 的编程模型，同时把最拖后腿的串行软件路径拆掉，让响应更快也更稳定。

## 核心洞察

论文最值得记住的命题是：RTOS 上下文切换内部其实存在大量可重叠的工作，但传统软件实现没有把这些并行性用起来。中断一到，处理器并不一定要先把全部寄存器都写回内存，才能开始运行调度器；它真正需要的只是一个干净的寄存器银行，让 ISR 先跑起来。同理，一旦知道下一个任务是谁，恢复该任务状态也可以和 ISR 的尾部并行执行。如果再把 ready list 与 delay list 一并搬进硬件，ISR 本身就会收缩到几乎只剩更新 `currentTCB`。

这也是 RTOSUnit 不做成单一“全能加速器”的原因。不同嵌入式场景在面积、平均延迟和 jitter 之间的偏好并不一样，所以作者把设计拆成可组合的功能位：`S` 负责后台保存上下文，`L` 负责硬件恢复上下文，`T` 负责硬件调度，外加 dirty bit、load omission、preloading 等可选优化。论文的主张不是笼统地说“硬件加速 RTOS 很有用”，而是更细地说明：哪些子路径值得下沉、怎样组合这些子路径，以及这些组合会把设计点推到什么地方。

## 设计

RTOSUnit 通过自定义 RISC-V 指令与处理器紧耦合，而不是走 MMIO。`vanilla` 配置保留标准 FreeRTOS ISR。到了 `S` 配置，处理器增加一个供 ISR 使用的备用寄存器文件银行。中断进入时，核心立刻切到新寄存器，后台的 store FSM 再把被打断任务的 31-word 上下文写入一块预留内存。每个任务分配一个固定的 32-word 槽位，由 task ID 索引得到地址，因此硬件不必像软件栈那样不断回写 TCB 里的上下文地址。

`L` 配置再加入 restore FSM。当软件通过 `SET_CONTEXT_ID` 宣布下一个任务后，RTOSUnit 就并行地把该任务上下文从预留内存装回应用寄存器文件和相关 CSR。离开 ISR 的 `mret` 会被阻塞到恢复完成，以保证不会过早返回任务执行。当 `S` 和 `L` 同时启用时，寄存器银行切换会在中断进入和退出时自动完成。

`T` 配置把 FreeRTOS 的 ready list 和 delay list 搬到硬件中。`ADD_READY`、`ADD_DELAY` 和 `RM_TASK` 用来维护这些队列，`GET_HW_SCHED` 则返回 ready queue 头部并把该项重新排到尾部，从而保留同优先级任务的 round-robin 语义。delay list 先按剩余 tick 排序，再按优先级打破平局；定时器中断会递减 delay 值，并在超时后自动把任务移回 ready list。这里要注意，它并没有把 event list 和同步原语也一起硬件化，所以这不是“完整 RTOS 内核上硬件”，而是针对最关键调度路径的部分卸载。

几个可选优化都很务实。dirty bit 让硬件只保存真正被写过的寄存器；load omission 在前后两次选中的任务相同时直接跳过加载；preloading 则利用硬件调度器提前看到 ready list 头部这一点，把最可能下一次运行的任务上下文预取到一个 31-word buffer 中。若猜对，切换会更快；若中断期间有更高优先级任务被唤醒，则会回退到普通加载路径。论文还把集成难点讲得很清楚：CV32E40P 这种简单 in-order 核几乎只需加复用器；CVA6 需要处理 `SWITCH_RF` 带来的流水线冒险；完全 out-of-order 的 NaxRiscv 则必须缓存自定义指令直到确认提交，并把架构寄存器地址翻译成物理寄存器地址。

## 实验评估

实验基于 RISC-V 版 RTOSBench 的全部测试，每个测试运行 20 次，硬件 ready/delay list 长度都设为 8。作者把延迟定义为从中断触发到执行 `mret` 的周期数，把 jitter 定义为最大值减最小值。他们比较了多种 RTOSUnit 配置、原始纯软件实现，以及自己在三种核心上都重做的一版 Balas 等人的 `CV32RT`。

第一个重要结论是：把切换阶段重叠起来，比只做“部分寄存器快照”更有效。`CV32RT` 的平均延迟改善只有 `3%-12%`，而最简单的 `S` 配置就达到 `17%-27%`，且 jitter 大体相当。单独把调度搬进硬件对可预测性尤其关键：在 CV32E40P 上，jitter 从 `188` 周期降到 `16` 周期，下降超过 `90%`；同时平均延迟在 CV32E40P、CVA6、NaxRiscv 上分别降低 `23%`、`29%` 和 `9%`。当 `SLT` 全开后，两项指标都被一起压低：CV32E40P 上 jitter 被完全消除，更复杂的两颗核心上也最多降低 `88%`，剩余变化主要来自 cache 和 speculation 这类 RTOSUnit 本身无法直接消掉的微架构因素。

第二个重要结论是，论文没有只谈“更快”，而是把硬实时边界和硬件代价一起摆出来。对 CV32E40P，baseline 的 WCET 是 `1649` 周期；`SL` 降到 `1442`，`T` 降到 `202`，`SLT` 则进一步降到 `70` 周期，而且和实际测得的切换延迟相同。平均延迟方面，结论部分把面向硬实时的 `SLT` 配置总结为最多降低 `69%`，而摘要给出的“最多 `76%`”则覆盖了更激进的整体设计空间，说明像 preloading 这样的选项虽然可以把均值再压低，却要以更大波动为代价。面积代价也呈现出清晰分层：CV32E40P 上只做调度的 `T` 基本没有可观测面积开销，而追求最低平均延迟的 `SPLOT` 约增加 `44%` 面积；功耗总体与面积高度相关，CV32E40P 上相对增幅最高可到 `72%`，但绝对功耗增量仍然不大。整体上，这套评估很好地支撑了论文主张：不存在单一最优配置，真正有价值的是可按目标在 WCET、均值和面积之间选点。

## 创新性与影响

和 _Balas et al. (TVLSI '24)_ 相比，这篇论文的新意不只是更快地 spill 一部分寄存器，而是把完整上下文的保存与恢复和 ISR 执行重叠起来，并把调度器也纳入可硬件化的范围。和 _Rafla and Gauba (MWSCAS '11)_ 相比，它更强调跨不同 RISC-V 微架构的可移植性，而不是只为单一处理器量身定做。和 FASTCHART 一类更激进的硬件 RTOS 方案相比，它不假设“不现实的一周期整份上下文落内存”，而是在真实内存带宽约束下做折中。

因此，这篇论文对两类人最有价值。对嵌入式处理器设计者来说，它给出了一套很具体的软硬件切分建议，告诉你应该从处理器与 RTOS 边界的哪里下刀。对实时系统研究者来说，它展示了一个常被忽略的事实：如果目标是降低 jitter，而不只是拉低平均值，那么硬件调度卸载的重要性可能和寄存器保存带宽一样大。

## 局限性

RTOSUnit 的硬件调度器只覆盖 FreeRTOS 的 ready list 和 delay list，事件队列以及同步原语仍在软件里处理。这意味着它并不是完整的“硬件 RTOS 内核”；如果工作负载主要瓶颈在 mutex 或 semaphore 交互上，软件路径仍会留下相当一部分开销。固定的上下文内存区和硬件队列长度也给任务数设置了设计时上限，尽管论文说明超过上限时可以退回软件调度。

可移植性展示得不错，但目前仍局限于 RV32IM_Zicsr + FreeRTOS 这一类单核系统。浮点或向量寄存器的上下文支持、多核扩展，都被明确留到未来工作。WCET 分析也只对 CV32E40P 做了完整展开；对于 CVA6 和 NaxRiscv，作者明确表示由于 cache 行为和 speculative execution 太复杂，精确 WCET 分析超出了本文范围。所以如果把论文当作“所有现代核心上都能给出硬实时上界”的证据，就会有些过头；目前最强的硬实时结论仍然主要落在简单 in-order 核上。

## 相关工作

- _Balas et al. (TVLSI '24)_ — CV32RT 通过快照半个寄存器文件来加速中断，而 RTOSUnit 则把完整上下文迁移与调度都纳入了可重叠的硬件路径。
- _Rafla and Gauba (MWSCAS '11)_ — 在 MIPS 上加入上下文保存/恢复自定义指令与 banked context memory；ASPLOS 这篇工作则更强调配置空间与跨三种 RISC-V 核的移植。
- _Grunewald and Ungerer (EUROMICRO '96)_ — 给每个任务单独分配寄存器文件银行，切换极快，但面积会随着任务数直接膨胀；RTOSUnit 通过把上下文放回主存来避免这一点。
- _Nakano et al. (IEICE '99)_ — STRON 把更多 RTOS 职责丢给协处理器，而 RTOSUnit 聚焦于处理器内部最影响延迟与抖动的调度和上下文路径。

## 我的笔记

<!-- 留空；由人工补充 -->

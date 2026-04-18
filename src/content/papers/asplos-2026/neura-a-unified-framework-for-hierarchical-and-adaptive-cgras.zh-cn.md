---
title: "Neura: A Unified Framework for Hierarchical and Adaptive CGRAs"
oneline: "Neura 用层次化空间时序 CGRA 与迁移感知映射，把内核的执行粒度从编译期解绑，使其能在运行时扩展、拆分并复用空闲子阵列。"
authors:
  - "Cheng Tan"
  - "Miaomiao Jiang"
  - "Yuqi Sun"
  - "Ruihong Yin"
  - "Yanghui Ou"
  - "Qing Zhong"
  - "Lei Ju"
  - "Jeff Zhang"
affiliations:
  - "Google, Mountain View, CA, USA"
  - "Arizona State University, Tempe, AZ, USA"
  - "Shandong University, Qingdao, Shandong, China"
  - "Independent Researcher, Qingdao, Shandong, China"
  - "University of Minnesota Twin Cities, Minneapolis, MN, USA"
  - "Cornell University, Ithaca, NY, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790193"
code_url: "https://github.com/tancheng/CGRA-Flow/tree/neura-asplos-ae"
tags:
  - hardware
  - compilers
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Neura 的核心主张是：可扩展的空间时序 CGRA 不该让“编译时映射粒度”直接锁死“运行时加速粒度”。因此它把硬件做成层次化 multi-CGRA，把映射做成 migration-aware，再配一个简单运行时，让多个小内核先挤在一个子 CGRA 上、之后再拆开，或者让一个正在运行的内核扩展到更多子 CGRA 而无需重新编译。在周期性多内核工作负载上，这种组合相对同规模 monolithic 基线带来 `1.64x-3.85x` 的吞吐提升。

## 问题背景

论文抓住的是 CGRA 扩展时最常见的一种失效模式。空间时序 CGRA 规模一旦变大，映射问题会因为搜索空间组合爆炸而迅速变难，但资源利用率却不会自动随之变高。小内核会让大量 tile 空闲，大内核则常常因为 mapper 找不到足够好的放置而得到更差的 initiation interval。更关键的是，在传统设计里，编译器面向一个 monolithic fabric 做静态映射，而这个映射又几乎直接决定了运行时到底能用多少硬件。

这种耦合在动态多内核场景里尤其糟糕。真实系统中的 kernel 到达时间和生命周期都不同，所以执行过程中会不断出现又消失空闲资源。现有 CGRA 往往要么一次只跑一个 kernel，要么做静态分区，于是当某个 kernel 结束后，别的 kernel 很难立刻把新释放出来的资源吃进去。论文的判断是，mapping scalability、architecture flexibility 和 multi-kernel runtime support 不是三个彼此独立的小缺点，而是一起阻碍 CGRA 成为通用可扩展平台的根因。

## 核心洞察

Neura 最重要的洞察是：空间时序 CGRA 应该先围绕一个“可管理的小单元”完成编译，再由运行时决定这个 kernel 实际占用多少这样的单元。也就是说，mapping granularity 和 acceleration granularity 应该是两根不同的旋钮。小 kernel 可以多个共享一个 CGRA；如果后面有更多资源可用，运行时就应该能够把该 kernel 的一部分映射迁移到邻近 CGRA，而不是永远接受编译时那次分配。

但这件事成立的前提是，体系结构必须容忍可变通信延迟。一个 kernel 一旦横跨多个子 CGRA，并且可能去远端 SRAM 取数据，传统那种每个操作固定时延的 clock-driven 假设就不再稳固。Neura 的做法是把层次化硬件、data-driven execution 和 migration-aware mapping 绑在一起：关键路径上的操作尽量固定不动，非关键操作则被当作可移动的 slack。论文用一个合成例子把这个思想讲得很清楚：只迁移非关键操作，就能把一个 kernel 的 II 从 `3` 降到 `2`。

## 设计

Neura 把整体 fabric 组织成一个 CGRA mesh，每个子 CGRA 含有 `4x4` 个 tile 和 8 个 SRAM bank。相邻 CGRA 不是彼此隔离的岛，边界 tile 之间仍通过 crossbar 相连，所有 SRAM bank 也共享一个全局地址空间，可经由 inter-CGRA NoC 访问。每个 CGRA 还配有独立 controller，通过单独的轻量 ring 分发控制信号，从而避免控制流量与 datapath 流量互相争抢。tile 内部则同时提供 scalar FU 和四路 vector FU。

建立在这套硬件之上，论文定义了多种执行模式。大 kernel 可以一开始就映射到多个 CGRA；多个小 kernel 可以先把 DFG 融合后挤进一个 CGRA，等后续资源释放再重新拆开；scalar kernel 可以把非关键操作以 mirrored 的方式迁移到邻居 CGRA；vector kernel 则可以在编译期 vectorization factor 超过单个子 CGRA lane 数时继续向外扩展。论文强调，这些模式可以在同一个 fabric 里并存。

编译器的作用是把这种灵活性保留下来。Neura compiler 基于 LLVM，先做 vectorization 和 unrolling，再构造 DFG、按需融合多个 kernel，并最终生成可迁移映射。这里最关键的策略是：先把 critical path 放好，尽量逼近 `criticalII`，再把非关键操作塞进后续带 slack 的时隙里，让它们成为后续迁移候选。运行时本身反而设计得很朴素：它跑在 host CPU 上，跟踪 kernel 完成状态，采用带 priority boosting 的 `FCFS`，不会撤销已经分配出去的 CGRA，但会让队首且资源不足的 kernel 在别的 kernel 结束后继续吸收新释放的 CGRA。论文称重配置开销通常只有几十个 cycle。

## 实验评估

实验使用了来自 embedded、ML 和 HPC 的十个 kernel，并构造了六种从密集到稀疏的周期性到达场景。主要对比对象是一个同规模的 monolithic `12x12` 空间时序 CGRA，它总共有 `144` 个 tile，且不支持 multi-kernel execution；Neura 的原型则是一个 `3x3` 的 multi-CGRA，每个子 CGRA 是 `4x4`，总 tile 数同样是 `144`。从 `Neura-L0` 到完整 `Neura` 的逐步消融很有价值，因为它把“只是层次化”与“scalar migration、multi-kernel migration、vector expansion”分别拆开了。

核心结果基本支撑了论文主张。相对于基线，总执行时间在 case 2-6 中提升 `1.44x-2.17x`，而整体工作负载吞吐在 case 1-6 中提升 `1.64x-3.85x`。随着到达模式变得更稀疏，收益会更大，这与设计动机一致：时间上的空隙越多，运行时就越有机会把空闲子 CGRA 重新分配给别的 kernel。论文还报告，仅仅层次化的 `Neura-L0` 在最稀疏 case 中就能带来最高 `2.3x` 的吞吐提升，而完整动态机制在此基础上最多还能再加 `1.67x`。资源利用率在密集 case 中接近 `99%`，即便最稀疏时也保持在 `56.66%` 以上。

扩展性实验同样有说服力。面对一个合成的高密度工作负载，当 fabric 从 `2x2` Neura CGRA 扩到 `5x5` 时，整体吞吐加速比从 `5.3x` 增长到 `25.8x`，同时利用率始终高于 `86%`。物理设计结果则更偏工程侧：在 ASAP7、`0.7V`、`400MHz` 下，`3x3` Neura 布局的平均功耗为 `489.7 mW`，相对 `12x12` monolithic 基线大约增加 `10%` 面积和 `10.2%` 功耗。我认为这些消融实验是扎实的，但更广义的跨平台对比就没那么强，因为作者自己也明确承认，不同平台的工艺、硬件假设和软件栈并不直接可比。

## 创新性与影响

相对于 HierCGRA 这类层次化 CGRA 设计，Neura 的真正新意不只是“做成层次化”，而是把 hierarchy、runtime migration 和专门为迁移留出空间的 mapping 一起设计。相对于 FLEX 或 VecPAC 这种向量化 CGRA 工作，它的贡献也不只是增加 vector lane，而是让一个 vectorized kernel 在单个子 CGRA lane 不够时，能够动态吃下更多子 CGRA。相对于 DRIPS 或 ICED 这样的运行时系统，Neura 更进一步试图把 architecture、compiler、runtime、RTL generator 与 physical-design exploration 统一进一个 open-source framework。

因此，这篇论文最可能被三类人引用：做 scalable CGRA architecture 的研究者，做 placement / scheduling 且需要面对动态硬件可用性的编译器作者，以及希望拿到一个端到端开源平台而不是单点原型的工程人员。它更像是一套新的系统机制与完整研究工件的组合，而不是只靠某个 benchmark 数字取胜。

## 局限性

Neura 的迁移机制其实是刻意受限的。动态资源分配只发生在 per-CGRA 粒度，scalar migration 也只迁移非关键操作，而且论文展示的 mirrored migration 明显比真正的通用重映射简单得多。运行时策略同样比较保守：`FCFS` 加 priority boosting，调度器跑在 host CPU 上，已经授予的资源不会被回收，更复杂的策略和专用硬件调度器都被留到未来工作。

实验在论文设定的世界里已经算宽，但这个世界本身仍主要是周期性 kernel mix 加 cycle-accurate simulation。物理设计结果覆盖了作者提出的结构，但 Figure 13 的跨平台功耗/性能对比被作者明确标注为非 apples-to-apples。我也会把这篇论文看作“在并发多内核吞吐与利用率上很强”，而不是已经完全回答了如何在任意真实应用和不可预测内存行为下做最优调度。

## 相关工作

- _Prabhakar et al. (MICRO '24)_ — SN40L 展示了层次化 dataflow 硬件如何 scale out，而 Neura 保留空间时序 CGRA 模型并加入 migration-aware 的运行时扩展。
- _Bandara et al. (ICCAD '23)_ — FLEX 证明了 CGRA 上的向量执行可以很灵活；Neura 则把这种 vector 支持放进层次化 fabric，并允许一个 vectorized kernel 跨多个子 CGRA 展开。
- _Gobieski et al. (MICRO '22)_ — RipTide 是面向超低功耗的 spatial-only dataflow 架构；Neura 选择保留 temporal reconfiguration，以更好支持大而不规则的 kernel 以及运行时迁移。
- _Tan et al. (HPCA '22)_ — DRIPS 面向的是 CGRA 上流式流水线应用的动态再平衡，而 Neura 目标是更一般的层次化 multi-kernel 执行模型。

## 我的笔记

<!-- 留空；由人工补充 -->

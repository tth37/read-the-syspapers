---
title: "Sequential Specifications for Precise Hardware Exceptions"
oneline: "XPDL 为 PDL 加入 pipeline exceptions，让顺序式处理器规格也能综合出精确 trap、interrupt 与 CSR 处理，保持 CPI 不变且成本温和。"
authors:
  - "Yulun Yao"
  - "Drew Zagieboylo"
  - "Andrew C. Myers"
  - "G. Edward Suh"
affiliations:
  - "Cornell University, Ithaca, NY, USA"
  - "NVIDIA, Westford, MA, USA"
  - "Cornell University / NVIDIA, Ithaca, NY, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3760250.3762233"
code_url: "https://github.com/apl-cornell/PDL"
tags:
  - hardware
  - compilers
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

XPDL 把 pipeline exceptions 变成 PDL 里的一级抽象，让顺序式处理器规格可以直接表达 precise trap、interrupt 和 CSR 控制流。设计者只需写普通流水线逻辑、`commit`、`except` 和 `throw`，编译器就会自动生成回滚与清空逻辑。作者在 RISC-V 处理器上的结果显示：常规路径 CPI 不变，最高频率只下降 `3.3%`。

## 问题背景

PDL 的优势，是把流水线处理器写成接近 one-instruction-at-a-time（`OIAT`）的顺序程序，而不是直接暴露 RTL 里的并行控制与 hazard 细节。但真实处理器必须支持 trap、fault、interrupt、system call 和 CSR 更新；这些行为要求较老指令已经提交、较年轻指令被撤销，并把控制权安全地交给异常处理程序。

在传统 RTL 中，这些逻辑通常和整个流水线控制深度耦合，需要额外的簿记结构和 rollback 通路。论文认为这既难写也难验证，而且属于安全关键路径。作者也反对把异常硬塞进 PDL 的 speculation 机制里，因为异常是 ISA 语义，不是性能优化，而且它通常比误预测稀少得多，这样做会用错误的面积-时间权衡来处理慢路径。

## 核心洞察

核心洞察是：precise exception 仍然可以放进顺序式规格里，只要把异常指令看成一个会到达唯一终结点的特殊流水线气泡。到这个点之前，更老的指令完成提交；到这个点之后，更年轻的指令不再允许产生体系结构可见效果。

由于 PDL 已经通过锁和最终提交点区分了“暂态工作”和“真正生效”，XPDL 只需把异常处理也做成一个显式的最终路径，再用静态规则保证指令要么正常提交，要么原子地回滚并执行异常处理。

## 设计

语言扩展本身很小。`throw(args)` 把当前指令标记为异常指令；`commit` 描述正常完成时的最终动作，最常见的是释放写锁；`except(args)` 描述异常完成时的最终动作，例如写 CSR、确认 interrupt、把 `pc` 跳到 handler。每条流水线都只有一个 `commit` 块和一个 `except` 块。

编译器会引入两个隐藏标志：沿 datapath 传播的局部异常位 `lef`，以及在异常处理期间关闭普通流水线工作的全局位 `gef`。当 `throw` 触发时，编译器设置 `lef` 并保存异常参数。到流水线尾部时，普通指令进入 `commit`；异常指令则设置 `gef`，等待已经进入最终区域的更老指令先完成，然后执行 rollback。

rollback 包括清空流水线寄存器的 `pipeclear`、清除推测记录的 `specclear`，以及对每一种锁执行 `abort` 来丢弃未提交状态。只有之后 `except` 才会真正运行。这里锁抽象非常关键：bypass queue、renaming register 等状态组件只要各自实现一次 `abort`，就能获得统一的异常恢复行为，不必在每条流水线里手工拼 rollback 逻辑。

这套机制靠静态规则来守住 precise behavior。`except` 必须自包含；final blocks 不能是推测的；在主体里拿到的写锁只能在 `commit` 中释放；`commit` 不能包含任意 stateful 动作。对于 interrupt，XPDL 还增加了 `volatile` memory，用来表达被外设异步更新、但仍需维持顺序观察的一类状态。

## 实验评估

实现基于扩展后的开源 PDL 工具链，新增大约 `2k` 行 Scala、Bluespec 和 Verilog。基线是一颗带 speculation、register renaming 和写队列的 5-stage RV32IM 核，然后作者在其上分别加入 fatal exceptions、system call 与 interrupt、CSR instructions，以及把这些能力全部合并的完整版本。正确性既用定向测试检查，也用真实软件运行来覆盖 system calls 和 interrupts。

最重要的结论是，异常支持没有拖慢常规路径。在没有异常真正触发时，基线和带 XPDL 的处理器 CPI 相同；论文在 `MachSuite-aes` 上报告的是 `1.59`。最高频率则从 `169.49 MHz` 下降到 `163.93 MHz`，也就是 `3.3%`。编译时间几乎不变，从 `15.34 s` 增加到 `15.50 s`。

面积结果按组成部分拆开看更有意义。论文指出，在各个实现配置里，最多有 `65%` 的面积增量来自 register files 和 CSRs，这更多是在为功能本身付费；新增异常 stage 的 pipeline registers 是第二大来源；CSR 版本里更复杂的解码逻辑又贡献了大约 `10%`。作者还强调，相似处理路径的异常可以共享大量硬件，因此增量支持新异常的成本通常不高。可编程性方面，完整设计仍少于 `500` 行代码。

## 创新性与影响

相对早先的 PDL 工作，这篇论文的创新点在于为 exceptions 提供了独立语言构件和独立综合路径，而不是逼着设计者回到 speculation 或 RTL 手工控制。相对 Verilog 层面的 checkpoint/rollback 扩展，XPDL 把抽象层次提得更高，并从锁接口自动导出恢复行为。相对 continuation-based synthesizable exceptions，它处理的是原生处理器异常语义，而不是软件异常的硬件化。

因此，这篇论文最可能影响的是做高层处理器 HDL、以及希望更快做 design-space exploration 又不想丢掉 OS 级特性的体系结构研究者。

## 局限性

这套设计的代价是结构性限制。XPDL 一次只能处理一个异常，而且必须先清理流水线再进入 handler，所以 interrupt latency 不会很低。异常处理还是非推测的，异常指令与普通指令之间的协作也被限制在体系结构状态层面，这会排除一些更激进的设计。

实验范围也比较窄：主要是 5-stage RISC-V 变体，加上综合和仿真结果，并没有直接和手工优化 RTL 的异常控制逻辑对打。因此它很有说服力地证明了“可行且成本不高”，但还没有证明它能自然扩展到更宽或更乱序的核心。

## 相关工作

- _Zagieboylo et al. (PLDI '22)_ — PDL 提供了面向流水线处理器的 `OIAT` 顺序式 HDL，而 XPDL 在此基础上进一步加入 precise trap、interrupt 和 CSR 风格异常处理。
- _Chan et al. (DAC '12)_ — 该工作为 Verilog 进程加入 checkpoint 与 rollback 机制；XPDL 则把异常提升到语言层，并借助锁抽象自动生成 rollback。
- _Pelton et al. (PLDI '24)_ — Kanagawa 面向流水线式高层硬件综合，但 XPDL 论文认为它缺少 `OIAT` 级别的语义保证，也没有直接处理 ISA 的非顺序行为。
- _Teng and Dubach (ASPDAC '25)_ — continuation-based synthesizable exceptions 面向软件风格异常的硬件化翻译，而 XPDL 关注的是原生处理器异常语义与 precise architectural state。

## 我的笔记

<!-- 留空；由人工补充 -->

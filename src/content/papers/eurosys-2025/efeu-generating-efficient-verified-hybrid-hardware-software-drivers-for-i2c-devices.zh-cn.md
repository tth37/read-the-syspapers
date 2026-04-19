---
title: "Efeu: generating efficient, verified, hybrid hardware/software drivers for I2C devices"
oneline: "Efeu 把整个 I2C 子系统写成同一份分层规格，在建模阶段检查互操作与 quirks，再自动生成 C、Verilog 和可调软硬件边界的驱动栈。"
authors:
  - "Daniel Schwyn"
  - "Zikai Liu"
  - "Timothy Roscoe"
affiliations:
  - "ETH Zurich"
conference: eurosys-2025
category: reliability-and-formal-methods
doi_url: "https://doi.org/10.1145/3689031.3696093"
project_url: "https://gitlab.inf.ethz.ch/project-opensockeye/efeu"
tags:
  - formal-methods
  - hardware
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Efeu 让开发者先把整个 I2C 子系统写成一份分层规格，再在这份规格上检查互操作与已知 quirks，最后按编译期选择的边界生成 C、Verilog 或 hybrid drivers。在 Zynq MPSoC 上，`Transaction` 和 `EepDriver` 两种设计分别跑到 392-396 kHz，中断模式下 CPU 占用只有 8% 和 4%。

## 问题背景

I2C 最大的麻烦，是它不像 PCIe 或 USB 那样给设备提供隔离。controller 与 responders 共享两根线，一个 device、controller 或 workaround 出错，就可能把整条 bus 拖死。这又偏偏发生在电源、传感器、时钟和 BMC 之类的关键路径上，所以后果不仅是功能错误，还可能是锁死、耗电异常，甚至硬件损伤。

以往的 driver verification 或 synthesis 往往只面对单个 device，或者默认接口是标准的。论文认为这正好避开了 I2C 最难的地方：一条总线上的整体验证，以及现实设备和 controller 的 quirks。Raspberry Pi 的 clock stretching bug 就说明，软件可以没写错，但 controller 硬件自己不守 I2C，系统照样会坏。

## 核心洞察

论文的核心判断是，I2C 应该被写成一份由验证和实现共享的分层子系统规格。只要 controller、responders 和 topology 都用这种方式描述，同一份源文件就能生成 Promela 模型、软件 driver、硬件模块，或两者的混合实现。

之所以能这样做，是因为 Efeu 不预设某层必须跑在软件还是硬件里。层间通信是对称的，所以边界可以留到编译时再决定；验证时再用下层的行为模型替代真实实现，就能把状态空间控制住。

## 设计

Efeu 把栈拆成 `Electrical`、`Symbol`、`Byte`、`Transaction` 和设备专用顶层，例如 EEPROM 的 `EepDriver`。ESI 用来描述双向、带类型的 channel；ESM 用来描述层内有限状态机，它长得像受限版 C，靠 `talk` 和 `read` 与相邻层同步。

ESMC 有三条后端。Promela backend 用于 SPIN；C backend 把各层编译成 stack-based coroutines，再用 compile-time call graph 决定外部入口；Verilog backend 则生成 ready/valid state machines。若边界跨在软硬件之间，Efeu 会自动插入 AXI Lite MMIO 接口，并把 `valid` 与 `ready` 设计成一次性信号，避免软件来不及清零时重复发包或丢包。

验证也按层进行。除 `Electrical` 外，每层都写 behavior specification 和输入空间，再检查断言、deadlock 和 livelock。quirks 可以局部修改：KS0127 的 read acknowledgment quirk 在 responder `Byte` 层多 13 行，controller 兼容它再加 10 行；模拟 Raspberry Pi 不支持 clock stretching，只需改 `Symbol` 层 3 行。

## 实验评估

抽象替换直接带来数量级收益。`EepDriver` 的检查时间从 584.78 秒降到 9.15 秒；`Transaction` 从 104.53 秒降到 6.11 秒；`Byte` 从 11.33 秒降到 4.01 秒。论文也验证了多 EEPROM 拓扑，但 payload 变长、设备变多之后，state explosion 仍然明显。

硬件实验在 Zynq UltraScale+ MPSoC 和真实 24AA512 EEPROM 上完成。纯软件 `Electrical` 配置跑到 154.44 kHz，和 Linux bit-banging 的 162.81 kHz 接近。把 `Symbol` 放进硬件后是 263.32 kHz；把 `Byte` 放进硬件后是 359.98 kHz，若用中断边界则为 342.9 kHz。边界上移到 `Transaction` 时，生成驱动达到 392.48 和 392.24 kHz，略高于 Xilinx I2C IP 的 386.57 kHz；全硬件 `EepDriver` 是 396.02 kHz。CPU 占用也同步下降：所有 polling 方案都吃满一个核，而中断模式下 `Symbol`、`Byte`、`Transaction`、`EepDriver` 分别是 64%、36%、8%、4%，Xilinx 基线是 12%。代价是 `Transaction` 设计需要 2.08 倍 LUT 和 2.11 倍 FF，但在目标 FPGA 上也只占 0.70% LUT 和 0.34% FF。

## 创新性与影响

Efeu 的新意，不是单独做出一个更快的 I2C controller，而是把总线级互操作、quirk 建模、形式化检查和软硬件切分整合进同一个 artifact。过去的 verified-driver 工作往往默认一次只看一个 device，过去的 synthesis 工作又往往假设设备行为是标准的；Efeu 真正对准的是 shared bus 上最危险的失败模式。

## 局限性

这篇 paper 的验证仍然是有界的：`Transaction` 和 `EepDriver` 只覆盖很小的 payload，而且内容固定；设备再多，状态空间还是会爆。其次，可信计算基并没有完全收紧，编译器、生成代码、EDA 工具链和手写 bus-timing adapter 都被默认可信。性能数据也只来自一个 MPSoC 和一种 EEPROM，且主要报告读路径，因为写路径被器件 busy time 主导。还有一个失败设计点：中断模式下的 `Electrical` 会产生过多中断，无法正常运行。

## 相关工作

- _Humbel et al. (SPIN '21)_ - 作者早先的 model-checked I2C stack 提出了分层思路；Efeu 把它推进到多设备拓扑和代码生成。
- _Ryzhyk et al. (SOSP '09)_ - Termite 面向单设备 driver synthesis；Efeu 则面向整条 shared bus。
- _Ortega and Borriello (ICCAD '98)_ - 早期 communication co-synthesis 能生成软硬件接口，但没有把 quirks 和互操作验证放进同一体系。
- _Pohjola et al. (PLOS '23)_ - Pancake 关注可验证 driver 的书写成本；Efeu 的不同之处在于它从一开始就处理多设备共享总线。

## 我的笔记

<!-- 留空；由人工补充 -->

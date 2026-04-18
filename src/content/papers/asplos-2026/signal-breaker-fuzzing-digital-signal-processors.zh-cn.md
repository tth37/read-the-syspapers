---
title: "Signal Breaker: Fuzzing Digital Signal Processors"
oneline: "SBFUZZ 把变异、执行和局部覆盖判断搬到 DSP 端，用自裁剪追踪避免每个测试样例都往返主机。"
authors:
  - "Cameron Santiago Garcia"
  - "Matthew Hicks"
affiliations:
  - "Virginia Tech, Blacksburg, Virginia, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790220"
code_url: "https://github.com/FoRTE-Research/SBFuzz"
tags:
  - fuzzing
  - security
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

SBFUZZ 的核心判断是：如果 DSP fuzzing 继续照搬面向更富设备的 host-centric embedded fuzzer 结构，就很难真正跑起来。它把变异、执行和逐测试样例的局部覆盖判断放到 DSP 上，只把崩溃恢复、全局语料维护和二进制重写这类低频重活留给主机。作者在 15 个 DSP benchmark 上报告 `17.4x` 吞吐提升、`2.6x` 覆盖提升，以及 `2491` 个崩溃输入对应的 `34` 个唯一 bug。

## 问题背景

这篇论文首先指出一个长期被忽视的错位：fuzzing 在桌面软件上已经非常成熟，在嵌入式设备上也开始有成体系的方法，但这些方法默认的目标并不是 DSP。已有 embedded fuzzers 往往假设目标有操作系统、有系统工具、能用高速链路和主机频繁交换 testcase 与 coverage bitmap。DSP 则恰好反过来：它常常是 bare metal，片上内存很小，对外只有低带宽的调试或控制接口。若仍沿用“每个输入都送到主机分析一次”的结构，系统绝大多数时间都会耗在协调与传输上。

这件事之所以重要，是因为 DSP 常处在安全和物理世界直接相连的链路里，而且它们的失败方式也不像普通进程退出那样规整。它可能跳进无效地址后一直自旋，可能触发 bus error，也可能在内部状态已经损坏的情况下继续跑。因此，论文把 DSP fuzzing 视为一个同时受三种约束支配的系统问题：内存极小、主机交互极贵、故障模式更像硬件而不是传统软件。

## 核心洞察

论文最关键的洞察是，DSP fuzzer 的职责划分不该按“开发方便”来做，而该按“事件出现频率”来做。凡是几乎每个测试样例都要做的事情，例如从局部 seed pool 里挑种子、做 mutation、执行 SUT、判断局部 coverage 是否增加，都应该留在 DSP 端。凡是低频但重量级的事情，例如保存 crash input、维护全局语料、重写 instrumentation，则应该放到主机端。只要这个分工成立，主机就不再处于普通 fuzzing 迭代的关键路径上。

第二个洞察是，经典 AFL 风格 coverage bitmap 对 DSP 来说是错误抽象。绝大多数输入并不新颖，为每个输入都物化并传输一整份覆盖信息，会同时浪费 RAM 和通信带宽。SBFUZZ 改为把当前 coverage frontier 直接编码进 instrumented binary 本身；一旦某个 basic block 已经被发现，主机之后就把对应 tracing call 改写成 `NOP`。这样，DSP 会随着 campaign 推进而逐步停止为“已知覆盖”付费。也正是这种会自我裁剪的追踪方式，让 DSP-centric 的整体架构真正可行。

## 设计

SBFUZZ 被拆成 host engine 和 DSP engine 两部分。主机保存 global seed pool、global coverage list、crashing input，以及一份 host 侧的 instrumented binary。DSP 只保存能塞进片上内存的 local pool，并在设备上运行一个永不退出的 fuzzing loop。周期性刷新 local pool 后，即便整个语料放不进板子，所有已知 seed 仍能随着时间轮流成为变异源。

在 DSP 端，mutation 被刻意设计得简单且廉价。系统沿用了 AFL 风格的 deterministic 与 random mutator，包括 bit/byte flip、算术增减、zeroing、插入与删除。论文还加入了 mutation digression：随着 fuzzing 继续推进，每次只扰动大约 `10%` 的 seed，因为作者观察到深层覆盖通常来自小幅扰动，而不是反复把输入整体打碎。一旦发现新的 coverage-increasing seed，mutation 的激进程度就会重置，重新扩大搜索半径。

执行模型更接近 persistent fuzzing，而不是每个输入都重新启动一次程序。DSP 会先保存寄存器上下文，然后在内部循环里反复调用 SUT，并在每次迭代后恢复寄存器状态，避免把残留机器状态误判成 crash。对于 crash 检测，SBFUZZ 使用 watchdog 风格的 timer，再配合硬件中断捕获 hang、bus error 和 data log error，然后跳转到主机可见的 handler，让主机取回输入并重新刷写板子。

最有辨识度的机制是 coverage tracing。作者在 assembly 层做 instrumentation，用很小的 trampoline call 记录 basic block 执行，而且记录的是相对 code segment 的 offset，而不是完整的 program counter 值。tracer 会保存并恢复完整寄存器状态，利用 C55x 的并行移动指令降低开销，并且避开不允许函数调用的 hardware loop 区域。当 DSP 报告一个 coverage-increasing input 后，主机会把局部 trace 合并进全局覆盖，并在自己的二进制副本里把对应 instrumentation 位置改写掉。以后若因 crash 重新刷机，host 与 board 上的 binary 仍保持一致，同时 tracing 开销会随着 campaign 持续下降。

## 实验评估

实验平台是 `100MHz` 的 TI `TMS320C5515`，每个 benchmark 跑 24 小时，每组做 5 次试验。作者使用了 15 个程序：其中 6 个来自 BDTImark2000 和 Embench DSP 1.0，另外 9 个是更复杂的 DSP 应用，覆盖 speech、image processing、biomedical、machine vision、sonar 和 telecommunications。作为参考基线，论文把 `uAFL`/`SHiFT` 风格的 embedded fuzzer 移植到同一平台，并刻意保持 seed selection 与 mutation 逻辑相近，从而把差异更多地收敛到职责划分和 tracing 策略上。

吞吐提升非常大，而且几乎是全局性的。SBFUZZ 在全部 15 个 benchmark 上平均达到基线的 `17.4x` 吞吐，在 `servo` 上最高达到 `1900x`，而在频繁崩溃、不得不不断回到主机协调的 `telecom` 上仍有 `1.3x` 提升。覆盖与 bug 发现也沿着同一方向改善：SBFUZZ 平均达到基线的 `2.6x` code coverage，在 15 个 benchmark 上的平均绝对覆盖率约为 `83%`，总共找到 `2491` 个崩溃输入，归并后对应 `34` 个唯一 bug。另一方面，instrumentation overhead 在这个场景里也是可接受的，平均二进制大小只增加 `7.0%`。

整体上，这组实验对论文主张的支持度是高的。参考实现对论文要回答的问题来说足够公平，结果也与作者声称的瓶颈基本对齐。真正的边界在于广度而不是内部有效性：所有实验都集中在一个 TI DSP 家族上，工作负载主要仍是 benchmark，而不是更大规模、更异构的生产固件。

## 创新性与影响

和 _Li et al. (ICSE '22)_ 相比，SBFUZZ 直接否定了“硬件辅助 embedded fuzzing 仍可承受逐输入 host-side 分析”这一前提。和 _Mera et al. (USENIX Security '24)_ 相比，它保留了 semi-hosted 思路，但把控制结构翻转过来，让 target 而不是 host 来执行常态路径上的 fuzzing 工作。和 _Nagy and Hicks (S&P '19)_ 相比，它把 commodity 系统里的 coverage-guided tracing 搬到了 bare-metal DSP 环境，并加入了设备端自裁剪 tracing 与 host 侧 binary coherence。

因此，这篇论文对两类人都很重要。一类是做 embedded security 的研究者，因为它给出了一套此前几乎空白目标类型的可操作 fuzzing 方法。另一类是 systems 与 architecture 研究者，因为它传达了一个更一般的经验：当目标位于硬件与软件边界时，正确的方案往往不是“把 AFL 移植过去”，而是围绕目标的内存层次、指令集和调试接口重新共设计整个运行时。

## 局限性

最明显的局限是覆盖范围。实现和评估都集中在一个 TI C55x 级别的 DSP 板卡、一套专有编译工具链，以及以 benchmark 为主的工作负载上，所以“能否迁移到其他 DSP 家族”更多还是被论证为合理，而不是被充分实证。系统还受限于 local seed pool 只能容纳 15 个输入，因为片上内存确实很紧，语料管理始终被硬件容量强约束。

还有一些复杂度只是被转移了位置，而没有真正消失。crash recovery 仍需要主机重新刷写和外部 power cycling，因此在高 crash 率 benchmark 上，SBFUZZ 的优势会被明显削弱。最后，论文停留在 DSP benchmark 上的 mutation-based fuzzing，没有进一步研究带复杂外围设备的生产固件，也没有整合 concolic 技术来处理后期路径探索停滞的问题。

## 相关工作

- _Li et al. (ICSE '22)_ — `uAFL` 依赖硬件 tracing 来 fuzz 微控制器固件，但它仍假设目标能承受每个输入一次的 host-visible trace 收集，这对低带宽 DSP 来说过于昂贵。
- _Mera et al. (USENIX Security '24)_ — SHiFT 是最接近的 semi-hosted 基线；SBFUZZ 的主要分歧是把 mutation 和逐测试样例的 coverage 判断放回设备端，而不是每轮都和主机协同。
- _Nagy and Hicks (S&P '19)_ — Full-Speed Fuzzing 在 commodity binary 上提出 coverage-guided tracing，而 SBFUZZ 把这个思路改造成会自裁剪的 DSP instrumentation。
- _Trippel et al. (USENIX Security '22)_ — Fuzzing Hardware Like Software 启发了 SBFUZZ 对持续执行目标的理解，但 SBFUZZ 只 instrument DSP SUT 本身，而不是动态发现目标区域。

## 我的笔记

<!-- 留空；由人工补充 -->

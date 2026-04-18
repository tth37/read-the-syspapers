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

SBFUZZ 把 DSP fuzzing 当成一个职责划分问题，而不只是把现有 embedded fuzzer 搬过去。它把变异、执行和局部覆盖判断放到 DSP 端，把 crash 恢复、全局语料维护和二进制重写留给主机。作者在 15 个 DSP benchmark 上报告 `17.4x` 吞吐提升、`2.6x` 覆盖提升，以及 `2491` 个崩溃输入对应的 `34` 个唯一 bug。

## 问题背景

论文指出，现有 embedded fuzzers 与 DSP 之间有根本错位。像 `uAFL`、`SHiFT` 这样的系统默认目标设备能在每次执行后把 testcase 和 coverage 报告发回主机，再由主机决定下一步。这个模式对更富的 embedded board 还成立，但 DSP 往往是 bare metal Type-3 设备：内存很小、带外接口带宽低、几乎没有系统软件可借力，而且很多时候连可用的公开 emulator 都没有。把它们强行塞进 host-centric 循环里，协调成本很快就会压过真正的 fuzzing 工作。而且 DSP 常处在通信、医疗、交通等 cyber-physical 链路中，失败时更像死循环、bus error，或“已经偏离正确行为却继续跑下去”的执行，而不是干净的进程退出。

## 核心洞察

最重要的洞察是，fuzzer 的职责应该按“发生频率”划分，而不是按“开发方便”划分。几乎每个输入都会做的工作，例如从本地 seed pool 取种子、做 mutation、执行 SUT、判断局部 coverage 是否增长，都应放在 DSP 端；低频但较重的工作，例如保存 crash、合并全局 coverage、刷新种子池、重写 instrumented binary，则交给主机。这样主机就能退出 steady-state fuzzing 的关键路径。

第二个洞察是，AFL 风格的完整 coverage bitmap 对 DSP 来说过于昂贵。大多数 testcase 并不会带来新覆盖，因此每次都生成并传输整份 bitmap 只是在消耗 RAM 和带宽。SBFUZZ 改用论文所说的 dynamic coverage-guided tracing：只记录紧凑的代码 offset，只在少数真正有意思的执行上报信息，并把已经发现的 tracing 点逐步改写成 `NOP`，使 tracing 成本随着 campaign 推进而下降。

## 设计

SBFUZZ 由 host engine 和 DSP engine 组成。主机保存 global seed pool、global coverage list、crashing input，以及一份与设备保持一致的 instrumented binary；DSP 只保留能放进片上内存的 local pool，并执行一个不会退出的 fuzzing loop。主机会周期性刷新这个 local pool，而不是把整个 corpus 都塞到板上。

在主循环里，DSP 负责 AFL 风格的 deterministic 与 random mutation。论文还加入 mutation digression：对同一个 seed 连续变异多轮后，只改动它大约 `10%`，因为作者认为更深层覆盖往往来自小幅扰动。执行模型采用 persistent fuzzing，DSP 会保存寄存器上下文并在每轮后恢复状态，避免残留机器状态制造假阳性 crash。

crash 处理直接利用硬件行为：timer 识别 hang，硬件中断捕获 bus error 和 data log error，主机可见的 breakpoint 则负责把崩溃事件暴露出来，方便主机取回输入并重新刷写或重启板子。最关键的 dynamic coverage-guided tracing 则在 assembly 层插入轻量 trampoline call，记录 basic block offset 而不是完整 PC。主机一旦收到 coverage 增长事件，就把对应 tracing 点改写成 `NOP`，既维持 host-device binary coherence，也持续降低 tracing 开销。

主机与 DSP 的协作不是靠持续轮询，而是靠三个 hardware breakpoint 形成的事件点：pool refresh、crash handler 和 coverage-increasing handler。这个细节很重要，因为它把主机变成 event-driven 的协调者。steady state 下，DSP 可以一直在本地变异并执行，主机只在少数事件发生时介入，论文也因此声称单个主机可以同时服务多个目标设备。

## 实验评估

实验平台是 `100MHz` 的 TI `TMS320C5515`，每个 benchmark 运行 24 小时，每组做 5 次试验。工作负载共 15 个程序，其中 6 个来自 BDTImark2000 和 Embench DSP 1.0，另外 9 个是更复杂的 DSP 应用。作为对照，作者把 `uAFL`/`SHiFT` 风格的 embedded fuzzer 直接移植到同一块 DSP 上，并尽量保持 seed selection 与 mutation 一致，使比较重点落在职责划分和 tracing 策略上。

结果与论文的瓶颈分析高度一致。SBFUZZ 的平均吞吐是基线的 `17.4x`，在 `servo` 上最高达到 `1900x`，而频繁崩溃的 `telecom` 上最小也还有 `1.3x`。覆盖率平均提升 `2.6x`，平均绝对覆盖约为 `83%`。作者还报告了 `2491` 个崩溃输入，人工归并后对应 `34` 个唯一 bug，而 instrumentation 开销平均只让二进制增大 `7.0%`；按论文的说法，这比传统 desktop 风格 instrumentation overhead 低了约 `28x`。对核心论点来说，这组实验是有说服力的；它的问题不在机制是否成立，而在可移植性还没有被更广泛地证明。

## 创新性与影响

和 _Li et al. (ICSE '22)_、_Mera et al. (USENIX Security '24)_ 相比，这篇论文真正的新意不在于“把 embedded fuzzing 跑到硬件上”，而在于它拒绝沿用标准的 host-centric 分工，并证明 DSP-centric steady state 才是关键。和 _Nagy and Hicks (S&P '19)_ 相比，它把 coverage-guided tracing 带进了 bare-metal DSP 环境，并把 tracing 做成紧凑、可动态删除的机制。

它的影响也不只限于 DSP。对 security 社区来说，这是长期被忽略设备类别的一套较完整 fuzzing 路线图。对 systems 研究者来说，它说明：当通信代价高、目标执行语义又特殊时，性能优势往往来自把常态路径压到设备端，把主机留给少数协调事件。

## 局限性

最大局限是可移植性。实现绑定在一个 TI C55x 级 DSP、一套闭源编译器、特定的 JTAG/debug 工作流和对应汇编环境上。论文也声称支持 emulated target，但评估全部基于真实硬件。

另外，工作负载和方法也有边界。DSP 一次只能容纳 15 个本地 seed，crash recovery 仍需要主机重新刷写或 power cycle，评估对象主要是 benchmark 而不是大型生产固件。论文也停留在 mutation-based fuzzing，没有继续探索更强的 seed scheduling 或 concolic 扩展。

## 相关工作

- _Li et al. (ICSE '22)_ — `uAFL` 证明了硬件 tracing 可以用于微控制器固件 fuzzing，但它仍依赖逐输入的主机侧 trace 处理，这对 DSP 链路太昂贵。
- _Mera et al. (USENIX Security '24)_ — SHiFT 是最接近的 semi-hosted 基线；SBFUZZ 的关键差别是把 mutation 与局部 coverage 判断放回设备端，而不是每轮都同步主机。
- _Nagy and Hicks (S&P '19)_ — Full-Speed Fuzzing 提出了 commodity binary 上的 coverage-guided tracing，而 SBFUZZ 把它改造成紧凑且会自裁剪的 DSP instrumentation。
- _Trippel et al. (USENIX Security '22)_ — Fuzzing Hardware Like Software 提醒人们持续运行目标需要不同处理方式，但 SBFUZZ 假设 DSP SUT 已知，并在汇编层直接对它做 instrumentation。

## 我的笔记

<!-- 留空；由人工补充 -->

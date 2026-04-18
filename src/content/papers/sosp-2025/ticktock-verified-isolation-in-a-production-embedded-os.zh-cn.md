---
title: "TickTock: Verified Isolation in a Production Embedded OS"
oneline: "TickTock 用经 Flux 验证的细粒度 MPU 抽象取代 Tock 的单体设计，让内核逻辑布局与硬件强制布局一致，并证明嵌入式进程隔离。"
authors:
  - "Vivien Rindisbacher"
  - "Evan Johnson"
  - "Nico Lehmann"
  - "Tyler Potyondy"
  - "Pat Pannuto"
  - "Stefan Savage"
  - "Deian Stefan"
  - "Ranjit Jhala"
affiliations:
  - "UCSD"
  - "NYU"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764856"
tags:
  - kernel
  - security
  - verification
  - isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

TickTock 是 Tock 的一个 verification-guided 分支，它在所有 Tock 支持的 ARMv7-M 平台和三个 32-bit RISC-V 平台上证明了：每个进程只能访问自己的代码与 RAM。它的关键招式是把 Tock 原先单体化的 MPU 抽象拆成细粒度接口，让内核记录的逻辑内存布局与硬件真正执行的布局保持一致，然后再用 Flux 验证内核、MPU driver 和 ARM 中断路径。整个过程中，作者在原始 Tock 中找出了 7 个 bug，其中 6 个会直接破坏隔离。

## 问题背景

Tock 已经部署在 Google Security Chip、Microsoft Pluton 2 这类安全关键系统里，所以它的进程隔离不是“锦上添花”，而是根安全属性。若恶意应用能读写 kernel memory，就可能窃取密钥、让设备变砖，甚至直接接管整个 OS。Rust 只能解决一部分问题：它能把 kernel 内部组件彼此隔离，并消掉很多 confused-deputy 风格的错误；但 Tock 的应用可以用任意语言编写，包括 C/C++ 这样的 memory-unsafe 语言，而且 Tock 面向的微控制器并没有 MMU。

因此，Tock 必须依赖 MPU 或 RISC-V PMP 来隔离用户进程。难点在于，这类硬件并不好编程。ARM Cortex-M 的 region 有 power-of-two 大小限制、对齐限制、subregion 机制，还要在每个进程切换时动态重配。内核同时还得在 interrupt 和 context switch 中保证 privileged / unprivileged mode 切换正确。最自然的工程做法，是用一个高级抽象把这些硬件细节“藏起来”；但论文表明，这恰恰是 Tock 出问题的根源：原始抽象把逻辑上的进程内存布局和底层 MPU 约束缠在一起，迫使内核反复重算边界，并让“内核以为的可访问内存”和“硬件实际上允许访问的内存”出现偏差。

论文给出的 bug 说明了后果有多严重。一个 bug 会让进程可访问的 subregion 与 kernel-owned grant memory 重叠；另一个 bug 在跳转到进程时漏掉了 ARM mode switch，使应用代码仍以 privileged 模式运行，从而绕过 MPU；还有一个 bug 则让 `update_app_mem_region` 中的整数下溢把畸形 `brk` 输入变成 kernel crash。于是，真正的问题不只是“给 Tock 加证明”，而是要先把进程抽象改造成更适合表达和验证隔离的不变量。

## 核心洞察

论文的核心洞察是：只有当内核不再假装可以用一个单体接口把 MPU 约束完全隐藏起来时，process isolation 的自动化验证才真正变得可行。正确的做法，是让硬件层直接返回已经满足对齐和大小约束的 region，再由内核记录这些 region 实际蕴含的可访问边界。

这个变化同时解决了两个根本问题。第一，它去掉了 entanglement：process allocator 不必再自己推理 subregion、power-of-two rounding 和寄存器编码。第二，它去掉了 disagreement：内核保存的 `app_break`、`kernel_break` 和进程内存范围，都来自同一套 region descriptor，而不是事后凭启发式公式重算。只要这些精确边界被显式记录下来，Flux 就能分层证明内核逻辑状态、不依赖具体架构的 region 抽象，以及汇编级 interrupt path 之间的一致性。六个月后最值得记住的一句话是：让验证变容易的，不只是“用了 Flux”，而是先选对了 abstraction boundary。

## 设计

TickTock 用一个更细粒度的接口替换了 Tock 原来的 `allocate_app_mem_region` / `update_app_mem_region` 风格抽象。新的设计把职责分成 `RegionDescriptor` 和更窄的 `MPU` trait。`RegionDescriptor` 只描述一个受硬件强制的 region 的抽象性质，例如 start、size、是否 overlap、是否启用等，同时隐藏 ARM subregion 或 RISC-V PMP 布局这类架构细节。`MPU` trait 则只暴露 `new_regions`、`update_regions`、`configure_mpu` 之类操作，专门负责创建或重配满足硬件约束的 region。

内核侧的 process allocator 因而可以写成对这些抽象泛型的通用代码。分配进程 RAM 时，allocator 向 MPU 层请求最多两个连续 region，它们至少覆盖应用所需的 process memory。拿到 region 后，内核再从 descriptor 中读出硬件真正强制的起始地址和大小，并把它们保存进 `AppBreaks`。`AppBreaks` 记录的是隔离真正关心的边界：process memory 起点、总大小、进程可访问内存的结束位置 `app_break`，以及 kernel-owned grant memory 的起点 `kernel_break`。Flux 在这里写下的关键不变量之一就是 `app_break < kernel_break`，从而静态排除用户内存与 grant memory 重叠。

证明是分层推进的。第一层，为 `RegionDescriptor` 增加抽象 refinement，例如 `start`、`size`、`matches`、`can_access`。第二层，验证内核保存的逻辑内存布局满足 Tock 的进程内存模型。第三层，证明保存下来的 region 数组与 `AppBreaks` 完全对应：flash 只有 read-execute，process RAM 只有 read-write，其他内存不可访问。最后，再分别验证 ARMv7-M 和 RISC-V 的 MPU driver，证明寄存器内容确实实现了这些抽象语义。

ARMv7-M 的 interrupt 另外由 `FluxArm` 处理。作者把相关 ISA 子集写成 Rust 可执行语义，建模 inline assembly handler、mode switch、栈保存/恢复和 exception return，再证明进程被抢占后，机器会带着正确的寄存器与 MPU 假设回到 privileged kernel state。这一步很关键，因为他们在原始 Tock 中发现的一个真实漏洞，正是 context-switch 汇编里漏掉了 mode switch。

## 实验评估

这篇论文的评估重点不是追求极致性能，而是说明“可部署、可验证、开销可接受”，这个取向是合理的。首先，作者对 21 个上游 Tock 应用做了 differential testing。ARM 侧使用 nRF52840dk 板卡，RISC-V 侧使用 QEMU。TickTock 和 Tock 都能跑完这些程序，出现差异的 5 个输出也都符合预期，因为那些测试本来就在观察 memory layout 或 sensor 输出。对这类验证式系统论文而言，这已经是相当扎实的兼容性证据。

ARM 上的运行时代价也相当克制。`setup_mpu` 大约慢 `8.08%`，这是最明显的 regression。但若干路径反而更快，因为 TickTock 不再重复推导 MPU 已经隐含的布局信息：`allocate_grant` 提升 `50.32%`，`brk` 提升 `21.71%`，`build_readonly_buffer` 提升 `20.00%`，`build_readwrite_buffer` 提升 `34.02%`。应用级 context switch 几乎不变：上游 Tock 平均 `32,640` cycles，TickTock 是 `32,740` cycles，只有约 `0.3%` 的开销。

更重要的结果其实是 verification time。细粒度重设计把 kernel 部分的验证时间从单体设计下的 `5m19s` 降到 `36s`，大多数 kernel 函数不到一秒即可检查完成，平均每个函数只要 `0.05s`。Interrupt proof 仍然昂贵，需要 `2m34s`，但整个项目仍能在三分钟以内验证完。论文报告总共约 `22 KLOC` Rust 代码配 `3.6 KLOC` 已检查的规格与注解。这个结果强有力地支撑了论文的核心论点：新的设计不只是“更优雅”，而是显著更容易被自动验证。

## 创新性与影响

这篇论文的创新点并不是泛泛而谈的“Rust 加证明”，而是把 verification-guided redesign 和 production embedded OS 上的 end-to-end isolation argument 结合在一起。许多已验证系统要么从一开始就为证明而设计，要么聚焦 hypervisor 和 microkernel；TickTock 则是在一个已经存在、已经部署、带有真实硬件约束和 inline assembly 热路径的 MCU OS 上，回过头来补上 machine-checked process isolation。

这使它的意义超出了 Tock 本身。论文说明，Rust 的基础安全性不足以覆盖 privilege transition、MPU 编程和整数边界条件，但这些危险区并不一定只能靠人工 code review 兜底；如果 abstraction boundary 选得对，自动验证可以真正进入 production workflow。对嵌入式 OS、firmware 安全和 Rust systems verification 社区来说，这都是一篇很可能被反复引用的“方法论型”论文。

## 局限性

TickTock 证明的是 process isolation，而不是完整功能正确性。它不覆盖 liveness、fairness、side channel，也不证明更广泛的 capsule 生态都正确。Interrupt 证明也主要是 ARMv7-M 路径；论文验证了 RISC-V 的 MPU driver，但没有给出对等的 RISC-V interrupt proof。

它的 trusted base 也并不小。实现里仍有一批 trusted function，用来绕过 solver 限制、承载 proof scaffolding 或处理明确不在范围内的辅助逻辑；ARM 和 RISC-V 的硬件语义是从架构手册 lift 进来的，而不是在 Flux 内部再次证明；某些算术引理还要借助 Lean，因为 SMT solver 在位运算与对齐事实上的推理会超时。所以这份结果很强，但它不是 seL4 式的最小 TCB 证明。

经验评估的覆盖面同样有限。性能数据只在 ARM 上测量，应用测试也只是 21 个程序的 differential sanity check，而不是大规模部署工作负载或强对抗场景。论文令人信服地证明了“这套方案可行且成本不高”，但并没有穷尽 Tock 在真实世界中的所有失败模式。

## 相关工作

- _Levy et al. (SOSP '17)_ - Tock 最初展示了如何在超小设备上用 MPU 做安全多程序执行；TickTock 则把这套 process abstraction 做成可机器检查的版本。
- _Mai et al. (ASPLOS '13)_ - ExpressOS 用 Dafny 验证一个新设计的 C# kernel 的安全不变量，而 TickTock 是把验证补到一个既有的 Rust embedded OS 上。
- _Li et al. (USENIX Security '21)_ - SeKVM 为 commodity hypervisor 验证 memory protection；TickTock 把类似的 machine-checked isolation reasoning 带到基于 MPU 的微控制器进程隔离。
- _Johnson et al. (S&P '23)_ - WaVe 验证的是 Rust 实现的 WebAssembly sandbox runtime，而 TickTock 验证的是 bare-metal OS 里的 kernel、MPU 和 interrupt machinery。

## 我的笔记

<!-- 留空；由人工补充 -->

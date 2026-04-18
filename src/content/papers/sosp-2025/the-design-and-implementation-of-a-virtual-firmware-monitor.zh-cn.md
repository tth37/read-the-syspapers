---
title: "The Design and Implementation of a Virtual Firmware Monitor"
oneline: "Miralis 把未修改的 RISC-V vendor firmware 放进用户态的 virtual M-mode，拦截特权操作，把 firmware 从 TEE 的 trusted base 中移走，同时不拖慢原生 OS 执行。"
authors:
  - "Charly Castes"
  - "François Costa"
  - "Neelu S. Kalani"
  - "Timothy Roscoe"
  - "Nate Foster"
  - "Thomas Bourgeat"
  - "Edouard Bugnion"
affiliations:
  - "EPFL, Switzerland"
  - "ETH Zurich, Switzerland"
  - "Cornell and Jane Street, USA"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764826"
tags:
  - virtualization
  - security
  - confidential-computing
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文指出，vendor firmware 不必继续和 security monitor 共享 CPU 的最高特权级。Miralis 是一个面向 RISC-V 的 virtual firmware monitor，它把未修改的 firmware 运行在用户态的 virtual M-mode 中，拦截特权操作，并通过少量 fast path 在不牺牲原生 OS 性能的前提下保护 OS、enclave 和 confidential VM。

## 问题背景

现代 TEE 依赖一个很小的 security monitor 来保护 enclave 或 confidential VM，不受不可信 OS 或 hypervisor 的影响，但在真实机器上，这个 monitor 往往与 vendor firmware 共处于应用 CPU 的最高特权级。结果是，firmware 也被迫进入 TCB；可 firmware 往往体量大、强平台相关、常常闭源，而且安全漏洞层出不穷。对 RISC-V 来说，Keystone 一类系统把 security monitor 和 firmware 一起放在 M-mode；对 Arm 来说，额外的 privilege level 虽然在结构上分开了组件，但 security monitor 仍然必须信任更高权限的 firmware。least-privilege 的故事在最后一层断掉了。

直接把 firmware 本身做 privilege separation 并不容易落地。Dorami 证明了在 RISC-V 上这样做是可能的，但它要求对 firmware 做重构，并对每个平台进行 binary scanning。于是作者把问题收紧成一个更实际的版本：如果 firmware binary 是 opaque 且不可修改，系统运营者还能不能把它 sandbox 起来？而且，做完这件事之后，正常 OS 路径还能不能保持接近原生的性能？

## 核心洞察

论文最核心的洞察是，最高特权模式本身也可以像传统 kernel 一样被虚拟化，只要 ISA 满足经典的 Popek-Goldberg trap-and-emulate 条件。RISC-V 的 M-mode 满足这一点：敏感操作会 trap，因此 firmware 可以在 U-mode 中作为 virtual M-mode 运行，而 Miralis 负责模拟 privileged instruction、CSR、interrupt 和 machine resource。

这个判断的价值在于它把两个问题彻底拆开了。Miralis 只需要统一处理“如何虚拟化 firmware”这一层；更高层的隔离需求则通过 policy module 插件化实现。这样，系统既不需要硬件改动，也不需要修改 firmware binary，更不需要为每个 TEE monitor 和每个平台分别重写一套底层机制。

## 设计

Miralis 是一个 6.2 KLoC 的 Rust monitor，运行在 M-mode，且关闭中断。每个 hart 始终处于两个 world 之一：一种是 native OS 的 direct execution，另一种是给 virtualized firmware 使用的 vM-mode。来自 vM-mode 的 trap 会进入 instruction emulator 和设备/内存模拟路径；来自 OS 的 trap 则要么被 Miralis 直接处理，要么被重新注入给 firmware。论文中的 emulator 支持 12 条 privileged instruction 和 84 个 CSR，通过 shadow CSR state 维护 virtual 状态，再在 world switch 时保存物理状态、安装正确的 CSR 视图、调整权限、刷新 TLB，并恢复到另一个 world。

内存保护围绕 PMP virtualization 展开。Miralis 复用物理 PMP entries：一部分始终保护 Miralis 自身和 virtual device，剩余部分暴露给 firmware 作为 virtual PMP 接口。它还补上了几个容易出错的架构语义细节，例如 M-mode 默认可访问全内存、ToR 模式对地址 0 的隐式下界，以及 `mstatus.MPRV`。对于 `MPRV`，Miralis 的做法是让数据访问 trap，再代表 firmware 完成读写。设备侧则尽量避免完整设备虚拟化：它强制委派非 M-mode interrupt，模拟 CLINT 来处理 timer/IPI，并在没有 IOPMP 时通过禁止 firmware 访问 DMA 相关 MMIO 来降低风险。

这套设计之所以能跑得动，是因为当前 RISC-V 平台里“固件调用的热点”高度集中。论文测得，VisionFive 2 在 Linux boot 期间 99.98% 的 firmware trap 都来自五类原因，基本都是对可选架构特性的 software emulation。Miralis 因此加入了一个很小的 fast path，直接处理这些常见 SBI 风格操作，特别是读时间和 timer/IPI，而不是每次都跳入 virtualized firmware。除此之外，Miralis 还暴露了七个 policy hook，并实现了三个示例策略：保护 OS 的 firmware sandbox、移植自 Keystone 的 enclave monitor，以及移植自 ACE 的 confidential-VM monitor。

论文还把“规格”本身纳入系统设计。作者提出 faithful emulation 与 faithful execution 两个准则，把 VFM 行为与 ISA 的权威语义绑定起来；然后把 RISC-V Sail model 翻译成 Rust，再用 Kani 对 Miralis 的关键路径做穷尽式符号执行校验。

## 实验评估

实验对主张的支撑是充分的。Miralis 在两块商用开发板上虚拟化了未修改的 vendor firmware：StarFive VisionFive 2 和 SiFive HiFive Premier P550。做法是在第一阶段和第二阶段 firmware 之间插入 Miralis。作者还进一步虚拟化了 RustSBI、Zephyr，甚至把 Star64 上从 flash 提取出的闭源 firmware image 跑在 Miralis 上。这直接说明它的可移植性并不依赖某一个开源 firmware 栈。

性能结果显示，只要把常见 firmware 操作 offload 到 fast path，OS 路径几乎保持原生。模拟一条 privileged instruction 在 VisionFive 2 和 Premier P550 上分别需要 483 和 271 cycles；一次 world-switch round trip 分别需要 2704 和 4098 cycles，但这种切换会变得非常稀少。启用 fast path 后，Miralis 把 boot 期间与 firmware 的交互从大约 5500 traps/s 降到约 1.17 次/s，并在 CoreMark-Pro、IOzone、Memcached、Redis、MySQL、GCC 和 boot time 上都报告了几乎没有可测开销。有些场景里 Miralis 甚至略快于 native firmware，因为它自己的 fast path 比 vendor 实现更高效。

反过来说，论文也诚实地展示了当前硬件的短板：现在还离不开这个 fast path。关闭 offloading 后，在 VisionFive 2 上，读时间从 208 ns 上升到 7.26 us，IPI 从 3.65 us 上升到 39.8 us；boot time 最多增加 29%，网络型 workload 也会明显变慢。也就是说，机制本身成立，但今天的 RISC-V 平台仍然把一些本该由硬件扩展承担的工作留给 firmware 处理，比如 Sstc 相关路径。形式化部分也不是装饰品：验证覆盖了 2.7 KLoC，也就是 Miralis 的 43%，并在开发过程中找出了 21 个 bug。

## 创新性与影响

这篇论文最大的创新，首先是概念层面的。Miralis 把 VFM 定义成位于 TEE 之下的一层新系统软件：它不是再造一个假设 firmware 可信的 enclave/CVM monitor，而是先把 firmware 自身虚拟化，再把 security monitor 变成运行在其上的 policy module。相对 Dorami，它在不修改 firmware、不做 binary scanning 的前提下实现 privilege separation；相对现有 TEE monitor，它把 vendor firmware 从 TCB 里拿掉，同时保留原有的高层抽象。

这让它同时对两类研究者有吸引力。对 TEE 设计者来说，它给出了一个能在现有 RISC-V 硬件上落地、减少对 opaque firmware 信任的方案。对 verification 和 architecture 研究者来说，它展示了一种从权威 ISA model 自动导出 VFM 校验条件的方法，而不是手写第二份规格。论文提出的 O(N + M) 可移植性论证也有说服力：一旦 VFM 负责平台虚拟化，多种 monitor 就可以共享这层 substrate。

## 局限性

最大的局限首先来自架构范围。论文之所以讲得这么干净，是因为 RISC-V 的 M-mode 满足 classical virtualization 条件；Arm 的 EL3 不满足，因此同样的方案需要 paravirtualization 或 ISA 改动。即使在 RISC-V 上，这个系统也依赖平台相关 CSR 和 MMIO 区域被准确文档化。如果 vendor 留下了未公开的控制路径或隐藏副作用，policy enforcement 就可能被绕过。

安全性也还不是端到端“证明完毕”的状态。被验证的部分已经很关键，但仍只覆盖总代码的一部分；其余 assembly、device emulation 和 fast path 仍在 TCB 中。sandbox 和 Keystone policy 没有做形式化验证；DMA 保护只有在存在 IOPMP 一类机制时才最强。threat model 也明确排除了物理攻击、拒绝服务和 transient-execution side channel。最后，ACE 只在 QEMU 上展示兼容性，更多证明的是“能接上”，而不是“在真实硬件上性能如何”。

## 相关工作

- _Lee et al. (EuroSys '20)_ — Keystone 保护 enclave 免受不可信 OS 影响，但原始设计仍让 firmware 与 monitor 共处 M-mode；Miralis 则把 Keystone 作为 policy 移植上来，并把 firmware 移出 TCB。
- _Ferraiuolo et al. (SOSP '17)_ — Komodo 用验证来缩小 enclave 的 TCB，而 Miralis 进一步把目标下探到这些 monitor 通常默认可信的 privileged firmware 层。
- _Li et al. (OSDI '22)_ — Arm Confidential Compute Architecture 依赖 ISA 支持来隔离 confidential VM；Miralis 则展示了在现有 RISC-V 平台上，仅用软件就能把 firmware 去特权化，从而实现类似的信任收缩。
- _Ozga et al. (HASP '23)_ — ACE 提供面向 confidential VM 的 security monitor；Miralis 把 ACE 承载为一个 policy module，并在其下方再增加一层 firmware isolation。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "Tock: From Research to Securing 10 Million Computers"
oneline: "Tock 把 Rust 类型系统、capsules、grants 和重设计的 syscall ABI 组合成一套可部署的安全嵌入式 OS，并已保护数千万台设备。"
authors:
  - "Leon Schuermann"
  - "Brad Campbell"
  - "Branden Ghena"
  - "Philip Levis"
  - "Amit Levy"
  - "Pat Pannuto"
affiliations:
  - "Princeton University"
  - "University of Virginia"
  - "Northwestern University"
  - "Stanford University"
  - "University of California, San Diego"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764828"
tags:
  - kernel
  - security
  - isolation
  - pl-systems
category: embedded-os-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这是一篇跨越十年的系统经验总结，回顾了 Rust 编写的安全嵌入式 OS Tock 如何从面向传感器网络的研究平台，演化成部署在数千万台设备上的生产级固件。论文最重要的结论是：Rust 的确让小设备上的隔离与最小权限设计变得现实，但前提是内核 ABI、syscall 语义和内部结构必须围绕 Rust 的 ownership 与 soundness 约束来重构，而不是把传统 C 内核直接翻译成 Rust。

## 问题背景

Tock 最初面对的是一个很苛刻的硬件区间：大约 100 kB RAM、没有 virtual memory、只有原始 memory protection、外设很多、同时还受到严格能耗约束的微控制器。像 Signpost 这样的早期部署希望在同一块板子上运行多个并发应用，支持不同硬件配置，并在应用或驱动出错时仍然维持健壮性。传统 embedded OS 往往把所有组件都放在单一 protection domain 中，驱动接口是临时拼出来的，也缺少机制去阻止某个组件破坏共享内核状态或耗尽公共内存。

当 Tock 从城市传感转向 hardware root of trust 时，问题的严重性进一步上升。这类芯片要保存密钥、验证 boot image，并且处在 laptop、server 和 security token 等系统安全链条的最底层。论文真正讨论的，因此不是“Rust 能不能写一个 embedded kernel”，而是一个研究 OS 如何在不丢掉 soundness、可部署性与可扩展性的前提下，演化成生产级安全固件。

## 核心洞察

论文的核心命题是：Rust 只有在操作系统架构主动顺应语言语义时，才会真正成为系统优势。Tock 能长期保留下来的机制，都把 privilege 或 ownership 变成了显式结构。capsules 禁止使用 `unsafe`，用类型系统隔离大多数 kernel extensions；grants 把每个进程相关的内核状态放进该进程自己的受保护内存；capabilities 把敏感 API 变成零运行时开销的类型化权限。这些设计让 Tock 在缺乏重量级隔离资源的小硬件上，依然能维持强边界。

反过来，凡是把 Rust 当作“更安全的 C”来用的地方，最后都暴露出 soundness 问题。比如异步 syscall 允许 capsules 不透明地持有 userspace 引用，`allow` 可能制造 mutably aliased buffers，零长度 buffer 的 null pointer 也会违反 Rust 的类型不变量。论文最有价值的地方，是把这些失败经验提炼成一个清晰判断：生产部署并没有推翻 Tock 的研究方向，而是逼迫它把 ownership、aliasing 和 lifetime 规则直接提升到 ABI 层面。

## 设计

Tock 把系统分成 hardware-isolated 的 userspace processes、一小块特权 kernel core 与 chip-specific 代码，以及半可信的 kernel extensions，也就是 capsules。capsules 是普通 Rust crates，但明确禁止 `unsafe`，因此它们只能访问自己的状态以及初始化时交给它们的安全接口。为了让单栈、异步、callback 驱动的内核在 Rust 中成立，Tock 采用 interior mutability 处理组件间的循环引用；代价是需要额外运行时检查，并谨慎处理 reentrancy。

原始设计里还有两个对可依赖性至关重要的选择。第一，内核是 heapless 的：所有和进程相关、需要动态分配的状态，都通过 grants 放进该进程自己的受保护内存区域，所以一个进程最多耗尽自己的内存。第二，kernel 和 syscall ABI 都是完全异步的，这在早期低功耗传感节点场景里很合理。

真正大的重构来自 root-of-trust 场景。为了支持 sound 的 Rust userland，Tock v2.0 把 `allow` 和 `subscribe` 改成 swapping semantics，让共享的 buffer 或 callback 由 kernel 持有，而不是交给 capsule 私自保存；系统还加入了 `allow-readonly`，以支持放在只读 flash 中的 public key。随后，按应用独立签名与更新的需求，又把 process loading 变成一个异步状态机，依次检查结构完整性、真实性与可运行性。论文还总结了几类随着项目成熟而出现的 Rust 技巧：用类型在编译期验证 driver composition、用 `SubSlice` 解决 split-phase buffers、用 DSL 生成 typed MMIO 抽象，以及用 compile-time capabilities 保护敏感内核接口。

## 实验评估

这篇论文不是传统 benchmark 论文，它的“评估”主要来自长期部署与设计演化证据。最强的结果就是部署本身：Tock 从 Signpost 研究平台，走向 Google 的 OpenSK 与 Ti50，再进入 server roots of trust、secure laptop boot、automotive 和 space systems；论文明确说它现在已经保护了数千万台计算机。论文要证明的不是某条 fast path 更快，而是哪些设计真的经得起真实产品环境。

几组案例也足够具体。Oxide 曾尝试把 Tock 用在 BMC 上，但认为异步 userland 模型不适合其固定且顺序化的服务集合，于是转而编写 Hubris。Ti50 则因为异步 syscall 序列在其 RISC-V 平台上带来明显 code size 压力，而较早分叉。相反，安全场景的真实需求也反过来塑造了主线 Tock，例如 signed process loading 和 v2.0 syscall 重设计。论文唯一较明确的量化趋势来自 Figure 5：2018 到 2024 年间，内核规模显著增长，但 `unsafe` blocks 的数量大体保持平稳。缺失之处同样明显：论文没有对 Zephyr、NuttX 或 Hubris 做受控性能、内存或安全性对比。

## 创新性与影响

相对 _Levy et al. (SOSP '17)_ 的原始 Tock 论文，这篇工作解释了哪些研究想法真正跨过了“原型到产品”的门槛，以及哪些地方必须重写。相对 RedLeaf、Theseus 这类 Rust OS 工作，它的独特性在于问题设定更脏也更真实：Tock 必须在 mixed-language、security-critical、hardware-isolated 的场景里，把 Rust 的保证跨越 hostile process boundary 维持下去。

这让论文的价值超出了 embedded systems。它总结出一组可复用的 Rust 低层系统设计模式：禁止 `unsafe` 的 capsules、grants、swapping syscalls、`SubSlice`、typed MMIO 描述以及 capability 风格权限控制。更重要的是，它还给出一个组织层面的判断：研究 OS 可以同时成为生产系统与后续安全、验证工作的研究平台，只要项目能挺过长期工程维护阶段。

## 局限性

这篇论文本质上是由长期维护者撰写的 retrospective，因此很多证据天然是定性的、带有自我报告色彩的。它很清楚地说明了真实部署如何改变设计，但并没有严格分离 Rust 本身的贡献，与硬件内存保护、项目治理方式、或 root-of-trust 芯片特殊需求之间的作用差异。若读者期待广泛的 embedded-kernel benchmark 或严格控制实验，这篇论文并不提供。

一些技术张力也仍未解决。作者明确承认，异步 userland 对很多顺序型应用依然别扭；怎样安全地集成第三方库依旧是开放问题；而 timer virtualization 与 memory protection 这类复杂子系统中的逻辑 bug，并不会因为 Rust 而自动消失。工业使用者仍可能选择 fork 而不是 upstream，因此这些经验最直接适用的对象仍是小型、强调安全的 MCU，而不是通用操作系统内核。

## 相关工作

- _Levy et al. (SOSP '17)_ — 原始 Tock 论文提出了在 64 kB 级设备上安全 multiprogramming 的设计；SOSP 2025 这篇则解释哪些设计在真实部署中保留下来，哪些必须被重构。
- _Narayanan et al. (OSDI '20)_ — RedLeaf 同样研究 safe OS 中的隔离与通信，但它更像 Rust OS 架构探索，而不是一个嵌入式 root-of-trust 内核十年部署经验的总结。
- _Boos et al. (OSDI '20)_ — Theseus 更进一步假设系统组件本身都是 Rust，从而减少 hostile boundary；Tock 的重点则是如何在 legacy applications 与真实硬件边界上维持 soundness。
- _Rindisbacher et al. (SOSP '25)_ — TickTock 对生产版 Tock 的隔离性质做形式化验证，说明 Tock 的实际接口已经成为后续 formal assurance 工作的基础。

## 我的笔记

<!-- 留空；由人工补充 -->

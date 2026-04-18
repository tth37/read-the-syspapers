---
title: "Rage Against the State Machine: Type-Stated Hardware Peripherals for Increased Driver Correctness"
oneline: "Abacus 把硬件设备协议编码成能处理硬件自发迁移的 Rust typestate，在编译期拦住驱动的协议违规。"
authors:
  - "Tyler Potyondy"
  - "Anthony Tarbinian"
  - "Leon Schuermann"
  - "Eric Mugnier"
  - "Adin Ackerman"
  - "Amit Levy"
  - "Pat Pannuto"
affiliations:
  - "UC San Diego, La Jolla, California, USA"
  - "Princeton University, Princeton, New Jersey, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790207"
tags:
  - kernel
  - hardware
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Abacus 的出发点是：传统 typestate 之所以在驱动里失效，不是因为硬件没有协议结构，而是因为硬件会在软件不知情时自己推进状态机。论文把硬件状态分成 stable 和 transient 两类，在 transient 状态里只允许执行对所有硬件可达后继状态都安全的操作，并要求驱动在需要更精确信息时显式做 re-synchronization。最终它把这些规则做成一个 Rust DSL 和代码生成框架，能在编译期抓住真实的 device-protocol bug，而且代码体积几乎不增加，运行时开销也很小。

## 问题背景

这篇论文解决的是 device protocol violation：驱动在原始 MMIO 接口层面“可以”发出的读写，在真实设备协议里却是当前状态下不合法的。这个问题并不边缘。作者引用已有工作指出，这类错误占 Linux 的 USB、1394 和 PCI 驱动补丁 bug 的 38%；他们又在 Tock 和 Redox 这两个 Rust OS 里找到了 21 个已修复的类似例子。Rust 能防住内存安全问题，但它不会自动阻止驱动在错误的硬件状态下写错寄存器。

难点在于，硬件给软件暴露的是一个极其宽松的接口，通常只是一些可读可写寄存器；真正的协议却藏在 datasheet 的自然语言描述里，并且会随着设备状态动态变化。例如 UART 的发送寄存器只能在 FIFO 未满时写入；某些网卡过滤器寄存器只能在接收被关闭时修改；无线电 shortcut 只能在很窄的瞬时阶段打开。这些恰恰是驱动最容易写错的地方，尤其当中断、DMA 或硬件自主状态迁移引入后，软件对当前状态的判断更容易失真。

乍看之下，typestate 很适合这个问题：把每个设备状态编码成一个类型，只暴露该状态下合法的方法，让编译器拒绝非法迁移即可。但标准 typestate 默认软件拥有状态机的控制权，而真实驱动并不是。硬件可能自行把队列清空、结束 reset、断开端口，或者推进 radio 的内部阶段。一旦这种迁移发生，软件静态持有的类型就不再和真实硬件状态一致，传统 typestate 的前提也就被破坏了。

## 核心洞察

论文最重要的洞察是：驱动并不需要完整拥有硬件状态机，仍然可以恢复有价值的静态保证。它真正需要的，是一种保守但可执行的规则，去描述“硬件可能已经在背后把状态推进到了哪里”。

Abacus 因而把状态分为两类。stable state 只能由软件显式操作离开；transient state 至少有一条由硬件发起的出边。对 stable state，普通 typestate 推理依然成立。对 transient state，Abacus 接受“软件视图可能已经和真实硬件分叉”这一事实，但通过一个更保守的规则维持正确性：驱动在该状态下只能执行那些对所有硬件可达状态都合法的操作。等驱动确实需要更精确的状态时，再通过轮询状态寄存器、处理中断或执行 reset 之类的动作，把软件模型与硬件重新对齐。

这就是论文真正的新意。它把“硬件并发会破坏 typestate”改写成“硬件并发会收窄 transient 状态下可暴露的 API，直到同步恢复精度为止”。作者用 rely-guarantee 的语言来解释这一点，但从系统实现角度看，核心结论很直接：只要把不确定性显式化并以交集语义保守处理，编译期驱动协议检查仍然可行。

## 设计

Abacus 由一个 Rust 框架和一套嵌入 procedural macro 注解的 DSL 组成。开发者先从 datasheet 中抽出设备状态机，并给每个状态标记 stable 或 transient。接着，对每个寄存器或 bitfield 添加两类注解之一：普通访问约束，或状态迁移约束 `SC(from, to)`。后者同时表达“什么状态下允许访问”以及“该访问会把设备带到什么状态”。

基于这些注解，Abacus 自动生成按状态参数化的硬件对象、只在合法状态暴露 MMIO 方法的 wrapper type、表示当前可能状态的 enum，以及编译器强制的同步义务。对于 transient state，开发者必须实现 `SyncState` trait，通过读取状态寄存器、处理中断结果等方式把状态细化回来。这个实现本身是 trusted code，但框架至少保证“少了同步器就无法编译”。

UART 例子很好地说明了这套机制。向 data 寄存器写入会把设备从 `QueueReady` 推到一个“可能已满”的状态；config 寄存器只能在 `QueueReady<Idle>` 时访问；reset 则能从任意状态把设备带回 `QueueReady<Idle>`。如果驱动当前位于 `QueueMaybeFull` 这样的 transient 状态，Abacus 干脆不会为它生成 `data.write()`，因为硬件可能已经偷偷迁移到任意可达后继状态，而只有这些后继状态的操作交集才是安全的。

为了适应 Rust 驱动里常见的 `&self` 方法风格，Abacus 还提供了 `AbacusCell`。它利用 interior mutability，让共享引用上的驱动方法也能在闭包内部 move 这些带 typestate 的寄存器对象，同时不破坏 Rust 的所有权约束。它不是完全意义上的定理证明器，而是一种把协议不变量压进类型系统、再通过受限代码生成把违规变成编译错误的工程化框架。

## 实验评估

实验主要回答三个实际问题：Abacus 能否接到真实驱动里、能抓到什么 bug、代价多大。

在可用性上，作者把它移植到了五个 Tock 驱动和一个 Redox xHCI 驱动。每个驱动需要的 DSL 注解从 4 行到 45 行不等，而驱动重构量则从几十行到几百行不等，取决于状态机复杂度。最复杂的是 nRF52 15.4 radio：有 8 个状态，需要 33 行注解，并伴随一轮较大的驱动改写。这当然不是零成本，但它仍然属于“正常系统工程工作量”，而不是“需要数月验证劳动”的级别。

在 bug 捕获上，Abacus 直接发现了 nRF52840 UARTE 驱动里一次对 disabled peripheral 的非法写入，也发现 Redox xHCI PortSC 路径缺少状态检查：驱动可能在硬件仍处于 Resetting 状态时读取 PLS 位，而该状态下这些位是未定义的。论文还解释了 Section 2 里提到的 Redox Ethernet 和 Tock UART bug，一旦相应协议约束被编码进 DSL，就会退化成编译错误。

在开销上，结果相当强。五个 Tock 集成里，内核镜像的最大额外体积只有 8 字节；对 100-200 KB 量级的内核来说基本可以忽略。Redox 的 xHCI 驱动甚至反而缩小了 7.5 KB，也就是 0.33%，原因是 Abacus 消除了重复的运行时状态检查。运行时 microbenchmark 里，多数路径几乎持平，部分路径还有小幅提升；最差的测量结果只是 STM32 USART 接收路径多了 40 个 cycle。macrobenchmark 里，端到端最明显的额外开销也只有 temperature driver 的 1.2%，而 Nordic UART 因为避免了冗余检查反而更快。最亮眼的案例是 nRF52 15.4 radio：作者在接入 Abacus 后，用不到两小时就安全打开了全部 hardware shortcuts，使中断数下降 50%，发送运行时开销下降 8%。

这组结果很好地支撑了论文的中心论点。Abacus 不是没有开发成本，但它在编译产物上的代价几乎可以忽略，而且更强的协议约束有时不只是“防 bug”，还会让开发者敢于启用原本因为太难保证正确而不敢打开的硬件特性。

## 创新性与影响

和 _Mérillon et al. (OSDI '00)_ 这类经典 driver DSL 相比，Abacus 的新意不只是“用更高级语言描述协议”，而是显式把硬件状态与硬件自发迁移纳入约束。和 _Ryzhyk et al. (ASPLOS '11)_ 这类硬件/软件联合验证工作相比，它放弃了最强的证明能力，换来了足够轻量、可以 retrofit 到现有 Rust 驱动里的工程可行性。和 _LeBlanc et al. (OSDI '24)_ 这类 typestate 系统相比，它真正推进的一步是处理“硬件才是主要 custody holder”的并发状态机，而不是只处理软件主导或同步硬件。

因此，这篇论文对 OS、嵌入式系统和安全系统工程师都很有意义，尤其是那些已经接受 Rust、但又觉得“光有内存安全还不够”的团队。它长期最可能留下的影响，不是某个具体驱动架构，而是一种可复用的方法论：把 PDF 里的协议规则挪进类型检查器。

## 局限性

Abacus 依赖开发者给出的协议模型本身是正确的。如果 DSL 注解错误地翻译了 datasheet，框架也只会非常忠实地执行错误规则。`SyncState` 这类 trusted hook 也是必要但脆弱的边界：没有它做不到同步，但它自身又不在 Abacus 的静态检查范围内。另一个限制是，协议必须能被压缩成规模可控的状态机，并且硬件最好提供某种可观测的同步手段，比如状态位、中断或 reset 路径；如果规则纯粹是“等 20ms 之后才允许操作”且硬件没有任何可观测反馈，Abacus 就无能为力。

实验范围也比论文问题陈述显得更窄。作者只研究了少量 Rust 驱动，而不是 Linux 级别的大规模驱动生态；最显著的性能收益也来自一个比较特殊的 radio-shortcut 场景，在那里更强的协议跟踪恰好解锁了更多硬件特性。这当然是积极信号，但不能直接推出“每个驱动都能以同样方式赚回注解成本”。

## 相关工作

- _Ryzhyk et al. (EuroSys '09)_ — Dingo 对 device-protocol bug 做了系统性刻画，而 Abacus 则把这个问题转化成驱动语言内部的静态约束机制。
- _Mérillon et al. (OSDI '00)_ — DEVIL 同样用 DSL 描述设备，但 Abacus 进一步把硬件状态和 transient 不确定性纳入编译期操作约束。
- _Ryzhyk et al. (ASPLOS '11)_ — 硬件验证复用追求更强的硬件/软件一致性证明；Abacus 则选择更轻量、更适合改造现有驱动的路线。
- _LeBlanc et al. (OSDI '24)_ — SquirrelFS 展示了 Rust typestate 如何维护文件系统不变量，而 Abacus 把这类方法扩展到会在软件控制之外并发迁移状态的硬件外设。

## 我的笔记

<!-- 留空；由人工补充 -->

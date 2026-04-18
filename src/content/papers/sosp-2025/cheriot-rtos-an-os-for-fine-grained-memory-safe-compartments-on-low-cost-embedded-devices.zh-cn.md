---
title: "CHERIoT RTOS: An OS for Fine-Grained Memory-Safe Compartments on Low-Cost Embedded Devices"
oneline: "CHERIoT RTOS 把 CHERI-only compartments、capability quotas 和 firmware auditing 结合起来，让低成本 MCU 也能获得 memory-safe isolation 与可 micro-reboot 的服务。"
authors:
  - "Saar Amar"
  - "Tony Chen"
  - "David Chisnall"
  - "Nathaniel Wesley Filardo"
  - "Ben Laurie"
  - "Hugo Lefeuvre"
  - "Kunyan Liu"
  - "Simon W. Moore"
  - "Robert Norton-Wright"
  - "Margo Seltzer"
  - "Yucong Tao"
  - "Robert N. M. Watson"
  - "Hongyan Xia"
affiliations:
  - "Apple"
  - "Microsoft"
  - "SCI Semiconductor"
  - "Google"
  - "University of British Columbia"
  - "University of Cambridge"
  - "ARM Ltd."
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764844"
tags:
  - kernel
  - security
  - hardware
  - isolation
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CHERIoT RTOS 的核心论点是：低成本 embedded device 若想获得真正强的隔离，必须把硬件与操作系统一起围绕 CHERI capability 重新设计。它最终给出的是一个没有 MMU 的 RTOS，但仍能提供 memory-safe compartments、quota-controlled sharing、interface hardening 和 firmware auditing，而且资源开销仍落在几十到几百 KB RAM 的设备预算内。

## 问题背景

这篇论文抓住了 embedded systems 里一个很典型的错配：最便宜、部署最广的设备往往运行着 legacy C/C++ 固件、没有 MMU，却还要联网，甚至承担关键基础设施功能。于是，最容易出现 memory corruption 的地方，恰恰也是防护能力最弱的地方。

现有方案并不真正适合这个场景。基于 MPU 或 TrustZone 的设计隔离粒度太粗，既难以把很多小组件彼此隔开，也难以在互不信任的代码之间安全共享细粒度对象。自动化 compartmentalization 只能补上一部分边界，却没有真正解决接口加固、故障恢复和系统级审计。全面改写成安全语言同样不现实，因为很多 deployment 依赖旧代码、binary-only 组件和监管约束。论文要解决的正是这个问题：如何在不放弃低成本和现实迁移路径的前提下，大幅提高安全下限。

## 核心洞察

作者最重要的判断是，embedded isolation 只有在 CHERI capability 成为唯一保护机制时才会真正可用，而不是继续把它当成 MMU 或 MPU 后面的一层补丁。如果每个指针天然都带着 bounds、permissions 和 tag，机器就能直接执行 spatial memory safety，而 OS 也可以用 capability 的传播与收缩规则表达最小权限，而不是继续依赖粗粒度区域和额外元数据。

真正关键的是，这种硬件底座让 OS 可以把安全能力做成编程模型。CHERIoT 用 load filter 与 revoker 支持 temporal safety，用 `permit-load-mutable` 与 `permit-load-global` 约束更深层的 delegation，再配合 richer sealing/sentry 语义，让 OS 能构建 fine-grained compartments、opaque objects、allocation quotas、TOCTOU-resistant claims，以及可 micro-reboot 的 fault domains。论文真正要记住的命题因此是：让 capability-safe sharing 成为默认编程模型，而不只是额外的硬件防护。

## 设计

整套系统只有四个 TCB 组件：boot-time loader、负责上下文与 compartment 切换的 switcher、共享堆 allocator，以及 scheduler。Compartment 是静态的代码与数据保护域；thread 也是静态创建的，并且只能通过声明好的 entry point 在 compartment 之间迁移。shared library 则直接运行在调用者域内，以更低代价实现代码复用。

最关键的协同设计选择，是让 CHERI 成为唯一隔离机制。temporal safety 依赖 revocation bits、load filter 和后台 revoker：对象 free 后，相关 capability 重新载入寄存器时会被清掉 tag，而 revoker 扫完整个内存后，allocator 才能安全复用这块区域。delegation 也不再只是普通的读写执行权限裁剪，而是加入 deep immutability 和 deep no-capture；sentry 进一步把跨 compartment 控制流和 interrupt posture 结构化。

在这层硬件之上，OS 提供了一组真正可用的抽象。opaque objects 让调用者可以代替 callee 持有 per-flow state，但不能篡改它；allocation capabilities 把 heap quota 和 free authority 显式化，而 quota delegation 允许服务代表调用者分配内存。interface-hardening API 会在共享 capability 前主动收紧权限、检查输入，并通过 claim 阻止围绕 free 的 TOCTOU 攻击。再加上 error handler 与 micro-reboot 支持，compartment 才真正成为 fault containment boundary。最后，linker 还会导出 JSON firmware report，让外部工具用 Rego policy 在部署前审计 imports、MMIO 访问和 quota 配置。

## 实验评估

论文对评估边界交代得很明确：当前并不存在一个能在同类 CHERIoT 硬件上提供相近隔离粒度与 memory safety 的现成 baseline，因此作者主要使用 code-size accounting、microbenchmark、porting study 和端到端 case study 来证明可行性。实验平台是一块 33 MHz 的 Arty A7 FPGA 板，配 256 KiB SRAM。

就目标场景而言，成本结果是有说服力的。CHERIoT core 相比 16-entry PMP 只增加约 4.5% 的面积，bare-metal CoreMark 相对非 CHERI RISC-V 32E 慢 20.65%。OS 层面，base system 需要 25.9 KB code 和 3.7 KB data，而 loader 在 boot 后会自擦除，因此常驻代码只有 18.4 KB。空的 compartment call 平均 209 cycles，使用 256 B stack 的调用为 452 cycles，interrupt latency 平均 1028 cycles，也就是 33 MHz 下约 31 微秒。allocator 在 1 KiB 以上、接近网络真实负载的 buffer 大小时可以提供约 5 MiB/s 的吞吐，足以覆盖 10 Mbit 链路。

最有分量的还是端到端系统演示。作者构建了一个运行在 13 个 compartments 中的 JavaScript IoT 应用，通过 MQTT over TLS 与后端通信，总内存占用 243 KB。随后他们向 TCP/IP stack 注入一个崩溃，系统在 0.27 秒内完成 micro-reboot 并重新建立连接。移植实验也支持“可渐进迁移”的主张：FreeRTOS TCP/IP stack 和 BearSSL 通过 wrapper 接入，而 Microvium 几乎不需要修改。整体来看，这些结果足以证明论文的中心命题，即这套设计在低成本 embedded profile 上是可部署的；但由于缺少真正同类系统的直接对照，它证明的更多是 feasibility，而不是全面性能领先。

## 创新性与影响

相对于先前的 MICRO'23 CHERIoT 硬件论文，这篇 SOSP 论文真正的新意在于 OS 与编程模型本身：compartment/thread 结构、least-privilege TCB split、opaque-object API、quota delegation、interface hardening 机制，以及 firmware auditing 工作流。相对于以往 embedded isolation 工作，它最大的推进点是把 memory safety、sharing、fault recovery 和 auditing 统一到同一个 capability substrate 上，而不是分裂成彼此独立的附加模块。

这种统一化对工程与研究都重要。对工程团队而言，它提供了一条现实的迁移路径：不必重写大量 C/C++ 固件，也不必引入昂贵 MMU，就能明显缩小权限边界。对研究者而言，它则说明 capability architecture 不只是硬件防护机制，还会反过来塑造 OS API、恢复机制和部署期策略审计。

## 局限性

这套设计建立在一些对研究原型来说合理、但仍然偏强的假设之上。论文假定 CHERIoT 硬件和 TCB 正确无误，physical attack 与 side channel 不在范围内；同时，error handler 和 auditing policy 的正确性仍需要 integrator 负责。系统也无法阻止那些不会触发 trap 的高层逻辑漏洞，而反复触发 fault 的攻击者依旧可以通过不停触发 micro-reboot 来造成 DoS。

工程代价同样存在。CHERIoT 需要专门硬件，追求的是 source compatibility 而不是 binary compatibility，某些服务也需要不小的 wrapper 才能充分受益于 compartment model。动态分配在严格确定性时延阶段同样不被鼓励，因为 revocation 是异步完成的。整体评估因此更像一份很强的 feasibility 证明，而不是对更广硬件代际和生产级工具链的完整回答。

## 相关工作

- _Amar et al. (MICRO '23)_ — 更早的 CHERIoT 硬件论文提供了 capability ISA、load filter 和 revoker；这篇 SOSP 论文则补上让这些硬件特性真正可被软件利用的 OS 结构与编程模型。
- _Levy et al. (SOSP '17)_ — Tock 借助 Rust 在小型 embedded device 上获得 memory safety，而 CHERIoT RTOS 的重点是保留 legacy C/C++ 迁移路径，同时提供更强的 compartment boundary 与 firmware auditing。
- _Clements et al. (USENIX Security '18)_ — ACES 试图在现有硬件上自动切分 embedded software，但 CHERIoT 认为这种 coarse-grained retrofit isolation 仍不足以支持安全共享、temporal safety 和接口加固。
- _Zhou et al. (EuroSys '22)_ — OPEC 在现有 bare-metal embedded hardware 上实现 operation-based isolation，而 CHERIoT 更强调 capability-safe delegation、fault-tolerant compartments 与系统级可审计性。

## 我的笔记

<!-- 留空；由人工补充 -->

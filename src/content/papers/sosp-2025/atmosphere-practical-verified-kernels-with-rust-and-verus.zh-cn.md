---
title: "Atmosphere: Practical Verified Kernels with Rust and Verus"
oneline: "Atmosphere 保留原始指针内核实现，再用 Verus、扁平权限映射与显式内存管理，把 verified microkernel 的验证做成可落地工程。"
authors:
  - "Xiangdong Chen"
  - "Zhaofeng Li"
  - "Jerry Zhang"
  - "Vikram Narayanan"
  - "Anton Burtsev"
affiliations:
  - "University of Utah"
  - "Palo Alto Networks"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764821"
tags:
  - kernel
  - verification
  - security
  - pl-systems
category: verification-and-reliability
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Atmosphere 认为，verified kernel 要想真正实用，关键不是把代码改写得更“高层”，而是重组证明结构。它在 Rust 里保留原始指针风格的数据结构，再用 Verus、扁平权限映射和显式内存管理，去证明一个 full-featured microkernel 的 refinement、安全性与 noninterference。

## 问题背景

此前的 verified kernel 要么需要接近 theorem prover 项目的投入，要么为了适配 SMT automation 先把 kernel 简化到不太像真实系统。真正的 microkernel 难在它的状态本来就是递归且 pointer-heavy 的：process tree、container hierarchy、linked list、多级 page table、reverse pointer，以及生命周期复杂的对象。这些模式既不适合按 Rust 常规 ownership 风格直接表达，也不适合交给 SMT solver 做开放递归推理。

自动内存管理还会进一步遮蔽全局内存状态，而 leak freedom、quota accounting 与 noninterference 恰恰都需要系统知道“每一页到底属于谁”。Atmosphere 因此选择更难的目标：不是验证一个削弱版 toy kernel，而是在支持进程、线程、IPC、虚拟内存、IOMMU 与 mixed-criticality container 的 separation kernel 上，把验证流程压到工程上可接受的范围。

## 核心洞察

论文的核心命题是：需要被扁平化的不是 kernel 功能，而是 proof structure。Atmosphere 在可执行 Rust 里继续使用原始、非线性的指针，但把访问内部对象的权限统一放进 subsystem 顶层的 flat map。这样 Verus 就能直接看到“所有 containers”“所有 threads”或“所有 page-table nodes”，很多原本依赖递归展开的论证都能改写成全局、非递归的不变量。

这会直接改变难题的形状。像树无环、parent/child 关系正确、对象所有权互不重叠这类 structural facts，可以单独证明；具体 syscall 则只需描述局部的 before/after 效果，再由独立的 proof function 说明这些更新不会破坏 structural invariants。内存管理也同理：不再把生命周期交给 Rust smart pointer 隐式处理，而是显式分配和释放，于是 kernel 才能对整个机器陈述 leak freedom、quota 与 isolation。

## 设计

Atmosphere 是一个 big-lock microkernel：在多核硬件上运行，但所有 syscall 和 interrupt 都在一个全局锁下进入内核。它提供 address space、thread、动态内存、IPC endpoint、IOMMU，以及为进程组保留内存和 CPU 核的 container。driver 与更高层服务放在 user space。container 构成一棵树，父 container 通过终止子孙来回收资源，而不是做细粒度 revocation，因为稳定的 ownership 边界更容易验证。

在内部，process manager 维护 container、process、thread、endpoint 等对象的 flat tracked-permission map。可执行代码的写法接近 unsafe C kernel，而 Verus permission 负责证明 pointer access 合法。像 container 的 `path` 与 `subtree` 这样的 ghost state，把层级信息暴露成 proof-friendly 形式。closed spec function 负责 structural invariants，open spec 负责具体操作的状态变化，独立的 proof function 再证明这些变化不会破坏结构正确性。

显式内存管理同样关键。Atmosphere 用 4 KiB、2 MiB 与 1 GiB 页面分配 kernel object，把每个物理页标记为 free、mapped、merged 或 allocated，并为每个 subsystem 定义 `page_closure()`，以自底向上的方式证明内存互斥和 leak freedom。page table 更新按单步写入来验证。相同的 flat-spec 风格还支撑了论文里的 A/B/V noninterference 例子：两个不受信任的 container 彼此隔离，但都可以和一个小型 verified mediator container 通信。

## 实验评估

Atmosphere 包含 6,048 行可执行代码和 20,098 行 proof/spec 代码，proof-to-code ratio 为 3.32:1。作者报告总投入不到 2.5 person-years，其中约 1.5 person-years 用在 verified 部分。完整验证在 8 线程 CloudLab c220g5 上耗时 1 分 7 秒，在较新的 laptop 上不到 20 秒。扁平化设计还有直接收益：与 Verus-verified 的 NrOS page table 相比，Atmosphere 的 page table 每行可执行代码所需的证明量约少 3 倍，单线程验证速度快 3 倍以上。

运行时性能也接近强基线。call/reply IPC 为 1,058 cycles，seL4 为 1,026；page mapping 为 1,984 cycles，而 seL4 的可比测试为 2,650 cycles。Ixgbe driver 在 batch size 32 时达到 10 GbE line rate；NVMe driver 的读性能接近 SPDK，写性能大约比 Linux 低 10%；Maglev 在 driver 独占核心时达到 13.3 Mpps；`httpd` 则达到 99.4 K requests/s，高于同场景下 Nginx 的 70.9 K。整体上，这些结果支持论文的核心结论：formal verification 没有把系统逼成 toy kernel，不过最佳结果通常依赖 batching 或专用核心。

## 创新性与影响

相对于 seL4 和 CertiKOS，Atmosphere 的贡献更像是改善 proof economics，而不是提供更强 assurance。相对于 Hyperkernel，它保留了更丰富的 kernel interface，而不是先把功能削弱到有利于自动化。相对于此前的 Verus 系统，它碰的正是最容易压垮 SMT-based verification 的部分：递归、pointer-centric 的 kernel state 和手工管理的生命周期。

因此，这篇论文的长期价值更像是一套方法论：保留高效的低层表示，把 proof ownership 扁平化，把内存状态显式化，再把 structural invariants 与局部 transition proof 分离。后续无论做 verified kernel，还是跑在 separation kernel 上的 verified user-level service，都可以复用这套思路。

## 局限性

这篇论文并没有解决细粒度的 kernel concurrency：Atmosphere 依赖 big lock，论文里的 verified mediator 例子也是单线程的。noninterference 只覆盖 syscall 效果，不覆盖 cache 等共享硬件带来的 timing channel；长时间持锁的操作仍可能泄露时序信息。粗粒度 revocation 也是明确折中：通过终止整个 container 回收资源更容易验证，但灵活性更差。

TCB 也依然很大。证明仍需信任 Verus frontend、Z3、Rust compiler 与 `core`、对 core primitive 的规格、Verus 中暂缺而补入的 axioms、tracked permission setter 代码、trusted 的低层 Rust 与 assembly、boot loader，以及底层 CPU/firmware 平台。Atmosphere 因此证明的是“验证成本能显著下降”，而不是“系统从此不再需要被信任”。

## 相关工作

- _Klein et al. (SOSP '09)_ - seL4 首次证明 practical verified microkernel 可行，而 Atmosphere 追求的是借助 SMT 驱动的 Rust verification 降低证明成本、提高迭代速度。
- _Nelson et al. (SOSP '17)_ - Hyperkernel 展示了高度自动化的 kernel verification，但它比 Atmosphere 更激进地约束了 kernel interface。
- _Lattuada et al. (SOSP '24)_ - Verus 提供了 linear ghost type 与 SMT automation 的基础；Atmosphere 则展示如何围绕这个 verifier 去塑造一个真实 microkernel，而不是只验证一个小型孤立组件。
- _Zhou et al. (OSDI '24)_ - VeriSMo 也是重要的 Verus-based verified system，但它面对的系统状态没有一般 microkernel 那样递归、pointer-centric。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "How to Copy Memory? Coordinated Asynchronous Copy as a First-Class OS Service"
oneline: "Copier 把 memory copy 变成由 OS 管理的异步服务，让 copy 与 computation 重叠，并用 AVX、DMA 与 copy absorption 优化跨边界的数据移动。"
authors:
  - "Jingkai He"
  - "Yunpeng Dong"
  - "Dong Du"
  - "Mo Zou"
  - "Zhitai Yu"
  - "Yuxin Ren"
  - "Ning Jia"
  - "Yubin Xia"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "Engineering Research Center for Domain-specific Operating Systems, Ministry of Education, China"
  - "Huawei Technologies Co., Ltd."
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764800"
code_url: "https://github.com/SJTU-IPADS/Copier"
tags:
  - memory
  - kernel
  - scheduling
category: memory-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Copier 主张把 memory copy 从阻塞式库函数重构为一项一等 OS 服务。它通过 `amemcpy`/`csync` 异步接口、跨 user/kernel 的依赖跟踪，以及 AVX+DMA 协同调度，让中等大小的 copy 与计算重叠，并把一串 copy 折叠成更短路径，在 Redis 上最高带来 `1.8x` 延迟收益、相对 zIO 最高快 `1.6x`。

## 问题背景

论文首先指出，copy 仍然是现代系统里的高频税项。syscall、IPC、network stack、serialization library、compression code 和 storage service 都在持续搬运字节。作者测得，在代表性应用里，copy 最多可以占到 `66.2%` 的周期；即使在商业手机 OS 上，它也仍是显著瓶颈。

现有优化路径各自割裂。硬件加速只能在软件真正能用到硬件时生效：用户态库可以使用 SIMD，但内核通常因为保存和恢复向量寄存器状态成本过高而避免它；DMA 虽然节省 CPU，但用户程序不容易直接驱动，而且小拷贝的提交成本太高。zero-copy 也只在特定场景成立，同时带来明显约束：要求页对齐、通常默认单所有者语义、难以支持多副本、需要额外的 ownership 管理，并且在共享可变缓冲区时容易暴露 TOCTTOU 风险。它的收益区间也偏窄，例如 Linux `MSG_ZEROCOPY` 更适合大消息，zIO 也要达到一定尺寸后才真正占优。

因此，问题不在于再造一个更快的 `memcpy()`，而在于怎样提供一种系统级机制，既能跨 privilege boundary 协调 copy，又能把 copy latency 隐藏到有用工作之后，还能把一整条 copy chain 作为整体优化，而不是逐个调用点各自处理。

## 核心洞察

这篇论文的核心命题是：copy 应该变成一项异步、全局管理的 OS 服务，因为程序通常是“整块 copy、分段使用”数据。论文把“copy 完成”到“数据第一次被真正使用”之间的间隔称为 Copy-Use window，并测得这个窗口在很多场景里达到同等数据 copy 时间的 `2x` 到 `10x`。只要 OS 能尽早启动 copy，并暴露细粒度的 ready 状态，就可以在不放弃私有缓冲区语义的前提下，把大量 copy latency 从 critical path 上移走。

把 copy 做成服务还有两个附加收益。第一，服务可以集中利用 AVX、DMA 这类异构 copy engine，而单个调用点很难做到这一点。第二，服务能够看到像 “kernel -> 中间 buffer -> 最终对象” 这样的 copy chain，并在正确性允许时直接消掉中间 copy。换句话说，论文真正要证明的不是“async memcpy 有用”，而是“协调式异步 copy + OS 的全局视角”才是收益的来源。

## 设计

Copier 提供高层 API `amemcpy()` 与 `csync()`，其底层是映射到进程地址空间中的三类 per-client 队列：`Copy Queue`、`Sync Queue` 和 `Handler Queue`。每个 Copy Task 携带源地址、目的地址、长度、granularity 以及 descriptor bitmap。Copier 以固定大小的 segment 为单位执行 copy，并在 segment 完成后设置对应 bit，因此客户端只需在真正访问某段数据前对该范围调用 `csync()`，而不必等待整个 transfer 结束。`Sync Queue` 还能把当前急需的 segment 及其依赖提升优先级，从而避免严格 FIFO 带来的 head-of-line blocking。像释放源缓冲区这样的 post-copy 操作，则通过 delegated handler 处理，而不是再增加显式 ownership syscall。

真正困难的是 user 与 kernel 之间的正确性。Copier 为每个进程维护独立的 user-mode 和 kernel-mode 队列集合，并在 trap/return 位置插入 barrier task，据此恢复跨队列的顺序关系。当 `csync()` 提升某个任务时，Copier 还会沿着重叠内存区域向后追踪数据依赖，防止把 copy 重排到会改变字节内容的写入之前。论文附录进一步给出 rely-guarantee 风格的模拟证明，说明只要 `csync` 插入位置正确，`amemcpy` 的语义就能 refine 传统同步 copy。

硬件利用依赖一个 piggyback dispatcher。Copier 先按物理连续区间把一次 copy 切成 subtasks，再把足够大的 subtask 分配给 DMA，其余留给 AVX。关键不只是“选哪种硬件”，而是避免 CPU 空等 DMA：Copier 在同一轮调度里让 DMA copy 与 AVX copy 重叠执行，并尽量让两边在相近时间完成。`ATCache` 还会缓存高重复缓冲区的虚拟地址到物理页翻译，降低地址解析成本。

另一个很有辨识度的机制是 layered copy absorption。如果系统看到 `A -> B` 后面跟着 `B -> C`，而 `B` 只有一部分真正 materialize 或被修改，那么 Copier 会按 segment 选择“最新的数据来源”，而不是盲目从单一源整体复制。配合 lazy copy task 和 abort 风格的 sync，它可以优化 proxy 这类“只检查 header、再转发 payload”的流水线。由于 Copier 是共享服务，它还实现了基于 copy length 的 CFS 风格调度、copier cgroup controller、copier thread 自动伸缩，以及 proactive fault handling，在 copy thread 解引用用户虚拟地址前先处理 CoW 与分页问题。围绕它的工具链还包括 `libCopier`、`CopierSanitizer` 和处于早期阶段的 `CopierGen`。

## 实验评估

主要服务器实验运行在双路 Xeon E5-2650 v4、Linux `5.15.131` 上；Copier 使用一个专用核心处理 copy。评估既覆盖底层 copy substrate，也覆盖端到端应用，对比对象包括 Linux ERMS copy、AVX2 user copy、DMA、`io_uring`、zero-copy socket、UB 与 zIO。

从微基准看，Copier 在自己的目标区间内显著优于任何单一 baseline。它的 copy throughput 相比内核 ERMS 最高提升 `158%`，相比用户态 AVX2 最高提升 `38%`；当缓冲区重复出现、`ATCache` 能发挥作用时，收益还能继续扩大。对于 OS service，`recv()` latency 下降 `16%` 到 `92%`，`send()` 下降 `7%` 到 `37%`；Binder IPC 端到端 latency 下降 `9.6%` 到 `35.5%`；CoW page fault 的阻塞时间在 `2 MB` 页面上下降 `71.8%`。

真正说明问题的是应用实验。Redis 同时受益于 copy overlap 与 copy absorption：GET latency 改善 `4.2%` 到 `42.5%`，SET latency 改善 `2.7%` 到 `43.4%`，throughput 最高提升 `50%`。TinyProxy 的 throughput 提升 `7.2%` 到 `32.3%`，因为 Copier 能把三段 forwarding copy 有效折叠成一次数据转移，而 zIO 无法跨 privilege boundary 做到这一点。Protobuf 反序列化最高提速 `33%`，OpenSSL `SSL_read()` 最高提速 `8.4%`，HarmonyOS 视频解码 latency 降低 `3%` 到 `10%`，额外能耗只增加 `0.07%` 到 `0.29%`。

整体上，这组实验支撑了论文的中心论点：当工作负载存在真实的 Copy-Use window、存在可吸收的 copy chain，或者系统有足够空闲 CPU 资源支撑专用 copy thread 时，Copier 的确能把 copy 从关键路径上挪开。baseline 选得也比较认真。最大的保留意见是，大而对齐的 send 仍然更适合传统 zero-copy，而且作者也明确展示了在完全饱和机器上，Copier 可能用更低的总体吞吐换来更低的请求延迟。

## 创新性与影响

这篇论文的新意在于提出了新的系统抽象，而不只是优化一个更快的 kernel primitive。已有工作分别探索过 async syscall、DMA copy 和 zero-copy I/O，但 Copier 是这里第一个把 memory copy 本身做成可调度的 OS 服务，并为它定义显式编程原语、跨 privilege boundary 的依赖跟踪，以及整条 copy chain 的全局优化机制。

这种 framing 很重要。很多系统论文都会指出 copy 开销，但解决方案通常被绑在 networking、IPC 或 storage 某个子系统里。Copier 想做的是一个可复用的公共底座，让 network stack、CoW handler、Binder、serializer、proxy 和应用库都能复用同一套 copy 优化逻辑。如果这个抽象最终成立，那么未来系统就不必在每个子系统里各自重做一遍 copy 优化。

## 局限性

Copier 的收益依赖工作负载结构。它主要面向访问模式规整、且存在明显 Copy-Use window 的场景；对于随机访问消费者，系统很难安全地推迟同步，因此可重叠的空间会更小。它的编程模型也并非零成本：开发者必须在正确位置插入 `csync`，虽然 sanitizer 和形式化证明降低了风险，但系统仍然依赖正确使用。

实现代价也不可忽略。服务器实验里，Copier 需要 polling thread 和专用 copy core。当所有 CPU 核心都已经忙满时，论文报告某个饱和 Redis 场景下虽然 latency 更好，但总体 throughput 会下降 `4.3%` 到 `6.5%`。对于至少 `32 KB` 的大消息，zero-copy send 仍能胜过 Copier；而基于编译器的自动迁移也还处于早期，复杂的指针密集代码仍被留作未来工作。

## 相关工作

- _Stamler et al. (OSDI '22)_ — zIO 同样试图消除不必要的 copy，但它依赖 remapping 与 page fault，适用尺寸区间更窄，也无法像 Copier 那样吸收跨 privilege boundary 的 copy chain。
- _Su et al. (FAST '23)_ — Fastmove 用 DMA 加速特定 OS storage path，而 Copier 把硬件加速 copy 推广成共享服务，并同时处理 AVX、DMA、公平性与异步语义。
- _Soares and Stumm (OSDI '10)_ — FlexSC 让 syscall 变得异步；Copier 则把这一思想再往下一层推进，让 copy 本身成为异步且可全局调度的对象。
- _Du et al. (ISCA '19)_ — XPC 优化的是安全的 cross-process call，而 Copier 面向的是横跨 syscall、IPC、library 与 application pipeline 的通用内存移动。

## 我的笔记

<!-- empty; left for the human reader -->

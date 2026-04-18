---
title: "KRR: Efficient and Scalable Kernel Record Replay"
oneline: "KRR 把 record-replay 边界缩到 guest kernel，并用 guest-host split recorder 与 replay-coherent 串行化，把多核和 kernel-bypass 场景的开销压低。"
authors:
  - "Tianren Zhang"
  - "Sishuai Gong"
  - "Pedro Fonseca"
affiliations:
  - "SmartX"
  - "Purdue University"
conference: osdi-2025
tags:
  - kernel
  - virtualization
  - observability
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

KRR 的核心主张是，做 kernel debugging 不必把整台 VM 一起 record/replay。它把记录边界缩到 guest kernel，再用跨 guest 与 hypervisor 的 split recorder，加上一套 replay-coherent 的串行化机制，只记录 kernel 真正看到的非确定性输入。这样一来，8 核 RocksDB 和 kernel compilation 的录制开销只有 1.52x 到 2.79x，而 whole-machine baseline 是 8.97x 到 29.94x；在 kernel-bypass 工作负载上，KRR 甚至接近原生性能。

## 问题背景

论文抓住的是一个很实际的痛点：部署环境里的 kernel failure 很难复现，而最难排查的往往又是非确定性故障。Record-replay 的吸引力在于，它能把某次失败执行完整录下来，再精确重放，从而支持 reverse debugging 和各种离线重分析。但现有系统通常以 application 或整台 VM 为边界来做记录，代价在今天的真实工作负载上非常高。

问题会被两个趋势进一步放大。第一，现代工作负载越来越依赖多核，而现有 VM record-replay 为了恢复确定性，往往要么把执行串行化，要么记录足够多的共享内存顺序信息，结果都是开销随核心数快速恶化，甚至超过核心数本身。第二，很多数据中心应用已经转向 SPDK、DPDK 这类 kernel-bypass 栈。此时 whole-VM record replay 仍然会把所有硬件侧活动都录下来，哪怕大量数据路径根本不经过 guest kernel。于是，开发者只想调 kernel，却要为整条 I/O 路径付费。

KRR 因而提出一个更窄但要求仍然很高的目标：只重现 kernel 的执行，而且要足够精确，能真正拿来调试；同时避免记录那些不会影响 kernel 的 guest user-space 行为。

## 核心洞察

这篇论文最重要的判断是，kernel debugging 的正确 replay 边界不是 machine interface，而是 kernel interface。只要系统能记录所有对 kernel 可见的非确定性输入，开发者就不需要为整台 VM 的行为买单。

难点在于 kernel 的输入有两个方向。来自下方的是 interrupts、DMA 和 device reads；来自上方的是 system calls、通过 `copy_from_user` 之类接口拷入的数据、`io_uring` 这类 shared-memory queue、page table 的副作用，以及 user-space 触发的 exceptions。KRR 的洞察是，这种双接口并非不可控，因为 kernel 的输入点相对明确、可枚举。一旦把这些输入记录下来，多核 replay 最贵的部分也可以一起缩小：KRR 只串行化 kernel execution，让 user-space thread 继续并行执行。于是系统开销会跟真正落在 kernel 里的工作量绑定，这也解释了为什么 kernel-bypass 负载会特别便宜。

## 设计

KRR 采用 split-recorder architecture。Guest recorder 运行在 guest kernel 内部，负责记录软件接口这一侧的输入，包括 system call 编号和参数、通过 `copy_from_user` 与 `get_user` 等接口拷入的数据、`io_uring` 这类 shared-memory 接口上的读取、会影响 memory management 的 page-table accessed/dirty bit、由 user-space 触发的 exceptions，以及 `RDTSC`、`RDRAND` 之类非确定性指令。把这些指令放在 guest 内记录很关键，因为如果每次都依赖 hypervisor trap，就会在高频路径上不断产生 VM exit。

Hypervisor recorder 则处理硬件接口这一侧的输入，包括 interrupts、PIO/MMIO reads，以及来自模拟设备的 DMA 数据。对于 interrupts 和 DMA 这类异步事件，KRR 用一枚保留的硬件计数器记录 kernel-mode instruction count，并把这个计数当作事件时间戳，这样 replay 时就能在同一个执行点注入事件。对于 kernel-bypass 设备，系统还允许显式忽略那些从 user-space 直接走向设备、从未进入 kernel 的流量。

最棘手的是多核确定性。KRR 引入 replay-coherent，也就是 RC spinlock，让任意时刻只有一个 vCPU 在执行 kernel code。和普通 spinlock 不同，RC lock 会把获取顺序以及获取前的 spin 次数都记录下来，因此 replay 时既能复现同样的顺序，也不会把 instruction count 搞乱。为了避免死锁，kernel 在获取某些内部锁前后会主动释放并重新获取这个 RC lock；少量 hypercall 只在这些罕见等待点上用来重新对齐 instruction count。再配合原子化的 event trace 更新，KRR 就能在不为每次 kernel entry/exit 都支付 VM-exit 成本的前提下，构造出一条 kernel 相关事件的全序。

Replay 从 VM snapshot 开始，按顺序重新注入 event trace，并在 QEMU emulator 中执行，这让开发者可以直接使用 GDB 风格的 replay debugging。KRR 还支持 reverse debugging：系统会周期性做 snapshot，并给每个 snapshot 打上 per-vCPU instruction-count vector，避免多核环境里单一全局计数器无法唯一标识状态的问题。

## 实验评估

实验范围足以支撑论文的中心论点。首先，KRR 在 8,156 个 Linux Test Project 用例上通过了 replay 一致性验证。对多核 RocksDB 和 Linux kernel compilation，KRR 相比 whole-machine baseline 明显更便宜。以 RocksDB 为例，在 2 核 VM 上，KRR 的 slowdown 是 1.01x 到 1.67x，而 baseline 是 2.71x 到 4.93x；在 4 核上，这两个区间分别变成 1.06x 到 2.03x 和 5.08x 到 11.76x。到 8 核时，论文摘要给出的 headline number 更直观：KRR 为 1.52x 到 2.79x，whole-VM replay 为 8.97x 到 29.94x。

Kernel-bypass 工作负载最能体现边界选择的收益。RocksDB over SPDK 下，KRR 的 latency slowdown 只有 1.17x 到 1.27x，而 whole-VM replay 会恶化到 29.36x 到 64.51x，因为它把 polling thread 和 worker 一起拖进串行化，尽管主要 I/O 路径已经搬到了 user-space。Redis with DPDK 的结果更接近“几乎无感”：GET 吞吐平均只下降 0.26%，SET 下降 1.14%，P99 latency 的变化范围在 -5.19% 到 11.27% 之间。Nginx with DPDK 则揭示了 KRR 仍然受 kernel 热路径支配的边界条件：处理 1 KB 和 4 KB 小文件时，开销超过 46%；但在 16 KB 和 64 KB 文件上，瓶颈转向网络传输，KRR 的额外开销分别只剩约 2% 和 5%。

Bug reproduction 同样关键。KRR 复现了全部 6 个 deterministic Syzbot bug、6 个 non-deterministic bug 中的 5 个，以及全部 5 个高风险 kernel CVE。唯一失败的例子是一个 BPF 相关 deadlock，它需要多个核心真实并行地竞争同一把锁，而这正是 KRR 的串行化模型无法表达的情况。

## 创新性与影响

相对于 _Ren et al. (ATC '16)_，KRR 不是又一个更快的 whole-machine recorder，而是直接改变了 replay boundary，并愿意额外记录 user-to-kernel 输入，从而换来不必记录无关 VM 行为。相对于 _O'Callahan et al. (ATC '17)_，它说明 application-level record replay 不能直接搬到 kernel：kernel debugging 还必须处理 hardware input、DMA timing 和特权指令。相对于 _Ge et al. (ATC '20)_，它选择 exact replay 而不是 partial reconstruction，代价是前期记录更多，但换来更干净、更可信的调试对象。

这篇论文的影响既在机制，也在 framing。它证明了一个很有价值的系统结论：如果调试目标本来就只是软件栈中的一层，那么只要这一层的接口足够规整、可被可靠拦截，缩小 replay boundary 不仅不会削弱能力，反而可能同时改善性能与可扩展性。

## 局限性

KRR 最大的局限是结构性的：它不能复现那些必须依赖多个物理核心同时执行 kernel code 才会触发的 bug，包括某些 weak-memory 行为和真正的并行锁竞争。论文里没能复现的 bug #8 就是这个限制的直接例子。可扩展性方面，超过大约 8 核之后，RC spinlock 会逐渐成为新的争用点，因此 KRR 并不是面向超大 SMP guest 的廉价 record-replay 方案。

此外还有几项实际代价。对非 kernel-bypass 工作负载，KRR 因为要记录 user-space 到 kernel 的软件输入，trace 体积反而高于 whole-machine replay；论文在 RocksDB 上报告的是 53.39 MB/s 对 8.26 MB/s，不过 gzip 可以把 KRR trace 再压缩 6.91x。Replay 本身也很慢，大约比原生执行慢 20x 到 150x，因为原型依赖 single-step 的 QEMU emulator。最后，普通 passthrough 与 SR-IOV 设备在非 kernel-bypass 模式下还不受支持。

## 相关工作

- _O'Callahan et al. (ATC '17)_ - Mozilla RR 提供了可部署的 application-level record replay，但它不处理 kernel 可见的 hardware input，也不负责 VM 内 guest kernel 的重放。
- _Mashtizadeh et al. (ASPLOS '17)_ - Castor 通过记录同步顺序来重放 race-free user application；KRR 则假设 kernel 天生充满数据竞争，因此选择只串行化 kernel execution。
- _Ren et al. (ATC '16)_ - Samsara 是最接近的多核 whole-machine baseline；KRR 的区别在于把边界切到 kernel，并利用 kernel-bypass 工作负载避免记录无关的 VM 流量。
- _Ge et al. (ATC '20)_ - Kernel REPT 依赖 traces 和 dumps 来重建 kernel failure，而 KRR 在记录阶段多付成本，以保证长执行也能被精确 replay。

## 我的笔记

<!-- 留空；由人工补充 -->

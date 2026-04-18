---
title: "µFork: Supporting POSIX fork Within a Single-Address-Space OS"
oneline: "µFork 在单地址空间内按需重定位 CHERI-tagged 指针来模拟 POSIX 进程，把 `fork` 语义带进 SASOS 而不重新引入多地址空间。"
authors:
  - "John Alistair Kressel"
  - "Hugo Lefeuvre"
  - "Pierre Olivier"
affiliations:
  - "The University of Manchester"
  - "The University of British Columbia"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764809"
code_url: "https://github.com/flexcap-project/ufork"
tags:
  - kernel
  - isolation
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

µFork 证明，真正的 single-address-space OS 也可以支持 POSIX `fork`，而不必退回到每进程页表或 VM cloning。它把子进程视为同一虚拟地址空间中的新区域，用 CHERI tags 找出并重定位绝对指针，再用 Copy-on-Pointer-Access 取代传统 copy-on-write。

## 问题背景

single-address-space operating system 的吸引力很直接：kernel 和应用共享一个地址空间，因此 IPC 更快、上下文切换更便宜、内存占用也更低。这类设计对 unikernel、FaaS runtime 和其他 lightweight system 很有价值，但它与大量真实软件存在根本冲突：很多 POSIX 多进程程序都建立在 `fork` 之上。问题不在 API 表面，而在语义本身。传统 `fork` 会把父进程复制到一个新的地址空间中，而 parent/child 的分离同时承担了 isolation 和内存语义这两件事。

此前的方案通常只解决其中一部分。早期 SASOS 如 Mungi 依赖 segment-relative addressing，让复制后的进程可以移动而不必重写任意指针，但这种前提已经不适配现代 ISA、toolchain、JIT 和手写汇编。另一些系统通过 host OS、hypervisor，或在系统内部重新引入多个地址空间来保住兼容性。这样确实能恢复 POSIX 行为，却也放弃了 SASOS 最核心的收益：来自单地址空间的 lightweightness。论文因此提出一个更严格的问题：能否在保持单地址空间、保持 POSIX 语义、保持 isolation 的同时，让 SASOS 在 fork-heavy workload 上仍然优于传统 kernel？

## 核心洞察

论文最关键的判断是，SASOS `fork` 的难点不是复制字节，而是重定位 authority。如果 child 落在同一地址空间中的另一段虚拟地址范围里，那么从 parent 原样复制过来的绝对指针仍会指向 parent 的内存。一个正确的设计必须能可靠地区分“指针”和“普通数据”，并且只把那些跨越 protection boundary 的指针重新指向 child。

µFork 用 CHERI 让这件事变得可行。CHERI capability 自带 bounds 和 permissions，而且合法 capability 在内存里带 tag。把代码编译成 PIC 之后，大多数引用本来就是相对 stack、base pointer 或 program counter 的，不需要重写。真正需要处理的是散落在内存和寄存器中的绝对引用。µFork 可以借助 tag 识别这些引用，把它们重定位到 child 的区域，再依靠 CHERI bounds 保证这些引用不会逃出该区域。这样一来，“在单地址空间里实现 fork” 就不再只是 compiler 层面的设想，而是一个可执行的 runtime 机制。

## 设计

µFork 引入了 `µprocess` 这一抽象：它是一个类 POSIX process，但其内存只是在全局地址空间中的一段连续区域。执行 `fork` 时，kernel 先为 child 预留新的连续区域，再复制 parent 的 page-table entries，使 parent 和 child 初始时共享大部分 physical pages，同时复制 file descriptor 等进程资源，并创建一个带新 PID 的线程来运行 child。有些结构会被 eager copy，例如 allocator metadata 和 GOT，这样 child 一开始解析 global 和 heap state 时就会落到自己的区域中。寄存器里已有的绝对引用也会在 child 开始运行前被重定位。

真正与普通 CoW 不同的地方在于共享内存策略。传统 copy-on-write 不够用，因为 child 完全可能在任何一方写入之前，就先从共享页里读出一个 stale pointer。µFork 因此定义了 Copy-on-Access (CoA)：child 访问共享页时就可能触发复制与重定位；随后又把它优化成 Copy-on-Pointer-Access (CoPA)。在 CoPA 下，普通读取仍可共享，但如果 child 从共享页中加载 capability，该页必须先被复制。实现上，µFork 使用 CHERI 的 page-table bit，让 capability load 触发 fault。进入 fault path 后，系统分配私有页、复制内容、按 16-byte capability 粒度扫描整页，并把仍指向 parent 区域的 tagged capability 全部重定位。父子双方的写入也会像 CoW 一样触发复制。

Isolation 分为两层。`µprocess` 之间依赖 CHERI 的单调 bounds：进程无法伪造更大权限的 capability，而 CoPA 又保证 parent capability 不会悄悄泄漏给 child。用户代码与 kernel 之间则使用 sealed capability 进行 trapless system-call entry，去掉执行 privileged instruction 所需的权限，检查 syscall 参数，并把按引用传入的 buffer 复制到 kernel memory 中以阻止 TOCTTOU。论文特别强调，这套 isolation 是 parameterized 的：面对 privilege separation 可启用完整的 adversarial isolation；面对“代码可信但可能有 bug”的程序，可只保留 fault isolation；而像 Redis snapshot 这种 fully trusted workload，还可以关闭部分检查。

## 实验评估

原型构建在 Unikraft 之上，运行于 Arm Morello 的 CHERI 环境中，并与原生 CheriBSD 比较；对 Nephele 的比较则限于无法直接复现实验的部分。microbenchmark 先证明了核心主张。fork 一个最小进程时，µFork 延迟为 54 µs，CheriBSD 为 197 µs，Nephele 为 10.7 ms。一个被 fork 出来的最小进程在 µFork 上只占 0.13 MB，而 CheriBSD 为 0.29 MB，Nephele 为 1.6 MB。Unixbench 的 Context1 IPC benchmark 中，µFork 用 245 ms 完成，CheriBSD 则为 419 ms，这说明保住单地址空间的价值不仅体现在 `fork` 本身，也体现在 fork 之后的通信路径上。

应用实验让这个结论更扎实。对于 Redis background snapshot，µFork 在所有数据库大小上都更快：100 KB 时整体 save time 为 1.8 ms，对比 CheriBSD 的 3.4 ms；100 MB 时为 109 ms，对比 158 ms。数据库为 100 MB 时，fork 出来的 Redis child 在 µFork 上只消耗 6 MB，而 CheriBSD 为 56 MB。论文还单独拆开 CoPA 的收益：同样在 100 MB 数据库下，如果做完整同步复制，需要 23.2 ms 和 144 MB；CoA 降到 283 µs 和 101 MB；CoPA 则进一步降到 260 µs 和 6 MB。对于基于 MicroPython Zygote 的 FaaS benchmark，µFork 每秒可处理的函数数比 CheriBSD 高 24%，这正是 fork latency 主导的场景。Nginx 的结果更复杂一些：µFork 可以无修改运行 Nginx，并在单核下比单核 CheriBSD 高 9%，但论文也明确承认 Unikraft 当前不成熟的 SMP 支持限制了多核比较的说服力。

## 创新性与影响

相对于 segment-relative 的早期 SASOS，µFork 的新意在于它面向现代系统现实：它依赖 PIC 和 runtime relocation，而不是要求整个软件栈接受一种特殊 addressing model。相对于 Graphene 或 Nephele，它的创新在于架构上的“诚实”：系统并没有把 `fork` 外包给另一个 protection domain，而是真的把 child 保留在同一个地址空间里。相对于一般性的 isolation 工作，论文的贡献也不只是“用 CHERI”，而是把 CHERI tags、bounds 和 load barrier 组合起来，在一个地址空间中重建 POSIX `fork` 语义。

因此，这篇论文会同时被几个社区引用。SASOS 和 unikernel 研究者会把它当作第一个比较完整的透明 `fork` 路线图；CHERI 和 capability-system 研究者会看到一个超越 memory safety 的系统级落点；围绕 Redis snapshot、预热 language runtime、或 privilege-separated service 的系统工程师，则会看到 fork 依赖并不一定与 lightweight kernel 天生冲突。它既提出了新机制，也重新定义了“为 SASOS 提供 POSIX 兼容”应该意味着什么。

## 局限性

这个设计与 CHERI 绑定得很深，尤其是性能最好的版本。论文认为，其他 memory tagging 机制也许可以帮助识别指针，但它明确表示自己并不知道还有哪种非 CHERI 机制能像 CoPA 这样，对 capability load 精确触发 fault。因此，µFork 最优雅的实现今天并不能自然迁移到主流 commodity hardware 上。

原型还继承了 Unikraft 与其内存布局带来的工程约束。每个 `µprocess` 都占据一大段连续虚拟地址区域，所以对于长时间运行、频繁 fork、且每次都需要大块连续空间的 workload，fragmentation 仍可能成为问题。实现里使用静态分配的私有 heap，虽然简化了 TCB，却也放大了“full copy”基线的代价。Nginx 多核扩展的不足主要来自 Unikraft 当前的 big kernel lock SMP 现状，而不是 µFork 机制本身，因此并发能力虽然方向正确，但还没有被完全证明。最后，大多数实验都局限在 Morello/CHERI 上，而对 Nephele 的比较又有一部分是间接的。

## 相关工作

- _Heiser et al. (SPE '98)_ — Mungi 通过 segment-relative addressing 保持 single address space，而 µFork 面向现代 PIC toolchain，在运行时重定位 tagged absolute references。
- _Tsai et al. (EuroSys '14)_ — Graphene 通过借用 host OS 的 `fork` 来支持 multiprocess application，而 µFork 则把 `fork` 真正实现到 SASOS 内部。
- _Lupu et al. (EuroSys '23)_ — Nephele 通过 cloning unikernel VM 来模拟 `fork`，但 µFork 把 kernel 和 child 都保留在同一地址空间内，因此保住了更快的 IPC 和更低的 fork 开销。
- _Lefeuvre et al. (ASPLOS '22)_ — FlexOS 研究的是 library OS 内部如何组合多种 isolation mechanism，而 µFork 则在这一更广泛的 intra-address-space isolation 议程上进一步给出了具体的 POSIX `fork` 设计。

## 我的笔记

<!-- 留空；由人工补充 -->

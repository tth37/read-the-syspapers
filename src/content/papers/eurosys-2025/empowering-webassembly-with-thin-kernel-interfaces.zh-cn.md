---
title: "Empowering WebAssembly with Thin Kernel Interfaces"
oneline: "这篇论文不为 Wasm 另造一套 OS API，而是把稳定的内核 syscall 薄薄映射进去，让现有用户态软件靠重编译就获得可移植、可沙箱化的执行环境。"
authors:
  - "Arjun Ramesh"
  - "Tianshu Huang"
  - "Ben L. Titzer"
  - "Anthony Rowe"
affiliations:
  - "Carnegie Mellon University"
  - "Carnegie Mellon University, Bosch Research"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717470"
code_url: "https://github.com/arjunr2/WALI"
tags:
  - kernel
  - virtualization
  - isolation
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文的核心主张是，Wasm 想成为严肃的用户态虚拟化目标，并不需要再发明一套全新的低层 OS API。作者提出的 thin kernel interface 直接把稳定的 kernel syscall 暴露给 Wasm，同时保住 Wasm 的进程内沙箱、CFI 和 ISA portability；像 WASI 这样的高层 API 则上移为运行在 Wasm 里的库。Linux 原型 WALI 的接口开销很小，而且启动时延明显优于容器。

## 问题背景

Wasm 在 Web 之外已经具备不少系统研究者想要的底层性质：跨 ISA 可移植、二进制体积小、静态可验证、内存访问受沙箱保护、控制流天然受约束。真正卡住它进入边缘与工业场景的，不是执行格式，而是 system interface。现有最自然的答案是 WASI，但论文认为 WASI 的目标函数和这类场景并不一致：它是一套仍在演化的新 API，刻意偏离 POSIX，而且缺少 `mmap`、process、asynchronous I/O、signals 和 users/groups 等大量旧软件实际依赖的能力。

这并不是一个只影响新应用的小缺口。论文瞄准的是长寿命部署的 edge software stack、难以整体重写的 legacy Linux userspace，以及来自多个供应商的混合组件。如果 Wasm 只能运行已经为 WASI 重构过的软件，那么它就没法真正承接现有生态的移植与加固需求。

作者因此换了一个思路：既然真正被长期软件栈依赖的，是 kernel 与 userspace 之间那条 syscall 边界，为什么不直接把它变成 Wasm 的底层接口？他们先做了一个范围分析来支撑这件事并非天方夜谭。动态分析显示，很多应用用到的 unique syscall 不到 100 个，所有应用的并集大约也只有 140-150 个；而在 x86-64、aarch64、riscv64 之间，Linux 也有很大的公共 syscall 核心。这意味着问题规模远比想象中小。

## 核心洞察

论文最重要的洞察是：对 Web 之外的 Wasm 来说，最值得复用的抽象层不是一套新设计的可移植 OS API，而是早已稳定下来的 kernel syscall ABI。这个边界上方，libc、语言运行时和大量现有软件早就已经围着它构建；只要 Wasm engine 暴露一个足够薄的 syscall interface，很多程序需要的只是重编译，而不是改写成另一种编程模型。

这个设计同时把今天 WASI 混在一起的两件事拆开了。第一件事是安全快速地执行 Wasm bytecode；第二件事是 capability policy、filesystem mediation、socket abstraction 之类更高层的系统策略。论文主张前者应当留在 engine，后者则应该搬到 WALI 之上的 Wasm 模块里。这样做的价值不只是兼容旧软件，更是更好的 layering、更小的 trusted computing base，以及让不同 security model 共存的空间。

## 设计

Linux 版本的接口叫 WALI。它暴露大约 150 个 host functions，其中绝大多数与 Linux syscall 近乎一一对应，外加少数处理命令行参数和环境变量的辅助调用。大部分 syscall 都是 passthrough：engine 主要做两类翻译。其一是地址空间翻译，把 Wasm 线性内存中的指针参数映射到宿主进程地址；其二是 ABI layout conversion，用于处理不同 ISA 上内存布局不一致的结构体参数。论文指出，真正需要后一类重拷贝的 syscall 占比不到 10%。

真正需要系统性适配的是 memory model 和 signal/process model。由于 Wasm memory 是受边界检查的线性地址空间，WALI 不能把原生地址直接交给 guest，于是 `mmap`、`mremap`、`munmap` 被虚拟化到 Wasm 线性内存里：engine 按需扩展 memory、追踪映射区间，并在底层利用固定映射来维持旧有内存分配策略可用。这样很多依赖内存映射的 allocator 和应用就能不改源码继续工作。

进程与信号方面，论文提出了三档方案：最朴素的 1-to-1 process mapping、更激进的 N-to-1 lightweight process，以及面向未来的 threadless 方案。实际实现选了最简单也最稳妥的 1-to-1：每个 WALI process 对应一个原生 Linux process，线程则采用 Wasm 的 instance-per-thread 语义。异步信号处理则由 engine 维护 virtual sigtable、pending queue 与 bitset，并只在编译器插入的 safepoints 执行 handler；原型里采用 loop-header polling，在响应性与开销之间取折中。

跨平台支持的关键，是把 WALI syscall 集定义成多种 Linux 架构 syscall 的按名字并集，而不是按 syscall number 绑定。只要某个参数布局在不同 ISA 上不同，就在边界处做显式转换。安全模型上，WALI 不尝试在 syscall 层重新发明安全策略，而是尽量保留 Wasm 既有的进程内沙箱性质，把更复杂的动态策略留给上层。论文还给出了一些具体护栏，例如阻止访问 `/proc/self/mem`、禁止从模块里直接调用 `sigreturn`，以及不支持会破坏 Wasm 执行模型的 `setjmp`/`longjmp` 式非局部跳转。

## 实验评估

原型实现基于 WAMR，采用 1-to-1 process model 与 loop-header signal polling。作者实现了 137 个最常用的 Linux syscall，总共大约 2000 行 C，平台相关代码不到 100 行，并支持 x86-64、aarch64、riscv64。单看接口层，这已经证明 thin interface 的主张在工程上站得住。

最有说服力的是移植实验。借助面向 WALI 的 LLVM toolchain，作者成功编译并运行了一批现有软件，包括 `bash`、`lua`、`memcached`、`openssh`、`sqlite`、`make`、`vim`、`openssl`、`libevent`、`libncurses`、Linux Test Project 以及 `libuvwasi`。绝大多数程序都无需源码修改即可执行；少数问题主要来自 C 里本就未定义的函数指针类型不匹配，而 WALI 的 typed indirect call 恰好把这些问题暴露了出来。尤其值得注意的是，`libuvwasi` 在 WALI 上不改代码即可构建，并通过 22 个单元测试，这很好地证明了 WASI 确实可以被下沉为 WALI 之上的一层。

接口本身的开销很小。代表性 syscall 大多只比 native 多出几百纳秒；论文给出的宏基准结果里，WALI 本身在大多数程序中占总运行时间不到 1%，`memcached` 也只是到 2.4%。真正的异常项是 `clone`，开销约 500 微秒，但作者说明这主要来自 WAMR 为每个线程复制 Wasm 执行环境的内部实现，而不是 WALI 这个接口层本身。异步信号轮询如果放在 loop header 或 function entry，通常额外 slowdown 在 10% 以内；若每条指令都轮询，代价会飙到 10x 以上。

放到端到端虚拟化对比里，WALI 的位置介于 Docker 与 QEMU 之间。CPU 密集型执行时，它平均仍比 native 与 Docker 慢接近 2x，这更多反映的是今天 Wasm runtime 的成本；但它的启动只需几毫秒，而容器接近 0.5 秒，基础内存开销也显著低于 Docker 约 30 MB 的平台成本。论文的结论是，对短生命周期或对启动延迟敏感的应用，这个折中很有吸引力。

## 创新性与影响

这篇论文的创新点不只是把 Linux 软件搬到 Wasm 上运行，而是重新界定了 Wasm 用户态虚拟化应该站在哪一层。相对 WASI/WASIX，它拒绝把低层接口和安全模型捆死在一起；相对 containers 与 hypervisors，它只虚拟化 userspace，却换来了 Wasm 自带的 CFI、不可寻址执行状态和跨 ISA 可移植性。

这种 framing 的影响有两层。对 Wasm engine 来说，目标被明显简化了：先把一个稳定的 kernel interface 做扎实，再让 WASI 之类高层 API 作为 Wasm 代码在上面演化。对既有软件生态来说，它给出了一条更接近重编译而不是重写的迁移路径。论文里的 Zephyr 原型 WAZI 也强化了这一点：作者用同一套 recipe 在 Zephyr 上做出约 4200 行的实现，并在只有 384 kB SRAM 的 Nucleo-F767ZI 板子上跑通 Lua toolchain。

## 局限性

论文的概念外延比真正落地的系统更大。被完整实现和评估的只有最保守的 1-to-1 process model，而且只在 WAMR 这一种 engine 里测试；N-to-1 与 threadless 仍属于设计草图。WAZI 也只是验证可行性的 prototype，所以跨内核通用性更多是被初步证明，而不是被彻底坐实。

兼容性上也有明确边界。当前 toolchain 依赖 static linking，因为 Wasm 生态里的 dynamic linking 还不成熟；direct hardware access、`ucontext`/`mcontext`、`setjmp`/`longjmp` 式非局部控制流都不支持；某些 signal handler 还可能受到 host engine 自身内部机制的限制。最后，即便 WALI 自己足够薄，整体运行时性能仍然会继承今天 Wasm runtime 在 CPU-heavy workload 上的性能差距。

## 相关工作

- _Powers et al. (ASPLOS '17)_ - Browsix 在浏览器里的 JavaScript 上模拟 POSIX 风格环境，而 WALI 直接把接口下探到 Wasm 与 kernel 之间的边界。
- _Porter et al. (ASPLOS '11)_ - Drawbridge 为 Windows library OS 设计极小 ABI；WALI 与它一样追求薄接口，但选择复用既有 syscall 边界，而不是重新发明一套可移植 ABI。
- _Agache et al. (NSDI '20)_ - Firecracker 借助硬件辅助提供轻量虚拟化；WALI 则只做 userspace 级虚拟化，并把跨 ISA 可移植性交给 Wasm 本身。
- _Lefeuvre et al. (ASPLOS '24)_ - Loupe 讨论兼容层究竟该支持哪些 OS API；WALI 用非常相近的 syscall 频度分析，为其小而关键的支持集合提供依据。

## 我的笔记

<!-- 留空；由人工补充 -->

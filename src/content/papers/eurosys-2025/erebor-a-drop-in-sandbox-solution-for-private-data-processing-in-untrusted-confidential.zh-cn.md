---
title: "Erebor: A Drop-In Sandbox Solution for Private Data Processing in Untrusted Confidential Virtual Machines"
oneline: "Erebor 在 CVM 里再做一层按客户端划分的沙箱，既防 guest OS，也防服务程序自己外泄数据，而且不要求云厂商改 hypervisor。"
authors:
  - "Chuqi Zhang"
  - "Rahul Priolkar"
  - "Yuancheng Jiang"
  - "Yuan Xiao"
  - "Mona Vij"
  - "Zhenkai Liang"
  - "Adil Ahmad"
affiliations:
  - "National University of Singapore"
  - "Arizona State University"
  - "ShanghaiTech University"
  - "Intel Labs"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3717464"
code_url: "https://github.com/ASTERISC-Release/Erebor"
tags:
  - confidential-computing
  - security
  - virtualization
  - isolation
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文抓住了 CVM 的一个真空地带：TEE 能把 host 挡在外面，却拦不住 guest OS 和服务程序本身把客户数据带出去。Erebor 在 guest 内部放入一个很小的 privileged monitor，用它建立按客户端划分的 sandbox，把内存映射、软件退出路径和数据通信都收归监控，同时不要求 hypervisor 或 paravisor 配合改造。TDX 原型在真实 CPU 服务上带来的运行时开销是 4.5%-13.2%，而共享只读公共状态时，内存占用最多能降 89.1%。

## 问题背景

论文讨论的是很典型的 SaaS 场景：客户端把敏感输入交给云上的数据处理服务，服务提供商把程序部署在 confidential VM 里，云厂商负责底层机器。从客户端视角看，服务提供商和云厂商都只是诚实但好奇。于是，传统 CVM 的保护边界就不够了。TDX、SEV 这类机制能防 host 直接读 guest 内存，却不会自动阻止 guest OS、服务进程，甚至它们彼此串通后，把数据再转手泄露出去。

作者把风险拆成三类。第一类是 OS 主动取数：内核可以读进程内存、改页表、借中断或异常时机观察寄存器状态。第二类是程序直接外泄：服务程序自己发 syscall 或 hypercall，把数据写到磁盘、网络或者别的外部接口。第三类更隐蔽，是把数据编码进调用参数、调用频率或其他软件可控的退出行为里，形成 covert channel。换句话说，论文不满足于保护一个可信 enclave 不受 OS 侵犯，而是要在程序本身也不可信时，继续保护客户数据。

现有 CVM 方案并没有完全解决这个问题。Veil、NestedSGX 之类方案借助 VMPL 把敏感数据放进 enclave 式隔离区，确实能挡住 OS 直接读取，但 enclave 内部代码依旧被默认信任，程序仍能主动往外吐数据；而且这一路线还要求云厂商在 hypervisor 或 paravisor 侧配合。Erebor 想要的是更高一级的目标：既阻止外部读取，也阻止 sandbox 内部程序故意泄露，同时保持租户可自行部署的 drop-in 属性。

## 核心洞察

这篇论文最值得记住的判断是：解决问题不一定要再造一个 enclave 分区，也不必把整个 guest OS 都纳入 TCB。更可行的办法，是在 ring 0 里切出一个极小的 monitor，用 intra-kernel privilege isolation 把它和普通 guest kernel 分开，然后只让它独占那些真正决定机密性边界的接口，例如页表与 MMU 状态、关键 CR/MSR、异常和中断入口、以及 guest-host communication。

一旦这几点被 monitor 握住，普通 Linux 内核就不再是根信任，而只是一个被去特权化的服务层。这样做的好处很实际：sandbox 里依然可以运行服务提供商的程序，也可以配一个 LibOS 维持原有运行体验，但在客户数据进入以后，所有普通 syscall、同步 VM exit 和用户态可控中断都可以被切断。Erebor 因而不是一个单纯把内存围起来的 compartment，而是一个把数据处理过程整体关进笼子的 sandbox。

## 设计

Erebor 由两个核心部件组成：处在 guest kernel 特权路径上的 Erebor-Monitor，以及面向每个客户端请求的 Erebor-Sandbox。系统通过两阶段启动建立 monitor。第一阶段先加载 firmware 和 monitor，并让它们进入 attestation measurement；第二阶段由 monitor 去加载已经去特权化的 Linux kernel，并验证其中敏感指令已经被删掉或改写。像 CR/MSR 写入、IDT 装载、`stac`、`tdcall` 这类操作都不能再由内核直接执行，而必须经由 Erebor-Monitor-Call。

真正有意思的地方是这些硬件特性的组合方式。PKS 用来保护 monitor 自己的内存以及页表控制路径，SMEP 和 SMAP 阻止普通内核去执行或读取不该碰的用户页，CET 的 indirect branch tracking 让进入 monitor 的控制流只能走固定入口，外加专门的 interrupt gate，保证一旦中断打断 monitor 执行，临时授予的 monitor 内存权限会先被撤销，再把控制权交回 OS。monitor 同时对内核代码维持 W^X，并接管仍被允许的动态代码验证路径。

Sandbox 里的内存分成 confined 和 common 两类。confined 区域保存代码、堆、栈、临时文件以及客户数据，只允许所属 sandbox 读写；common 区域用来放可共享的大对象，例如模型、数据库或共享库，多个 sandbox 可以映射，但在客户数据装入后，对 sandbox 来说只剩只读权限。confined 页被 pin 住，避免秘密通过换页路径泄露；DMA 视图则通过 monitor 对 GHCI 的控制被收紧，保证 sandbox 内存一直保持 private。

运行时层面，Erebor 用一个基于 Gramine 改出来的 LibOS，在 sandbox 内部承担堆管理、内存文件系统、线程、同步和 I/O 辅助逻辑。客户数据一旦到位，monitor 就封死软件可控退出路径：syscall、同步 VM exit、user interrupt 都会直接导致 sandbox 被杀掉。普通时钟或设备中断仍允许发生，但流程变成先由 monitor 保存并清空 sandbox 上下文，让 OS 去处理，再由 monitor 恢复执行。`cpuid` 是个例外，monitor 会向 hypervisor 取一次结果并缓存。输入输出则通过 attestation 建立的 monitor-client 安全通道进入系统，再借一个保留的 `ioctl` 接口在 monitor 与 LibOS 之间搬运；输出长度会做 padding，sandbox 销毁时内存会被清零。

## 实验评估

实验做得比较有层次。作者不仅和 native CVM 比，还给出 LibOS-only、只开内存隔离、只开退出保护等拆分实验，因此能看清主要成本分别落在哪。机制级别上，一个空的 Erebor monitor call 需要 1224 cycles，而空 syscall 是 684 cycles，TDX 的 `tdcall` 是 5276 cycles。最贵的是页表更新：native 只要 23 cycles，经 Erebor 后涨到 1345 cycles，也就是 58.5 倍。这听起来很大，但论文没有回避，而是进一步说明这种成本大多发生在初始化或少量控制路径里，是否可接受要看端到端 workload。

端到端结果总体是站得住的。五个真实服务 workload，`llama.cpp`、YOLO 图像处理、Drugbank 查询、GraphChi PageRank 和 Unicorn 入侵检测，运行时开销落在 4.5%-13.2%，几何平均为 8.1%。拆分结果也很有信息量：单独引入 LibOS 平均只增加 1.7%，内存视图隔离和退出保护分别贡献 3.6% 与 3.9%。最高的是 `llama.cpp` 的 13.15%，原因是共享模型大、page fault 多、同步更频繁。另一方面，common memory 共享带来的收益非常显著：内存占用缩减范围是 0.15x-9.2x，最高节省 89.1%；论文举的例子是把 8 个各自复制约 4 GB 模型的实例，从约 36 GB 压到约 8 GB。

评估也把代价讲清楚了。LMBench 里某些 system event 的时延最多上升 3.8 倍，初始化时间会增加 11.5%-52.7%，因为预分配和 page fault 都要走 monitor。即使是不在 sandbox 里的后台服务，也会承受一些系统级副作用：OpenSSH 平均吞吐下降 8.2%，Nginx 下降 5.1%。这些结果支持论文的核心结论，即 Erebor 是 practical 的，但并不意味着它对所有工作负载都便宜。还有一个需要记住的点是，原型用 DebugFS 模拟通信通道，而不是完整的生产级网络 relay，所以 I/O 路径的实证还不算最终形态。

## 创新性与影响

Erebor 的创新，不只是又做了一个 CVM monitor，而是把两条原本分开的路线拼到了一起：一条是 intra-kernel privilege separation 这类 OS 机制，一条是防程序主动外泄的 anti-exfiltration sandbox 目标。和 Veil 相比，Erebor 改写了默认信任边界，不再把处理客户数据的服务代码视为可信组件；和 Ryoan、Chancel 这类 SGX 时代的方案相比，它把类似的安全目标搬到了 CVM 里，而且不依赖 compiler-enforced SFI，也不需要云厂商先提供新的分区支持。

这让它对两个社区都有吸引力。对 confidential computing 而言，它给出了一个介于「每个客户单独一台 VM」和「把希望寄托给 enclave 内部代码自律」之间的折中点。对 OS 与 virtualization 研究者来说，它说明 guest 内部的一小段 monitor，只要握住正确的控制接口，就足以把普通 kernel 从 TCB 里剥离出来。更重要的是，这篇论文既提出了一个具体机制，也提出了一种更强的 framing：CVM 里的目标不该只是 memory encryption，而应该是完整的数据处理沙箱。

## 局限性

离真正的生产系统，它还有明显距离。论文只支持 CPU workload，GPU 或其他加速器、可信设备 I/O、数字时序 side channel、微架构 side channel 都被放到了未来工作。通信通道的实现目前也不是实际网络栈，而是 DebugFS 模拟。设计里原本希望使用的 CET backward-edge 保护，因为 Linux 支持还不完整，没有在原型中真正落地。

兼容性边界同样不能忽视。为了简化细粒度权限控制，当前实现关闭了 huge pages、loadable kernel modules 和 eBPF。应用虽然不需要大改，但仍要围绕 monitor 暴露的 `ioctl` 做少量源码调整；LibOS 也采用单地址空间和预创建线程模型。最后，实验主要拿 native CVM 和自身 ablation 做对比，没有与 VMPL 路线的系统做直接 apples-to-apples 比较，因此论文更有力地证明了自己可行且威胁模型更强，而不是全面证明它优于所有替代方案。

## 相关工作

- _Ahmad et al. (ASPLOS '24)_ - Veil 也想在 CVM 内保护数据，但它默认 enclave 内代码可信，而且依赖 VMPL 分区；Erebor 则把服务程序本身也放进威胁模型，并坚持 guest-side drop-in。
- _Hunt et al. (OSDI '16)_ - Ryoan 在概念上最接近，它同样追求防止程序主动带出秘密，只是依赖 NaCl 风格的 software fault isolation，而不是 CVM 内的 privileged monitor。
- _Ahmad et al. (NDSS '21)_ - Chancel 展示了 adversarial SGX 代码下的高效多客户端隔离与共享内存；Erebor 把这一目标迁到 confidential VM，并改用页表与退出路径控制来实现。
- _Dautenhahn et al. (ASPLOS '15)_ - Nested Kernel 提供了 Erebor 最接近的机制原型，即 intra-kernel privilege separation；Erebor 则把它从 kernel hardening 推进到 confidential data sandboxing。

## 我的笔记

<!-- 留空；由人工补充 -->

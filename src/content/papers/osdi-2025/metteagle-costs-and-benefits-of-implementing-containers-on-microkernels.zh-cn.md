---
title: "MettEagle: Costs and Benefits of Implementing Containers on Microkernels"
oneline: "MettEagle 在 L4Re 上把容器实现为 capability-based compartments，用更小的 TCB 取代 Linux 式加固，并在许多工作负载上接近 Linux 容器且启动更快。"
authors:
  - "Till Miemietz"
  - "Viktor Reusch"
  - "Matthias Hille"
  - "Lars Wrenger"
  - "Jana Eisoldt"
  - "Jan Klötzke"
  - "Max Kurze"
  - "Adam Lackorzynski"
  - "Michael Roitzsch"
  - "Hermann Härtig"
affiliations:
  - "Barkhausen Institut, Germany"
  - "Leibniz-Universität Hannover, Germany"
  - "Kernkonzept GmbH, Germany"
  - "Technische Universität Dresden, Germany"
conference: osdi-2025
tags:
  - kernel
  - isolation
  - security
  - serverless
  - datacenter
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

MettEagle 追问的是一个很基础的问题：如果底层 OS 不是 monolithic kernel，而是 capability-based microkernel，那么容器隔离是否会天然更简单、更安全？论文给出的答案在架构上是肯定的，在工程上也基本成立：在 L4Re 上，container-style compartment 不再需要 Linux 式的 seccomp 与 namespace 加固，TCB 明显更小，而且启动时延显著优于 runC，同时多数 serverless 工作负载的端到端性能仍能接近 Linux 容器。

## 问题背景

这篇论文首先指出了 mainstream container 的一个尴尬事实：在 Linux 上，容器并不是一种与进程本质不同的抽象，而更像是“事后被加固过的进程”。原因在于 monolithic kernel 默认就给应用进程暴露了大量 ambient authority。为了把这些原本不该拥有的权限重新收回去，容器运行时必须额外依赖 seccomp-bpf 来限制 system call，用 namespaces 来限制可见性，再用 cgroups 来约束资源。它们当然有用，但也会把更多复杂性塞进共享 kernel，使互不信任租户之间共享的攻击面更大。

由此，论文提出了一个更根本的问题：如果 microkernel 从一开始就遵循 principle of least authority，那么 container-grade isolation 能否直接建立在普通 process 之上，而不需要 Linux 那套后补式加固？难点在于，这不只是一个安全论证。Microkernel 通常被联想到嵌入式或静态配置环境，而不是运行动态云工作负载的大型服务器。因此作者还必须证明，这种 capability-based 设计不仅概念上更干净，而且真的能支持容器所需的功能、能运行现实软件栈，并在 FaaS 这类场景里保持有竞争力的性能。

## 核心洞察

论文的核心判断是：Linux 容器里那些看似必须由内核专门实现的隔离机制，在 microkernel 上大多可以改写成“向普通进程精确委派能力”的问题。只要任务启动时没有任何 authority，只拿到自己被允许访问的那些 capability，那么接口限制、可见性限制，以及大部分资源控制，都不再是内核级的全局加固机制，而变成了 session 构造与 capability 分发的问题。

这个重构同时改变了安全边界和系统结构。安全性提升的原因在于，compartment 只需要信任 microkernel 以及它实际使用到的系统服务，而不是一个包含大量无关子系统的大型共享 kernel。实现结构也因此更模块化：Linux 需要通过 namespaces、seccomp 和 cgroups 让一个内核同时理解多种资源类型；MettEagle 则把不同资源封装成不同服务的 session，再通过受限 IPC endpoint 只暴露给 compartment 必需的数据面与控制面。

## 设计

MettEagle 运行在 L4Re 之上，由两个核心部分构成。低层的 compartment service 类似 Linux 中的 runC，负责创建、启动和清理隔离执行环境；高层的 Phlox 则提供偏 FaaS 的抽象接口，用来预分配资源并发起 compartment 启动请求。围绕这两个核心，作者又构建了一组原生 L4Re 服务，包括可写的内存文件系统 SPAFS、网络服务 LUNA、并行内存管理器 LSMM，以及并行化 boot file system 的 PROMFS。

Compartment 的生命周期本质上是一条 capability 流。收到启动请求后，Phlox 会先向所需系统服务创建 session。每个 session 会返回一个 IPC gate capability，并把该 session 的资源限制绑在这个 gate 上。随后，Phlox 把这些收集到的 capability 一并交给 compartment service，由后者把 capability 委派到新 compartment 的任务中，启动任务，并在结束时通过 revoke 剩余 capability 来回收资源。这就是论文把“容器启动”翻译成 capability system 操作序列的具体方式。

最值得看的部分，是 Linux 容器三类隔离机制在 L4Re 上的对应关系。可见性限制通过 capability 集合和私有 namespace 实现：compartment 中所有任务共享一组经过挑选的 capability，并通过 namespace 把诸如 `"/usr"` 之类的名字映射到这些 capability。由于 L4Re 没有全局 PID 空间，也没有共享内存键，一些 Linux 必须额外虚拟化的层次在这里直接消失。System-call restriction 也不需要 seccomp 对应物：服务会分别暴露 control-plane 与 session data-plane 的 IPC gate，而不受信任的 compartment 只拿到后者。资源限制同样下推到各个服务的 session 中，以 memory、CPU placement、network bandwidth 等具体 quota 的形式表达，而不是像 cgroups 那样用一个统一框架覆盖所有资源。

实现部分说明，这套架构虽然概念更简洁，但仍然需要大量工程工作。作者没有在每个 compartment 下再嵌一层 L4 Linux VM，因为那会抬高 TCB，也会抵消 lightweight isolation 的意义。相反，他们移植了 10 Gbit NIC driver 与简单的 UDP/IP stack，通过交叉编译路径让 Python 3 跑在 L4Re 上，并对内存管理、boot file service 和若干热路径做了并行化与去关键路径优化，例如避免在热路径上做 capability revocation 与 thread 创建。

## 实验评估

实验同时覆盖安全与性能两个维度。安全方面，作者给出的 MettEagle TCB 总规模是 89,271 SLOC；对比之下，Linux 侧把 kernel、NIC driver、containerd 和 runC 合起来大约是 270 万行代码。随后，作者又研究了 33 个与 seccomp-bpf、namespaces 和 cgroups 有关的高危或严重 Linux CVE。这个分类当然是定性而不是形式化证明，但仍然有解释力：其中 12 个被作者判定为 fully mitigated，16 个 partially mitigated，5 个 not mitigated。最强的一类结论出现在 seccomp 与 eBPF 上，因为 capability-based access control 直接替代了驻留在 kernel 内的过滤解释器；较弱的一类则出现在 namespace 或具体资源服务的实现错误上，因为这些问题仍可能在 userspace service 中以别的形式出现。

性能结果则呈现出一种很健康的 prototype 气质：有明显亮点，也有清楚暴露的瓶颈。单个空 compartment 的冷启动时延约为 1 ms，显著快于 runC 的约 70 ms，但仍慢于普通 Linux process。在 64 个并发启动下，L4Re 上升到约 100 ms，而 runC 达到约 200 ms。网络方面，UDP ping latency 在各平台上都约为 40 微秒。单线程带宽上，L4Re 只有大约 350 MiB/s，而 Linux 约为 900 MiB/s，因为原型没有实现 receive-side scaling，driver processing 也集中在单核；但随着并行 socket 增多，L4Re 最终可以跑到 line rate，而 Linux 吞吐反而下降。

应用层实验使用 SeBS 的 Python function，这对 microkernel 很不友好，因为它会触发大量文件操作、内存分配与动态加载。即便如此，在顺序执行的大多数 benchmark 上，MettEagle 的端到端时延与 runC 相差不超过 15%，而在 HTML benchmark 上甚至快约 10%。在 16 路并发 burst 模式下，empty function 和 HTML 依旧与 runC 接近，但 ZIP 和 graph workloads 会慢一到两倍。作者把这部分损失主要归因于文件系统，而不是 compartment 机制本身：例如一次 `stat` 在 L4Re 上约需 4 微秒，而在 Linux 上只有约 460 纳秒。

## 创新性与影响

这篇论文的创新点不只是“把容器搬到 microkernel 上”。更重要的是，它系统性地说明了 Linux 容器的三种典型隔离机制怎样映射到 capability system，然后用一个真实原型以及与 runC、Firecracker-backed Kata 的对比实验，把这种映射从理念落实到工程。相对于 _Shen et al. (ASPLOS '19)_ 和 _Li et al. (ATC '22)_ 这类工作，MettEagle 不是在 Linux 安全模型外面再叠更多层，而是试图让底层 process abstraction 本身就足够安全，从而让许多加固层失去必要性。对于 cloud isolation、serverless runtime，以及 “microkernel 能否在大机器上实用” 这场长期争论，这都是一篇有分量的实证论文。

## 局限性

论文的局限也很明确。首先，安全证据主要是 proxy metric，而不是 exploit resistance 的形式化证明；在被研究的 33 个 CVE 中，也有 5 个被明确归为 not mitigated。其次，当前实现依赖一套相对简单的原生服务栈：不支持 OCI image，不包含 warm start 优化，没有 disk-backed file system，且对依赖 `fork` 的工作负载无能为力。Capability map/unmap、文件系统延迟，以及 `moe` 中仍由单锁保护的部分，都是已经被作者点名的瓶颈，因此论文更像是在证明“这种设计可以成立”，而不是“这个平台已经完成打磨”。

另外还有一些论文只讨论、未完全解决的风险。Timing-based attack 的缓解主要是基于 L4Re kernel 更小、且具备 real-time 特性的论证，但并没有给出实测验证。网络栈只有在足够并行时才能掩盖单核 fast path 的弱点。最后，如果未来为了进一步缩小共享状态而为每个 compartment 单独部署更多服务实例，内存占用可能会明显上升，而这部分成本仍留待后续工作评估。

## 相关工作

- _Biggs et al. (APSys '18)_ - 这篇论文从总体上论证 microkernel-based system 的安全优势，而 MettEagle 把这一论点落实成了带有实测数据的容器架构。
- _Manco et al. (SOSP '17)_ - 基于 unikernel 的 lightweight VM 同样试图缩小 TCB 并降低启动开销，但它把 OS 与应用揉进同一个 guest；MettEagle 则在 OS 内保留了 process-level compartmentalization。
- _Shen et al. (ASPLOS '19)_ - X-Containers 通过重构 Linux 容器周边层次来提升性能与隔离性，而 MettEagle 的做法是改变底层 OS 模型，让 process 从一开始就遵循 least authority。
- _Van't Hof and Nieh (OSDI '22)_ - BlackBox 通过 virtualization 与 sanitization 保护容器免受不可信 OS 的影响，而 MettEagle 直接尝试缩小特权 OS 的攻击面。

## 我的笔记

<!-- 留空；由人工补充 -->

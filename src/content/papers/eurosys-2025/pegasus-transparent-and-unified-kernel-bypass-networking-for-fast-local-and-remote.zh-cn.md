---
title: "Pegasus: Transparent and Unified Kernel-Bypass Networking for Fast Local and Remote Communication"
oneline: "Pegasus 把共生 Linux 进程装进同一个受保护 monitor，让未修改二进制同时拿到本地 TCP 快路径和远端 NIC bypass。"
authors:
  - "Dinglan Peng"
  - "Congyu Liu"
  - "Tapti Palit"
  - "Anjo Vahldiek-Oberwagner"
  - "Mona Vij"
  - "Pedro Fonseca"
affiliations:
  - "Purdue University"
  - "Intel Labs"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696083"
tags:
  - networking
  - datacenter
  - scheduling
  - isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pegasus 的出发点很明确：既然云应用已经被拆成大量频繁互调的进程和 sidecar，那优化通信就不能只盯远端 NIC，也得把同机通信一起纳入 kernel bypass。它把一组 symbiotic Linux 进程装进同一个受保护的用户态 monitor 里，本地 TCP 走共享内存快路径，远端流量走 DPDK 支撑的 bypass 栈，因此在不改二进制的前提下，把本地吞吐提升 19%-33%，远端提升 178%-442%，混合通信场景提升 222%。

## 问题背景

这篇论文抓住的是微服务和 service mesh 带来的一个现实后果：应用拆分之后，通信成本不再只发生在跨机 RPC 上，连同一台机器里的 sidecar、proxy、backend 之间，也会被 Linux kernel 反复拖慢。传统内核路径的问题不只是网络栈复制和协议处理，还包括调度、唤醒、模式切换这些控制面成本。作者用一个很直观的数字说明这一点：Linux 上一次 futex 唤醒平均要 1.37 us，这已经接近甚至超过一些快网场景下的网络往返级别。

现有方案大多只解一半。共享内存能让本地数据路径更快，但同步仍要经过 futex 和内核调度；远端 kernel-bypass 系统又常常要求应用改写成新 API、换线程模型，或者受限于特定语言/runtime。这样一来，开发者要么接受大规模迁移成本，要么继续被 POSIX 兼容路径上的通信开销束缚。Pegasus 想解决的就是这个缺口：在保留 Linux ABI 的同时，把本地和远端通信都从 kernel critical path 上拿掉。

## 核心洞察

Pegasus 最值得记住的判断是，真正该被统一优化的对象不是某一类 socket 调用，而是一组频繁互相通信、逻辑上属于同一应用的进程。只要把这些 symbiotic processes 融合进同一个地址空间，再由一个受保护的 monitor 接管调度、内存和 socket 中介，系统就能透明决定某条 TCP 连接应该落到哪条快路径上：同机通信改写成共享内存消息传递，跨机通信切到 bypass NIC 的用户态网络栈，而应用本身仍然只看到熟悉的 Linux 进程和 socket 语义。

关键不在共享内存本身，而在把控制路径一起搬出来。很多系统把数据复制优化掉了，却仍然把阻塞、唤醒和切换交给 kernel，于是收益被同步成本吃回去。Pegasus 通过 `vProcess` 和 `vThread` 把这些动作也放到用户态 monitor 里，所以一个服务给另一个服务发消息时，接收方能沿着消息关键路径被直接调度起来，而不是先掉进内核再绕回来。

## 设计

Pegasus 把多个应用放进同一个 Linux 进程里运行，但不会让它们失去逻辑隔离。每个程序都会变成一个 `vProcess`，其线程对应为 `vThread`。用户态 ELF loader 负责创建这些抽象，把 PIE binary 及其 dynamic linker 装进各自的内存区域，再从 Linux ABI 层面启动它们，因此应用无需改源码。

调度和资源管理则由一个偏 OS 风格的 monitor 接手。Pegasus 在用户态维护每个 worker 的 run queue 和 wait queue，调度策略近似 CFS。像 `futex`、`read`、`clone` 这种可能阻塞的点会触发 cooperative scheduling；`SIGALRM` 用来做周期性抢占，`SIGURG` 负责跨核抢占。隔离这部分，Pegasus 结合 Intel MPK 与 uSwitch 的隐式 kernel context switching：monitor 自己占一个 domain，每个应用占一个 domain，mode-switch gate 会严格更新 `PKRU`、栈和 kernel resource 选择，避免故障进程跳进 monitor 或其他 `vProcess`。

透明性来自更细的 syscall 中介。Pegasus 给每个 domain 配 Seccomp filter，把关键 syscall 拦下来；但它不想为每次调用都付出一次信号开销，于是先用 `LD_PRELOAD` 接住 libc wrapper，再对直接出现的 `syscall` 指令做首次触发后的运行时重写。文件描述符也会被虚拟化，所以本地快路径 socket 仍然可以占据普通 fd 编号，不会破坏应用假设。

在这些基础设施之上，Pegasus 提供两条通信快路径。对本地通信，如果两个被融合的进程通过本地 TCP 地址连接，Pegasus 会把连接透明切到共享 ring buffer，让发送消息退化成写共享内存，并直接调度接收任务继续执行。对远端通信，它继续拦截常规 socket API，但把实现转交给 F-Stack/DPDK 后端，因此应用无需采纳新网络 API 也能用上 kernel bypass。`io_uring` 则负责补位文件、定时器和阻塞等待，也在没有远端 bypass 后端时充当默认实现。

## 实验评估

实验跑在两台 CloudLab r6525 机器上，每台有双路 2.8 GHz AMD EPYC 7543、256 GiB 内存和 Mellanox ConnectX-6 100 Gbps NIC。作者评估的对象不是玩具程序，而是 Redis、Nginx、Memcached、Caddy、Node.js，以及带 Istio sidecar 的部署。

本地通信部分最能说明它不是单纯把 copy 变快，而是把控制路径一起重写了。futex 唤醒从 1.37 us 降到 0.49 us，condition variable 唤醒从 1.51 us 降到 0.56 us。协议级延迟也明显下降：TCP echo 从 7.8 us 到 1.2 us，Redis `SET` 从 11.0 us 到 4.8 us，Memcached `set` 从 10.3 us 到 3.7 us。到了真实应用，Node.js + Redis + Nginx 的 web app 峰值吞吐提升 19%，Istio sidecar 场景提升 33%。在反向代理实验里，当所有请求都穿过 proxy 时，Pegasus 吞吐最高提升 74%，说明它最适合那类本地通信本来就很重的部署。

远端通信结果则表明，Pegasus 虽然不是绝对最低延迟的 datapath，但在保持透明性的同时已经非常接近专用系统。TCP round-trip latency 从 Linux 的 27.78 us 降到 13.88 us，只比 F-Stack 多 1.91 us。Redis 达到 801 KQPS，相比 Linux 的 189 KQPS 高 323%，比 Demikernel 高 153%，仅比 F-Stack 低 1.5%。Nginx 和 Memcached 的峰值吞吐分别比 Linux 高 178% 和 442%，整体落在 Junction 与 F-Stack 同一档位。

最有说服力的是混合通信实验：一个 Caddy 静态文件服务器前面挂一个 Nginx TLS reverse proxy。Linux 只有 12.1 KQPS，Pegasus 达到 39.0 KQPS，也就是 222% 提升。若只开远端快路径，吞吐是 16.8 KQPS；只开本地快路径则是 20.4 KQPS。两者一起开时效果基本叠加，说明 Pegasus 的统一设计不是概念包装，而是真把本地和远端优化组合起来了。

## 创新性与影响

Pegasus 的新意，不是再做一个支持 POSIX 的用户态网络库，而是把 Linux ABI 兼容、本地通信 bypass、远端 kernel bypass、以及进程内隔离当成同一个系统设计问题来处理。和 _Fried et al. (NSDI '24)_ 的 Junction 相比，Pegasus 多了受保护的 monitor 和真正的本地快路径，而不是让融合后的程序 fate-sharing，并把所有流量都压到 NIC 路径上。和 _Ousterhout et al. (NSDI '19)_ 的 Shenango、_Zhang et al. (SOSP '21)_ 的 Demikernel 相比，它坚持支持未修改的 POSIX/Linux 二进制，而不是要求开发者改线程或 socket 接口。和 _Li et al. (SIGCOMM '19)_ 的 SocketDirect 相比，它不只优化共享内存传输，还把调度和唤醒决策一起搬进用户态。

这让 Pegasus 对 service mesh、反向代理、sidecar-heavy 平台和容器运行时都很有参考价值。即便未来未必人人直接部署 Pegasus，这篇 paper 也把问题重新框定清楚了：如果一个系统号称服务于现代云应用，却把本地 IPC、ABI 透明性和隔离当作可选项，它就得解释为什么。

## 局限性

Pegasus 的透明性有明显边界。程序必须是 PIE，可执行时不能依赖固定地址映射，也不能通过 `fork` 复制整个地址空间；作者直接点名 Apache、Bash 这类重度依赖 `fork` 的程序目前不适合。它提供的隔离也主要是功能隔离，不是抗 side channel 的多租户隔离，而且 MPK 设计天然受限于最多 16 个 protection domains，可容纳的隔离 `vProcess` 数量有限。

远端路径还带着 F-Stack 的包袱。只要远端 kernel-bypass 后端启用，F-Stack 不支持的 netlink、netfilter、virtual network interfaces 之类能力也就用不上了；一些 OS 功能仍然要回退到 Linux 内核，因此 sampled system calls 里还能看到 6%-178% 的虚拟化额外开销。论文同样没有深入回答多租户部署或性能隔离问题，而是默认这些被融合的进程来自同一租户、确实彼此共生。

## 相关工作

- _Fried et al. (NSDI '24)_ - Junction 也追求 Linux ABI-compatible kernel bypass，但 Pegasus 额外提供受保护的进程内隔离，以及不经过 NIC 的本地 TCP 快路径。
- _Ousterhout et al. (NSDI '19)_ - Shenango 把调度与网络栈移到用户态来服务低延迟数据中心负载，而 Pegasus 的区别在于保留未修改 Linux 二进制的接口面。
- _Zhang et al. (SOSP '21)_ - Demikernel 提供面向微秒级数据中心系统的 datapath OS 与新 API；Pegasus 接受一点点额外延迟，换来零移植成本。
- _Li et al. (SIGCOMM '19)_ - SocketDirect 主要加速兼容的本地 socket 通信，Pegasus 则把这一路线扩展成同时覆盖远端 bypass 和用户态进程虚拟化的一体化框架。

## 我的笔记

<!-- 留空；由人工补充 -->

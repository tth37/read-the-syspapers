---
title: "Enabling Fast Networking in the Public Cloud"
oneline: "Machnet 只依赖主流公有云共同支持的最小 vNIC 特性集，并用基于 RSS 的随机化流映射与 sidecar 运行时，把低延迟用户态网络带进云 VM。"
authors:
  - "Alireza Sanaee"
  - "Vahab Jabrayilov"
  - "Ilias Marinos"
  - "Farbod Shahinfar"
  - "Divyanshu Saxena"
  - "Gianni Antichi"
  - "Kostis Kaffes"
affiliations:
  - "University of Cambridge and Huawei, Cambridge, United Kingdom"
  - "Columbia University, New York, USA"
  - "NVIDIA, London, United Kingdom"
  - "Politecnico di Milano, Milan, Italy"
  - "The University of Texas at Austin, Austin, USA"
  - "Queen Mary University of London, London, United Kingdom"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790158"
code_url: "https://github.com/microsoft/machnet"
tags:
  - networking
  - virtualization
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文的核心主张是：公有云 vNIC 不是“稍弱一点的裸机 NIC”，而是一种应该被单独建模的平台。Machnet 先定义跨 Azure、AWS、GCP 都成立的最小特性集，再围绕它做 sidecar 式用户态网络栈，并用名为 `RSS--` 的随机化握手机制补回多核流放置能力。结果是，它在云 VM 中做到了接近特化系统的延迟，同时明显优于 Linux TCP。

## 问题背景

论文指出，现有高性能用户态网络栈难以直接搬进公有云 VM，并不只是“还没适配好”，而是默认前提就不成立。eRPC、TAS 以及许多 libOS 风格系统都建立在 flow steering、可编程 RSS、深 RX 队列、直接从应用内存 DMA 等裸机 NIC 功能之上。但云租户在 VM 里拿到的是经过网络虚拟化包装后的 vNIC。为了兼容多代硬件并维持统一接口，云上真正稳定暴露给租户的只是更弱的一组能力。作者在三大云上归纳出的共同子集只有：基础报文 I/O、不可见也不可改的 opaque RSS、每核最多一个队列对，以及每个队列仅 `256` 个 descriptor。

软件执行模型同样不合适。libOS 方案常常要求一个应用独占 NIC，并让每条线程绑定一个队列持续 busy-poll。现实中的云 VM 却经常同时跑多个进程、多种语言运行时，以及远多于核数的线程。因此，论文要解决的不是单纯“如何让包更快”，而是如何在不依赖特权 NIC 功能的前提下，把低延迟用户态网络做成一种对公有云 VM 真正可移植、也真正可用的能力。

## 核心洞察

论文最值得记住的洞察是：公有云里的正确抽象不是“现代 NIC 能做什么”，而是“所有云 vNIC 稳定保证了什么”。只要网络栈先围绕这个 LCD 设备模型建立起来，剩下的问题就收缩成：如何在 opaque RSS 与一层共享内存 IPC 之上，补回足够的结构来维持低延迟。

作者认为这件事可行，靠的是两个观察。第一，公有云的端到端网络时延本来就比小型裸机集群大，因此 sidecar 多出的一次共享内存跳转并不致命；论文测得这一步单向约 `250 ns`。第二，虽然云 NIC 不暴露 RSS key，也不允许改 RSS 表，但 opaque RSS 仍然保留了“同一 flow 会稳定落到同一个队列”的性质。Machnet 在连接建立阶段通过随机化 UDP 端口不断试探，直到报文命中目标 engine 队列，也就是把原本依赖 NIC 硬件控制的确定性流放置，换成冷路径上的概率式流放置。

## 设计

Machnet 由两个部分组成：一个拥有 NIC 的 userspace sidecar 进程，以及应用侧链接的 shim library。应用通过隔离的共享内存通道与 sidecar 交换消息，shim 暴露类 BSD socket API，例如 `bind`、`listen`、`connect`、`send`、`recv`。这不是为了宣称“无需修改即可兼容”，而是为了把改动尽量收敛在网络层。

在传输层，Machnet 选择“跑在 UDP 之上的可靠消息传输协议”。作者的理由是公有云 SDN 会让新连接进入较慢控制路径，所以系统更偏向复用连接而不是大量短连接喷洒。它支持分片、重组、选择确认、有序交付、最多 `8 MB` 的消息，以及单 flow 下多个并发在途消息。

最有新意的机制是 `RSS--`。Machnet 采用每核一个 engine 的 shared-nothing 架构，因此每个 flow 必须在通信两端都落到指定 engine 上。由于云 vNIC 只给 opaque RSS，Machnet 在握手时不断尝试随机化 UDP 端口，让 SYN 和 SYN-ACK 去试探目标队列。作者再把逻辑 flow 标识和 UDP 四元组解耦，这样正反两个方向可以使用不同的成功端口对，从而把 `4x4` engine 配置下 `95%` 成功率的代价降到约 `25` 个包，`8x8` 约 `55` 个。围绕这一核心，系统还做了几项务实取舍：用 DPDK 而不是云上难以启用 zero-copy 的 AF_XDP，支持 blocking receive 以适应过订阅 VM，并在平台额外暴露能力时 opportunistically 启用更强的 offload。

## 实验评估

这篇论文的实验比较契合其主张，因为它同时验证了 portability 和实际应用价值。Machnet 跑通了 Azure、AWS、GCP，也测试了多代裸机 NIC。在基础 echo 实验里，Azure 上 `64 B` 消息的往返延迟达到 median/`p99`/`p99.9` 分别 `27/32/49 us`，而 Linux TCP 是 `62/79/118 us`。AWS 与 GCP 在小消息上也有同样趋势。对 `32 kB` 大消息，结论则更克制：Machnet 在 Azure 和 EC2 仍然优于 Linux，但在 GCP 上反而落后，这与论文把大消息极限吞吐列为非目标是一致的。

宏基准说明它不只是一个微基准系统。把 Hashicorp 的 Go 版 Raft 移植到 Machnet 后，中位延迟下降 `34%`，`p99` 下降 `37%`，大约做到 `185 us` 的 median 与 `625 us` 的 `p99`。在 Mongoose web server 上，Machnet 在 Azure 中能以接近 `68K` RPS 的负载把 `p99` 稳在约 `60-70 us`；Linux 栈则超过 `4000 us`，并且在 `40K` RPS 后明显吃力。对 FASTER key-value store，Machnet 约做到 `700K` RPS，而 Linux TCP 只有 `210K`，即 `3.3x` 吞吐提升，同时把 `p99` 从约 `250 us` 降到 `50 us`。

微基准则把取舍讲清楚。Machnet 在 `64 B` 延迟上已经很接近 eRPC：median 和 `p99` 都只差约 `10%`。但在大消息、大窗口吞吐场景下，Machnet 约比 eRPC 低 `45%`，更接近 TAS。这恰好支持了作者的定位：它不是要在所有 datapath 指标上赢过所有特化系统，而是要证明“遵守公有云真实硬件契约”的设计，依然能拿回大部分延迟收益，同时换来更现实的部署模型。

## 创新性与影响

如果和 _Kalia et al. (NSDI '19)_ 相比，Machnet 的新意并不是把 RPC datapath 再压低几微秒，而是重新界定了问题：公有云里的用户态网络应该围绕 LCD vNIC 设计，而不是围绕租户根本控制不了的裸机功能设计。和 _Kaufmann et al. (EuroSys '19)_ 相比，它保留了 sidecar 路线，但补上了 opaque RSS 条件下如何做按应用放置的关键缺口。它的影响也很直接：研究者得到了一份更诚实的云端硬件契约，工程实践者则看到 Go 服务、Web server、复制状态机都可以在不改造整套 OS 的前提下使用 kernel-bypass 网络。

## 局限性

论文也很坦率地承认，Machnet 并不适合所有工作负载。它不面向 RDMA 类那种极高吞吐、极重通信的场景，而且实验已经显示，只要进入大消息、大窗口区间，Machnet 相比 eRPC 仍有明显吞吐差距。可移植基线带来的额外 copy 开销在某些云上甚至会抹平优势，`32 kB` 消息在 GCP 上落后于 Linux 的结果就是直接例子。`RSS--` 也只是把缺失 flow steering 的问题移出热路径，没有让它消失；连接建立仍然是概率式的亚毫秒握手，而不是零成本精确队列控制。与此同时，Machnet 提供的是 socket-like API，而不是对未经修改应用的二进制兼容，且大多数实验都集中在同一 availability zone 与中小规格 VM 上。

## 相关工作

- _Kalia et al. (NSDI '19)_ — eRPC 展示了依赖高级 NIC 特性的 libOS 式 RPC 栈能做到多快，而 Machnet 讨论的是当这些特性对云租户根本不可用时，还能剩下多少性能空间。
- _Kaufmann et al. (EuroSys '19)_ — TAS 同样把网络视为一种 OS 级服务，但仍依赖 Machnet 在可移植基线中排除的 NIC 控制能力，也缺少显式的应用到 engine 隔离。
- _Marty et al. (SOSP '19)_ — Snap 与 Machnet 都有 microkernel 风格的网络设计直觉，但前者面向云厂商可控的宿主机网络栈，而不是租户 VM 面前受限的 vNIC 接口。
- _Fried et al. (NSDI '24)_ — Junction 也试图让 kernel bypass 更适合云环境，不过 Machnet 认为只要仍然依赖 direct NIC access 或非 LCD 特性，它就还不能覆盖多数普通 VM 租户。

## 我的笔记

<!-- empty; left for the human reader -->

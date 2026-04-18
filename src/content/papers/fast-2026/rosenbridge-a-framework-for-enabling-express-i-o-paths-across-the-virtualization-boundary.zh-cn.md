---
title: "RosenBridge: A Framework for Enabling Express I/O Paths Across the Virtualization Boundary"
oneline: "通过一个支持 uBPF 的 paravirtualized device 把 NDP 式存储卸载搬进 QEMU，让 VM 在不打破隔离的前提下获得接近 XRP/GDS 的快速 I/O 路径。"
authors:
  - "Shi Qiu"
  - "Li Wang"
  - "Jianqin Yan"
  - "Ruofan Xiong"
  - "Leping Yang"
  - "Xin Yao"
  - "Renhai Chen"
  - "Gong Zhang"
  - "Dongsheng Li"
  - "Jiwu Shu"
  - "Yiming Zhang"
affiliations:
  - "NICE Lab, XMU"
  - "SJTU"
  - "KylinSoft"
  - "Huawei Theory Lab"
  - "NUDT"
  - "THU"
conference: fast-2026
category: os-and-io-paths
tags:
  - virtualization
  - storage
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

RosenBridge 的目标，是让裸机上的 express storage path 能真正穿过 guest-host 边界，在 VM 内继续成立。它通过一个新的 `virtio-ndp` 设备，把经过验证的 uBPF 程序装载到 QEMU 用户态，在 I/O 提交或完成时触发，再配合地址翻译 helper 与 `io_uring` passthrough，把 XRP、GDS 这类 NDP 优化搬到虚拟化环境里。论文表明，这种做法能明显缩小 VM 与裸机之间的差距，同时显著降低传统 virtio/vhost 路径的 CPU 消耗。

## 问题背景

这篇论文解决的是一个很现实的错位：NVMe SSD 已经快到让软件栈本身成为主要瓶颈，但虚拟化偏偏又把软件栈拉得更长。作者对 `virtio-blk` 上一次 `4 KB` 随机读做了分解，发现总延迟里有 `87%` 来自软件处理，而不是设备本身；当 VM 与物理机达到同样的 `2`、`4`、`8 GB/s` 吞吐时，VM 还要多消耗 `498.3%`、`630.4%`、`581.0%` 的 CPU 资源。对云上的本地盘、数据库、深度学习和 HPC 工作负载来说，这种放大代价已经不可忽视。

问题在于，现有裸机 express I/O 机制并不能直接搬进 VM。像 XRP 和 GDS 这类方案之所以有效，是因为它们能把逻辑推到设备附近，避免一次次回到用户态或穿越完整内核栈。但在 KVM/QEMU 架构里，guest 只能看到 hypervisor 暴露的虚拟块设备，看不到宿主机真正的 NVMe 驱动、地址映射和队列语义。把优化逻辑写在 guest 里的 virtio frontend，仍然要走完整的 host storage stack；把它直接下推到 host kernel，又会破坏虚拟化赖以成立的安全边界和可管理性。

## 核心洞察

论文最重要的判断是：想让 VM 获得 express I/O path，关键不是想办法把裸机 fast path 原封不动穿过虚拟化边界，而是在 host 一侧提供一个受限但足够表达力的可编程执行环境。对一个 NDP 程序来说，它真正需要的能力并不多：能在 host 侧运行，能在 I/O 提交与完成这两个时刻介入，能把 guest 视角下的地址和偏移翻译成 host 视角下的语义。

RosenBridge 因此把程序放在 QEMU 用户态执行，而不是 guest 内核，也不是 host 内核。这个落点很讲究。放在用户态，仍然处于 hypervisor 的安全包络之内；放在 QEMU 附近，又足够接近 `io_uring` 和 NVMe driver，能让 resubmission 这种优化真正有意义。这个思路成立的前提，是把可编程性和边界控制绑在一起：限定上下文对象，借助 verifier 检查内存访问，通过 helper 暴露翻译能力，并把速率限制状态在所有 I/O 路径之间共享，避免 VM 借“新快路径”逃逸掉 QoS 约束。

## 设计

RosenBridge 的核心机制是一个新的 paravirtualized device `virtio-ndp`，包括 guest 内核里的 frontend 和 QEMU 中的 backend。它向 guest 暴露四类主要接口：`BPF_HOST_ATTACH` 与 `BPF_HOST_DETACH` 用来在 host 侧装载和卸载 BPF 程序，`read_nd` / `write_nd` 则在发起 I/O 时绑定某个已装载的程序。为此，RosenBridge 扩展了 virtio 请求头，在普通读写字段之外加入程序标识与额外 buffer 信息，使 QEMU 能区分程序加载、卸载和 NDP 触发型 I/O。

当 `read_nd` 或 `write_nd` 抵达 QEMU 后，RosenBridge 会把请求路由到专门的 worker 线程，并执行与 `bpf_fd` 对应的 uBPF 程序。真正的数据路径则建立在 `io_uring` passthrough 上，这样 host 用户态运行时仍能绕过大部分传统内核 I/O 栈，直接高效地下发到 NVMe driver。为同时支持 GDS 这类“提交前改写”模式和 XRP 这类“完成后按内容重提”模式，RosenBridge 在 `io_uring` 中加入两个 hook point：一个位于 submission queue 准备阶段，一个位于 completion 处理阶段。前者允许程序改写 buffer 或偏移，后者允许程序查看返回数据并生成新的 SQE 继续提交。

跨边界语义对齐同样是设计重点。Guest 元数据会被复制到一个 guest-host 共享内存区域，这个区域通过 `virtio-ndp` 的 PCI BAR 映射给 VM；BPF 程序接收到的 `rosenbridge_md` 上下文里包含 `meta`、`meta_end`、`data`、`data_end` 四个指针，用来界定可读元数据与可读写数据的边界。对于只存在于 host 的语义，RosenBridge 提供 `BPF_disk_trans`、`BPF_mem_trans` 等 helper，把 guest 视角下的磁盘偏移或内存指针翻译成 host 侧地址。两个案例正好说明了这套抽象的用法：RosenXRP 在 completion hook 上判断一次 B-tree 查询是否结束，若未结束则翻译下一跳偏移并构造新的 SQE；RosenGDS 则在 submission hook 上查找已下放的 GPU memory mapping，把 phony buffer 重写成 host 可见的 GPU 地址，从而建立到 GPU HBM 的 peer-to-peer DMA。

安全与公平性不是论文的附属讨论，而是机制的一部分。RosenBridge 定义了专门的 `BPF_PROG_TYPE_ROSENBRIDGE` 上下文，并在加载阶段借助 PREVAIL verifier 验证程序终止性与越界访问；运行期，`BPF_uring_set_sqe` 还会检查内存引用是否落在 VM 拥有的区域内，磁盘访问是否落在该 VM 的虚拟磁盘范围内。由于 offloaded I/O 相当于新增了一条提交路径，RosenBridge 还把 QEMU 的 leaky-bucket 状态在标准 I/O 与 uBPF 触发 I/O 之间共享，从而保证 VM 的总额度仍然被统一计量。

## 实验评估

实验平台是一台双 `64` 核、`512 GB` DRAM 的服务器，host 与 guest 都运行 Linux `6.1.0`，QEMU 版本是 `7.1.50`，底层存储设备为 Intel `P5800X`，GDS 实验还额外挂接了一张通过 VFIO passthrough 给 VM 的 `48 GB` GPU。基线选择比较合理：RosenXRP 对比 `virtio-blk`、`vhost-kernel-blk`、`vhost-user-blk`，并用裸机 XRP 作为上界；RosenGDS 对比 `virtio-blk + cudaMemcpy`，并与裸机 GDS 比较。

RosenXRP 的结论很清楚：真正跨过边界去做可编程 resubmission，比单纯优化传统 paravirtualized path 更有效。在随机 key lookup 上，RosenXRP 相对 `virtio-blk` 吞吐提高 `461.8%`，相对 `vhost-kernel-blk` 提高 `243.5%`，相对 `vhost-user-blk` 提高 `102.1%`；平均延迟分别下降 `82.1%`、`70.7%`、`49.4%`。它仍然落后于裸机 XRP，大约只能达到其 `65%` 的带宽，平均延迟则高 `55%`，这与论文的解释一致：每次操作至少还要穿越一次虚拟化栈。Range query 的趋势相同，而且随着查询长度增大，RosenXRP 会更接近 XRP，因为固定的虚拟化代价被更多重提 I/O 摊薄。CPU 开销方面，RosenXRP 在 key lookup 中只消耗三个虚拟化基线的 `14.73%`、`28.69%`、`41.85%`；在 range query 中甚至更低。公平性实验虽然规模不大，但能说明问题：当每个 VM 被限制在 `1300 MB/s` 时，如果关闭 RosenBridge 的 throttling，运行 XRP 风格负载的 VM 会把邻居的 virtio VM 压到大约 `30%` 的配额；开启多路径协同限流后，两者都能维持在接近各自限制的位置。

RosenGDS 的收益没有 RosenXRP 那么夸张，但也足够可信。与 `virtio-blk` 加 `cudaMemcpy` 相比，它在单线程下把延迟降低 `27.5%` 到 `56.4%`，并至少减少 `35.2%` 的 CPU 消耗；与裸机 GDS 相比，平均延迟仍高约 `30%`。在四线程测试里，RosenGDS 在 `4 KB` 到 `256 KB` 区间都优于 virtio 路径，平均带宽只比裸机 GDS 低 `26%`。当块大小达到 `1 MB` 和 `4 MB` 时，它分别只使用 `virtio-blk` 所需 CPU 的 `45.2%` 与 `79.7%`。整体来看，这组结果基本支撑了论文主张：RosenBridge 没有消除虚拟化开销，但它消除了足够多本可避免的 guest-host 栈层往返，使得 NDP 风格快路径在 VM 中终于值得用。

## 创新性与影响

相对于 _Zhong et al. (OSDI '22)_ 的 XRP，RosenBridge 不是重新发明一种新的 storage function，而是回答了“XRP 这类语义在虚拟化后怎么保住”这个更棘手的问题。相对于 _Qiu et al. (SC '24)_ 的 EXO，它不满足于只加速 paravirtualized storage 中的地址映射逻辑，而是把可编程的 NDP 逻辑本身跨边界卸载到 host 侧，从而省掉一次逻辑操作内部更多重复的 guest-host 往返。

因此，这篇论文更像是一项新的系统机制，而不只是一个更快的 virtio 变体。它的潜在影响对象包括云上的本地盘服务、跑数据库和分析任务的存储密集型 VM，以及依赖 GPU 但又受制于存储中介开销的工作负载。更广义地看，RosenBridge 提供了一种可复用的方法论：把可编程逻辑安放在 hypervisor 用户态，通过有边界的 helper 暴露 host 语义，再把资源控制做成共享状态，而不是一条“旁路”。

## 局限性

RosenBridge 并没有让虚拟化“消失”。论文自己也承认，RosenXRP 相比裸机仍有明显损失，因为每个操作至少还要穿越一次完整的虚拟化存储栈，之后 host 侧快路径才能接管。这意味着它最适合的是带有多阶段处理、内容驱动重提或特殊 buffer 重映射的场景，而不是所有 I/O 模式都会同样受益。

部署成本也不低。RosenBridge 需要新的 virtio 设备语义、QEMU backend 修改、`io_uring` hook 集成，以及针对具体优化编写的 helper。Guest 应用还要使用扩展 API，并负责共享元数据的一致性，这把一部分复杂度推给了应用或 guest 运行时。安全论证总体合理，但依赖 verifier 能力和受限的 helper 面。最后，实验只覆盖了一种主机平台、一块 SSD、一种 GPU 配置和两个案例；论文的“通用性”更多是由机制设计支撑，而不是由大范围 workload 覆盖直接证明。

## 相关工作

- _Zhong et al. (OSDI '22)_ — XRP 在裸机 NVMe 路径中用 eBPF 做存储请求重提；RosenBridge 则把这类重提语义通过 verified uBPF 和 QEMU 搬进 VM。
- _Qiu et al. (SC '24)_ — EXO 用 eBPF 加速 KVM/QEMU 存储虚拟化中的地址映射，而 RosenBridge 提供的是更通用的跨边界 NDP 可编程执行模型。
- _Amit and Wei (USENIX ATC '18)_ — Hyperupcalls 允许 hypervisor 无需切回 guest 就触发 guest 注册的 eBPF 处理逻辑，但它是 host 主导的机制，并不提供通用的 guest-to-host express storage path。
- _Leonardi et al. (ISC '22)_ — eBPF-based extensible paravirtualization 在 host 与 guest 之间转移 eBPF 逻辑以做 VM 调优，而 RosenBridge 关注的是带显式公平性控制的安全 guest-to-host programmable storage I/O。

## 我的笔记

<!-- 留空；由人工补充 -->

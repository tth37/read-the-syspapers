---
title: "Device-assisted Live Migration of RDMA devices"
oneline: "论文把迁移控制下沉到 RDMA NIC，配合两阶段 PCIe quiescing，让 passthrough RDMA 与 GPUDirect 设备组合在不改 guest 和对端的前提下实现透明 live migration。"
authors:
  - "Artem Y. Polyakov"
  - "Gal Shalom"
  - "Aviad Yehezkel"
  - "Omri Ben David"
  - "Asaf Schwartz"
  - "Omri Kahalon"
  - "Ariel Shahar"
  - "Liran Liss"
affiliations:
  - "NVIDIA Corporation, USA"
  - "NVIDIA Corporation, Israel"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764795"
tags:
  - rdma
  - virtualization
  - smartnic
category: datacenter-scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文认为，passthrough RDMA 设备的透明 live migration 只有在 NIC 本身参与迁移时才真正可行。为此，作者提出一个 device-level migration API，要求设备直接保留 RDMA namespace 与连接状态，并为 PCIe peer-to-peer 流量设计了两阶段 quiescing 方案，从而在面向 HPC 和 AI 的 VM 配置上做到亚秒级停机。

## 问题背景

云平台已经把 live migration 当成维护和 rolling upgrade 的基础能力，但 passthrough RDMA 设备会直接打破这套抽象。VM 一旦通过 SR-IOV 和 PCIe passthrough 直接访问 RDMA NIC，hypervisor 就拿不到设备内部状态。RDMA 还进一步增加难度：QP number、memory key 等标识符由设备分配并暴露给 guest，部分还会暴露给远端 peer；而 transport progress、in-flight packet 和 one-sided memory access 则全部保存在 NIC 内部，而不是一个 hypervisor 可以序列化的软件层里。

software-only 的补救办法，是在硬件之上虚拟化 RDMA 资源：在目标端重建 QP 和 MR，运行时翻译标识符，drain outstanding work，再和对端重连。论文认为这条路在生产云里几乎不可部署。通过 Verbs 重建对象会额外耗费数秒；draining 会把 downtime 直接绑到消息大小和网络状态上；要求修改 guest OS 或 middleware 又不适合云租户。AI VM 让问题更严重，因为 GPUDirect 允许 RDMA NIC 通过 PCIe peer-to-peer 直接访问 GPU memory，此时迁移不仅要保住单个设备状态，还要保住设备间直接通信的一致性。

## 核心洞察

论文最重要的主张是：RDMA live migration 必须在 device state 层面完成，而不是在 RDMA object 层面完成。只要源 NIC 能导出一份语义上足够的状态镜像，目标 NIC 能重建相同的 RDMA namespace、本地地址和 transport progress，那么迁移就能对 guest 和 remote peer 保持透明，而不需要运行时 translation 或全局协调。

这个主张之所以成立，是因为只有设备自己真正知道哪些隐藏状态需要保留。NIC 可以按 packet 粒度挂起通信，而不是把 queue pair 全部 drain 完；可以保留 wire-visible identifier，而不是在软件层额外加映射；还可以区分哪些 microarchitectural state 必须复制，哪些已经过时或能在目标端重建。同样的思路也适用于多设备场景：与其逐个冻结设备，不如分阶段 quiesce 整个 memory fabric，让 posted PCIe transaction 在设备被 seal 之前全部冲刷到位。

## 设计

整套设计围绕一组 device assists 展开。先看 network transparency。设备必须保留 RDMA namespace、本地连接状态和远端连接状态。这样一来，QP number 和 memory key 在迁移前后保持不变，目标 NIC 可以把 MAC/IP 或 LID/GID 以及各类 QP 状态原样恢复，而可靠 RDMA 连接则通过 exponential-backoff retransmission timeout 跨过迁移停顿，无需和对端显式协调。

其中最关键的是按 packet 粒度 quiesce。已有工作通常选择 drain communication，这会让 downtime 受消息大小和网络条件支配。本文让设备在 transport packet 粒度停止前进，因此重传单位始终固定且很小，同时 expected sequence number、opcode、virtual RDMA address 以及 atomic operation 的缓存结果都能直接恢复。状态导出也采取同样的思路：设备不通过 Verbs 逐对象序列化，而是把状态当成 black box 分块导出，并通过 vendor-specific migration tag 做兼容性检查；hypervisor 只看到 `PreCopy`、`DevThrottle`、`Suspend-Active`、`Suspend-Passive` 以及 image save/load 这类通用命令。

多设备部分是论文的另一项核心贡献。作者为 PCIe 这类 fabric 设计了两阶段 suspend/resume 协议。在 active 阶段，设备停止发起新的 DMA，但继续作为 PCIe target 处理外来请求；在 passive 阶段，设备状态被 seal 并可安全导出。论文利用 PCIe ordering rule 说明，只要先让所有设备完成 active suspend，再让任何一个设备进入 passive suspend，即便设备之间存在 peer-to-peer PCIe 流量，也能得到一致切面。

实现基于 NVIDIA ConnectX-7，包含大约 6K 行 firmware 修改，以及 Linux VFIO 和 QEMU 中的配套改动。每个 VF 的主要状态位于由设备管理、但放在 hypervisor memory 中的 ICM 页面里。`Suspend-Active` 会把 VF 从 embedded switch 上摘下、停止 transmit queue、完成 guest 的 control-path 命令并关闭 DMA mastering；`Suspend-Passive` 则 flush device cache，并把 location-dependent reference 与已经过时的 runtime state 从镜像里剔除。pre-copy 用来提前传递 ICM layout 并预分配页面，dirty-rate control 则复用了设备的 traffic shaping 能力。

## 实验评估

实验运行在三台服务器上，每台机器配有 96-core AMD EPYC 9654、128 GB 内存、NVIDIA L40S GPU，以及 ConnectX-7 200 Gbit/s NIC；QEMU 的 out-of-band 迁移通道有效吞吐约为 16 Gbit/s。第一组结果说明，批量搬运设备状态比逐对象重建便宜得多。对于 100K 个 QP，bulk image load 只需 2.5 秒，而通过 Verbs 单独创建并连接这些对象需要约 9.14 秒加 5.88 秒。对于 100K 个 MR，bulk load 只需 0.1 秒，而重建则要 37.75 秒，因为镜像路径完全绕开了 guest 侧 memory pinning。

downtime 数据基本支持论文主张，同时也清楚暴露了瓶颈。100K 个 QP/CQ pair 时，device image 会膨胀到 395 MB。把 ICM allocation 前移到 pre-copy 阶段后，100 个 QP 的 downtime 下降 25%，100K 个 QP 时下降 75%。pipelining 的主要收益是把迁移缓冲压缩成固定 16 MB，但由于真正的限制来自 16 Gbit/s 的 OOB 通道，所以对 downtime 本身只再减少了 3%。从应用视角看，`ib_write_lat` 观测到一次 310 ms 的 RTT spike，与 QEMU 报告的 308 ms downtime 基本一致；另一处 81 ms 的 spike 则来自测试床里的 route reconfiguration。

性能结果在论文承诺的范围内是有说服力的。对于 `ib_write_bw` 和 message-rate 测试，pre-copy 阶段看不到性能下降，downtime 结束后性能立即回到 bare-metal 水平，即便 VM 同时持有 100K 个 idle QP 也是如此。MPI NAS Parallel Benchmarks 都通过一致性检查，只在一次迁移下出现轻微运行时间上升；对 1 GB 向量做 500 次 NCCL Allreduce 的实验中，迁移后带宽可以完全恢复。不过，pre-copy convergence 仍然受限于通道带宽。当 RDMA 吞吐达到 18 Gbit/s 时迁移无法收敛；即便把设备限速到 15 Gbit/s，也需要 99.7 秒和 46.4 轮 pre-copy，而 1 Gbit/s 时只需 31 秒和 5.6 轮。

## 创新性与影响

相较于 software RDMA migration 系统，这篇论文的创新点不只是“加硬件支持”，而是明确刻画了硬件支持到底该提供什么：保留 namespace、按 packet 粒度 quiesce、以 black-box 形式导出镜像、控制 dirty rate，以及为多个直接通信设备提供两阶段 quiesce 协议。相较于已有的 device-assisted Ethernet migration 工作，它又把透明迁移推进到了更困难的场景，因为这里不仅要保住 wire-visible RDMA state，还要让 GPU/NIC 的 peer-to-peer 通信在迁移前后保持一致。

它的影响也很务实。作者把机制定位为已经进入生产 Linux virtualization stack 的 generally available 能力，而 API 又刻意保持 device-agnostic，使得后续其他 passthrough 设备也能复用同一迁移流程。

## 局限性

最直接的局限是跨厂商可部署性。整套方案依赖深度 firmware 支持、对设备内部状态的掌握，以及 hypervisor 侧的专门集成；论文真正展示的只有 ConnectX-7。兼容性策略也不是完全灵活的：feature version 可以向上兼容，但只要 ICM layout 改变，仍然需要 cold reboot。

性能边界也很清楚。downtime 仍然会随 image 大小增长；当设备脏页速率高于迁移通道速率时，pre-copy 可能不收敛。当前实现里，resume 还需要在 firmware 中扫描 QP，这会带来恢复开销；post-copy 支持则被留到未来工作。连接保持目前仍主要依赖 timeout inflation，而作者自己也指出，这可能和快速 failure detection、path management 的目标冲突。应用级评估虽然证明了正确性与 steady-state performance 的恢复，但范围仍局限于单一 NIC 家族、单一 hypervisor 栈和单一测试网络。

## 相关工作

- _Cao et al. (HPDC '14)_ - DMTCP over InfiniBand 通过软件层 checkpoint/restart 处理 RDMA，而本文把一致性与状态提取下沉到 NIC，以避免对象重建和对端协调。
- _Planeta et al. (USENIX ATC '21)_ - MigrOS 也追求透明 RDMA migration，但它依赖 object-level serialization 和新的 `Paused` QP state；本文则保留 namespace 并依赖 timeout，从而避免 wire-protocol 修改和潜在 deadlock。
- _Li et al. (APNet '24)_ - MigrRDMA 借助 guest 参与在 pre-copy 阶段摊销软件重建成本，而本文直接导出 black-box device image，不要求 guest 或 remote peer 做任何改动。
- _Zhang et al. (IEEE TC '24)_ - Un-IOV 展示了面向 VirtIO 设备的 device-assisted transparent migration，而本文进一步处理 RDMA 语义，以及 PCIe peer-to-peer 多设备一致性这一新增难点。

## 我的笔记

<!-- 留空；由人工补充 -->

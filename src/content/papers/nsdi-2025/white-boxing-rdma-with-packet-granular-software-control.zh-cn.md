---
title: "White-Boxing RDMA with Packet-Granular Software Control"
oneline: "SCR 把 RNIC 的 per-QP dequeue rate 变成软件可控的 packet-granular 控制点，让 BlueField-3 在不改主机栈的前提下实现公平调度、拥塞控制、路由和接收端反馈。"
authors:
  - "Chenxingyu Zhao"
  - "Jaehong Min"
  - "Ming Liu"
  - "Arvind Krishnamurthy"
affiliations:
  - "University of Washington"
  - "University of Wisconsin-Madison"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - rdma
  - networking
  - smartnic
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文试图把 RDMA 做成“white-box”系统: 保留 Nvidia BlueField-3 RNIC ASIC 的高速数据通路，但把运输层控制搬到 DPA 软件里。`SCR` 通过 dequeue-rate 控制模型和跨 fabric、host、peer 三个域的事件收集，让软件能够实现公平调度、RTT 型拥塞控制、多路径路由和接收端反压，而且不需要改主机应用或库。

## 问题背景

RDMA 的高性能来自 RNIC ASIC 对 packetization、DMA 和可靠传输的硬件卸载，但同样的硬件化也把传输策略锁死了。想引入新的 congestion control、tenant fairness 或 routing policy，通常只有三条路: 等供应商下一代 ASIC、自己做 FPGA 或专用 NIC，或者在 verbs 之上加一层主机侧 overlay。前两种路线慢而贵，后一种虽然更灵活，却只能看到 message-granular 的操作，仍无法真正直接操控 RNIC。

随着 RDMA 进入多租户以太网中的存储和 GPU 流量场景，这个矛盾更加明显。现代部署需要的不只是传统的 fabric congestion response，还包括不同消息尺寸租户之间的公平共享、many-to-one incast 下的 receiver feedback，以及多路径环境下的 path selection。难点在于，有用的信号往往以 packet 甚至 sub-microsecond 的粒度出现，而商品 SmartNIC 内部可编程核心又很弱。

## 核心洞察

论文最关键的判断是把控制旋钮放在 RNIC 的 per-QP dequeue rate 上，也就是 NIC 从 host memory 拉取 WQE 和 payload 的速率。这个控制量比单纯的 sending rate 更通用，因为它同时影响上线路带宽、PCIe DMA 压力、RNIC 内部处理资源占用，以及对对端 receiver 造成的负载。

一旦把 dequeue rate 作为统一控制变量，“white-boxing RDMA” 就变得可行了。硬件继续负责 DMA、packetization 和 transport execution 的高速通路，软件则根据多域事件来计算新的 dequeue rate。换句话说，RNIC 仍然是高性能 datapath，但它的 control plane 开始具备 white-box switch 式的可编程性。

## 设计

`SCR` 围绕一个 event-driven framework 组织起来。事件收集器从三个域拉取信号: fabric domain 的 `TX`、`ACK`、`NACK`、`CNP` 和 RTT，host domain 的 application hint、PCIe 利用率或延迟、RNIC 利用率，以及 peer domain 的 receiver credit、对端 PCIe 和 RNIC 压力。当 RNIC 不能直接暴露某类信号时，`SCR` 就让 DPA 通过轻量级 out-of-band UDP 包去探测这些信息。

真正困难的是如何跟上 line rate。BF3 硬件原本就能对部分 in-band fabric 事件做 coalescing，但它只支持固定策略，所以 `SCR` 又加入软件队列和 multiplexing，提供如 accumulation、keep-latest 等更丰富的 policy。计算侧采用 deterministic multithreading: handler run-to-completion、线程之间 shared-nothing，并把同一 flow 的同一类事件固定映射到同一 DPA thread。论文提出的 "granularity invariance" 论点说明，只要总 line rate 不变，把更多 flow 合并到固定 thread pool 上，并不一定会降低控制精度。

由于 DPA core 很弱、cache 也很小，整套实现对 state footprint 和 instruction count 都做了严格约束。它用 Bloom filter、紧凑 hash map 和 fixed-point arithmetic 压低开销，只保留一个很小的 host agent 来绕过 BF3 的现实限制，比如 thread 必须预先拉起，以及只有 `doca_pcc` 能真正把新 rate 安装到硬件里。

## 实验评估

原型总共约 7.8K 行 C/C++，运行在两台 100 GbE 服务器上，配有 BlueField-3 DPU 和 A30 GPU。使用最多 64 个 DPA thread 时，`SCR` 可以跟上 line-rate 流量，而且即使 QP 数量扩展到 1024，coalescing granularity 也基本保持不变。软件 coalescing 在 4-thread 配置下比纯硬件 coalescing 把 event rate 再提升了 51.3%，而 Bloom filter 又把一类 membership structure 从大约 2 MB 压到了 8 KB，可覆盖 8192 个 flow。

最有说服力的端到端结果来自 fair QP scheduler。对两个竞争 QP，Water Filling 相比默认调度器把 Jain fairness index 最多提升了 1.78x；当扩展到 4 个 QP 时，fairness 从 0.51 提升到 0.96，同时仍保持接近 line rate 的利用率。在一个 256 B latency-sensitive flow 与 64 KB bandwidth-hungry flow 竞争的实验里，Water Filling 把延迟从 5.3 微秒降到 2.5 微秒，下降 52.8%，而大流仍保有 82.4 Gbps，默认调度器则是 90.6 Gbps。附录 case study 还表明，同一套 substrate 可以实现 Swift 风格 RTT 控制、多路径故障检测、最高 16-to-1 incast 下的 receiver credit，以及在不改 host 栈的前提下为 GPU-Direct RDMA 和 NVMe-oF 执行公平共享。

## 创新性与影响

这篇论文的创新点不是某一个新的 transport algorithm，而是为商品 RDMA NIC 提供了一套可复用的控制基座: 一个通用的 dequeue-rate 模型，再加上一套多域事件框架。

它站在两类老方案之间。像 `Flor`、`Justitia` 这样的 host overlay 更容易部署，但粒度粗且侵入主机栈；定制 NIC 或 FPGA 虽然灵活，却很难普及。`SCR` 提供了一个更现实的中间层，也因此更像未来 RNIC API、SmartNIC firmware 或 Falcon 类 rate engine 可以借鉴的模板。

## 局限性

这个原型很大程度上依赖 BF3 已经暴露的接口。BF3 目前没有直接的 `RX` event、更丰富的 NIC counter、运行时动态建线程的能力，也缺少通用的 DPA IPC，因此 `SCR` 仍需要一个小型 host agent，并且要和 `doca_pcc` 做比较别扭的协调；像 per-packet header rewrite 这样的动作还得借助 NIC flow engine 的额外技巧。

另一个限制是时间精度。论文测得从事件生成到新 rate 生效之间会有数微秒级延迟，而 1 Gbps 以下的精细 rate limiting 仍然不够准确。所以这篇论文证明的是一个高灵活度 substrate，而不是所有细粒度 RDMA policy 今天都已经能直接投入生产。

## 相关工作

- _Li et al. (OSDI '23)_ - `Flor` 在 heterogeneous RNIC 之上提供软件 RDMA 框架，而 `SCR` 把控制推进到 packet-granular transport loop，同时保持对 host 的透明性。
- _Montazeri et al. (SIGCOMM '18)_ - `Homa` 强调 receiver-driven transport control，而 `SCR` 通过 out-of-band peer signal 把这种思路迁移到 one-sided RDMA。

## 我的笔记

<!-- empty; left for the human reader -->

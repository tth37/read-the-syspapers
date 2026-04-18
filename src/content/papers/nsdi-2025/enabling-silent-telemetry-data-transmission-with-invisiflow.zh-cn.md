---
title: "Enabling Silent Telemetry Data Transmission with InvisiFlow"
oneline: "InvisiFlow 把遥测导出改成低优先级、按拥塞梯度拉取转发，让报告绕开繁忙链路，而不是在通往 collector 的最短路径上饿死。"
authors:
  - "Yinda Zhang"
  - "Liangcheng Yu"
  - "Gianni Antichi"
  - "Ran Ben Basat"
  - "Vincent Liu"
affiliations:
  - "University of Pennsylvania"
  - "Microsoft Research"
  - "Queen Mary University of London"
  - "Politecnico di Milano"
  - "University College London"
conference: nsdi-2025
category: datacenter-networking-and-transport
code_url: "https://github.com/eniac/InvisiFlow"
tags:
  - networking
  - observability
  - smartnic
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

InvisiFlow 把遥测数据和用户流量分开，并用低优先级、按拥塞梯度的拉取式转发来代替“沿最短路径把报告推给 collector”。这样做既几乎不增加用户流量开销，又能明显减少遥测丢失；在默认场景下 70% 负载时，它的路径缺失率比低优先级 UDP 低约 33.8 倍。

## 问题背景

这篇论文讨论的是一个很具体但很关键的问题：交换机已经生成了细粒度遥测之后，怎么把报告送到少量 collector，同时又不扰动被测网络，也不因为大量丢失而让遥测失去价值？现有方案基本只有两条路。第一类是把遥测塞进用户包里，给每个包都增加额外负担。第二类是单独生成遥测包，再沿普通最短路径发往 collector。后者更容易部署，但会把“遥测完整性”和“用户流量不受干扰”直接绑定在一起。

论文把这个冲突量化得很清楚。在动机实验里，如果让遥测包和用户流量同优先级，collector 附近应用的 FCT 会增加大约 19%；如果把遥测降成低优先级，大约有 11% 的路径无法被重建。路径追踪、负载不均衡检测、sketch 同步这类上层工具都会因此失真。论文的基本判断是：遥测不该被建模成“死守最短路送到 collector”，因为它通常允许异步、乱序，而且不在用户请求的关键路径上；它更应该去追逐网络中的剩余容量。

## 核心洞察

论文最重要的洞察，是把遥测导出重新表述成“分布式缓冲区平衡”问题。InvisiFlow 不要求每台交换机都把报告朝 collector 推过去，而是让相邻交换机比较各自遥测缓冲区的占用，把数据从更满的节点移到更空的节点。这个局部拥塞梯度来自 max-weight 调度的经典结果：沿梯度转发可以扩大稳定区域，从而提升遥测信道的可持续吞吐。

InvisiFlow 的贡献，是把这个思路做成一个能在可编程 ASIC 上运行的拉取协议。交换机持续发出低优先级 pull request，包里带上当前缓冲区占用；邻居只有在自己更拥塞时才返回遥测数据，collector 则被视为固定占用为 0 的汇点。系统再加一个很小的“坡度”偏置，让数据总体上更愿意朝 collector 方向流动，避免占用接近时来回震荡。

## 设计

InvisiFlow 里有三类参与者：交换机、collector，以及可选的空闲服务器，用作临时遥测存储。交换机借助 OrbWeaver 风格的低优先级 packet generation 周期性产生 seed packet。在 egress pipeline 中，每个 seed 会被改写成一个 pull request，带上本地遥测缓冲区占用。邻居收到 pull 后，会把它从原端口送回去并比较远端和本地占用；如果本地更满，就弹出一段遥测数据，把包改成 telemetry packet，否则就把 pull 反弹回去并填上自己的占用值。collector 发送占用为 0 的 pull，因此遥测会自然被吸向汇点。

实现上的关键，是把遥测主要存放在 egress pipeline 的寄存器缓冲区里，而不是只放在 ingress。这样就能 late bind 输出端口：只有当某个 egress arbiter 真正给了低优先级包发送机会，交换机才在最后一刻附加下一段遥测数据，避免过早绑定到忙碌出口。围绕这个核心，论文再补上三层务实控制：用基于到 collector 距离的坡度 `delta` 防止少量数据来回震荡；随着本地占用上升，概率性抑制新生成的 seed packet；一旦占用超过约 95%，暂时退回到盲推。原型实现用了大约 600 行 P4-16，collector 和可用服务器用 DPDK 实现，相对基于 OrbWeaver 的低优先级 UDP 基线只增加了很小的硬件开销。

## 实验评估

评估分成两部分：一部分是 144 台服务器、4 个 pod 的 FatTree 上的 ns-3 仿真，另一部分是两台 Wedge100BF-32X 交换机组成的硬件测试床。仿真里同时运行四类遥测应用，并对比默认优先级 UDP、低优先级 UDP，以及一个“只拉取但不看拥塞梯度、只沿最短路径走”的 pull-based 设计。

在默认仿真场景里，InvisiFlow 在 70% 以下负载可以保持 0 遥测丢包。到了 70% 负载，它的路径缺失率仍比低优先级 UDP 和 pull-based shortest-path 基线分别低约 33.8 倍和 36.3 倍；对流大小估计而言，归一化相对误差分别下降约 2.4 倍和 4.8 倍。在通往 collector 的链路被削弱的非对称拓扑下，低优先级 UDP 和 pull-based 方案的路径缺失率经常超过 40% 和 30%，而 InvisiFlow 只在负载高于 70% 时才开始丢遥测。ML 工作负载和不同缓冲区大小实验也呈现相同趋势。40% 负载时，它的 99% telemetry delay 大约 80 us，约为低优先级 UDP 的 1/3.4、pull-based 基线的 1/10.9。

硬件实验验证的是实现能否真的落地。在测试床中，通往 collector 的唯一最短路径被用户流量完全占满时，低优先级 UDP 的遥测丢失率超过 97%，默认优先级 UDP 也仍然超过 80%；InvisiFlow 则能找到其他可用路径，把遥测丢失维持在 0。与此同时，它对用户流量的 FCT 开销低于 0.1%；默认优先级 UDP 则大约增加 0.8% 的 FCT，并且会把交换机排队时延放大到比 InvisiFlow 高多达 500 倍。

## 创新性与影响

相对于 Planck、Everflow 这一类系统，InvisiFlow 的新意在于它不再把遥测导出视为普通的最短路径包投递。相对于 PINT 以及其他通过压缩、采样、近似来减少开销的工作，它不去减少被传输的信息，而是去改造传输基座。相对于 OrbWeaver，它是在低优先级 gap filling 之上再叠加分布式路由和缓冲控制。它最可能留下的影响，不是某个新的遥测应用，而是一种新的遥测传输默认范式。

## 局限性

InvisiFlow 并没有违背带宽竞争的物理现实。如果相关端口持续被用户流量占满，低优先级遥测仍然只能等待或被丢弃，论文也明确承认在这种极端情况下会出现任意大的延迟和丢失。这个设计默认优化的是“可持续送达能力”，而不是“严格时效性”，所以它并不提供硬性的延迟上界。

实现层面也有约束。由于要放进寄存器式缓冲区，遥测负载需要足够小，原型面向的是 160 字节以下的包；更大的消息需要逐跳切分。若网络里存在很多不同类型的 collector，每种类型都需要独立缓冲配额，可选空闲服务器也会带来额外的运维和调参成本。最后，实验证据仍主要来自数据中心风格拓扑。

## 相关工作

- _Yu et al. (NSDI '22)_ — OrbWeaver 提供了 InvisiFlow 借用的低优先级 gap-filling 基元，但它并不决定遥测在网络里应该往哪里走。
- _Rasley et al. (SIGCOMM '14)_ — Planck 也用专门的数据包导出遥测，不过它仍依赖传统转发路径，而不是基于梯度的机会式转发。
- _Ben Basat et al. (SIGCOMM '20)_ — PINT 通过近似减少需要传输的遥测量；InvisiFlow 则尽量保住完整性，把重点放在改造传输通道。

## 我的笔记

<!-- 留空；由人工补充 -->

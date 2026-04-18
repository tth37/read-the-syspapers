---
title: "Coyote v2: Raising the Level of Abstraction for Data Center FPGAs"
oneline: "Coyote v2 把数据中心 FPGA 变成带可重构服务、多流接口和 cThreads 的共享加速器 shell，让应用能像用 GPU/DPU 那样部署并复用基础设施。"
authors:
  - "Benjamin Ramhorst"
  - "Dario Korolija"
  - "Maximilian Jakob Heer"
  - "Jonas Dann"
  - "Luhao Liu"
  - "Gustavo Alonso"
affiliations:
  - "ETH Zurich"
  - "AMD Research"
  - "ETH Zurich and The University of Tokyo"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764845"
code_url: "https://github.com/fpgasystems/Coyote"
tags:
  - hardware
  - networking
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Coyote v2 认为，数据中心 FPGA 应该更像共享加速器，而不是“裸板卡加几段驱动”。它通过三层 shell 把可复用服务放进可动态重配置的层里，提供统一多流接口，并用 `cThreads` 让同一条硬件流水线同时服务多个客户端。

## 问题背景

论文的出发点很直接：FPGA 部署里仍有太多工作花在基础设施而不是应用上。作者引用已有研究指出，大约 75% 的开发精力消耗在 DMA、内存、网络和控制通路上，而且这些基础设施通常和某个具体设计耦合得很深，下一次几乎不能复用。

现有 shell 虽然改善了情况，但作者认为它们还缺三点。第一，服务多半是静态的，切换网络栈、MMU 配置或插入过滤器都可能要求整板下线。第二，接口不够通用。神经网络推理理应支持“权重放 HBM、输入直接从 host 流入”，向量加法理应天然支持多个输入流，但很多系统仍要求额外拷贝或在软件里手工打包。第三，现代 FPGA 很容易被单客户端执行模型浪费掉；一旦流水线存在数据依赖，单个请求会让大部分阶段闲置。若 FPGA 真想像 GPU、DPU 那样成为数据中心的一等加速器，就需要可复用服务、直接 host/网络集成，以及不依赖整板重启的动态部署能力。

## 核心洞察

核心洞察是把 FPGA shell 设计成更像操作系统底座，而不是固定的板级支持包。Coyote v2 把 static layer 缩到 CPU-FPGA 连接和重配置逻辑，把真正可复用的服务移到可运行时部分重配置的 dynamic shell layer，再让用户应用通过一套统一接口挂在其上。

这样做的价值在于，它把过去绑死在一起的职责拆开了。服务不再固化在 static region 后，平台就能不重启整块 FPGA 而切换 shell 配置，应用也能直接链接到已经完成 place-and-route 的 shell checkpoint。与此同时，应用接口必须真的通用，既支持多个 host/card/network 数据流，也支持硬件发起 DMA、通用中断和把多个软件客户端复用到一个 vFPGA 上的软件抽象。这样一来，FPGA 集成就更像部署共享加速器，而不是每个应用都重做一次硬件工程。

## 设计

Coyote v2 由三层硬件和一套软件支持组成。static layer 负责平台相关机制，包括基于 XDMA 的 CPU-FPGA 通信、shell 控制、host streaming、把缓冲迁移到板上内存的 migration channel，以及用于 writeback、中断和重配置的 utility channel。重配置走 ICAP，但作者没有沿用传统逐字写入控制器，而是做了一个流式控制器，在 AMD UltraScale+ 上可达到约 800 MB/s。因为 static layer 被刻意简化并包在 AXI4 接口之后，同一套 shell 结构才更容易复用到多种 AMD 板卡上。

dynamic layer 负责可复用服务。内存子系统扩展了原版 Coyote 的 shared virtual memory 模型，支持可配置的 TLB 大小、组相联度和页大小，包括 1 GB huge page。TLB 放在片上 SRAM，miss 时回退到 host driver，形成类似 GPU 的“页故障再迁移”模型。这个层也负责 HBM/DDR 控制器和 HBM 条带化。网络方面，BALBOA 提供 100G、兼容 RoCEv2 的网络栈，并复用同一套虚拟内存抽象，因此 RDMA 数据同样经过 shell MMU/TLB 翻译。

应用运行在 vFPGA 中。每个 vFPGA 都有 control bus、interrupt path、并行 host/card/network stream，以及读写 send/completion queue，从而允许硬件直接发起 DMA。对于共享 PCIe 和网络链路，shell 会把传输切成默认 4 KB 的 packet，做 round-robin interleaving，并用 per-vFPGA credit 防止某个租户把整块设备拖死。软件 API 之上再引入 `cThreads`，把多个软件线程映射到同一个 vFPGA 流水线上，从而让顺序流水线也能被多个客户端喂满。论文的 traffic sniffer 案例很好地展示了这种组合方式：filter 位于网络栈和 CMAC 之间，抓包数据在 application layer 中打时间戳并写入 HBM，随后再导回 host 生成 PCAP。

## 实验评估

实验主要评估这些抽象是否真的解决了具体瓶颈。最扎实的结果来自重配置层：Coyote v2 的 ICAP 控制器可达到约 800 MB/s，而 AXI HWICAP、PCAP、MCAP 分别只有 19、128、145 MB/s。最终 shell 重配置的端到端时间在 536-929 ms 之间，而通过 Vivado 对整块 FPGA 重新编程需要约 56-71 秒。构建流程上，应用直接链接到预先完成 place-and-route 的 shell checkpoint 后，application-only flow 又把 synthesis 加 implementation 时间额外缩短了约 15-20%。

数据通路结果也和设计目标一致。在 U55C 上，一个简单的 pass-through benchmark 随 HBM stream 数量增加而近似线性扩展，六路并行达到 12.3 GB/s。对于部署成多个独立 vFPGA 的 AES-ECB，总带宽稳定在 host memory 瓶颈附近，大约 12 GB/s，并且在租户之间分配得较公平。对于 AES-CBC，由于单请求会让 10 级流水线大面积空转，单个 `cThread` 在 32 KB 附近只有约 280 MB/s，但随着更多 `cThreads` 共享同一条硬件流水线，吞吐近似线性增加。

几个案例说明 shell 不只适用于玩具工作负载。HyperLogLog accelerator 与原版 Coyote 吞吐相近，而总体资源占用仍只有约 10%；按需部分重配置加载 HLL kernel 平均只需 57 ms。`hls4ml` 集成则是最直接的用户体验证明：神经网络加速器可以用不到十行 Python 完成编译与部署，论文报告其后端在资源占用接近的情况下，比 baseline 快一个数量级左右。作者同时指出，baseline 并未完全优化，因为它先把输入拷到 FPGA HBM，而不是直接从 host 流入模型。

## 创新性与影响

这篇论文的创新点不是新的 FPGA kernel，而是更完整的系统抽象。相较于原版 Coyote 以及相关 shell，Coyote v2 把服务层重配置、多流数据通路、公平共享和软件可见的流水线多路复用都做成平台能力。这让它既对构建新型加速器的系统研究者有价值，也对想把 FPGA 部署做得更像标准化数据中心基础设施的工程实践者有价值。

## 局限性

最大局限仍是可移植性。论文把分层架构描述为通用 shell 设计，但实现和评估都深度依赖 AMD 板卡、AMD IP（如 XDMA、ICAP）以及作者自己的服务。它说明这种拆分有利于移植，却没有给出跨厂商、跨云平台的完整移植验证。

抽象边界也并非没有代价。shell 重配置虽然远快于整板重编程，但几百毫秒仍不适合特别细粒度的切换；应用依然要链接到兼容的 shell 配置上；MMU 还没有 prefetching，而且论文明确承认某些追求极限 HBM 带宽的场景可能需要绕开它。隔离性最强的边界在 vFPGA 之间，而不是同一 vFPGA 内部的 `cThreads`。此外，实验大多是微基准和少量案例，还没有覆盖长期运行的混合生产负载或对抗式多租户。

## 相关工作

- _Korolija et al. (OSDI '20)_ - 原版 Coyote 首先把 OS 风格抽象带到 FPGA；Coyote v2 延续这一路线，但把服务移入可动态重配置的 shell，并显著扩展了应用接口。
- _Khawaja et al. (OSDI '18)_ - AmorphOS 强调 reconfigurable fabric 上的共享、保护与兼容性，而 Coyote v2 更强调直接 host streaming、更完整的 RoCEv2 等服务，以及更通用的多流执行接口。
- _Vaishnav et al. (TRETS '20)_ - FOS 提供面向动态工作负载的模块化 FPGA OS；Coyote v2 则更突出可复用服务、shared virtual memory，以及服务层和应用层同时支持重配置。
- _Li et al. (ASPLOS '25)_ - Harmonia 通过 reusable building blocks 推进异构 FPGA 加速的可移植性，而 Coyote v2 在此之外补上了 shared virtual memory、集成网络栈，以及面向多客户端流水线复用的软件模型。

## 我的笔记

<!-- empty; left for the human reader -->

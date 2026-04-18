---
title: "Oasis: Pooling PCIe Devices Over CXL to Boost Utilization"
oneline: "Oasis 把 CXL memory pod 变成软件实现的 PCIe 资源池，用共享缓冲区和消息通道承载远端 NIC 流量，把聚合 NIC 利用率提升到约 2x。"
authors:
  - "Yuhong Zhong"
  - "Daniel S. Berger"
  - "Pantea Zardoshti"
  - "Enrique Saurez"
  - "Jacob Nelson"
  - "Dan R. K. Ports"
  - "Antonis Psistakis"
  - "Joshua Fried"
  - "Asaf Cidon"
affiliations:
  - "Columbia University"
  - "Microsoft Azure"
  - "University of Washington"
  - "Microsoft Research"
  - "University of Illinois Urbana-Champaign"
  - "MIT CSAIL"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764812"
code_url: "https://bitbucket.org/yuhong_zhong/oasis"
tags:
  - disaggregation
  - networking
  - storage
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Oasis 把共享 CXL memory pool 同时当作数据通路和信令通路，让一台主机能够访问另一台主机所连接的 PCIe 设备。它最关键的工程点，是在今天仍然不具备跨主机 cache coherence 的 CXL 2.0 硬件上把这件事做对：让设备 DMA 尽量绕开 CPU cache，再用专门为 non-coherent memory 设计的消息通道恢复预取效率。在这个基础上，Oasis 能以几乎可忽略的干扰让两台主机共享一块 NIC，每个数据包只增加 4-7 us 开销，并在 38 ms 内切换到备份 NIC。

## 问题背景

论文的出发点很务实：云平台里的 NIC 和 SSD 既昂贵又耗电，但利用率仍然很差。作者给出的量级是，每台服务器上的 NIC 和 SSD 各自大约要花 2,000 美元，而且在 Azure 中二者还各自贡献约 13% 的服务器功耗。与此同时，Azure 的生产轨迹显示，平均有 27% 的 NIC 带宽和 33% 的 SSD 容量因为主机先在别的资源维度上耗尽而被 stranded。即便已分配的 NIC 带宽也是高度突发的：在作者抽样的机架里，P99.99 利用率只有 20%。

论文把原因归纳为三类：多维资源装箱会造成 stranded resource，按峰值分配会让设备大多数时间闲置，而为了故障切换预留的冗余 NIC 又进一步拉低平均利用率。把设备放到多主机共享的池子里可以同时解决这三件事，但现有方案都不理想。PCIe switch 的确能做 pooling，但论文认为它们昂贵且不灵活，给出的数字是每个机架最多要额外增加 80,000 美元成本。基于 RDMA 的 disaggregation 对部分存储场景有用，却既无法池化 NIC，也不适用于许多缺乏合适 peer-to-peer DMA 支持的 PCIe 设备。

## 核心洞察

Oasis 最核心的判断是：如果一个机架本来就因为 memory pooling 部署了 CXL pod，那么这块共享内存完全可以顺带成为 PCIe pooling 的低延迟软件背板。真正的难点在于当前 CXL 2.0 pod 只有共享内存，没有跨主机 cache coherence。

Oasis 能成立，是因为它只在非做不可的地方付 coherence 成本。对于 I/O buffer，发送方在交接前把数据刷回 CXL memory，而 backend 尽量不去碰 packet 或 block buffer，让 NIC/SSD 的 DMA 直接访问共享内存。对于 request 和 completion 的信令，Oasis 设计了专门的消息通道：receiver 会主动失效已经消费过的 cache line，以及那些被无效预取进来但没有新消息的 cache line，让 prefetching 在 non-coherent memory 上重新变得有效。论文真正的命题是，只要软件从一开始就围绕“非一致性”来设计，就能在 commodity CXL 2.0 上实现接近原生的远端设备访问。

## 设计

Oasis 的结构是一个可复用的系统框架，而不是只针对 NIC 的小技巧。每种设备类型对应一个 engine：每台主机上都有 frontend driver，而只有物理连接设备的主机才运行 backend driver。frontend 对本地 container 或 VM 暴露接口；backend 则调用原生驱动，例如 DPDK 的 MLX5，或者在存储设计里调用 SPDK 的 NVMe 驱动。系统还有一个 pod-wide allocator 负责分配资源、监控负载、处理重平衡与故障切换。它不在数据面临界路径上；状态放在共享 CXL memory 中，通过租约维护一致性，每 100 ms 接收 backend 上报的 telemetry，论文还说明 allocator 本身可以用 Raft 复制。

公共 datapath 把 I/O buffer 和 request/completion channel 都放进共享 CXL memory。消息通道是一个单生产者单消费者的环形缓冲区，默认有 8192 个槽位；每条消息带一个 epoch bit，另外再配一个 8 字节 consumed counter。这个细节非常关键，因为论文的微基准显示 naive 设计会失败得很惨。完全绕开 cache 的版本只能做到 3.0 MOp/s；朴素 prefetching 只有 8.6 MOp/s；而把已消费和无效预取的 cache line 都及时失效后，吞吐能到 87.0 MOp/s，并在论文要求的 14.0 MOp/s 目标吞吐下把延迟压回 0.6 us。

已实现的 network engine 很清楚地体现了这套思路。发送路径上，实例先把 packet 写到自己的共享 CXL TX 区域，frontend 把该 buffer write back，然后发出一条 16 字节消息，把 buffer 指针和元数据交给 backend；backend 不读 payload，只负责给 NIC 投递 work queue entry。接收路径上，backend 先在共享 CXL memory 的 per-NIC RX 区域里挂好 descriptor，NIC 通过 DMA 把收到的 packet 写进去；backend 再依靠 flow tagging 来判断目标实例，从而避免在软件里解析 payload。frontend 收到通知后，把 packet 拷回本地内存以满足隔离要求。论文还设计了与之对称的 storage engine，用 64 字节消息对应 NVMe command，但这个部分并未实现。

## 实验评估

实验平台由两台 AMD 主机和一个通过 x8 链路连接的 CXL 2.0 memory device 组成，两台主机各带一块 100 Gbit 的 Mellanox ConnectX-5 NIC。在四个 web application 和 memcached 上，和使用本地 NIC 的同一软件栈相比，Oasis 在 P50、P90、P99 上都只增加了大致 4-7 us 的延迟。UDP echo 微基准也表明，这个开销对 packet size 并不敏感。更重要的是 breakdown：单纯把 packet buffer 放进 CXL memory 几乎不增加额外延迟，绝大部分新增成本都来自 frontend 和 backend 之间的跨主机消息传递。

更贴近论文主张的是利用率实验。作者回放来自 Azure 两台主机的真实流量轨迹，对比“一台主机一块 NIC”和“通过 Oasis 让两台主机共享一块 NIC”这两种配置。结果里延迟影响很小：host 1 的 P99 完全不变，host 2 也只多了大约 1 us；但聚合后的 NIC 利用率在 P99.99 上从 18% 提升到 37%，这正是摘要里“NIC utilization 提升 2x”的原型级证据。

故障切换结果也相当务实。由于每个实例在启动时就已经向备份 NIC 完成注册，Oasis 在检测到故障后可以立刻改写 TX 路由，并让备份 NIC 借用故障 NIC 的 MAC 地址，使交换机把 RX 流量导向新的端口。UDP 实验里，中断大约持续 38 ms。memcached over TCP 的实验中，P99 延迟大约在 133 ms 内恢复，论文也明确解释这是因为可靠传输会把故障窗口中丢失的数据在客户端侧积压并重传，而不是控制面的 failover 本身更慢。

## 创新性与影响

这篇论文的新意不只是“CXL 很快，所以可以这么做”。Oasis 给出的是一套面向 non-coherent CXL 2.0 的完整 PCIe pooling 软件底座，而不只是一个关于硬件速度的观察。它对 CXL 系统、云资源管理和 I/O virtualization 都有价值，因为它说明为 memory pooling 部署的 CXL pod 还可以顺带摊薄 NIC 和 SSD 成本，而消息通道的设计也有机会被别的 CXL 系统复用。

## 局限性

论文最强的地方是 feasibility，因此局限性也主要来自这个定位。真正实现出来的只有 network engine；每个 frontend 和 backend 只用一条 I/O 线程；系统默认 DDIO 被关闭，并信任 frontend、backend 与 NIC；RX 路径仍要把 packet 从共享 CXL memory 复制到本地内存。实验只覆盖两台主机、一块 CXL device 和 100 Gbit NIC，也没有证明更大 pod 或 200/400 Gbit 时代下的行为。负载均衡只在启动或故障时触发，failover 依赖预留备份 NIC，而 CXL 链路故障与 VIP-to-DIP 公有云部署都还需要额外基础设施。

## 相关工作

- _Zhong et al. (HotOS '25)_ — 更早的 “My CXL Pool Obviates Your PCIe Switch” 主要提出动机，而 Oasis 给出了完整的设计、原型与评估。
- _Li et al. (ASPLOS '23)_ — Pond 论证了 CXL memory pool 对云平台内存利用率的价值；Oasis 则复用同样的 CXL pod 投资，把对象从 DRAM capacity 扩展到 PCIe device pooling。
- _Ma et al. (ATC '24)_ — HydraRPC 同样利用 shared CXL memory 做主机间通信，但 Oasis 把这一底座推进到远端设备访问与 failover，并专门解决 non-coherent datapath 的工程问题。
- _Hayakawa et al. (NSDI '21)_ — Prism 依赖可编程网络支持来迁移 TCP 流，而 Oasis 在 pod 内通过共享 CXL memory 和 NIC 映射切换来迁移流量，不要求专门的网络硬件。

## 我的笔记

<!-- 留空；由人工补充 -->

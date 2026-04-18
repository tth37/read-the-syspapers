---
title: "Building an Elastic Block Storage over EBOFs Using Shadow Views"
oneline: "Shadow View 把黑盒 EBOF 变成可观测的数据面，让 Flint 能跨 SSD 放置 extent、按 I/O 成本调度请求，并按需分配带宽。"
authors:
  - "Sheng Jiang"
  - "Ming Liu"
affiliations:
  - "Carnegie Mellon University"
  - "University of Wisconsin-Madison"
conference: nsdi-2025
code_url: "https://github.com/netlab-wisconsin/Flint"
tags:
  - storage
  - disaggregation
  - observability
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

论文的核心判断是：今天的 EBOF 很快，但太黑盒。客户端只能看到固定 block volume，看不到盒子内部真正的瓶颈。Shadow View 用软件重建这些运行状态，Flint 再利用这份视图跨 SSD 放置 extent、按成本调度 I/O，并公平分配带宽。在 Fungible FS1600 上，Flint 做到 9.3/9.2 GB/s 的读写带宽，并让 MinIO 最高提升 2.9x。

## 问题背景

EBOF 的吸引力在于，它用一个以交换机为中心、塞满 NVMe 的盒子取代了 CPU 很重的存储服务器，同时又通过兼容 block volume 保持了易部署性。但这种便利来自 smart-sender dumb-receiver 设计：每个 volume 静态绑到一块 SSD，带宽保留跟 volume 大小绑定而不是跟真实需求绑定，设备也几乎不暴露内部哪些端口、队列或 SSD 正在拥塞。

这带来三类问题。单个 volume 的吞吐很容易撞上单盘上限，浪费整机并行路径；小容量但高吞吐的业务被迫多申请空间，大容量但低吞吐的业务又隐式占着闲置带宽；而一旦请求在 SSD 或内部 pipeline 冲突，volume 级限速也挡不住干扰。论文展示了受害流的尾延迟会膨胀到毫秒级，碎片化 SSD 上的吞吐也会明显下跌。

## 核心洞察

论文的中心论断是：EBOF 不必先变成“完全可编程硬件”，也可以被高效管理。因为现代数据中心里跨服务器通信只有几微秒，客户端加上一个中心控制器，就能从端到端 I/O 观测里维护出一份“shadow view”，知道哪些端口、pipe 和 SSD 正在繁忙。这样一来，placement、scheduling 和带宽分配就可以根据真实瓶颈来做，而不是继续依赖静态 volume 元数据。

所以本文的贡献不只是“做了一个更好的逻辑卷管理器”。真正关键的是，它证明了 telemetry 本身就是使能因素：只要把黑盒 EBOF 变得足够可观测，上层软件就能实现弹性放置、逐 I/O 调度和运行时带宽拍卖。

## 设计

Shadow View 的第一步，是把 EBOF 建模成两个串联的 switch：Ethernet 端口通过 NetPipe 接到内部 I/O 端口，I/O 端口再通过 IOPipe 接到 SSD。它监控端口流量、pipe 吞吐与排队时延，以及 SSD 的可用容量、估计带宽余量、延迟和碎片度。每个客户端旁边的 view agent 上报 `<session, target SSD, type, size, RTT>`，中心化的 view controller 把这些向量映射回硬件模型，维护窗口统计，并通过按实体递增的计数器加上 hybrid push/pull 协议来同步 partial view。定位瓶颈时，它会从过载 SSD 反向追到相关 pipe 和 session。

Flint 建立在这层 telemetry 之上。它的 elastic volume（`eVol`）按 2 MB extent 管理数据，extent 可以落到任意 SSD。arbiter 为每块 SSD 先建一个 mega-volume，第一次写入时再惰性分配 extent，并根据历史分配次数、已用容量、繁忙程度、碎片程度和用户偏好打分来决定放到哪里。客户端侧用 `io_uring` 负责异步提交，再由一个 PIFO 风格的 eIO scheduler 按成本估计来优先放行更便宜的请求，同时保持单个 stream 内 FIFO。

容量与带宽也被解耦了。每个活跃 NVMe-oF session 都维护一个三元 deficit 向量，对应 NetPipe、IOPipe 和 SSD 资源。arbiter 把 deficit round robin 和类似 gang scheduling 的资源测试结合起来，只有当 shadow view 认为整条路径都有余量时才发新的 bandwidth slice。客户端手里有足够 slice 时走 fast path；不够时再走 slow path 续租，写入还可能额外申请新 extent。Flint 还支持用 chain replication 把 extent 复制到三块 SSD 上。

## 实验评估

原型约 7,600 行 C++，运行在 Dell R7525 客户端、Dell Z9264F-ON ToR 和 Fungible FS1600 上。最重要的结果是，eVol 终于把 EBOF 当成“整机”来用，而不是继续受困于单盘视角。对大 I/O，Flint 达到 9.3 GB/s 随机读和 9.2 GB/s 顺序写带宽，相比单个 physical volume 分别提升 14.5x 和 13.6x。对 4 KB 随机读和 4 KB 顺序写，中位延迟基本不变，但 P99 仍分别下降 48.1% 和 13.4%。

公平性实验支持了带宽拍卖的设计。在多组 4 KB/128 KB、读多写少/写多读少流的竞争里，Flint 都能让带宽更接近真实需求，而不是更接近 volume 容量。关闭该机制后，论文给出的一个例子是 128 KB 读流能拿到 4 倍于 4 KB 写流的带宽。干扰实验则说明 Shadow View 确实找到了坏路径：当 4 KB 受害 I/O 与更重的背景流共享 SSD 时，eIO scheduler 明显降延迟；在 4 KB 读对 128 KB 随机读的场景下，P50/P99/P999 分别提升 4.8x、2.6x 和 7.5x。作者再故意把 SSD 压到拥塞后，动态 remapping 加调度又把平均延迟在读拥塞和写拥塞下分别降低 40.1% 和 29.8%，并比 LVM 快 2.3x 到 3.8x。

端到端应用实验里，MinIO over Flint 相比基础 EBOF volume 最高把吞吐提升到 2.9x，并把平均读/写延迟最多降低 66.4%/74.6%。telemetry 自身的开销也不大：`view_query` 的 P50/P99 是 24 us / 31 us，`view_sync` 的 P50 是 38 us，P99 低于 70 us。

## 创新性与影响

这篇论文真正新的地方，不只是 elastic volume，而是 shadow view 这个抽象：它在不改硬件的情况下，从一个封闭 EBOF 里恢复出足够可用的内部状态，让 placement、scheduling 和 fairness policy 都能围绕同一份视图工作。对那些硬件已经固定、但控制面还能继续做聪明事的 disaggregated storage 研究和工程实践，这个思路很有参考价值。

## 局限性

Shadow View 仍然有很强的“间接性”：很多 SSD 内部状态都是通过端到端时延反推的，如果这些估计失真，scheduler 和 bandwidth auction 就会做错决策。系统也依赖外部 arbiter 和 controller，而论文的评估规模还比较小。

复制部分进一步暴露了理想设计与真实硬件之间的差距。因为 FS1600 没有暴露 recirculation，链式复制写入必须多走额外网络往返，使 4 KB / 128 KB 写的 P50 分别恶化 2.9x / 3.5x。最后，单个挂载 volume 的吞吐仍会被客户端 NIC 封顶；想继续扩展，就需要多个 session 或多个客户端。

## 相关工作

- _Klimovic et al. (EuroSys '16)_ - Flash storage disaggregation 主要说明了 remote flash 的性能可行性，而本文关注的是在这种硬件已经存在后，如何管理一个黑盒 EBOF。
- _Klimovic et al. (ASPLOS '17)_ - Reflex 构建了一个低开销的 remote-flash datapath；Flint 则基本保留厂商 EBOF datapath，在外围增加软件 telemetry 和控制层。
- _Min et al. (SIGCOMM '21)_ - Gimbal 面向多租户 SmartNIC JBOF，更偏保守的干扰控制；Flint 借助 Shadow View 估计运行时瓶颈，并在 EBOF 上做到逐 I/O 粒度调度。
- _Shu et al. (OSDI '24)_ - Burstable cloud block storage with DPUs 同样在 commodity storage 外部增加智能控制，但 Flint 的独特之处在于重建盒内隐藏状态，并用它驱动 extent placement 和带宽拍卖。

## 我的笔记

<!-- 留空；由人工补充 -->

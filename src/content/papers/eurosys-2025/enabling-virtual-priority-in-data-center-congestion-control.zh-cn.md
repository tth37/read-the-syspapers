---
title: "Enabling Virtual Priority in Data Center Congestion Control"
oneline: "PrioPlus 把优先级映射成时延通道，让端侧拥塞控制在不改交换机的前提下，于一个物理队列里实现多级严格虚拟优先级。"
authors:
  - "Zhaochen Zhang"
  - "Feiyang Xue"
  - "Keqiang He"
  - "Zhimeng Yin"
  - "Gianni Antichi"
  - "Jiaqi Gao"
  - "Yizhi Wang"
  - "Rui Ning"
  - "Haixin Nan"
  - "Xu Zhang"
  - "Peirui Cao"
  - "Xiaoliang Wang"
  - "Wanchun Dou"
  - "Guihai Chen"
  - "Chen Tian"
affiliations:
  - "Nanjing University"
  - "Shanghai Jiao Tong University"
  - "City University of Hong Kong"
  - "Politecnico Milano & Queen Mary University of London"
  - "Unaffiliated"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3717463"
code_url: "https://github.com/NASA-NJU/PrioPlus"
tags:
  - networking
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PrioPlus 的做法是把排队时延切成按优先级递增的通道：流只有在 RTT 落在自己通道内时才继续发包，超过上限就主动让路。它在 Swift 之上补了 probing、linear start、dual-RTT adaptive increase 和按流数估计调节激进度等机制，因此不用改交换机，也能在一个物理队列里逼近严格优先级。论文里的主要仿真结果是，高优先级性能相对理想物理优先级的退化不超过 9%，而低优先级大流常常因为带宽回收更快而更受益。

## 问题背景

数据中心缺的不是优先级算法，而是可用的物理优先级队列。交换机通常只有 8 个或 12 个优先级，DSCP 和 PFC 也都卡住了命名空间；再加上带宽增长快于缓冲增长，每新增一个优先级都会吃掉更宝贵的 buffer。问题在于，这些少量物理优先级已经要承担跨流量类型隔离，例如实时业务、后台流量、RDMA 或租户级 QoS，于是同一类流量内部几乎没有足够的层级可供调度。

把更复杂的优先级逻辑搬进交换机，往往意味着 ASIC 改造或可编程硬件。论文要做的是反过来：让端侧拥塞控制在一个物理队列里合成出很多个严格优先级。现有 CC 做不到。D2TCP 仍然把高低优先级绑在同一个 ECN 门限上；Swift 虽然有多比特时延信号，但如果只是给不同优先级配不同 target delay，系统最后收敛出来的更像带权共享，而不是严格抢占。

## 核心洞察

作者的核心判断是，虚拟优先级应该被表示成端侧可容忍的排队时延区间，而不是交换机内部的调度状态。每个优先级都有自己的 delay channel。低优先级流看到 RTT 超过本级 `Dlimit`，就推断更高优先级正在发送，于是完全停发；高优先级流则继续把时延推向自己的 `Dtarget`，把低优先级挤出去。

真正的难点，是让这些通道既不把高优先级时延整体抬高，又足以容纳正常的 CC 振荡和时间戳噪声。PrioPlus 的贡献，就是把这个抽象变成一套可运行的端侧控制逻辑。

## 设计

PrioPlus 叠在现有 delay-based CC 之上。对优先级 `i`，它增加一个 `Dtarget` 和一个更高的 `Dlimit`，优先级越高，这两个阈值越大，同时关闭底层 CC 的 target scaling。RTT 低于 `Dtarget` 时，原始 CC 正常工作；RTT 超过 `Dlimit` 时，该流立即停发，把带宽让给更高优先级。

让路之后，流不会靠常驻最低速率保活，而是用 probe with collision avoidance：在大致 `delay - Dtarget + random(baseRTT)` 之后发一个 64 字节 probe。如果返回的 RTT 仍高于 `Dlimit`，就继续沉默并安排下一次探测。RTT 等于 base RTT 时，PrioPlus 用 linear start，每个 RTT 按固定 `WLS` 增加 `cwnd`，而不是直接 line-rate start 或 TCP 式 slow start。RTT 介于 base RTT 和 `Dtarget` 之间时，则启用 dual-RTT adaptive increase，按当前时延与目标时延的比值估计窗口该增大多少，单次最多增加到当前窗口的一半，而且只每两个 RTT 执行一次，因为一次放大对时延的完整影响要到两个 RTT 之后才看得见。

为了不把通道做得太宽，PrioPlus 还用 inflight data 除以本地 `cwnd` 去估计同优先级活跃流数，并按这个估计缩放 additive increase 与 linear start 的激进度，避免大量流一起把队列振荡出通道。另一个做法是要求 RTT 连续两次超过 `Dlimit` 才真正让路，用来过滤长尾测时噪声。论文在 Swift 的实验配置里把 150 个竞争流带来的波动预算设为 3.2 微秒，把 99.85 分位的时间戳噪声设为 0.8 微秒，因此优先级间隔设置为 4 微秒。

## 实验评估

实现负担很小。作者在 DPDK 版 Swift 上只增加了 79 行代码；若放到 RNIC 上，额外状态也只是 9 个变量、13 字节和一个定时器。10 Gbps、约 13 微秒 RTT 的测试床先证明它能跑起来：4 个相邻优先级在同一瓶颈上能明显分层；另一组放大控制步长的实验里，PrioPlus 仍能把时延压在 37 微秒附近，而普通 Swift 经常越过 39.4 微秒。

更主要的证据来自 ns-3。通用流调度场景下，PrioPlus + Swift 与理想物理优先级的整体平均 FCT 最多只差 8%；小流和中等流的平均值与 p99 退化分别不超过 9% 和 19%。低优先级大流反而是它的强项：相对物理优先级 + Swift，平均 FCT 提升 25% 到 41%，tail FCT 提升 24% 到 43%，原因是被抢占后能更快把链路重新吃满。应用级负载里，Coflow 的整体 speedup 在 40% 负载时比物理优先级高 12%，在 70% 负载时高 21%；模型训练里，PrioPlus 把 ResNet 和 VGG 分别提升 12% 和 15%，总加速 13%，而物理优先级对应的是 16%、-18% 和总加速 9%。

## 创新性与影响

按作者的定位，PrioPlus 是第一种不依赖交换机支持、却能实现严格虚拟优先级的方案。真正的新意不在于又造了一个 packet scheduler，而是把拥塞控制本身改造成物理队列内部的优先级执行器，因此它才有机会以很小的改动量嫁接到现有 CC 上。

如果这个思路能推广到生产环境，它最有价值的地方就是把稀缺的硬件优先级继续留给跨流量类型隔离，同时在每一类流量内部派生出更多调度层级，服务 coflow、存储和模型训练这类任务。

## 局限性

PrioPlus 和 delay-based CC 绑定得很紧。论文展示了 Swift 与 LEDBAT 的集成，但没有真正覆盖 DCQCN、HPCC 这类主流 ECN-based 数据中心 CC，也没有延伸到 Homa、pHost 这类 receiver-driven transport。它还默认网络能提供相当干净的时延测量，并最好让 ACK 走最高物理优先级。

此外，部署证据仍以仿真为主。真实实现只有小规模 10 Gbps DPDK 测试床，较强的性能结论来自 ns-3；通道宽度、噪声容忍度和流数估计器也主要靠经验调参。再加上论文研究的是严格优先级而不是带权共享，低优先级饥饿与跨优先级公平性仍未解决。

## 相关工作

- _Vamanan et al. (SIGCOMM '12)_ - D2TCP 按 deadline 调整 ECN 反应，但一旦跨过同一个拥塞门限，高低优先级还是会一起减速。
- _Kumar et al. (SIGCOMM '20)_ - Swift 提供了 PrioPlus 所依赖的 delay-based CC 基底，但单独使用 Swift 时，系统会更接近带权共享，而非严格虚拟优先级。
- _Montazeri et al. (SIGCOMM '18)_ - Homa 借助网络优先级和 receiver-driven 调度降低 RPC 时延，而 PrioPlus 关注的是怎样在一个物理队列里再合成出更多优先级。
- _Atre et al. (NSDI '24)_ - BBQ 关注高速硬件 packet scheduling，本质上还是交换机侧能力；PrioPlus 则把优先级机制挪到端侧拥塞控制里，避免升级交换机。

## 我的笔记

<!-- 留空；由人工补充 -->

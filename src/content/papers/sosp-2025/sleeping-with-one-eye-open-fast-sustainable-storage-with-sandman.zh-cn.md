---
title: "Sleeping with One Eye Open: Fast, Sustainable Storage with Sandman"
oneline: "Sandman 通过让 polling core 浅睡、用基于缓存一致性的 user wait 唤醒，并按 NIC 队列到达请求检测 burst，在保持 SPDK 级性能的同时显著降低全闪存储能耗。"
authors:
  - "Yanbo Zhou"
  - "Erci Xu"
  - "Anisa Su"
  - "Jim Harris"
  - "Adam Manzanares"
  - "Steven Swanson"
affiliations:
  - "UC San Diego"
  - "Shanghai Jiaotong University"
  - "Samsung Semiconductor"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764804"
tags:
  - storage
  - scheduling
  - energy
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Sandman 针对的是现代全闪存储服务器里一个很具体的浪费来源：polling stack 为了应对 burst 会长期把很多 CPU core 保持在高活跃状态。它保留了 SPDK 式 polling datapath，但把工作尽量压缩到更少的 core 上，让空闲 polling core 进入浅睡，用基于 cache coherence 的 user-wait 指令直接唤醒，并且从 NIC 队列到达的 I/O 数量而不是 CPU load 去判断 burst。结果是在接近 SPDK 延迟的同时，显著降低能耗。

## 问题背景

论文的出发点是，SSD 越快，存储服务器的软件栈就越像能耗瓶颈而不是介质瓶颈。在作者的 NVMe-oF 实验环境里，一个 logical core 用 SPDK 大约能驱动 `800K` IOPS，因此一块可达 `2,500K` IOPS 的 PCIe 5.0 SSD 就至少要三个 logical core 才能吃满。这带来的代价不只是 CPU 配额更高，还包括更高的内存和散热功耗。

busy polling 进一步放大了问题。在他们的 16 SSD 服务器上，即便负载不到最大 IOPS 的 `5%`，CPU 功耗仍然几乎维持在峰值负载附近；而在真实云 trace 中，为了应对 burst 预留的计算能力，会让系统白白消耗高达实际所需 `3.4x` 的能量。根因并不是系统长期满载，而是负载短促而频繁地波动。

现有省电方案各有各的失败方式。Linux interrupt 在轻载时能省电，但要付出 context switch 代价；在重载下，它甚至可能比 SPDK 更耗能，因为每个 I/O 需要更多 CPU 工作。Governor 通过降频省电，但 P-state 切换本身就要几百微秒。Dynamic Scheduling 会在 polling core 之间迁移线程，但它靠 CPU cycle 估计负载，又通过 software interrupt 唤醒睡眠 core，所以既难以准确捕获微秒级 burst，也会在唤醒路径上引入额外延迟。Hybrid Polling 虽然避免了最坏的性能损失，但每个 core 独立且短暂地睡眠，导致真正的能耗收益有限。

## 核心洞察

这篇论文的核心主张是：存储栈要靠“让 polling core 睡下去再快速醒来”来缩放算力，而不是靠降频，也不该把 interrupt-heavy 的关键路径重新带回来。前提是唤醒足够快，并且调度器能在 CPU load 统计显现之前就看到 burst。

因此 Sandman 把两个判断绑在一起。第一，浅睡才是正确的低功耗状态，因为返回高性能态的路径足够短；论文测得，从 `C-1` 退出大约只要 `3 us`，而降到 `400 MHz` 后恢复约需 `450 us`，更深的睡眠状态约需 `800 us`。第二，最好的 burst 信号不是 thread load，而是 NIC 队列上的到达 I/O 数，因为请求一进队列，就已经暴露了新的需求，而线程还没来得及积累足够的 busy cycle 去“看起来很忙”。这两个选择叠加起来，使 Sandman 能在延迟上逼近 static polling，同时在多数时间里关掉多余的计算能力。

## 设计

Sandman 运行在 SPDK 之上，把 core 分成一个 main core 和多个 worker core。每个 core 仍然执行 RDMA 网络和 NVMe completion 的 polling datapath，但 main core 额外承担 scheduler。工作被组织成轻量级 user-level I/O thread；每个 I/O thread 代表一组任务，存放在 ring list 里。某个 core 每轮从队首取出一个 I/O thread，顺序执行其任务，再放回队尾；跨 core 迁移工作，只是把这个 I/O thread 从一个 ring 中摘下，再插入另一个 ring。

最有辨识度的机制是它的快速唤醒路径。当某个 worker core 变空闲时，Sandman 先搬走它的 I/O thread，再在下一个 event-queue slot 上设置 `monitorx`，随后执行 `mwaitx`，让该 core 在浅睡状态下监视这条 cache line。之后若 scheduler 想复用这个 core，别的 core 只需向事件队列写入一个 scheduling event；cache coherence 状态变化就会直接把睡眠 core 唤醒，整个关键路径里没有 system call，也没有 interrupt。论文测得 thread movement 只需 `106.52 ns`，而 Dynamic Scheduling 的 software-interrupt 唤醒路径约为 `27 us`。

控制策略分成两个时间尺度。每 `1 s`，Sandman 观察 core load，把轻载 thread 合并到仍然健康的 core 上，并优先选择能让 sibling hyper-thread 一起睡下去的放置方式。默认 healthy threshold 是 `80%` busy cycles，给 burst 留出 `20%` 的缓冲；idle threshold 则是它的一半。每 `10 us`，Sandman 做一次 burst detection。它不看 CPU load，而是统计每个 thread 在 RDMA receive queue 上收到的 I/O 数量，维护 moving average 和 standard error，构建 confidence interval；若当前计数超过上界，就认为出现 burst。此时它会立即唤醒一个未使用的 core，并把整个 core 分配给该 thread，等 burst 消退后再由粗粒度调度重新收拢。

实现上，作者扩展了 SPDK 的 scheduler、event queue 和 poller，然后增加 user-wait 抽象层、基于队列的 burst-detection 模块，以及新的 scheduler。也就是说，这并不是从零开始重写一套 storage stack；datapath 依然是 SPDK 式 busy polling，真正的新意在于它决定何时缩小或扩大 polling footprint 的方式。

## 实验评估

实验平台由两台 AMD EPYC 9454P 服务器组成，通过双 `200 Gbps` RDMA 互连，每个存储节点有 `16` 块 Samsung PM1743 PCIe 5.0 SSD。对比基线并不弱：SPDK 被视为最佳性能上界，而 Linux、Governor、Dynamic Scheduling 和 Hybrid Polling 都是经过调优的替代方案。

在跨 `16` 块 SSD 的稳定 `4 KB` 随机读负载下，Sandman 的功耗与 Governor、Dynamic Scheduling 相近，但延迟明显更接近 SPDK。论文报告 Sandman 的 tail latency 与 SPDK 只差 `4.8%`，而 Governor 在 `5210K` IOPS 时最高可达到 `161.5%` 的额外延迟；Dynamic Scheduling 则在 thread migration 变频繁后急剧恶化。这支持了论文的核心论证：sleep-based scaling 加上更好的 burst 信号，比降频或基于 cycle 的调度更有效。

在显式 burst 负载下，Sandman 更有说服力：相对 SPDK，系统功耗最高可下降 `39.38%`，但 tail latency 和 IOPS 仍与 SPDK 基本一致，而 Linux 与 Governor 都明显更差。论文的消融实验也很有价值。把 frequency scaling 换成 sleeping cores，延迟下降 `41.34%`；再加入基于 NIC queue 的 burst detection，进一步下降 `25.13%`；再去掉唤醒路径上的 interrupts，又额外下降 `17.69%`。在功耗方面，hybrid polling 的确有帮助，但真正拉开差距的是 sleeping cores 和 sibling-aware packing。burst detector 在稳定负载下以避免无谓迁移为标准可达到 `93.45%-95.78%` 的准确率，在真实 burst 上的检测准确率为 `97.84%`。

应用级结果方向一致。在 SPDK RAID-5 和 RocksDB/YCSB 上，Sandman 同时拿到了接近 Governor 类方案的低功耗，以及更接近 SPDK 的吞吐和延迟。在 Alibaba 和 Tencent 的 24 小时块存储 trace 上，它给出了论文最关键的端到端结论：相对 Linux 能耗下降 `30.23%`，相对 SPDK 下降 `33.36%`，同时延迟分布是所有省电方案里最接近 SPDK 的。

## 创新性与影响

Sandman 的新意不在于提出了新的 SSD datapath，也不只是单独提出一种调度理论。它真正新的是把三件此前分散存在的东西组合到了一起：浅睡型 core scaling、通过 cache-coherence user wait 实现的无 syscall 唤醒路径，以及用 network queue 到达请求代替 CPU-cycle accounting 的 burst detection。这个组合让 polling-based storage stack 可以把 energy efficiency 变成一等目标，同时又不放弃 SPDK 之所以有吸引力的性能轮廓。

它的影响对象首先会是 disaggregated flash server 和各种存储后端，因为这些系统本来就要为 bursty demand 付出过度预留的成本。更广泛地说，这篇论文也给 sustainable systems 提供了一个清楚的论点：当硬件快到一定程度以后，“高性能”不再等于“让软件永远忙着转”，软件栈本身会成为能耗和碳排的重要来源。

## 局限性

Sandman 依赖较新的硬件与软件前提。它最理想的唤醒路径需要现代 Intel 或 AMD 服务器 CPU 上的 unprivileged user-wait instruction；在更旧的平台上，它会回退到 software interrupt，因此优势会变弱。该设计还默认自己运行在围绕 SPDK、RDMA queue 以及显式 per-thread queue 可见性的 polling datapath 上，论文没有证明同样的控制逻辑可以无缝移植到差异很大的存储栈。

调度器本身也不是零成本。在 `10 us` 的细粒度间隔下，main core 有 `16.6%` 的 CPU 时间要花在调度算法上，不过作者认为这主要落在原本就给 scheduler 和 idle thread 预留的 core 上。更重要的是，评估对象仍集中在一种很现代的全闪服务器场景里，以 `4 KB` 随机读、少量应用 benchmark 和两条 field trace 为主。这已经足以支撑系统论文的主张，但还不足以说明 Sandman 对所有存储负载和部署拓扑都是最优答案。

## 相关工作

- _Fried et al. (OSDI '20)_ - Caladan 证明了 userspace scheduling 可以在微秒级时间尺度上快速响应负载变化；Sandman 则把这种时间尺度用于存储服务器的能耗管理，而不是 RPC 干扰控制。
- _Jia et al. (SOSP '24)_ - Skyloft 同样利用 userspace 机制降低调度开销，但重点是调度效率本身；Sandman 则把快速唤醒机制放进一个面向存储的 power-management loop 中。
- _Reidys et al. (OSDI '22)_ - BlockFlex 展示了 cloud block storage 的需求具有 bursty 且可收割的特性；Sandman 进一步处理这些 bursty backend 在 always-on polling 下造成的 CPU 能耗浪费。
- _Shu et al. (OSDI '24)_ - Burstable cloud block storage with DPUs 把 burst 处理更多地下沉到专用设备，而 Sandman 则保留 storage server 上的软件栈，并减少其 polling core 消耗的功率。

## 我的笔记

<!-- empty; left for the human reader -->

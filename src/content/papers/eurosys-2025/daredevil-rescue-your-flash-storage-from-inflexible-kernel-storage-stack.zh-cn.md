---
title: "daredevil: Rescue Your Flash Storage from Inflexible Kernel Storage Stack"
oneline: "daredevil 把 blk-mq 固定的 core-to-NQ 绑定拆开，用 SLA 感知的请求路由和 NQ 调度在商品 NVMe SSD 上隔离低时延与高吞吐租户。"
authors:
  - "Junzhe Li"
  - "Ran Shu"
  - "Jiayi Lin"
  - "Qingyu Zhang"
  - "Ziyue Yang"
  - "Jie Zhang"
  - "Yongqiang Xiong"
  - "Chenxiong Qian"
affiliations:
  - "The University of Hong Kong"
  - "Microsoft Research"
  - "Peking University"
  - "Zhongguancun Laboratory"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717482"
code_url: "https://github.com/HKU-System-Security-Lab/Daredevil"
tags:
  - storage
  - kernel
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文认为，NVMe 多租户隔离做不好，症结不在 Linux 缺少优先级接口，而在 `blk-mq` 把每个 CPU core 永久绑死到一条固定队列路径上。daredevil 用 SLA 感知的请求路由替代这条静态路径，再配合 NQ 调度，把低时延租户和高吞吐租户分流到不同 NVMe 队列里。作者在自己的平台上报告了最高 3-170x 的时延下降，同时大体保住了 T-tenant 的吞吐。

## 问题背景

论文讨论的是云服务器里很常见的一类本地存储场景：多个租户共享一块 NVMe SSD，但它们要的服务完全不同。L-tenant 发的是小请求，最在意时延；T-tenant 发的是批量大请求，更在意吞吐。一旦两类请求落到同一个 NVMe I/O queue，排在前面的 T-request 就会在提交和完成两个阶段同时拖慢后面的 L-request。作者的动机实验给出了很直观的量化结果：如果让 L 和 T 在同一组队列里互相干扰，L-tenant 的平均时延最高会放大 3.49x，尾时延最高放大 15.7x。

现有软件方案的问题，是它们继承了 `blk-mq` 的基本形状。FlashShare 和 D2FQ 会给每个 core 静态多配几条队列，但热点 core 依旧借不到冷门 core 手里的空闲队列。`blk-switch` 试图靠跨核调度把工作挪开，可这样一来，CPU 放置和 I/O 隔离被绑成了同一个优化问题。更麻烦的是，多 namespace 情况下 Linux 会为每个 namespace 各建一套 `blk-mq`，可底层物理 NVMe 队列其实还是共享的，所以上层看起来分开了，底下的干扰却还在。

## 核心洞察

论文最关键的判断是，队列归属不该由 core 静态决定，而应该由请求的 SLA 决定。只要一个 core 能把请求发到任意 NVMe queue，问题就从固定绑定变成了可调度的分流问题。这样一来，即使 SSD 固件完全不改，内核也能用软件方式把 L-request 和 T-request 分开。

这也是 daredevil 能处理多 namespace 的原因。请求最终落到哪条 NQ，本质上是设备级事实，不是某个 namespace 自己的局部事实。只要 block layer 能直接观察并调度这些队列，就能在所有 namespace 上执行一套统一策略，而不是让每个 namespace 各自局部优化、最后在共享物理队列里重新撞车。

## 设计

daredevil 由三部分组成。第一部分 `blex` 是解耦后的 block layer。它去掉了 `blk-mq` 里固定的 SQ-to-HQ 路径，用轻量级 `nproxy` 把每条 submission queue 的状态暴露出来，让每个按 core 建立的软件队列都可以连接任意 NVMe submission queue。这样既保留了驱动层的模块边界，又把 core 到队列的连接从单一路径改成了全连通。

第二部分 `troute` 负责决定请求发往哪里。它先从 `ionice` 推断租户的基础 SLA：real-time 视为高优先级的 L-tenant，其余视为低优先级的 T-tenant。接着它还会识别那些经常发同步请求或元数据请求的 T-tenant；论文把这类请求当成 outlier request，通过检查 `REQ_SYNC` 和 `REQ_META` 来识别。被打上 outlier 倾向的 T-tenant 会同时持有一条默认的低优先级队列和一条高优先级的 outlier 队列；若只是偶发 outlier，则按请求临时查询高优先级队列。这样做的重点在于，隔离是通过请求路由完成的，而不是靠跨核搬迁完成的。

第三部分 `nqreg` 给队列分工并负责调度。它先把 NQ 划成高优先级和低优先级两组，再用两阶段调度来选队列：先选一条最能改善 IRQ balance 的 completion queue，再在它挂着的 submission queue 里挑一条最能降低争用的队列。队列 merit 会做指数平滑，更新频率由 MRU 策略限制，并发查询则用 RCU 保护。最后，daredevil 还把提交和完成路径也做成 SLA 感知的：高优先级队列立即通知控制器、按请求完成；低优先级队列则批量通知、批量完成。

## 实验评估

主要实验跑在 Linux 6.1.53、64 核 EPYC 7702P 和 3.2 TB Samsung PM1735 NVMe SSD 上，对比对象是原生 `blk-mq` 和移植到同一内核版本的 `blk-switch`。在单 namespace 的 FIO 主实验里，作者固定 4 个 L-tenant，再逐步提高 T-pressure，所有租户共享 4 个 core。结果显示，在服务器平台上，daredevil 最多把 L-tenant 的 99.9 分位尾时延和平均时延分别降到原来的 1/3.2 和 1/33；在另一台每个 core 可用 submission queue 更多的工作站上，这两个收益进一步扩大到 40x 和 170x。论文摘要里总结的 3-170x 时延改善，基本就是从这些高干扰场景里来的，而且现象和设计预期一致：队列越多、干扰越重，收益越明显。

多 namespace 结果是论文最有说服力的一部分。作者创建了 4、8、12 个 namespace，L/T namespace 比例固定为 1:3。daredevil 依然能把 L-tenant 的尾时延和平均时延最多分别压低 15.3x 和 39.3x，同时吞吐基本维持在 vanilla 水平。这正好验证了论文对旧方案的批评：如果系统只在单个 namespace 视角里做隔离，就会漏掉共享物理队列上的真实干扰。

真实工作负载的结果更克制，也因此更可信。对 RocksDB + YCSB，daredevil 把 YCSB-A 里 update 的尾时延相对 `blk-switch` 降低 2x，也能改善 YCSB-F；对 Filebench Mailserver，它让 `fsync` 快 2-3 ms，让 `delete` 快 0.5-1.2 ms。可在 YCSB-B、YCSB-E 以及 Mailserver 里大量命中缓存的部分，收益就不明显了。开销分析也很有价值：如果单看局部步骤，跨核 submission 和 completion 分别会带来 1.4-1.6x 与 3.3-3.6x 的额外代价，但这些额外成本在端到端时延里最多只占 1.7%，因为调度器会主动把请求摊到更少争用的队列上。真正需要警惕的是 SLA 快速抖动：若频繁改 `ionice`，L-tenant IOPS 最低会掉到正常值的 7.4%，T-tenant 吞吐最低掉到 25%，说明这套机制默认优先级不会高频震荡。

## 创新性与影响

这篇论文的创新点，不是单独提出一个新的 SSD 调度器，而是重新拆分了 Linux 存储栈里的责任边界。FlashShare 和 D2FQ 试图在保留 `blk-mq` 基本绑定模型的前提下做隔离；daredevil 则直接指出，真正卡住软件方案的恰恰就是这套绑定本身。`blk-switch` 在思路上更接近，但它把跨核调度放在中心位置；daredevil 则把请求路由和队列调度提升为第一控制面，让队列分配不再依赖 CPU 放置。

这使它成为一篇很实在的系统论文。对云数据库、本地缓存服务、存储 sidecar 这类依赖本地 NVMe 的系统来说，它给出的结论很明确：在动 SSD 固件之前，先把内核里固定的队列路径拆开，就已经能解决一大块多租户干扰问题。而且作者还讨论了 smartNIC、CXL SSD 等其他 multi-queue 设备，这让它的影响面不只停留在一块 NVMe SSD 上。

## 局限性

论文明确承认，daredevil 解决不了微秒级时延问题。即便做完队列隔离，L-request 看到的整体时延仍然是毫秒级，因为 SSD 内部的排队、flash 介质行为等干扰还在。这一点很重要：daredevil 修的是 kernel storage stack 的瓶颈，不是整个设备栈的全部瓶颈。

除此之外还有几个边界。当前实现不支持 VM，因为 guest 里的应用对 host kernel 来说不可见到论文所需的粒度。它默认运行环境是可信的，`ionice` 基本能反映真实 SLA。对 CPU 或 page cache 主导的工作负载，它的收益会变小，甚至接近没有。再加上实验虽然做得扎实，但硬件覆盖面主要还是一块企业级 SSD 加一块工作站 SSD，所以外推到更广设备族时仍需谨慎。

## 相关工作

- _Zhang et al. (OSDI '18)_ - FlashShare 同样处理 NVMe SSD 上混合时延与吞吐流量，但它依赖固件相关机制，而且仍工作在比 daredevil 更刚性的队列绑定框架里。
- _Woo et al. (FAST '21)_ - D2FQ 关注 NVMe SSD 的公平队列服务，而 daredevil 关注的是在内核存储栈里拆掉固定 core-to-queue 路径，用 SLA 分流来隔离不同请求类别。
- _Hwang et al. (OSDI '21)_ - `blk-switch` 是最接近的软件基线：它通过跨核调度重构 Linux 存储路径，而 daredevil 改为把请求路由和队列调度作为主控制面，并补上多 namespace 支持。
- _Peng et al. (USENIX ATC '23)_ - LPNS 处理云环境中的可预测本地存储虚拟化，daredevil 则更靠近 host kernel，重点是共享 NVMe 设备上的队列级隔离。

## 我的笔记

<!-- 留空；由人工补充 -->

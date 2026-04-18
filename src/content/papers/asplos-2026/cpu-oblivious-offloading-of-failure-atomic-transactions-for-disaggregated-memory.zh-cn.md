---
title: "CPU-Oblivious Offloading of Failure-Atomic Transactions for Disaggregated Memory"
oneline: "Fanmem 把解耦内存事务日志的持久化下沉到 CXL 交换机，用异步完成检查替代同步远端 fence，同时不要求改 CPU。"
authors:
  - "Cheng Chen"
  - "Chencheng Ye"
  - "Yuanchao Xu"
  - "Xipeng Shen"
  - "Xiaofei Liao"
  - "Hai Jin"
  - "Wenbin Jiang"
  - "Yan Solihin"
affiliations:
  - "Huazhong University of Science and Technology, Wuhan, Hubei, China"
  - "University of California, Santa Cruz, Santa Cruz, California, USA"
  - "North Carolina State University, Raleigh, North Carolina, USA"
  - "University of Central Florida, Orlando, Florida, USA"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790146"
tags:
  - disaggregation
  - persistent-memory
  - transactions
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Fanmem 瞄准的是解耦内存上持久化事务最痛的一步：最后那个仍然要让 CPU 等待远端持久化完成的同步 fence。它的做法是让 CXL 交换机提前确认日志写入、自己跟踪持久化进度，再由软件稍后轮询确认。这样既保住 failure atomicity，也不需要改 CPU。

## 问题背景

论文首先指出一个很现实的错位：持久内存事务最初是为“持久化设备离 CPU 足够近”的机器设计的，`clwb` 加 `sfence` 虽然昂贵，但尚可接受。到了 CXL 风格的内存解耦环境里，这个假设失效了，因为日志写入必须穿过交换机，到达远端内存服务器并真正落盘后，fence 才能退休。论文引用的 CMM-H 访问中位延迟约为 `728.9ns`，这意味着每次 persist barrier 都可能变成事务执行路径上的主瓶颈。

现有方案各有缺口。SpecPMT 这类纯软件方法减少了 fence 的数量，但剩下的那一个仍然要同步等待。HOOP、ASAP 这类硬件方案虽然能更积极地重叠持久化，却要求 CPU 侧架构支持，因此与 CXL 想强调的异构、厂商无关部署方式并不契合。于是，这篇论文真正要解决的问题并不只是“把事务做快”，而是“在 compute server、switch、memory server 都可能失败的前提下，提供 failure-atomic 事务，而且不要把方案绑死在某一种 CPU 上”。

## 核心洞察

这篇论文最值得记住的命题是：在解耦内存上，CPU 并不需要精确知道每一条远端日志写入何时变得 durable；它只需要一个足够便宜的办法，判断“某个事务对应的日志前缀是否已经确定到达持久内存”，然后再决定是否提交。

这就给了 Fanmem 一个新的放置点：把持久化进度跟踪放进 CXL 交换机。如果每个线程都把日志写进一个 append-only 的顺序日志区域，交换机只需维护一个 cursor，表示当前已经连续持久化到哪里。软件不再在关键路径上等远端持久化完成，而只是等日志写入到达交换机，然后先继续执行其他工作，之后再通过 cursor 检查来确认日志尾部是否 durable，再执行 commit。六个月后回看，这篇论文留下的核心记忆应该是：顺序日志加上交换机侧 durability cursor，就足以把执行与持久化解耦，同时保持简单的提交规则。

## 设计

Fanmem 把事务生命周期拆成 execution、offloading 和 commit 三段。执行阶段里，软件像 SpecPMT 一样直接修改数据，并记录包含新值的 speculative log。到了 offloading 阶段，软件对日志执行 `clwb`，随后执行 `sfence`，但 Fanmem 改写了这个 fence 的语义：CPU 不再等待远端内存服务器确认持久化，只需要等到 Fanmem-enabled 的交换机收到并缓存这些日志写入即可。事务随后通过 `tx_end()` 结束执行，应用可以先去做别的工作，稍后再检查持久化是否完成。

支撑这一点的是每线程一个顺序日志区域。由于每个日志区都是 append-only 且物理连续的，持久化状态就能被压缩成“一个 cursor”。软件只需要记住某个事务最后一条日志记录的最后一个字节地址，之后通过一次 memory-mapped load 读取对应 cursor。如果 cursor 已经越过该地址，就说明该事务的日志已经 durable。

交换机内部有两个关键结构。Log Area Table（LAT）负责判断一条写请求是否命中了已注册的日志区域。为避免大而慢的全关联查找，LAT 按 source port 划分为多个较小的 pLAT。Log Write Status Table（LWST）则跟踪每个日志区域里正在飞行中的日志写入。它不保存每个请求的完整地址，而是用一个 cursor 加一个 sliding-window bit vector 来描述从当前 durable frontier 往后的若干 64B 日志项状态。远端内存服务器返回“已持久化”确认后，交换机把对应项标成 persisted，并把 cursor 沿着连续 durable 的前缀推进。

正确性仍由 CPU 侧提交逻辑保证，而不是把事务语义塞进交换机。Fanmem 在事务 execution 结束时打时间戳，随后按照执行顺序提交那些已经确认持久化的事务，保守地把更早结束的事务视作依赖项。恢复时，系统读取最近一次持久化的 per-process commit timestamp，只回放已提交的日志。这样一来，交换机仍然保持 lightweight 和 CPU-oblivious，而软件保留了顺序约束策略。若 LAT 或 LWST 容量耗尽，Fanmem 会对该事务回退到同步持久化路径，因此最坏情况只是退化成基线，而不是卡死或丢失耐久性保证。

## 实验评估

论文的实验和主张基本是对齐的。作者在 gem5 上评估了两种解耦内存架构：低延迟的 `CXL-F` 与更高延迟的 `CXL-S`，工作负载来自 STAMP 和 TPC-C，比较对象包括 SpecPMT、Crafty、SPHT、DudeTM、PMNet 以及 no-log baseline。与此同时，作者还实现了一个 FPGA 原型来估算交换机侧硬件开销。

最重要的结果直接支撑了论文主张。相对 SpecPMT，Fanmem 在 `CXL-F` 上平均提升 `1.2x`，在 `CXL-S` 上平均提升 `1.7x`。后者更高，正好符合论文的直觉：远端路径越长，可被隐藏的持久化延迟就越多。分 workload 看，`ssca2` 最多可达 `3.1x`，因为它事务短、计算轻、日志持久化占比高；`labyrinth` 的收益则明显更小，因为长计算本身才是主导成本。这个差异反而让结果更可信，因为它说明 Fanmem 并不是“普遍魔法加速”，而是在论文宣称的瓶颈真正存在时才最有效。

扩展性与敏感性实验也有信息量。在 `CXL-S` 上扩到 32 线程时，Fanmem 还能继续上升，而其他方案更早进入平台期，论文把这主要归因于更低的 write amplification。增大 switch-to-memory latency 时，Fanmem 相对基线的收益会从大约 `1.1x` 提升到 `2.0x`；日志尺寸越大，它的优势也越明显。硬件成本方面，FPGA 原型使用了 `2,590` 个 flip-flop、`3,361` 个 LUT 和 `594KB` BRAM；论文给出的 ASIC 估算为 `1.4 mm²`、`479.2 mW`。

我认为这套评估对“远端日志持久化是许多解耦内存事务的主要瓶颈，而交换机提前确认能显著削掉这部分等待”这一狭义主张是有说服力的。但作为端到端系统论文，它的覆盖面仍然有限：默认设置是单线程，工作负载主要是经典事务基准而不是现代云应用，而且一旦应用自身计算远大于 persist latency，Fanmem 的优势就会明显缩小。即便如此，baseline 选择是合理的，实验也确实打到了它声称优化的那个点。

## 创新性与影响

相对 _Ye et al. (ASPLOS '23)_，Fanmem 的新意不在 speculative logging 本身，而在于去掉了 SpecPMT 仍然必须支付的最后一次同步远端等待。相对 _Seemakhupt et al. (ISCA '21)_，它并不是把 persistence domain 扩展到带持久介质的 NIC，而是让交换机承担 lightweight 的 durability tracking，同时仍把远端内存作为日志的持久宿主。相对 _Castro et al. (FAST '21)_ 或 _Cai et al. (ISCA '20)_ 这类 CPU-assisted 事务设计，这篇论文最重要的贡献是“把加速点放在哪”：不是处理器，而是 CXL fabric。

因此，这篇论文很可能会被做 CXL memory pooling、后 Optane 时代 persistent memory 机制以及想在不绑定单一 CPU 厂商前提下实现 crash consistency 的系统研究者引用。它主要贡献的是一个新机制和一个新的放置选择，而不是从头定义一套全新的事务模型。

## 局限性

Fanmem 依赖相当规整的日志结构。每个线程都需要一个顺序、append-only 的日志区域；如果事务系统想使用分散式日志记录或更动态的日志复用方式，cursor 机制就不再这么自然。论文认为它也能扩展到其他 logging protocol，但同时也明确承认：若要支持 undo logging，就必须在交换机里加入更多依赖跟踪逻辑，这会偏离它刻意追求的简单、轻量设计。

性能收益同样是有条件的。Fanmem 隐藏的是日志持久化延迟，而不是降低解耦内存访问本身的固有延迟，所以对大 working set 或长计算事务，它的帮助会明显变小。溢出回退策略虽然安全，却也说明了一个部署前提：如果 LAT 或 LWST 容量不够，系统就会退回基线同步路径，因此交换机元数据容量需要认真规划。最后，论文的实现以单进程为单位处理提交与恢复，更关注组件故障下的正确性，而没有深入讨论 admission control、复制、或与更高层分布式事务系统的协同。

## 相关工作

- _Ye et al. (ASPLOS '23)_ — SpecPMT 用 speculative logging 去掉了一次 fence，但在远端 durable 之前仍要同步等待；Fanmem 把这段剩余等待下沉到 CXL 交换机。
- _Seemakhupt et al. (ISCA '21)_ — PMNet 借助 NIC 附近的持久介质把 persistence 推进网络，而 Fanmem 仍以远端内存为最终耐久介质，只用交换机侧元数据跟踪进度。
- _Castro et al. (FAST '21)_ — SPHT 是依赖 CPU 协作的硬件辅助持久事务方案；Fanmem 则把加速点移到 fabric 中，从而避免处理器修改。
- _Cai et al. (ISCA '20)_ — HOOP 说明硬件确实能有效重叠持久化，但它依赖 CPU 侧架构支持，而不是 CPU-oblivious 的交换机方案。

## 我的笔记

<!-- empty; left for the human reader -->

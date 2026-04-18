---
title: "Self-Clocked Round-Robin Packet Scheduling"
oneline: "SCRR 用自时钟虚拟时间替换 DRR 的固定 quantum，在保持公平性的同时减少空转 CPU，并让短突发流更快发完。"
authors:
  - "Erfan Sharafzadeh"
  - "Raymond Matson"
  - "Jean Tourrilhes"
  - "Puneet Sharma"
  - "Soudeh Ghorbani"
affiliations:
  - "Johns Hopkins University"
  - "Hewlett Packard Labs"
  - "University of California Riverside"
  - "Meta"
conference: nsdi-2025
code_url: "https://github.com/jean2/scrr"
tags:
  - networking
  - scheduling
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SCRR 保留了 DRR 的 round-robin 队列遍历方式，但把固定 quantum 改成了自时钟的虚拟时间规则。落后于全局虚拟时钟的队列可以连续发送直到追平，刚重新活跃的 sparse flow 也能在安全范围内稍微“提前”一点。Linux 实测表明，这样既能保持公平共享，又能同时降低 CPU 浪费和短突发流的排队延迟。

## 问题背景

DRR 之所以被广泛部署，是因为传统 fair queuing 调度器如 SCFQ、STFQ 需要维护按虚拟时间排序的数据结构，活跃队列一多，代价就会上升。DRR 用固定 quantum 换来了常数级复杂度，但现代流量恰好把这个设计点变成了问题根源。quantum 设大了，才能覆盖大包或 TSO/LRO 生成的大 SKB，可短小且对时延敏感的突发就会被单个流的长发送片段挡住；quantum 设小了，调度器又会花大量访问次数去累积 deficit 才能发出一个大包，CPU 被白白消耗。

论文认为，相比 DRR 被提出的年代，今天的 Internet 让这组矛盾更加严重。数据包大小高度变化，很多应用产生的是短暂的 on-off 突发，而不是始终 backlogged 的长流。在这种流量下，即便给 DRR 加上 Sparse Flow Optimization，它通常也只会优先照顾突发的第一个包，后续包很快就会掉回普通的轮转周期里，可能要再等完整一轮调度。论文要解决的问题因此是：在不要求显式优先级和不需要人工调参的前提下，能否保留 DRR 的可扩展性，同时让调度行为更接近对 sparse flow 友好的 fair queuing。

## 核心洞察

论文的核心判断是：真正有问题的不是 round-robin，而是固定字节预算。SCRR 保留了按子队列轮转的骨架，但用虚拟时钟替代固定 quantum。每个子队列维护头包的虚拟时间，调度器维护当前轮次的全局虚拟时钟。如果一个队列落后于这个时钟，SCRR 就让它继续发送，直到追平；如果一个队列已经领先，则只发送一个包就切换到下一个队列。这样，调度器的“有效 quantum”就会随工作负载自动变化，而不是由管理员预先猜测。更重要的是，这套虚拟时间机制还能安全地调整新近活跃队列的时钟，使短小突发不再只能一轮发一个包，同时仍然维持公平性和 burstiness 的理论上界。

## 设计

SCRR 把数据包分类到按流或按类划分的 FIFO 子队列中。基础版本里，包的虚拟起始时间是 `max(前一个包的完成时间, 当前全局时钟)`，虚拟完成时间则是在此基础上加上包长并除以权重。Dequeue 时，SCRR 至少会从当前子队列发出一个包；如果下一个包的虚拟时间仍早于当前全局时钟，就继续留在这个队列里发送，否则切到下一个活跃队列。全局时钟只会在一轮 round-robin 结束时更新一次，更新值是本轮已发送包中最大的虚拟时间。论文证明了每轮时钟推进量被最大包长所界定，且 SCRR 的长期公平性指标与 DRR 相同。

完整版本又加入了四个实现层面的增强。No Packet Metadata 把虚拟时间计算推迟到 dequeue，减少 enqueue 时的元数据写入。Sparse Flow Optimization 维护一个专门给新活跃队列的优先列表。Initial Advance 把新活跃队列的初始虚拟时间设在上一轮时钟附近，使一个短突发常常能在第一次被调度时连续发出多个包。No Empty 则立刻移除空队列，只在该队列没有超额占用带宽时才给予优先插入。四者叠加后的目标很明确：在复杂度和资源开销上尽量接近 DRR，但在 sparse flow 的体验上尽量靠近 STFQ。

## 实验评估

作者把 SCRR 实现为 Linux `tc` qdisc，并在真实的 10 Gbps 与 25 Gbps 测试床上，对比 tail-drop、PI2、STFQ、DRR、DRR+SFO、AIFO 和 SP-PIFO。评测设计和论文论点是对齐的：用 TSO/LRO 制造大幅波动的包长，用最多 20k 个活跃流验证公平性，再用 request-response 与合成的 VBR 工作负载去打 sparse flow 和轻度 backlogged flow 交替出现的场景。

在 NIC offload 场景下，SCRR-basic 能自动跟随包长变化，因此不会陷入 DRR 的 quantum 两难。面对 2,048 个流时，它相对 STFQ 降低了 46% 的调度 CPU 开销，相对 1500 B quantum 的 DRR 降低了 23%。在公平性方面，SCRR 与其他 fair scheduler 处于同一水平，调度多达 20k 个活跃流时 Jain 指标仍高于 0.97。这说明它并不是靠牺牲公平共享来换取更低时延。

最有说服力的是延迟结果。在 request-response 工作负载中，SCRR 的平均延迟优于所有对手，同时 CPU 开销还低于各个 DRR 变体；按不同 reply size 取平均后，它相对 tail-drop、DRR+SFO-1500 和 STFQ 的延迟改进分别达到 87x、1.5x 和 1.18x。在 VBR streaming 实验里，SCRR 的 frame latency 相对这三者又分别降低了 15x、1.4x 和 1.08x。附录还解释了为什么近期的 PIFO 近似实现并不是直接替代方案：AIFO 会导致队列利用不足，而 SP-PIFO 会造成足以触发 TCP 重传的数据包重排。

## 创新性与影响

相对 DRR，SCRR 去掉了需要人工配置的 quantum，换成由工作负载自己驱动的自时钟规则。相对 SCFQ 和 STFQ，它不再维护全局排序结构，而保留了简单的 round-robin 队列遍历。相对 Linux 里已有的带 SFO 的 fq/DRR 风格调度器，它不只是在空闲后优先发第一个包，而是显式改善短小多包突发的连续推进能力。所以这篇论文更像一篇真正的机制论文，而不是单纯的测量工作：它为 software switch、middlebox、host stack，甚至未来的硬件调度器，提供了一个比 DRR 更少调参负担的公平调度方向。

## 局限性

论文最强的证据仍来自单线程 Linux 软件调度器以及 10 Gbps、25 Gbps 测试床，而不是生产部署或真实硬件流水线替换。作者虽然强调 SCRR 对硬件友好，但并没有给出 ASIC 或 NIC 级别的实现结果。大多数实验也只评估了等权重的 flow scheduling，因此 weighted QoS 更多是由公式支持，而不是由系统实验充分验证。最后，SCRR 对 sparse flow 的优化本质上是有意识地让持续 backlogged 的流在时延上吃一点小亏，去换取短突发更好的体验，这个取舍在很多网络里是合理的，但依然带有工作负载依赖性。

## 相关工作

- _Shreedhar and Varghese (SIGCOMM '95)_ - DRR 是最直接的基线，SCRR 保留它的 round-robin 可扩展性，但移除了那个对包长分布和突发结构极其敏感的固定 quantum。
- _Golestani (INFOCOM '94)_ - SCFQ 引入了基于虚拟时间的 self-clocking 与排序式调度，而 SCRR 采用了相近的虚拟时间思想，却避免了全局逐包排序。
- _Goyal et al. (ToN '97)_ - STFQ 用虚拟起始时间改善 sparse flow 的时延表现，SCRR 可以看作是在更低实现开销下去逼近这类行为的 round-robin 版本。
- _Hoiland-Jorgensen (IEEE Communications Letters '18)_ - Sparse Flow Optimization 让 DRR/fq 更照顾新活跃流，而 SCRR 则把这种思想扩展到短小多包突发，使其在不打破公平性界限的前提下持续前进。

## 我的笔记

<!-- 留空；由人工补充 -->

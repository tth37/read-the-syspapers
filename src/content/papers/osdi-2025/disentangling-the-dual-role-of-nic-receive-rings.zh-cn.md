---
title: "Disentangling the Dual Role of NIC Receive Rings"
oneline: "rxBisect 把 NIC 的 Rx ring 拆成小型 allocation rings 和大型 reception rings，在保留 burst absorption 的同时缩小 DDIO working set。"
authors:
  - "Boris Pismenny"
  - "Adam Morrison"
  - "Dan Tsafrir"
affiliations:
  - "EPFL"
  - "NVIDIA"
  - "Tel Aviv University"
  - "Technion – Israel Institute of Technology"
conference: osdi-2025
tags:
  - networking
  - smartnic
  - memory
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文指出，传统 NIC receive ring 实际上同时承担了两件不同的工作：为 NIC 提供空 buffer，以及把装满数据的 buffer 交付给软件。rxBisect 把这两个职责拆成小型 allocation ring（Ax）和大型 bisected reception ring（Bx），因此系统既能保留 1 Ki 级别的 burst absorption，又不必让每个核心都把整圈 receive buffer 长期压进 DDIO 的 I/O working set。基于软件仿真的实验显示，这种接口重构相对私有 per-core ring 最多提升 37% 吞吐，在负载失衡时相对理想化 dynamic shRing 最多提升 20%。

## 问题背景

论文从一个缓存容量问题切入。现代 100 Gbps 及以上的 NIC 会把流量分散到多个 per-core receive ring 上，以便软件并行处理包。每个 ring 都会预先填满 MTU 大小的 buffer，默认常见配置是 1,024 个描述符。因此，接收侧的 I/O working set 至少是 `N x R x 1500 B`，其中 `N` 是 ring 数量，`R` 是每个 ring 的大小。在多核机器上，这个总 footprint 很容易超过 LLC，甚至超过 DDIO 能直接使用的那部分 LLC way。结果是，新到达的 DMA 包会把软件尚未处理的包从缓存里挤出去，使得后续访问退化为主存访问，内存带宽和延迟都变成瓶颈。

最直观的补救办法是减少每个核心持有的 receive-buffer 状态，但现有接口恰恰让这件事变得困难。缩小 private ring 的确能减小 working set，可它同时也削弱了单核吸收突发流量的能力，导致 burst 下更容易丢包。作者此前提出的 shRing 则尝试通过多核共享大 receive ring 来压缩 working set，但这引入了另一种耦合：同一个共享结构既决定谁拥有空 buffer，也决定谁还有接收空间。于是，shRing 在快路径上必须承担同步开销，而且在持续负载失衡时会失效，因为过载核心会占满共享 ring，使得本来还能处理流量的轻载核心也拿不到接收空间。论文使用真实的 CAIDA trace 证明，这种失衡并不罕见，最忙与最闲核心的输入负载比值在示例中持续位于 325% 到 433% 之间。

## 核心洞察

论文的核心主张是：现有 Rx 接口在抽象边界上就设计错了。一个 receive ring 看起来只是一个循环队列，但语义上它把两个彼此独立的 producer-consumer 关系揉在了一起：核心生产空 buffer 给 NIC 消费，NIC 再生产装有数据的 full buffer 给核心消费。这两个关系需要不同的容量配置，也需要不同的共享策略。如果把它们拆开，软件就可以跨核心共享空 buffer 池，而不必把“谁还有接收能力”也绑定到同一个共享队列上。

这个命题解释了为什么以往方案总像是在两个坏处之间取舍。要吸收 burst，确实需要一个大的 reception 结构，因为短时间内包到达速度可能快于软件处理速度；但给 NIC 供给空 buffer 并不需要每个核心都私有一个同样大的 receive ring。真正需要的是整个应用层面有足够多的空 buffer，并且软件能及时补充。rxBisect 正是利用了这种不对称性：保持 reception 大、allocation 小，并让 NIC 在硬件里完成跨核心空 buffer 调度，而不是让软件在共享 receive ring 上加锁同步。

## 设计

rxBisect 用两类 ring 取代传统的单一 Rx ring。allocation ring（Ax）保存空 packet buffer 的描述符，供 NIC 消费；bisected reception ring（Bx）则保存交给软件的通知，包括收到的 packet pointer，以及“某个 Ax ring 的某个 buffer 已被消费”的通知。一个 Bx ring 可以关联多个 Ax ring，而多个 Bx ring 也可以共享同一组候选 Ax ring，只要它们属于同一个软件实体并位于同一个 NUMA 节点。

当包到达时，NIC 先像今天一样决定目标 Bx ring，例如通过 RSS。随后它在关联的 Ax ring 集合中找到一个仍有空 buffer 的 ring，DMA 读出该 buffer 指针，把数据写进去，再把交付通知写到目标 Bx ring 里。如果这个 buffer 来自别的核心的 Ax ring，NIC 还需要通知那个分配核心去补回 Ax 条目。论文指出，在最常见的情形下，接收核心和分配核心其实是同一个核心，因此“收到包”和“消费了一个空 buffer”这两件事可以合并编码进同一个 Bx 描述符中。

软件侧逻辑保持得很简洁。每个核心轮询自己的 Bx ring，把真正收到的数据包收集出来进行处理；如果某个通知表明自己的 Ax buffer 被 NIC 用掉了，就立即重新分配一个新 buffer，并推进 Ax tail。设计唯一额外要求的是：buffer 可能在一个核心上分配、在另一个核心上释放，因此 allocator 必须高效支持跨核心 handoff。作者认为 DPDK 与 Linux 内核现有的“两级结构” allocator 已经满足这一点，即每核有本地 cache，上层再配一个共享池来摊销跨核转移成本。

真正关键的工程点在于，rxBisect 允许 allocation 与 reception 独立定尺寸。论文给 100 Gbps NIC 的建议是：Bx ring 维持 1 Ki 级别以吸收突发，而 Ax ring 则可缩小到 128 项左右，只要同时满足 `k x |Ax| x 1500 B` 不超过 DDIO 容量，以及 `k x |Ax| >= |Bx|` 以保证在软件补充前有足够 buffer。这就把“共享空 buffer 池”和“共享接收队列”拆开了。作者还论证，NIC 侧 critical path 与当前 Rx+completion-ring 机制并没有本质变长：仍然是读取 buffer 地址、写 packet 数据、再写 completion-style 元数据。变化主要在于，当本地 Ax ring 为空时，NIC 需要在硬件里从其他 Ax ring 中挑选 buffer，把 shRing 原本放在软件锁里的共享逻辑迁到了 NIC 流水线中。

## 实验评估

原型并不是真实 ASIC 实现，而是作者在 DPDK 上构建的一个软件 NIC 仿真框架，由专门的 emulator core 充当 NIC。实验平台是双路 Dell R640 服务器，配两对 100 Gbps ConnectX-5 NIC，并与 native privRing、small privRing、shRing 做比较。作者首先验证仿真是保守的：相对原生执行，仿真会让吞吐最多下降 12%，延迟最多升高 94%。因此，rxBisect 在仿真中取得的优势并不是因为测量环境偏向它。

在 200 Gbps、1500 字节包的 NAT 与 load balancing 网络功能上，rxBisect 能维持线速，而原生 privRing 会因为 I/O working set 过大、先后溢出 DDIO 区域与 LLC，导致吞吐最多下降 20%，平均延迟最高变成 11 倍。burst 吸收实验更直观地展示了设计收益：在单个 100 Gbps NIC、四个核心的 no-drop 测试中，rxBisect 用 256-entry 的 Ax ring 就能达到约 80 Gbps 的单流无丢包吞吐，而 privRing 需要 1 Ki 的 receive ring 才能达到同样的 burst tolerance。这里节省下来的，正是“共享空 buffer 而不共享 reception”带来的收益。

论文还用 MICA key-value store 证明这个思路不只适用于 NF。对 MICA，rxBisect 相比仿真的 privRing 最多提升 37% 吞吐，相比仿真的 shRing 最多提升 7%，甚至相对原生 privRing 和原生 shRing 也分别最高提升 18% 和 6%。而在负载失衡场景下，它与 shRing 的差距更明显：当某个目标核心的每包处理成本被人为拉高时，shRing 吞吐最多下降 60%；当目标核心接收更高比例流量时，shRing 最多下降 49%。rxBisect 基本保持线速，直到 emulator 自己成为瓶颈。对与 PageRank 共置运行的真实 CAIDA trace，rxBisect 相比论文中的理想化 dynamic shRing，在 LB 上提升 16%，在 NAT 上提升 20%。整体看，这组实验相当有力地支持了论文主张：rxBisect 同时解决了 LLC 压力问题，以及 shRing 在偏斜负载下共享队列被堵死的问题。

## 创新性与影响

相对于 _Pismenny et al. (OSDI '23)_，rxBisect 并不是在 shared receive ring 上再做一个更聪明的启发式，而是直接改变接口，让 buffer sharing 与 packet reception 不再绑定在同一个队列上。相对于 _Fried et al. (NSDI '24)_ 中 Junction 基于 Mellanox RMP 的共享方案，rxBisect 把共享逻辑下沉到 NIC，让所有核心都能继续做有效工作，而不需要额外的监控或辅助核心。相对于 _Sadok et al. (OSDI '23)_，后者优化的是 NIC-application 之间的 streaming communication 路径，而 rxBisect 攻击的是另一个层次的瓶颈，即 oversized receive-buffer working set 对缓存造成的压力。

因此，这篇论文的影响面会比“又一个更快的 packet-processing trick”更大。对于高吞吐 kernel-bypass runtime、端主机网络栈，以及未来 NIC receive interface 的设计者来说，它给出的启发是：真正的问题不是“receive ring 应该做多大”，而是“为什么一个队列要同时编码两种资源分配策略”。具体机制当然可以继续演进，但这个抽象层面的重新划分，是论文更有价值的贡献。

## 局限性

最主要的局限是，rxBisect 仍停留在软件仿真阶段，而不是硬件原型。作者对 emulator 保守性和 NIC critical path 不变给出了相当可信的论证，但他们并没有展示真实 ASIC、实际 firmware，或与现有量产 NIC 的完整集成。因此，任何关于部署可行性的判断，最终仍然依赖于论文的硬件论证是否令人信服，而不是来自端到端产品级实现。

这个设计也依赖软件栈配合。buffer 可能在一个核心上分配、在另一个核心上释放，因此 allocator 必须高效支持跨核心回收。论文给出的 DPDK 测量显示，这部分开销始终低于总周期的 0.2%，但这个结论毕竟建立在特定的 DPDK 风格环境之上。类似地，rxBisect 在严重失衡时仍可能消耗更多 buffer，因为过载核心的 Bx ring 可能被其他核心贡献的 buffer 填满；作者也明确指出，如果采用预分配 buffer pool，就必须把这种情况考虑进容量规划里。

最后，实验覆盖范围比抽象本身更窄。原型没有改动 transmit side，重点仍是 kernel-bypass 应用与 MICA，并且大多评估的是同节点、同 NUMA 条件下的 buffer sharing。论文没有研究通用 socket 栈、multi-tenant isolation，或除丢包与队列堵塞之外的更复杂失败模式。对于 OSDI 论文来说这很合理，但离真实部署仍有一些工程问题没有回答。

## 相关工作

- _Pismenny et al. (OSDI '23)_ — shRing 同样通过共享来缩小 receive working set，但它仍把 buffer ownership 与 reception capacity 绑定在一个共享 ring 上，这正是 rxBisect 试图拆开的耦合。
- _Fried et al. (NSDI '24)_ — Junction 借助 Mellanox RMP 共享 receive buffer，并通过 work stealing 与辅助核心缓解失衡；rxBisect 则让 NIC 直接完成跨核心 buffer sharing。
- _Sadok et al. (OSDI '23)_ — Enso 重构的是 NIC 与应用之间的 streaming 接口，以降低通信开销；rxBisect 关注的则是 oversized receive-buffer working set 对缓存造成的压力。
- _Farshin et al. (ATC '20)_ — Reexamining direct cache access 刻画了 DDIO 与 leaky DMA 在高速网络中的代价；rxBisect 进一步修改接收接口本身，以缩小造成这些代价的 working set。

## 我的笔记

<!-- 留空；由人工补充 -->

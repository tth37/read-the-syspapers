---
title: "Occamy: A Preemptive Buffer Management for On-chip Shared-memory Switches"
oneline: "Occamy 把共享缓冲从只会被动等待改成可抢占回收，用 head-drop 快速腾出过量占用的队列空间，让浅缓冲交换机更能扛突发。"
authors:
  - "Danfeng Shan"
  - "Yunguang Li"
  - "Jinchao Ma"
  - "Zhenxing Zhang"
  - "Zeyu Liang"
  - "Xinyu Wen"
  - "Hao Li"
  - "Wanchun Jiang"
  - "Nan Li"
  - "Fengyuan Ren"
affiliations:
  - "Xi'an Jiaotong University"
  - "Huawei"
  - "Central South University"
  - "Tsinghua University"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3717495"
code_url: "https://github.com/ants-xjtu/Occamy"
tags:
  - networking
  - datacenter
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Occamy 保留 DT 风格的 admission，但把共享缓冲管理重新做成可抢占式：它利用片上 metadata 通路里的冗余 bandwidth 做 head-drop，最多把 burst absorption 提高约 57%，把平均 QCT 降低约 55%。

## 问题背景

今天的数据中心交换机把 packet buffer 放到芯片上，是为了让 25.6 Tbps 到 51.2 Tbps 级别的交换容量还能在线速下访问缓冲；问题是，buffer 增长速度远远跟不上带宽。论文提到，按单位带宽折算，交换机缓冲在过去十年里大约缩小了 4 倍，而 incast、低时延解耦 RPC 和分布式训练都在把这点共享缓冲推向极限。

商品交换芯片最常见的方案是 Dynamic Threshold，也就是 DT。它按当前 free buffer 计算每个队列的阈值，优点是简单，但本质上是 non-preemptive：包一旦进了 buffer，就只能等它所在队列自己排空。这样既要预留空闲缓冲，又很难在流量快速变化时及时重分配空间；在作者的仿真里，DT 丢包时的 99 分位 buffer utilization 只有大约 66%。

实验里这种问题会直接变成性能异常。作者在 Huawei CE6865 上看到，低优先级背景流量能把高优先级 incast 的 QCT 拉长到最多 8 倍；把拥塞换到不同端口后，退化仍可达到 2 倍。论文把它概括成 buffer choking：慢速排空的队列还攥着超额缓冲，而新到的突发流量在拿到公平份额之前就先被丢掉。

## 核心洞察

Occamy 的核心判断是，现代 shared-memory 交换机其实重新具备了做 preemption 的条件，因为驱逐一个已缓存分组主要是 metadata 操作。在常见的 cell-based buffer 里，交换机只要删掉 packet descriptor，再把对应的 cell pointer 还回 free list；它不需要把 payload SRAM 重新读一遍。

于是设计重点就变了。Occamy 不再试图发明更复杂的 admission rule，而是尽量把 expulsion 做简单：admission 不等待 expulsion，expulsion 也不追全局最长队列，而是对所有 over-allocated 队列做 round-robin 的修剪。

## 设计

Occamy 在 admission 侧基本沿用 DT，只是把 `alpha` 调大，让系统只保留一小块 free buffer 给新活跃流量。这就是它的 proactive component：继续复用商品芯片已经有的 queue-length thresholding，但因为后面能快速回收 buffer，就不必留太多 headroom。

真正关键的是 egress 侧的 reactive component。任何队列只要长度超过当前阈值 `T(t)`，就会在 bitmap 中被标成 over-allocated。随后由 round-robin arbiter 从这些队列里选一个做 head-drop。这里是 Occamy 相比经典 Pushout 的核心简化：既不在 enqueue 时阻塞，也不实时维护最长队列。

被选中的队列会发起 head-drop request，与正常 dequeue 竞争 descriptor 和 cell-pointer 的访问。fixed-priority arbiter 永远优先满足 output scheduler，因此 preemption 只能吃掉原本空闲的带宽。executor 的动作也很直接：把队首包的 descriptor 出队，再把对应的 cell pointer 还回 free list。因为不碰 payload cell，这条路径可以直接拼进现有 dequeue pipeline。作者推荐的运行点是 `alpha = 8`。

## 实验评估

论文的可实现性结果相当扎实。作者把 selector、arbiter 和 executor 用 Verilog 实现后，报告的硬件开销只有大约 1,300 个 LUT、约 50 个 flip-flop、小于 0.03 mm^2 的 ASIC 面积，以及约 1 mW 功耗；时序结果还表明，在 1 GHz 下它可以每 2 个周期驱逐一个包。

性能结果也和机制对得上。Tofino 上的 P4 原型显示，在 `alpha = 4` 时，Occamy 比 DT 多吸收约 57% 的突发。DPDK 软件交换机上，Occamy 相比 DT 最多可把平均 QCT 降低约 55%，相比 ABM 也能降低约 42%，同时 background flow 的 FCT 基本持平；在 buffer choking 实验里，背景流量能把 DT 的平均 QCT 放大到最多 6.6 倍、p99 QCT 放大到最多 60 倍，而 Occamy 接近 Pushout。到了 128 主机 leaf-spine 仿真里，它在 web-search 负载下最多可把平均 QCT slowdown 相比 DT 降低约 44%；背景换成 all-to-all 和 all-reduce 后，query QCT 仍可分别改善最多 33% 和 48%。

## 创新性与影响

Occamy 的贡献不在于又给 DT 加一个补丁，而在于提出了一种适合现代 shared-memory 交换机的 preemptive 架构。对交换机设计者来说，它给出了带硬件成本的实现路径；对运营者来说，它说明了为什么只调 admission 参数，不可能彻底解决 shallow-buffer 场景下的 microburst 吸收和性能隔离问题。

## 局限性

最直接的限制是，论文并没有把完整 Occamy 放进量产 ASIC 的 traffic manager。Tofino 上的 P4 原型做不出完整 selector 和 fixed-priority arbiter，DPDK 原型也只是目标行为的模拟，所以现阶段仍是综合结果加外围原型，而不是商品交换芯片里的最终实现。

另一个限制是，Occamy 的收益依赖存在可供 preemption 使用的冗余 memory bandwidth。作者论证这种情况在实践里很常见，并在 90% 仿真负载下仍观察到大约 38% 的中位空闲 memory bandwidth，但只要逼近 full-bisection 的最坏情况，preemption 的优势自然会收缩。最后，`alpha = 8` 也是实验上推荐的经验值，而不是一种可直接迁移到所有部署的通用定律。

## 相关工作

- _Fan et al. (GLOBECOM '99)_ - Dynamic Threshold 是 Occamy 明确保留下来的 admission 基线，但 Occamy 用主动回收替换了 DT 只能被动等待的部分。
- _Shan et al. (INFOCOM '15)_ - EDT 仍在 non-preemptive 框架里增强 DT 的 burst absorption，而 Occamy 认为瓶颈恰恰在这个框架本身。
- _Addanki et al. (SIGCOMM '22)_ - ABM 通过考虑 drain time 来改善性能隔离，但它依旧依赖队列自然排空，因此无法从根上消除 buffer choking。
- _Wei et al. (GLOBECOM '91)_ - 经典 Pushout 证明了驱逐已缓存分组在理论上的优越性；Occamy 则把这个方向改写成现代交换芯片更容易实现的版本，不再追踪最长队列，也不在 enqueue 时阻塞。

## 我的笔记

<!-- 留空；由人工补充 -->

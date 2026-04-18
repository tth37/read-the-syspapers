---
title: "A Layered Formal Methods Approach to Answering Queue-related Queries"
oneline: "QUASI 先用有单侧正确性保证的抽象层剪掉不可能的队列场景，只在剩余难例上调用 SMT，从粗粒度端口计数回答队列查询。"
authors:
  - "Divya Raghunathan"
  - "Maria Apostolaki"
  - "Aarti Gupta"
affiliations:
  - "Princeton University"
conference: nsdi-2025
tags:
  - networking
  - formal-methods
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

QUASI 把队列查询改写成一个存在性问题：是否存在某条 packet trace，同时满足观测到的每端口输入、输出、丢包计数，并让目标队列性质成立。它先用一个可证明“不会漏掉真实否定答案”的过近似层快速排除不可能场景，再只把剩余难例交给 SMT 做精确求解。这样一来，系统仅靠 SNMP 风格的粗粒度计数，就能回答 queue length、burst 和 buffer occupancy 这类问题。

## 问题背景

运维人员在排障、容量规划和 SLO 检查时，经常需要知道某段时间里队列是否可能堆高、是否可能出现 microburst、是否可能触发显著排队时延。但生产网络里长期保留下来的往往只有每端口 packet counts。细粒度 queue telemetry 持续采集成本高、存储和分析开销大，很多时候还依赖专用硬件；更现实的问题是，当事故已经发生后，这些高精度数据通常根本不存在。论文因此把目标重新表述为一个更贴近运维的问题：并不一定要重建“真实的”队列时间序列，只要能证明某个坏场景是否可能发生，就已经很有价值。

难点在于，queue length 虽然和 packet counts 强相关，却并不能由这些计数直接推出。计数没有告诉你包的到达顺序、每个时刻哪个输入端口把包送到了哪个输出队列、以及这些事件与出队和丢包之间的精确交错关系。真正决定队列动态的是一条潜在的 packet trace，而满足同一组粗粒度计数的 trace 数量可能非常大。现有的 telemetry inference 系统可以生成“看起来合理”的细粒度信号，但它们缺少形式化保证，无法可靠地证明某种队列场景“不可能发生”。更通用的 formal performance analysis 工具也并不是围绕“给定观测计数约束下是否存在可行 trace”这个问题设计的，扩展性很快就会崩掉。

## 核心洞察

论文最重要的命题是：对它支持的查询语言而言，包来自哪个 input port 并不重要，真正重要的是每个时间步有多少包被送入了哪个 output queue，也就是 enqueue-rate。只要把问题提升到“每个队列、每个时间步的入队数量”这个层次，QUASI 就能同时代表大量具体 packet traces，而且对它关心的查询不会丢失精度。

第二个洞察是把这种抽象用成一个不对称的 layered reasoning 流程。QUASI 的第一层先做过近似，只负责快速排除不可能场景，并且它的负答案是可证明正确的；只有第一层得到正答案时，系统才需要进一步求精。换句话说，第一层“不会产生 false negative”，而整个两层系统在进入精确层后“不会产生 false positive”。这让 QUASI 能把 formal methods 里很经典的 abstraction-refinement 思想，真正落到一个以测量数据为输入的网络运维问题上。

## 设计

QUASI 的查询语言覆盖三类指标：瞬时入队率 `enq`、累计入队率 `cenq` 和队列长度 `qlen`，并支持对时间与队列做有界量化。第一层 `QUASI-1` 分成三个模块。第一步，cover-set generator 从查询本身以及 per-port output/drop counts 推导必要条件。对 queue-length 查询，它用 packet conservation 把“某个时刻队列至少达到 `K`”改写成对累计入队数的下界，同时结合初始队列长度、最少出队数和丢包数的上下界。输出不是枚举 traces，而是一组有限的约束分量，每个分量都代表一簇“可能同时满足查询和观测输出”的 abstract traces。

第二步，most-uniform abstract-trace constructor 会为每个约束分量构造一个代表性 abstract trace。这里“most-uniform”是关键定义：在满足所有上下界约束的前提下，算法总是把 packet 放进当前总高度最低的时间列里，于是得到那个“尽量不突发”的代表。如果连这样一个代表 trace 都无法被标号成满足输入计数的 concrete trace，那么同一分量里那些更不均匀的 traces 也都不可能成立。论文证明了这一点，因此第一层可以一次剪掉整块搜索空间，而不必显式枚举所有 traces。

第三步，matrix-based consistency checker 把“是否能为这些 packets 分配 input ports”转成一个纯组合问题。它先把每个时间步的总入队量聚合出来，再检查是否存在一个 `N x T` 的二元矩阵，使得行和等于每个输入端口的计数、列和等于代表 trace 在对应时间步的总高度。借助 Gale-Ryser theorem，QUASI 可以直接做存在性判断，而不是搜索所有 packet-to-input 的分配方式。

第二层 `QUASI-2` 是精确求解回退路径。它把交换机时序行为和查询一起编码成 SMT 约束，并交给 Z3 检查可满足性。这里的工程亮点在于：即使进入精确层，QUASI 仍然保留 enqueue-rate abstraction，因此变量规模是 `O(NqT)`，而不是完整 packet-trace 编码的 `O(NNqT)`。由于查询语言从不区分同一队列里 packet 的来源输入端口，论文认为这个抽象在其适用范围内是 lossless 的。

## 实验评估

评估使用 ns-3，在一个围绕 8-port switch 的 star topology 上收集 measurements；每个 output port 的最大 queue 容量是 250 packets，总 buffer 是 2000 packets，一共考察 25 个长度为 100 个 time steps 的 monitoring intervals。作者还额外做了一个更贴近运维场景的 SLO case study：8 Gbps 链路、1 KB packets、5 分钟监控窗口，对应 3 亿个 time steps。

最能体现论文价值的是 SLO 检查案例。为了验证排队时延是否可能违反 289 微秒目标，作者把问题转成“某个端口是否可能达到 290 个排队 packets”。结果是，QUASI 在所有 5 分钟窗口上都证明了这一坏事件不可能发生，总耗时只有 0.03 秒；相比之下，heuristic baseline 在所有窗口里都误报了潜在违约。这正好说明论文的核心主张：即使只有粗粒度 counters，系统仍然可以对“不曾发生某种队列事件”给出形式化保证。

对 burst 查询，第一层本身已经很强。在 25 个实际不存在目标 burst 的 intervals 上，`QUASI-1` 全部在 1 秒内给出否定答案，而 heuristic baseline 有 14 个 false positives。对定量问题，系统通过对布尔查询做 binary search 来求最大 queue length 和最大 buffer occupancy。`QUASI-1` 能在约 1 秒内给出上界，平均相对误差为 0.25，而且这些上界相比 heuristic 最多可再收紧 58%；随后 `QUASI-2` 会在 25 分钟内求出最大 queue length 的精确值，在 15 分钟内求出最大 buffer occupancy 的精确值。

与 FPerf 的比较也很有说服力，即便作者已经把 interval 缩短到 10 个 time steps，好让 FPerf 至少偶尔能跑完。论文的 headline 结果是 QUASI 在最大 queue length 上快了 `10^6` 倍量级：FPerf 平均要 8.5 小时，而 QUASI 不到 1 秒。FPerf 甚至不支持 burst 查询；在最大 buffer occupancy 上，它一天内都无法完成每个 interval 需要的全部求解，给出的上界还可能比精确答案大约 9 倍。

## 创新性与影响

这篇论文的新意并不只是“把 SMT 用到网络问题里”。更关键的是围绕 solver 搭起的一整套 reasoning pipeline：针对查询语义设计的 lossless enqueue-rate abstraction、把必要条件组织成 cover-set 的表示方式、证明 most-uniform representative 足以支撑否定性推理的理论结果，以及用矩阵存在性替代显式 label search 的组合化检查。它把原本只是粗糙监控信号的 packet counts，变成了一个可以承载形式化推理的分析基座。

我认为它最可能影响的是缺少 always-on 细粒度 queue instrumentation 的网络运维和 telemetry 系统。QUASI 当然不能替代直接测量，但它证明了：即使只有非常便宜、非常粗的 counters，仍然可以对“某种坏的排队场景是否可能发生”给出有意义的证明。这也把 networking 里的 formal methods，从传统的 control-plane correctness，向 measurement-constrained performance diagnosis 推进了一步。

## 局限性

QUASI 的保证严格依赖于它的模型和查询语言。系统核心只支持 single-switch queries，虽然论文提到某些 multi-switch path 问题可以通过分解成 per-switch 上界来近似处理，但这并不是直接的端到端建模。查询语言也只覆盖 `enq`、`cenq` 和 `qlen` 这三类指标；如果需要更丰富的 packet 语义、跨设备因果关系或更复杂的时序属性，当前抽象就不够用了。

可扩展性也明显依赖查询类型。Queue-length 类问题经常能在第一层就很快结束，但 burst 查询要差得多：论文给出的数字是 `BurstOccurrence` 在 60,000 个 time steps 上大约需要 75 分钟。除此之外，评估完全基于仿真，并集中在 randomized UDP traffic 和单交换机拓扑上。它足以展示方法成立与复杂度趋势，但还不足以证明 QUASI 在真实生产 traces、以及行为细节偏离论文交换机模型的硬件上同样稳健。

## 相关工作

- _Arashloo et al. (NSDI '23)_ - `FPerf` 用 workload synthesis 做 formal network performance analysis，而 `QUASI` 关注的是“在观测到的 per-port counts 约束下，是否存在满足查询的 trace”，并在精确求解前加入了一个有正确性保证的快速层。
- _Gong et al. (SIGCOMM '24)_ - `Zoom2Net` 试图从粗粒度测量补全细粒度 telemetry，而 `QUASI` 并不声称重建隐藏时序，只回答带形式化保证的 yes/no 与 bound 问题。
- _Geng et al. (NSDI '19)_ - `SIMON` 从测量推断 queueing delay，`QUASI` 则是在所有与计数一致的 traces 空间上推理，并能证明某些队列场景从未发生。
- _Lei et al. (SIGCOMM '22)_ - `PrintQueue` 通过数据平面直接测量 queue behavior，而 `QUASI` 的价值恰恰在于当这种细粒度 instrumentation 不存在、只剩 SNMP 风格 counters 时仍然能工作。

## 我的笔记

<!-- 留空；由人工补充 -->

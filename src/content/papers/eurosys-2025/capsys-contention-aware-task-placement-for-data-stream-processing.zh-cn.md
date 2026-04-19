---
title: "CAPSys: Contention-aware task placement for data stream processing"
oneline: "CAPSys先剖出每个算子的CPU、状态访问和网络代价，再在Flink里快速搜索更均衡的任务摆放，让放置决策真正进入自动扩缩容闭环。"
authors:
  - "Yuanli Wang"
  - "Lei Huang"
  - "Zikun Wang"
  - "Vasiliki Kalavri"
  - "Ibrahim Matta"
affiliations:
  - "Boston University"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3696085"
code_url: "https://github.com/CASP-Systems-BU/CAPSys"
tags:
  - scheduling
  - datacenter
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CAPSys的出发点很直接：流处理系统里的 task placement 不能再被当成扩缩容之后顺手一分的随机步骤。它先测出每个算子的 CPU、state access 和 network 成本，再用 CAPS 在很短时间内找出更均衡的放置方案，并把这个步骤接进 DS2 的重配置闭环。落到 Apache Flink 上，结果是吞吐更高、backpressure 更低，而且 auto-scaling 的收敛过程更稳。

## 问题背景

像 Apache Flink、Storm 这类 slot-oriented SPS，会在部署或重配置时生成静态 task placement，但内置策略基本默认 task 同质。真实查询却同时混着轻量 map、吃 state backend 的 window 或 join，以及吃 CPU 的 inference 算子，所以系统如果只是按空槽位去填，或者按任务数均摊，而不管任务到底在抢什么资源，同一条查询在同一套集群上也可能跑出完全不同的性能。论文用 `Q1-sliding` 把影响量化得很清楚：在 4 个 worker、16 个 slot 上，`80` 种 placement 里最好的方案能做到 `14k` records/s、`6.8%` backpressure，最差的只有 `9k` records/s 和 `86.4%` backpressure。更糟的是，坏 placement 还会把 DS2 这类 auto-scaler 的容量估计带偏，导致 over-provision 或反复重配置。现有办法要么像 R-Storm、Flink 的 fine-grained hints 一样依赖人工标注，要么像 ODRP 一样太慢，不适合放进在线闭环。

## 核心洞察

这篇论文最值得记住的一点是：在线 placement 不必先做一个精确的端到端性能预测，先衡量瓶颈 worker 的资源失衡就够了。CAPSys把 plan 质量压成 compute、state access、network 三维失衡度。这个抽象不是拍脑袋来的。`Q2-join` 如果把太多 tumbling-window join task 摞在一起，吞吐会从大约 `110k` 降到 `91k` records/s，backpressure 从最高 `4%` 升到 `32%`；`Q3-inf` 在 `1 Gbps` 出口限速下，高争用 placement 会把吞吐从 `1555` 拉到 `1185` records/s，backpressure 从 `12%` 拉到 `37%`。所以真正该避免的，是同类重负载叠在同一台机器上；只要搜索能尽快排除这类方案，就没必要先把整条查询完整模拟一遍。

## 设计

CAPSys 在 Apache Flink 和 DS2 外围加了一层 placement controller。系统先用 profiling job 将每个算子单独放到 Task Manager 上，测每条记录对应的 CPU utilization、RocksDB 读写字节数和输出字节数。DS2 决定 parallelism 后生成 physical execution graph，placement controller 再按目标速率换算每个 task 的资源代价，调用 CAPS 搜索，并通过扩展过的 `ResourceProfile` 与自定义 `SlotMatchingStrategy` 把结果交给 Flink scheduler。CAPS 对 physical graph `Gp` 和 homogeneous worker cluster `Gw` 建模，给每个 plan 计算 `C = [Ccpu, Cio, Cnet]`，每一维都是最忙 worker 相对理想均衡状态的归一化失衡度。搜索用 DFS：outer search 按 operator 展开，inner search 尝试 worker，并做 duplicate elimination。核心优化是阈值剪枝 `alpha = [alpha_cpu, alpha_io, alpha_net]`。由于 partial plan 的资源负载只会上升不会下降，任何已经越过阈值的分支都能立刻剪掉；再配合把 resource-heavy operator 提前放到高层，坏方案会更早暴露。CAPS 还能自动放松阈值寻找可行解，并把搜索并行到多线程。论文也明确承认其前提：worker 需 homogeneous，总 slot 足够，同一算子的 task 视作等价；data skew、slot sharing 和 WAN-aware placement 不在核心模型里。

## 实验评估

端到端结果和机制解释是一致的。单查询实验在 4 台 `m5d.2xlarge`、每台 8 个 slot 上比较 6 条 workload，CAPSys 在吞吐、backpressure、latency 上都优于 Flink `default` 和 `evenly`，平均把 backpressure 降 `84%`、平均 latency 降 `48%`；`Q5-aggregate` 上对 `default` 最多有 `6x` 吞吐，对 `evenly` 最多 `5.5x`。多租户实验放到 18 个 worker、144 个 slot 上同时跑 6 条查询时，只有 CAPSys 能全部达到目标吞吐。和 ODRP 比，`Q3-inf` 上 CAPSys 用 `27` 个 slot 跑到 `4236` records/s、`0.5%` backpressure，算 plan 只要 `0.2 s`；ODRP 要 `1607-4037 s`，而且不是明显 under-provision 就是要 `32` 个 slot 才接近目标。可变负载实验里，CAPSys 让 DS2 在 4 次受控 scaling step 里都命中目标且不 over-provision，在更长的收敛实验中最多能少掉 8 次额外重配置。scalability 方面，最多 `256` 个 task 时，CAPS 都能在 `100 ms` 内找到满足阈值的方案；离线 auto-tuning 在 `64` 个 task 时要 `1.16 s`，到 `1024` 个 task 时为 `125.08 s`。

## 创新性与影响

CAPSys 的新意不在于再次宣称 placement 重要，而在于把 placement 和 auto-scaling 合并成一个可运行的控制问题，并用足够轻的 contention 模型把它塞进闭环。贡献落在整套组合上：profiling、失衡代价、pruning、operator reordering 和 scheduler integration 一起工作，才让 Flink 里的在线 placement 变得现实。对流处理研究者，这是对随机或按任务数均分策略的有力反驳；对控制平面实现者，这是一个可直接借鉴的改造路径。

## 局限性

CAPSys 假设 homogeneous worker，并把同一算子的 task 当成等价对象，因此明显的 data skew 仍需靠外部 partitioning 先处理。它的 cost profile 又是在隔离条件下测得并缓存的，这对性能友好，但工作负载或干扰模式一变，画像就可能过期；online reprofiling 只停留在未来工作。更整体地看，论文的实验仍集中在 Apache Flink `1.16.2`、6 条查询和相对 homogeneous 的云集群，所以它证明的是这类场景中的实用性，而不是对异构或跨机房 stream processor 的普适性。

## 相关工作

- _Cardellini et al. (DEBS '16)_ - 把 distributed stream processing 的 operator placement 写成优化问题；CAPSys 则主动缩小目标，只保留在线重配置真正需要的 contention balance。
- _Cardellini et al. (SIGMETRICS Perform. Eval. Rev. '17)_ - ODRP 联合优化 replication 和 placement，追求精确解；CAPSys 接受近似最优，用 pruning 换取控制环里可接受的决策时延。
- _Peng et al. (Middleware '15)_ - R-Storm 让 Storm 支持 resource-aware scheduling，但前提是用户得先给出资源需求；CAPSys 改成系统自己 profiling 再自动搜索。
- _Jonathan et al. (Middleware '20)_ - WASP 关注 wide-area adaptive stream processing，重点是跨地域网络时延与异构性；CAPSys 讨论的则是 datacenter 内部 compute、state 和 network contention 的均衡。

## 我的笔记

<!-- 留空；由人工补充 -->

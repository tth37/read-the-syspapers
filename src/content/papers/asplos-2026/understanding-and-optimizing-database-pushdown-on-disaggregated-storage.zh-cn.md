---
title: "Understanding and Optimizing Database Pushdown on Disaggregated Storage"
oneline: "TapDB 把 pushdown 决策推迟到运行时，用表感知代价估计、准入控制、DRAM/SSD 混合表和关键路径调度重新适配现代解耦存储。"
authors:
  - "Hua Zhang"
  - "Xiao Li"
  - "Yuebin Bai"
  - "Ming Liu"
affiliations:
  - "University of Wisconsin-Madison, Madison, WI, USA"
  - "Beihang University, Beijing, China"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790243"
code_url: "https://github.com/netlab-wisconsin/TapDB"
tags:
  - databases
  - disaggregation
  - storage
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

TapDB 的核心判断是：在现代解耦存储上，数据库 pushdown 已经不再主要是“省网络”的问题，而是“存储节点算力太稀缺”的问题。它把 pushdown 决策推迟到运行时，并配上表感知代价学习、并发准入控制、DRAM/SSD 混合临时表和关键路径驱动调度。对于新一代存储节点上的 SSB 与 TPC-H，这套组合相比已有 pushdown 设计带来 `1.3x-2.3x` 提升。

## 问题背景

这篇论文抓住了一个很容易被忽略但非常致命的硬件变化。作者统计自己集群中四代存储节点后发现：每核网络密度从 `1 Gbps/core` 增长到 `12.5 Gbps/core`，每核 I/O 密度从 `37.5K` 增长到 `500K IOPS/core`，但 CPU 与内存子系统的每核能力并没有同步提升。旧时代的 pushdown 成立，是因为把算子下推到存储侧，能用便宜的近数据计算换掉昂贵的网络和 I/O。到了新一代架构，这个交换关系反过来了，下推算子往往只是把本来就弱的存储侧 CPU 压垮。

作者用实验证明，这不是局部现象，而是会系统性地击穿现有方案。启发式 pushdown 和 cost-driven pushdown 在 Gen1/Gen2 存储节点上依然有效，但到了 Gen3/Gen4 就变成负收益：前者平均拖慢约 `40-55%`，后者平均拖慢约 `36-45%`。原因并不神秘。对新节点来说，query runtime 的主导项已经从 Network/Storage 变成 Compute，很多查询里计算时间占到总时间的四分之三左右，因此“少传点数据”不再自动等于“更快”。

进一步看，作者把问题拆成三个根因。第一，已有代价模型基本不关心表结构，因此一旦行列组织、数据类型、数据倾斜、宽表上的算术操作改变了真实计算代价，pushdown 决策就会错。第二，新一代存储节点的 interference-free window 明显缩小：CPU 安全区间大致从旧节点的 `[0, 68%]`、`[0, 65%]` 缩到新节点的 `[0, 33%]`、`[0, 28%]`，内存容忍区间也类似收缩。第三，当查询变成 compute-bound 以后，存储侧 operator scheduler 的好坏会直接影响性能，但以往 pushdown 系统几乎把它当成次要实现细节。

## 核心洞察

论文最重要的命题是：pushdown 不应该再是一个提前做完、主要依赖静态策略的规划期决策，而应该变成一个延迟到运行时、可被实时验证的执行期决策。只有等上游算子吐出部分结果之后，系统才能看到真实表结构、估计当前这台存储节点上的真实执行代价，并根据当下负载决定该不该继续下推。

但仅仅“晚一点再决定”还不够。TapDB 的真正洞察在于，它把运行时代价估计、并发准入控制、临时表内存管理和算子调度看成同一个问题的不同侧面。作者想记住的一句话可以概括为：在现代解耦存储里，系统应该持续地用充裕的网络和 I/O 带宽去换取稀缺的存储侧计算资源，而不是默认这种交换天然总是划算。

## 设计

TapDB 一共提出四个机制。第一个是表感知的学习型代价估计器。它不再依赖离线得到的固定算子速率，而是在上游生成部分输入后，用 equidistant sampling 抽出代表性样本，依据上游消息先做 eager input estimation，再把这些观测喂给一个在线线性回归模型。对于倾斜表，TapDB 还会插入一个 Pre-Scan Balancing Operator，把数据切成更细粒度的 segment 后重分布，让采样代价更接近全表真实代价。这个机制的重点不在“机器学习”本身，而在于让 pushdown 决策真正看到操作对象的表结构。

第二个机制是 admission control。即便一个算子的理想代价估计正确，只要当前存储节点已经接近干扰阈值，它依然不该被下推。TapDB 因此引入自适应参数 `A` 去缩放预测代价，并用历史预测误差与真实执行时间之间的差距在线更新 `A`。当节点拥塞变重时，`A` 会变大，pushdown 看起来就更“贵”，于是更多算子会被留在 compute node 上执行。这个控制环并不复杂，但它精准地对准了第二个根因：现代存储节点可容忍的波动空间太小。

第三个机制是 `HBTable`，也就是 DRAM-SSD 混合临时表。每张表都有 manifest，以及用循环缓冲区组织的 DRAM 区域和 SSD 区域。append 时优先写内存，不够了再 spill 到 SSD。更关键的是，TapDB 允许高优先级表通过 ballooning 风格的 lend/redistribute 机制向低优先级表借内存，这样关键算子就不会仅仅因为别的临时表占住 DRAM 而被卡住。作者的思路很明确：既然网络和 SSD 带宽更富余，那就用更多 I/O 去换内存与 CPU 的稳定性。

第四个机制是关键路径驱动的算子调度器。论文把查询执行形式化为 operator DAG 上的 NP-hard 调度问题，然后使用一个可实现的优先级策略：critical path 上的算子优先级最高，能解锁 critical path 的 urgent bypass path 次之，其他 bypass path 最后。如果高优先级算子已经 ready，但资源被低优先级工作占着，TapDB 就让低优先级算子让出 CPU 和内存。和 `FCFS`、`RR`、`SJF`，甚至单纯的多资源打包相比，这个调度器更清楚 query 结构里“谁先完成最值钱”。

## 实验评估

原型实现建立在 FPDB 之上，关闭 caching，加入 River 在线学习库与基于 CAF 的执行引擎，部署在一台 x86 compute server 加四代解耦存储节点上。工作负载是 SSB 与 TPC-H，scale factor 为 `1`、`30`、`100`、`200`，底层数据格式是按 `50 MB` 分区的 Parquet。这个实验设置和论文主张是对齐的，因为它同时覆盖了多种算子与作者强调的硬件代际变化。

在 Gen3/Gen4 存储节点上，相比 cost-driven baseline，TapDB 对 SSB 的提升分别是 `2.3x/1.3x/1.4x/1.3x` 和 `1.9x/1.7x/1.3x/1.5x`，对应 scale factor `1/30/100/200`；对 TPC-H 的提升分别是 `1.7x/1.7x/1.7x/1.6x` 与 `1.7x/1.8x/2.1x/1.8x`。相对 non-pushdown，它在新节点上仍有 `1.1x-6.9x` 收益，但在老节点上只有约 `6.5%-8.1%`。这其实增强了论文论点：TapDB 不是“任何机器都更快”的万能方案，而是专门为新型解耦存储硬件重构 pushdown。

分机制实验也比较扎实。表感知估计器让 SSB runtime 分别下降 `22.7%` 与 `36.3%`，让 TPC-H 分别下降 `42.1%` 与 `45.4%`，而平均相对误差大约是 `0.16`。Admission control 还能继续带来大约 `13-15%` 的平均收益；`HBTable` 根据 workload 与代际不同，再贡献约 `9-17%` 的改善；调度器则比作者在前文表征里表现最好的 `WFS` 与 `Tetris` 高出约 `9-13%`。我认为这些结果相对有说服力，因为每个机制都被拿来对应证明它解决了自己声称解决的那个瓶颈，而不是只在最终总成绩里“打包展示”。

## 创新性与影响

和 _Depoutovitch et al. (SIGMOD '20)_ 的 Taurus 相比，TapDB 的新意不只是“做更多 pushdown”，而是指出在存储侧算力稀缺之后，旧的启发式假设已经不成立。和 _Yang et al. (VLDB J. '24)_ 相比，TapDB 也不满足于在已有 cost model 上加一个 adaptive rejection，而是把表感知运行时代价、并发控制、内存扩展和 DAG 感知调度一起纳入系统设计。和 _Yang et al. (PVLDB '21)_ 相比，它也明显弱化了 caching 视角，而把重点放在执行期 pushdown 质量本身。

因此，这篇论文最可能影响两类人。一类是做解耦存储、云上 OLAP 引擎和 near-data analytics 的研究者，因为它把 pushdown 重新定义成运行时资源管理问题。另一类是构建 computational storage 或存储侧分析加速系统的工程团队，因为它提供了在“下推不再天然便宜”之后的一组可操作补救机制。

## 局限性

TapDB 依赖离线冷启动和在线再训练，因此可移植性并不免费。换一套硬件、存储栈或算子实现，可能都需要重新生成 synthetic query 数据并重新调模型。论文里对 urgent bypass path 的判定还依赖算子执行语义的先验知识，所以这个调度器也不是完全通用的黑盒机制。

实验最有力的部分集中在作者自己的 FPDB 原型和 OLAP benchmark 上。论文没有展示在更复杂的生产数据库优化器、多租户环境、或非 Parquet 数据格式下，收益是否还能稳定复现。它还明确地用更多网络流量和 SSD I/O 去换更低的 CPU 与 DRAM 压力，因此如果目标环境本身是带宽稀缺而不是算力稀缺，TapDB 的优势可能会缩小，甚至不成立。最后，若数据几乎不倾斜、负载也很轻，TapDB 某些机制带来的额外复杂度与开销未必总是值得。

## 相关工作

- _Depoutovitch et al. (SIGMOD '20)_ — Taurus 把 pushdown 主要视为一种启发式的近存储优化，而 TapDB 认为现代存储硬件已经要求系统在运行时重新验证并调度这些下推算子。
- _Yang et al. (PVLDB '21)_ — FlexPushdownDB 将 pushdown 与 caching 结合到云数据库里，但它仍然默认核心问题是“节省的数据传输值不值得这次下推”。
- _Yang et al. (VLDB J. '24)_ — FlexpushdownDB 的 adaptive pushdown 已经开始处理存储侧过载；TapDB 延续这个方向，但进一步加入表感知代价估计和更广泛的执行控制。
- _Jo et al. (VLDB '16)_ — YourSQL 关注把计算直接推入存储设备内部，而 TapDB 的目标是通用型解耦存储节点上的算子调度与争用管理。

## 我的笔记

<!-- 留空；由人工补充 -->

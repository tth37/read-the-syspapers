---
title: "Moirai: Optimizing Placement of Data and Compute in Hybrid Clouds"
oneline: "Moirai 在 hybrid cloud 中联合优化表复制与作业路由，把每周成本相对既有方案压低最多 98%，同时把跨站流量维持在带宽预算内。"
authors:
  - "Ziyue Qiu"
  - "Hojin Park"
  - "Jing Zhao"
  - "Yukai Wang"
  - "Arnav Balyan"
  - "Gurmeet Singh"
  - "Yangjun Zhang"
  - "Suqiang (Jack) Song"
  - "Gregory R. Ganger"
  - "George Amvrosiadis"
affiliations:
  - "Carnegie Mellon University"
  - "Uber"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764802"
project_url: "https://www.pdl.cmu.edu/Moirai/index.shtml"
tags:
  - datacenter
  - scheduling
  - storage
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Moirai 把 hybrid cloud 的放置问题表述成“表放哪、作业跑哪”的联合优化，而不是把数据复制和作业调度拆成两个彼此脱节的问题。它从生产访问日志构建 job-table dependency graph，用同时包含云存储、云 egress 和跨轮次重放置成本的模型求解，并对新出现的作业使用轻量级历史访问预测做在线路由。在 Uber 四个月的 Presto 与 Spark 轨迹上，它相对 Yugong 把每周部署成本压低 97% 以上，同时把跨站流量控制在目标上限之内。

## 问题背景

Hybrid cloud 之所以难做，并不是“云贵”这么简单，而是数据分析工作负载会把每一次错误的放置决策都放大成真金白银的代价。作业可能在一侧运行、表却在另一侧，于是每次远程读写都会变成 cloud egress、专线带宽压力，或者额外的复制存储成本。论文指出，已有方案基本落在两个糟糕极端：完全不复制、随机分区，存储最省但远程访问费用爆炸；或者大规模复制，把远程流量压下去，却把存储成本推高。

更麻烦的是，现代 data lake 的依赖关系并不沿着人类组织边界展开。Uber 的四个月轨迹包含 66.7M 个 Presto query 和 Spark job，访问了 300 PB 语料中的 13.3 EB 数据，而且依赖图高度缠绕：85% 的 job 与 77% 的 table 都落在最大的弱连通分量里。只有 10% 的读流量留在 project 内部，因此 Yugong 依赖的 project-level 分组在这里过于粗糙。与此同时，工作负载又不是高度重复的；按流量算，只有 56% 来自 recurring jobs，这意味着即使把历史上常见作业放置得很好，仍有很大一部分新作业需要在线决策。

## 核心洞察

论文最重要的判断是：要真正降低 hybrid cloud 成本，就必须在“实际 job-table 依赖”这个粒度上同时优化数据与计算的位置；但要让这个问题可解，又必须利用工作负载结构主动缩小搜索空间。换句话说，正确的抽象不是“项目”或“集群”，而是连接作业与其读写表的二分图。

之所以可行，是因为优化收益主要集中在少量可提炼的结构上。重复出现的作业可以按 query template 折叠，近期完全未访问的表可以在不损失准确性的前提下做聚合，而一小批“体积不大但被很多作业共享”的表可以预先复制，从而一次性打断大量依赖边。至于剩下的不确定性，尤其是新作业，基于近期每张表访问量做近似路由，已经足够逼近 oracle。

## 设计

Moirai 由三个主要组件组成。`Spinner` 消费访问日志并构建加权二分图：job 节点带 compute demand，table 节点带 size，边带 read/write bytes。`Allotter` 在这张图上求解 mixed-integer program。二进制变量分别决定每个 job 在 on-prem 还是 cloud 执行，以及每个 table 是否位于 on-prem、cloud 或两边同时存在。目标函数同时考虑云端存储成本、作业远程读写产生的 egress 成本，以及不同优化轮次之间重新搬运数据的成本；约束则覆盖 on-prem 与 cloud 的计算容量、on-prem 存储容量和跨站网络流量，但 cloud compute reservation 与 dedicated link 被当作预付约束，而不是优化变量。

让这个求解过程能落地的关键是两层降维。第一层是图压缩：重复出现且 canonical template 相同的作业被合并，上一时间窗没有被访问过的表按数据库名分组。对 Uber 的 weekly window，这一步把图从超过 4M 个 job 和超过 1M 个 table 缩到 356K 个 job 与 134K 个 table。第二层是预复制：Moirai 在正式求解前先选出极少量表强制复制。论文比较了多种启发式后发现，`Job Access Density` 最有效，因为它偏好“体积小但连接多”的表；只复制总数据量的 0.2%，就能把平均优化时间从 147 小时压到约 2 小时。

在线路由负责处理优化器无法预先决定位置的那部分作业。Recurring jobs 直接遵循优化结果；newly seen jobs 则由 `Size Predict` 处理。它查看作业会访问哪些表，用上一时间窗中每张表的平均访问量预测本次读取规模，再把作业送到预测本地数据量更大的那一侧执行。这个设计默认作业足够无状态，可以在任一侧运行；也默认 table 是原子搬运单元，即便某个作业实际上只访问其中一部分数据。

## 实验评估

评估基于 Uber 四个月的 Presto 与 Spark 生产轨迹。作者将 Moirai 与随机分区不复制、Volley 风格的数据放置、按时间新近性复制、按访问热度复制，以及自行重实现的 Yugong 做比较。他们假设 hybrid deployment 使用一条 800 Gbps 的专线，并把每周目标流量设成 11.5 PB，也就是峰值的五分之一，以给突发流量留余量。

核心结果不是“比 Yugong 略好”，而是近一个数量级的差距。在最难的 50% on-prem / 50% cloud 划分下，Moirai 把每周成本从 Yugong 的 `$393K` 降到 `$12K`，把每周流量从 `18.2 PB` 压到 `751 TB`。在三个资源划分场景里，它相对 Yugong 都能做到 97-98% 的成本下降和 96-98% 的流量下降。即便和最强的重复制启发式 `RepTop2.5%` 相比，Moirai 依然便宜约 94-95%，因为它不仅决定“复制哪些表”，还联合决定“不复制的那些表放哪”和“依赖它们的 job 跑哪”。

这些收益来自哪里，论文也做了拆解。中间变体 `Moi-JobDist` 保留了 Moirai 的 job 分布和首轮复制计划，但把剩余 table 的放置退回到类似 Volley 的逐表策略；即便如此，它也已经优于所有非 Moirai 基线，说明主要收益确实来自 job 与 data 的联合放置。至于预复制比例，0.2% 是最佳工作点：0.1% 留下了过多 egress，0.4% 则增加了存储成本却几乎没有额外回报。

面对新作业，`Size Predict` 相对“按当前闲置程度路由”的策略，可把 egress 成本再降 90.3-99.8%，而且整体上通常只比不可实现的 `Size Oracular` 下界高不到 2 倍。在渐进式迁移实验里，Moirai 的“重分布成本感知”目标几乎把额外 egress 压到零；相反，不考虑搬迁代价的优化器在最终退役 on-prem 存储时，会引入约 150 PB 的多余 egress 和约 450 PB 的 ingress。

## 创新性与影响

Moirai 的新意不只是“又一个优化器”，而是把 hybrid cloud 的经济模型、job-table 细粒度建模，以及能让问题规模落地的两三步关键削减，组合成了一个在真实生产轨迹上可运行的系统。Yugong 已经说明联合放置 job 和 data 很重要，但它依赖 project boundary，也服务于 private cloud 场景。Moirai 则把问题改写为更符合 hybrid cloud 的形式，把 cloud egress、存储弹性和跨轮次搬迁抖动都放进了目标函数。

它的影响对象会是建设 hybrid data lake、设计迁移工具链，以及试图让 scheduler 理解 data gravity 的团队。论文本身既是系统论文，也是 workload 论文：作者先给出首个大规模 hybrid-cloud analytics 轨迹分析，再用这些观测结果为系统设计背书，因此贡献并不只是“求解器跑得更好”。

## 局限性

最明显的局限是评估仍然以 trace-driven 模拟为主，而不是完整的生产闭环部署。第 6 节确实描述了 HiCam、HiveSync 和 control-plane routing hook 等落地组件，但没有展示优化器在真实 hybrid cloud 中端到端长期在线运行的结果，因此论文中的收益仍取决于轨迹回放与成本模型的保真度。

此外，它的建模假设也比较收敛。Moirai 把 cloud compute 与 dedicated link 当作预付资源约束，而不是被优化的决策变量；假设 job 可以在任一侧执行；把 table 当作原子迁移单元，而不是更细的 partition 粒度。当前设计只覆盖单个 cloud region 加一个 on-prem 站点，复制服务提供的是 eventual consistency，目标函数优化的是吞吐而非 per-job deadline。即便使用 0.2% 预复制这一关键技巧，求解时间仍然是“按小时计”，所以它更像周期性控制环，而不是反应式调度器。最后，按流量算仍有 44% 来自 newly seen jobs，因此系统对启发式在线路由依然有明显依赖。

## 相关工作

- _Huang et al. (VLDB '19)_ - Yugong 同样联合优化 job 与 data，但它依赖 private cloud 中的 project-level 放置；Moirai 用 table-level 依赖和 hybrid-cloud 成本模型取代了这种行政边界。
- _Agarwal et al. (NSDI '10)_ - Volley 假设 compute placement 固定，只把数据放到访问来源更多的一侧；Moirai 还会路由 job，并通过选择性复制重塑依赖图。
- _Choudhury et al. (OSDI '24)_ - MAST 联合放置跨数据中心的训练 job 与数据，但目标是 ML training、GPU 利用率和抢占，而不是 hybrid cloud 中的 analytics workload。
- _Park et al. (SOSP '24)_ - Macaron 用缓存降低跨云或跨 region 成本，而 Moirai 解决的是更长时间尺度上的放置问题：哪些数据该复制、作业该在哪里执行。

## 我的笔记

<!-- 留空；由人工补充 -->

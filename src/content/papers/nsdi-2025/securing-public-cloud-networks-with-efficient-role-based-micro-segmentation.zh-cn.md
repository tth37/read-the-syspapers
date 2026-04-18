---
title: "Securing Public Cloud Networks with Efficient Role-based Micro-Segmentation"
oneline: "ZTS 从 cloud flow telemetry 推断端点角色并自动生成微分段策略，同时把持续监控的额外成本压到约 0.5% 的 VM 成本。"
authors:
  - "Sathiya Kumaran Mani"
  - "Kevin Hsieh"
  - "Santiago Segarra"
  - "Ranveer Chandra"
  - "Yajie Zhou"
  - "Srikanth Kandula"
affiliations:
  - "Microsoft"
  - "Rice University"
  - "University of Maryland"
conference: nsdi-2025
category: security-and-privacy
tags:
  - security
  - networking
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ZTS 是一个面向 public cloud 的端到端 micro-segmentation 系统。它的关键做法是：从 communication graph 中结合 deployment-specific feature 和少量人工标签来推断 endpoint role，再基于这些 role 生成和维护分段策略。论文在 11 个真实部署上表明，它的聚类准确率明显高于已有 role-inference 基线，而图生成流水线相对作者实现的 Apache Flink 方案快 7.5x、成本效率高 21.5x。

## 问题背景

这篇论文首先指出了一个很现实的落差。零信任语境下的 micro-segmentation 很有吸引力，因为它能在入侵发生后限制 lateral movement；但在 public cloud 里，真正难的是先把 segment 划出来。现有商用方案大多要求管理员手工给每个 endpoint 打标签。对小系统这也许可行，但对拥有成千上万甚至上百万资源、工作负载不断变化、又有许多团队同时修改软件行为的云部署来说，这种做法几乎无法维护。作者调研发现，只有 12% 到 23% 的节点带有足够有用的现成线索，比如 tag、功能名或机器角色元数据，因此纯人工标注既不完整，也很容易过时。

单靠“看见流量”本身也很贵。一个可用的 micro-segmentation 系统必须近实时地知道谁和谁通信，这样才能建议策略、检测漂移，并在部署变化时重新分段。论文认为，这类可见性的成本才是落地的主要经济障碍：商用产品的额外费用已经能达到 VM 成本的 16% 到 71%，而作者早期基于 Flink 和 Spark 的尝试也会把总 VM 成本再抬高 10% 以上。所以真正的问题不只是“怎么在图上做聚类”，而是如何在足够低的成本下，持续推断出有意义的 workload role，并维护能用于分段的 communication graph。

## 核心洞察

论文的核心判断是，micro-segmentation 应该围绕“推断出的 deployment role”来构建，而不是围绕原始 IP，也不能只依赖图结构。在一个云部署里，很多 endpoint 在功能上属于同一种角色，但它们并不会拥有完全相同的邻居或完全相同的流量模式。纯结构聚类因此很容易错过管理员真正关心的语义规律。ZTS 把 role inference 重新表述成一个 deployment-specialized 的表示学习问题：把 graph structure、端口、流量统计、motif，以及系统里已有的部分标签或管理员反馈一起编码，学出一个能把同角色节点拉近的 embedding。

与之对应的系统洞察也很务实。论文没有去追求更丰富但更昂贵的 telemetry，而是认为主流云厂商已经提供的 connection summary 足够好，只要后端分析流水线真的按它们的格式和规模来设计即可。通过批处理、预处理，再配合基于 SQL 的 heavy-hitter graph construction，ZTS 把“持续在线的分段可见性”做到了足够便宜，因而具备大规模部署价值。

## 设计

ZTS 由三个主要部分组成：communication-graph generator、role-inference trainer 和 policy enforcer。它的 telemetry 来源是大型 public cloud 中已经普遍存在的 flow summary logging。这类 summary 通常由 programmable NIC 或宿主机网络栈采集，对租户 VM 的干扰很小，而且比 VM 内代理更不容易被攻陷后的客户代码篡改。

graph generator 的设计紧贴这种 telemetry 的实际形态。云平台会输出大量小型、嵌套的 JSON 文件，里面再嵌入分隔符编码的 flow summary。ZTS 因而把处理流程拆成两阶段：先由可扩展的 pre-processor 解析并打包原始文件，再由 batch SQL 系统把这些批次聚合成 communication graph，并补充 IPAM 与 virtual-network 元数据。为了把成本压住，图构建阶段会把那些贡献不到 0.1% bytes、packets 或 connections 的 remote IP 和 ephemeral port 合并掉，并通过大量使用 CTE 的查询优化避免昂贵的中间结果物化。它明确追求的目标是：大约 1000 台 VM 的 telemetry，只用少量几台 VM 级别的资源就能处理。

在此基础上，ZTS 为 featured IP graph 定义 adjacency matrix `A` 和 node-feature matrix `X`。它先分别对二者做 PCA，在保留 99% 方差的前提下去噪和降冗余，再把降维后的表示拼接起来。接着，这些向量进入一个带 contrastive loss 的 autoencoder。contrastive 项利用部分标签 `h`，这些标签可能来自端口规则、命名规则或管理员反馈，用于把已知同角色的节点拉近、不同角色的节点推远。训练完成后，系统把 encoder 输出视为节点 embedding，并通过 hierarchical agglomerative clustering 得到 role。最后，这些 role 被当作建议的 micro-segment；policy enforcer 再把 segment-level policy 映射回具体的 IP-level 规则，并在新 endpoint 出现或角色变化时持续更新。

## 实验评估

role inference 这部分的评估相当扎实，因为它不是在单一 toy graph 上比指标，而是使用了 11 个真实的一方和三方部署。这些数据集在用于准确率评估的摘要图里，规模从大约 100 个节点到 25,000 个节点不等，边数最高到 165,000。与 Jaccard、SimRank、GAS 和 CloudCluster 相比，ZTS 的平均 Adjusted Rand Index 为 0.77，而这些基线分别只有 0.33、0.43、0.39 和 0.34。唯一一个 ZTS 不是绝对最优的数据集是 Deployment C，在那里它得到 0.96，而最佳基线是 0.97；原因是该部署的 ground truth 本身部分参考了 Jaccard。这个例外反而让结果更可信。

policy authoring 的实验同样重要，因为它把聚类质量直接连回最终用途。在五个较大的部署上，用 ZTS 推断出的 role 生成的策略，在四天后的 telemetry 上只产生 0.1% 到 2.1% 的 policy violation rate；而基线方法生成的策略则在 2.1% 到 38.4% 之间波动。这个结果支撑了论文最实际的论点：更好的 role inference 不只是指标更漂亮，而是真的会减少错误拒绝和过度暴露的分段策略。

在 telemetry analytics 成本方面，ZTS 与作者实现的 Flink 方案对比。ZTS 运行在每月总成本 845 美元的基础设施上，而 Flink 方案需要 2406 美元。在区域级数据集上，ZTS 处理 1 小时 telemetry 需要 78 到 109 秒，而 Flink 需要 344 到 590 秒；处理 10 倍放大的数据集时，ZTS 为 765 秒，Flink 则达到 5748 秒。因此，论文给出的总结是站得住脚的：在 35% 成本下获得 7.5x 的速度，等价于 21.5x 的成本效率提升。不过，这里的实验对象是策略编写与监控环路，而不是攻击发生中的在线 enforcement。

## 创新性与影响

这篇论文的新意不在于提出新的 packet-filtering dataplane，而在于把两件通常被分开的事整合到了一起：用于分段策略编写的 role inference，以及一个足够便宜、能够持续支撑这套编写流程的 cloud-native telemetry pipeline。CloudCluster 之类的图方法已经会对 communication structure 做聚类，但 ZTS 认为分段问题需要的是由领域特征和人工线索共同塑形的 embedding，而不是只看 topology。与此同时，它把 graph generator 的成本当成一等系统约束来设计，而不是实现完功能后再补优化。

这种组合对 public-cloud 安全团队是有现实价值的。如果 role inference 在更多部署上也成立，ZTS 就能显著降低创建 micro-segment 的人工负担，并在部署变化时让策略维护不那么脆弱。我预期它会同时被两类人引用：一类是做 security policy synthesis 的系统研究者，另一类是构建 east-west cloud traffic 零信任控制的工程团队。

## 局限性

ZTS 仍然依赖 deployment-specific 的 feature engineering 与部分监督。它比静态基线灵活得多，但并不是“无需先验”的通用魔法：如果现有标签、端口信息或元数据质量很差，聚类质量依然会下降。论文定义 ground truth role 的方式也是通过开发者访谈完成的，这在工程上合理，但对一些服务来说难免带有主观性。

graph generator 的成本结果虽然很亮眼，但比较对象是作者自己的 Flink 设计以及 cloud-managed SQL 基础设施。论文并没有证明一个高度定制的流式引擎一定无法缩小差距，也没有把 telemetry 收集与存储的全部成本完全纳入核心比较，因为作者把这部分视为所有方案的共同底座。最后，policy violation 实验也明确说明系统并不打算实现全自动策略下发。即便 role 推断得足够好，策略仍然需要操作员审核，而那些稀有或新近出现的通信边仍可能违反由历史轨迹生成的规则。

## 相关工作

- _Pang et al. (NSDI '22)_ - `CloudCluster` 同样对 cloud communication graph 做聚类，但它主要依赖结构相似性，而 `ZTS` 把领域特征和部分标签直接注入到 embedding 学习里。
- _Hsieh et al. (NSDI '24)_ - `NetVigil` 利用 east-west traffic telemetry 做数据中心安全异常检测；`ZTS` 则把相近的 telemetry 用在更前面的阶段，用来定义 role 并编写 micro-segmentation 策略。
- _Arzani et al. (NSDI '20)_ - `PrivateEye` 面向 cloud compromise detection，而 `ZTS` 的重点是通过事先划定 segmentation boundary 来做主动遏制，而不是事后检测入侵。
- _Mogul et al. (NSDI '20)_ - `MALT` 研究的是给运维人员使用的多层网络拓扑建模，而 `ZTS` 关注的是为 workload role 推断和安全策略生成重建 communication graph。

## 我的笔记

<!-- 留空；由人工补充 -->

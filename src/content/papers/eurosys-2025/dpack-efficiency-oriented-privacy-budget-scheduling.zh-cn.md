---
title: "DPack: Efficiency-Oriented Privacy Budget Scheduling"
oneline: "DPack把差分隐私预算当成有限资源来装箱调度：先估计每个数据块最划算的 RDP order，再优先放入更省预算的任务。"
authors:
  - "Pierre Tholoniat"
  - "Kelly Kostopoulou"
  - "Mosharaf Chowdhury"
  - "Asaf Cidon"
  - "Roxana Geambasu"
  - "Mathias Lécuyer"
  - "Junfeng Yang"
affiliations:
  - "Columbia University"
  - "University of Michigan"
  - "University of British Columbia"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3696096"
code_url: "https://github.com/columbia/dpack"
tags:
  - scheduling
  - ml-systems
  - security
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文主张别再把 privacy budget 主要当成公平分配对象，而要把它当成会被永久消耗的稀缺资源来装箱。DPack 通过估计每个 block 在哪一个 RDP alpha order 上最值钱，再按这个方向贪心打包，因此能比 fairness-first 的 DPF 放进更多私有 ML 任务。

## 问题背景

论文面对的是一个很具体的 DP-ML 场景：平台把用户数据按 block 存起来，不断有训练或分析任务到来，系统必须保证所有发布结果合起来仍满足全局 `(epsilon_G, delta_G)`。麻烦在于 privacy budget 和 CPU、RAM 不一样，它不是可回收资源；某个任务一旦在某个 block 上花掉了预算，这部分空间以后就永远没了。

作者之前在 PrivateKube 里做过 DPF，用 dominant resource fairness 的思路把 privacy 当资源调度，优先运行 dominant share 小的任务。可一旦 workload 有异质性，这种公平视角会明显浪费预算。最典型的情况是：一个任务横跨很多 block，另外几个任务各自只碰一个 block。按 dominant share 排序时，前者可能先拿走所有 block 的剩余额度，后面的几个任务全进不来，尽管换一种打包方式其实能让更多任务运行。RDP accounting 还会把这个问题再放大，因为每个任务在不同 alpha order 上的成本曲线并不一样。对真正运营 DP 平台的人来说，更自然的目标往往不是 max-min fairness，而是同一份用户数据到底还能支撑多少任务。

## 核心洞察

作者最重要的判断是：privacy scheduling 本质上是 knapsack，而不是 fairness。只盯着需求向量里最大的那一维，也就是 dominant share，只适合回答谁更公平，不适合回答谁更省预算。若使用传统 DP composition，正确的度量应该把任务跨所有 block 的归一化需求面积一起算进去；而到了 RDP，问题更特别，因为每个 block 对应多个 alpha order，但最终只要该 block 至少有一个 alpha 仍然没超预算，就还能给出合法的传统 DP 保证。

这意味着 alpha 维度和普通多维 knapsack 的资源维度语义不同，不能简单把每个 alpha 都当成必须同时满足的约束。DPack 的核心想法就是先猜出每个 block 最可能成为最终有效约束的那个 alpha，也就是最能装下任务的 best alpha，再主要根据任务在这些 best alpha 上消耗了多少预算来排序。换句话说，调度器真正该守住的，是未来最可能卡脖子的 privacy coordinate。

## 设计

论文先把传统 DP 下的效率型调度写成标准的 multidimensional knapsack：任务有 weight，也有对每个 block 的 privacy demand，目标是在每个 block 都不超预算的前提下，让总 weight 最大。这个问题是 NP-hard，所以不可能指望精确求解在系统里直接跑。作者随后把 DPF 重新解释成一种贪心启发式：它用 dominant share 导出的效率分数排序任务。DPack 在传统 DP 场景里把这个分数改成基于整体面积的版本，也就是 weight 除以跨 block 的总归一化 demand。

真正新的部分发生在 RDP。此时任务的需求变成 `d_{i,j,alpha}`，而合法性条件也从每个维度都不能超预算，改成对每个 block 来说只要存在某个 alpha 仍在容量内即可。作者把这个问题命名为 privacy knapsack，并证明它同样 NP-hard；同时又证明单 block 情况可以做出多项式时间近似，而多 block 情况除非 `P = NP` 否则不存在 FPTAS。

DPack 就利用了这个单 block 可近似的性质。它先对每个 block、每个 alpha 单独求一个近似 single-block knapsack，看哪个 alpha 能装下最多 utility，把它当成该 block 的 best alpha。接着，任务的效率分数只看它在各个 block 的 best alpha 上消耗的归一化预算，再按这个分数贪心排序。真正决定能不能放入时，系统仍会检查完整约束：每个相关 block 至少还要保留一个 alpha order 不超预算。在线版本则把任务按周期 `T` 批量调度，每轮只解锁每个 block 的 `1/N` 容量，并借助 privacy filter 处理自适应到达任务，保证最后仍能回到目标 `(epsilon, delta)`。

## 实验评估

评估分成三层。第一层是 offline microbenchmark：作者准备了 620 条 RDP 曲线，覆盖五种常见 DP mechanism，再系统性调两个异质性旋钮，一是任务会请求多少个 block，二是不同任务的 best alpha 会差多远。在这组实验里，DPack 与 Gurobi 求出的最优解始终贴得很近，最差也在 23% 以内；而一旦异质性升高，它对 DPF 的优势就很明显，最多可多调度 161% 的任务，或在 best alpha 异质性场景下多调度 67%。同一节还说明了为什么不该把精确求解器直接拿进系统：有 7 个 block 时，Optimal 大约到 200 个任务后就基本不可用了，DPack 和 DPF 则还能保持实用。

第二层是更接近真实在线环境的 Alibaba-DP。它从 Alibaba 2022 GPU 集群 trace 出发，用系统指标去近似 privacy usage 和 block 需求，所以仍是 proxy workload，但已经比纯手搓 toy trace 靠谱得多。在这组实验里，DPack 比 DPF 多分配 1.3-1.7x 的任务，换成绝对增幅是 22-43%。落到 Kubernetes prototype 上，DPack 最终调度了 1269 个任务，DPF 是 1100 个，而且两者的等待时延分布几乎一样。

我觉得这组实验最有说服力的地方，在于作者没有回避自己不占优的情况。到了 Amazon Reviews 那个比较简单的 workload，由于 block 需求和 best alpha 几乎没什么变化，DPack 和 DPF 表现基本一致。也就是说，它并不是一个放之四海皆准的更优算法，而是专门在 workload 具有异质性时才真正兑现收益，这和论文前面的理论判断是对上的。

## 创新性与影响

和 _Luo et al. (OSDI '21)_ 相比，这篇论文的创新不在于提出新的 privacy abstraction，而在于把优化目标从 fairness 改成 efficiency。和 _Ghodsi et al. (NSDI '11)_ 这类多资源公平调度工作相比，它的新意则在于指出：当资源是会永久耗尽的 privacy budget，且 RDP 又带来 alpha-order 这种特殊语义时，dominant share 已经不是一个合理的效率指标。

因此这更像是一篇新问题表述加新启发式算法的论文，而不是重做一套完整训练系统。不过它的潜在影响很直接：如果私有训练平台真的能在同样的公开隐私承诺下多接纳 1.3-1.7x 的任务，那就等于同一批用户数据能支撑更多模型更新和更多分析作业。

## 局限性

最明显的限制是评估仍然大量依赖 synthetic 或 proxy-derived workload。Alibaba-DP 虽然比旧工作更像真实场景，但 privacy demand 终究是从内存和网络指标推出来的，不是从真实 DP pipeline 的 accountant 里直接读出来的，因此收益幅度有可能随 proxy 质量而变化。

第二个限制是它明确放弃了 DPF 意义上的公平性。论文里那组 Alibaba 实验显示，DPF 能让 90% 的 fair-share 任务被调度，而 DPack 只有 60%，只是总代价换来了 45% 更多的任务数。如果使用者很在意哪一类任务总能先被满足，那这不是一个免费升级。

最后，DPack 在一般情形下仍是 heuristic。作者只在单 block 等特殊情况下给出较强的理论保证，多 block privacy knapsack 依旧很难；而且整套方法默认 curator 与任务代码可信，也默认每个任务申报的 DP 成本本身是正确的，这些前提一旦不成立，系统保证就会变弱。

## 相关工作

- _Luo et al. (OSDI '21)_ - PrivateKube 与 DPF 把 privacy budget scheduling 做成系统问题；DPack 继承这套模型，但把目标换成效率优先的装箱。
- _Lécuyer et al. (SOSP '19)_ - Sage 提供了 data block 与 privacy filter 的组合方式，DPack 在线版正是沿着这条 accounting 路线扩展出来的。
- _Küchler et al. (S&P '24)_ - Cohere 同样把差分隐私当成一等系统资源管理，但更依赖精确求解或 workload 结构；DPack 的重点则是可扩展的近似调度。
- _Ghodsi et al. (NSDI '11)_ - Dominant Resource Fairness 是 DPF 的思想源头，而这篇论文的一个核心观点恰恰是 dominant-share 排序不适合有限的 privacy budget。

## 我的笔记

<!-- 留空；由人工补充 -->

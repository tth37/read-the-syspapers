---
title: "BFTBrain: Adaptive BFT Consensus with Reinforcement Learning"
oneline: "BFTBrain 把 BFT 协议选择建模成具备拜占庭鲁棒性的 contextual bandit，在工作负载、故障和硬件变化时在线切换六种协议。"
authors:
  - "Chenyuan Wu"
  - "Haoyun Qin"
  - "Mohammad Javad Amiri"
  - "Boon Thau Loo"
  - "Dahlia Malkhi"
  - "Ryan Marcus"
affiliations:
  - "University of Pennsylvania"
  - "Stony Brook University"
  - "UC Santa Barbara"
conference: nsdi-2025
category: consensus-and-blockchain
code_url: "https://github.com/JeffersonQin/BFTBrain"
tags:
  - consensus
  - fault-tolerance
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

BFTBrain 把六种 leader-based BFT 协议封装进同一个执行引擎，并按 epoch 在线选择下一轮该运行哪一种。它真正的贡献不是发明了一个更强的单一协议，而是把“协议选择”本身做成了拜占庭鲁棒的学习闭环：副本本地采集工作负载与故障信号，经由共识形成报告法定人数、按字段取中位数，再切到当前条件下最合适的协议。论文报告，在动态环境下它比固定协议高 18%-119%，在被污染数据场景下相对已有学习方案最高可领先 154%。

## 问题背景

论文首先系统性地量化了一个常识：BFT 世界里不存在“一招吃遍天”的协议。Zyzzyva 和 SBFT 在 fast path 高概率命中的条件下很强，CheapBFT 在某些大请求或更小 quorum 更占优的场景下更好，Prime 和 HotStuff 一类协议则更能扛 slow leader。到底谁赢，取决于 request size、reply size、客户端负载、网络规模、客户端资源，以及 leader 是否恶意拖慢提案。作者用 Table 1 说明了这一点：4 KB 请求、无明显故障时 Zyzzyva 最好；请求增大到 100 KB 后 CheapBFT 反超；leader proposal 变慢时，HotStuff-2 或 Prime 又会因为 slowness 程度和系统规模不同而成为最优。

这意味着传统部署流程非常脆弱。工程师往往在离线 benchmark 里挑一个协议，然后希望生产环境别偏离太多。现有自适应工作也没有真正解决问题。`Abstract` 虽然支持切换协议，但核心逻辑是预设好的 fallback 顺序；这过于僵硬，因为最优协议并不是简单的主备替补链。`A DAPT` 用 supervised learning 改进了协议选择，但它假设存在一个中心化 learner，需要在部署前为具体环境收集完整标签数据，而且缺失关键的 fault-related feature。在拜占庭环境里，中心化 learner 本身就不可信；每换一套硬件还要重新采数据训练，更难落地。

## 核心洞察

论文的核心洞察是：协议选择问题应该被建模成在线 contextual bandit，而不是离线分类问题。BFTBrain 不试图学习一个对所有部署都恒定有效的“条件到协议”映射，而是在每个 epoch 都回答一个更现实的问题：基于刚刚观察到的状态，下一轮值得尝试哪一个协议，并在 exploitation 与 exploration 之间做平衡。

这个想法成立的前提，是状态必须刻画出真正决定协议胜负的机制差异。因此论文没有只看粗粒度指标如 throughput，而是引入了能解释协议为何输赢的信号，例如 fast-path ratio、per-slot 接收到的消息数、request/reply size、client sending rate、execution cost，以及 leader proposal slowness。更关键的是，学习过程本身也必须能抵抗拜占庭行为。BFTBrain 因而不信任单点收集器，而是让副本交换本地测量值，对报告法定人数再跑一次共识，并按字段取中位数，使得有限数量的污染值无法把全局状态拖出 honest range。

## 设计

BFTBrain 以 epoch 为单位运行，每个 epoch 包含 `k` 个已提交请求。在一个 epoch 内，底层 BFT 协议保持不变。每个节点同时运行 validator 和 companion learning agent。执行到足够多请求后，learning agent 汇总最近的工作负载与故障状态，预测下一个 epoch 应该切到哪种协议。

状态空间分成三类。工作负载特征包括平均 request size、平均 reply size、聚合后的 client sending rate，以及 executor thread 消耗的 CPU cycles 所代表的 execution overhead。故障特征更有意思。为了刻画副本“缺席”或被放进 `in-dark` 的情况，BFTBrain 使用 fast-path ratio 与每个 slot 接收到的有效消息数；这些特征能区分 optimistic dual-path 协议在部分副本缺席时为何突然退化。为了刻画 slow leader，系统为每次 leader proposal 打时间戳，并测量连续 proposal 间隔。硬件与拓扑则不直接入模，作者认为这些较静态因素可以由在线训练后的模型隐式吸收。

动作空间就是六个候选协议：PBFT、Zyzzyva、CheapBFT、Prime、SBFT 和 HotStuff-2。这里最细的建模问题在于，某些 fault feature 会依赖“上一轮选了哪个协议”。例如 proposal interval 变高，既可能意味着 leader 恶意拖慢，也可能只是当前协议天然让 leader 做更多工作。为避免这种 one-step dependency 误导 learner，BFTBrain 为每个 `(previous protocol, next protocol)` 对分别训练一个 random forest，并把经验缓冲区也按这种转移对拆桶。然后它用 bootstrap resampling 的方式近似 Thompson sampling：对对应桶采样训练模型，枚举所有候选 next protocol 的预测 reward，选出最优；空桶则优先被探索。

学习协调机制是论文第二个核心系统贡献。每个 epoch 结束后，agent 会广播上一轮本地测得的 reward，以及自己提取出的下一轮状态。一个独立的 validated Byzantine consensus 实例对报告集合达成一致。如果法定人数里有 `2f + 1` 份报告，各 agent 就对每个字段取中位数，把得到的 state-action-reward 三元组写入经验缓冲区，重新训练模型，并推导下一轮协议；如果报告不足，则保留当前协议，不做低置信度切换。附录进一步给出了这条学习路径的 safety、liveness 与 robustness 论证。

协议切换本身建立在 `Abstract` 的 Backup 思路之上，但 BFTBrain 对它做了专门化，因为所有 epoch 都运行在同一组机器上，而且每个 epoch 都是 backup instance。副本可以异步广播 init history，而不必等待客户端驱动切换。对于像 Zyzzyva 这样的 speculative 协议，论文还加入了一个关键技巧：把第 `k` 个请求强制设成经 slow path 提交的 `NOOP`，这样副本才能确定性地知道当前 epoch 已经结束。

## 实验评估

实现方面，底层 BFT 框架基于 Bedrock，协议运行时用 Java，learning agent 用 Python 与 scikit-learn，并通过 gRPC 与 validator 交互。实验主要跑在 CloudLab 的 xl170 裸机上，配置为 10-core Intel E5-2640v4、64 GB 内存和 Mellanox ConnectX-4 NIC，系统规模为 `n = 4` 或 `n = 13`。优化目标是 throughput。

静态场景的结果体现了预期取舍：当条件完全不变时，BFTBrain 不会超过最佳固定协议，但它能较快收敛到这个最优点，并在跨场景平均表现上更好。代表性 LAN 设置下，它在 0.81 到 5.39 分钟内达到稳定峰值。例如作者的 "Row 1" 中，BFTBrain 达到 13,100 tps，而最佳固定协议 Zyzzyva 为 13,664 tps；"Row 8" 中，BFTBrain 为 4,329 tps，而 Prime 为 4,527 tps。这些差距基本就是在线探索和切换成本，但换来的是适应能力。

真正关键的是动态实验。在一个 4 小时、轮流切换多种工作负载和故障条件的 benchmark 中，BFTBrain 提交的请求数比最佳固定协议多 18%，比最差固定协议多 119%，比 `A DAPT` 多 14%，比使用更完整特征但预训练不完整的 `A DAPT#` 多 19%，比手写 heuristic 多 43%。当系统再次回到曾经见过的条件时，BFTBrain 的收敛速度明显加快，从首次约 70 秒缩短到约 2 秒。在一个更激进的 randomized sampling 两小时实验里，它又比 `A DAPT` 多提交了 44% 的请求。

WAN 与数据投毒实验进一步支撑了论文主张。当同一 workload 从 LAN 挪到一个 RTT 为 38.7 ms、带宽 559 Mbps 的 live WAN 后，最佳固定协议会从 Zyzzyva 变成 CheapBFT；BFTBrain 能在 1.58 分钟内重新学到这一点，而 `A DAPT` 会卡在之前 LAN 训练出的 Zyzzyva 选择上。在轻度数据污染下，BFTBrain 吞吐只下降 0.7%，而 `A DAPT` 下降 12%；在重度污染下，BFTBrain 仅下降 0.5%，`A DAPT` 则可能下降 55%，使得 BFTBrain 获得 154% 的优势。换句话说，论文关于“去中心化报告 + 中位数聚合确实重要”的论点是有扎实证据支持的。

## 创新性与影响

最接近的前作是 `Abstract` 与 `A DAPT`。`Abstract` 的贡献是把多协议切换框架搭起来，但切换策略本质上还是手写的 fallback policy。`A DAPT` 把学习引入协议选择，却仍停留在中心化、离线预训练范式。BFTBrain 的新意在于把三件事合成一个能部署的系统：围绕协议机制差异而非单纯结果来设计 feature，使用无需针对每次部署做完整预训练的在线探索策略，以及为 learner 自身再做一条拜占庭鲁棒的协调路径。

这使得论文对 permissioned blockchain 和其他 BFT replicated service 的工程实践很有价值，尤其是在工作负载变化、硬件异构、攻击行为并存的环境里。它并不是在狭义算法意义上提出一个新的 consensus protocol，而是提出了一个“在多协议之间做运行时选择”的控制平面。这个 framing 很重要，因为它把协议选择从“一次性 benchmark 决策”提升成了系统持续运行时的一等问题。

## 局限性

最大的局限是设计空间仍然有限。BFTBrain 只能在已实现的六种协议之间选择。如果某个部署的最佳答案不在这个候选池里，learner 无法自己“发明”出来。因此论文证明的是在一个强但有限的协议集合里，自适应选择是有价值的。

建模假设也比“reinforcement learning”这个名字听起来更克制。论文实际采用的是 contextual bandit，而不是长时程 MDP，并且只显式处理了一步依赖，通过 per-transition model 规避状态解释歧义。这是务实的工程选择，但也意味着系统不会显式推理长期切换成本，或者更久远的协议历史。

最后，实验虽然有说服力，但仍不是无条件可外推。多数结果来自 4 节点和 13 节点部署，且所有协议都运行在统一的 Bedrock 实现之上，而不是各自最成熟的生产实现。CheapBFT 也为了切换便利做了额外 active replica 的改动。再加上 reward 只优化 throughput，而不是延迟与吞吐的联合目标，这些都限制了结果的普适解释范围。

## 相关工作

- _Aublin et al. (EuroSys '10)_ - `Abstract` 最早系统化提出 Backup 风格的 BFT 协议切换，但它依赖预定义的 progress condition 和 fallback 结构，而不是在线学习最优协议。
- _Bahsoun et al. (IPDPS '15)_ - `A DAPT` 用 supervised learning 选择协议，而 `BFTBrain` 改为在线学习，并通过分布式报告与中位数聚合让学习路径本身具备拜占庭鲁棒性。
- _Gueta et al. (DSN '19)_ - `SBFT` 代表 optimistic fast-path 这一类协议，它在 benign 场景中表现很好，但一旦故障让 slow path 成为常态，BFTBrain 就会学会放弃它。
- _Yin et al. (PODC '19)_ - `HotStuff` 体现了 responsive leader replacement 在 slow leader 场景下的优势，而 `BFTBrain` 则把这种权衡推广成在多种 leader-management 策略之间运行时切换。

## 我的笔记

<!-- 留空；由人工补充 -->

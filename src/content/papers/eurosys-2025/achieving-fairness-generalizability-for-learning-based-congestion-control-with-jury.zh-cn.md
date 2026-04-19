---
title: "Achieving Fairness Generalizability for Learning-based Congestion Control with Jury"
oneline: "Jury 不让 DRL 直接学习吞吐份额，而是只学习瓶颈状态，再按估计的带宽占用后处理速率调整，因此公平性可以跨未见网络泛化。"
authors:
  - "Han Tian"
  - "Xudong Liao"
  - "Decang Sun"
  - "Chaoliang Zeng"
  - "Yilun Jin"
  - "Junxue Zhang"
  - "Xinchen Wan"
  - "Zilong Wang"
  - "Yong Wang"
  - "Kai Chen"
affiliations:
  - "University of Science and Technology of China"
  - "iSING Lab, Hong Kong University of Science and Technology"
  - "BitIntelligence"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696065"
code_url: "https://github.com/tianhan4/jury"
tags:
  - networking
  - ml-systems
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Jury 认为，learning-based congestion control 的公平性不该靠神经网络端到端学出来。它让 DRL 只看归一化后的 bottleneck-state 信号，先输出一个速率调整区间，再用带宽占用估计在区间里给不同流选动作，因此大流会更早让速，小流会更积极抢回份额。

## 问题背景

前几代 DRL 拥塞控制常见的失效模式是：训练区间里公平，出了训练区间就失稳。原因在于，公平收敛需要知道谁已经占了更多带宽，但 throughput 这类输入又会把策略绑在训练时见过的带宽尺度上。论文里的 Astraea 就是如此：训练在 100 Mbps 链路上没问题，换到 350 Mbps 后公平性明显退化。

反过来，把带宽相关特征直接删掉也不行。作者重训了去掉 throughput 特征的 Astraea，结果连训练环境里的收敛都很难学出来。真正的难点因此变成：怎样既利用带宽信息逼近公平点，又不让模型记住某个固定的带宽范围。

## 核心洞察

Jury 的核心判断是，把泛化和公平拆开处理。神经网络只负责识别 bottleneck 状态，也就是 queue 是空的、在增长，还是已经开始掉包；谁该让、谁该抢，则交给一个不依赖训练分布的后处理步骤。

这样做之后，所有共享同一 bottleneck 的流看到的都是归一化后的 RTT 和 loss 变化，输入天然一致，模型给出的决策区间也会一致，不会因为链路从 100 Mbps 换到 350 Mbps 就失真。随后，Jury 再按带宽占用估计在同一个区间里选动作点，让大流更保守、小流更激进。

## 设计

Jury 先按控制周期记录 action-feedback 信号。送进 DRL 的只有归一化后的 RTT 变化和 loss 变化；DRL 部分采用 DDPG actor-critic，并结合 TD3 风格技巧，输出的不是单个动作，而是由 `mu` 和 `delta` 表示的决策区间。

另一条路径则用 sending rate 变化和 throughput 响应来估计 bandwidth occupancy。若速率提高后吞吐也明显上涨，说明这条流原本份额偏小；若吞吐几乎不动，说明它已经接近自己的公平份额。Jury 用这个估计值在 `(mu, delta)` 区间里选动作，再做乘性的 `cwnd` 和 pacing rate 更新。论文还补了 moving average、异常值裁剪、输出接近 0 时的强制探索，以及最小样本门槛，用来稳住噪声并降低短流的 DRL 开销。

## 实验评估

作者故意把训练区间收得很窄，只覆盖 20-100 Mbps 带宽、10-60 ms base RTT 和最高 0.1% loss，然后把 Jury 放到明显超出的环境里测试。在三条同构竞争流实验里，测试链路覆盖 20-400 Mbps、10-75 ms base delay、最高 0.3% loss，Jury 的平均 Jain index 达到 0.94，5th percentile 也有 0.82。RTT 异构测试里，20 条流中一半是 30 ms RTT，一半是 90 ms RTT，平均单流吞吐仍然接近，分别是 10.3 Mbps 和 11.1 Mbps。

性能方面，Jury 也没有因为强调公平性而明显掉速。单流仿真中，它在 10-600 Mbps 带宽、15-120 ms 单向时延、最高 1.5% 随机丢包，以及 0.2-16 BDP buffer 的范围内都维持了较高利用率和较低排队时延。satellite 风格链路上，42 Mbps 带宽、800 ms RTT、0.74% 随机丢包的条件下，它仍拿到超过 75% 的链路容量，并且只比 400 ms 单向 base delay 多出 18.2 ms。AWS 在 Seoul、Tokyo、London 之间的真实实验也给出同样结论：Jury 的 throughput-latency 前沿优于 Cubic 和其他学习式 baseline。

## 创新性与影响

Jury 的新意，不是又做了一个 RL-based congestion controller，而是换了切法。它不再指望黑盒策略同时学会公平和泛化，而是把学习问题收缩到 bottleneck-state 识别，再用一个手工设计的后处理规则保住公平性。这使它不只是一个更好的 controller，也像是一个给 learned control loop 加护栏的范例。

## 局限性

论文也把边界说得很清楚。Jury 保证的是 Jury 与 Jury 在同一 bottleneck 上的公平收敛；和 Cubic、BBR 这类其他协议竞争时，friendliness 只有经验结果，没有跨环境保证。再加上带宽占用是从 noisy 的 action-feedback 信号间接估出来的，估计误差会直接影响后处理。

工程代价也不小。Jury 仍然依赖 userspace inference loop，在 20 ms 控制周期下单次推理平均要 4.5 ms，虽然比 Orca 轻，但比经典 TCP 控制器重得多。reward 权重是为某一种 throughput-delay-loss 取舍调出来的，目标一变就要重训；大 BDP 链路上它的收敛也会更慢，因为反馈更迟、单周期可调整的幅度有限。

## 相关工作

- _Yen et al. (SIGCOMM '20)_ - Orca 也是把学习和经典拥塞控制拼在一起，但它让 Cubic 与 RL 直接交织，收敛性仍然会互相干扰；Jury 则把公平性明确收敛到一个独立的后处理阶段。
- _Jay et al. (ICML '19)_ - Aurora 证明了 vanilla deep RL 可以学出可用的拥塞控制策略，而 Jury 处理的是 Aurora 没有解决的那一段：一旦离开训练区间，公平性能否还站得住。
- _Dong et al. (NSDI '18)_ - PCC Vivace 依靠在线 trial-and-error utility optimization 逼近公平点，Jury 则希望在不花多个 RTT 做探索的前提下，依旧保留稳定的收敛行为。
- _Liao et al. (EuroSys '24)_ - Astraea 把 fairness 目标直接写进 multi-agent RL reward；Jury 基本可以看成是对 Astraea 失效模式的回应，即带宽尺度变化时，单靠学习奖励并不足以保住公平性。

## 我的笔记

<!-- 留空；由人工补充 -->

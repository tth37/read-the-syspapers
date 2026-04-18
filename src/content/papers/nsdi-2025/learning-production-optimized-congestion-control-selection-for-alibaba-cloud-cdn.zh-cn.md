---
title: "Learning Production-Optimized Congestion Control Selection for Alibaba Cloud CDN"
oneline: "ALI CCS 从 TCP 统计预测每条 CDN 连接的接入类型，再在 CUBIC 与 BBR 间切换，把 Alibaba Cloud 短视频业务的卡顿和重传一起压低。"
authors:
  - "Xuan Zeng"
  - "Haoran Xu"
  - "Chen Chen"
  - "Xumiao Zhang"
  - "Xiaoxi Zhang"
  - "Xu Chen"
  - "Guihai Chen"
  - "Yubing Qiu"
  - "Yiping Zhang"
  - "Chong Hao"
  - "Ennan Zhai"
affiliations:
  - "Alibaba Cloud"
  - "Sun Yat-sen University"
  - "Nanjing University"
conference: nsdi-2025
tags:
  - networking
  - datacenter
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ALI CCS 是 Alibaba Cloud 为短视频 CDN 部署的生产级 congestion control selection 系统。它不去重新设计一个新 transport，而是先从每条连接的 TCP 统计里判断这条连接更像 Wi-Fi 还是 4G，再据此在 CUBIC 和 BBR 之间选择。论文给出的关键价值不是分类模型本身，而是把这个决策做成了可泛化、可解释、且不会拖慢边缘节点请求路径的完整生产方案。

## 问题背景

论文要解决的是一个很现实的 CDN 运维矛盾：大多数 CDN 仍然在所有地区上使用统一的 CC 配置，但 Alibaba 的实测表明，不同省份、不同时间、不同接入网络下，BBR 和 CUBIC 的优劣会持续翻转。对短视频业务来说，这种差异会直接反映到 rebuffer rate 和起播体验上，而在 Alibaba Cloud 的流量规模下，哪怕只是几个百分点的退化，也会同时伤害用户体验和带宽成本。

直接的替代方案并不合适。只调一个 CC 的参数，仍然受限于该算法本身的反应逻辑；论文举例说明，为了让 CUBIC 在 4G 上追平 BBR 的 rebuffer 表现而把它调得更激进，只会把 retransmission rate 推得更高。把 ML 直接套到 CCS 上也有生产难题：客户端能回传 label 的请求只占 5%-10%，不同 CDN 节点面对的路径条件差异很大，而如果每条连接都在请求路径上串行做推理，QPS 会明显下降。于是问题就变成了：如何在大规模生产 CDN 上，为每条连接选择合适 CC，同时保证可泛化、可定位错误、而且在线开销足够低。

## 核心洞察

这篇论文最重要的判断是，Alibaba 没有直接去学“哪种 CC 最好”，而是先把问题化简成一个更稳定的任务。它们发现 network type 的 information gain 远高于其他特征：在 4G 下 BBR 通常更优，在 Wi-Fi 下 CUBIC 通常更优。于是 ALI CCS 先预测连接属于 Wi-Fi 还是 4G，再把 Wi-Fi 映射到 CUBIC、把 4G 映射到 BBR。

但这个化简只有在模型学到的是“接入类型信号”而不是“路径偶然性”时才成立。原始 TCP 统计混合了两者，所以论文借助因果图和领域知识去提取 path-invariant feature：IP prefix 在数小时尺度上通常近似对应稳定路径，同一 prefix 的样本可以帮助模型压制隐藏路径状态的干扰，之后在线阶段也能按 prefix 缓存结果。换句话说，ALI CCS 真正学的是“哪些 TCP 行为模式稳定地暴露了 Wi-Fi/4G 差异”，而不是去在线拟合短视频 QoE 本身。

## 设计

ALI CCS 的设计分成三层：可泛化的分类模型、面向运维的可解释工具链，以及低开销的在线部署路径。模型部分建立在一个分解式 causal graphical model 之上。论文把观测到的 TCP 统计视为两部分的叠加：一部分由 network type 决定，另一部分由路径容量、竞争流、buffer 等 hidden state 决定。为了尽量只留下前者，系统使用了带 GAN 风格训练目标的模型：分别为 Wi-Fi 和 4G 构造 discriminator，去判断样本来自哪个 `/24` prefix group；而 generator 则学习一种 feature representation，让这种“来自哪个 prefix”的判断变难，从而逼近对路径不敏感、但对 network type 仍然有区分力的表示。

为了把这件事做成能落地的系统，论文又加了几层明显带有 production 气质的工程化修正。因为真实环境里 prefix 数量太大，discriminator 不直接预测具体 prefix，而是先用 K-means 把 prefix 聚成组，再做组级判别。模型还加入了受 RSC 启发的 regularizer，避免过度依赖少数“看起来很好用”的特征，尤其帮助 feature distribution 与大 ISP 不同的小运营商样本；同时又加了 variance regularizer，要求同一个 `/24` prefix 的样本在抽取后的表示上更接近，以降低噪声。训练标签来自合作短视频应用通过 HTTP header piggyback 回传的 network-type 信息。

论文同样很在意“工程师能不能信这个模型”。它把深度模型输出的 Wi-Fi/4G 概率蒸馏成一个多输出 decision tree，再结合 Shapley analysis 去排查某些 `/16` 或某些特征为什么在特定区域上造成误判。这个 tree 不用于在线推理，因为它比原模型低 5%-7% 准确率，但它给了生产团队一个可以检查、解释和调整模型的抓手。

在线路径的核心原则则是：不要在请求关键路径上跑复杂推理。Alibaba 的 TCPe 内核扩展协议栈在收到新连接时，只查询本地 mapping cache 决定该用哪个 CC，再通过标准 socket 接口应用这个选择。后台则由 Log Server 收集细粒度 TCP 统计，AI Server 离线预测 network type，Aggregation Module 周期性把 prefix 到 CC 的映射下发到缓存。由于很多 prefix 会在数小时内持续被 Wi-Fi 或 4G 主导，而且同一 prefix 内的最佳 CC 往往一致，系统就能用按 prefix 聚合、按小时更新的 trie cache 把昂贵的 per-connection inference 变成一次很轻的本地查表。论文还加了保守的 fallback：只有高置信度预测才覆盖默认配置。

## 实验评估

这篇论文最有说服力的地方，是它评估的不是一个离线分类器，而是整个生产系统。在中国和东南亚三家主要 ISP 的约 400 个 CDN 节点上，模型只用 30% 节点的数据训练，就能达到 95.8%-99.0% 的 network-type prediction accuracy。在线验证还显示，两个类别的 recall 在至少 6 个月里都保持在 90% 以上，虽然 Wi-Fi recall 会随着月末 4G 使用比例变化而出现周期性波动。

系统开销方面，论文证明了“在线离线解耦”是这个方案成立的关键。串行在线推理的基线会带来 10,417 ns 的处理延迟，最大只能做到 7.6k QPS；ALI CCS 的 cache-based 方案把这两个数字变成 162 ns 和 18.4k QPS，对应 64.30 倍的延迟改进和 2.42 倍的 QPS 提升。CPU 使用在 17k QPS 时也只到 200%，也就是一台 256 核 CDN 节点里不到 2 个核；内存占用始终低于 2.9 GB。

真正的业务收益同样很强。随机对照实验显示，相比默认的全 CUBIC 部署，ALI CCS 让 4G 的 rebuffer rate 改善 9.31%，Wi-Fi 改善 2.51%，整体改善 4.76%。在 retransmission rate 上，App #1 提升 59.24%，App #2 提升 61.28%，按省份看增益范围为 25.51%-174.36%，论文把这部分节省折算为每年超过 1000 万美元的带宽成本收益。trace-driven emulation 进一步表明，在网络条件差、长尾代价最大的区域，ALI CCS 比 Configanator、Disco 和 Pytheas 更稳。

## 创新性与影响

这篇论文的创新点不是又发明了一个新的 congestion control，而是给出了一个“生产环境如何选用已有 CC”的完整方法论。它的关键贡献在于利用领域知识把 CCS 化简为 network-type classification，再围绕这个化简设计出可泛化、可调试、可低成本部署的整套系统。

因此，它的影响不只在 Alibaba 自己的 CDN 上。对其他 CDN 或大规模网络服务来说，这篇论文提供了一个很具体的模式：如果请求路径容不下重型推理，那么就要同时考虑因果不变性、运维可解释性，以及 prefix 级缓存这样的系统优化。它也提醒读者，在生产网络里，真正重要的往往不是平均准确率，而是差网络区域里的最坏表现。

## 局限性

ALI CCS 的适用范围比标题看起来更窄。它最终只是在 CUBIC 和 BBR 之间选择，而其核心化简又依赖于短视频业务中的一个强观察：Wi-Fi 和 4G 基本决定了哪一个更优。换一个业务、换一组 CC、或者换一个国家/运营商环境，这个映射关系未必还成立。

此外，这个方案依赖明显的部署控制力。Alibaba 需要来自客户端的一部分标注数据，需要足够深的领域知识来设计因果分解和 fallback 规则，也需要同时改造用户态 AI 服务、日志流水线、缓存分发和内核里的 TCPe。论文也承认一些边角情况并没有真正解决，比如 connection 与 network type 不是一一对应时怎么办。再加上 NAT、负载均衡和 ISP 策略变化都会破坏 prefix 稳定性，所以系统仍然必须依赖保守阈值和默认回退策略。

## 相关工作

- _Naseer and Benson (NSDI '22)_ - `Configanator` 也试图自动化 CDN 侧的 congestion-control 选择，但它基于更粗粒度的 network class 分组，较 ALI CCS 的 path-invariant per-connection 设计更容易在小样本区域过拟合。
- _Yang et al. (ICNP '23)_ - `Disco` 把 CCS 视为动态选择问题并采用 RL 风格机制，而 ALI CCS 避开了在线 reward learning，转而使用可缓存的 supervised access-type prediction。
- _Jiang et al. (NSDI '17)_ - `Pytheas` 通过 group-based exploration-exploitation 优化视频 QoE，而 ALI CCS 不在生产请求路径上做持续探索，因为短视频 QoE 反馈既滞后又昂贵。
- _Yen et al. (SIGCOMM '23)_ - `Sage` 关注从专家 CC 行为中学习更好的控制逻辑，而 ALI CCS 保持成熟 CC 不变，把重点放在生产 CDN 上可部署的 selection logic。

## 我的笔记

<!-- 留空；由人工补充 -->

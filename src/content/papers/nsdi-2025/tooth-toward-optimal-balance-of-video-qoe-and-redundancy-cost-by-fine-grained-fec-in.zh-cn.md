---
title: "Tooth: Toward Optimal Balance of Video QoE and Redundancy Cost by Fine-Grained FEC in Cloud Gaming Streaming"
oneline: "Tooth 结合 frame length 与预测的 loss pattern 为每帧设置 FEC 冗余，在降低 cloud gaming 卡顿与带宽成本的同时提高实际视频码率。"
authors:
  - "Congkai An"
  - "Huanhuan Zhang"
  - "Shibo Wang"
  - "Jingyang Kang"
  - "Anfu Zhou"
  - "Liang Liu"
  - "Huadong Ma"
  - "Zili Meng"
  - "Delei Ma"
  - "Yusheng Dong"
  - "Xiaogang Lei"
affiliations:
  - "Beijing University of Posts and Telecommunications"
  - "Hong Kong University of Science and Technology"
  - "Well-Link Times Inc."
conference: nsdi-2025
category: wireless-cellular-and-real-time-media
tags:
  - networking
  - datacenter
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Tooth 的核心观点是，cloud gaming 里的 FEC 不能再按整条流或整段时间统一设置，而要按帧决定，因为短帧在同样丢包条件下往往需要远高于长帧的冗余。它先在 RTCP 时间尺度上预测未来的 loss rate 和 loss aggregation，再结合当前 frame length 为每个编码帧选择 Reed-Solomon 冗余。部署到生产平台后，Tooth 把 stall 降低 40.2%-85.2%，把视频码率提高 11.4%-29.2%，同时把冗余带宽成本降低 54.9%-75.0%。

## 问题背景

cloud gaming 的应用层时限非常严格。如果 input-to-screen latency 超过大约 100 ms，玩家就会明显感觉到卡顿。作者对一个商用平台进行了覆盖 6 万多场 session、6.6 万玩家的大规模测量，发现真正主导 QoE 的是下行游戏视频传输，而不是其他模块。现有恢复手段都没有抓住正确的控制粒度。Retransmission 需要等待丢包检测，再额外承担至少一个 RTT，在这个时延预算下代价过高。现有 FEC 则普遍是 coarse-grained 的，通常给整条流、一个时间窗口，或者 GOP 中某几类帧设置统一冗余率。

问题在于 cloud gaming 的 frame length 变化很大。由于码率自适应和 VBR 编码，同一游戏流中的帧长度会从 2 个 packet 波动到 80 多个 packet。论文证明，在相同网络条件下，小帧的帧内丢包率 LRIF 会显著高于大帧。作者报告说，小帧的 LRIF 可以超过 30%，而大帧可能只需要约 2% 的冗余即可恢复。于是统一冗余会同时造成两种坏结果：对大帧过度保护，浪费带宽；对小帧保护不足，恢复失败。更糟的是，冗余发得太多还会制造额外拥塞突发，进一步抬高后续帧的 LRIF，导致 stall 反而更多。

## 核心洞察

这篇论文最值得记住的判断是，发送端真正应该控制的是每一帧的恢复概率，而不是整条流的平均 loss rate。这个恢复概率取决于三个在线可估计的变量：frame length、network loss rate，以及丢包在相邻帧之间究竟是分散还是集中。论文把第三个因素称为 network loss aggregation。只要 Tooth 能预测接下来短时间内的 loss pattern，就能把更多冗余留给那些真正脆弱的短帧，而减少对长帧的无谓保护，因为长帧在大数效应下的有效 LRIF 更低。换句话说，只有同时考虑应用层的帧结构和传输层的丢包结构，fine-grained FEC 才有意义。

## 设计

Tooth 把问题拆成 slow module 和 fast module，两者配合后，逐帧 FEC 才能在实时系统里落地。Slow module 在 RTCP feedback 到来时运行。它读取最近一段时间的 loss-rate 历史、loss-aggregation 历史，以及 packet arrival bitmap，然后用一个压缩过的 neural model 预测未来的 loss rate 和 future loss aggregation。它的 loss function 会更重地惩罚低估，因为冗余不够带来的 QoE 损失，比轻微多发一点冗余更难接受。

loss aggregation 是设计里很关键的一步。它不是只统计丢了多少 packet，而是刻画这些丢包究竟分散在很多帧上，还是集中砸在少数几帧上。对 Reed-Solomon 来说，这个区别很重要，因为恢复能力取决于某一帧里丢了多少 packet，而不是这些 packet 在链路上是否连续。

Fast module 则在每个视频帧编码完成时运行。它的输入是预测得到的 loss rate、loss aggregation，以及当前帧的 frame length，输出是该帧应该添加的冗余量。作者选择 random forest，而不是更大的 neural network，因为这个映射关系既非线性又不连续，但又必须在单帧时间预算内完成。论文还专门对训练集做了划分，避免模型过度依赖某一个特征。部署实现中，Tooth 位于服务器视频 codec 与 FEC codec 之间，运行在基于 WebRTC 的 streaming stack 上，使用 Reed-Solomon 编码，决策时间大约 0.7 ms，FEC 编码时间低于 1 ms。

## 实验评估

实验由两部分组成：一部分是大规模生产测量，另一部分是在商用平台上的 6 周在线部署。在线部署覆盖约 2,300 个 session，对比 RTC-FEC、RTC-FEC+、RL-AFEC 和 Hairpin。核心结果是，Tooth 不是沿着旧方法的成本-效果曲线挪动一点，而是找到了明显更优的工作点。它把 stall frequency 降到每分钟 0.49 次，把实际视频码率提高到 17.8 Mbps，并且相对几个 FEC baseline 把冗余带宽成本降低 54.9%-75.0%，把 frame recovery failure rate 降低 51.9%-89.3%。

消融实验也能支撑设计解释。把 random-forest fast module 换成启发式规则后，恢复失败率和带宽成本都会上升，说明逐帧冗余映射确实过于非线性，简单规则抓不住。把 neural slow module 换成简单平均，也会降低预测准确性，说明 future loss aggregation 不是靠朴素平滑就能估准。论文还表明，Tooth 的 dual-module 结构比单个大 neural model 明显更轻量。除此之外，Tooth 在 WiFi 和 cellular、2D 和 3D 游戏、四家 ISP、以及 intra-city / cross-city session 上都保持收益。一个规模较小的受控实验还显示它在 PSNR 和 VMAF 上优于次优基线。

## 创新性与影响

相对已有 adaptive FEC 工作，这篇论文的创新点不在于提出一种新的纠删码，也不只是再做一个结合 bitrate 和 loss rate 的控制器。它真正的新意是把 frame length 和 loss aggregation 提升为一等输入，并通过一个可部署的 split architecture 把逐帧决策压缩到生产系统可接受的时延内。这让它不仅对 cloud gaming 平台有价值，也会影响 WebRTC/FEC 设计者，以及那些控制粒度仍停留在 stream 或 GOP 层面的实时视频系统。

## 局限性

这篇论文的部署很有说服力，但外部有效性仍然有限。Tooth 只在一个具体商用栈上评估：WebRTC/RTP、H.265 with NVENC、100 ms 一次的 RTCP feedback，以及来自中国一个平台用户群的网络环境。论文没有说明，若换成其他 codec、transport 参数，或者完全不同的 client 组合，需要多大程度的 retraining 和 retuning。

此外，Tooth 也不是一个可以外挂到任意系统上的黑盒组件。它依赖 packet-level feedback、训练后的模型，以及对 media path 和 network path 的集成。最后，视觉质量部分的实验规模明显小于线上部署，而 Hairpin 对于 100 ms 以内的交互预算本身就处于结构性劣势，因此这个 baseline 的参考价值有限。

## 相关工作

- _Holmer et al. (ICIP '13)_ - RTC-FEC 根据粗粒度的 bitrate/loss heuristic 选择冗余，而 Tooth 额外引入 frame length 和 loss aggregation，按帧决定保护强度。
- _Chen et al. (MMSys '22)_ - RL-AFEC 围绕 GOP 中的 critical frames 调整冗余，而 Tooth 认为 cloud gaming 的 infinite GOP 和剧烈帧长变化要求 frame-by-frame 控制。
- _Rudow et al. (NSDI '23)_ - Tambur 通过跨多帧的 streaming codes 改善 videoconferencing 丢包恢复，而 Tooth 保持 frame-local 设计，避免引入 cloud gaming 无法承受的额外延迟。
- _Meng et al. (NSDI '24)_ - Hairpin 改进了 interactive video 的 retransmission，但 Tooth 认为在 cloud gaming 里，多出一个 RTT 的修复代价仍然过高，因此必须使用主动式 FEC。

## 我的笔记

<!-- 留空；由人工补充 -->

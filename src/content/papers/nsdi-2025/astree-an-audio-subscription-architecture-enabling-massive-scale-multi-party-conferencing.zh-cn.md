---
title: "AsTree: An Audio Subscription Architecture Enabling Massive-Scale Multi-Party Conferencing"
oneline: "AsTree 用 SFU 树逐跳只转发 dominant speakers，把大房间音频从全量订阅改成有界转发，并去掉大部分信令风暴。"
authors:
  - "Tong Meng"
  - "Wenfeng Li"
  - "Chao Yuan"
  - "Changqing Yan"
  - "Le Zhang"
affiliations:
  - "ByteDance Inc."
conference: nsdi-2025
tags:
  - networking
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

AsTree 把 Lark 早期的 `FullAud` 方案，也就是“每个人预先订阅所有远端音频流”，改成两层级 SFU 树加逐跳 dominant-speaker selection。每台 media server 只转发一个小而有界的响度最高流集合，并由 media plane 直接触发下游传输，而不是依赖房间级音频信令。结果是，大房间音频从 `O(N^2)` 的订阅问题，变成了一个有界的转发问题，并在线上同时改善了容量和 QoE。

## 问题背景

这篇论文的问题意识非常工程化。Lark 先靠 simulcast 改善了 video 体验，随后在海量通话反馈里发现，audio stall 反而成了最大的投诉类别。作者认为，音频订阅比视频订阅更难，原因有三点。第一，视频是否需要订阅，常常受 UI 和用户显式操作约束；而音频是被动的，任何人都可能随时开口。第二，如果等 `unmute` 后再建立订阅，语音开头往往已经被信令往返时间吞掉。第三，视频的 fanout 受界面布局自然限制，而音频没有这个上界，因为房间里每个人都可能变成说话者。

Lark 早期的解法是 `FullAud`：用户一进房间就预先把所有人的音频都订上，静音用户继续发送 DTX frame，mute/unmute 广播只负责更新界面上的状态。这个方案把建立订阅的代价前移了，但扩展性很差。Join 突发和 mute/unmute 会在 local signaling unit 上制造信令风暴；客户端会在很多静音或不重要的流上浪费带宽、CPU、内存和电量；服务器则要承担 `O(N^2)` 的边缘 fanout 和高昂的跨服务器 WAN 成本。论文还给了一个很直观的带宽估算：移动端一个 focus video 加一个 thumbnail 大约是 0.82 Mbps，因此同时 unmute 的人数一旦超过 12 个，audio 的带宽就可能已经超过 video；就算都是静音 DTX 流，人数超过 100 后也不再是小数目。换句话说，在真正重要的大房间里，瓶颈反而先落在音频上。

## 核心洞察

核心观察是，会议里在任意时刻真正承载关键信息的，通常只是极少数 dominant speakers。真正重要的并不是“承认音频很稀疏”这件事本身，而是把选择逻辑放在哪里。作者认为，speaker selection 不能主要放在 control plane，否则就会在最脆弱、最容易成为瓶颈的位置引入新的信令和额外 RTT。

因此，AsTree 采取的是逐跳的 `select-before-forward`。每个 SFU 只在自己本地收到的流和邻居转来的流里挑选最值得继续传播的那几个，尽可能早地丢弃低价值流，而不是先把流泛洪到所有地方、最后再在边缘裁剪。这样才能真正降低 WAN 成本和服务器负载，而不是只把问题从客户端挪到后端。

## 设计

AsTree 保留了 Lark 现有的 user plane、media plane 和逻辑集中 control plane，但把音频的拓扑改掉了。参与者先连到附近的 SFU media server。区域内采用一个非常务实的规则：某个房间里，在该 region 最早加入的 media server 成为 region delegate，之后同 region 的其他服务器都级联到它。跨 region 时，各个 delegate 再组成一棵 spanning tree。论文讨论了“最小化最长路径 RTT”等目标，但实际部署采用更简单的启发式：选出一个 master delegate，其余 region delegate 直接挂到它下面。这个决策强调的是成本和稳定性，而不是全局最优。

稳定性本身是设计目标之一。随着参与者加入和离开，AsTree 尽量不去拆已经建立好的 cascading link。Region delegate 通常会一直保留到该 region 在这个房间里没人为止；master delegate 也只有在经验时延阈值无法满足时才会变化。系统接受一定程度的路由次优，来换取更低的工程复杂度和更简单的 failover 逻辑。

音频选择是完全分布式的。每台 media server 只看两类输入：本地参与者发布的流，以及 cascading neighbor 转来的流；并且被选中的流不会被再发回来源方向。为了识别 dominant speaker，AsTree 不解码原始音频，而是直接使用 RTP header extension 里的 audio level。每条流维护最近 15 个包、约 300 ms 的 ring buffer；每 5 个包更新一次加权 audio level，每 50 ms 重跑一次选择。算法先预选最多 `Li` 个最响候选，再用 `extraCushion` 抑制抖动，并让已选流至少保留 `smoothTime`。线上默认值是 `Li = 4`、`L = 10`。audio level 为 127 的静音流会被直接排除。

控制面简化和树拓扑本身同样关键。AsTree 不再广播音频 `Publish`。Media server 会缓存上游 SDP offer；当某个 speaker 首次进入选中集合时，服务器向下游服务器或客户端发送更新后的 SDP answer，并立刻开始转发 RTP。大房间里的 Join 还可以聚合，而 mute/unmute 广播则被完全去掉。于是界面上的“是否 unmuted”不再对应按钮状态，而是对应该参与者的音频流当前是否被选中。

## 实验评估

评估同时包含压力测试和真实部署，这很符合这篇 operational systems 论文的目标。客户端侧，作者用 Redmi Note 13 只测试音频订阅负载。在 `FullAud` 下，即便远端参与者都处于静音状态，手机仍要接收和处理它们的 DTX 流，因此 CPU 和内存几乎随人数线性上升。到了 50 个静音参与者时，AsTree 相比 `FullAud` 让客户端 CPU 降低 64%，内存降低 17%。

服务器侧，benchmark 把参与者分成三类：持续发言且开视频的人、保持 unmute 但不说话的人，以及完全静音的观众。这个 workload 设计是合理的，因为论文的核心主张正是“大房间里多数人不是当前有效 speaker”。在单 region、单服务器实验里，AsTree 的开销近似线性增长，而 `FullAud` 明显不是。房间规模到 125 人时，AsTree 比 `FullAud` 少用 80.9% CPU 和 89.5% 内存，作者据此估算单机可承载会议数提高到 5.2 倍。信令结果同样关键：当参与者以每秒 50 人的速度突发加入时，`FullAud` 的 CPU 峰值接近 75%，到 150 人就会崩溃；而 1000 人的 AsTree 房间没有出现可比的 join 峰值。

QoE 结果和资源结果吻合。Benchmark 中，AsTree 即使在 800 人房间里，也能让全部 audio/video frame 在 200 ms 内完成 encode-to-decode；`FullAud` 在只有 125 人时，满足同一阈值的音频帧只有 0.014%，视频帧也只有 51.6%。Audio stall 在 `FullAud` 下只有 25 人房间才能做到零，而 AsTree 在 800 人时仍是零；video stall 相比 125 人的 `FullAud` 也低了接近两个数量级。论文也特别说明，DTX frame 被一并算入音频 latency，因此 `FullAud` 的音频数据会显得格外差，但视频指标给出的趋势完全一致。

最有说服力的还是线上结果。2021 年 8 月到 2022 年 1 月，在超过 1 亿场会议的真实部署中，AsTree 让音频卡顿比例的中位数下降 30% 以上、95 分位下降 45% 以上；视频卡顿比例的中位数和尾部都下降 50% 以上；负面评价比例下降约 40%。至于树拓扑本身的额外绕行，论文给出的数字也很克制：与 ByteDance 其他 RTC 应用相比，Lark 每条已订阅流经过的 cascading link 平均只多了 5.7%。

## 创新性与影响

这篇论文的创新不在于“有 dominant-speaker selection”这件事本身。很多系统和产品里早就有 loudest-speaker 的想法。AsTree 真正补上的，是一套完整可部署的架构：两层级 cascading tree、逐跳的分布式音频选择，以及把音频特有的控制面广播整体拿掉。论文最强的地方，也正是很多 systems paper 最弱的地方：它不仅说清楚了机制，还说明了为什么一些看起来简单的替代方案在运维上并不成立，并拿出了真实部署后的行为数据。

因此，这篇论文同时服务两类读者。对 RTC 后端和 SFU 架构师来说，它给出了一种把 audio 和 video 分开扩展的清晰方法。对 systems 研究者来说，它则提供了一份很少见的大规模一线报告，说明当系统仍把音频当成视频之后的附属问题时，究竟会先在哪里崩掉。

## 局限性

AsTree 依赖一个经验事实：任意时刻真正重要的 speaker 数量很小。如果很多人持续同时说话，系统虽然仍能扩展，但选择质量会更依赖“响度是否能代表重要性”这个代理指标。较安静但内容更关键的发言者，可能会输给更响但不那么重要的人。论文还接受了一个产品层面的折中：静音展示状态跟随当前是否被选中，而不是严格跟随按钮状态。

拓扑算法本身也是刻意设计成启发式的。Region 内部的“先到先当 delegate”和跨 region 的单 master delegate，确实能显著降低实现与 failover 复杂度，但并不保证全局最优，也可能在房间成员分布变化后错过更好的路径。作者明确把动态 topology deformation 和更丰富的优化目标留给未来工作。最后，这些证据对 Lark 非常有说服力，但毕竟仍然来自单一产品、单一网络足迹和单一工程栈，不能直接证明同样的常数和启发式能原样迁移到所有 RTC 系统。

## 相关工作

- _Volfin and Cohen (Computer Speech & Language '13)_ - 早期 dominant-speaker identification 依赖更丰富的语音特征，而 AsTree 必须在 SFU 上只靠 RTP 元数据工作，不能解码音频。
- _Grozev et al. (NOSSDAV '15)_ - `Last N` 限制的是 dominant-speaker video 的转发，并没有把音频订阅重构成逐跳裁剪的架构。
- _Lin et al. (SIGCOMM '22)_ - `GSO-Simulcast` 用集中控制编排 video simulcast；AsTree 则认为 audio 需要独立且更偏 media-plane 的拓扑，因为任何参与者都可能随时开口。
- _Bothra et al. (SIGCOMM '23)_ - `Switchboard` 解决的是会议服务的资源配置问题，而 AsTree 先把每个房间自身制造的负载压低，再让资源配置器去承接它。

## 我的笔记

<!-- 留空；由人工补充 -->

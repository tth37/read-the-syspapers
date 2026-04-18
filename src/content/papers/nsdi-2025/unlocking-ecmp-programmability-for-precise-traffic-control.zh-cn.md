---
title: "Unlocking ECMP Programmability for Precise Traffic Control"
oneline: "P-ECMP 把闲置的 ECMP groups 变成由 selector 驱动的路径策略，让主机无需关闭 ECMP 就能精确切路、探路和导流。"
authors:
  - "Yadong Liu"
  - "Yunming Xiao"
  - "Xuan Zhang"
  - "Weizhen Dang"
  - "Huihui Liu"
  - "Xiang Li"
  - "Zekun He"
  - "Jilong Wang"
  - "Aleksandar Kuzmanovic"
  - "Ang Chen"
  - "Congcong Miao"
affiliations:
  - "Tencent"
  - "University of Michigan"
  - "Tsinghua University"
  - "Northwestern University"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - networking
  - datacenter
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

P-ECMP 把 ECMP groups 变成由 selector 寻址的行，让主机在不关闭普通 ECMP 的前提下，为少量选中的包切换到另一种路径策略。这样一来，re-path、探路和确定性 spraying 都从“碰运气”变成“可控操作”，其中收益最大的是消除了 ECMP failover 的长尾重试。

## 问题背景

ECMP 在数据中心里广泛部署，是因为它便宜、适合 ASIC，而且从整体流量看足够有效。但精确流量控制要的是“现在就换到某条确定的路”，这正好和 ECMP 的随机性冲突。当流量撞上 gray failure、链路 flap 或热点拥塞时，PRR、PLB 这类方案只能修改包头字段，期待交换机里不透明的哈希碰巧选到别的路径。这样做会反复碰撞重试，而长尾延迟恰恰出现在最脆弱的流上。

作者指出，这种问题不只出现在 failover。Failure localization 需要覆盖所有路径，MPTCP 需要子流真正不重叠，packet spraying 需要可控分散，segment-routing-like 场景需要精确指定下一跳。彻底用显式路径替代 ECMP 代价太高，要求全网换成 programmable switch 也不现实。更务实的目标是：让绝大多数流量继续走普通 ECMP，只给少量选中的包提供快速、精确的覆盖能力。

## 核心洞察

核心洞察是，commodity switch 其实已经有合适的硬件原语，只是一直没有被提升成编程模型。ECMP groups 允许包携带 selector `s` 选择矩阵中的一行，再由正常流哈希选择列，因此转发决策可以写成 `C[s, Hash(f)]`。只要运营者能控制这些行的内容，就能在不关闭 ECMP 的前提下，叠加一层确定性结构。

由此可以得到两类策略。循环移位的行保留负载分散效果，但给路径增加一个已知 offset，足以实现确定性的 re-path；单端口的行则直接绕过哈希，给出精确 next hop，足以支持探路、spraying 和逐跳 steering。生产网络中的 ECMP-group SRAM 本来就大量闲置，因此这更像对现有硬件做重配置。

## 设计

P-ECMP 用循环移位的方式实现路径 offset 控制。如果基础行是 `[p0, p1, ..., pN-1]`，下一行就是 `[pN-1, p0, ..., pN-2]`；selector 改变时，输出端口就按固定 offset 平移，但行内仍保留按流哈希的随机分散。这正是 failover、拥塞触发切路和 multipath 去重叠所用到的机制。

Exact-next-hop 控制则把某一行压成单一端口。不同网络层级可以读取 selector 的不同 bit，因此主机可以把一条 ToR-leaf-spine 路径编码进去，支持全路径探测、确定性 packet spraying，以及无需额外封装的 segment-routing-like 功能。

编译器从 topology 中提取每台交换机的基础 ECMP group，再按 SRAM 约束追加所需的控制行。运行时一致性通过双版本更新保证：交换机 SRAM 分成两半，旧表和新表并存，只有在新表装好后主机才把 selector 切换到新版本区间。实现上，原型运行在 SONiC 上，覆盖 Trident 和 Tomahawk；selector 放在 DSCP；双宿主 NIC bonding 也被补丁成把 selector 叠加到 bond hash 之后。

## 实验评估

第一类结果回答“资源够不够”。在论文评估的 Clos 拓扑里，如果同时支持两类精确控制，ToR 只需要 4 到 16 个 ECMP groups，leaf 需要 4 到 128 个，spine 每个 pod 需要 4 到 16 个。对于最常用的 offset-only 模式，selector 只需 2 到 6 bit，所以 6-bit DSCP 足够；如果还要做 exact-hop 控制，大型 dual-homed 拓扑可能需要最多 24 bit。

最有说服力的是 failover。单流实验里，P-ECMP 每次都能在第一次 re-path 就成功，因此故障检测后的恢复时间稳定在约 6ms，不受故障层级影响。PRR 则保留随机碰撞带来的长尾：ToR 故障时，中位恢复时间是 42ms，95th percentile 超过 4.5s。在链路故障事件里，P-ECMP 在 65ms 内把 loss rate 降到 0，而 PRR 需要 85ms。

其他 use case 也有明显收益。用于 PLB 风格拥塞切路时，P-ECMP 把 80% 负载下 web-search 的 last-flow completion time 从 366.7 降到 189.0，把 Hadoop 的 1278.3 降到 769.1。用于 MPTCP 时，只要强制子流走不重叠路径，100K 条 flow 在任意单点故障下都能存活。用于 failure localization 时，probe 数量下降到 ECMP 随机探测方案的 1/2 到 1/5。用于 packet spraying 时，大多数 99th percentile 队列被压到 11KB，而随机 spraying 会出现 31KB 到 70KB 的队列。生产部署方面，Tencent Cloud Block Storage 的 IO jitter 最多分别下降 80%、36%、40%，IO hang 发生率最多下降 16%。

## 创新性与影响

相对 RePaC，P-ECMP 不依赖哈希线性，而是直接编排 mapping stage；相对 XPath，它复用廉价的 ECMP-group SRAM，而不是安装显式端到端路径；相对 PRR 和 PLB，它把主机触发的 reroute 从概率性重试变成确定性 primitive。真正的贡献是围绕现有 dataplane 特性建立起一整套系统化抽象：编程模型、编译器和一致性更新运行时。

## 局限性

生产落地目前主要覆盖 offset 型 failover，而不是完整的 exact-hop 功能族。Exact-next-hop 控制主要针对分层、tree-like 拓扑，大型 dual-homed 网络还可能需要 24 bit selector，因此 DSCP 单独不够。P-ECMP 还要求网络里确实存在可替代的 equal-cost 路径，并且把 failure detection 与 congestion signaling 交给外部系统处理。

## 相关工作

- _Hu et al. (NSDI '15)_ — XPath 通过在转发表里预装压缩后的显式路径来给主机路径控制，而 P-ECMP 保留 ECMP，只把 ECMP-group state 当作控制接口。
- _Zhang et al. (USENIX ATC '21)_ — RePaC 利用哈希线性实现相对路径控制，P-ECMP 则直接编排 ECMP-group 映射，从而避免依赖可预测的哈希算法。
- _Qureshi et al. (SIGCOMM '22)_ — PLB 在拥塞时也会重路由，但仍然依赖随机重试；P-ECMP 把同样的触发信号变成确定性的路径 offset。
- _Wetherall et al. (SIGCOMM '23)_ — PRR 在 RTO 触发后做 protective reroute，而 P-ECMP 消除了 PRR 仍然要承受的 hash-collision 长尾。

## 我的笔记

<!-- 留空；由人工补充 -->

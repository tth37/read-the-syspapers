---
title: "Atlas: Towards Real-Time Verification in Large-Scale Networks via a Native Distributed Architecture"
oneline: "Atlas 不再把大规模数据平面验证塞进单点服务器，而是让交换机、区域和中心分层协作，把环路、黑洞和策略检查压到接近实时。"
authors:
  - "Mingxiao Ma"
  - "Yuehan Zhang"
  - "Jingyu Wang"
  - "Bo He"
  - "Chenyang Zhao"
  - "Qi Qi"
  - "Zirui Zhuang"
  - "Haifeng Sun"
  - "Lingqi Guo"
  - "Yuebin Guo"
  - "Gong Zhang"
  - "Jianxin Liao"
affiliations:
  - "State Key Laboratory of Networking and Switching Technology, Beijing University of Posts and Telecommunications"
  - "Pengcheng Laboratory"
  - "E-Byte.com"
  - "Huawei Technologies"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3717494"
tags:
  - networking
  - formal-methods
  - verification
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Atlas 把 data plane verification 改造成三层 distributed service：Switch Adapter 维护单交换机模型，Region Adapter 汇总区域内可达性，Center Adapter 再把这些摘要拼成跨区域验证。多数数据集已经是亚秒级，在 500 台交换机的真实部署里也保持在 1 秒以内。

## 问题背景

这篇论文盯住的是一个很现实的瓶颈：近年的 DPV 工具虽然越来越快，但大多还是 centralized verifier。所有交换机的更新都要汇到一台服务器，由它维护整网模型并执行验证；网络一大，这台机器就同时成为算力瓶颈和收集瓶颈。论文给出的代表性数字是：EPVerifier 在 48-ary fat-tree、2,880 个节点上仍要 1 分钟以上。

把执行简单地下推也不够。Tulkun 虽然让设备参与验证，但前提是先靠 planner 为每台设备算出子任务。这个 planner 在大拓扑上会超时或吃爆内存，而且验证任务一变就得重算。Atlas 因而追求的是另一件事：让模型维护和任务执行在稳态里就已经是分布式的，而不是再套一个昂贵的中心预处理阶段。

## 核心洞察

Atlas 的核心洞察是，验证器应该顺着网络已有的层次结构来设计。只要交换机、region 和全局 backbone 各自只维护自己能从局部信息推出的抽象，更新就能在源头附近处理，上层只保留紧凑的 reachability 摘要。论文把这叫作 native distribution：模型维护天然分散在各层，验证时再把这些局部模型直接组合起来，而不是先在中心合成一份额外的执行计划。

## 设计

Atlas 分成三层。Switch Adapter (SA) 维护 switch-model，把输出端口映射到 packet set，并用 BDD 编码；Region Adapter (RA) 把多个 SA 合成 region-model，记录区域内转发、跨区域出口以及 backbone node 之间的 reachability；Center Adapter (CA) 再把各个 RA 的摘要拼成 backbone-model。

不同任务按层拆分。loop-freedom 由 RA 检查区域内环路，CA 检查跨区域环路；blackhole 检查复用同一套路径推理，并让 SA 顺手报告本地 forwarding-table 缺口；user-defined policy 则由 CA 先按 region 切开约束路径，再向相关 RA 额外索取 backbone 与非 backbone 节点之间的 reachability，最后拼成任务专用的全局模型。Atlas 还支持增量维护：某条边变动后，RA 只从该边两端做双向遍历，再把受影响的 forward 和 reverse 摘要 join 起来，而不是整区域重算。

## 实验评估

评估覆盖 7 个 WAN 数据集、3 个数据中心数据集，以及一个 500 台交换机的真实部署。burst update 场景里，Atlas 在多数 WAN 的 loop 与策略验证上都低于 0.5 秒，在多数数据中心数据集里也大致保持在 1 秒上下。FT-48 上，Atlas 做 loop-freedom 和 user-defined policy 分别只要 0.97 秒、1.08 秒；Tulkun 是 4.28 秒、4.13 秒，EPVerifier 则是 63.36 秒、32.04 秒。更大的 INET 上，Atlas 仍能在 14.83 秒和 17.08 秒内完成，而 Tulkun 超时，EPVerifier 分别要 230.55 秒和 285.05 秒。

incremental update 的结果更能说明问题。初始装载后再顺序插入 10,000 条规则，Atlas 在所有数据集上都能把至少 96.97% 的更新压到 10 ms 内完成验证；80% 分位时延相对 EPVerifier 最多快 7 倍，相对 Tulkun 最多快 2 倍。系统开销也很低：SA 的 CPU 占用始终不超过 0.3%，峰值内存 26 MB。真实 500-switch fat-tree 部署里，Atlas 做 loop-freedom 和策略验证分别是 0.62 秒与 0.58 秒，而 EPVerifier 对应是 10.25 秒和 9.54 秒。整体证据对可扩展性主张是有力的，不过 blackhole-freedom 更多是通过模型构造来论证，缺少单独 benchmark。

## 创新性与影响

Atlas 的新意主要是架构层面的。APKeep、Flash、EPVerifier 关注的是怎样把 centralized incremental verification 做得更快；Tulkun 证明分布式方向可行，但仍绕不开昂贵的 planner。Atlas 则用层次化本地模型和按任务拼装的中心摘要，把 distributed DPV 做成一套可以落地的系统。这会让它成为生产 NMS 和后续 verifier 设计里很自然的参考点。

## 局限性

Atlas 很依赖合理的 region partition，而这一步仍由管理员决定。它当前也主要覆盖普通 forwarding rule，NAT 和 ACL 被留到 future work。再者，Atlas 依赖基于 JDD 的 BDD，而作者自己也承认这可能成为下一步瓶颈；真实部署中的 SA 还是跑在交换机外部 VM 上，而不是直接嵌入交换机软件栈。

## 相关工作

- _Zhang et al. (NSDI '20)_ - APKeep 通过合并 equivalence classes 去延展 centralized verifier 的规模上限，而 Atlas 直接把模型维护和验证执行拆到层次化分布式架构里。
- _Guo et al. (SIGCOMM '22)_ - Flash 主要解决的是 centralized verification 在 update storm 下的吞吐问题，Atlas 则认为在大规模网络中，这些优化之后仍然存在单点架构瓶颈。
- _Zhao et al. (NSDI '24)_ - EPVerifier 用 edge predicate 提速增量验证，但整网状态依旧由一个中心持有；Atlas 改成让 switch、region 和 center 三层各自持有摘要状态。
- _Xiang et al. (SIGCOMM '23)_ - Tulkun 把验证进一步下推到设备端，不过它依赖昂贵的 planner；Atlas 通过层次化摘要规避了这一步预计算。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "Pyrrha: Congestion-Root-Based Flow Control to Eliminate Head-of-Line Blocking in Datacenter"
oneline: "Pyrrha 按 congestion root 隔离并暂停真正喂给该 root 的流，在不做 per-flow queue 的前提下消除 FC 引入的 HOL blocking。"
authors:
  - "Kexin Liu"
  - "Zhaochen Zhang"
  - "Chang Liu"
  - "Yizhi Wang"
  - "Vamsi Addanki"
  - "Stefan Schmid"
  - "Qingyue Wang"
  - "Wei Chen"
  - "Xiaoliang Wang"
  - "Jiaqi Zheng"
  - "Wenhao Sun"
  - "Tao Wu"
  - "Ke Meng"
  - "Fei Chen"
  - "Weiguang Wang"
  - "Bingyang Liu"
  - "Wanchun Dou"
  - "Guihai Chen"
  - "Chen Tian"
affiliations:
  - "Nanjing University"
  - "TU Berlin"
  - "Huawei, China"
conference: nsdi-2025
code_url: "https://github.com/NASA-NJU/Pyrrha"
tags:
  - networking
  - datacenter
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pyrrha 认为，hop-by-hop flow control 的隔离粒度不该是端口、目的地址或哈希桶，而该是 congestion root。每台交换机维护下游 congestion root 快照，预测一个到达的数据包后续会经过哪些 root，再把它放入对应的 isolation queue。这样网络只会暂停真正造成该 root 拥塞的流，从而在不做 per-flow queue 的前提下消除 flow control 自身带来的 HOL blocking。

## 问题背景

论文抓住的是现代 datacenter 里的一个时序失配。链路带宽持续上升，buffer 却没有同步扩张，而 incast、web search、分布式训练这类工作负载会制造极短但极猛的突发。端到端 congestion control 必须等拥塞信号回到 sender 之后才能调速，通常至少要一个 RTT，稳定下来往往还要多个 RTT。对于 100 Gbps 乃至更高带宽的 fabric 来说，这意味着 sender 还没来得及收敛，网络里就已经注入了大量流量。

per-hop flow control 的反应更快，但常见设计过于粗粒度。PFC 会在下游队列超过阈值时暂停上游队列，保护 bottleneck 处的 buffer；问题是，它会把“共享这个队列的流”和“真正经过 bottleneck 的流”混在一起处理。结果就是 HOL blocking：vulnerable flow 甚至 background flow 会因为别人造成的拥塞而被误暂停。最直接的修复是 per-flow queue，但论文指出这在交换机上不可扩展，因为单个端口可能同时看到成千上万条并发流。此前的折中方案，例如按 destination 隔离，或者像 BFC 那样用有限队列池做哈希映射，虽然能降低状态量，却仍会把无关流混在一起，因此无法彻底消除 HOL blocking。

## 核心洞察

Pyrrha 的核心论点是，正确的隔离单位是 congestion root，也就是一棵 congestion tree 中最下游、真正导致拥塞的那个 hotspot。只要 flow control 暂停的恰好是“会经过某个 root 的流”，那么被暂停的集合就和真正对该 root 负责的流集合一致，innocent flows 就不会被连坐。论文进一步声称，这还是最小的正确粒度：任何比 congestion-root isolation 使用更少队列的方案，在一般情况下都无法避免 HOL blocking。

这个洞察成立，是因为 hop-by-hop backpressure 天然会形成 congestion tree。只要 root 被识别出来，上游交换机就不必等数据包真的到达 bottleneck，便可以根据“该包接下来会遇到哪些 root”提前分流，并在多个 hop 之前就把正确的流量压回去。换句话说，Pyrrha 试图用一种拓扑感知的隔离方式，把 per-hop flow control 从“粗暴但迅速”提升为“足够精确，因此能与 end-to-end congestion control 分工协作”。

## 设计

Pyrrha 的设计由三个紧密耦合的机制组成。第一步是 congestion root identification。某个输出端口的默认 output queue 超过暂停阈值时，它可以先自我提名为 root；随后再通过分布式 merge 过程修正判断。如果上游 hotspot 收到来自下游候选 root 的 `PAUSE`，并发现自己的部分流也会经过那个下游端口，它就知道自己只是 false-positive root。于是它为下游 root 新建队列，向更上游发送 `MERGE`，并把旧队列置为 soft-merging，让已经入队的包安全排空。

第二步是 congested flow identification，而且是在数据包到达时完成，而不是等它走到 bottleneck 再判断。每台交换机维护下游 congestion-root table，并据此判断一个到达的包是否属于某棵 congestion tree。前提是交换机能推导这个包的 onward path。论文假设路由满足这一点，例如 source routing，或已知哈希函数与 seed 的 hash-based ECMP。交换机用这些信息重建后续路径，再与 root table 匹配；若路径会经过某个 root，就把该包标记为属于该 root，否则继续走普通路径。

第三步是用 Hierarchical Isolation Queues 处理多 root、tree overlap 与 root 迁移。IQ 会按对应 root 与当前交换机的拓扑距离分层组织。若一个包后续会经过多个 root，它必须按从近到远的顺序依次穿过这些 IQ，最后才能进入普通 OQ。这样做的结果是：只有当所有相关 root 都发送了 `RESUME`，这个包才会真正被转发。这个层次化结构同时解决了两类难题，一是多个 congestion tree 交织时如何避免控制语义互相干扰，二是 root 合并或上移时如何保持 in-order delivery。论文还强调，普通 OQ 不会进入 pause 路径，这也是它规避 cyclic buffer dependency 的关键不变量之一。

## 实验评估

评估由 Tofino2 原型和 NS-3 模拟两部分组成。硬件实现约 2.5k 行 P4 加 2k 行 Python；在一个代表性的 `k=36` fat-tree、11,664 hosts 上，论文报告 Pyrrha 约消耗 11 MB 交换机内存。100 Gbps leaf-spine testbed 上的结果说明，这一套机制不只是理论构想：在 incast-mix 场景里，Pyrrha 把 vulnerable flow 吞吐提升到 66.7 Gbps，同时保持 incast 聚合吞吐在 100 Gbps，总网络吞吐比 PFC 高 26.7 Gbps。

更完整的证据来自模拟。论文在 160-host Clos 和 1024-host fat-tree 上，用 Memcached、Web Server、Web Search、incast-mix、多 root 的 load imbalance，以及 MoE 风格的周期性 all-to-all 流量评估 Pyrrha，并与 PFC、BFC 对比，同时考察与 DCQCN、HPCC、TIMELY 的协同。综合这些场景，Pyrrha 让 uncongested flows 的平均 FCT 降低 42.8%-98.2%，99th-tail latency 降低 1.6x-215x，而且不会损害 congested flows 的吞吐。由于它能更早把压力往源侧推，而不是让 root 处长期堆队，最大 buffer occupancy 还能下降 1.8x-6.2x。在 collided-phase 的 MoE 工作负载上，把 Pyrrha 加到 DCQCN 之上，相比 DCQCN+PFC 还能带来 1.46x 的 tail-latency 改善。整体上，这些结果基本支撑了论文的中心论断，不过大多数证据仍来自受控模拟，而非生产部署。

## 创新性与影响

相对于 BFC，Pyrrha 不接受“有限队列池 + 哈希碰撞”带来的残余误伤，而是直接论证只有 congestion-root isolation 才能在可扩展的前提下把 HOL blocking 清干净。相对于 Floodgate 这种面向 last-hop incast 的 per-destination 方案，Pyrrha 处理的是任意 congestion tree。相对于 HPCC 这类 end-to-end 机制，Pyrrha 改变的是控制层次：它控制的是已经进入网络的包，而且工作在 sub-RTT 时间尺度上，而 sender 侧 CC 继续负责 persistent congestion 与 fairness。

因此，这篇论文的贡献不只是“又一个 queue 管理技巧”。它把形式化的隔离粒度论证、分布式 root 识别协议，以及 programmable switch 上的可运行原型放到了一起。即便未来工业界不完全照搬 Pyrrha，congestion root 这个抽象本身也很可能会成为设计 per-hop FC 与 end-to-end CC 分工边界时的一个长期参考点。

## 局限性

Pyrrha 依赖交换机能够确定数据包的下游路径。这对 source routing 和可预测的 hash-based load balancing 比较自然，但对高度动态的 adaptive routing 就没有那么直接。论文展示了它与 DRILL 在 destination collision 场景下的互补性，但并没有给出对所有动态选路机制都通用的整合方案。

它最强的可扩展性叙事也依赖当前 Tofino2 并不原生提供的能力。原型是用 single-tier queues 去模拟 HIQ，因此部分队列管理成本高于论文理想中的体系结构。论文还默认每个端口上并发的 congestion root 数量通常不大；如果队列资源不够，Pyrrha 会退回到哈希分配，从而牺牲一部分隔离精度。最后，评估虽然覆盖面广，但仍主要是合成负载；论文也承认，在极端病态场景下，系统仍可能需要丢包并借助 IRN 一类机制恢复，而不是完全依赖无损的 hop-by-hop flow control。

## 相关工作

- _Goyal et al. (NSDI '22)_ - BFC 把流哈希到有限队列池里以缓解 HOL blocking，而 Pyrrha 认为 congestion-root isolation 才是能彻底消除 HOL blocking 的最小粒度。
- _Liu et al. (CoNEXT '21)_ - Floodgate 用 per-destination window 隔离 last-hop incast；Pyrrha 则面向任意 congestion tree，并避免维护 destination 粒度的控制状态。
- _Li et al. (SIGCOMM '19)_ - HPCC 用 in-band telemetry 做端到端速率控制，而 Pyrrha 对已经注入网络的数据包执行 hop-by-hop 的拥塞隔离。
- _Cho et al. (SIGCOMM '17)_ - ExpressPass 通过预先分配 transmission credit 做主动控制，Pyrrha 则在网络内部 root 出现后再做细粒度反应，并把持续速率控制留给 end host。

## 我的笔记

<!-- 留空；由人工补充 -->

---
title: "Suppressing BGP Zombies with Route Status Transparency"
oneline: "RoST 把每个接口的路由状态签名后公开，并在 BGP 通告里携带逐跳 RouteID，让 AS 不必依赖 key rollover 也能识别被压制的撤回。"
authors:
  - "Yosef Edery Anahory"
  - "Jie Kong"
  - "Nicholas Scaglione"
  - "Justin Furuness"
  - "Hemi Leibowitz"
  - "Amir Herzberg"
  - "Bing Wang"
  - "Yossi Gilad"
affiliations:
  - "School of Computer Science and Engineering, The Hebrew University of Jerusalem, Jerusalem, Israel"
  - "School of Computing, University of Connecticut, Storrs, CT"
  - "Faculty of Computer Science, The College of Management Academic Studies, Rishon LeZion, Israel"
conference: nsdi-2025
tags:
  - networking
  - security
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

RoST 瞄准的是 BGP 安全里一个常被忽略的缺口：一条路由即使来源和路径都合法，也可能因为某个 AS 压制了撤回而变成过期路由。它通过签名的逐接口路由状态向量和写入 BGP 的逐跳 RouteID 链，让下游 AS 能在一个批处理周期内识别 zombie route，而不必先等 BGPsec 普及。

## 问题背景

论文指出，origin validation 和 path authentication 仍然没有给 BGP 提供“新鲜度”语义。一条路由的 origin 可能正确、AS-path 也可能真实，但它实际上已经不可用，因为上游某个 AS 早已撤回了它。如果中间 AS 没有继续传播显式 withdrawal，或者压制了由替代通告引发的隐式 withdrawal，下游 AS 就会继续以为旧路径还活着。作者把这类“历史上合法、当前却失效”的路径称为 zombie routes。

这个问题并不只是控制平面里的整洁性问题。Zombie route 可能把流量送到一个已经没有目的前缀可达性的邻居，从而形成黑洞；也可能让 AS 误以为自己走的是更短或更便宜的策略路径，但下游实际上会沿着别的方式转发；在某些情况下还会造成 routing loop。论文引用既有测量工作说明 zombie outbreak 是日常现象，并提到大型 provider 内部故障一旦没有正确发出 withdrawal，就会把影响扩散到大量外部网络。

现有防线并没有真正覆盖这一缺口。RPKI 只解决 origin，BGPsec 一类机制解决 path authenticity，却不回答“这条路径现在是否仍然有效”。先前主要的解决思路是 key rollover，但这要求 route authentication 已经部署，而且需要重复完成发新证书、撤销旧证书、刷新所有路由等高成本运维工作。RoST 的定位，就是把“路径是否真实”和“路径是否仍然活着”这两件事拆开处理。

## 核心洞察

这篇论文的核心洞察是：只要每个转发路由的接口都把自己当前导出的路由状态透明化，freshness 就可以被逐跳验证。RoST 不去依赖“没有看到 withdrawal”这种间接信号，而是让每个采用者明确发布自己当前向每个邻居导出的路由状态。下游 AS 如果后来收到一条 BGP announcement，而其中携带的逐跳标识与这些公开状态不一致，就能定位出链路上的某一跳已经发生了撤回或替代更新。

RoST 把同一条路由的两个视图绑定在一起：一个是存放在 repository 中、由 AS 签名的透明控制平面记录；另一个是随着 BGP announcement 一起传播的紧凑 RouteID 序列。验证方逐接口比对这两者。如果任何一跳已经把该路由标成 withdrawn，或者同一前缀已经出现了更新的 RouteID，那么当前收到的通告就是 stale 的。这样一来，freshness 被变成了一个可验证属性，而且它与 path authentication 正交，可以叠加在 vanilla BGP 或未来的安全扩展之上。

## 设计

每个采用 RoST 的 AS 都运行一个独立的 RoST agent，而不是修改路由器内核。Agent 会为本地到每个邻居的接口 `(x, y)` 维护一个 Route Status Vector，也就是 RSV。每个 RSV entry 保存一个 prefix、一个 `RouteID = (BatchID, PathID)`，以及一个布尔状态位。`BatchID` 标识报告周期，`PathID` 统计这个周期内该前缀发生了多少次路由变化，因此更新突发会被 batch 吸收，而不会逼着系统维护一个不断增长的全局计数器。

每个 batch 结束时，agent 只发布这一周期内变更过的条目，也就是 `ΔRSV-Out`。为了让这份 delta 可验证，agent 会对该接口的完整状态建立 Merkle tree，并用 AS 的 RPKI 私钥对 batch counter、接口二元组和 Merkle root 做签名。Repository 存储这些更新，而订阅方只需要拉取自己当前最佳路由涉及到的接口和前缀；repository 返回对应的 `ΔRSV-In` 和 inclusion proof 供验证。

RoST 还扩展了 BGP announcement，在 transitive extended community attribute 中携带一个 RouteID 序列。当路由器导出一条路由时，它的 agent 会把当前接口的 RouteID prepend 到这个序列里再转发。假设 AS `w` 正在使用 `x-y-z` 这条路径到达某个前缀，那么它的 agent 就会跟踪 `z→y`、`y→x` 和 `x→w` 这些接口，并把 BGP update 里携带的 RouteID 与 repository 中取回的 RSV 数据逐跳对比。若状态缺失，就先标成 pending 并补订阅；若某一跳已经 withdrawn，或者 repository 中同一前缀在该接口上出现了更新的 RouteID，那么该路由就是 invalid，agent 会让路由器撤销它或切到替代路径。论文也给出了务实的落地方式：利用现有 Cisco 命令做 BGP logging、extended community 注入和路由删除。

## 实验评估

这篇论文的评估主要是 overhead 分析和 partial adoption 仿真，而不是在真实 Internet 上部署。作者使用六个月份、55 个 RIPE RIS vantage point 的 RIB snapshot 与 update trace 做估算。第一个定量结论是，RoST 给 BGP 报文增加的负担很小：在去掉 AS-path prepending 之后，平均路径长度是 3.86 跳，因此每跳携带一个 7-byte RouteID 后，一条 announcement 平均只增加大约 27 字节。

存储开销对 agent 来说比较温和，但对 repository 来说不算小。在一个保守的 worst-case 模型里，作者假设全网有 100 万个 IPv4 prefix 和 25 万个 IPv6 prefix，那么单个完整 `RSV-Out` 约为 16.83 MiB。再结合观测到的平均每个 AS 有 6.43 个接口，一个 agent 大约需要 106.76 MiB 的 `RSV-Out` 状态；用于跟踪最佳路由沿途接口的 `RSV-In` 工作集约为 65 MiB。Repository 需要存储所有 `RSV-Out` 和订阅相关状态，在作者的 worst-case 估算下总规模约为 8.1 TiB。

带宽开销呈现出预期的不对称性。以 5 分钟 batch 为例，拥有 1 到 10 个接口的 AS 平均只需约 1.01 Kbps 上传带宽；即使落在最大接口桶里的 AS，平均也只是 122.13 Kbps。向 repository 发起订阅请求的平均成本只有 0.21 Kbps，但因为每个返回条目都带有 Merkle proof，agent 接收 `ΔRSV-In` 的平均入站带宽会上升到约 106.97 Kbps。Repository 端把这些响应聚合起来，在论文的 worst-case 估算下最高可达 12.63 Gbps。

最有政策含义的结果来自 partial adoption 仿真。作者在 CAIDA 2025 年 1 月的 AS-level topology 上模拟了 Tier-1 AS 压制 withdrawal 的场景，发现随着采用 RoST 的 AS 比例提升，zombie AS 的比例会单调下降。这个收益在远未达到全面部署时就已经出现，而且还有外溢效应：一旦某个 adopter 识别并过滤了 zombie route，它也不会再把这条 stale 路由继续导出给其他 AS。

## 创新性与影响

RoST 的真正新意，在于它把 freshness 当成一等路由状态来处理，而不是把它视作 path authentication 的附属品。既有 BGP 安全工作更多关注“谁可以宣告这个前缀”以及“AS-path 是否被伪造”。RoST 提出的是另一个问题：即便这条路径曾经真实，它现在是否仍然在所有转发它的 hop 上保持 active？为此，论文给出的不是一份测量报告，也不是一条运维建议，而是一套新机制：签名的逐接口路由状态、批量透明更新，以及逐跳 RouteID 链。

这让论文同时对研究者和运营者都有价值。对研究者来说，它填补了 interdomain routing security 里“freshness”这块长期空白；对运营者来说，它提供了一条不必等待 BGPsec 全面部署、也不必靠高频 key rollover 的增量落地路径。

## 局限性

RoST 并没有解决整个 interdomain attack surface。作者明确排除了路径伪造和路径篡改攻击，这些场景仍然需要 BGPsec 或 BGP-iSec 一类 path-authentication 方案。RoST 还依赖 RPKI 风格的密钥来给 route-status report 做签名，因此它并不是一个完全无依赖的附加层。

实际部署中，它也确实引入了新的基础设施。Agent 必须与一个或多个 repository 保持同步、持续监控 BGP 状态，并且正确地下发路由器控制命令。论文讨论了多 repository 甚至 BFT 同步的可能性，但这些都还只是部署设想而非被评估的组件，而且 repository 在 worst-case 下的出站带宽也不算低。

最后，论文给出的实证证据仍然是间接的。它展示了 overhead 的可行性，也通过模拟说明 partial adoption 有价值，但没有真实网络部署，也没有评估 repository 延迟、agent 控制失误、或者误报漏报会如何影响实际运营。再加上 RoST 以 batch 为节奏推进，因此它能把暴露窗口压到“分钟级”，却不是即时收敛。

## 相关工作

- _Fontugne et al. (PAM '19)_ - `BGP Zombies` 证明了 stuck route 在真实网络中既常见又有害，而 `RoST` 把这种现象从测量结论推进成了可执行的防护机制。
- _Ongkanchana et al. (ANRW '21)_ - `Hunting BGP Zombies in the Wild` 扩展了对 zombie route 的观测视角，而 `RoST` 关注的是如何用可认证的数据面外信息来检测并抑制它们。
- _Cohen et al. (SIGCOMM '16)_ - `Path-End Validation` 加强了 BGP path authenticity，但它并不能告诉路由器一条曾经有效的路径是否已经在下游某一跳被撤回。
- _Morris et al. (NDSS '24)_ - `BGP-iSec` 主要解决 post-ROV 场景下的路径攻击，而 `RoST` 与之正交，专门补上 withdrawal suppression 导致的 freshness 问题。

## 我的笔记

<!-- 留空；由人工补充 -->

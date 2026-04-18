---
title: "Rajomon: Decentralized and Coordinated Overload Control for Latency-Sensitive Microservices"
oneline: "Rajomon 让请求携带 token、让接口传播价格，把过载路径的节流前推到客户端，并让并行分支一致丢弃同一批注定超时的请求。"
authors:
  - "Jiali Xing"
  - "Akis Giannoukos"
  - "Paul Loh"
  - "Shuyue Wang"
  - "Justin Qiu"
  - "Henri Maxime Demoulin"
  - "Konstantinos Kallas"
  - "Benjamin C. Lee"
affiliations:
  - "University of Pennsylvania, USA"
  - "DBOS, Inc, USA"
  - "University of California, Los Angeles, USA"
conference: nsdi-2025
code_url: "https://github.com/pennsail/rajomon"
tags:
  - datacenter
  - scheduling
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Rajomon 把微服务过载控制改写成一套分布式“市场”机制。请求携带 token，接口回传 price，拥塞路径会在更多工作发起前就变得“昂贵”。这样系统既能把限流前推到客户端，也能让扇出分支一致地丢弃同一批低优先级请求。

## 问题背景

论文讨论的是传统过载控制在大规模微服务调用图里最容易失灵的场景。微服务系统中，没有单个组件能看到完整调用图，过载往往从深层依赖开始，再随着队列增长一路向上游传播；同时，共享服务又常常 multiplex 多个成本差异很大的 API。论文引用 Alibaba trace 指出，宽扇出和多接口复用都很常见，所以只做单机本地丢弃，或者只在前端限流，都太粗糙。

现有方案各自缺一块关键能力。Dagor 是去中心化的，但只做成对协调，所以请求可能已经穿过多个层级、浪费了不少算力，才在热点附近被丢掉。Breakwater 只在前端边界做客户端限流，无法及时感知下游热点。TopFull 能按 API 粒度控制，但它是中心化的，而且反应较慢。结果就是计算被浪费，并在流量激增时恢复很差。

## 核心洞察

Rajomon 的核心主张是，端到端微服务过载控制并不一定需要中心协调器，只要每个请求携带一种可传播的“预算”，每个接口暴露一种可传播的“拥塞信号”即可。Rajomon 把前者实现成 token，把后者实现成 price。

Token 让同一个原始请求派生出的所有分支都能共享优先级信息，所以扇出路径上的多个服务可以一致地丢弃同一批低 token 工作，而不是各丢各的、继续浪费算力。Price 则把接口的稀缺程度一路向上游传递，让调用方在请求进入长链路之前就先减速。靠这两个元数据字段，Rajomon 同时获得了去中心化、跨图协调和接口粒度控制。

## 设计

Rajomon 在每个节点上运行本地 controller，同时扮演 client-side 和 server-side 两种角色。Client-side controller 生成 token，检查当前 token 是否足够支付目标接口的 price；不够就在本地 rate limit，足够就附带 token 发出请求。论文使用 Poisson process 生成 token，避免所有客户端同步补充预算形成突发；同时，每个请求随机花费一个均匀分布的 token 数量，让 price 上升时 admission 变化更平滑。

Server-side controller 负责 admission control 和 price update。服务收到请求后，把请求携带的 token 与目标接口的 price 比较；token 不足就丢弃，足够则放行，并把同一份 token 继续带到下游 RPC。接口的本地 price 按 queueing delay 调整：超过阈值时按过载严重程度上涨，降到阈值一半以下时再缓慢回落。每个接口维护独立价格，因此 multiplexed service 不必共享一个粗糙的 admission level。

跨调用图的协调来自反向 price propagation。服务把自己的本地 price 和下游 price 结合起来，再把更新后的结果 piggyback 在响应里返回上游。为了控制开销，Rajomon 采用 lazy propagation，例如只在 20% 的响应里携带 price。对于扇出路径，论文把总 price 定义为“本地 price 加上相关下游 price 的最大值”，而不是求和。这样可以快速指向最热瓶颈，同时避免在多分支之间拆分 token 预算。原型约 948 行 Go 代码，以 gRPC interceptor 实现。

## 实验评估

评估覆盖了较小的学术 benchmark 和更大的图结构工作负载。Rajomon 部署在 Kubernetes 和 CloudLab 上，对比对象是 Dagor、Breakwater、Breakwaterd 和 TopFull。这些 baseline 都被重写成了 Go 的 gRPC library，并用 Bayesian optimization 调参，所以比较相对可信。

在单接口过载实验里，Rajomon 能把 Search Hotel 的 tail latency 控制在约 200 ms 以内，并在重载下维持约 3k 的 goodput；当输入负载超过 12k RPS 时，baseline 的 goodput 不到它的一半，而 tail latency 约为它的 5 倍。对 Compose Post，Rajomon 在重载下仍把 goodput 保持在 2k RPS 以上，而其他方法会跌到约 500 RPS。按论文定义的 recovery metric，Rajomon 是唯一能稳定保持 sub-second recovery 的方法，不过细粒度时序图也显示，由于 price 采用懒传播，从“服务端先丢请求”过渡到“客户端主导限流”仍大约需要 2 秒。

多接口结果最能支撑论文主张。Rajomon 可以让不同 API 各自贴近自己的可持续工作点，而不是被迫共享一个已经拥塞的队列。在 Social Network 的并发请求中，它让所有接口都保持在各自 SLO 内，同时把 Compose Post 和 Read Home Timeline 稳定在约 2.5k RPS，并让 Read User Timeline 提升到 5k RPS。论文汇总称，在高挑战负载下，Rajomon 相对已有工作将 goodput 提高 117% 到 266%，将延迟降低 33% 到 46%；在混合接口场景下，goodput 提升 45% 到 245%，延迟下降 78% 到 94%。这组实验基本支持其核心论点，只是仍属于短时实验室验证，而非生产环境证据。

## 创新性与影响

Rajomon 的贡献在于，它用一条很紧凑的元数据路径同时实现了去中心化、跨图协调和接口粒度隔离。它既不是纯本地 AQM，也不是中心化的学习式控制器，因此很适合作为 service mesh 或 RPC middleware 里的现实设计点，用来实现不依赖全局遥测的亚秒级过载处理。

## 局限性

Rajomon 假设客户端可信，因此如果要防御伪造 token 或策略性囤积 token 的行为，还需要额外的 server-side validation，而这部分被留到了未来工作。实验也主要假设调用路径基本确定，对于动态调用路径，论文只给出了按期望值定价的扩展思路。

控制律本身也带有启发式。把总 price 设成“最大下游 price”虽然简单高效，但对所有扇出模式都未必最优，而且论文没有给出完整 token-price 控制环的严格稳定性证明。再加上多数工作负载仍是学术 benchmark 或 trace replay，Rajomon 在部分部署或更混乱的生产流量下会怎样表现，仍是开放问题。

## 相关工作

- _Zhou et al. (SoCC '18)_ - Dagor 是去中心化的，并通过 admission level 在热点前一跳丢弃请求，但它只做成对协调，无法把节流一路前推到客户端。
- _Cho et al. (OSDI '20)_ - Breakwater 为快速 RPC 过载控制引入了客户端可见的 credit，而 Rajomon 把这类思想扩展到完整微服务图，并加入按接口维护的状态和下游反馈。
- _Park et al. (SIGCOMM '24)_ - TopFull 也按 API 粒度思考问题，但它依赖全局遥测和中心化 reinforcement learning；Rajomon 则依靠本地 controller 和 piggyback 的元数据传播。

## 我的笔记

<!-- 留空；由人工补充 -->

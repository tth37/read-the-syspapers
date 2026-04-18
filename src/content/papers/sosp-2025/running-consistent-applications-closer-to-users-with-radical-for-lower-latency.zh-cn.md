---
title: "Running Consistent Applications Closer to Users with Radical for Lower Latency"
oneline: "Radical把数据留在主数据中心，却让确定性serverless处理器贴近用户运行，并用一次与执行重叠的LVI往返完成缓存校验与写入兜底。"
authors:
  - "Nicolaas Kaashoek"
  - "Oleg A. Golev"
  - "Austin T. Li"
  - "Amit Levy"
  - "Wyatt Lloyd"
affiliations:
  - "Princeton University"
  - "Sentient Foundation"
  - "Cornell University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764831"
tags:
  - serverless
  - caching
  - transactions
  - fault-tolerance
category: datacenter-scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Radical把权威存储留在单个主数据中心，却允许确定性的serverless处理器在靠近用户的位置对最终一致缓存做推测执行。它的Lock-Validate-WriteIntent（LVI）协议把校验、加锁和恢复准备压缩到一次与执行重叠的往返里，因此在验证成功时，系统能拿到大部分“把计算搬近用户”带来的延迟收益，同时继续提供linearizability。

## 问题背景

这篇论文讨论的是一个越来越常见的部署错位。云厂商正在不断增加区域数据中心、边缘PoP和本地集群，因此计算理论上可以离用户更近。但一大类面向用户的应用，例如社交网络、预订系统和论坛，仍然需要强一致性。如果它们把存储留在单个主数据中心，那么每次在近用户位置执行请求时，都要为每一次存储访问支付WAN延迟；如果它们改用跨地域强一致副本，那么每次读写又会因为远距离副本协调而变慢。

作者认为，现有方案正是在这个场景里浪费了最多的延迟预算。一个用户请求通常会包含多次存储访问，因此中心化部署会把WAN代价放大多次。强一致的geo-replicated存储也解决不了这个问题，因为PRAM下界仍然要求读写延迟反映最远副本之间的距离。结果是，哪怕计算基础设施已经向外扩展，应用在实际效果上仍然被它的数据“绑”在原地。

## 核心洞察

论文的核心主张是：只要系统能在处理器真正运行前知道这次请求的read/write set，那么一个预执行的协调消息就足以完成缓存状态校验、相关键加锁，以及对推测写的恢复准备；处理器本身则可以同时在近用户位置本地执行。

这个观察成立的前提有两个。第一，处理器必须是确定性的；第二，运行时必须能截获所有存储访问。为此，Radical选择serverless function作为基本执行单元：它们天然无状态，存储操作显式暴露，而且可以编译到一个确定性的WebAssembly子集。论文真正新的地方不只是“推测执行”，而是“只用一次与执行重叠的控制往返，就能安全发布强一致结果”的推测执行。

## 设计

Radical在每个近用户位置放置一个运行时和缓存，并在靠近主数据库的地方保留一个near-storage站点。函数`f`注册时，Radical的分析器会导出一个伴随函数`f_rw`，用来计算这次调用会精确读取和写入哪些键。分析器基于symbolic execution和dependency analysis处理serverless处理器。如果后续访问依赖前面的读取结果，那么`f_rw`也可以先在本地缓存上执行这些前置读；若缓存是旧的，后面的validation会失败，推测结果本来也会被丢弃。

在一次调用开始时，近用户运行时先运行`f_rw`，然后并行做两件事：一边让`f`在本地缓存上推测执行，一边把read/write set和缓存中的版本号打包成LVI请求发往near-storage位置。LVI server收到请求后，会按键获取read lock或write lock，并按字典序排序来避免死锁；随后它比较缓存版本与主存储版本是否一致。如果任何项缺失或过期，推测路径立即作废，near-storage位置直接执行该处理器，返回权威结果，同时把新值带回去修复缓存。

如果validation成功，Radical还必须在不增加第二次同步往返的前提下处理推测写。它的办法是write intent。near-storage位置在处理LVI请求时，会为可能写入的执行创建一个intent并启动定时器。一旦近用户执行完成且LVI响应确认校验成功，Radical就可以先把推测结果返回给客户端；真正的写入随后通过异步followup发送，而锁会一直保持到这些写入被应用为止。

让这条路径正确的关键是恢复机制。如果followup因为近用户节点故障或消息丢失而永远不到，定时器触发后，near-storage位置会用同样的输入重新、确定性地执行该函数。由于最初的LVI请求已经持有read lock，重放会看到与原执行相同的存储状态；由于函数运行在禁止计时器和随机数的受限WebAssembly环境里，重放会生成相同的写集合。论文还要求任何外部服务交互都必须是幂等的，或者能提供at-most-once语义。validation、锁、write intent和确定性重放一起构成了Radical保证linearizability的核心机制。

## 实验评估

原型刻意构建在现有基础设施上，而不是定制平台之上：近用户执行使用AWS Lambda，LVI server运行在EC2上，主存储使用DynamoDB，缓存也同样使用DynamoDB，以便把测得的差异集中在Radical协议本身，而不是“换了个更快缓存”的效果上。作者把5个真实应用移植成27个Rust-to-WASM的serverless函数，分析器成功处理了全部27个，其中3个需要论文提出的dependent-read优化。

主要实验聚焦在一个社交网络、一个酒店预订服务和一个论坛上，它们部署在5个AWS区域，而Virginia承载主数据。与“应用和主存储都放在Virginia”的基线相比，Radical把端到端中位延迟降低了28%-35%：酒店预订从270 ms降到194 ms，社交网络从234 ms降到154 ms，论坛从317 ms降到229 ms。若与一个只使用本地不一致存储的理想化下界相比，Radical仍然拿到了84%-89%的最大可能收益。更重要的是，这些收益在高偏斜负载下依然成立，因为LVI的validation成功率大约有95%。

按函数拆开的结果也和论文叙事一致。执行时间长于近用户到near-storage RTT的处理器受益最大，因为LVI往返大多被执行时间遮住了。那些只有13-18 ms、且包含写操作的短函数收益较小，但它们的延迟也只是比直接在near-storage执行高几个毫秒，而不是明显退化。整体来看，实验相当有说服力，不过它依然是一个AWS原型，比较对象是中心化部署和理想化下界，而不是某个真实geo-replicated强一致数据库的完整端到端实现。成本是主要代价：论文估算基础设施成本大约比基线高31%，另外validation失败的约5%请求还会触发一次near-storage侧的备用执行。

## 创新性与影响

这篇论文最接近的对比对象，不是另一个缓存系统，也不是另一个serverless runtime，而是像Spanner这样的geo-distributed存储系统，以及像Correctables这样的推测接口。Spanner及其同类系统把协调成本放在存储层里的每次操作上；Correctables允许应用先看到较弱、后看到较强的结果，但那个乐观值仍然来自存储协议本身。Radical则把关键优化边界抬到了应用运行时层：它用静态分析提前知道一次请求会碰到什么，用推测执行掩盖距离，再用write intent把耐久性推迟而不丢失正确性。

因此，这篇论文的系统贡献很明确。它提出的是一种新的机制，让linearizable应用不必重写底层数据库，也能更靠近用户运行。它很可能会被做边缘/云执行、stateful serverless平台以及广域事务处理的研究者引用。哪怕未来有人把DynamoDB或Lambda换成性能更好的组件，论文的核心思想依旧可迁移：不要让应用为每一次远端存储动作停下来等待，而是把一个精心组织过的一次性一致性往返，与确定性的应用执行重叠起来。

## 局限性

Radical并不是一种通用部署模型。它要求应用能够拆成独立的serverless函数，而且这些函数的read/write set要么可以静态推出，要么预测代价足够低。如果计算`f_rw`本身就很昂贵，那么这段分析时间会直接落在关键路径上；如果分析器根本推不出来，Radical就只能回退到near-storage执行，收益随之消失。

系统还依赖一些容易被低估的确定性与信任前提。处理器不能依赖计时器、随机数等环境性非确定性；外部服务必须提供幂等或at-most-once接口；开发者还必须同时信任near-user和near-storage位置，因为二者都会处理共享应用状态。最后，超低延迟函数的收益有限。论文明确指出，只有当处理器执行时间足以覆盖大约一次LVI往返时，Radical才最有吸引力；而复制版LVI server的讨论进一步给出了一个更实际的经验值，大约要到20 ms左右才更稳妥。

## 相关工作

- _Corbett et al. (OSDI '12)_ - Spanner通过跨副本协调为每次请求提供全局强一致，而Radical保留单主存储，并把一次协调往返与推测执行重叠起来。
- _Lloyd et al. (SOSP '11)_ - COPS通过因果一致性换取低延迟geo-replication，而Radical面向的是那些不能把一致性降到causal consistency的linearizable应用。
- _Jia and Witchel (SOSP '21)_ - Boki优化的是数据中心内部的stateful serverless存储，而Radical把serverless handler当成可分析的执行单元，用来解决广域低延迟强一致问题。
- _Guerraoui et al. (OSDI '16)_ - Correctables向应用暴露逐步增强的一致性结果，而Radical的目标是让一次预执行LVI请求就足以验证并提交一次推测执行。

## 我的笔记

<!-- 留空；由人工补充 -->

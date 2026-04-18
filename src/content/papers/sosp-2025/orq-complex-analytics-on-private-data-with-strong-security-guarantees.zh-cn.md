---
title: "Orq: Complex Analytics on Private Data with Strong Security Guarantees"
oneline: "Orq 把 oblivious join 与可分解聚合融合起来，让 MPC 在不泄露结果规模的前提下执行多路分析，避免二次级中间表。"
authors:
  - "Eli Baum"
  - "Sam Buxbaum"
  - "Nitin Mathai"
  - "Muhammad Faisal"
  - "Vasiliki Kalavri"
  - "Mayank Varia"
  - "John Liagouris"
affiliations:
  - "Boston University"
  - "UT Austin"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764833"
code_url: "https://github.com/CASP-Systems-BU/orq"
tags:
  - databases
  - security
  - pl-systems
category: storage-and-databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Orq 是一个面向 outsourced collaborative analytics 的 MPC query engine，核心目标是在不泄露中间结果规模的情况下执行复杂关系分析。它把 join 和可分解聚合融合到同一个 oblivious control flow 中，因此即便两侧输入都含有重复键，也不必显式物化完整 Cartesian product。配合协议无关的 oblivious operators 与向量化运行时，Orq 首次把完整 TPC-H benchmark 带到了纯 MPC 执行路径上。

## 问题背景

论文针对的是 secure analytics 中一个长期存在的瓶颈。在 outsourced MPC 场景里，多个数据拥有者把表 secret-share 给一小组互不串通的计算服务器，由这些服务器在看不到明文的前提下共同执行查询。为了保证隐私，系统不仅要隐藏输入和中间值，还要隐藏中间结果和最终结果的规模。这个要求让关系算子普遍变贵，而 join 最麻烦，因为一个完全 oblivious 的 join 为了掩盖真实匹配数，往往需要产生最坏情况下的 `n^2` 笛卡尔积；多路 join 叠加后，中间表还会继续级联膨胀。

现有工作对这个问题的处理都不够理想。一类系统坚持强安全，但接受 quadratic join 和代价很高的 bitonic sort；另一类系统为了性能泄露 join result size，或者把部分工作下放到 trusted compute、数据拥有者本地，或者依赖非常狭窄的 ownership 假设，例如每个参与方恰好贡献一张表、参与方数量很少等。可是在更一般的 outsourced setting 中，同一张逻辑表往往来自多个数据拥有者，而计算服务器始终见不到明文。论文认为，这恰恰是 secure analytics 最有价值的场景，却也是过去最难把复杂 join-heavy workload 做实用的场景。

## 核心洞察

Orq 最关键的判断是，真正困难的并不是“所有 join 都必须在 MPC 下执行”，而是那些中间结果规模无法被数据无关上界约束的 join。作者观察到，TPC-H 以及既有 MPC 文献里的多路分析查询，虽然中间可能包含 duplicate-key join，但它们的最终结果通常是聚合后的答案，其最坏规模仍可被输入大小的 `O(n)` 上界约束。只要最终聚合是 decomposable 的，并且 group-by key 只来自一个输入表，就可以在 join 之前先做 partial aggregation，在 join 过程中继续合并 partials，最后再做一次收尾聚合。

这会把执行策略从“先把所有匹配物化出来，再做聚合”改成“在保持 obliviousness 的同时边 join 边聚合”。一旦系统知道工作表大小从一开始就是可控的，就可以把 join 和 aggregation 融合到同一个 oblivious pipeline 里。这样一来，Orq 避免 quadratic intermediates 不是因为先泄露真实 join size 再裁剪，而是因为它把计算本身改写成了一个从最坏情况上就有界的过程。

## 设计

Orq 不是单个密码学算子，而是一个完整的 query engine。用户通过类似 Spark 或 Conclave 的 dataflow API 编写查询，Orq 再把执行计划编译成操作 secret-shared tables 的 MPC 程序。每张表都带有一个 secret-shared validity bit，用来表示某一行当前是否有效；这样系统就能在 worst-case 大小上运行各类算子，obliviously 失效掉无用行，并在最终输出前统一做 mask 和 shuffle。

第一层设计是通用 oblivious building blocks。Orq 为 tabular data 实现了 filter、deduplication、multiplexing、aggregation 和 sorting。它的 `TableSort` 不会对整张表反复重排，而是先从排序键列中提取 permutation，按从右到左的顺序组合这些 permutation，最后只对整表应用一次最终排列。针对不同位宽，系统分别使用 oblivious quicksort 与 radixsort，并把底层 shuffle primitives 泛化到不同 MPC 协议之上。

论文最核心的机制是 `Join-Agg`。在最基本的一对多 equality join 中，Orq 先把左右输入表拼成一个工作表，额外记录 origin marker，然后按 validity、join key 和来源排序，使得同一 key 的有效记录聚在一起，并让左表记录排在每个 group 的起点。接着系统标记 group boundary，再运行一个 aggregation network：其中一个内部函数负责把左侧 payload 列 copy 到匹配的右侧行，另一个负责传播有效性，用户给出的 aggregation 函数则在同一条 control flow 里对每个 key 计算结果。最后系统再按需要 trim 多余行，于是输出规模被约束在输入表规模内，而不是隐藏的真实 join cardinality。

这个框架可以通过很小的控制流改动推广到更多 join 类型。semi-join、anti-join 和各类 outer join 的主要区别，本质上只是“哪些行应该在何时被 invalidated”。theta-join 也可以支持，只要其中至少有一个 equality predicate 能给输出规模提供上界，其余条件就退化为 oblivious filter。对于双方都含 duplicate key 的 many-to-many join，Orq 通过 pre/post/final aggregation 分解来处理：先在一侧按 join key 做 multiplicity 或 partial sum 的 pre-aggregation，把 join key 变成唯一；然后执行基本 Join-Agg；最后按目标输出 key 做 post-aggregation。围绕这些算子，系统还实现了 columnar format、向量化 secure primitives、data-parallel worker threads，以及能批量摊销网络开销的通信层。重要的是，这整套 operators 只把底层 MPC primitives 当作 black box，因此同一引擎可以实例化在 ABY、Araki et al. 和 Fantastic Four 上，覆盖 semi-honest 与 malicious security。

## 实验评估

这篇论文的实验有说服力，因为它既评估了 end-to-end analytics，也评估了真正主导成本的底层算子。作者在 AWS `c7a.16xlarge` 上运行 Orq，测试了 31 个 workload：完整的 22 个 TPC-H queries，加上从既有 relational MPC 文献中收集的 9 个查询。在 TPC-H Scale Factor 1 下，查询已经要处理数百万行输入，最重的 Q21 最多要执行 12 次 sort。即便在 LAN 下的 malicious security 配置中，Q21 也能在 42 分钟内完成；其余来自 prior work 的查询都在 10 分钟以内。到了 WAN，RTT 增加 75 倍，端到端时间只增加了 1.2x 到 6.9x，这说明论文强调的 vectorization 和 message batching 确实对系统级性能有决定性作用。

更重要的是与现有系统的比较。对比 Secrecy 这个目前最接近、且同样强调 outsourced setting 与 no leakage 的开源系统，Orq 在最昂贵的 join 或 semi-join 查询上可实现 478x 到 760x 的延迟下降，在 group-by 或 distinct 为主的查询上也有 17x 到 42x 的提升，整体最高达到 827x。对比 SecretFlow-SCQL，尽管后者允许泄露 matching rows、还能利用 data owners 的 trusted compute，Orq 在 join 查询上仍快 1.1x 到 1.5x，在简单查询上领先更大。仅看 oblivious sorting，Orq 的 radixsort 最多比 SecretFlow 快 5.5x、比 MP-SPDZ 快 189x。扩展性部分则补全了故事：Orq 能在纯 MPC 下跑完整个 SF10 的 TPC-H，而默认 quicksort 在最优设置下可在约 70 多分钟内完成 5.37 亿个元素的排序。

## 创新性与影响

这篇论文的创新点并不只是“又做快了一种 sort”，也不只是“给 MPC 套了一层更整洁的接口”。它真正的新意在于把 workload 观察、fused join-aggregation 机制和一个围绕该机制设计的系统运行时整合在一起。过去很多工作默认认为，要把 relational MPC 做到大规模，要么接受 leakage，要么依赖 trusted compute，要么给 schema 和 ownership 加很强的限制。Orq 则证明：对于一大类实际存在的复杂分析，只要系统足够激进地利用 decomposable aggregation，就能在保持 fully oblivious 的前提下获得实用性能。

这对系统研究者和应用密码学研究者都很重要。对前者而言，Orq 让跨医院、跨公司、跨机构的 collaborative analytics 更接近真实可部署；这些场景往往不能接受中间结果规模泄露。对后者而言，Orq 提供了一套 protocol-agnostic 且开源的 operator design，使得未来无论是替换 MPC backend，还是把新的 secure analytics workload 接进来，都不必从零重写整个 query stack。

## 局限性

Orq 并不是 secure SQL 的通用解。它的高效路径局限于 acyclic conjunctive queries、一对多 joins，或那些后接可分解聚合且 group-by key 落在单侧输入上的 many-to-many joins。对于 cyclic joins，或者那些必须跨两张表共同形成聚合语义、无法被 decomposition 改写的查询，Orq 仍然要退回到 oblivious `O(n^2)` join。这个限制并不掩饰，但也意味着论文中的“complex analytics”范围很广，却并不覆盖全部 SQL。

系统层面也有实际代价。查询文本和 schema 默认是公开的，参与方必须事先就要执行的计算达成一致，因此 Orq 并不隐藏 workload shape。当前实现还不支持 fixed-point arithmetic 和 substring operations，用户也仍需手工把查询写成 Orq 的 dataflow API，而不是直接交给自动 SQL planner。最后，在大规模 malicious security 配置下，成本仍然不低：论文报告的 SF10 WAN 结果中，Q21 需要 18 小时，排序与 padding 仍是最主要的瓶颈。

## 相关工作

- _Liagouris et al. (NSDI '23)_ - Secrecy 是最接近的 outsourced relational MPC system，也同样强调无泄露；但它依赖 quadratic join 和 `O(n log^2 n)` bitonic sort，而 Orq 把支持范围内的 join-aggregation 工作负载降到了 `O(n log n)`。
- _Fang et al. (VLDB '24)_ - SecretFlow-SCQL 通过 peer-to-peer execution 和对 matching rows 的泄露来换取性能；Orq 则面向 outsourced setting，并把 intermediate sizes 也保密下来。
- _Bater et al. (PVLDB '18)_ - Shrinkwrap 明确提出了 cascading effect 问题，并通过 controlled leakage 来削弱它；Orq 的贡献是证明许多实际 workload 可以通过 fused join and aggregation 避免这种泄露。
- _Asharov et al. (CCS '23)_ - Secure Statistical Analysis on Multiple Datasets 研究了 secure join 和 group-by operators，但它面向更窄的协议设定，也没有提供 Orq 这种覆盖 many-to-many analytics 的端到端系统实现。

## 我的笔记

<!-- empty; left for the human reader -->

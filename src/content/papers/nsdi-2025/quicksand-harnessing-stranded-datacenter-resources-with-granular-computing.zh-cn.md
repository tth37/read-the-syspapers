---
title: "Quicksand: Harnessing Stranded Datacenter Resources with Granular Computing"
oneline: "Quicksand 把应用拆成 compute proclet 和 memory proclet，并持续保持它们足够小且可迁移，让机架能拼起零散 CPU 与 RAM，而不必承受透明 far memory 的黑盒代价。"
authors:
  - "Zhenyuan Ruan"
  - "Shihang Li"
  - "Kaiyan Fan"
  - "Seo Jin Park"
  - "Marcos K. Aguilera"
  - "Adam Belay"
  - "Malte Schwarzkopf"
affiliations:
  - "MIT CSAIL"
  - "Brown University"
  - "VMware Research by Broadcom"
  - "USC"
conference: nsdi-2025
category: memory-serverless-and-storage
code_url: "https://github.com/NSDI25-Quicksand/Quicksand"
tags:
  - datacenter
  - disaggregation
  - memory
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Quicksand 是一个面向机架规模的运行时，它把应用拆成 compute proclet、memory proclet，以及只在必要时才使用的 hybrid proclet。系统持续把这些 proclet 维持在可 split、merge、migrate 的毫秒级粒度上，因此能把 CPU-heavy 的计算放到有空闲 core 的机器上，把 memory-heavy 的状态放到有空闲 RAM 的机器上。它因此提供了一种软件化替代 transparent memory disaggregation 的路径，而且还能同时回收 stranded CPU。

## 问题背景

论文切入的是数据中心里一个很常见却很难彻底消掉的低效现象：应用需要的 CPU/内存比例，往往和单机硬件提供的比例不一致。一旦其中一种资源先耗尽，另一种就会被 stranded，于是运营者只能接受容量浪费，或者为了应对突发流量而做更保守的 overprovision。作者分析 Alibaba trace 后发现，即使在峰值时段，机器平均仍有 56% 的 CPU 和 10% 的内存处于空闲状态；即便假设系统能完美预知未来，并把 batch task 做理想化装箱，仍会剩下 14% idle CPU 和 3% idle memory，因为任务的需求比例与机器供给比例本来就不匹配。

现有办法各自缺一块。Transparent memory disaggregation 可以把远程 RAM 池化起来，但它不能回收 stranded CPU，而且它把 locality 完全藏到系统内部，应用无法知道某次访问到底是本地还是远程。当 compute intensity 较低时，这一点代价很大，因为一次远程访问就会变成无法预测、也难以主动 prefetch 的 stall。像 Nu 这样的 granular system 虽然暴露了 placement 和 migration，但它的执行单元仍把 compute 和 memory 绑在一起，因此没法把 CPU-heavy 的工作与 memory-heavy 的状态独立摆放；与此同时，开发者还得自己承担大量手工分解和维持粒度的工作。

所以问题并不只是“调度器不够聪明”。系统真正缺的是一种执行模型：它既要让 CPU 和内存以细粒度独立流动起来，又不能把复杂度完全推给应用作者。

## 核心洞察

Quicksand 最重要的命题是：要让资源真正具备 fungibility，不能只迁移传统 process 或 shard，而必须把资源消耗本身解耦开来。为此，Quicksand 引入了 resource proclet：主要消耗 CPU 的 compute proclet、主要消耗 RAM 的 memory proclet，以及只在 locality 值得时才使用的 hybrid proclet。

这个抽象成立的关键，在于 Quicksand 保持了远程访问的显式边界。Compute proclet 不能直接去解引用别的 proclet 的内存；它只能通过库提供的 API 去读写 memory proclet，或者在只读场景中利用 iterator 和 prefetch。这样一来，Quicksand 站在“纯本地执行”和“透明 far memory”之间：程序和库仍知道哪些数据可能是远程的，但 runtime 可以在高层抽象之下自动完成放置、迁移和粒度管理。

## 设计

开发者看到的是高层接口，而不是 proclet 细节。Quicksand 提供三类库：sharded data structures、batch computing，以及 stateless/stateful services。它们最终都会被落到同一套 auto-sharding layer 上。比如 `ShardedVector` 会被映射成按索引区间分片的一组 memory proclet；`ForAll` 这类 batch operator 会被映射成覆盖某段输入范围的一组 compute proclet；stateful service 则会被映射成成对出现的 compute proclet 和 memory proclet，并通过 client identifier 做 sticky routing。

数据路径保持显式。Memory proclet 封装 shard 状态，对外提供 `Read`、`Write` 和 iterator 风格访问；当其被 seal 成只读后，运行时就可以安全地做 prefetch。Compute proclet 负责执行 lambda，也可以绑定一个 range；split 时直接把 range 对半切开。Hybrid proclet 不是默认形态，而是由 memory proclet 显式提升而来，只在论文认为 locality 比灵活性更重要的场景中使用，例如原地排序。整个设计的关键不变量是：每个 proclet 都应该主要消耗一种资源，这样调度器才真的拥有独立摆放它们的自由。

控制路径则是“中心化元数据 + 本地缓存 + shard-specific policy”的组合。`AutoSharder` 通过 centralized mapping proclet 维护 sharding key range 到 proclet 的映射，客户端本地缓存这张表，失效后再回源刷新。每次路由完成后，具体 shard 类型定义的 `ShouldSplit` 与 `ShouldMerge` 会判断当前 proclet 是否太大或太小。各机器运行时把资源使用与 idle capacity 上报给 centralized controller，由它做放置和迁移决策。实现上系统采用 RCU，因此普通访问只走 reader path，较重的同步成本主要落在 split/merge 事件上。

这些机制存在的意义，是为了支持真正的毫秒级反应。论文中的库每 2 ms 检查一次队列长度或 proclet CPU 使用率，在需要时 split compute proclet、在负载下降时 merge 它们，并把 compute 或 memory proclet 从过载机器迁走。Quicksand 的承诺不只是“proclet 可以迁移”，而是“proclet 小到迁移这件事真的来得及、也值得做”。

## 实验评估

原型基于 Nu 实现，总计 10 KLoC C++，运行在八台 Xeon E5-2680 v4、64 GiB RAM、100 GbE 的机器上。论文移植了四个应用：ML training pipeline、DeathStarBench social network、内存排序，以及 ExCamera 风格的视频编码。最核心的比较对象是透明 memory disaggregation 的 Hermit，以及前一代 granular programming 系统 Nu。

对高 compute intensity 工作负载，ML pipeline 把核心收益展示得最清楚。在理想平衡布局下，系统吞吐是 26k images/s；在 CPU-unbalanced、memory-unbalanced、both-unbalanced 这些总资源不变但分布失衡的布局下，Quicksand 仍能保持接近理想吞吐，因为它可以跨机器拼起 stranded CPU 与 RAM。Hermit 在 memory-unbalanced 场景下只有 Quicksand 的 83%，而在 CPU-unbalanced 与 both-unbalanced 场景下更只能达到大约一半，因为它根本无法回收 stranded CPU。Nu 在平衡布局下表现不错，但由于 proclet 仍绑定资源，在更困难的失衡布局中 Quicksand 会快 2-4 倍。

对低 compute intensity 工作负载，social-network 服务是更严格的测试，因为 locality 远比纯资源数量更重要。这里 Quicksand 与 Nu 在 memory-imbalanced 场景里都能达到理想吞吐的 40%-84%，而 Hermit 只有 9%-11%，在纯 memory-disaggregated 布局里甚至只剩 4%。这组结果很关键，因为它说明 Quicksand 并没有让远程内存“免费”，但它通过显式访问边界，让库和应用仍能保住足够 locality，避免 paging 式 disaggregation 的吞吐崩塌。

动态实验则说明 split/merge 速度为什么重要。当 ML pipeline 里的 GPU 可用数每 200 ms 在 5 到 10 之间波动时，Quicksand 仍能把 GPU 跑满，而且平均只用 105 个 CPU core；静态高水位基线则要消耗 140 个 core。若把 Quicksand 的反应时间从 2 ms 放慢到 20 ms 或 200 ms，GPU 利用率会明显下降。面对 social network 的突发 memory pressure，Quicksand 通过快速迁移小于 2 MiB 的 shard，把 p99 latency 维持在约 0.3 ms，同时比静态过度预留基线少用 37% 内存。论文对 Hermit 的比较其实已经算偏宽松，因为作者给它按机分实例并手工分发工作；即便如此，整组实验仍只是小规模集群研究，而不是生产部署证据。

## 创新性与影响

这篇论文的创新点不只是“做了一个更好的调度器”或“给 proclet 包了更好用的 API”。它真正新的地方，在于把三种通常分开的东西合在了一起：来自 granular system 的显式远程访问语义、来自 disaggregation 的资源类型解耦，以及藏在高层库内部的自动粒度管理。也正因为这三者被同时实现，应用作者才能继续使用熟悉的抽象，而 runtime 则在背后生成有意偏向单一资源类型的细粒度 proclet。

这会让几类研究方向都从中受益。做 rack-scale disaggregation 的工作可以把 Quicksand 当成软件路径的有力案例：即便没有透明 far memory，也能拿回相当一部分收益。做 granular system 的研究者会看到，仅有 migratability 还不够，proclet 本身还需要资源类型上的 specialization。做 autoscaling 和 service runtime 的研究者，则会把它视为一个证据，说明只要抽象边界选对，毫秒级 split/merge 控制是可以落地的。

## 局限性

Quicksand 明确是一套面向机架规模、高双向带宽网络的设计，而不是通用集群运行时。那些依赖超低延迟内存访问、需要直接控制加速器、或者本身仍是高度单体化遗留结构的应用，移植到 Quicksand 可能会付出明显性能代价。系统目前也只支持 compute 与 memory 两类 proclet；其他资源还是未来工作，而 fault tolerance 也主要借用了已有 granular-computing 技术，并未被直接内建。

架构上也有代价。Controller 和 mapping proclet 都是中心化组件。Hybrid proclet 的存在本身就说明：资源解耦并不总是免费，某些负载仍然需要把计算和状态重新放回一起。附录还直接量化了远程访问开销：当元素大小是 100 B 时，Quicksand 大约需要每个元素 3 微秒计算才能达到 99% efficiency；元素越大，需要的 compute intensity 也越高。这意味着它的适用范围很广，但绝不是所有低 compute intensity 场景都会赢。

## 相关工作

- _Ruan et al. (NSDI '23)_ - Nu 提出了可迁移 proclet 来实现 resource fungibility，但它的执行单元仍把 CPU 与内存绑在一起，也要求应用承担更多粒度管理责任。
- _Qiao et al. (NSDI '23)_ - Hermit 以透明方式池化远程内存，而 Quicksand 则保持远程访问显式，并同时回收 stranded CPU。
- _Adya et al. (OSDI '16)_ - Slicer 也做 datacenter application 的 auto-sharding，但 shard 更粗、反应时间更慢，和 Quicksand 的毫秒级 proclet 控制不是同一量级。
- _Ousterhout et al. (SOSP '17)_ - Monotasks 同样从概念上分离资源消耗，但它服务的是 analytics job 的性能分析，而不是把 compute 和 memory 独立摆放到不同机器上的运行时。

## 我的笔记

<!-- empty; left for the human reader -->

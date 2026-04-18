---
title: "One-Size-Fits-None: Understanding and Enhancing Slow-Fault Tolerance in Modern Distributed Systems"
oneline: "论文先刻画六个系统的 fail-slow danger zone，再用 ADR 把脆弱的静态 timeout 阈值改成运行时自适应的慢故障检测。"
authors:
  - "Ruiming Lu"
  - "Yunchi Lu"
  - "Yuxuan Jiang"
  - "Guangtao Xue"
  - "Peng Huang"
affiliations:
  - "University of Michigan"
  - "Shanghai Jiao Tong University"
conference: nsdi-2025
category: memory-serverless-and-storage
code_url: "https://github.com/OrderLab/xinda"
tags:
  - fault-tolerance
  - datacenter
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文的核心结论是，现代分布式系统并不存在一个稳定统一的 fail-slow 容忍边界。故障类型、严重程度、发生位置、工作负载和硬件预算的轻微变化，都可能让系统从几乎正常直接掉进吞吐崩塌，因此静态 timeout 阈值往往在错误的时机触发。作者先用覆盖六个生产级系统的 fault-injection study 证明这一点，再提出 ADR，把固定阈值替换为运行时自适应的慢故障检测。

## 问题背景

分布式系统对 crash fault 的处理已经相当成熟，但 fail-slow 在大规模部署里同样常见，来源可能是磁盘、NIC、交换机、驱动或环境因素。真正棘手的地方在于，慢节点并没有完全失效，它仍然参与协议，只是慢到足以引发排队、重试和级联瓶颈。早期的 Limplock 已经说明 limpware 可以把整个集群拖入僵局，近年的 Cassandra、HBase、CockroachDB、etcd 等系统也确实加入了 slow query、slow sync、slow disk 之类的处理逻辑。

问题在于，这些逻辑大多还是靠固定 warning threshold 和 fatal threshold 驱动。论文认为这套模型对现代系统过于粗糙。同样的 1 ms 或 10 ms 延迟，在某些系统里几乎没有影响，在另一些系统里却足以造成严重降级；即使在同一个系统内，危险区间也会随着 workload mix、机器资源、leader/follower 位置变化而移动。结果就是，基础设施层和应用层都容易使用 one-size-fits-all 的告警，而开发者写下的阈值往往只在调参时的那一个环境里看起来合理。

论文还指出，当前工程实践本身也在放大这个问题。被研究系统里的 slow-fault handler，大多只是用 unit test 里的 `sleep` 去跨过阈值，再断言 warning、restart 或 log roll 是否触发。这只能验证“代码路径存在”，却无法回答这些阈值在真实端到端部署里会不会足够早地触发，甚至会不会触发。

## 核心洞察

论文最重要的命题是：fail-slow tolerance 本质上是一个动态控制问题，而不是一个“是否跨过 timeout”的二元判定问题。真正决定伤害大小的，不只是某个操作是否变慢，还包括系统行为如何围绕这次变慢发生变化，例如请求完成频率是否在下降、是不是 workload 自己发生了变化，以及故障是否“刚好够慢”到卡在关键路径上，却又没慢到触发 failover。

这种视角能够解释论文中很多反直觉现象。更轻的故障有时反而更糟，因为更重的故障会直接触发 leader re-election 或 connection failover，把慢节点移出关键路径。更多 CPU 资源有时也会让同样的延迟看起来更致命，因为无故障基线变快了。因此，一个有效的 slow-fault detector 必须根据近期局部行为自适应地更新判断标准，同时把 workload transition 和真实 slow fault 区分开，而不是永远把每次观测都和同一条静态 timeout 线比较。

## 设计

论文的测量部分覆盖六个系统：Cassandra、HBase、HDFS、etcd、CockroachDB 和 Kafka。测试流水线会先部署集群并预热，然后一次只注入一个 slow fault，持续采集故障前、故障中和故障后的 throughput 与 latency。故障并不是直接打在某个特定硬件设备上，而是注入到底层接口：packet loss 取 1%、10%、40%、70%，network delay 从 100 us 到 1 s，filesystem delay 从 1 ms 到 1 s。作者还系统性地变化 fault location、fault duration、workload pattern，以及 etcd 的 CPU 和内存限制。核心指标是 performance degradation，也就是 slow period 内平均吞吐相对正常阶段的下降比例。

基于这套 study，论文进一步梳理现有系统里的 slow handling 逻辑，发现它们高度相似：监控某个 latency-like metric，用静态 warning/fatal threshold 判定，然后触发 logging、leader re-election、client reconnection、log roll 或 fail-stop 等动作。ADR 就是为替换这类静态判断而设计的。它是一个轻量级 Java/Go library，总共约 400 行代码，可以直接包裹现有系统里的 timeout check，例如 HBase 的 `slowSyncNs` 与 `rollOnSyncNs`。

ADR 同时追踪一个 traced variable 的“数值”与“更新频率”。当 value window 积累到足够历史后，ADR 使用近期 p99 作为自适应阈值，而不是一直使用固定 timeout。接着它再结合 frequency 做交叉验证：如果更新频率突然变高，ADR 会把它理解为 workload 上升，并重置窗口重新学习；如果更新频率下降，同时数值又持续偏高，ADR 才把它判定为真实 slow fault。系统代码最终拿到的是 `slow` 或 `fatal` 这样的等级，再映射到 warning、log roll、restart 或 fail-stop 等已有动作上。

## 实验评估

测量结果首先说明，fail-slow 的影响在系统之间极不稳定。以 network delay 为例，Cassandra、HBase 和 Kafka 在 1 ms 时就可能超过 25% degradation，而 CockroachDB 与 etcd 大约要到 100 ms 才达到类似程度。有些系统在 10 ms 就接近 70% 降级，另一些系统即便到 1 s 也达不到这么糟。更重要的是，这个关系并不单调：对于 etcd leader，更重的 packet loss 反而可能伤害更小，因为 heartbeat 终于超时，leader re-election 把慢 leader 从关键路径上换掉了。

fault location 和 workload 同样关键。论文报告，在 flaky network 下，etcd 的 slow follower 会带来 45% degradation，而 slow leader 是 31%。根因不是复制协议本身，而是 gRPC client balancer 与 server-side awareness 之间的信息失配：只要 keepalive 还没断，客户端就会继续把请求发给“虽然很慢但仍然活着”的 follower。工作负载的影响更夸张。对 etcd 注入 10 ms network delay 时，read-only、mixed、write-only 三种 workload 的 degradation 分别是 85%、18% 和 15%。论文还找到了非常狭窄的 danger zone，例如 read-only etcd 在 1-2 ms 之间就会从中度退化陡然滑向灾难性退化。

硬件扩容也不能自动解决问题。对于 etcd，在 32 GB 内存和 10 ms network delay 下，CPU core 从 1 增加到 2 再到 5 时，degradation 会从 7% 上升到 26% 再到 72%，因为无故障基线延迟下降得更快。同样，tail latency 也不是可靠的 slow-fault indicator：slow period 中处理的请求更少，正常阶段的大量样本会把 tail statistic 稀释掉，让严重 slow fault 看起来并不显著。

ADR 的评估在 HBase 和 CockroachDB 上进行，对比对象包括原始实现、几组精调过的静态阈值方案以及 IASO。对 HBase 注入 100 ms network delay 时，ADR 把 degradation 从 97% 降到 32%，优于最佳静态方案的 37%，也优于 IASO reboot/shutdown 版本的 38% 和 54%。跨 workload 看，ADR 在 HBase 上把 mixed workload 的 degradation 降低 16-80%，把 write-only workload 的 degradation 降低 43-90%，而且避免了某些 fine-tuned static setting 会把集群直接调崩的情况。对 CockroachDB，论文中的评测场景甚至从 slowdown 变成了约 7% 的 performance gain。ADR 的检测时间约为 mixed workload 1.3 s、write-heavy workload 0.9 s，平均运行时开销为 2.8%。

论文还把几类近期 fail-slow 方案拿来直接对比，结果同样说明问题不只是“有没有机制”，而是“触发逻辑是否足够贴合动态环境”。Perseus 的设备级 latency-throughput 模型迁移到端到端分布式系统后就变得失真；IASO 依赖底层系统已经暴露出来的 timeout signal，因此会继承这些信号本身过于保守的问题；Copilot 在它主要针对的 10 ms 左右区间最有优势，但仍受限于静态的 fast-takeover 与 heartbeat timer。这个对比让论文的主张更完整：真正薄弱的环节往往是僵硬的触发条件，而不是系统里完全没有 slow-fault 处理动作。

## 创新性与影响

这篇论文的创新不在于发明一种新的 replication protocol，而在于把“大范围实证刻画”和“可落地的代码级响应”组合起来。Limplock 一类工作已经证明 slow component 可能很危险，但 One-Size-Fits-None 进一步解释了为什么现代系统即便已经加入 slow-fault handler，仍然会经常失手：触发逻辑是静态的，而故障面是动态的。ADR 因而更像是一种可复用的 retrofit 机制，适合那些已经散落着 slow query、slow sync、slow disk handler，但缺少统一自适应策略的 storage、database 与 control-plane 软件。

## 局限性

这项 study 一次只注入一个 fault，而且只通过 network 与 filesystem 接口注入，因此没有覆盖复合型 gray failure，也没有精细建模更丰富的硬件级 fail-slow 行为。大多数实验使用 3-6 节点的小集群，虽然作者对若干关键结论又在 10 节点和 20 节点上做了复核。论文覆盖的六个系统已经相当广，但仍然不是完整的软件生态。

ADR 本身也有边界。它假设开发者已经知道应该追踪哪些变量，所以对未被 instrument 的慢路径无能为力；它不能处理系统启动阶段的 slow fault；如果故障恰好与 workload transition 同时发生，也可能因为依赖 frequency 变化来区分两者而出现误判。HBase 的 read-only 结果正说明了这一点：作者接入 ADR 时追踪的是 write path 变量，因此它不会改善 read-only slowdown。论文也没有给出这套自适应策略的形式化最优性或稳定性证明。

## 相关工作

- _Do et al. (SoCC '13)_ - Limplock 证明了 limpware 在最坏情况下可以拖垮 scale-out 系统，而这篇论文把视角扩展到现代系统、现实 workload 和更丰富的 slow-fault 空间。
- _Panda et al. (USENIX ATC '19)_ - IASO 通过跨节点聚合 timeout signal 来检测 fail-slow，而这篇论文指出 timeout signal 本身就常常过于静态，并用实验展示了这种局限。
- _Lu et al. (FAST '23)_ - Perseus 面向存储设备 telemetry 建模 fail-slow，而这篇论文说明这类离线、设备导向的模型并不能自然迁移到端到端的分布式系统行为。
- _Ngo et al. (OSDI '20)_ - Copilot 通过协议级冗余容忍一个 slow replica，而这篇论文指出固定 takeover/heartbeat threshold 仍然会留下盲区，因此主张在系统内部采用自适应检测。

## 我的笔记

<!-- 留空；由人工补充 -->

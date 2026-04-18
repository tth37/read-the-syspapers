---
title: "Mitigating Application Resource Overload with Targeted Task Cancellation"
oneline: "Atropos 追踪任务对应用内部资源的占用，并直接取消造成过载的请求，在维持 SLO 的同时把请求丢弃率压到几乎为零。"
authors:
  - "Yigong Hu"
  - "Zeyin Zhang"
  - "Yicheng Liu"
  - "Yile Gu"
  - "Shuangyu Lei"
  - "Baris Kasikci"
  - "Peng Huang"
affiliations:
  - "Boston University"
  - "Johns Hopkins University"
  - "University of Michigan"
  - "University of California, Los Angeles"
  - "University of Washington"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764835"
code_url: "https://github.com/OrderLab/Atropos"
tags:
  - scheduling
  - datacenter
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Atropos 把 overload control 改写成一个有选择的 cancellation 问题：当某个已被接纳的请求开始垄断应用内部资源时，系统应当取消这个 culprit，而不是在入口处丢掉无辜请求。论文在六个应用、16 个复现实例上报告了 96% 的基线吞吐、1.16x 的归一化 p99 latency，以及低于 0.01% 的请求丢弃率。

## 问题背景

论文关注的是一类传统 admission control 几乎看不见的过载：发生在应用自定义资源上的争用，例如 table lock、buffer pool 和内部队列。这些瓶颈不会像 CPU 或 NIC 一样直接暴露为系统计数器，而且不同请求对它们的压力差异极大。因此，极少数病态请求就可能把一个原本健康的服务拖垮。

MySQL 的两个案例把问题讲得很具体。第一个是 buffer pool overload：当 dump query 只占 0.001% 或 0.01% 时，最大吞吐仍会从大约 25 KQPS 降到 18 KQPS 和 12 KQPS，因为这些请求垄断缓存并触发 thrashing。第二个是 table-lock overload：一个 backup query 与长时间 table scan 相互作用后，会把吞吐打到大约 11 KQPS；而只要移除 backup 或 scan 中任意一方，系统就能回到约 25 KQPS。已有方法在这里都抓不住要害：admission control 只能看到全局 delay，于是误丢大量 victim request；isolation 框架虽然能重分配资源，却无法移走已经握住关键资源的 culprit。

## 核心洞察

论文最重要的主张是：应用资源过载应该在 admission 之后处理，而不是 admission 之前处理。只要系统能够观察到哪个正在运行的 task 真正在垄断受争用的资源，那么取消这个 task，通常会比节流无辜请求有效得多。

这个思路可行，是因为很多应用早就有安全、应用语义感知的 cancellation 逻辑。作者调研了 151 个流行开源系统，发现 76% 支持 task cancellation，而其中 95% 已经暴露了可触发 cancellation 的 initiator。Atropos 因此复用现有 hook，而不是发明一个通用 kill 机制。

## 设计

Atropos 建立在两个抽象之上。第一，开发者用 `createCancel` 和 `freeCancel` 把 request 或后台任务标成 cancellable task，并通过 `setCancelAction` 注册应用自身的 cancellation initiator。第二，Atropos 把内部瓶颈统一建模为 application resource，并只跟踪三类事件：获取、释放和等待。当前实现覆盖 synchronization resource、queue resource 和 memory-like resource，例如 buffer pool 或 cache。

运行时管理器负责把这些资源事件归属到当前 task。检测过程比较克制：Atropos 先观察端到端现象，也就是 latency 超出 SLO 且 throughput 基本不再增长；只有在这个时候，它才进一步判断是否真有某个内部资源是瓶颈。进入估计阶段后，系统会为每类资源计算两个无量纲指标。第一个是 contention level：对 lock 和 queue 来说，本质上是等待时间相对使用时间的比例；对 memory pool 来说，则用 eviction 行为来刻画。第二个是 resource gain，即取消一个 task 之后预计能减少多少未来争用。这里不能只看当前占用量；对于 memory 和 lock，Atropos 会结合 task progress，用“当前占用乘以剩余工作比例”的方式估计未来损害。

最有辨识度的部分是 cancellation policy。Atropos 不是简单地在单个资源上做 greedy 选择，而是先把 contention 统一归一化成“执行时间里有多少比例损失给了这个资源”，再找出跨多个资源都不被支配的 non-dominated set，最后用各资源的 contention 作为权重，把 gain 合成一个总分。它要回答的问题不是“谁在某个资源上最坏”，而是“取消谁，能在所有同时过载的资源上带来最大的总收益”。为了缓解 starvation，被取消的请求只会在资源恢复后重试一次，随后会被标记为 non-cancellable。

## 实验评估

实验把 Atropos 集成进了 MySQL、PostgreSQL、Apache、Elasticsearch、Solr 和 etcd，覆盖 C/C++、Java 与 Go 三种语言，并复现了 16 个真实 overload bug，类型包括 lock contention、thread-pool 上限、memory 压力、CPU 争用和 I/O 争用。新增代码量本身不大，从 etcd 的 22 行到 MySQL 的 74 行不等；不过论文也明确承认，真正费时的是识别哪些内部资源值得跟踪。

核心结果支持论文主张。相对于无过载基线，Atropos 平均保住了 96% 的吞吐，并把归一化 p99 latency 控制在 1.16。它明显优于 Protego、pBox、DARC 和 PARTIES，这些基线的平均归一化吞吐分别只有 50.7%、53.9%、36.3% 和 37.8%。关键差异在于选择性。Atropos 的平均 request drop rate 低于 0.01%，而取消 victim 而非 culprit 的 Protego 平均要丢掉约 25% 的请求。

SLO 和开销结果也有说服力。在“latency 最多上涨 20%”的 SLO 下，Atropos 在 16 个 case 中有 14 个达标，平均 latency 增幅为 10.2%；剩下两个 case 失败，是因为 noisy task 太多，需要连续取消多个请求才能真正恢复。运行时开销较低：正常负载下平均吞吐只下降 0.59%，过载时由于切换到更细粒度 tracing，平均下降 7.09%。

## 创新性与影响

这是一篇 mechanism paper，而不只是一个更会调参数的控制器。它的创新点，是把 overload control 的 actuation point 改成 targeted runtime cancellation，并补齐这件事所需的系统支撑：task 边界、resource-agnostic tracing hook、future-gain estimation，以及面向多资源的 policy。当真实瓶颈藏在应用逻辑内部时，这篇论文说明 admission control 往往并不是最合适的杠杆。

## 局限性

Atropos 很依赖应用配合。开发者需要识别内部资源、插入 tracing hook、暴露 progress signal，并且最好本来就有安全的 cancellation point。它的 resource-gain 模型也只是近似，把未来需求简化成与剩余进度成正比，这对长时间垄断资源的请求通常够用，但仍可能错判。更大的边界是，论文只把它评估成一个 single-node framework；分布式 cancellation 和 partition 等故障情形都被留给未来工作。最后，并不是所有应用都拥有干净的 task-level cancellation path。Apache 在 PHP script 场景下需要退回到 `pthread_cancel`，这提醒读者：Atropos 的安全性终究取决于底层应用自己的 cancellation 语义。

## 相关工作

- _Cho et al. (OSDI '20)_ - Breakwater 通过 queueing-delay 信号调 admission，而 Atropos 选择让请求先执行，再取消真正造成内部资源争用的 task。
- _Cho et al. (NSDI '23)_ - Protego 面向不可预测的 lock contention，并取消那些即将违反 SLO 的请求；Atropos 则试图识别并取消 lock holder 或其他 culprit task，而且适用范围不止于 lock。
- _Hu et al. (SOSP '23)_ - pBox 把 performance isolation 推进到应用内部做 request-aware resource control，而 Atropos 进一步指出，一旦有害请求已经在运行，单靠 isolation 仍然不够。
- _Banga et al. (OSDI '99)_ - Resource Containers 通过资源分区来做服务器隔离，而 Atropos 认为面对高度可变的请求行为和应用自定义资源，这种 partitioning 过于粗糙。

## 我的笔记

<!-- 留空；由人工补充 -->

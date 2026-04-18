---
title: "NotebookOS: A Replicated Notebook Platform for Interactive Training with On-Demand GPUs"
oneline: "NotebookOS 将 notebook kernel 复制到多台 GPU 服务器上，只在 cell 执行时绑定 GPU，以更低成本维持交互式训练体验。"
authors:
  - "Benjamin Carver"
  - "Jingyuan Zhang"
  - "Haoliang Wang"
  - "Kanak Mahadik"
  - "Yue Cheng"
affiliations:
  - "George Mason University, Fairfax, Virginia, USA"
  - "Adobe Research, San Jose, California, USA"
  - "Adobe Inc, San Jose, California, USA"
  - "University of Virginia, Charlottesville, Virginia, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3760250.3762230"
code_url: "https://github.com/ds2-lab/NotebookOS"
tags:
  - gpu
  - scheduling
  - ml-systems
  - datacenter
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

NotebookOS 把 notebook session 视为长生命周期状态，但把 GPU 占用视为短生命周期、可弹性回收的资源。它把每个 Jupyter kernel 复制到三台 GPU 服务器上，用 Raft 同步小状态、用异步持久化处理大对象，并且只在 cell 真正执行时绑定 GPU。这样一来，在 Adobe 生产负载片段上，它在 17.5 小时内节省了 1,187.66 个 GPU 小时，同时把交互性维持在接近“全程保留 GPU”的 notebook 部署水平。

## 问题背景

论文关注的是 notebook 平台的一个结构性错配：系统按“长会话”来分配硬件，但用户对 GPU 的实际使用却是短促、零散且间歇性的。在 Jupyter 风格的交互式深度学习训练（`IDLT`）里，用户会长时间保留一个 notebook session，在其中调试代码、查看输出、改超参数，只偶尔触发一次很短的训练 cell。今天的大多数 notebook 平台为了保证响应速度，会在整个 session 生命周期里一直把 GPU 绑给这个用户。

作者用 Adobe 内部 trace 说明了这种做法有多浪费：保留出来的 GPU 有超过 81% 的时间处于空闲状态，将近 70% 的 GPU 在所属 session 的整个生命周期里都没有真正被用到；大约四分之三的 session，真正活跃使用 GPU 的时间占比不超过 5%。而且这类工作负载和传统批处理深度学习明显不同：AdobeTrace 里 50% 的训练任务在 2 分钟内结束，75% 在 5 分钟内结束，按 session 统计的任务间隔中位数却有 5 分钟。这说明目标场景是一组长生命周期、带状态、偶尔提交短训练任务的 notebook session，而不是一串持续运行的大训练作业。直接切到 batch scheduler 虽然能回收 GPU，却会把容器启动、排队和状态恢复的开销压到用户最在意的交互时刻。

## 核心洞察

论文最核心的观点是：notebook 状态和 GPU 保留不必绑定在一起。NotebookOS 把一个 notebook kernel 复制到多台 GPU 服务器上，并在这些服务器上进行过订阅，前提是假设 `IDLT` 请求到达是稀疏的。用户提交 cell 时，只需要有一个 replica 能快速拿到 GPU；其余 replica 用来保留状态、承受故障，并提高“总有一个宿主机还有空闲资源”的概率。小的 CPU 侧状态持续同步，大的模型和数据集则在关键路径之外异步持久化。目标工作负载中较长的任务间隔，让这套拆分能够成立。

## 设计

NotebookOS 在普通 Jupyter 客户端之下插入了一层资源管理系统。核心组件包括 Jupyter Server、一个 Global Scheduler、每台 GPU 服务器上的 Local Scheduler、每个 notebook 对应的三副本 Distributed Kernel，以及一个 Distributed Data Store。创建 kernel 时，Global Scheduler 会选择三台候选服务器，并在每台上拉起一个 replica。重要的是，这些 replica 只是“订阅”资源，而不是长期独占资源，因此整个集群可以对空闲容量做过订阅。

当用户发送 `execute_request` 时，NotebookOS 会决定哪个 replica 充当 executor。如果调度器已经知道哪台机器具备足够的 GPU，就可以直接绕过完整选举；否则，三个 replica 会基于 Raft 提交 `LEAD` 或 `YIELD` 提案，最先被提交的 `LEAD` 获胜。只有这个 executor 真正执行代码，其他 replica 保持 standby。若所有 replica 都因为资源不足而 `YIELD`，系统就把其中一个 replica 迁移到更合适的服务器上，然后重试；为降低迁移延迟，NotebookOS 还维护了一个小规模的 pre-warmed container 池。

状态管理是这篇论文最有辨识度的部分。cell 执行完成后，NotebookOS 会先把代码转成 Python AST，分析哪些状态需要保留，然后用 Raft 的状态机复制同步小对象。对于大对象，它只在 Raft log 里记录一个指针，实际数据则写入 Redis、S3 或 HDFS 这类可插拔的分布式存储中，从而避免把多 GB 的模型直接塞进一致性路径。论文也明确说明，这套机制目前覆盖的是 Python 级状态，以及在 kernel namespace 中被引用的原生状态；外部进程状态和 libc 状态暂时还不能透明同步。

GPU 管理部分则非常务实。NotebookOS 在真正执行之前才进行动态 GPU 绑定，把模型参数从主机内存加载到分配到的 GPU 上，执行 cell，再在回复前把相关 GPU 状态拷回主机内存。放置与自动扩缩容则由 subscription ratio 驱动：当活跃需求上升到难以维持“每个 notebook 至少有一个 replica 大概率还能立刻拿到资源”时，系统就会扩容。

## 实验评估

论文同时做了原型系统实验和模拟实验。原型运行在 30 台 AWS EC2 GPU 虚拟机上，每台 8 张 GPU，并使用计算机视觉、NLP 和语音模型与数据集回放一段 17.5 小时的 AdobeTrace。对比基线包括：模仿当前 notebook 平台的 Reservation、每次请求都重新拉起 kernel container 的 Batch 调度器，以及一个用更大 warm-container 池换取更低成本但更差交互性的 `NotebookOS (LCP)`。

原型实验最重要的结果是，NotebookOS 在没有显著牺牲交互性的前提下把资源效率大幅拉高。相对 Reservation，它在 17.5 小时 trace 回放中节省了 1,187.66 个 GPU 小时；`NotebookOS (LCP)` 节省了 1,662.53 个 GPU 小时，但延迟更差。NotebookOS 有 89.6% 的执行请求能够在到达时立刻把 GPU 绑定给某个 replica，连续请求中有 89.45% 会复用同一个 executor replica，因此它的交互性曲线非常接近 Reservation。它的 task completion time 在 38 到 90 分位之间略差一些，主要是因为过订阅偶尔会触发 replica migration 或冷容器创建，但整体上仍明显优于 batch 基线。

状态复制开销也基本符合论文预期。对通过 Raft 同步的小对象，90、95 和 99 分位延迟分别是 54.79ms、66.69ms 和 268.25ms；对大对象，99% 的读写在约 3.95 秒和 7.07 秒内完成。作者认为这些开销大多能藏在 AdobeTrace 的工作负载间隔中，因为最短事件间隔也有 240 秒。

模拟实验把分析从短时间回放扩展到整个夏季 trace。在论文的计费模型下，NotebookOS 相比 Reservation 最多能把 provider 侧成本降低 69.87%，同时提高利润率，因为系统回收了大量空闲 GPU 时间，但又能对 standby replica 收取少量费用。

## 创新性与影响

相对于 _Xiao et al. (OSDI '18)_ 和 _Gu et al. (NSDI '19)_ 这类经典 GPU 集群调度工作，NotebookOS 的新意在于它把 notebook session 而不是训练作业本身当成系统设计的第一对象。相对于现有 notebook 平台，它的关键一步也不是改 timeout 策略或接入 batch queue，而是提出了“状态持久化的 notebook kernel + 按需绑定的 GPU”这一拆分方式。论文真正的主机制是 Raft 复制的 kernel 抽象，动态绑定、过订阅、迁移和自动扩缩容都是围绕它展开的。

因此，这篇论文既会吸引托管 notebook 平台的构建者，也会吸引关注有状态交互式 ML 基础设施的系统研究者。它的贡献更像一种新的系统分解方式，而不只是新的调度目标。

## 局限性

NotebookOS 目前还不支持 GPU sharing、fractional GPU allocation 或跨多台服务器的训练，基于 AST 的状态同步也还不能捕获外部进程状态和 libc 状态。此外，这套设计对工作负载形状有依赖：较长的任务间隔可以隐藏模型和数据集的异步搬运，但更紧凑的 edit-run 循环可能会把这些成本直接暴露出来。最后，系统刻意保留额外 replica 和 warm container，因此它本来就不是要在所有场景下都把常驻成本压到 batch 系统以下。

## 相关工作

- _Xiao et al. (OSDI '18)_ — Gandiva 通过内省式调度和时间片来提升批量深度学习集群效率，而 NotebookOS 的出发点是长生命周期 notebook session 和逐 cell 的响应性。
- _Gu et al. (NSDI '19)_ — Tiresias 关注的是分布式深度学习作业在部分信息下的完成时间优化，但它不保留交互式 notebook 状态，也不把 session 当作一等对象。
- _Mahajan et al. (NSDI '20)_ — Themis 面向多租户 GPU 集群中的公平性与效率，而 NotebookOS 愿意支付额外的复制开销来保持 notebook 用户的交互体验。
- _Wu et al. (NSDI '23)_ — Transparent GPU sharing in container clouds 提供了 NotebookOS 目前尚未实现、且论文明确留给未来集成的细粒度 GPU 共享能力。

## 我的笔记

<!-- 留空；由人工补充 -->

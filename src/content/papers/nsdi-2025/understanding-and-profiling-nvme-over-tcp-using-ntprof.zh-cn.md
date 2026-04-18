---
title: "Understanding and Profiling NVMe-over-TCP Using ntprof"
oneline: "ntprof 把 NVMe/TCP 看成一串软件交换机，用内核 tracepoint 和探测命令定位时延、争用与硬件瓶颈，同时保持较低开销。"
authors:
  - "Yuyuan Kang"
  - "Ming Liu"
affiliations:
  - "University of Wisconsin-Madison"
conference: nsdi-2025
code_url: "https://github.com/netlab-wisconsin/ntprof"
tags:
  - storage
  - networking
  - observability
  - disaggregation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`ntprof` 是一个面向 Linux NVMe-over-TCP 的剖析系统，它把整条存储路径看成无损交换网络。通过在各个软件阶段挂接基于 tracepoint 的 profiling agent，并用类似 TPP 的探测命令查询统计信息，它可以拆解 I/O 时延、定位软件和硬件瓶颈，并分析租户间干扰，同时只引入很小的额外开销。

## 问题背景

这篇论文要解决的，是一个很现实但长期被忽视的问题：NVMe/TCP 已经开始被部署，但开发者依然缺少一个一等公民级别的 profiler，去理解一次 I/O 在协议栈里到底经历了什么。在 Linux 中，一个请求会穿过块层、发起端 `nvme-tcp` 传输层、TCP/IP 协议栈、目标端 `nvmet-tcp`、目标块层，最后才到达 NVMe 设备。每一层都有自己的队列、并发策略和调度行为，而且关键路径跨越两台主机。

这让现有的排障方式非常脆弱。开发者可以把应用 benchmark、`perf`、`blktrace`、`iperf3`、`qperf` 和 SSD 工具拼在一起用，但每个工具只看到系统的一小块。论文给出的动机例子很典型：当目标 SSD 被额外负载压满后，吞吐从 `1441.0 MB/s` 降到 `625.0 MB/s`，平均时延从 `867.1 us` 升到 `1999.6 us`；可 `perf` 在两种情况下看到的热点函数几乎一样，网络工具又只会告诉你链路带宽够用。操作者只能知道“系统变慢了”，却无法知道队列是从哪里开始堆积的，也不知道到底是哪个阶段出了问题。

困难不只是埋点数量多。NVMe/TCP 工作负载会在请求大小、读写比例、访问模式和并发度上发生剧烈变化。Linux 还提供多队列块层接口、多连接 session，以及会随负载变化而重映射请求的 per-core 执行模型。因此，论文真正想要的不是另一个局部 tracing 工具，而是一个能沿着横向主机路径和纵向软件栈同时跟踪 I/O，并且足够轻量、可以和被测应用共存的 profiler。

## 核心洞察

论文最重要的洞察，是不要把 NVMe/TCP 当成一个黑盒存储栈，而是把它重新建模成一个无损交换网络。在这个视角下，initiator 发送请求“报文”，target 返回响应，而路径上的每个系统模块都可以视作一个带缓冲的软件交换机，具有自己的排队规则。一旦这样抽象，时延归因和瓶颈定位就从“事后拼日志”的问题，变成了“如何做 telemetry”的问题。

这个重构带来了两个关键抽象。第一，不同层可以用少量排队模型刻画，例如 centralized FCFS、split FCFS 和 processor sharing。第二，每个 I/O 都可以绑定一条 profiling record，在跨越各个阶段时不断追加时间戳。论文的核心主张是：只要有了这样的记录和路径模型，就足以重建端到端时延拆分、租户干扰和拥塞位置，而不需要对整个内核做超重的细粒度 tracing，也不需要开发者再去手工拼接彼此无关的工具输出。

## 设计

`ntprof` 的设计可以分成四部分。第一部分是 profiling task specification。用户要告诉系统关心哪些 I/O，比如请求类型和大小、要观察哪个 NVMe/TCP session、应用和队列是如何配置的、采用 online 还是 offline profiling、采样频率是多少，以及最终要生成什么样的报告。换句话说，论文不是在做一个固定格式的 report generator，而是在做一个可查询的 profiling substrate。

第二部分是路径建模。论文把 NVMe/TCP 的请求和响应路径映射成九个逻辑阶段，从 initiator 侧的 `blk_mq` 一直到 target 侧 SSD，并把每个阶段都当成一个排队交换节点。这样即便并不是每个内部细节都有直接时间戳，`ntprof` 仍然可以借助队列占用和并发信息推断各段的等待时间。这个模型刻意比内核调用图更抽象，但又足够细，能够把传输队列争用、target core 饱和、TCP 栈排队和 SSD 服务时间区分开来。

第三部分是 programmable profiling agent。实现上，作者在 `nvme-tcp` 和 `nvmet-tcp` 中加入了新的 tracepoint，并注册回调函数，在每个 I/O 的生命周期里创建或更新一条 profiling record。每条 record 保存请求元数据，以及一个按时间追加的事件列表。来自 task specification 的 predicate 会过滤掉不相关的 I/O，因此一次 profiling 可以只聚焦 4 KB reads，或者只观察某一个 session。论文还给出了 record 的空间开销，大致是几百字节，具体随 I/O 类型不同而变化。

第四部分是受 Tiny Packet Programs 启发的查询路径。`ntprof` 定义了特殊的 `ProbCmd` 和 `ProbResp` capsule，它们沿用现有 NVMe/TCP 机制传输。一个 probe 中携带简单的 load、store、reset 指令，指明要访问哪个 software switch、哪类统计量。每个 switch 只执行属于自己的那部分指令，还可以像端口镜像一样把 probe 复制到所有可能的下游路径，并直接返回统计结果。最后，用户态 analyzer 会对时间戳做校准，把排队延迟与占用和并发信息对齐，再通过类似 map-reduce 的聚合流程输出 JSON 报告。整套实现大约 `10K` 行代码，包含内核 patch、新模块和用户态工具。

## 实验评估

论文的评估组织方式不是给出一个单一跑分，而是用六个 case study 展示 `ntprof` 能回答什么问题，这和论文目标是匹配的。首先，在 CloudLab testbed 上，`ntprof` 可以做细粒度时延拆解。对 4 KB random read，当 `iodepth` 从 `1` 增加到 `32` 时，网络相关的组合阶段 `S3-S5(S+C)` 从 `14.3 us` 增长到 `127.0 us`；在最高并发时，这部分已经占到总时延的 `92.2%`。而对 128 KB sequential write，主导项转移到了 `S6-S9(S+C)`，其时延从 `79.2 us` 飙升到 `2234.9 us`，其中 `95.9%` 发生在 target 侧。这种结论是普通 CPU profiler 无法直接给出的。

第二类结果是软件瓶颈定位。在 target core 成为瓶颈的场景里，吞吐只从 `252.4 MB/s` 微涨到 `284.9 MB/s`，但时延却从 `238.7 us` 升到 `431.0 us`。论文引入了 Latency Amplification Degree，也就是 `LAD`，来识别哪一段在过载后膨胀得最厉害，并借此把问题定位到 completion path 上过载的 target 阶段。另一个实验把越来越多作业压到过少的 TCP 连接上，结果 `S1` 的 `LAD` 最高达到 `51`，准确指出 initiator 侧连接并行度不足。

第三类结果说明，同一套机制也能识别硬件瓶颈和干扰模式。当 target 本地 writer 与远端工作负载竞争同一块 SSD 时，远端带宽降到 `627.2 MB/s`，时延升到 `1984.6 us`，而 target 侧存储阶段具有最高的 `LAD`。当 `16` 个 `iperf3` client 与 NVMe/TCP 流量争抢 NIC 时，读时延会从 `834.9 us` 增加到 `2803.5 us`，传输栈相关阶段出现 `4.5` 的 `LAD`。在 4 KB 和 128 KB 混合读的多租户实验中，延迟敏感的 4 KB 流吞吐分别下降 `26.7%`、`71.5%` 和 `73.1%`，而 `ntprof` 能进一步区分这是 target 端共享队列带来的问题，还是 initiator 端共享 transport state 带来的问题。Apache IoTDB 和 F2FS 两个真实应用案例也说明了同一点：当只有一个 session、NIC 很忙或 SSD 很忙时，真正的限制因素并不一样，而 profiler 可以把它们分开。系统开销方面，读场景 CPU 使用率只增加 `0.6%`，写场景增加 `2.9%`，内存额外占用最多 `17 MB`。

整体来看，实验是支持论文核心论点的：`ntprof` 确实是一个有操作价值的诊断工具。它没有证明每一段时延都能以绝对精确的方式被测出来，但它确实在多种合成和真实应用场景里给出了稳定且可行动的归因结果。

## 创新性与影响

这篇论文的创新主要在 observability，而不是提出新的存储协议。相对 TPP 这类 active-network telemetry 系统，它把“可编程 in-band 查询”的思路从交换机带到了一个跨越块层、网络栈和远端 SSD 的主机软件栈里。相对 `perf` 这种 Linux 性能工具，它提供的是以 request 为中心、跨主机的端到端视图，而不是以函数为中心的热点视图。相对 `i10` 这类 remote storage 系统，它并不重做 datapath，而是让现有 Linux NVMe/TCP datapath 变得可检查、可归因。

这个定位很重要。做存储解耦、主机栈瓶颈、NVMe/TCP 调度的人，可以把 `ntprof` 当成测量底座；运维和基础设施工程师，则可以用它回答 queue depth、session 数、租户干扰和硬件饱和度这些非常实际的问题。论文更可能被引用的原因，不是因为 `ntprof` 已经是最终答案，而是因为它给出了一套把分层存储协议改造成可查询 telemetry surface 的明确方法论。

## 局限性

这个系统和 Linux 内核态 NVMe/TCP 实现绑定得很紧，具体依赖的是围绕内核 `5.15.143` 加入的代码路径和 tracepoint。论文虽然讨论了基于 eBPF 的实现变体，以及扩展到 SPDK 的可能性，但这些都属于未来方向，而不是已经完成并评估的系统。如果实际部署使用 kernel bypass，或者使用了重度定制的厂商协议栈，那么现有实现并不能直接迁移过去。

归因质量也依赖于排队模型和被选中的 tracepoint。`ntprof` 能在很多关键边界上打时间戳，但它并没有观察到每一个内部状态转换，因此有些延迟拆分是通过校准和模型恢复出来的，而不是完全直接观测得到的。这是合理的工程折中，但也意味着应当把它理解为一个结构化诊断系统，而不是完美的 ground-truth recorder。

评估本身也仍有范围限制。大多数实验都是两节点 CloudLab 和人工构造的争用场景。论文证明了低开销，但没有系统性量化 probe 频率、buffer 大小和长时间在线监控在更大规模下会如何相互作用。论文还提到，执行 probe 时会暂时阻塞本地 profiling agent，因此测量能力和侵入性之间依然存在权衡。

## 相关工作

- _Jeyakumar et al. (SIGCOMM '14)_ - `TPP` 提供了可编程 in-band 查询模型，`ntprof` 则把它从网络交换机改造成 NVMe/TCP I/O 路径上的查询机制。
- _Hwang et al. (NSDI '20)_ - `i10` 通过重构远端 TCP 存储 datapath 来降低开销，而 `ntprof` 保留现有 Linux NVMe/TCP，实现的是“解释时间花在哪里”。
- _Haecki et al. (NSDI '22)_ - `NSight` 关注端主机网络时延的细粒度诊断，`ntprof` 则把类似的分析方式扩展到了块层、传输层和存储设备阶段。
- _Liu et al. (NSDI '23)_ - `Hostping` 定位的是 RDMA 场景中的主机内瓶颈；`ntprof` 面向 NVMe/TCP，并增加了 per-I/O 记录和跨 initiator/target 的 in-band 查询。

## 我的笔记

<!-- 留空；由人工补充 -->

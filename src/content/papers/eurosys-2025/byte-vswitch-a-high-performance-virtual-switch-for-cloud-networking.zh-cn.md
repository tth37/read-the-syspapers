---
title: "Byte vSwitch: A High-Performance Virtual Switch for Cloud Networking"
oneline: "BVS 把云上 virtual switch 收窄成固定的 VPC 流水线，再用 Orca 按需学习 VM location，以更低成本换取更高吞吐和更好可运维性。"
authors:
  - "Xin Wang"
  - "Deguo Li"
  - "Zhihong Wang"
  - "Lidong Jiang"
  - "Shubo Wen"
  - "Daxiang Kang"
  - "Engin Arslan"
  - "Peng He"
  - "Xinyu Qian"
  - "Bin Niu"
  - "Jianwen Pi"
  - "Xiaoning Ding"
  - "Ke Lin"
  - "Hao Luo"
affiliations:
  - "ByteDance Inc."
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3717479"
tags:
  - networking
  - virtualization
  - datacenter
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

BVS 是 ByteDance 面向公有云 VPC 网络的生产级 virtual switch。它的核心做法不是继续在 OVS 的通用框架上修修补补，而是把策略判定留在 slow path，把转发热点压进围绕 flow、session、路由和 ACL 重新定制的 fast path，再用 Orca 按需学习 VM location。作者在评测里报告，相比 OVS-DPDK，BVS 最多把 PPS 提高到 3.3 倍，CPS 提高 17%，转发时延降低 25%。

## 问题背景

这篇论文的出发点很直接：在超大规模公有云里，OVS 的大部分通用能力并没有真正被租户场景使用，但它的复杂性却会落到每一台主机上。ByteDance 真正常用的是 VPC 语义下那几件事，比如虚拟网卡、路由、安全组、限速和监控；可 OVS 背后是一整套面向 OpenFlow 的通用架构、层层分类器，以及连接跟踪逻辑。等租户规模涨到数百万 flow、而安全组又成了刚需时，这套通用性就开始反噬性能。

论文抓住了两个很具体的瓶颈。其一，OVS 的缓存层级在公有云工作集面前不够大。即便社区已经把 EMC 换成 SMC，容量也大约只有 100 万条，超出后仍要掉回 `dpcls` 做代价更高的 wildcard matching，直接拖慢 forwarding latency 和 connection establishment。其二，connection tracking 本身就很吃算力，论文引用的数字是安全组相关处理最多会让性能下降 50%，而继续给 switch 多分配 CPU core 在云环境里通常又过于昂贵。

更麻烦的是，这还不只是 dataplane 的问题。主机上的 virtual switch 还要面对海量 VPC 里的 VM location 维护、频繁升级、live migration，以及线上故障排查。换句话说，作者想解决的不是某个孤立的 forwarding microbenchmark，而是一套能长期跑在生产云里的 host networking system。

## 核心洞察

论文最关键的判断是，云上的 VPC switch 不该继续围绕一个通用可编程 dataplane 来设计，而应该围绕云里真正稳定存在的对象来定制。只要 pipeline 固定在 ENI、route、security group、VM location 和 session 这些 VPC 原语上，代码路径就能显著收窄，数据结构也能按这些对象本身的访问模式来挑选，fast path 才有可能被彻底优化。

这种专用化还改变了状态分发的思路。作者在生产环境里观察到，一台 BVS 实例实际用到的 VM location entry 往往不到整个 VPC 的 30%，在大 VPC 里甚至更接近 20%。这意味着最合理的办法不是把所有 location 都预先灌到每台 host 上，而是只在真正有流量时再学习 active working set。换句话说，BVS 把问题从维护全量控制面状态，改成了维护随流量浮动的工作集状态。

## 设计

BVS 采用分层架构。全局的 VPC control plane 仍然维护 ENI、subnet、route、ACL 等高层配置；每台计算主机上则运行 `BVS-Controller` 和 `BVS-Agent`。前者负责监听 ETCD 变化并把它们翻译成 host-local 配置动作，后者通过 gRPC 暴露管理接口、把配置落到 SQLite、并提供运维工具。真正的数据面分成 slow path 和 fast path：协议包以及新 flow 的首包先走 slow path，在那里完成 ACL、安全组、路由、限速和目的 VM location 判定；一旦动作确定，就安装到以 session 为基础的 exact-match flow table 里，后续包直接走 fast path。

fast path 建在 Byteflow 之上。Byteflow 是一个基于 DPDK 的转发框架，用来屏蔽不同 NIC 和 DPDK 版本的差异，同时给 BVS 留出足够薄的执行面。这里最重要的是几处数据结构替换。LPM 不再使用 DPDK 默认的 DIR-24-8，而是换成 Tree Bitmap：在 1K 路由表上，内存只剩原来的 0.1%；在 769K 路由表上，内存也大约还能降到 1/3。ACL 侧，BVS 用 HyperSplit 代替 Multi-Bit Tries，用 2-3 倍更慢的 lookup 换来 8-21 倍更低的内存占用和更快的 build time。flow table 则引入 per-thread local cache，减少不同线程围绕全局 ring 的竞争，单这一项就能把 CPS 提高到最多 39.6%。

状态管理同样是为云场景定制的。session reconciliation 不会在控制面一变时立刻重写全部 flow，而是只更新更小的 ENI version table，等后续包发现 version mismatch 再回到 slow path 重新求值。session aging 负责批量回收不活跃 flow。最有代表性的是 Orca：当一台 BVS 第一次发包到未知 VM 时，它先把包送到 Orca gateway；gateway 一边转发，一边回一条 sync message，把目标 VM 的 location 直接同步给发送端。之后的数据流就可以 host-to-host 直连。论文还给 BVS 加了一个 vendor-agnostic 的 offload abstraction layer，让 full-flow、elephant-flow、按协议或按阈值的 offload policy 能映射到不同 SmartNIC 或 DPU 上。再往上，则是更偏生产系统的能力，例如 SLBB、基于 vhost-user state migration 的 hitless upgrade，以及带 session sync 的 live migration。

## 实验评估

最核心的对比实验在四台服务器上完成，机器配的是 Intel Xeon 8336C、Mellanox ConnectX-6 2x100Gbps NIC，两边都打开了相同的网络功能，并且都只给 dataplane 分配 4 个 hyper-thread。在这个条件下，BVS-Byteflow 相比 OVS-DPDK 做到了最多 3.3 倍的 PPS、17% 更高的 CPS，以及 25% 更低的 forwarding latency。作者把收益主要归因于更短的代码路径、更轻的 session 处理方式，以及优化后的 hash table。硬件 offload 场景里，两者在 NIC SRAM 尚未打满前差异不大；大约超过 10K flows 之后，性能都会因为退回 host memory 而下降。

其余评测更能体现这篇论文不是单点 dataplane 优化。Orca 在单 VPC、16 vCPU 条件下能做到每秒 439 万条 VM location 学习，在 16 个 VPC 时提高到每秒 1390 万条；update 速率达到每秒 258 万条，而上一代控制面预编程方案只有每秒约 1 万条。SLBB 把集中式 SLB 集群的负载从大约 20 Tbps 压到略高于 4 Tbps，相当于下降 80%。hitless upgrade 方面，新的 VSM 模式把 16 个四队列 VM 时的停顿从 2400 ms 压到 5 ms，把 255 个四队列 VM 时的停顿从 5130 ms 压到 22 ms。live migration 的生产数据则显示，服务中断始终低于 300 ms，整个迁移过程即便在最大实例上也能控制在 10 秒以内。

这些结果基本支撑了论文的中心论点：BVS 的收益来自围绕云场景做的一整套专用化，而不只是某个 dataplane trick。不过外部有效性仍要谨慎看待。它主要是在 ByteDance 的环境里、和特定版本的 OVS 做比较，所以更适合被理解成一种面向公有云 host switch 的强工程论证，而不是适用于所有 virtual switching 工作负载的通用结论。

## 创新性与影响

BVS 的新意不在某一个单独算法，而在于它把多件彼此相关的工程决策打包成一套完整系统：固定的 VPC-oriented pipeline、紧凑的数据结构、数据面位置学习、统一的硬件 offload 抽象，以及真正能支撑长期运营的 hitless upgrade 和 migration 机制。和很多只盯 dataplane 吞吐的工作相比，这篇论文把 host virtual switch 当成了一个需要持续演进和维护的云服务。

因此它的价值也分成两层。对运营者而言，论文说明如果业务边界足够清晰，放弃通用 switch stack、换来更窄但更快的 cloud-native implementation，是完全可能划算的。对研究者而言，它提醒人们不要把 performance、scalability 和 operability 拆开看；在 BVS 里，真正起决定作用的恰恰是这三件事被一起设计了。

## 局限性

这套方案最大的优势也是最大的边界条件。BVS 之所以快，是因为它主动放弃了 OpenFlow 级别的通用性和 OVS 的大量特性，所以只有在部署场景确实以 VPC 风格云网络为主时，这种取舍才成立。如果你需要更开放的 SDN 编程模型，或者要承载更杂的 middlebox 行为，BVS 并没有试图覆盖这些需求。

另外几项关键机制也带着明显假设。Orca 建立在活跃 VM location working set 远小于全量状态这一观察之上，而且首包学习与同步仍依赖 Orca gateway 集群。硬件 offload 方面，论文明确承认 vendor 侧可观测性不足，NIC SRAM 溢出后性能也会明显下滑。再往外看，评测几乎完全来自 ByteDance 内部环境，因此关于成本、可维护性，以及和 OVS 比较的公平性，更适合被视为真实部署证据，而不是一套彻底一般化的 benchmark 结论。

## 相关工作

- _Dalton et al. (NSDI '18)_ - Andromeda 同样构建了分层的云网络虚拟化栈，但它主要通过控制面识别并下发大流信息；BVS 则把 VM location learning 进一步推到了数据面里。
- _Firestone (NSDI '17)_ - VFP 保留了可编程的多层 match-action 模型，并让外部控制器承担大量逻辑；BVS 则反过来收窄接口，把 host switch 固定成面向 VPC 对象的专用 pipeline。
- _Yang et al. (SIGCOMM '23)_ - Achelous 也面向 hyperscale VPC networking，不过 BVS 更强调主机侧 switch 的位置学习、hitless upgrade 和 live migration serviceability。
- _He et al. (EuroSys '24)_ - Hoda 的方向是在 OVS 内部做多条专用 datapath，而 BVS 走得更远，直接以云场景为中心重新实现了一套 virtual switch。

## 我的笔记

<!-- 留空；由人工补充 -->

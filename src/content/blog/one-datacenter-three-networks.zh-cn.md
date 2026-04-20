---
title: "One Datacenter, Three Networks"
oneline: "2026 年的 AI 数据中心不再是一张 Clos 大网，而是协同运作的三张网络——scale-up、scale-out backend、frontend——外加跨 DC 的 WAN，所有超大规模厂商都在朝同一套分层范式收敛。"
topic: datacenter-networking
tags:
  - networking
  - datacenter
  - gpu
  - rdma
  - ml-systems
total_words: 7400
reading_time_minutes: 12
written_by: "Claude Opus 4.7 (Claude Code)"
publish_date: 2026-04-20
draft: false
---

## 核心论点

数据中心网络在教科书里通常被画成一张 folded Clos 胖树：由商用交换机堆叠而成的多级拓扑，对任意一台服务器都近似无阻塞。对传统 CPU 数据中心而言，这张图现在依然成立；可一旦换成 2026 年超大规模厂商真正砸钱的 GPU 数据中心，它就严重跑偏了。今天的 AI 数据中心不再是一张网，而是三张，再加上一张出机房大门的第四张：scale-up fabric（NVLink 或 TPU ICI）像内存一样运行，scale-out backend（InfiniBand、RoCE、或 AWS SRD）承载集合通信，frontend Ethernet 拖着存储和控制面，跨 DC 的 SDN WAN 负责多集群训练。工业界真正关心的问题，已经从「用什么拓扑」变成了「怎么把四张拓扑拼在一起，而又互不干扰」。

## 背景与铺垫

在过去十来年，「数据中心网络」的主流心智模型是 Google 的 Jupiter。2015 年的 [Jupiter Rising](https://conferences.sigcomm.org/sigcomm/2015/pdf/papers/p183.pdf) 记下了五代由商用芯片搭出的多级 Clos fabric——到 2015 年时，30,000+ 台服务器每台接入 40 Gb/s、整体 1.3 Pb/s 的二分带宽，全部跑在集中控制面之下。Meta 的 [F16 / Minipack](https://engineering.fb.com/2019/03/14/data-center-engineering/f16-minipack/) 走的是同一条路子：每个 pod 拆成 16 个 100 G 平面、每机架 1.6 Tb/s，之所以选 16×100 G 而不是 4×400 G，只是因为当时 400 G 光模块的供货和功耗都不配合。AWS 选了不同的传输层、但保留了同样的精神：[Scalable Reliable Datagram](https://www.amazon.science/publications/a-cloud-optimized-transport-protocol-for-elastic-and-scalable-hpc)（SRD）把每个包洒到约 64 条 Ethernet 路径上，再在 Nitro 里把顺序重新拼回来。

那个世界对任何拓扑问题都给出同一个答案——商用芯片堆出的 folded Clos，ECMP 按 5-tuple 哈希，剩下的研究空间几乎只剩拥塞控制。但那个世界已经被替代了：一次训练动辄把 24,576 张 GPU 拉下去跑、一个机架要吃 120 kW，这些场景不再能套进「一张 Clos 打遍天下」的图景里。后面整篇文章，其实就是对替代它的那四层网络做一次实地走访。

## 第一部分 — 工业界的组网范式

### CPU baseline 已经悄悄变成一张光 Clos

通用 CPU fabric 也没有停在 2015 年。Google 2022 年的 [Jupiter Evolving](https://dl.acm.org/doi/pdf/10.1145/3544216.3544265) 讲得很直白：在 spine 层，Jupiter 其实已经不是 Clos 了——aggregation block 之间由 MEMS 光路交换机（OCS）直接互联，上面叠一层 SDN 流量工程。十年下来，这次重构带来 5× 的容量、30% 更低的 capex、41% 更低的功耗、3× 更快的 fabric 重构速度。现役版本已经 [做到 13 Pb/s 的二分带宽](https://cloud.google.com/blog/products/networking/speed-scale-reliability-25-years-of-data-center-networking)，由 512×400 G 的 aggregation block 拼出。Meta 和 AWS 没走光学路线，但他们同样把 plane 数和单端口速率翻了一番又一番。那张「看似无聊」的 Ethernet 数据中心，形状依然无聊，只是它现在跑在 400–800 Gb/s 端口上，而底下的商用芯片越来越像一枚与自己专属传输层共同设计的 ASIC。

### Scale-up：像内存一样工作的那张网

第一层真正「新」的拓扑是 scale-up fabric——把一小撮 GPU 绑得太紧，以至于「内存」和「网络」的界线开始发虚。NVIDIA 的 [GB200 NVL72](https://www.nvidia.com/en-us/data-center/gb200-nvl72/) 把 72 颗 Blackwell GPU 塞进一个 NVLink 域，每机架 9 片 NVLink-Switch tray。每颗 B200 有 18 个 NVLink 端口、每端口 100 GB/s，合计 [每 GPU 1.8 TB/s 双向带宽](https://developer.nvidia.com/blog/nvidia-gb200-nvl72-delivers-trillion-parameter-llm-training-and-real-time-inference/)——大约是一张 400 Gb/s NIC 的 36 倍。再扩展 NVLink-Switch 就能拉到 576-GPU、总和 >1 PB/s 的大域。真正值得记的数字是这种不对称：任何一条 TP / CP 轴如果落在 NVLink 域内部，跑的是内存带宽速度；一旦溢出去，带宽直接掉一个数量级。

Google 的答案在拓扑上完全不同。[TPU v4](https://arxiv.org/abs/2304.01433) 把 4096 颗芯片组织成一张三维 torus：64 个每块 64 颗的 cube，cube 之间由 48 台 Palomar 136 端口 3D-MEMS OCS 串起来，你可以在配置时挑选 torus 形状（包括 twisted-torus）。OCS 加光学器件的成本不到系统总成本的 5%，功耗不到 3%，却能在 all-to-all 上拿到相对普通 torus 1.3–1.6× 的吞吐。后继的 [TPU v5p](https://cloud.google.com/blog/products/ai-machine-learning/introducing-cloud-tpu-v5p-and-ai-hypercomputer) 把这套扩到每 pod 8,960 颗芯片，单颗 ICI 带宽 4,800 Gb/s，还正式写进文档的 [OCS-based ICI resiliency](https://docs.cloud.google.com/tpu/docs/v5p) 能绕过坏掉的光链路。NVIDIA 和 Google 走的拓扑天差地别，但结论是同一个——该跑最快的那张网，就是 scale-up 那张。

### Scale-out backend：有目的的 rail-optimized 胖树

一旦出了 NVLink 或 ICI 域，带宽立刻掉一个台阶，训练任务就得面对这道悬崖。工业界的答案是一张专用、按 rail 排列的 backend fabric。NVIDIA 的 [DGX SuperPOD H100 参考架构](https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-h100/latest/network-fabrics.html) 把每 32 节点为一个 Scalable Unit：对任一节点而言，它 8 张 GPU NIC 中的每一张，都只要一跳就能到其他 31 个节点对应位号的那张 NIC。跨 rail、跨 SU 才到 spine 去绕一次。即将到来的 [B300 / Quantum-X800 架构](https://docs.nvidia.com/dgx-superpod/reference-architecture/scalable-infrastructure-b300-xdr/latest/network-fabrics.html) 把 rail 对齐单元扩到 72 个节点、端口 800 Gb/s。这个形状不是装饰——NCCL 生成 AllReduce 调度时，就默认 rail 是对齐的。[Meta 的 SIGCOMM '24 论文](https://engineering.fb.com/wp-content/uploads/2024/08/sigcomm24-final246.pdf) 报告，在跑 Llama 3 的 24,576-GPU RoCE 集群里，一旦 Enhanced-ECMP 尊重 QP affinity、每对节点之间把流拆成 16 个 QP，AllReduce 能拿到约 40% 的提升。

具体谁用什么会有差异，但骨架恒定。[Meta 那对 24K-GPU 的 GenAI 双子集群](https://engineering.fb.com/2024/03/12/data-center-engineering/building-metas-genai-infrastructure/) 把 Grand Teton GPU 同时接到一张 RoCE backend（Arista + Minipack2）和一张 InfiniBand Quantum-2 backend——同一套平台，两种传输。xAI 的 100K-GPU 集群 [Colossus](https://nvidianews.nvidia.com/news/spectrum-x-ethernet-networking-xai-colossus) 用的是 NVIDIA Spectrum-X，SN5600 交换机端口 800 Gb/s；按 NVIDIA 的说法，三级 fabric 下有效吞吐能达到 95%，而普通 Ethernet 在这个规模上只能跑到 60%。底层的物理规律——rail 对齐胖树、每端口高 radix、每颗 GPU 配一张 NIC——已经是 backend 设计的工业基线。

### Frontend / backend 的分离是显式的，不是附带的

backend 和 frontend 之间的分离，现在不再是部署细节，而是写进参考架构的基本原则。NVIDIA 的 [GB200 SuperPOD 架构](https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-gb200/latest/network-fabrics.html) 明文列出四张 fabric：Compute Fabric（InfiniBand 或 Spectrum-X，rail-optimized）、Storage Fabric（独立的 IB 或 RoCEv2）、带内管理 Ethernet、以及完全隔离的带外管理平面。GB200 计算 tray 上，4 张 ConnectX-7 坐在 backend，2 张 BlueField-3 坐在存储+带内管理平面——拆分在 NIC 这一层就硬性落地。[Meta 的 RoCE 博客](https://engineering.fb.com/2024/08/05/data-center-engineering/roce-network-distributed-ai-training-at-scale/) 给出的理由是第一性的：一张专用 backend 让 AI fabric 能独立于通用 DC 网演进，而这是必要的，因为两张网的流量矩阵本质不同——backend 主要是梯度同步带来的少量 burst 大流，frontend 则是大量小流加上存储的长读。

### 在无损 Ethernet 上跑 RDMA，学费叫拥塞控制

不用 InfiniBand 而把 RDMA 放到 Ethernet 上跑，账单以拥塞控制复杂度的形式偿还。Microsoft 的 [DCQCN](https://conferences.sigcomm.org/sigcomm/2015/pdf/papers/p523.pdf) 和 [RDMA over Commodity Ethernet at Scale](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/11/rdma_sigcomm2016.pdf) 是所有人引用的经典：PFC 一旦让 pause 住的链路形成有向环就会死锁，一场 [pause 帧风暴足以打垮整张 fabric](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/11/rdmahotnets16.pdf)。阿里巴巴给出的答卷是 [HPCC](https://liyuliang001.github.io/publications/hpcc.pdf)：用网内遥测让 sender 一步算出精确的速率调整，相较 DCQCN 把 FCT 砍掉最多 95%。把 lossless Ethernet 跑起来的「科研税」大致就是这个比率——每出一次生产事故，就多一篇 SIGCOMM。

### 跨数据中心：SDN WAN，如今再一次为 AI 分叉

第四张网在机房与机房之间。Google 2013 年的 [B4](https://conferences.sigcomm.org/sigcomm/2013/papers/sigcomm/p3.pdf) 证明了集中式 SDN WAN + 流量工程可以把跨 DC 链路推到接近 100% 利用率——比传统 WAN 高 2–3×；[B4-After](https://research.google/pubs/b4-and-after-managing-hierarchy-partitioning-and-asymmetry-for-availability-and-scale-in-googles-software-defined-wan/) 又过几年：33 个节点、100× 的流量，靠分层 TE 和两阶段 flow-matching 把 8× 的 TE 规则塞进同一款交换芯片。Meta 把它拆成两条：给 DC-to-DC 走的 MPLS-based [Express Backbone（EBB）](https://dl.acm.org/doi/pdf/10.1145/3603269.3604860)，基于 Open/R 做集中式 TE；DC-to-POP 走另一条 Classic Backbone。2025 年那篇 [10X Backbone](https://engineering.fb.com/2025/10/16/data-center-engineering/10x-backbone-how-meta-is-scaling-backbone-connectivity-for-ai/) 的博客，把眼下的扩容压力明确挂在 AI 头上。[AWS 的全球网络](https://aws.amazon.com/about-aws/global-infrastructure/global-network/) 则在自研硬件上铺了约 2000 万公里光纤，跑 400 GbE，所有机房间流量做物理层加密。

AI 要用 WAN 训练曾经被当成是理论议题，[Pathways](https://arxiv.org/pdf/2203.12533) 和 [PaLM](https://arxiv.org/pdf/2204.02311) 第一次把它跑成真的：PaLM 540B 用两个 TPU v4 pod、共 6,144 颗芯片训练，pod 内 SPMD 走 ICI，pod 之间的梯度交换走普通 DCN，全部由单 controller runtime 调度。[Gemini 的技术报告](https://storage.googleapis.com/deepmind-media/gemini/gemini_v2_5_report.pdf) 也确认：多 pod、多 DC 训练已经是前沿模型的日常。WAN 在不知不觉间成了训练 fabric 的第四层，而这反过来改写了下面三层的思维方式——既然跨 pod 那一段是整条链路里最慢的，底下三层的调度就得刻意避开让它停顿。

### Ultra Ethernet：工业界押下的再收敛赌注

如果说今天的世界里传输协议过多，那么 Ultra Ethernet Consortium 的 [Specification 1.0](https://ultraethernet.org/uec-2025-in-review-preparing-for-what-comes-next-a-letter-from-uecs-chair/)（2025 年 6 月 11 日发布）就是工业界试图把它们重新装回同一个盒子里。UEC 的核心是 Ultra Ethernet Transport（UET），562 页的协议栈背后站着 [AMD、Arista、Broadcom、Cisco、HPE、Intel、Meta 和 Microsoft](https://www.prnewswire.com/news-releases/ultra-ethernet-consortium-uec-launches-specification-1-0-transforming-ethernet-for-ai-and-hpc-at-scale-302478685.html)。路线图直指当前 backend 的所有痛点：拥塞管理、小消息性能、scale-up 传输、以及网内集合通信。UEC 究竟是把 scale-up 和 backend 都吞掉，还是仅仅统一 backend，是数据中心网络今天最大的一桩公开赌局。

### Optical Circuit Switch：fabric 形状的那个开关

再往底下看，超大规模厂商已经把光路交换当作一等的 fabric 基元。Google 的 [Mission Apollo](https://arxiv.org/abs/2208.10041) 描述了 136×136 的 Palomar 3D-MEMS OCS：2013 年起在生产环境里跑，每台功耗约 108 W，而同口数的 EPS 在 3 kW 级别；随后 [Lightwave Fabrics](https://dl.acm.org/doi/10.1145/3603269.3604836)（SIGCOMM '23）讲清楚了现在 Jupiter 和 TPU 互连共用的那一套集成栈。OCS 早不是研究新物，而正是 Google 能在 TPU v5p pod 里绕过一条坏光链路继续训练的那颗螺丝。

## 第二部分 — 把拓扑变成一个运行时变量

如果第一部分讲的是共识，第二部分就是正在被撬开的前线。近两年里真正有意思的论文都在做同一件事——它们不再把拓扑当成部署时的既定事实，而是把它当成运行时可控的变量。

### 共同综合：拓扑与集合调度一起设计

[Efficient Direct-Connect Topologies for Collective Communications](../papers/nsdi-2025/efficient-direct-connect-topologies-for-collective-communications.md)（NSDI '25）直接否掉了「先挑拓扑再挑调度」的前提。它用保持性质的图扩张与多项式时间的 BFB 调度生成器，在 (topology, schedule) 这对向量上搜 Pareto 前沿，并在接近 1000 节点的规模下拿出相对 ShiftedRing 最多 56× 的 AllReduce 增益——而那是 NCCL 默认调度早就跑不动的区间。这种取法天然契合光学 ML 集群、TPU 式 torus，以及所有端口数紧缺的 fabric：它在说，值得优化的单位是「拓扑 + 调度」，而非其中任一方。

### 可重构 torus fabric

[Morphlux](../papers/asplos-2026/reconfigurable-torus-fabrics-for-multi-tenant-ml.md)（ASPLOS '26）把光学可编程性下沉到服务器尺度。它在每台 4 加速器服务器下面塞了一块光 interposer，再由软件控制器重分配 sub-rack 的带宽、把非连续的空闲服务器拼成一张逻辑 torus，并在某颗加速器挂掉时直接在机架内换配线，而不需要把整个任务疏散走。基于公开 TPU v4 slice 分布的仿真里，Morphlux 把最多 50% 原本搁浅的 `Y` 维带宽拿回来，服务了 32-TPU 这类被默认 TPU / SiPAC 调度器拒绝约 75% 的请求，并在单芯片故障时用约 1.2 秒完成恢复。它的主张是：一旦带宽分配变得可编程，「torus 还是灵活性」这道选择题自己会消解。

### Server 内部的 fabric 也属于 server 间路径

[FuseLink](../papers/osdi-2025/enabling-efficient-gpu-communication-over-multiple-nics-with-fuselink.md)（OSDI '25）攻的是同一个问题的另一面角。它观察到，当机间流量本身偏斜时，一颗繁忙的 GPU 可以通过 NVLink 借用同机其他 GPU 的空闲 NIC。机制上有两点：用虚拟内存 remap——应用照常写 NCCL buffer，但 buffer 物理上落在 relay GPU 上；再加一条优先级感知的调度——NIC 的本主可以随时把它收回。在 8-GPU、每机 8×400 Gbps NIC 的配置上，机间点对点带宽从 NCCL+PXN baseline 的 49 GB/s 拉到 212 GB/s。这篇论文把一个隐含的新观念说得最清楚：NVLink fabric 和 RDMA fabric 是同一条路径上的两段，runtime 本就应该合起来看。

### 传输层依然被反复重写

几乎每一届顶会的 networking track 都会出几篇重构 RoCE / InfiniBand 传输层的论文。[SIRD](../papers/nsdi-2025/sird-a-sender-informed-receiver-driven-datacenter-transport-protocol.md) 与 [Pyrrha](../papers/nsdi-2025/pyrrha-congestion-root-based-flow-control-to-eliminate-head-of-line-blocking-in-datacenter.md)（NSDI '25）分别从 sender 侧和 receiver 侧解 HOL 阻塞；[Fork](../papers/eurosys-2025/fork-a-dual-congestion-control-loop-for-small-and-large-flows-in-datacenters.md)（EuroSys '25）跑一套双环——小流由 sender 拉、大象流给 receiver credits。[PrioPlus](../papers/eurosys-2025/enabling-virtual-priority-in-data-center-congestion-control.md) 在一条物理队列里用延迟通道模拟多级严格优先级，绕开对交换机的改动。[White-boxing RDMA](../papers/nsdi-2025/white-boxing-rdma-with-packet-granular-software-control.md) 和 [ScalaCN](../papers/nsdi-2025/mitigating-scalability-walls-of-rdma-based-container-networks.md) 则更往下：把 RNIC 内部的控制点暴露出来，让软件做到包粒度的调度，也让人能侦测 RDMA 容器网络在规模上的那堵「峭壁」。[Söze](../papers/osdi-2025/s-ze-one-network-telemetry-is-all-you-need-for-per-flow-weighted-bandwidth-allocation-at.md)（OSDI '25）更极端：仅凭「每包最大排队时延」这一个信号，就做出分布式的加权 max-min 带宽分配——对 HPCC 那套重遥测的一种最简主义回应。统一的旋律只有一句：拓扑还没定稿，跑在它上面的传输层也就不会定稿。

### 集合通信调优与训练可观测性

既然拓扑可变，集合通信库就得自己发现它。[AutoCCL](../papers/nsdi-2025/autoccl-automated-collective-communication-tuning-for-accelerating-distributed-and.md)（NSDI '25）按任务在线调优 NCCL，把实现选择和资源旋钮拆开；[MSCCL](../papers/asplos-2026/msccl-rethinking-gpu-communication-abstractions-for-ai-inference.md)（ASPLOS '26）把集合通信构造在接近硬件的 channel 抽象加一套 DSL 之上，让推理拿到接近定制实现的性能，而不用绑在厂商栈上。可观测性也升级成了一等的拓扑问题：[Holmes](../papers/nsdi-2025/holmes-localizing-irregularities-in-llm-training-with-mega-scale-gpu-clusters.md)、[Mycroft](../papers/sosp-2025/mycroft-tracing-dependencies-in-collective-communication-towards-reliable-llm-training.md) 和 [ByteRobust](../papers/sosp-2025/robust-llm-training-infrastructure-at-bytedance.md) 都从同一处直觉切入：一个 10K-GPU 训练任务的故障信号，往往先以一种异常的集合通信依赖形态冒头。[SimAI](../papers/nsdi-2025/simai-unifying-architecture-design-and-performance-tuning-for-large-scale-large-language.md) 则反向行事，复用真实训练框架与 NCCL，在包粒度上模拟 LLM 训练，与真机对齐率达到 98.1%——一件能对着「尚未建成」的拓扑提前推理的工具。

### 对着生产场景开的那几扇减压阀

最后还有两篇偏向补救角度的论文。[OptiReduce](../papers/nsdi-2025/optireduce-resilient-and-tail-optimal-allreduce-for-distributed-deep-learning-in-the-cloud.md)（NSDI '25）处理的是公有云里拿不到专用 backend 时的尾时延 AllReduce；Google 那篇 [热点感知调度](../papers/nsdi-2025/preventing-network-bottlenecks-accelerating-datacenter-services-with-hotspot-aware.md)（NSDI '25）则更朴素——只把任务和存储往「凉」的机架放，就把持续热 ToR 砍掉 90%、Colossus 的 p95 网络时延降低 50–80%。两篇都在提醒：绝大多数负载其实还生活在「一张网、一套拓扑」的那个世界里，而即便在那里，「拓扑感知的调度」仍然是一根尚未真正拧紧的杠杆。

## 反方证据

「三张网」这条主张并非毫无异议。AWS 的 [SRD](https://aws.amazon.com/blogs/hpc/in-the-search-for-performance-theres-more-than-one-way-to-build-a-network/) 是最响亮的反面例子。AWS 给出的（并且至今仍在出货的）答案是一张普通 Ethernet fabric，把流量以自定义传输层洒到 64 条路径上，而不是另起一张 InfiniBand 或 RoCE backend。如果 SRD 在 GB200 级别的集群尺度上也能撑起集合通信，那么「backend 必须独立」这个前提就会退化为「一张 fabric，一套更聪明的传输层」。

Ultra Ethernet 是第二股压力。[UET](https://arxiv.org/html/2508.08906v1) 的明确目标就是让 backend 和通用 Ethernet 重新变成同一张网。如果它真的走通了，frontend / backend 之间的分界就从物理墙落成一条流量类别的边界，本文里不少拓扑上的切分都会失去受力点。

还有一股更安静的反推来自 scale-up 那一侧。NVLink 域从 8 长到 72，再规划到 576。每次长大，都会蚕食原本归属于 scale-out backend 的地盘：一旦整个模型能塞进 NVLink 域，backend 只需要跑数据并行副本，对拓扑的要求就放松了很多。把这条曲线外推到头，「scale-up 吞掉 scale-out」是一种可信的未来——唯一的反证是，模型规模的那条曲线也在长，两条线被挤得很近。

这三条里没有哪一条强到足以把 2026 年的「三张网」图景整体推翻。但每一条都是正在进行的争论，今天选拓扑的系统架构师应当默认：边界还会再挪动。

## 这意味着什么

对平台建设者来说，现在已经不能「挑一张网」。你一次要挑四张，而且要设计好它们怎么分摊资源——哪张 NIC 坐在哪一层，哪些交换机允许在什么 pause 机制下死锁，哪些流归哪一套传输层。NVIDIA 那套 SuperPOD 参考架构之所以有价值，正是因为它把这些选择以连接器的粒度明文规定下来了。

对做研究的人来说，真正有意思的拓扑工作已经上移了一层。图与调度的共同综合（direct-connect 那篇）、可编程光学（Morphlux）、运行时可调的路径选择（FuseLink）其实在问同一个问题——如果拓扑是个变量，那这个变量的控制回路长什么样？关于 Clos 还是 fat-tree 的老争论，对 CPU 集群是真的结束了；对 AI 集群则正在被一场关于「可重构性」的新辩论取代。

对整个领域来说，未来两年会决定工业界是保留四张网，还是把它们合并回一张。Ultra Ethernet 是响度最大的再收敛赌注；NVLink 域的膨胀是一条安静的再收敛线。无论谁胜出，2028 年的「数据中心网络拓扑」都不会再长成 2015 年 Jupiter 那张图——它要么是四层终于协商出一套共同传输层，要么是一层终于把所有事都统一了。研究议程的走向，早已随着这两种未来中哪一种兑现而开始分叉。

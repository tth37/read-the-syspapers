---
title: "One Datacenter, Three Networks"
oneline: "2026 年的数据中心已经不再是一张 folded Clos：通用 DC 仍跑在一张 IP fabric 上，而 AI DC 则层叠出 scale-up、scale-out backend、frontend 以及跨 DC 的 WAN，四张网各有明确的拓扑配方。"
topic: datacenter-networking
tags:
  - networking
  - datacenter
  - gpu
  - rdma
  - ml-systems
total_words: 9600
reading_time_minutes: 14
written_by: "Claude Opus 4.7 (Claude Code)"
publish_date: 2026-04-20
draft: false
---

## 核心论点

数据中心网络在教科书里通常被画成一张 folded Clos 胖树：由商用交换机堆叠而成的多级拓扑，对任意一台服务器都近似无阻塞。对运行 EC2、S3、Aurora、Spanner 这类非 AI 负载的通用数据中心来说，这张图依然成立；可一旦换成 2026 年超大规模厂商真正砸钱的 GPU 数据中心，它就严重跑偏了。今天的 AI 数据中心不再是一张网，而是三张，再加上一张出机房大门的第四张：scale-up fabric（NVLink 或 TPU ICI）像内存一样运行，scale-out backend（InfiniBand、RoCE、或 AWS SRD）承载集合通信，frontend Ethernet 拖着存储和控制面，跨 DC 的 SDN WAN 负责多集群训练。工业界真正关心的问题，已经从「用什么拓扑」变成了「怎么把四张拓扑拼在一起，而又互不干扰」。

## 背景与铺垫

在过去十来年，「数据中心网络」的主流心智模型是 Google 的 Jupiter——IP fabric、folded Clos、ECMP 按 5-tuple 哈希、商用芯片——它现在是人人都要继承的基线。本文接下来做一次规格级别的走访：(a) 今天通用 DC 里这张基线到底长什么样；(b) AI DC 在它之上又叠了什么。我们尽量给出具体的拓扑配方，让读者能看清哪台节点通过哪张 fabric 连到哪里。

## 第一部分 — 工业界的组网范式

### 通用 DC：folded Clos 的具体参数

构造的基本单位仍是**机架**。超大规模机架里装 20–48 台服务器，接到同一台 **Top-of-Rack（ToR）** 交换机。典型的南向端口：48 个 25/50/100 Gbps 服务器端口；典型的北向上联：4–8 条 400 Gbps 上联到下一层。ToR 的超额订阅在超大规模生产 pod 里一般是 1:1，企业环境则常见 2:1–3:1。ToR 之上还有两层：**leaf** 把约 32 台 ToR 聚合成一个 pod，**spine** 把不同 pod 互联。整体是一张 folded Clos——路由 L3 下沉到 ToR，ECMP 按 5-tuple 哈希。

三个具体实例：

- **Meta F16。** 每个 pod 被接成 16 个并行的 100 G 平面。每机架的 ToR 有 16 条北向上联，一条对应一个平面，落到 16 台 fabric switch（FSW）上——FSW 由 Minipack ASIC 构成（128×100 G），FSW 再上联 spine。选 16×100 G 而不是 4×400 G 是明确的决定：那时 400 G 光模块的成本和功耗还跟不上机队规模。见 [F16 / Minipack](https://engineering.fb.com/2019/03/14/data-center-engineering/f16-minipack/)。
- **Google Jupiter（现役）。** 顶层已经不是纯 Clos：aggregation block（512×400 Gbps 客户端口，单块 204.8 Tb/s 双向）之间由 MEMS OCS 光路交换机互联，SDN 流量工程按需调整 block 之间的容量。64 块 × 400 Gbps = 每张 fabric 约 13 Pb/s 二分带宽。见 [Jupiter Evolving](https://dl.acm.org/doi/pdf/10.1145/3544216.3544265) 和 [Speed, scale, reliability: 25 years of datacenter networking](https://cloud.google.com/blog/products/networking/speed-scale-reliability-25-years-of-data-center-networking)。
- **AWS EC2。** 每台服务器装一张 ENA NIC，25/50/100/200 Gbps 视实例类型而定。ENA 跑的是 AWS 自研的 [SRD](https://www.amazon.science/publications/a-cloud-optimized-transport-protocol-for-elastic-and-scalable-hpc)，把包洒到普通 Ethernet Clos 上的最多 64 条 ECMP 路径，再在 Nitro 里重新排序。没有 RoCE、没有 PFC、没有 InfiniBand。

### DBMS、存储、搜索集群跑的是同一张 Clos

不同负载的物理拓扑其实区别不大，差异主要体现在超额订阅比、副本布置和传输层选择上，而不在于布线本身。

- **分布式 OLTP（Spanner、CockroachDB、Aurora）。** 副本被故意拉开放在不同机架和不同可用区，以隔离故障域，于是每一轮 Paxos 都要付 leaf-spine 的跳数。AWS Aurora 把计算和存储拆到同一张 Clos 的不同层，存储分片在 3 个 AZ 之间做 6 副本复制。跨 AZ 时延（约 1–2 ms）常常是提交延迟的主导项，物理拓扑仍然是一张普通 Clos。
- **对象存储（S3、Colossus）。** 存储机架像计算机架一样挂在同一张 Clos 上。流量是高度不对称的——读流量聚合向计算机架——所以存储机架的北向上联要按出口方向设计。存储侧的超额订阅往往比计算侧更激进，因为 SLA 是聚合吞吐，不是尾时延。
- **搜索 / OLAP（Bigtable、BigQuery、F1）。** 典型的 fan-out 流量：一个 leaf 查询节点向几百个 worker 分片广播，再等最慢的回来。尾时延主导一切。这也是现代 Ethernet fabric 优先优化 p99 而不是峰值吞吐的最大原因。

### 传统 DC，其余的工程细节

- **路由到 ToR 走 L3。** VLAN 用得很少。租户隔离走 overlay（VXLAN 或 Geneve），跑在 IP fabric 之上。AWS VPC、Azure VFP、Google Andromeda 都是这个路数——overlay 是软件构造，物理 fabric 是同一张 Clos。
- **NIC 就是「租户网」与「数据中心网」的边界。** AWS Nitro、Azure SmartNIC、Google Titanium 负责终止 overlay、执行安全组、卸载 TCP。宿主机内核只看到一块 SR-IOV vNIC，下面的一切归 Nitro 管。
- **东西向流量约 80%。** 南北向（DC ↔ 互联网）走独立的 edge 路由层，这也是 Meta、Google、AWS 都会为 DC-to-DC 与 DC-to-Internet 各跑一张独立 WAN 的原因（详见下文 WAN 小节）。

### GPU DC：scale-up fabric（一个机架内部）

AI 机架从机架这一层开始，就已经脱离了单张 Clos 的图景。

**GB200 NVL72（NVIDIA）。** 每机架 18 台 compute tray，每台 tray 装 2 颗 Grace + 4 颗 Blackwell，合计每机架 36 Grace + 72 Blackwell。每颗 B200 有 18 个 NVLink 端口 × 100 GB/s，合计每 GPU 1.8 TB/s 双向带宽。每机架 9 片 NVLink-Switch tray（每片是一台 144 端口、每端口 100 GB/s 的非阻塞交换机），把 72 颗 GPU 接成一张单一的 NVLink 域——任意一颗 GPU 只需一跳 NVLink-Switch 就能到达同机架的任意另一颗，整体约 130 TB/s 聚合带宽。通过外部 NVLink-Switch 扩展可以把域扩到 576 颗 GPU、>1 PB/s。见 [GB200 NVL72](https://www.nvidia.com/en-us/data-center/gb200-nvl72/) 和 [NVIDIA technical blog](https://developer.nvidia.com/blog/nvidia-gb200-nvl72-delivers-trillion-parameter-llm-training-and-real-time-inference/)。

**TPU v4 pod（Google）。** 4096 颗芯片组成一张三维 torus。构造砖是 4×4×4 = 64 芯片的 cube，每颗芯片有 6 条 ICI 链路（±X/±Y/±Z 各一条），单方向约 50 GB/s。64 个 cube 由 48 台 Palomar 3D-MEMS OCS（每台 136 端口）缝合在一起，能在配置时挑选 inter-cube 拓扑——包括 twisted-torus，相对普通 torus 在 all-to-all 上能拿 1.3–1.6× 吞吐。TPU v5p 把这套扩到每 pod 8,960 颗芯片，单颗 ICI 带宽 4,800 Gb/s。见 [TPU v4（ISCA '23）](https://arxiv.org/abs/2304.01433) 和 [v5p 文档](https://docs.cloud.google.com/tpu/docs/v5p)。

真正值得记的数字是这种不对称：一颗 B200 在 NVLink 上是 1.8 TB/s，在单张 ConnectX-7 NIC 上只有约 50 GB/s。任何一条并行轴（TP、CP）如果能落在 NVLink 域内，就跑内存带宽速度；一旦溢出去，带宽直接掉 30× 以上。

### GPU DC：scale-out backend（跨机架）

出了 NVLink 或 ICI 域，GPU 之间必须走一张专用的 NIC fabric。

**DGX SuperPOD H100（NVIDIA 参考架构）。** 单位是 **Scalable Unit（SU）**，每 SU 32 台节点。每台节点装 8 颗 H100 + 8 张 ConnectX-7 NIC（400 Gbps，InfiniBand NDR）。fabric 走 **rail-optimized**：对 rail `k` ∈ {1..8}，每台节点的第 k 张 NIC 都接到同两台 rail-`k` leaf switch 上（一左一右做冗余）。于是 rail `k` on 节点 A 到 rail `k` on 节点 B 只需一跳 leaf。跨 rail（例如节点 A 的 GPU 1 ↔ 节点 B 的 GPU 3）必须绕到 spine。4 个 SU（128 节点、1024 GPU）组成一个 SuperPOD；规模再大就加 spine 层。即将到来的 [B300 / Quantum-X800](https://docs.nvidia.com/dgx-superpod/reference-architecture/scalable-infrastructure-b300-xdr/latest/network-fabrics.html) 把 rail 对齐单元扩到 72 个节点、端口 800 Gbps。见 [SuperPOD H100 fabric 文档](https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-h100/latest/network-fabrics.html)。

**Meta GenAI 集群（24,576 GPU，2024）。** Grand Teton 服务器，每台 8 GPU + 8×400 Gbps NIC。两个版本共享机架硬件：一个用 Arista 7800 + Minipack2 跑 RoCEv2，另一个用 NVIDIA Quantum-2 跑 InfiniBand。两者都是 rail 对齐的胖树，与 Meta 的通用 DC fabric **物理分离**。在 RoCE 变体里，每对节点之间的流被拆成 16 个 QP，ECMP 按 destination QP 哈希（通过 UDF）——这套「Enhanced-ECMP」相较普通 5-tuple ECMP 能带来最多 40% 的 AllReduce 提升。见 [SIGCOMM '24 论文](https://engineering.fb.com/wp-content/uploads/2024/08/sigcomm24-final246.pdf) 和 [engineering 博客](https://engineering.fb.com/2024/08/05/data-center-engineering/roce-network-distributed-ai-training-at-scale/)。

**xAI Colossus（100K+ H100，Memphis）。** Spectrum-X 平台：SN5600（Spectrum-4）800 Gbps 交换机 + BlueField-3 SuperNIC。三级 fabric（ToR → leaf → spine）。NVIDIA 报告有效吞吐率能达到 95%，而普通 Ethernet 在这个规模上只能跑到 60%。见 [NVIDIA 的 Colossus 公告](https://nvidianews.nvidia.com/news/spectrum-x-ethernet-networking-xai-colossus)。

### GPU DC：显式的 frontend / backend 分离

现代 AI 机架的每台节点至少跑两张物理网络，归属在 NIC 这层硬性落地。以 **GB200 compute tray** 为例：

- **Compute（backend）平面。** 4 张 ConnectX-7 NIC（每 2 颗 GPU 共享一张，经 PCIe Gen5），接 InfiniBand 或 Spectrum-X 的 compute fabric。承载 AllReduce、AllGather、P2P 集合通信。
- **存储 + 带内管理平面。** 2 张 BlueField-3 DPU，接独立的 Ethernet 存储/管理 fabric。承载 checkpoint I/O、数据集 ingest、VPC overlay、调度器（Slurm、K8s）。
- **带外管理。** 第三张隔离的 Ethernet，用于 IPMI/BMC。

见 [GB200 SuperPOD fabric 文档](https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-gb200/latest/network-fabrics.html)。两张平面的传输、拥塞控制机制乃至交换机供应商都可以不同，分离是架构层面的决定。

### 跨 DC：按流量类别切分的 SDN WAN

每家超大规模厂商都至少跑两张 WAN，按流量类别切开。跨 DC 训练走内部那张（DC-to-DC），不是面向互联网那张。

- **Google B4**（内部 WAN）：OpenFlow + SDN 跑在商用芯片上，集中式 TE 能把链路峰值利用率推到接近 100%；[B4-After](https://research.google/pubs/b4-and-after-managing-hierarchy-partitioning-and-asymmetry-for-availability-and-scale-in-googles-software-defined-wan/) 把它扩到 33 个节点，用分层 TE 和两阶段 flow matching 把 8× 的规则塞进同一款交换芯片。与 Google 的对外 WAN B2 是两张网。见 [B4（SIGCOMM '13）](https://conferences.sigcomm.org/sigcomm/2013/papers/sigcomm/p3.pdf)。
- **Meta Express Backbone（EBB）。** MPLS-based、多平面，自约 2015 起承载 Meta 100% 的 DC-to-DC 流量。控制面混合：集中式 MPLS-TE 规划 gold/silver/bronze LSP，分布式 Open/R agent 预装备份路径做本地快速切换。与 DC-to-POP 的 Classic Backbone（CBB）是两张网。见 [EBB（SIGCOMM '23）](https://dl.acm.org/doi/pdf/10.1145/3603269.3604860) 和 [2025 年的 10X Backbone 博客](https://engineering.fb.com/2025/10/16/data-center-engineering/10x-backbone-how-meta-is-scaling-backbone-connectivity-for-ai/)。
- **AWS Global Network。** 约 2000 万公里光纤，400 GbE 内部标准，自研光传输，所有机房间流量做物理层加密。见 [AWS Global Network](https://aws.amazon.com/about-aws/global-infrastructure/global-network/)。

**AI 在 WAN 上的训练。** [Pathways](https://arxiv.org/pdf/2203.12533) 加 [PaLM](https://arxiv.org/pdf/2204.02311) 把 540B 参数训在两个 TPU v4 pod 上（每 pod 3,072 芯片、768 主机）：pod 内 SPMD 走 ICI，pod 间梯度交换走普通 DCN，全部由单 controller runtime 调度。[Gemini 的技术报告](https://storage.googleapis.com/deepmind-media/gemini/gemini_v2_5_report.pdf) 确认多 pod、多 DC 训练在前沿模型上已经是日常。WAN 就这样成了训练 fabric 的第四层。

### 小结：每一层谁连谁、用什么 fabric

| 层 | 连接谁 | Fabric / 传输 | 2026 年规模实例 |
|---|---|---|---|
| Scale-up | 机架内部的 GPU | NVLink + NVSwitch，或 TPU ICI torus | GB200 NVL72（72 GPU、每 GPU 1.8 TB/s）；TPU v5p pod（8,960 芯片） |
| Scale-out backend | 跨机架的 GPU NIC | InfiniBand NDR/XDR、RoCEv2、或 AWS SRD | DGX SuperPOD、Meta 24K RoCE、xAI Colossus、AWS EFA |
| Frontend（DC） | 其余一切——存储、ingest、VPC、管理 | L3 Ethernet Clos + overlay | EC2、S3、Lambda、所有 CPU 负载 |
| 跨 DC WAN | DC 与 DC | MPLS + 集中式 SDN TE | Google B4、Meta EBB、AWS Global Network |

### 无损 Ethernet 的拥塞控制（跑 RoCE 的那张税单）

RoCEv2 要无损 fabric，也就意味着必须跑 PFC，进而意味着必须有一套拥塞控制协议让队列短到 PFC 不会连锁触发。

- **DCQCN**（Microsoft）：ECN-based 速率控制，与 PFC 协同设计。见 [DCQCN](https://conferences.sigcomm.org/sigcomm/2015/pdf/papers/p523.pdf) 和 [RDMA over Commodity Ethernet at Scale](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/11/rdma_sigcomm2016.pdf)。
- **HPCC**（Alibaba）：基于 INT 的精确速率更新。相较 DCQCN，FCT 最多缩短 95%。见 [HPCC](https://liyuliang001.github.io/publications/hpcc.pdf)。
- **E-ECMP**（Meta）：ECMP 按 QP 哈希，每对节点 16 个 QP。AllReduce 最多提升 40%。见 [Meta RoCE 论文](https://engineering.fb.com/wp-content/uploads/2024/08/sigcomm24-final246.pdf)。

PFC 死锁是常在的尾部风险：pause 住的链路一旦形成有向环，整张 fabric 会死住。见 [Microsoft HotNets '16](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/11/rdmahotnets16.pdf)。

### Ultra Ethernet Consortium（再收敛的赌注）

[UEC Specification 1.0](https://ultraethernet.org/uec-2025-in-review-preparing-for-what-comes-next-a-letter-from-uecs-chair/) 于 2025 年 6 月 11 日发布，562 页，核心是 Ultra Ethernet Transport（UET）。背后的公司：[AMD、Arista、Broadcom、Cisco、HPE、Intel、Meta、Microsoft](https://www.prnewswire.com/news-releases/ultra-ethernet-consortium-uec-launches-specification-1-0-transforming-ethernet-for-ai-and-hpc-at-scale-302478685.html)。路线图锚定了 backend 的几个痛点：拥塞管理、小消息性能、scale-up 传输、网内集合通信。若走通，scale-up / backend / frontend 的分离就会从物理边界退化为一张 fabric 上的流量类别边界。

### Optical Circuit Switch（OCS）

超大规模厂商已经把 MEMS-based 光路交换当作一等的 fabric 基元。

- **Palomar 3D-MEMS OCS**（Google）：136×136 端口，每台功耗约 108 W，而同口数的 EPS 在 3 kW 量级。自 2013 年起在生产环境里跑。见 [Mission Apollo](https://arxiv.org/abs/2208.10041) 和 [Lightwave Fabrics](https://dl.acm.org/doi/10.1145/3603269.3604836)。
- **Jupiter 的 aggregation 层** 已经由 Palomar 承担。
- **TPU v4** 用 48 台 Palomar 缝合 3D-torus 的 inter-cube 链路，成本不到系统总成本的 5%，功耗不到 3%。

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

既然拓扑可变，集合通信库就得自己发现它。[AutoCCL](../papers/nsdi-2025/autoccl-automated-collective-communication-tuning-for-accelerating-distributed-and.md)（NSDI '25）按任务在线调优 NCCL；[MSCCL](../papers/asplos-2026/msccl-rethinking-gpu-communication-abstractions-for-ai-inference.md)（ASPLOS '26）把集合通信构造在接近硬件的 channel 抽象加一套 DSL 之上，让推理拿到接近定制实现的性能，而不用绑在厂商栈上。可观测性也升级成了一等的拓扑问题：[Holmes](../papers/nsdi-2025/holmes-localizing-irregularities-in-llm-training-with-mega-scale-gpu-clusters.md)、[Mycroft](../papers/sosp-2025/mycroft-tracing-dependencies-in-collective-communication-towards-reliable-llm-training.md) 和 [ByteRobust](../papers/sosp-2025/robust-llm-training-infrastructure-at-bytedance.md) 都从同一处直觉切入——一个 10K-GPU 训练任务的故障信号，往往先以一种异常的集合通信依赖形态冒头。[SimAI](../papers/nsdi-2025/simai-unifying-architecture-design-and-performance-tuning-for-large-scale-large-language.md) 则反向行事，复用真实训练框架与 NCCL，在包粒度上模拟 LLM 训练，与真机对齐率达到 98.1%——一件能对着「尚未建成」的拓扑提前推理的工具。

### 对着生产场景开的那几扇减压阀

最后还有两篇偏向补救角度的论文。[OptiReduce](../papers/nsdi-2025/optireduce-resilient-and-tail-optimal-allreduce-for-distributed-deep-learning-in-the-cloud.md)（NSDI '25）处理的是公有云里拿不到专用 backend 时的尾时延 AllReduce；Google 那篇 [热点感知调度](../papers/nsdi-2025/preventing-network-bottlenecks-accelerating-datacenter-services-with-hotspot-aware.md)（NSDI '25）则更朴素——只把任务和存储往「凉」的机架放，就把持续热 ToR 砍掉 90%、Colossus 的 p95 网络时延降低 50–80%。两篇都在提醒：绝大多数负载其实还生活在「一张网、一套拓扑」的那个世界里，而即便在那里，「拓扑感知的调度」仍然是一根尚未真正拧紧的杠杆。

## 反方证据

「三张网」这条主张并非毫无异议。AWS 的 [SRD](https://aws.amazon.com/blogs/hpc/in-the-search-for-performance-theres-more-than-one-way-to-build-a-network/) 是最响亮的反面例子：一张普通 Ethernet fabric、把流量以自定义传输层洒到 64 条路径上，而不是另起一张 InfiniBand 或 RoCE backend。如果 SRD 在 GB200 级别的集群尺度上也能撑起集合通信，「backend 必须独立」这个前提就会退化为「一张 fabric，一套更聪明的传输层」。

Ultra Ethernet 是第二股压力。[UET](https://arxiv.org/html/2508.08906v1) 的明确目标就是让 backend 和通用 Ethernet 重新变成同一张网。如果它真的走通了，frontend / backend 之间的分界就从物理墙落成一条流量类别的边界。

还有一股更安静的反推来自 scale-up 那一侧。NVLink 域从 8 长到 72，再规划到 576。每次长大，都会蚕食原本归属于 scale-out backend 的地盘：一旦整个模型能塞进 NVLink 域，backend 只需要跑数据并行副本，对拓扑的要求就放松了很多。「scale-up 吞掉 scale-out」是一种可信的未来——唯一的反证是，模型规模的那条曲线也在长。

这三条里没有哪一条强到足以把 2026 年的「三张网」图景整体推翻。但每一条都是正在进行的争论，今天选拓扑的系统架构师应当默认：边界还会再挪动。

## 这意味着什么

对平台建设者来说，现在已经不能「挑一张网」。你一次要挑四张，而且要在 NIC 和交换机上设计好它们怎么分摊资源——哪张 NIC 坐在哪一层，哪些交换机允许在什么 pause 机制下死锁，哪些流归哪一套传输层。NVIDIA 那套 SuperPOD 参考架构之所以有价值，正是因为它把这些选择以连接器的粒度明文规定下来了。

对做研究的人来说，真正有意思的拓扑工作已经上移了一层。图与调度的共同综合、可编程光学、运行时可调的路径选择，都在问同一个问题——如果拓扑是个变量，那这个变量的控制回路长什么样？关于 Clos 还是 fat-tree 的老争论，对 CPU 集群是真的结束了；对 AI 集群则正在被一场关于「可重构性」的新辩论取代。

对整个领域来说，未来两年会决定工业界是保留四张网，还是把它们合并回一张。Ultra Ethernet 是响度最大的再收敛赌注；NVLink 域的膨胀是一条安静的再收敛线。无论谁胜出，2028 年的「数据中心网络拓扑」都不会再长成 2015 年 Jupiter 那张图——它要么是四层终于协商出一套共同传输层，要么是一层终于把所有事都统一了。
